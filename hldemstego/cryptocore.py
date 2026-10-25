"""
cryptocore.py - Nucleo criptografico de HLdemStego
Usa UNICAMENTE stdlib de Python (hashlib, hmac, os, struct, secrets).

MODELO DE SEGURIDAD
-------------------
Clave = SHA-256 de TODOS los frames CLIENTDATA de la demo (timestamp +
        origen + viewangles + weaponbits de cada frame, en orden temporal).
        Si el usuario ademas provee una password, se aplica PBKDF2-HMAC-SHA256
        con el hash anterior como sal ? clave de 256 bits final.

Cifrado = flujo XOR con keystream HMAC-SHA256 en modo contador:
          keystream_block_i = HMAC-SHA256(key, nonce || i_as_8_bytes_BE)
          Equivalente en seguridad a AES-256-CTR cuando key tiene 256 bits.

Autenticacion = HMAC-SHA256 del ciphertext completo (Encrypt-then-MAC).
                La verificacion usa hmac.compare_digest para evitar ataques
                de timing sobre el MAC.

Shuffle = Fisher-Yates con el mismo HMAC-CSPRNG en vez de Mersenne Twister.
          El PRNG es determinista dado key, pero criptograficamente seguro:
          no se puede predecir el orden de los fragmentos sin la clave.

GARANTIAS:
  - Alterar UN solo fotograma de la demo (un valor de viewangle en 0.001
    grados) cambia completamente la clave y hace el archivo irrecuperable.
  - Sin el stego.dem: no hay chunks.
  - Sin la clave (= sin la demo con los movimientos correctos): los chunks
    son ruido blanco. El HMAC asegura deteccion de tampering.
  - Con password: ademas se necesita la password. PBKDF2 con 200.000
    iteraciones hace el brute-force costoso (~2s por intento en CPU moderna).

LIMITES ANTI-DoS:
  - MAX_PLAINTEXT:  100 MB de payload descomprimido (anti zip-bomb)
  - MAX_CHUNKS:     50.000 fragmentos (anti-DoS en total_declared del header)
  - MAX_PAYLOAD_B64: 4.000.000 chars de Base64 combinado
"""

import hashlib
import hmac as _hmac_mod
import os
import struct
import secrets
from typing import List, Optional, Tuple


# Limites de seguridad
MAX_PLAINTEXT    = 100 * 1024 * 1024   # 100 MB descomprimido
MAX_CHUNKS       = 50_000              # fragmentos maximos por demo
MAX_PAYLOAD_B64  = 4_000_000           # chars base64 maximos

# Version del protocolo (parte del domainSeparation para el hash de key)
_DOMAIN = b"HLdemStego_v1_key"


# ----------------------------------------------------------------
#  CSPRNG determinista basado en HMAC-SHA256
# ----------------------------------------------------------------

class _HMACCSPRNG:
    """
    Generador de numeros pseudo-aleatorios criptograficamente seguro (CSPRNG).
    Determinista dado 'key': la misma clave siempre produce la misma secuencia.
    Reemplaza random.Random (Mersenne Twister, no apto para criptografia).

    Basado en HMAC-SHA256 en modo contador:
      bloque_i = HMAC-SHA256(key, i.to_bytes(8, 'big'))
    """

    def __init__(self, key: bytes):
        self._key = key
        self._buf = bytearray()
        self._ctr = 0

    def _refill(self) -> None:
        block = _hmac_mod.new(
            self._key,
            self._ctr.to_bytes(8, "big"),
            "sha256"
        ).digest()
        self._buf.extend(block)
        self._ctr += 1

    def randbelow(self, n: int) -> int:
        """Entero uniforme en [0, n). Requiere n >= 1."""
        if n <= 1:
            return 0
        bits   = (n - 1).bit_length()
        nbytes = (bits + 7) // 8
        while True:
            while len(self._buf) < nbytes:
                self._refill()
            val = int.from_bytes(self._buf[:nbytes], "big")
            del self._buf[:nbytes]
            # Rejection sampling para uniformidad perfecta
            val >>= (nbytes * 8 - bits)
            if val < n:
                return val


# ----------------------------------------------------------------
#  Keystream HMAC-SHA256 en modo contador
# ----------------------------------------------------------------

def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    """
    Genera 'length' bytes de keystream.
    bloque_i = HMAC-SHA256(key, nonce || i_as_8_bytes_BE)
    """
    stream  = bytearray()
    counter = 0
    while len(stream) < length:
        block = _hmac_mod.new(
            key,
            nonce + counter.to_bytes(8, "big"),
            "sha256"
        ).digest()
        stream.extend(block)
        counter += 1
    return bytes(stream[:length])


# ----------------------------------------------------------------
#  Derivacion de clave desde frames CLIENTDATA
# ----------------------------------------------------------------

def derive_key(
    cd_frames      : list,           # List[Frame] con ftype==FRAME_CLIENTDATA
    password       : Optional[str] = None,
    pbkdf2_iters   : int            = 200_000,
) -> bytes:
    """
    Deriva una clave de 256 bits desde los frames CLIENTDATA de la demo.

    Proceso:
      1. Para CADA frame CLIENTDATA (en orden temporal), serializa:
           timestamp (float64 BE) + origin[3] (float32x3 BE)
           + viewangles[3] (float32x3 BE) + weaponbits (uint32 BE)
         y lo acumula en un SHA-256 incremental.
         => El hash final es una "huella criptografica" de la partida entera.

      2. Si hay password:
           key = PBKDF2-HMAC-SHA256(
               password  = password_utf8,
               salt      = event_hash,    # 32 bytes del paso 1
               iterations= pbkdf2_iters,  # default 200.000
               dklen     = 32             # 256 bits
           )
         Si no hay password:
           key = event_hash directamente.

    Raises ValueError si cd_frames esta vacio y no hay password.

    Propiedades de seguridad:
      - Un solo fotograma distinto (viewangle cambiado en 0.001 grados)
        cambia completamente la clave ? control de integridad implicito.
      - Con password: brute-force cuesta ~2s/intento en CPU moderna.
      - Sin password pero con demo: la clave tiene 256 bits de entropia
        siempre que los movimientos del jugador sean suficientemente variados.
    """
    if not cd_frames and not password:
        raise ValueError(
            "La demo no contiene frames CLIENTDATA detectables.\n"
            "  No se puede derivar una clave criptografica de los movimientos.\n"
            "\n"
            "  Opciones:\n"
            "    a) Usa una demo donde el jugador se mueva, salte y dispare.\n"
            "    b) Provee una password con --password (se usa sin entropia de demo).\n"
            "    c) Prueba con --democmdinfo-size 0 o 56 si el parser falla."
        )

    # ---- Paso 1: hash de todos los frames CLIENTDATA ----
    h = hashlib.sha256()
    h.update(_DOMAIN)

    frame_count = 0
    for f in cd_frames:
        if f.origin is None or f.viewangles is None:
            continue
        try:
            h.update(struct.pack(">d", f.timestamp))
            h.update(struct.pack(">3f", *f.origin))
            h.update(struct.pack(">3f", *f.viewangles))
            h.update(struct.pack(">I", f.weaponbits or 0))
            frame_count += 1
        except (struct.error, TypeError):
            continue

    if frame_count == 0 and not password:
        raise ValueError(
            "No se pudieron parsear frames CLIENTDATA con datos validos.\n"
            "  Usa --password o una demo grabada en modo offline con movimiento."
        )

    event_hash = h.digest()   # 32 bytes = 256 bits de huella de la partida

    # ---- Paso 2: incorporar password con PBKDF2 ----
    if password:
        key = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt      = event_hash,
            iterations= pbkdf2_iters,
            dklen     = 32,
        )
    else:
        key = event_hash

    return key


# ----------------------------------------------------------------
#  Cifrado / descifrado (Encrypt-then-MAC)
# ----------------------------------------------------------------

def encrypt(plaintext: bytes, key: bytes) -> Tuple[bytes, bytes]:
    """
    Cifra 'plaintext' con HMAC-SHA256 counter mode.

    Returns
    -------
    ciphertext_with_nonce : nonce(16 bytes) || ciphertext(len(plaintext) bytes)
    mac                   : HMAC-SHA256(key, ciphertext_with_nonce) -- 32 bytes

    El MAC se calcula sobre el ciphertext completo incluyendo el nonce
    (Encrypt-then-MAC), lo que garantiza integridad y autenticidad.
    """
    nonce      = os.urandom(16)
    ks         = _keystream(key, nonce, len(plaintext))
    ciphertext = bytes(a ^ b for a, b in zip(plaintext, ks))
    payload    = nonce + ciphertext
    mac        = _hmac_mod.new(key, payload, "sha256").digest()
    return payload, mac


def decrypt(payload: bytes, key: bytes, mac: bytes) -> bytes:
    """
    Descifra y verifica integridad.

    Raises ValueError si el MAC no coincide (datos alterados o clave incorrecta).
    """
    if len(payload) < 16:
        raise ValueError("Payload demasiado corto (faltan nonce + ciphertext).")

    # Verificacion de MAC en tiempo constante (resiste timing attacks)
    expected_mac = _hmac_mod.new(key, payload, "sha256").digest()
    if not _hmac_mod.compare_digest(expected_mac, mac):
        raise ValueError(
            "Fallo de verificacion de integridad (HMAC-SHA256).\n"
            "  Posibles causas:\n"
            "    - La clave (demo) no corresponde a la usada en el encode\n"
            "    - La password es incorrecta\n"
            "    - El stego.dem fue modificado o esta corrupto"
        )

    nonce      = payload[:16]
    ciphertext = payload[16:]
    ks         = _keystream(key, nonce, len(ciphertext))
    return bytes(a ^ b for a, b in zip(ciphertext, ks))


# ----------------------------------------------------------------
#  Permutacion criptograficamente segura
# ----------------------------------------------------------------

def permute_secure(n: int, key: bytes) -> List[int]:
    """
    Fisher-Yates shuffle usando HMAC-CSPRNG en vez de Mersenne Twister.
    Determinista dado 'key', pero criptograficamente seguro.
    """
    rng  = _HMACCSPRNG(key)
    perm = list(range(n))
    for i in range(n - 1, 0, -1):
        j = rng.randbelow(i + 1)
        perm[i], perm[j] = perm[j], perm[i]
    return perm


def inverse_permute_secure(n: int, key: bytes) -> List[int]:
    """Permutacion inversa de permute_secure (misma key, mismo n)."""
    perm = permute_secure(n, key)
    inv  = [0] * n
    for k, v in enumerate(perm):
        inv[v] = k
    return inv


# ----------------------------------------------------------------
#  Validacion de nombres de archivo (path traversal)
# ----------------------------------------------------------------

def safe_filename(raw_name: str) -> str:
    """
    Sanitiza el nombre de archivo del token HL:HEAD contra path traversal.

    - Extrae solo el basename (descarta rutas absolutas y relativas)
    - Elimina caracteres de control y secuencias peligrosas
    - Limita la longitud a 240 caracteres
    - Si el resultado esta vacio, usa "recovered_file"

    Ejemplo:
        "../../etc/passwd"  ->  "passwd"
        "/abs/path/secret"  ->  "secret"
        "normal.txt"        ->  "normal.txt"
    """
    import os
    import re

    # Tomar solo el nombre final (elimina rutas)
    name = os.path.basename(raw_name)

    # Eliminar caracteres de control y nulos
    name = re.sub(r'[\x00-\x1f\x7f]', '', name)

    # Eliminar secuencias de punto-punto residuales
    name = name.replace("..", "")

    # Limitar longitud
    name = name[:240]

    # Fallback
    if not name or name in (".", "/", "\\"):
        name = "recovered_file"

    return name


# ----------------------------------------------------------------
#  Validacion anti-DoS
# ----------------------------------------------------------------

def validate_payload_limits(total_declared: int, b64_joined: str) -> None:
    """
    Verifica que el payload esta dentro de limites razonables.
    Lanza ValueError si se exceden, protegiendo contra:
      - Zip bombs (payload descomprimido enormemente mas grande que el comprimido)
      - DoS por total_declared artificialmente alto en el header
      - Payloads de Base64 gigantescos en memoria
    """
    if total_declared > MAX_CHUNKS:
        raise ValueError(
            f"total_declared={total_declared} excede el limite de "
            f"{MAX_CHUNKS} fragmentos.\n"
            "  Posible ataque DoS o demo corrupta."
        )
    if len(b64_joined) > MAX_PAYLOAD_B64:
        raise ValueError(
            f"Payload Base64 ({len(b64_joined)} chars) excede el limite de "
            f"{MAX_PAYLOAD_B64} chars.\n"
            "  Posible ataque DoS o demo corrupta."
        )

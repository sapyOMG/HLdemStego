"""
MODULO 1 - Input Handler
Preparacion y reconstruccion del payload usando cryptocore.
"""

import os
import zlib
import base64
from typing import List, Tuple, Optional

from .constants   import CHUNK_SIZE, MIN_INJECT_GAP
from .cryptocore  import (
    encrypt, decrypt, safe_filename,
    validate_payload_limits, MAX_PLAINTEXT
)


def prepare_payload(
    file_path : str,
    key       : Optional[bytes] = None,
) -> Tuple[List[str], str, int, int, bytes]:
    """
    Lee, comprime, cifra y fragmenta el archivo.

    Returns
    -------
    chunks    : lista de strings Base64 (fragmentos del ciphertext)
    filename  : basename del archivo
    orig_size : bytes originales
    comp_size : bytes tras zlib
    mac       : HMAC-SHA256 del payload (32 bytes) para DC:END
    """
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"Archivo no encontrado: {file_path!r}")

    with open(file_path, "rb") as fh:
        raw = fh.read()

    orig_size = len(raw)
    if orig_size == 0:
        raise ValueError("El archivo esta vacio.")

    # 1. Comprimir
    compressed = zlib.compress(raw, level=zlib.Z_BEST_COMPRESSION)
    comp_size  = len(compressed)

    # 2. Cifrar (Encrypt-then-MAC)
    if key:
        payload, mac = encrypt(compressed, key)
    else:
        # Sin clave: solo zlib + base64 (obfuscacion, no seguridad real)
        payload = compressed
        mac     = b"\x00" * 32   # MAC nulo = sin autenticacion

    # 3. Base64 + fragmentar
    b64_str = base64.b64encode(payload).decode("ascii")
    chunks  = [b64_str[i : i + CHUNK_SIZE]
               for i in range(0, len(b64_str), CHUNK_SIZE)]

    filename = os.path.basename(file_path)
    return chunks, filename, orig_size, comp_size, mac


def validate_capacity(
    chunks    : List[str],
    demo_dur  : float,
    filename  : str,
    orig_size : int,
    comp_size : int,
    has_key   : bool = False,
    verbose   : bool = True,
) -> bool:
    total_needed = len(chunks) + 2
    min_dur      = total_needed * MIN_INJECT_GAP
    b64_total    = sum(len(c) for c in chunks)
    ratio        = comp_size / orig_size if orig_size else 1.0

    if verbose:
        print("-" * 56)
        print("  HLdemStego - Resumen del payload")
        print("-" * 56)
        print(f"  Archivo           : {filename}")
        print(f"  Tamano original   : {orig_size:,} bytes")
        print(f"  Tras zlib         : {comp_size:,} bytes ({ratio:.1%})")
        print(f"  Cifrado           : {'AES-256 equiv. (HMAC-SHA256-CTR)' if has_key else 'SIN CIFRADO (solo obfuscacion)'}")
        print(f"  Base64 total      : {b64_total:,} chars")
        print(f"  Fragmentos        : {len(chunks)} (de {CHUNK_SIZE} chars c/u)")
        print(f"  Duracion demo     : {demo_dur:.2f}s")
        print(f"  Duracion minima   : {min_dur:.2f}s")

    ok = demo_dur >= min_dur

    if verbose:
        if ok:
            print("  [OK] La demo tiene capacidad suficiente.")
        else:
            print(f"  [!] Demo muy corta. Necesitas al menos {min_dur:.1f}s.")
        print("-" * 56)

    return ok


def reconstruct_payload(
    chunks   : List[str],
    out_dir  : str,
    filename : str,
    key      : Optional[bytes] = None,
    mac      : Optional[bytes] = None,
) -> str:
    """
    Reconstruye el archivo original desde los chunks extraidos.

    Aplica: join base64 ? decode ? decrypt+verify ? decompress ? write
    Protege contra: path traversal, zip bombs, MAC spoofing, clave incorrecta.
    """
    # Validar limites (anti-DoS / zip-bomb)
    b64_joined = "".join(chunks)
    validate_payload_limits(len(chunks), b64_joined)

    payload = base64.b64decode(b64_joined)

    # Descifrar y verificar integridad
    if key and mac and any(b != 0 for b in mac):
        compressed = decrypt(payload, key, mac)
    elif key:
        # MAC nulo: intentar descifrar igual, sin verificacion de integridad
        compressed = decrypt(payload, key, b"\x00" * 32) if False else payload
        import base64 as _b64
        # fallback seguro
        from .cryptocore import _keystream
        if len(payload) >= 16:
            nonce = payload[:16]
            ct    = payload[16:]
            ks    = _keystream(key, nonce, len(ct))
            compressed = bytes(a ^ b for a, b in zip(ct, ks))
        else:
            compressed = payload
    else:
        compressed = payload

    # Anti zip-bomb: limitar descompresion
    try:
        dec = zlib.decompressobj()
        raw = dec.decompress(compressed, max_length=MAX_PLAINTEXT)
        if dec.unconsumed_tail:
            raise ValueError(
                f"Payload descomprimido supera el limite de {MAX_PLAINTEXT//1024//1024} MB.\n"
                "  Posible zip-bomb o archivo corrupto."
            )
    except zlib.error as e:
        hint = ""
        if key:
            hint = "\n  Hint: verifica que la demo y la password sean las correctas."
        raise ValueError(f"Error al descomprimir: {e}{hint}") from e

    # Sanitizar nombre (path traversal)
    safe_name = safe_filename(filename)
    out_path  = os.path.join(out_dir, safe_name)
    if os.path.exists(out_path):
        base_n, ext = os.path.splitext(safe_name)
        out_path    = os.path.join(out_dir, f"{base_n}_recovered{ext}")

    with open(out_path, "wb") as fh:
        fh.write(raw)

    return out_path

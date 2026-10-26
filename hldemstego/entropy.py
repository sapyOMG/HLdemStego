"""
MODULO 2 - Extraccion de entropia y derivacion de clave
=========================================================
Recopila los datos de todos los frames CLIENTDATA de la demo para
construir la clave criptografica. No se limita a "eventos" discretos
(saltos/disparos) sino que usa CADA fotograma del jugador:

  timestamp + posicion XYZ + angulos (pitch/yaw/roll) + weaponbits

Esto da entropia maxima y vincula el archivo cifrado a esa partida
especifica de forma indisoluble.
"""

from typing import List, Optional

from .constants  import FRAME_CLIENTDATA, FIRE_BITS_MASK, JUMP_Z_DELTA
from .dem_io     import Frame, scan_clientdata_any
from .cryptocore import derive_key, permute_secure, inverse_permute_secure


# ----------------------------------------------------------------
#  Recoleccion de frames CLIENTDATA (entropia bruta)
# ----------------------------------------------------------------

def collect_cd_frames(frames: List[Frame]) -> List[Frame]:
    """
    Filtra y devuelve los frames CLIENTDATA con datos validos.
    Estos son los que se usan para derivar la clave criptografica.
    """
    return [
        f for f in frames
        if f.ftype == FRAME_CLIENTDATA
        and f.origin     is not None
        and f.viewangles is not None
    ]


def report_entropy(cd_frames: List[Frame]) -> None:
    """
    Imprime un resumen de la entropia disponible en la demo.
    """
    if not cd_frames:
        print("  [!] ADVERTENCIA: no se encontraron frames CLIENTDATA.")
        print("      La clave no podra derivarse de los movimientos del jugador.")
        return

    ts_first = cd_frames[0].timestamp
    ts_last  = cd_frames[-1].timestamp
    duration = ts_last - ts_first

    # Contar eventos discretos para informacion
    jumps = fires = 0
    prev_z = prev_fire = None
    for f in cd_frames:
        z  = f.origin[2]
        wb = f.weaponbits or 0
        if prev_z is not None and (z - prev_z) > JUMP_Z_DELTA:
            jumps += 1
        firing = bool(wb & FIRE_BITS_MASK)
        if firing and prev_fire is False:
            fires += 1
        prev_z    = z
        prev_fire = firing

    print(f"  Frames CLIENTDATA  : {len(cd_frames)}")
    print(f"  Rango temporal     : {ts_first:.2f}s - {ts_last:.2f}s ({duration:.1f}s)")
    print(f"  Saltos detectados  : {jumps}")
    print(f"  Disparos detectados: {fires}")
    print(f"  Entropia estimada  : {len(cd_frames) * 28 * 8} bits brutos "
          f"(~{len(cd_frames) * 28} bytes de datos de movimiento)")


# ----------------------------------------------------------------
#  API publica: derivar clave y permutar
# ----------------------------------------------------------------

def build_key(
    cd_frames : List[Frame],
    password  : Optional[str] = None,
) -> bytes:
    """
    Deriva la clave de 256 bits desde los frames CLIENTDATA + password opcional.
    Delega a cryptocore.derive_key.

    Raises ValueError si no hay frames Y no hay password.
    """
    return derive_key(cd_frames, password=password)


def shuffle_chunks(chunks: List[str], key: bytes):
    """
    Baraja chunks usando Fisher-Yates con HMAC-CSPRNG (no Mersenne Twister).
    Devuelve (shuffled, perm).
    """
    n    = len(chunks)
    perm = permute_secure(n, key)
    shuffled = [chunks[perm[i]] for i in range(n)]
    return shuffled, perm


def unshuffle_chunks(shuffled: List[str], key: bytes) -> List[str]:
    """
    Revierte el shuffle. Requiere la misma clave usada en shuffle_chunks.
    """
    n   = len(shuffled)
    inv = inverse_permute_secure(n, key)
    return [shuffled[inv[i]] for i in range(n)]

"""
MODULO 3 - Inyeccion / Extraccion esteganografica
===================================================
Protocolo de tokens DC:*:

  HL:HEAD:<filename>:<N_chunks>
  DC:<idx_zero_padded>:<chunk_b64>
  ...
  HL:END:<mac_base64>    (MAC de 32 bytes en base64, 44 chars)

El MAC en HL:END permite verificar integridad antes de descomprimir.
Si no hay cifrado, el MAC es la cadena "0" * 44 (44 ceros base64 = 32 nulos).
"""

import base64
from typing import List, Tuple, Optional

from .constants import MIN_INJECT_GAP, DC_HEAD_TOKEN, DC_END_TOKEN, DC_DATA_PREFIX
from .dem_io    import Frame, make_stringcmd_frame
from .cryptocore import validate_payload_limits


_MAC_ZERO_B64 = base64.b64encode(b"\x00" * 32).decode("ascii")


def _linspace(start: float, stop: float, n: int) -> List[float]:
    if n <= 1:
        return [start]
    step = (stop - start) / (n - 1)
    return [start + i * step for i in range(n)]


# ----------------------------------------------------------------
#  Crear frames de inyeccion
# ----------------------------------------------------------------

def make_injection_frames(
    shuffled_chunks : List[str],
    filename        : str,
    t_start         : float,
    t_end           : float,
    mac             : bytes = b"",
) -> List[Frame]:
    """
    Crea los frames STRINGCMD 'echo DC:*' para inyectar en la demo.
    Devuelve SOLO los frames nuevos (surgical_save_dem los inserta).

    El MAC (HMAC-SHA256 del payload cifrado) se embebe en HL:END para
    que el decoder pueda verificar integridad antes de descomprimir.
    """
    mac_b64 = base64.b64encode(mac).decode("ascii") if mac else _MAC_ZERO_B64

    n_total    = len(shuffled_chunks) + 2
    timestamps = _linspace(t_start, t_end, n_total)
    pad        = len(str(max(len(shuffled_chunks) - 1, 0)))

    def _frame(ts: float, text: str) -> Frame:
        import math
        ts = max(0.0, ts) if math.isfinite(ts) else 0.0
        return make_stringcmd_frame(ts, f"echo {text}")

    frames: List[Frame] = []

    # HEAD
    frames.append(_frame(timestamps[0], f"{DC_HEAD_TOKEN}:{filename}:{len(shuffled_chunks)}"))

    # Datos
    for i, chunk in enumerate(shuffled_chunks):
        frames.append(_frame(timestamps[i + 1], f"{DC_DATA_PREFIX}{str(i).zfill(pad)}:{chunk}"))

    # END con MAC
    frames.append(_frame(timestamps[-1], f"{DC_END_TOKEN}:{mac_b64}"))

    return frames


# ----------------------------------------------------------------
#  Parsear tokens DC:* extraidos
# ----------------------------------------------------------------

def parse_dc_commands(cmds: List[str]) -> Tuple[str, int, List[str], bytes]:
    """
    Recibe la lista de strings DC:* normalizados y reconstruye el payload.

    Returns
    -------
    filename       : nombre del archivo original (sanitizado externamente)
    total_declared : total de chunks declarado en HEAD
    shuffled       : chunks en orden barajado
    mac            : 32 bytes del HMAC-SHA256 (de HL:END) o 32 nulos
    """
    head_found     = False
    end_found      = False
    filename       = ""
    total_declared = 0
    data_dict      = {}
    mac            = b"\x00" * 32

    for raw_cmd in cmds:
        cmd = raw_cmd.strip()
        # Normalizar prefijos de comando
        for prefix in ("echo ", "say "):
            if cmd.startswith(prefix):
                cmd = cmd[len(prefix):]
                break

        # HEAD
        if cmd.startswith(DC_HEAD_TOKEN + ":"):
            parts = cmd[len(DC_HEAD_TOKEN) + 1:].split(":", 1)
            if len(parts) == 2:
                filename = parts[0]
                try:
                    total_declared = int(parts[1])
                except ValueError:
                    pass
            head_found = True
            continue

        # END (con MAC opcional)
        if cmd.startswith(DC_END_TOKEN):
            end_found = True
            rest = cmd[len(DC_END_TOKEN):]
            if rest.startswith(":") and len(rest) > 1:
                try:
                    mac_candidate = base64.b64decode(rest[1:])
                    if len(mac_candidate) == 32 and any(b != 0 for b in mac_candidate):
                        mac = mac_candidate
                except Exception:
                    pass
            continue

        # DATA
        if head_found and not end_found and cmd.startswith(DC_DATA_PREFIX):
            rest  = cmd[len(DC_DATA_PREFIX):]
            colon = rest.find(":")
            if colon != -1:
                try:
                    idx = int(rest[:colon])
                    data_dict[idx] = rest[colon + 1:]
                except ValueError:
                    pass

    if not head_found:
        raise ValueError(
            "No se encontro HL:HEAD en la demo.\n"
            "  La demo no fue procesada por HLdemStego, o el archivo esta truncado."
        )

    if not end_found:
        print("[EXTRACT WARN] No se encontro HL:END. La demo puede estar incompleta.")

    if not data_dict:
        raise ValueError("No se encontraron fragmentos DC:* de datos en la demo.")

    # Validar limites anti-DoS
    validate_payload_limits(total_declared, "".join(data_dict.values()))

    missing = [i for i in range(total_declared) if i not in data_dict]
    if missing:
        print(f"[EXTRACT WARN] Faltan {len(missing)} fragmento(s): {missing[:10]}")

    max_idx  = max(data_dict.keys())
    shuffled = [data_dict.get(i, "") for i in range(max_idx + 1)]
    return filename, total_declared, shuffled, mac

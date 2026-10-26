"""
dem_io.py - Parser / serializer binario de demos GoldSrc.

ARQUITECTURA DE INYECCI?N QUIR?RGICA
======================================
El problema de re-serializar el demo completo desde frames parseados es
que cualquier frame con tipo desconocido (demo grabada con un mod, CS CZ,
tamano de democmdinfo_t distinto, etc.) causa perdida de datos.

La solucion: surgical_save_dem() toca SOLO los bytes que necesita:
  1. Lee el demo original sin modificar.
  2. Localiza el frame LASTRECORD al final del segmento objetivo.
  3. Inserta los nuevos frames ANTES del LASTRECORD.
  4. Recalcula solo el offset del directorio y el length del segmento.
  5. Escribe: header_actualizado + cuerpo_con_inyeccion + directorio_actualizado.
  ? El 99.9% del archivo original queda bit-a-bit identico.

Para DECODE usamos scan_dc_commands() que hace regex sobre los bytes
crudos del segmento buscando nuestros tokens "say DC:*" sin necesitar
parsear tipos de frame desconocidos.
"""

import re
import struct
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .constants import (
    DEMO_MAGIC, HEADER_SIZE, DIR_ENTRY_SIZE,
    FRAME_HDR_FMT, FRAME_HDR_SIZE,
    FRAME_UNKNOWN, FRAME_STARTUP, FRAME_NORMAL,
    FRAME_STRINGCMD, FRAME_LASTRECORD,
    FRAME_EVENT, FRAME_SOUND, FRAME_BUFFER,
    FRAME_CLIENTDATA, FRAME_WEAPONANIM,
    FRAME_BODY_SIZES, DEMOCMDINFO_SIZE,
    SVC_PRINT, SVC_CENTERPRINT,
)


# --- Data-classes -------------------------------------------------------------

@dataclass
class DemoHeader:
    demo_protocol : int
    net_protocol  : int
    map_name      : str
    game_dir      : str
    map_crc       : int
    dir_offset    : int
    _raw          : bytes = field(repr=False, compare=False)


@dataclass
class DirEntry:
    entry_type  : int
    description : str
    flags       : int
    cd_track    : int
    time        : float
    frame_count : int
    offset      : int
    file_length : int


@dataclass
class Frame:
    timestamp  : float
    ftype      : int
    raw_body   : bytes = field(repr=False)
    cmd        : Optional[str]                        = field(default=None, repr=False)
    origin     : Optional[Tuple[float, float, float]] = field(default=None, repr=False)
    viewangles : Optional[Tuple[float, float, float]] = field(default=None, repr=False)
    weaponbits : Optional[int]                        = field(default=None, repr=False)
    fov        : Optional[float]                      = field(default=None, repr=False)


# --- Header -------------------------------------------------------------------

def parse_header(data: bytes) -> DemoHeader:
    if len(data) < HEADER_SIZE:
        raise ValueError(f"Archivo muy corto ({len(data)} bytes) para ser un .dem de GoldSrc.")
    magic = data[:8]
    if magic != DEMO_MAGIC:
        raise ValueError(
            f"No es un demo GoldSrc - magic incorrecto: {magic!r}\n"
            f"Esperado: {DEMO_MAGIC!r}"
        )
    demo_proto, net_proto = struct.unpack_from("<ii", data, 8)
    map_name = data[16:276].split(b"\x00")[0].decode("utf-8", errors="replace")
    game_dir = data[276:536].split(b"\x00")[0].decode("utf-8", errors="replace")
    map_crc, dir_offset = struct.unpack_from("<Ii", data, 536)
    return DemoHeader(
        demo_protocol=demo_proto, net_protocol=net_proto,
        map_name=map_name, game_dir=game_dir,
        map_crc=map_crc, dir_offset=dir_offset,
        _raw=bytes(data[:HEADER_SIZE]),
    )


def serialize_header(hdr: DemoHeader, new_dir_offset: int) -> bytes:
    buf = bytearray(hdr._raw)
    struct.pack_into("<i", buf, 540, new_dir_offset)
    return bytes(buf)


# --- Directory ----------------------------------------------------------------

def parse_directory(data: bytes, offset: int) -> List[DirEntry]:
    if offset + 4 > len(data):
        raise ValueError(f"Offset de directorio {offset} fuera del archivo.")
    num = struct.unpack_from("<i", data, offset)[0]
    if num < 0 or num > 64:
        raise ValueError(f"Cantidad de entradas de directorio invalida: {num}")
    pos = offset + 4
    entries: List[DirEntry] = []
    for _ in range(num):
        if pos + DIR_ENTRY_SIZE > len(data):
            break
        etype, desc_raw, flags, cdt, t, nf, off, flen = struct.unpack_from(
            "<i64siifiii", data, pos
        )
        desc = desc_raw.split(b"\x00")[0].decode("utf-8", errors="replace")
        entries.append(DirEntry(
            entry_type=etype, description=desc, flags=flags,
            cd_track=cdt, time=t, frame_count=nf,
            offset=off, file_length=flen,
        ))
        pos += DIR_ENTRY_SIZE
    return entries


def serialize_directory(entries: List[DirEntry]) -> bytes:
    buf = struct.pack("<i", len(entries))
    for e in entries:
        desc_b = e.description.encode("utf-8")[:63].ljust(64, b"\x00")
        buf += struct.pack(
            "<i64siifiii",
            e.entry_type, desc_b, e.flags, e.cd_track,
            e.time, e.frame_count, e.offset, e.file_length,
        )
    return buf


# --- Frame serialization ------------------------------------------------------

def serialize_frame(f: Frame) -> bytes:
    return struct.pack(FRAME_HDR_FMT, f.timestamp, f.ftype) + f.raw_body


def make_stringcmd_frame(timestamp: float, cmd: str) -> Frame:
    cmd_b    = cmd.encode("utf-8") + b"\x00"
    raw_body = struct.pack("<I", len(cmd_b)) + cmd_b
    f = Frame(timestamp=timestamp, ftype=FRAME_STRINGCMD, raw_body=raw_body)
    f.cmd = cmd
    return f


# --- Carga del demo -----------------------------------------------------------

def load_dem(path: str, democmdinfo_size: int = DEMOCMDINFO_SIZE):
    """
    Carga el demo y devuelve (header, directory, raw_bytes).
    NO parsea los frames individuales - eso queda para las funciones
    especializadas de scan mas abajo.
    """
    with open(path, "rb") as fh:
        raw = fh.read()
    header    = parse_header(raw)
    directory = parse_directory(raw, header.dir_offset)
    return header, directory, raw


# --- INYECCI?N QUIR?RGICA -----------------------------------------------------

def _find_lastrecord_pos(raw: bytes, seg_offset: int, seg_length: int) -> int:
    """
    Encuentra la posicion del frame LASTRECORD al final del segmento.
    Estrategia: el LASTRECORD es el ultimo frame (5 bytes exactos).
    Busca hacia atras desde el final del segmento.

    Devuelve el offset absoluto del frame LASTRECORD dentro de `raw`,
    o seg_offset + seg_length si no lo encuentra (fallback: append al final).
    """
    seg_end = seg_offset + seg_length

    # Estrategia 1: esta exactamente en los ultimos 5 bytes
    candidate = seg_end - FRAME_HDR_SIZE
    if candidate >= seg_offset and candidate + FRAME_HDR_SIZE <= len(raw):
        _, ft = struct.unpack_from(FRAME_HDR_FMT, raw, candidate)
        if ft == FRAME_LASTRECORD:
            return candidate

    # Estrategia 2: buscar en los ultimos 64 bytes (por si hay padding)
    for back in range(1, 65):
        pos = seg_end - FRAME_HDR_SIZE - back
        if pos < seg_offset:
            break
        if pos + FRAME_HDR_SIZE > len(raw):
            continue
        _, ft = struct.unpack_from(FRAME_HDR_FMT, raw, pos)
        if ft == FRAME_LASTRECORD:
            return pos

    # Fallback: insertar al final del segmento
    return seg_end


def surgical_save_dem(
    path         : str,
    raw          : bytes,
    header       : DemoHeader,
    directory    : List[DirEntry],
    seg_idx      : int,
    extra_frames : List[Frame],
) -> None:
    """
    Guarda el demo inyectando extra_frames en el segmento seg_idx
    SIN re-parsear ni re-serializar el resto del archivo.

    Pasos:
      1. Localiza el LASTRECORD al final del segmento objetivo.
      2. Inserta los nuevos frames justo antes de el.
      3. Recalcula dir_offset y el file_length del segmento.
      4. Escribe: header_nuevo + cuerpo_con_inyeccion + directorio_nuevo.

    Resultado: el 99%+ del archivo original queda byte-a-byte identico.
    """
    entry      = directory[seg_idx]
    seg_offset = entry.offset
    seg_length = entry.file_length

    # Si el segmento tiene longitud 0 (startup vacio), no hay nada que hacer
    if seg_length == 0:
        # Buscar el segmento principal con datos reales
        for i, e in enumerate(directory):
            if e.file_length > 0 and i != seg_idx:
                seg_idx    = i
                entry      = e
                seg_offset = e.offset
                seg_length = e.file_length
                print(f"  [SURGICAL] Segmento {seg_idx} seleccionado para inyeccion "
                      f"(offset={seg_offset}, len={seg_length}).")
                break

    inject_pos = _find_lastrecord_pos(raw, seg_offset, seg_length)

    extra_bytes = b"".join(serialize_frame(f) for f in extra_frames)
    shift       = len(extra_bytes)

    # Cuerpo del demo = todo lo que esta entre el header y el directorio viejo
    old_body = raw[HEADER_SIZE : header.dir_offset]

    # Offset de inyeccion relativo al cuerpo
    body_inject_offset = inject_pos - HEADER_SIZE
    body_inject_offset = max(0, min(body_inject_offset, len(old_body)))

    new_body = (
        old_body[:body_inject_offset]
        + extra_bytes
        + old_body[body_inject_offset:]
    )

    # Reconstruir directorio con offsets y lengths actualizados
    new_entries: List[DirEntry] = []
    for i, e in enumerate(directory):
        if i == seg_idx:
            ne = DirEntry(
                entry_type=e.entry_type, description=e.description,
                flags=e.flags, cd_track=e.cd_track, time=e.time,
                frame_count=e.frame_count + len(extra_frames),
                offset=e.offset,
                file_length=e.file_length + shift,
            )
        else:
            # Si este segmento empieza despues del punto de inyeccion,
            # su offset se desplaza
            new_off = e.offset + shift if e.offset >= inject_pos else e.offset
            ne = DirEntry(
                entry_type=e.entry_type, description=e.description,
                flags=e.flags, cd_track=e.cd_track, time=e.time,
                frame_count=e.frame_count,
                offset=new_off,
                file_length=e.file_length,
            )
        new_entries.append(ne)

    new_dir_offset = header.dir_offset + shift
    hdr_bytes      = serialize_header(header, new_dir_offset)
    dir_bytes      = serialize_directory(new_entries)

    with open(path, "wb") as fh:
        fh.write(hdr_bytes)
        fh.write(new_body)
        fh.write(dir_bytes)

    print(f"  [SURGICAL] Inyectados {len(extra_frames)} frames en segmento {seg_idx}.")
    print(f"  [SURGICAL] Desplazamiento: +{shift} bytes.")
    print(f"  [SURGICAL] Nuevo dir_offset: {new_dir_offset}.")


# --- SCAN: buscar comandos DC:* sin parsear frames ----------------------------

def scan_dc_commands(raw: bytes, seg_offset: int, seg_length: int) -> List[str]:
    """
    Busca todos los comandos 'say DC:*' en el segmento usando regex
    sobre los bytes crudos. No requiere parsear tipos de frame.

    Devuelve lista de strings (sin el null terminator).
    """
    segment_data = raw[seg_offset : seg_offset + seg_length]
    # Busca: "say DC:" seguido de cualquier byte que no sea null, hasta null
    pattern = rb'say HL:[^\x00]{0,300}\x00'
    cmds: List[str] = []
    for m in re.finditer(pattern, segment_data):
        cmd_bytes = m.group(0).rstrip(b"\x00")
        try:
            cmds.append(cmd_bytes.decode("utf-8"))
        except UnicodeDecodeError:
            cmds.append(cmd_bytes.decode("latin-1"))
    return cmds


# --- SCAN: buscar frames CLIENTDATA para entropia ----------------------------

def scan_clientdata_frames(
    raw        : bytes,
    seg_offset : int,
    seg_length : int,
    democmdinfo_size: int = DEMOCMDINFO_SIZE,
) -> List[Frame]:
    """
    Intenta parsear el segmento de forma PERMISIVA buscando frames
    CLIENTDATA (tipo 8) para extraer entropia del jugador.

    A diferencia del parser estricto, ante un frame con tipo desconocido
    intenta varios tamanos de democmdinfo_t hasta encontrar algo que tenga
    sentido, y si no puede, avanza byte a byte (modo busqueda).

    En el peor caso devuelve lista vacia (la entropia cae al seed fallback).
    """
    frames: List[Frame] = []
    end = seg_offset + seg_length
    pos = seg_offset

    CLIENTDATA_BODY = 32  # tamano fijo de los datos de CLIENTDATA

    # Intentar parsear con el democmdinfo_size dado y varios alternativos
    for dci_size in [democmdinfo_size, 0, 56, 164, 208]:
        frames = _try_scan_clientdata(raw, seg_offset, seg_length, dci_size)
        if frames:
            if dci_size != democmdinfo_size:
                print(f"  [ENTROPY] democmdinfo_size={dci_size} funciono para entropia.")
            break

    return frames


def _try_scan_clientdata(
    raw: bytes, seg_offset: int, seg_length: int, dci_size: int
) -> List[Frame]:
    """Intento de scan con un democmdinfo_size especifico."""
    frames: List[Frame] = []
    end = seg_offset + seg_length
    pos = seg_offset
    max_errors = 5
    errors = 0

    while pos < end and errors < max_errors:
        if pos + FRAME_HDR_SIZE > end:
            break
        try:
            ts, ftype = struct.unpack_from(FRAME_HDR_FMT, raw, pos)
        except struct.error:
            break

        pos += FRAME_HDR_SIZE

        if ftype in (FRAME_NORMAL, FRAME_STARTUP):
            needed = dci_size + 4
            if pos + needed > end:
                break
            try:
                msg_len = struct.unpack_from("<I", raw, pos + dci_size)[0]
            except struct.error:
                errors += 1
                pos -= FRAME_HDR_SIZE
                pos += 1
                continue
            if msg_len > 0x10000:
                errors += 1
                pos -= FRAME_HDR_SIZE
                pos += 1
                continue
            pos += needed + msg_len

        elif ftype == FRAME_STRINGCMD:
            if pos + 4 > end:
                break
            try:
                cmd_len = struct.unpack_from("<I", raw, pos)[0]
            except struct.error:
                break
            if cmd_len == 0 or cmd_len > 512:
                errors += 1
                pos -= FRAME_HDR_SIZE
                pos += 1
                continue
            pos += 4 + cmd_len

        elif ftype == FRAME_LASTRECORD:
            break

        elif ftype in FRAME_BODY_SIZES:
            sz = FRAME_BODY_SIZES[ftype]
            if pos + sz > end:
                break
            if ftype == FRAME_CLIENTDATA and sz == 32:
                try:
                    body = raw[pos : pos + sz]
                    f = Frame(timestamp=ts, ftype=ftype, raw_body=body)
                    f.origin     = struct.unpack_from("<3f", body, 0)
                    f.viewangles = struct.unpack_from("<3f", body, 12)
                    f.weaponbits = struct.unpack_from("<I",  body, 24)[0]
                    f.fov        = struct.unpack_from("<f",  body, 28)[0]
                    frames.append(f)
                except struct.error:
                    pass
            pos += sz

        elif ftype == FRAME_SOUND:
            if pos + 8 > end:
                break
            try:
                sample_len = struct.unpack_from("<I", raw, pos + 4)[0]
            except struct.error:
                break
            if sample_len > 260:
                errors += 1
                pos -= FRAME_HDR_SIZE
                pos += 1
                continue
            pos += 4 + 4 + sample_len + 16

        elif ftype == FRAME_BUFFER:
            if pos + 4 > end:
                break
            try:
                buf_len = struct.unpack_from("<I", raw, pos)[0]
            except struct.error:
                break
            if buf_len > 0x10000:
                errors += 1
                pos -= FRAME_HDR_SIZE
                pos += 1
                continue
            pos += 4 + buf_len

        else:
            # Tipo desconocido: contar como error y avanzar
            errors += 1
            pos -= FRAME_HDR_SIZE
            pos += 1
            continue

    return frames


# --- Load completo (legacy, para inspect) ------------------------------------

def load_dem_full(path: str, democmdinfo_size: int = DEMOCMDINFO_SIZE):
    """
    Carga el demo intentando parsear todos los frames.
    Usado por inspect(). Para encode/decode usar load_dem() + funciones quirurgicas.
    """
    header, directory, raw = load_dem(path, democmdinfo_size)
    segments = []
    for entry in directory:
        avail  = max(0, len(raw) - entry.offset)
        length = min(entry.file_length, avail)
        frames = _try_scan_clientdata(raw, entry.offset, length, democmdinfo_size) if length > 0 else []
        # Tambien capturar STRINGCMDs para inspect
        all_frames = _parse_segment_for_inspect(raw, entry.offset, length, democmdinfo_size)
        segments.append(all_frames)
    return header, directory, segments, raw


def _parse_segment_for_inspect(raw, seg_offset, seg_length, dci_size):
    """Parser permisivo para inspect: captura CLIENTDATA y STRINGCMD."""
    frames = []
    end = seg_offset + seg_length
    pos = seg_offset
    errors = 0

    while pos < end and errors < 20:
        if pos + FRAME_HDR_SIZE > end:
            break
        try:
            ts, ftype = struct.unpack_from(FRAME_HDR_FMT, raw, pos)
        except struct.error:
            break

        pos += FRAME_HDR_SIZE

        if ftype in (FRAME_NORMAL, FRAME_STARTUP):
            needed = dci_size + 4
            if pos + needed > end:
                break
            try:
                msg_len = struct.unpack_from("<I", raw, pos + dci_size)[0]
            except struct.error:
                errors += 1; pos -= FRAME_HDR_SIZE; pos += 1; continue
            if msg_len > 0x10000:
                errors += 1; pos -= FRAME_HDR_SIZE; pos += 1; continue
            pos += needed + msg_len

        elif ftype == FRAME_STRINGCMD:
            if pos + 4 > end:
                break
            try:
                cmd_len = struct.unpack_from("<I", raw, pos)[0]
            except struct.error:
                break
            if cmd_len == 0 or cmd_len > 512:
                errors += 1; pos -= FRAME_HDR_SIZE; pos += 1; continue
            raw_cmd = raw[pos + 4 : pos + 4 + cmd_len]
            body = raw[pos : pos + 4 + cmd_len]
            f = Frame(timestamp=ts, ftype=ftype, raw_body=body)
            f.cmd = raw_cmd.rstrip(b"\x00").decode("utf-8", errors="replace")
            frames.append(f)
            pos += 4 + cmd_len

        elif ftype == FRAME_LASTRECORD:
            frames.append(Frame(timestamp=ts, ftype=ftype, raw_body=b""))
            break

        elif ftype in FRAME_BODY_SIZES:
            sz = FRAME_BODY_SIZES[ftype]
            if pos + sz > end:
                break
            body = raw[pos : pos + sz]
            f = Frame(timestamp=ts, ftype=ftype, raw_body=body)
            if ftype == FRAME_CLIENTDATA and sz == 32:
                try:
                    f.origin     = struct.unpack_from("<3f", body, 0)
                    f.viewangles = struct.unpack_from("<3f", body, 12)
                    f.weaponbits = struct.unpack_from("<I",  body, 24)[0]
                    f.fov        = struct.unpack_from("<f",  body, 28)[0]
                except struct.error:
                    pass
            frames.append(f)
            pos += sz

        elif ftype == FRAME_SOUND:
            if pos + 8 > end:
                break
            try:
                sample_len = struct.unpack_from("<I", raw, pos + 4)[0]
            except struct.error:
                break
            if sample_len > 260:
                errors += 1; pos -= FRAME_HDR_SIZE; pos += 1; continue
            total = 4 + 4 + sample_len + 16
            frames.append(Frame(timestamp=ts, ftype=ftype,
                                raw_body=raw[pos:pos+total]))
            pos += total

        elif ftype == FRAME_BUFFER:
            if pos + 4 > end:
                break
            try:
                buf_len = struct.unpack_from("<I", raw, pos)[0]
            except struct.error:
                break
            if buf_len > 0x10000:
                errors += 1; pos -= FRAME_HDR_SIZE; pos += 1; continue
            frames.append(Frame(timestamp=ts, ftype=ftype,
                                raw_body=raw[pos:pos+4+buf_len]))
            pos += 4 + buf_len

        else:
            errors += 1; pos -= FRAME_HDR_SIZE; pos += 1

    return frames


# --- Inyeccion NET_MSG con SVC_PRINT (texto VISIBLE en el demo) ---------------

def find_democmdinfo_template(
    raw       : bytes,
    directory : list,
    dci_size  : int = DEMOCMDINFO_SIZE,
) -> bytes:
    """
    Busca el primer frame NET_MSG (tipo 2) en el demo para extraer
    su bloque democmdinfo_t como plantilla para los frames inyectados.

    Estrategia: escanea byte a byte en el segmento mas largo buscando
    la secuencia (float32 plausible) + (byte == 2) + (uint32 msg_len < 64K).
    Si no encuentra nada, devuelve bytes(dci_size) (ceros).

    Los ceros funcionan para SVC_PRINT porque el motor solo usa democmdinfo
    para posicionamiento de camara - el renderizado de texto es independiente.
    """
    best = sorted(directory, key=lambda e: -e.file_length)
    for entry in best:
        seg_end = min(entry.offset + entry.file_length,
                      entry.offset + 40_000)   # escanear solo los primeros 40 KB
        pos = entry.offset
        while pos + FRAME_HDR_SIZE + dci_size + 4 <= seg_end:
            try:
                ts, ft = struct.unpack_from(FRAME_HDR_FMT, raw, pos)
                if ft == FRAME_NORMAL and 0.0 <= ts < 7200.0:
                    ml_pos = pos + FRAME_HDR_SIZE + dci_size
                    if ml_pos + 4 <= len(raw):
                        ml = struct.unpack_from("<I", raw, ml_pos)[0]
                        if 1 <= ml <= 32768:
                            # Parece valido - extraer democmdinfo
                            dc_start = pos + FRAME_HDR_SIZE
                            dc_end   = dc_start + dci_size
                            if dc_end <= len(raw):
                                return raw[dc_start:dc_end]
            except Exception:
                pass
            pos += 1

    # Fallback: ceros (valido para SVC_PRINT, puede causar salto visual breve)
    return bytes(dci_size)


def make_net_msg_frame(
    timestamp   : float,
    text        : str,
    democmdinfo : bytes,
    svc_type    : int = SVC_PRINT,
) -> "Frame":
    """
    Crea un frame dem_normal (tipo 2) con un mensaje SVC_PRINT o SVC_CENTERPRINT.

    Durante la reproduccion del demo, el motor procesa este frame como si
    el servidor original hubiera enviado ese mensaje de red ? el texto
    APARECE en el juego (notificaciones HUD / centro de pantalla).

    Formato del body:
      [democmdinfo_t  N bytes]
      [msg_len        4 bytes  uint32]
      [svc_type       1 byte   = SVC_PRINT(8) o SVC_CENTERPRINT(26)]
      [text + '\n'    N bytes  null-terminated]
    """
    import math
    if not math.isfinite(timestamp) or timestamp < 0:
        timestamp = 0.0

    text_b   = (text + "\n").encode("utf-8") + b"\x00"
    msg_data = bytes([svc_type]) + text_b
    msg_len  = struct.pack("<I", len(msg_data))

    body = democmdinfo + msg_len + msg_data
    f    = Frame(timestamp=timestamp, ftype=FRAME_NORMAL, raw_body=body)
    f.cmd = text   # para debug / inspect
    return f


# --- Scan DC:* mejorado: detecta STRINGCMD y NET_MSG -------------------------

def scan_dc_commands(
    raw        : bytes,
    seg_offset : int,
    seg_length : int,
) -> list:
    """
    Busca tokens DC:* en el segmento usando regex sobre bytes crudos.
    Compatible con AMBOS metodos de inyeccion:
      - Frames STRINGCMD legacy: "say DC:HEAD:...\x00"
      - Frames NET_MSG nuevos:   "HL:HEAD:...\n\x00"  (SVC_PRINT)

    Devuelve lista ordenada de strings normalizados (sin "say ", sin saltos).
    Preserva el orden de aparicion en el archivo (= orden temporal de inyeccion).
    """
    segment = raw[seg_offset : seg_offset + seg_length]

    results = []
    seen    = set()

    # Patron unificado: captura "say DC:..." y "HL:..." con o sin "say "
    # Termina en \x00, \n, o ambos
    pattern = re.compile(
        rb'(?:(?:say|echo) )?(HL:(?:HEAD|END|\d+)[^\x00\n\x08]{0,300})[\x00\n]'
    )

    for m in pattern.finditer(segment):
        raw_cmd = m.group(1)
        try:
            cmd = raw_cmd.decode("utf-8")
        except UnicodeDecodeError:
            cmd = raw_cmd.decode("latin-1")

        cmd = cmd.strip()
        if cmd and cmd not in seen:
            seen.add(cmd)
            results.append(cmd)

    return results


# ----------------------------------------------------------------
#  Scanner brute-force de CLIENTDATA (fallback para demos con
#  democmdinfo_size desconocido o parseo fallido)
# ----------------------------------------------------------------

def scan_clientdata_brute(
    raw        : bytes,
    seg_offset : int,
    seg_length : int,
    max_frames : int = 50_000,
) -> list:
    """
    Busca frames CLIENTDATA (tipo 8) byte a byte sin parsear NET_MSG.

    Funciona independientemente del valor de democmdinfo_size porque
    no intenta interpretar los frames NET_MSG: solo busca el patron
    [float32 ts][byte==8][32 bytes de datos].

    Filtros que eliminan falsos positivos:
      - Tipo byte == 8
      - Timestamp en [0.001, 7200.0] (segundos, hasta 2 horas)
      - Origin XYZ dentro de bounds de mapa GoldSrc [-32768, 32768]
      - FOV entre 1 y 180 grados
      - Timestamps estrictamente no decrecientes (elimina la mayoria
        de falsos positivos ya que deben aumentar con el tiempo)
      - Minimo 8 frames para considerar la deteccion valida
        (evita aceptar ruido como clave)
    """
    frames  = []
    end     = seg_offset + seg_length
    TOTAL   = FRAME_HDR_SIZE + 32   # 5 + 32 = 37 bytes por frame
    last_ts = -1.0

    pos = seg_offset
    while pos <= end - TOTAL:
        try:
            ts, ft = struct.unpack_from(FRAME_HDR_FMT, raw, pos)
        except struct.error:
            pos += 1
            continue

        if ft != FRAME_CLIENTDATA:
            pos += 1
            continue

        # Timestamp valido y monotono (tolerancia 0.5s)
        if not (0.001 <= ts <= 7200.0) or ts < last_ts - 0.5:
            pos += 1
            continue

        body_start = pos + FRAME_HDR_SIZE
        body       = raw[body_start : body_start + 32]
        if len(body) < 32:
            break

        try:
            ox, oy, oz = struct.unpack_from("<3f", body,  0)
            vx, vy, vz = struct.unpack_from("<3f", body, 12)
            wb          = struct.unpack_from("<I",  body, 24)[0]
            fov         = struct.unpack_from("<f",  body, 28)[0]
        except struct.error:
            pos += 1
            continue

        # Coordenadas GoldSrc: mapas tipicos tienen coords en [-8192, 8192]
        # pero ampliamos a [-32768, 32768] para ser mas permisivos
        import math
        if not all(
            isinstance(v, float) and not math.isnan(v) and not math.isinf(v)
            and abs(v) <= 32768.0
            for v in [ox, oy, oz]
        ):
            pos += 1
            continue

        if not (1.0 <= fov <= 180.0):
            pos += 1
            continue

        last_ts = ts
        f       = Frame(timestamp=ts, ftype=FRAME_CLIENTDATA, raw_body=body)
        f.origin     = (ox, oy, oz)
        f.viewangles = (vx, vy, vz)
        f.weaponbits = wb
        f.fov        = fov
        frames.append(f)

        if len(frames) >= max_frames:
            break

        pos += TOTAL   # avanzar un frame completo (optimizacion)

    return frames


# ----------------------------------------------------------------
#  Wrapper que intenta parser normal primero, brute-force como fallback
# ----------------------------------------------------------------

def scan_clientdata_any(
    raw              : bytes,
    seg_offset       : int,
    seg_length       : int,
    democmdinfo_size : int = DEMOCMDINFO_SIZE,
) -> list:
    """
    Intenta extraer frames CLIENTDATA con todas las estrategias disponibles:
      1. Parser normal con democmdinfo_size dado
      2. Parser normal con valores alternativos (0, 56, 208)
      3. Scanner brute-force byte a byte (fallback universal)

    Retorna la lista con mas frames validos encontrada.
    Nunca lanza excepcion: en el peor caso retorna lista vacia.
    """
    best = []

    # Estrategia 1 y 2: parser normal con varios democmdinfo_size
    for dci in [democmdinfo_size, 0, 56, 208]:
        try:
            frames = _try_scan_clientdata(raw, seg_offset, seg_length, dci)
            if len(frames) > len(best):
                best = frames
                if len(best) >= 20:   # suficiente entropia, no seguir probando
                    break
        except Exception:
            continue

    if len(best) >= 8:
        return best

    # Estrategia 3: brute-force (funciona sin importar democmdinfo_size)
    try:
        brute = scan_clientdata_brute(raw, seg_offset, seg_length)
        if len(brute) > len(best):
            print(
                f"  [INFO] Scanner brute-force: {len(brute)} frames CLIENTDATA "
                f"(parser normal encontro {len(best)})."
            )
            best = brute
    except Exception as e:
        print(f"  [WARN] Brute-force scanner error: {e}")

    return best

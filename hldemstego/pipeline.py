"""
MODULO 4 - Pipeline encode / decode / inspect
"""
import os, time
from typing import Optional

from .constants     import DEMOCMDINFO_SIZE, MIN_INJECT_GAP
from .dem_io        import (load_dem, load_dem_full,
                            scan_clientdata_frames, scan_clientdata_any,
                            scan_dc_commands, surgical_save_dem,
                            find_democmdinfo_template)
from .input_handler import prepare_payload, validate_capacity, reconstruct_payload
from .entropy       import collect_cd_frames, report_entropy, build_key, shuffle_chunks, unshuffle_chunks
from .stego         import make_injection_frames, parse_dc_commands
from .cryptocore    import safe_filename

def _hr(c="=",w=60): return c*w
def _banner(t):
    print(); print(_hr()); print(f"  {t}"); print(_hr())
def _tick(): return time.strftime("%H:%M:%S")
def _main_seg(directory):
    return max(range(len(directory)), key=lambda i: directory[i].file_length)

# ================================================================
#  ENCODE
# ================================================================
def encode(
    file_path        : str,
    base_dem         : str,
    out_dem          : str,
    password         : Optional[str] = None,
    democmdinfo_size : int  = DEMOCMDINFO_SIZE,
    force            : bool = False,
) -> None:
    _banner(f"HLdemStego ENCODE  [{_tick()}]")

    # 1. Demo base
    print(f"\n[1/5] Leyendo demo base: {base_dem}")
    header, directory, raw = load_dem(base_dem, democmdinfo_size)
    print(f"      mapa={header.map_name!r}  {len(raw):,} bytes  segs={len(directory)}")
    for i,e in enumerate(directory):
        print(f"        [{i}] offset={e.offset}  len={e.file_length:,}B  dur={e.time:.1f}s")
    seg_idx  = _main_seg(directory)
    entry    = directory[seg_idx]
    demo_dur = entry.time if entry.time > 0 else 9999.0
    print(f"      Segmento principal: [{seg_idx}]")

    # 2. Extraer entropia y derivar clave
    print(f"\n[2/5] Derivando clave criptografica desde los movimientos del jugador...")
    cd_raw = scan_clientdata_any(raw, entry.offset, entry.file_length, democmdinfo_size)
    cd     = collect_cd_frames(cd_raw)
    report_entropy(cd)

    if not cd and not password:
        raise ValueError(
            "No se detectaron frames CLIENTDATA en la demo.\n"
            "\n"
            "  El scanner normal Y el brute-force fallaron con esta demo.\n"
            "  Esto puede pasar con demos de versiones especificas del juego.\n"
            "\n"
            "  SOLUCIONES:\n"
            "    1. Agregar --password  (la password reemplaza la entropia de la demo)\n"
            "       Ejemplo: python -m hldemstego encode archivo.pdf demo.dem out.dem --password mipass\n"
            "\n"
            "    2. Probar otros valores de democmdinfo-size:\n"
            "       --democmdinfo-size 0\n"
            "       --democmdinfo-size 56\n"
            "       --democmdinfo-size 208\n"
            "\n"
            "    3. Grabar una demo nueva en modo offline (crea LAN server en CS 1.6,\n"
            "       escribi 'record mi_demo' en consola, move al jugador, 'stop')."
        )

    key = build_key(cd, password=password)
    print(f"      Clave (primeros 8 bytes): {key[:8].hex()}...")
    if password:
        print(f"      Modo: demo_entropia + password (PBKDF2 200k iters)")
    elif cd:
        print(f"      Modo: solo demo_entropia ({len(cd)} frames CLIENTDATA)")
    else:
        print(f"      Modo: solo password (sin entropia de demo)")

    # 3. Preparar payload
    print(f"\n[3/5] Preparando payload: {file_path}")
    chunks, filename, orig_size, comp_size, mac = prepare_payload(file_path, key=key)
    print(f"      {len(chunks)} fragmento(s)  |  MAC: {mac[:8].hex()}...")

    # 4. Validar capacidad
    print(f"\n[4/5] Validando capacidad ({demo_dur:.1f}s)...")
    ok = validate_capacity(chunks, demo_dur, filename, orig_size, comp_size,
                           has_key=True, verbose=True)
    if not ok and not force:
        raise RuntimeError("Demo muy corta. Usa --force para ignorar.")

    # 5. Barajar e inyectar
    print(f"\n[5/5] Barajando con HMAC-CSPRNG e inyectando...")
    shuffled, perm = shuffle_chunks(chunks, key)
    print(f"      Permutacion (primeros 5): {perm[:5]}{'...' if len(perm)>5 else ''}")

    t_start    = 1.0
    t_end      = max(demo_dur - 0.5, t_start + (len(shuffled) + 2) * MIN_INJECT_GAP)
    inj_frames = make_injection_frames(shuffled, filename, t_start, t_end, mac=mac)
    print(f"      Frames a inyectar: {len(inj_frames)}  |  Ventana: {t_start:.2f}s-{t_end:.2f}s")

    surgical_save_dem(out_dem, raw, header, directory, seg_idx, inj_frames)

    out_sz = os.path.getsize(out_dem)
    print()
    print(_hr("-"))
    print(f"  [OK] Demo cifrada: {out_dem}")
    print(f"       Original  : {len(raw):,} bytes")
    print(f"       Resultado : {out_sz:,} bytes  (+{out_sz-len(raw):,} bytes)")
    print(f"       Overhead  : {(out_sz-len(raw))/len(raw)*100:.4f}%")
    if password:
        print(f"       Seguridad : demo + password (PBKDF2 + HMAC-SHA256-CTR)")
    else:
        print(f"       Seguridad : solo demo ({len(cd)} frames CLIENTDATA como clave)")
    print(_hr("-"))
    print()

# ================================================================
#  DECODE
# ================================================================
def decode(
    stego_dem        : str,
    out_dir          : str,
    password         : Optional[str] = None,
    democmdinfo_size : int = DEMOCMDINFO_SIZE,
) -> str:
    _banner(f"HLdemStego DECODE  [{_tick()}]")
    os.makedirs(out_dir, exist_ok=True)

    # 1. Cargar demo
    print(f"\n[1/4] Leyendo demo: {stego_dem}")
    header, directory, raw = load_dem(stego_dem, democmdinfo_size)
    print(f"      mapa={header.map_name!r}  {len(raw):,} bytes")
    seg_idx = _main_seg(directory)
    entry   = directory[seg_idx]
    print(f"      Segmento [{seg_idx}]: {entry.file_length:,} bytes")

    # 2. Recalcular clave
    print(f"\n[2/4] Recalculando clave criptografica...")
    cd_raw = scan_clientdata_any(raw, entry.offset, entry.file_length, democmdinfo_size)
    cd     = collect_cd_frames(cd_raw)
    report_entropy(cd)

    if not cd and not password:
        raise ValueError(
            "No se detectaron frames CLIENTDATA en la demo.\n"
            "  No se puede recalcular la clave.\n"
            "\n"
            "  Posibles causas:\n"
            "    - La demo es de un formato no standard (mod, version especial)\n"
            "    - El archivo fue cifrado con --password pero no se paso aqui\n"
            "\n"
            "  Soluciones:\n"
            "    - Si se uso --password en el encode, usarla tambien aqui\n"
            "    - Probar --democmdinfo-size 0, 56 o 208"
        )

    key = build_key(cd, password=password)
    print(f"      Clave (primeros 8 bytes): {key[:8].hex()}...")

    # 3. Extraer y parsear tokens DC:*
    print(f"\n[3/4] Extrayendo tokens DC:* (regex en bytes crudos)...")
    raw_cmds = scan_dc_commands(raw, entry.offset, entry.file_length)
    print(f"      Tokens encontrados: {len(raw_cmds)}")
    for c in raw_cmds[:3]:
        print(f"        {c[:80]}{'...' if len(c)>80 else ''}")

    filename, total, shuffled, mac = parse_dc_commands(raw_cmds)
    print(f"      Archivo: {filename!r}  chunks: {total}/{len(shuffled)}")
    print(f"      MAC extraido: {mac[:8].hex()}{'...' if len(mac)>8 else ''}")

    # 4. Des-permutar y reconstruir
    print(f"\n[4/4] Des-permutando y reconstruyendo archivo...")
    original = unshuffle_chunks(shuffled, key)
    out_path = reconstruct_payload(original, out_dir, filename, key=key, mac=mac)

    print()
    print(_hr("-"))
    print(f"  [OK] Archivo recuperado: {out_path}")
    print(f"       Tamano: {os.path.getsize(out_path):,} bytes")
    print(_hr("-"))
    print()
    return out_path

# ================================================================
#  INSPECT
# ================================================================
def inspect(dem_path, democmdinfo_size=DEMOCMDINFO_SIZE, show_frames=20):
    _banner(f"HLdemStego INSPECT  [{_tick()}]")
    header, directory, segments, raw = load_dem_full(dem_path, democmdinfo_size)
    print(f"\n  Archivo   : {dem_path}  ({os.path.getsize(dem_path):,} bytes)")
    print(f"  Demo proto: {header.demo_protocol}  Net: {header.net_protocol}")
    print(f"  Mapa      : {header.map_name!r}")
    print(f"\n  Directorio ({len(directory)} entradas):")
    for i,e in enumerate(directory):
        print(f"    [{i}] dur={e.time:.1f}s  frames={e.frame_count}  "
              f"offset={e.offset}  len={e.file_length:,}B")

    all_dc = []
    for e in directory:
        if e.file_length > 0:
            all_dc.extend(scan_dc_commands(raw, e.offset, e.file_length))
    if all_dc:
        print(f"\n  Tokens DC:* ({len(all_dc)} total):")
        for cmd in all_dc[:show_frames]:
            print(f"    {cmd[:100]}")
        if len(all_dc) > show_frames:
            print(f"    ... y {len(all_dc)-show_frames} mas.")
    else:
        print("\n  No se encontraron tokens DC:*.")

    from collections import Counter
    NAMES={0:"UNKNOWN",1:"STARTUP",2:"NET_MSG",3:"STRINGCMD",4:"LASTRECORD",
           5:"EVENT",6:"SOUND",7:"BUFFER",8:"CLIENTDATA",9:"WEAPONANIM"}
    for i,frames in enumerate(segments):
        if not frames: continue
        c = Counter(f.ftype for f in frames)
        print(f"\n  Segmento {i}: {len(frames)} frames parseados")
        for ft,n in sorted(c.items()):
            print(f"    {NAMES.get(ft,f'TYPE_{ft}'):12s}({ft:2d}): {n:5d}")

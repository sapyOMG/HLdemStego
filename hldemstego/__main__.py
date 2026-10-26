"""
HLdemStego - CLI entry point.

Uso
---
  python -m hldemstego encode <archivo> <demo_base.dem> <demo_salida.dem>
  python -m hldemstego decode <demo_cifrada.dem> [carpeta_salida]
  python -m hldemstego inspect <demo.dem>

Flags opcionales
----------------
  --democmdinfo-size N    Tamano del bloque democmdinfo_t en bytes
                          (default 164; proba 0, 56, 208 si hay errores)
  --force                 Ignorar advertencia de capacidad insuficiente
  --show-frames N         Cantidad de frames a mostrar en inspect (default 20)
  --chunk-size N          Caracteres Base64 por fragmento (default 80, max 80)
  -h / --help             Mostrar esta ayuda
"""

import sys
import os
import argparse

# Soporte para ejecutar como modulo standalone (python hldemstego/...)
# o instalado como paquete
try:
    from .pipeline  import encode, decode, inspect
    from . import constants
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
    from hldemstego.pipeline  import encode, decode, inspect
    from hldemstego import constants


# --- Colores ANSI simples (desactivados en Windows sin soporte) ---------------
def _supports_color() -> bool:
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


_C = {
    "red"   : "\033[91m" if _supports_color() else "",
    "green" : "\033[92m" if _supports_color() else "",
    "yellow": "\033[93m" if _supports_color() else "",
    "cyan"  : "\033[96m" if _supports_color() else "",
    "reset" : "\033[0m"  if _supports_color() else "",
}


def _err(msg: str) -> None:
    print(f"{_C['red']}[ERROR]{_C['reset']} {msg}", file=sys.stderr)


def _warn(msg: str) -> None:
    print(f"{_C['yellow']}[WARN]{_C['reset']} {msg}", file=sys.stderr)


# --- Parseo de argumentos -----------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m hldemstego",
        description=(
            "HLdemStego - Esteganografia en demos GoldSrc (HL / CS 1.6)\n"
            "Oculta archivos dentro de archivos .dem usando comandos 'say'."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  # Ocultar secreto.txt en mi_demo.dem ? salida.dem
  python -m hldemstego encode secreto.txt mi_demo.dem salida.dem

  # Extraer el archivo oculto de salida.dem
  python -m hldemstego decode salida.dem ./recuperado/

  # Inspeccionar cualquier demo
  python -m hldemstego inspect mi_demo.dem --show-frames 30
        """,
    )

    sub = p.add_subparsers(dest="command", metavar="COMANDO")
    sub.required = True

    # -- encode ------------------------------------------------------------
    enc = sub.add_parser(
        "encode",
        help="Oculta un archivo dentro de una demo .dem",
        description="Lee un archivo, lo comprime, codifica en Base64 y "
                    "lo inyecta esteganograficamente en la demo.",
    )
    enc.add_argument("file",    metavar="ARCHIVO",      help="Archivo a ocultar")
    enc.add_argument("base_dem",metavar="DEMO_BASE.dem",help="Demo GoldSrc de entrada (original)")
    enc.add_argument("out_dem", metavar="DEMO_OUT.dem", help="Demo de salida (cifrada)")
    enc.add_argument(
        "--democmdinfo-size", type=int, default=164, metavar="N",
        help="Tamano del bloque democmdinfo_t (default: 164)",
    )
    enc.add_argument(
        "--password", "-p", default=None, metavar="PASS",
        help="Password adicional (opcional pero recomendada). Sin ella, la clave son los movimientos del jugador en la demo. Si la demo no tiene frames CLIENTDATA detectables, la password es obligatoria.",
    )
    enc.add_argument(
        "--force", action="store_true",
        help="Continuar aunque la demo sea demasiado corta para el payload",
    )
    enc.add_argument(
        "--chunk-size", type=int, default=None, metavar="N",
        help=f"Caracteres Base64 por fragmento (default: {constants.CHUNK_SIZE}, max recomendado: 80)",
    )

    # -- decode ------------------------------------------------------------
    dec = sub.add_parser(
        "decode",
        help="Extrae y reconstruye el archivo oculto de una demo cifrada",
        description="Lee la demo modificada, extrae los comandos DC:*, "
                    "recalcula la semilla y reconstruye el archivo original.",
    )
    dec.add_argument("stego_dem", metavar="DEMO_CIFRADA.dem", help="Demo procesada por HLdemStego")
    dec.add_argument(
        "out_dir", nargs="?", default=".", metavar="CARPETA_SALIDA",
        help="Directorio donde guardar el archivo recuperado (default: .)",
    )
    dec.add_argument(
        "--password", "-p", default=None, metavar="PASS",
        help="Password usada en el encode (si se aplico).",
    )
    dec.add_argument(
        "--democmdinfo-size", type=int, default=164, metavar="N",
        help="Tamano del bloque democmdinfo_t (default: 164)",
    )

    # -- inspect -----------------------------------------------------------
    ins = sub.add_parser(
        "inspect",
        help="Muestra informacion interna de cualquier demo .dem",
        description="Herramienta de diagnostico: muestra cabecera, directorio, "
                    "tipos de frame y comandos DC:* detectados.",
    )
    ins.add_argument("dem_path", metavar="DEMO.dem", help="Archivo .dem a inspeccionar")
    ins.add_argument(
        "--democmdinfo-size", type=int, default=164, metavar="N",
        help="Tamano del bloque democmdinfo_t (default: 164)",
    )
    ins.add_argument(
        "--show-frames", type=int, default=20, metavar="N",
        help="Max. de comandos a mostrar (default: 20)",
    )

    return p


# --- Main ---------------------------------------------------------------------

def main(argv=None) -> int:
    p    = build_parser()
    args = p.parse_args(argv)

    # Aplicar chunk-size personalizado si se pide
    if getattr(args, "chunk_size", None) is not None:
        cs = args.chunk_size
        if cs < 4 or cs > 80:
            _warn(f"--chunk-size {cs} fuera del rango seguro [4..80]; "
                  f"se usara {constants.CHUNK_SIZE}.")
        else:
            constants.CHUNK_SIZE = cs

    try:
        if args.command == "encode":
            for attr, label in [("file", "ARCHIVO"), ("base_dem", "DEMO_BASE")]:
                path = getattr(args, attr)
                if not os.path.isfile(path):
                    _err(f"No se encuentra {label}: {path!r}")
                    return 1
            out_dir = os.path.dirname(os.path.abspath(args.out_dem))
            os.makedirs(out_dir, exist_ok=True)
            encode(
                file_path        = args.file,
                base_dem         = args.base_dem,
                out_dem          = args.out_dem,
                password         = args.password,
                democmdinfo_size = args.democmdinfo_size,
                force            = args.force,
            )

        elif args.command == "decode":
            if not os.path.isfile(args.stego_dem):
                _err(f"No se encuentra la demo cifrada: {args.stego_dem!r}")
                return 1
            decode(
                stego_dem        = args.stego_dem,
                out_dir          = args.out_dir,
                password         = args.password,
                democmdinfo_size = args.democmdinfo_size,
            )

        elif args.command == "inspect":
            if not os.path.isfile(args.dem_path):
                _err(f"No se encuentra la demo: {args.dem_path!r}")
                return 1
            inspect(
                dem_path         = args.dem_path,
                democmdinfo_size = args.democmdinfo_size,
                show_frames      = args.show_frames,
            )

    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        _err(str(exc))
        return 1
    except KeyboardInterrupt:
        print("\nInterrumpido por el usuario.")
        return 130
    except Exception as exc:
        _err(f"Error inesperado: {exc}")
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())

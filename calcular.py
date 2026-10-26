"""
calcular.py  -  HLdemStego
===============================================================
Calcula cuanto tiene que durar el archivo .dem para poder
ocultar el archivo que le pasas.

Uso:
    python calcular.py contrasena.txt
    python calcular.py "C:\\Users\\Vos\\Desktop\\foto.jpg"

No modifica ni necesita ningun .dem; solo analiza el archivo
de entrada y te dice los requisitos de la demo.
"""

import sys
import os
import zlib
import base64
import math

# -- Configuracion (tiene que coincidir con constants.py) ----------
CHUNK_SIZE    = 80      # chars Base64 por fragmento
MIN_INJECT_GAP = 0.05  # segundos entre frames inyectados
# -----------------------------------------------------------------


def calcular(ruta: str) -> None:
    # -- Leer archivo ---------------------------------------------
    if not os.path.isfile(ruta):
        print(f"\n  [ERROR] No se encuentra el archivo: {ruta!r}")
        print("  Verifica que la ruta sea correcta y que no tenga typos.\n")
        sys.exit(1)

    with open(ruta, "rb") as fh:
        contenido = fh.read()

    nombre    = os.path.basename(ruta)
    tam_orig  = len(contenido)

    if tam_orig == 0:
        print("\n  [ERROR] El archivo esta vacio.\n")
        sys.exit(1)

    # -- Comprimir + Base64 ----------------------------------------
    comprimido = zlib.compress(contenido, level=zlib.Z_BEST_COMPRESSION)
    tam_comp   = len(comprimido)
    b64_str    = base64.b64encode(comprimido).decode("ascii")
    tam_b64    = len(b64_str)

    # -- Fragmentos ------------------------------------------------
    n_chunks   = math.ceil(tam_b64 / CHUNK_SIZE)
    # +2 porque tambien inyectamos HEAD y END
    n_frames   = n_chunks + 2

    # -- Duracion minima del .dem ----------------------------------
    dur_min    = n_frames * MIN_INJECT_GAP   # segundos

    # -- Mostrar resultado -----------------------------------------
    SEP = "=" * 56
    sep = "-" * 56

    print()
    print(SEP)
    print("  HLdemStego - Calculador de requisitos")
    print(SEP)
    print()
    print(f"  Archivo          : {nombre}")
    print(f"  Tamano original  : {tam_orig:,} bytes  ({tam_orig/1024:.1f} KB)")
    print()
    print(sep)
    print("  Procesamiento interno")
    print(sep)
    ratio = tam_comp / tam_orig * 100
    print(f"  Tras compresion  : {tam_comp:,} bytes  ({ratio:.1f}% del original)")
    print(f"  Tras Base64      : {tam_b64:,} chars")
    print(f"  Fragmentos       : {n_chunks}  (de {CHUNK_SIZE} chars c/u)")
    print(f"  Frames a injectar: {n_frames}  (datos + HEAD + END)")
    print()
    print(sep)
    print("  ?Que demo necesitas?")
    print(sep)

    # Expresar en segundos, minutos y cantidad de frames tipicos
    min_s  = dur_min
    min_m  = dur_min / 60
    frames_aprox = int(dur_min * 64)   # ~64 fps tipico en GoldSrc

    print(f"  Duracion minima  : {min_s:.1f} segundos  ({min_m:.2f} minutos)")
    print(f"  Frames aprox     : {frames_aprox:,}  (asumiendo 64 fps)")
    print()

    # -- Consejo segun duracion ------------------------------------
    if min_s < 10:
        consejo = (
            "Una demo CORT?SIMA alcanza. Podes grabar 10-15 segundos\n"
            "  jugando cualquier mapa en modo offline (Counter-Strike:\n"
            "  abris la consola, escribis 'record test' para empezar\n"
            "  a grabar y 'stop' para parar)."
        )
    elif min_s < 60:
        consejo = (
            f"Necesitas aproximadamente {math.ceil(min_s)} segundos de demo.\n"
            "  Una partida corta alcanza sobradamente.\n"
            "  Comandos: 'record mi_demo' para grabar, 'stop' para parar."
        )
    elif min_s < 300:
        consejo = (
            f"Necesitas una demo de {min_m:.1f} minutos.\n"
            "  Una partida completa de CS 1.6 (30 min) es mas que suficiente."
        )
    else:
        consejo = (
            f"El archivo es grande. Necesitas {min_m:.1f} minutos de demo.\n"
            "  Considera comprimir el archivo antes con otro metodo\n"
            "  (ej: archivarlo en .zip primero) para reducir el tamano,\n"
            "  o dividirlo en partes y cifrar cada parte por separado."
        )

    print(f"  Consejo          : {consejo}")
    print()
    print(sep)
    print("  Como grabar una demo en CS 1.6 / Half-Life")
    print(sep)
    print("  1. Abri el juego y crea un servidor offline (Training / LAN)")
    print("  2. Abri la consola con la tecla  ~  o  ?")
    print("  3. Escribi:  record mi_demo   ? empieza a grabar")
    print("  4. Juga / movete / salta / dispare un poco")
    print("     (los saltos y disparos generan la 'semilla' de encriptado)")
    print("  5. Escribi:  stop             ? para la grabacion")
    print("  6. La demo queda en la carpeta del juego como  mi_demo.dem")
    print()
    print("  Ruta tipica en Windows:")
    print("    C:\\Program Files (x86)\\Steam\\steamapps\\common\\")
    print("    Half-Life\\cstrike\\mi_demo.dem")
    print()
    print(SEP)
    print()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print()
        print("  Uso:  python calcular.py <archivo>")
        print()
        print("  Ejemplo:")
        print('  python calcular.py contrasena.txt')
        print('  python calcular.py "C:\\Users\\Vos\\foto.jpg"')
        print()
        # Si lo abren con doble clic (sin argumento), pedir la ruta
        print("  (O escribi la ruta del archivo aca abajo)")
        ruta = input("  Archivo: ").strip().strip('"').strip("'")
        if not ruta:
            sys.exit(0)
    else:
        ruta = sys.argv[1].strip('"').strip("'")

    calcular(ruta)

    # Pausa para que no se cierre si lo abrieron con doble clic
    print("  Presiona Enter para cerrar...")
    input()

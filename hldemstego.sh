#!/usr/bin/env bash

set -euo pipefail

# Ruta base
BASE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Colores ANSI
if [[ -t 1 ]]; then
    RED='\033[0;91m';  GREEN='\033[0;92m'; YELLOW='\033[0;93m'
    CYAN='\033[0;96m'; BOLD='\033[1m';     DIM='\033[2m'
    RESET='\033[0m'
else
    RED=''; GREEN=''; YELLOW=''; CYAN=''; BOLD=''; DIM=''; RESET=''
fi

err()  { echo -e "${RED}[ERROR]${RESET} $*" >&2; }
warn() { echo -e "${YELLOW}[WARN]${RESET}  $*"; }
ok()   { echo -e "${GREEN}[OK]${RESET}    $*"; }
info() { echo -e "${CYAN}[INFO]${RESET}  $*"; }
hr()   { echo -e "${DIM}$(printf '%.0s=' {1..62})${RESET}"; }
hr2()  { echo -e "${DIM}$(printf '%.0s-' {1..62})${RESET}"; }

banner() {
    clear
    echo -e "${CYAN}${BOLD}"
    echo "  =========================================================="
    echo "   HLdemStego  -  Esteganografia en demos GoldSrc"
    echo "   Half-Life / Counter-Strike 1.6"
    echo "  =========================================================="
    echo -e "${RESET}"
}

find_python() {
    local py=""
    for cmd in python3 python python3.12 python3.11 python3.10 python3.9 py; do
        if command -v "$cmd" &>/dev/null; then
            local ver
            ver="$("$cmd" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || echo "0.0")"
            local major minor
            major="${ver%%.*}"
            minor="${ver##*.}"
            if [[ "$major" -ge 3 && "$minor" -ge 9 ]]; then
                py="$cmd"
                break
            fi
        fi
    done
    echo "$py"
}

PYTHON="$(find_python)"

check_python() {
    if [[ -z "$PYTHON" ]]; then
        banner
        err "No se encontro Python 3.9+ en tu sistema."
        echo
        echo "  Instalacion:"
        if [[ "$(uname)" == "Darwin" ]]; then
            echo "    brew install python"
            echo "    o descarga desde https://www.python.org/downloads/"
        else
            echo "    sudo apt install python3        # Debian / Ubuntu"
            echo "    sudo dnf install python3        # Fedora / RHEL"
            echo "    sudo pacman -S python           # Arch"
        fi
        echo
        exit 1
    fi
}

check_package() {
    if [[ ! -f "$BASE/hldemstego/__main__.py" ]]; then
        banner
        err "No se encontro el paquete hldemstego/ en: $BASE"
        echo
        echo "  Estructura esperada:"
        echo "    tu_carpeta/"
        echo "      hldemstego.sh"
        echo "      hldemstego/"
        echo "        __main__.py"
        echo "        pipeline.py"
        echo "        ..."
        echo
        exit 1
    fi
}

prompt_path() {
    local msg="$1"
    local var_name="$2"
    local default="${3:-}"
    local input

    if [[ -n "$default" ]]; then
        echo -ne "  ${BOLD}${msg}${RESET} ${DIM}[${default}]${RESET}: "
    else
        echo -ne "  ${BOLD}${msg}${RESET}: "
    fi
    read -r input
    input="${input//\'/}"
    input="${input//\"/}"
    if [[ -z "$input" && -n "$default" ]]; then
        input="$default"
    fi
    printf -v "$var_name" '%s' "$input"
}

pause_msg() {
    echo
    echo -ne "  ${DIM}Presiona Enter para continuar...${RESET}"
    read -r
}

run_calcular() {
    banner
    echo -e "  ${BOLD}${CYAN}CALCULAR - Cuanto tiene que durar la demo${RESET}"
    hr2
    echo
    prompt_path "Archivo a analizar (ruta completa)" FILE ""
    [[ -z "$FILE" ]] && return
    if [[ ! -f "$FILE" ]]; then
        err "No se encuentra: $FILE"
        pause_msg; return
    fi
    echo
    cd "$BASE"
    set +e
    "$PYTHON" calcular.py "$FILE"
    set -e
    pause_msg
}

do_encode() {
    while true; do
        banner
        echo -e "  ${BOLD}${CYAN}CIFRAR - Ocultar archivo dentro de un .dem${RESET}"
        hr2
        echo
        echo -e "  ${DIM}Podes arrastrar archivos a esta terminal para pegar la ruta.${RESET}"
        echo -e "  ${DIM}Deja vacio y Enter para volver al menu.${RESET}"
        echo

        prompt_path "Archivo a ocultar" FILE ""
        [[ -z "$FILE" ]] && return
        if [[ ! -f "$FILE" ]]; then
            err "No se encuentra: $FILE"
            pause_msg; continue
        fi
        local fsize
        fsize="$(wc -c < "$FILE" | tr -d ' ')"
        ok "Encontrado: $(basename "$FILE") (${fsize} bytes)"
        echo

        prompt_path "Demo base .dem (sin modificar)" BASEDEM ""
        [[ -z "$BASEDEM" ]] && return
        if [[ ! -f "$BASEDEM" ]]; then
            err "No se encuentra: $BASEDEM"
            pause_msg; continue
        fi
        ok "Demo: $(basename "$BASEDEM")"
        echo

        prompt_path "Demo de salida (nueva .dem cifrada)" OUTDEM ""
        [[ -z "$OUTDEM" ]] && return

        echo
        echo -e "  ${BOLD}SEGURIDAD:${RESET}"
        echo -e "  ${DIM}La clave = movimientos del jugador en la demo (frames CLIENTDATA).${RESET}"
        echo -e "  ${YELLOW}Si la demo es de servidor online y falla, usa una password.${RESET}"
        echo -e "  ${DIM}Con demos grabadas en offline (LAN/training) funciona sin password.${RESET}"
        prompt_path "Password (Enter para omitir)" PW ""

        echo
        echo -e "  ${DIM}Opciones avanzadas (Enter = default):${RESET}"
        prompt_path "democmdinfo-size" CMDINFO "164"
        local FORCE_FLAG=""
        echo -ne "  ${BOLD}Forzar aunque la demo sea corta? [s/N]${RESET}: "
        read -r FORCE_RESP
        [[ "${FORCE_RESP,,}" =~ ^(s|si|y|yes)$ ]] && FORCE_FLAG="--force"

        echo
        hr2
        info "Ejecutando encode..."
        hr2
        echo
        cd "$BASE"
        set +e
        local -a args2=("encode" "$FILE" "$BASEDEM" "$OUTDEM" "--democmdinfo-size" "$CMDINFO")
        [[ -n "$PW" ]] && args2+=("--password" "$PW")
        [[ -n "$FORCE_FLAG" ]] && args2+=("$FORCE_FLAG")
        "$PYTHON" -m hldemstego "${args2[@]}"
        local EXIT_CODE=$?
        set -e
        echo
        hr2
        if [[ $EXIT_CODE -eq 0 ]]; then
            ok "Demo cifrada guardada en: $OUTDEM"
        else
            err "El encode termino con codigo $EXIT_CODE"
        fi
        pause_msg
        return
    done
}

do_decode() {
    while true; do
        banner
        echo -e "  ${BOLD}${CYAN}DESCIFRAR - Extraer archivo de un .dem cifrado${RESET}"
        hr2
        echo

        prompt_path "Demo cifrada .dem (procesada por HLdemStego)" STEGO ""
        [[ -z "$STEGO" ]] && return
        if [[ ! -f "$STEGO" ]]; then
            err "No se encuentra: $STEGO"
            pause_msg; continue
        fi
        ok "Demo: $(basename "$STEGO")"
        echo

        prompt_path "Carpeta donde guardar el archivo recuperado" OUTDIR "."
        [[ -z "$OUTDIR" ]] && OUTDIR="."
        mkdir -p "$OUTDIR"

        echo
        echo -e "  ${DIM}Si se uso password en el encode, ingresala ahora.${RESET}"
        prompt_path "Password (Enter si no se uso ninguna)" PW2 ""

        prompt_path "democmdinfo-size" CMDINFO2 "164"

        echo
        hr2
        info "Ejecutando decode..."
        hr2
        echo
        cd "$BASE"
        set +e
        local -a dargs=("decode" "$STEGO" "$OUTDIR" "--democmdinfo-size" "$CMDINFO2")
        [[ -n "$PW2" ]] && dargs+=("--password" "$PW2")
        "$PYTHON" -m hldemstego "${dargs[@]}"
        local EXIT_CODE=$?
        set -e
        echo
        hr2
        if [[ $EXIT_CODE -eq 0 ]]; then
            ok "Archivo recuperado en: $OUTDIR"
        else
            err "El decode termino con codigo $EXIT_CODE"
        fi
        pause_msg
        return
    done
}

do_inspect() {
    banner
    echo -e "  ${BOLD}${CYAN}INSPECCIONAR - Ver tokens DC:* dentro de un demo${RESET}"
    hr2
    echo

    prompt_path "Demo a inspeccionar" INSPDEM ""
    [[ -z "$INSPDEM" ]] && return
    if [[ ! -f "$INSPDEM" ]]; then
        err "No se encuentra: $INSPDEM"
        pause_msg; return
    fi
    prompt_path "Cuantos tokens mostrar" NFRAMES "20"
    [[ -z "$NFRAMES" ]] && NFRAMES="20"
    prompt_path "democmdinfo-size" CMDINFO3 "164"

    echo
    hr2
    cd "$BASE"
    set +e
    "$PYTHON" -m hldemstego inspect "$INSPDEM" --show-frames "$NFRAMES" --democmdinfo-size "$CMDINFO3"
    set -e
    echo
    hr2
    pause_msg
}

do_tests() {
    banner
    echo -e "  ${BOLD}${CYAN}TESTS - Verificar que todo funciona (28 tests)${RESET}"
    hr2
    echo
    info "Corriendo tests unitarios..."
    echo
    cd "$BASE"
    set +e
    "$PYTHON" -m unittest discover tests/ -v
    local EXIT_CODE=$?
    set -e
    echo
    hr2
    if [[ $EXIT_CODE -eq 0 ]]; then
        ok "Todos los tests pasaron."
    else
        err "Algunos tests fallaron."
    fi
    pause_msg
}

do_ayuda() {
    banner
    echo -e "  ${BOLD}${CYAN}AYUDA - Flags, ejemplos y uso desde consola${RESET}"
    hr2
    echo
    cd "$BASE"
    "$PYTHON" -m hldemstego --help
    echo
    hr2
    echo
    echo -e "  ${BOLD}FLAGS AVANZADOS:${RESET}"
    echo -e "    --democmdinfo-size N   (default 164, probar 0 / 56 / 208)"
    echo -e "    --force                Ignorar advertencia de demo corta"
    echo -e "    --chunk-size N         Chars Base64 por fragmento (max 80)"
    echo
    echo -e "  ${BOLD}EJEMPLOS DESDE BASH (sin menu):${RESET}"
    echo -e "    ${GREEN}./hldemstego.sh encode secreto.txt base.dem salida.dem${RESET}"
    echo -e "    ${GREEN}./hldemstego.sh decode salida.dem ./recuperado/${RESET}"
    echo -e "    ${GREEN}./hldemstego.sh inspect salida.dem --show-frames 50${RESET}"
    echo
    hr2
    pause_msg
}

main_menu() {
    local pyver
    pyver="$("$PYTHON" --version 2>&1)"
    while true; do
        banner
        echo -e "  ${DIM}Python : $pyver${RESET}"
        echo -e "  ${DIM}Carpeta: $BASE${RESET}"
        echo
        hr2
        echo -e "  ${BOLD}Que queres hacer?${RESET}"
        hr2
        echo -e "  [1]  CALCULAR     - Ver cuanto tiene que durar la demo"
        echo -e "  [2]  CIFRAR       - Ocultar archivo en un .dem"
        echo -e "  [3]  DESCIFRAR    - Extraer archivo de un .dem cifrado"
        echo -e "  [4]  INSPECCIONAR - Ver tokens DC:* en cualquier demo"
        echo -e "  [5]  TESTS        - Verificar instalacion (28 tests)"
        echo -e "  [6]  AYUDA        - Flags, ejemplos, info del proyecto"
        echo -e "  [7]  SALIR"
        hr2
        echo
        echo -ne "  Opcion: "
        read -r OPT

        case "$OPT" in
            1) run_calcular ;;
            2) do_encode    ;;
            3) do_decode    ;;
            4) do_inspect   ;;
            5) do_tests     ;;
            6) do_ayuda     ;;
            7)
                banner
                echo -e "  ${GREEN}Hasta luego!${RESET}"
                echo
                exit 0
                ;;
            *)
                warn "Opcion invalida. Escribi un numero del 1 al 7."
                sleep 1
                ;;
        esac
    done
}

check_python
check_package

if [[ $# -gt 0 ]]; then
    cd "$BASE"
    exec "$PYTHON" -m hldemstego "$@"
fi

main_menu
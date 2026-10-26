# HLdemStego - Launcher PowerShell (ASCII puro, sin caracteres especiales)
# Uso: doble clic en ABRIR.cmd
# O desde PS: powershell -ExecutionPolicy Bypass -File hldemstego.ps1

$ErrorActionPreference = "Stop"
$Host.UI.RawUI.WindowTitle = "HLdemStego"
$BASE = Split-Path -Parent $MyInvocation.MyCommand.Path

# --- Colores ---
$CC = "Cyan"; $CG = "Green"; $CY = "Yellow"; $CR = "Red"; $CD = "DarkGray"; $CW = "White"

# --- Output helpers ---
function HR  { Write-Host ("  " + ("=" * 62)) -ForegroundColor $CD }
function HR2 { Write-Host ("  " + ("-" * 62)) -ForegroundColor $CD }

function WOk  { param([string]$M) Write-Host "  [OK]  $M" -ForegroundColor $CG }
function WErr { param([string]$M) Write-Host "  [ERR] $M" -ForegroundColor $CR }
function WWrn { param([string]$M) Write-Host "  [!]   $M" -ForegroundColor $CY }
function WInf { param([string]$M) Write-Host "  >>   $M"  -ForegroundColor $CW }

function Show-Banner {
    Clear-Host
    Write-Host ""
    Write-Host "  ==========================================================" -ForegroundColor $CC
    Write-Host "   HLdemStego  -  Esteganografia en demos GoldSrc" -ForegroundColor $CC
    Write-Host "   Half-Life / Counter-Strike 1.6" -ForegroundColor $CC
    Write-Host "  ==========================================================" -ForegroundColor $CC
    Write-Host ""
}

function Pause-Back {
    Write-Host ""
    Read-Host "  Presiona Enter para volver al menu" | Out-Null
}

function Ask-Val {
    param([string]$Label, [string]$Def = "")
    if ($Def) {
        Write-Host "  ${Label} [$Def]: " -NoNewline -ForegroundColor $CW
    } else {
        Write-Host "  ${Label}: " -NoNewline -ForegroundColor $CW
    }
    $v = (Read-Host).Trim().Trim('"').Trim("'")
    if ((-not $v) -and $Def) { return $Def }
    return $v
}

# --- Buscar Python ---
function Find-Python {
    foreach ($cmd in @("python","python3","py")) {
        try {
            $out = & $cmd --version 2>&1
            if ($out -match "Python (\d+)\.(\d+)") {
                if ([int]$Matches[1] -ge 3 -and [int]$Matches[2] -ge 9) {
                    return $cmd
                }
            }
        } catch {}
    }
    return $null
}

# --- Verificar paquete ---
function Check-Pkg {
    if (-not (Test-Path (Join-Path $BASE "hldemstego\__main__.py"))) {
        Show-Banner
        WErr "No se encontro la carpeta hldemstego\ en:"
        Write-Host "    $BASE" -ForegroundColor $CY
        Write-Host ""
        Write-Host "  Estructura esperada:" -ForegroundColor $CD
        Write-Host "    HLdemStego\"
        Write-Host "      ABRIR.cmd"
        Write-Host "      hldemstego.ps1"
        Write-Host "      hldemstego\"
        Write-Host "        __main__.py"
        Write-Host "        pipeline.py  ..."
        Write-Host ""
        Read-Host "  Enter para salir" | Out-Null
        exit 1
    }
}

# ================================================================
#  CALCULAR
# ================================================================
function Run-Calcular {
    Show-Banner
    Write-Host "  CALCULAR - Cuanto tiene que durar la demo" -ForegroundColor $CC
    HR2
    Write-Host ""
    $f = Ask-Val "Archivo a analizar (ruta completa)"
    if (-not $f) { return }
    if (-not (Test-Path $f)) { WErr "No se encuentra: $f"; Pause-Back; return }
    Write-Host ""
    Set-Location $BASE
    try {
        & $PYTHON calcular.py $f
    } catch { WErr "Error: $_" }
    Pause-Back
}

# ================================================================
#  ENCODE
# ================================================================
function Run-Encode {
    while ($true) {
        Show-Banner
        Write-Host "  CIFRAR - Ocultar archivo dentro de un .dem" -ForegroundColor $CC
        HR2
        Write-Host ""
        Write-Host "  Podes arrastrar archivos a esta ventana para pegar la ruta." -ForegroundColor $CD
        Write-Host "  Deja vacio y Enter para volver al menu." -ForegroundColor $CD
        Write-Host ""

        $file = Ask-Val "Archivo a ocultar"
        if (-not $file) { return }
        if (-not (Test-Path $file)) { WErr "No se encuentra: $file"; Pause-Back; continue }
        $sz = (Get-Item $file).Length
        WOk "Encontrado: $(Split-Path -Leaf $file) ($sz bytes)"

        $baseDem = Ask-Val "Demo base .dem (sin modificar)"
        if (-not $baseDem) { return }
        if (-not (Test-Path $baseDem)) { WErr "No se encuentra: $baseDem"; Pause-Back; continue }
        $dsz = [int]((Get-Item $baseDem).Length / 1KB)
        WOk "Demo: $(Split-Path -Leaf $baseDem) (${dsz} KB)"

        $outDem = Ask-Val "Demo de salida (nueva .dem cifrada)"
        if (-not $outDem) { return }

        Write-Host ""
        Write-Host ""
        Write-Host "  SEGURIDAD:" -ForegroundColor $CW
        Write-Host "  La clave = movimientos del jugador en la demo (frames CLIENTDATA)." -ForegroundColor $CD
        Write-Host "  Si la demo es de servidor online y falla, usa una password." -ForegroundColor $CY
        Write-Host "  Con demos grabadas en offline (LAN/training) funciona sin password." -ForegroundColor $CD
        $pw = Ask-Val "Password (Enter para omitir, recomendada si la demo es online)" ""

        Write-Host ""
        Write-Host "  Opciones avanzadas (Enter = default):" -ForegroundColor $CD
        $dci   = Ask-Val "democmdinfo-size" "164"
        $force = Ask-Val "Forzar aunque la demo sea corta? s/N" "N"

        Write-Host ""
        HR2
        WInf "Ejecutando encode..."
        HR2
        Write-Host ""

        Set-Location $BASE
        try {
            $args2 = @("encode", $file, $baseDem, $outDem, "--democmdinfo-size", $dci)
            if ($pw) { $args2 += "--password"; $args2 += $pw }
            if ($force -match "^[sySY]") { $args2 += "--force" }
            & $PYTHON -m hldemstego @args2
            Write-Host ""
            HR2
            if ($LASTEXITCODE -eq 0) {
                WOk "Demo cifrada guardada en: $outDem"
            } else {
                WErr "El encode termino con codigo $LASTEXITCODE"
            }
        } catch { WErr "Error inesperado: $_" }
        Pause-Back; return
    }
}

# ================================================================
#  DECODE
# ================================================================
function Run-Decode {
    while ($true) {
        Show-Banner
        Write-Host "  DESCIFRAR - Extraer archivo de un .dem cifrado" -ForegroundColor $CC
        HR2
        Write-Host ""

        $stego = Ask-Val "Demo cifrada .dem (procesada por HLdemStego)"
        if (-not $stego) { return }
        if (-not (Test-Path $stego)) { WErr "No se encuentra: $stego"; Pause-Back; continue }
        $dsz = [int]((Get-Item $stego).Length / 1KB)
        WOk "Demo: $(Split-Path -Leaf $stego) (${dsz} KB)"

        $outDir = Ask-Val "Carpeta donde guardar el archivo recuperado" "."
        if (-not $outDir) { $outDir = "." }
        if (-not (Test-Path $outDir)) { New-Item -ItemType Directory -Path $outDir | Out-Null }

        Write-Host ""
        Write-Host "  Si se uso password en el encode, ingresala ahora." -ForegroundColor $CD
        $pw2 = Ask-Val "Password (Enter si no se uso ninguna)" ""

        $dci = Ask-Val "democmdinfo-size" "164"

        Write-Host ""
        HR2
        WInf "Ejecutando decode..."
        HR2
        Write-Host ""

        Set-Location $BASE
        try {
            $dargs = @("decode", $stego, $outDir, "--democmdinfo-size", $dci)
            if ($pw2) { $dargs += "--password"; $dargs += $pw2 }
            & $PYTHON -m hldemstego @dargs
            Write-Host ""
            HR2
            if ($LASTEXITCODE -eq 0) {
                WOk "Archivo recuperado en: $outDir"
            } else {
                WErr "El decode termino con codigo $LASTEXITCODE"
            }
        } catch { WErr "Error inesperado: $_" }
        Pause-Back; return
    }
}

# ================================================================
#  INSPECT
# ================================================================
function Run-Inspect {
    Show-Banner
    Write-Host "  INSPECCIONAR - Ver tokens DC:* dentro de un demo" -ForegroundColor $CC
    HR2
    Write-Host ""

    $dem = Ask-Val "Demo a inspeccionar"
    if (-not $dem) { return }
    if (-not (Test-Path $dem)) { WErr "No se encuentra: $dem"; Pause-Back; return }
    $n   = Ask-Val "Cuantos tokens mostrar" "20"
    $dci = Ask-Val "democmdinfo-size" "164"

    Write-Host ""
    HR2
    Set-Location $BASE
    try {
        & $PYTHON -m hldemstego inspect $dem --show-frames $n --democmdinfo-size $dci
    } catch { WErr "Error: $_" }
    Pause-Back
}

# ================================================================
#  TESTS
# ================================================================
function Run-Tests {
    Show-Banner
    Write-Host "  TESTS - Verificar que todo funciona (28 tests)" -ForegroundColor $CC
    HR2
    Write-Host ""
    WInf "Corriendo tests unitarios..."
    Write-Host ""
    Set-Location $BASE
    try {
        & $PYTHON -m unittest discover tests/ -v
        Write-Host ""
        if ($LASTEXITCODE -eq 0) { WOk "Todos los tests pasaron." }
        else { WErr "Algunos tests fallaron." }
    } catch { WErr "Error: $_" }
    Pause-Back
}

# ================================================================
#  AYUDA
# ================================================================
function Run-Ayuda {
    Show-Banner
    Write-Host "  AYUDA - Flags, ejemplos y uso desde consola" -ForegroundColor $CC
    HR2
    Write-Host ""
    Set-Location $BASE
    & $PYTHON -m hldemstego --help
    Write-Host ""
    HR2
    Write-Host ""
    Write-Host "  FLAGS AVANZADOS:" -ForegroundColor $CW
    Write-Host "    --democmdinfo-size N   (default 164, probar 0 / 56 / 208)" -ForegroundColor $CD
    Write-Host "    --force                Ignorar advertencia de demo corta" -ForegroundColor $CD
    Write-Host "    --chunk-size N         Chars Base64 por fragmento (max 80)" -ForegroundColor $CD
    Write-Host ""
    Write-Host "  EJEMPLOS DESDE POWERSHELL (sin menu):" -ForegroundColor $CW
    Write-Host '    .\hldemstego.ps1 encode secreto.txt base.dem salida.dem' -ForegroundColor $CG
    Write-Host '    .\hldemstego.ps1 decode salida.dem C:\recuperado\' -ForegroundColor $CG
    Write-Host '    .\hldemstego.ps1 inspect salida.dem --show-frames 50' -ForegroundColor $CG
    Write-Host ""
    Write-Host "  LOS DC:* EN EL JUEGO:" -ForegroundColor $CW
    Write-Host "    Al reproducir con 'viewdemo salida' en CS 1.6 aparecen en el" -ForegroundColor $CD
    Write-Host ""
    HR2
    Pause-Back
}

# ================================================================
#  MENU PRINCIPAL
# ================================================================
function Show-Menu {
    $pyver = & $PYTHON --version 2>&1
    Show-Banner
    Write-Host "  Python : $pyver" -ForegroundColor $CD
    Write-Host "  Carpeta: $BASE" -ForegroundColor $CD
    Write-Host ""
    HR2
    Write-Host "  Que queres hacer?" -ForegroundColor $CW
    HR2
    Write-Host "  [1]  CALCULAR     - Ver cuanto tiene que durar la demo" -ForegroundColor $CW
    Write-Host "  [2]  CIFRAR       - Ocultar archivo en un .dem" -ForegroundColor $CW
    Write-Host "  [3]  DESCIFRAR    - Extraer archivo de un .dem cifrado" -ForegroundColor $CW
    Write-Host "  [4]  INSPECCIONAR - Ver tokens DC:* en cualquier demo" -ForegroundColor $CW
    Write-Host "  [5]  TESTS        - Verificar instalacion (28 tests)" -ForegroundColor $CW
    Write-Host "  [6]  AYUDA        - Flags, ejemplos, info del proyecto" -ForegroundColor $CW
    Write-Host "  [7]  SALIR" -ForegroundColor $CW
    HR2
    Write-Host ""
    Write-Host "  Opcion: " -NoNewline -ForegroundColor $CW
    return (Read-Host).Trim()
}

# ================================================================
#  INICIO
# ================================================================
$PYTHON = Find-Python
if (-not $PYTHON) {
    Show-Banner
    WErr "No se encontro Python 3.9+ instalado."
    Write-Host ""
    Write-Host "  Descargalo en: https://www.python.org/downloads/" -ForegroundColor $CY
    Write-Host "  Durante la instalacion, marca 'Add Python to PATH'." -ForegroundColor $CY
    Write-Host ""
    Read-Host "  Enter para salir" | Out-Null
    exit 1
}
Check-Pkg

# Passthrough: si se pasan argumentos directos, ejecutar sin menu
#   .\hldemstego.ps1 encode archivo.txt base.dem salida.dem
if ($args.Count -gt 0) {
    Set-Location $BASE
    & $PYTHON -m hldemstego @args
    exit $LASTEXITCODE
}

# Loop del menu
while ($true) {
    $opt = Show-Menu
    switch ($opt) {
        "1" { Run-Calcular }
        "2" { Run-Encode   }
        "3" { Run-Decode   }
        "4" { Run-Inspect  }
        "5" { Run-Tests    }
        "6" { Run-Ayuda    }
        "7" {
            Show-Banner
            Write-Host "  Hasta luego!" -ForegroundColor $CG
            Write-Host ""
            Start-Sleep -Seconds 1
            exit 0
        }
        default {
            WWrn "Opcion invalida. Escribi un numero del 1 al 7."
            Start-Sleep -Seconds 1
        }
    }
}

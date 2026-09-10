# ============================================================
#  Publicacion AUTOMATICA (desatendida) del Dashboard Ejecutivo
#  en GitHub Pages.
#
#  Pensado para el Programador de tareas de Windows. Se ejecuta
#  sin ventanas ni pausas y deja registro en LOGS\publicacion_web.log
#
#  Solo LEE la base de datos y publica index.html.
#  Nunca modifica el repositorio documental original.
# ============================================================

$ErrorActionPreference = 'Continue'

$raiz   = Split-Path -Parent $MyInvocation.MyCommand.Path
$logDir = Join-Path $raiz 'LOGS'
$log    = Join-Path $logDir 'publicacion_web.log'
$python = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'

if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }

# Git y GitHub CLI deben estar en PATH aunque la tarea corra sin perfil cargado.
$env:PATH = (Join-Path $env:LOCALAPPDATA 'Programs\Git\cmd') + ';' +
            (Join-Path $env:LOCALAPPDATA 'Programs\GitHubCLI\bin') + ';' + $env:PATH
# Nunca pedir credenciales por consola: si faltan, debe fallar limpio.
$env:GIT_TERMINAL_PROMPT = '0'

function Escribir($texto) {
    $linea = "[{0}] {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $texto
    Add-Content -Path $log -Value $linea -Encoding utf8
}

Add-Content -Path $log -Value "" -Encoding utf8
Add-Content -Path $log -Value "============================================================" -Encoding utf8
Escribir "Iniciando publicacion automatica"

# --- 1. Regenerar el dashboard desde la base de datos ---------------------
Set-Location (Join-Path $raiz 'SISTEMA')
$salida = & $python 'generar_dashboard_ejecutivo.py' 2>&1
$salida | ForEach-Object { Add-Content -Path $log -Value "    $_" -Encoding utf8 }
if ($LASTEXITCODE -ne 0) {
    Escribir "ERROR: fallo la generacion del dashboard (codigo $LASTEXITCODE)."
    exit 1
}

# --- 2. Publicar solo si hubo cambios -------------------------------------
Set-Location $raiz

$pendientes = & git status --porcelain
if (-not $pendientes) {
    Escribir "Sin cambios en los datos: no se publica nada."
    exit 0
}

& git add -A 2>&1 | ForEach-Object { Add-Content -Path $log -Value "    $_" -Encoding utf8 }

$mensaje = "Actualizacion automatica del dashboard - {0}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm')
& git commit -m $mensaje 2>&1 | ForEach-Object { Add-Content -Path $log -Value "    $_" -Encoding utf8 }
if ($LASTEXITCODE -ne 0) {
    Escribir "ERROR: no se pudo registrar el commit (codigo $LASTEXITCODE)."
    exit 1
}

# --quiet/--no-progress evitan que git escriba barras de progreso en una
# consola que no existe cuando la tarea corre desatendida.
$commitLocal = (& git rev-parse HEAD).Trim()
& git push --quiet --no-progress origin main 2>&1 | ForEach-Object { Add-Content -Path $log -Value "    $_" -Encoding utf8 }

# No se confia en el codigo de salida de git: bajo el Programador de tareas el
# proceso puede morir DESPUES de haber subido correctamente (deja un codigo de
# error enganoso). Se comprueba contra el servidor cual es el estado real.
$commitRemoto = ''
try {
    $ref = & git ls-remote origin refs/heads/main 2>&1
    if ($ref -match '^([0-9a-f]{40})') { $commitRemoto = $Matches[1] }
} catch { }

if ($commitRemoto -eq $commitLocal) {
    Escribir "Publicacion completada correctamente ($($commitLocal.Substring(0,7))): https://rossemarysanmartin.github.io/SISTEMA_SEGUIMIENTO_CONVENIOS/"
    exit 0
}

Escribir "ERROR: el servidor no tiene el ultimo commit (local $($commitLocal.Substring(0,7)) / remoto $(if($commitRemoto){$commitRemoto.Substring(0,7)}else{'desconocido'})). Ejecute publicar_web.bat manualmente."
exit 1

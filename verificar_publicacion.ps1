# ============================================================
#  Cierre y verificacion de la publicacion automatica.
#
#  Se ejecuta como SEGUNDA accion de la tarea programada.
#
#  Motivo: en este equipo el proceso de git puede ser terminado de
#  forma abrupta cuando corre desde el Programador de tareas (deja
#  codigos de error enganosos y a veces se corta antes de confirmar
#  los cambios). Por eso este paso NO se limita a mirar: termina el
#  trabajo que haya quedado a medias y solo entonces informa.
#
#  Es idempotente: si no hay nada pendiente, no hace nada.
# ============================================================

$raiz = Split-Path -Parent $MyInvocation.MyCommand.Path
$log  = Join-Path $raiz 'LOGS\publicacion_web.log'

$env:PATH = (Join-Path $env:LOCALAPPDATA 'Programs\Git\cmd') + ';' + $env:PATH
$env:GIT_TERMINAL_PROMPT = '0'

function Escribir($texto) {
    $linea = "[{0}] {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $texto
    Add-Content -Path $log -Value $linea -Encoding utf8
}

# Los comandos de git se ejecutan a traves de cmd para que su salida de
# error quede contenida en el archivo de log y no se mezcle con el flujo
# de errores de PowerShell.
function Git($argumentos) {
    cmd /c "git $argumentos >> `"$log`" 2>&1"
}

Set-Location $raiz

function CommitRemoto {
    $ref = cmd /c "git ls-remote origin refs/heads/main 2>nul"
    if ($ref -match '([0-9a-f]{40})') { return $Matches[1] }
    return ''
}

# --- 1. Confirmar lo que haya quedado sin registrar -----------------------
$pendientes = cmd /c "git status --porcelain 2>nul"
if ($pendientes) {
    Escribir "Habia cambios sin confirmar: completando el registro."
    Git "add -A"
    $mensaje = "Actualizacion automatica del dashboard - {0}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm')
    Git "commit -m ""$mensaje"""
}

# --- 2. Subir si el servidor esta atrasado --------------------------------
$local  = (cmd /c "git rev-parse HEAD 2>nul").Trim()
$remoto = CommitRemoto

if ($remoto -ne $local) {
    Git "push --quiet --no-progress origin main"
    $remoto = CommitRemoto
}

# --- 3. Informar el estado real -------------------------------------------
$sucio = cmd /c "git status --porcelain 2>nul"

if ($remoto -eq $local -and -not $sucio) {
    Escribir "VERIFICADO: publicado correctamente ($($local.Substring(0,7))). https://rossemarysanmartin.github.io/SISTEMA_SEGUIMIENTO_CONVENIOS/"
    exit 0
}

if ($sucio) {
    Escribir "ERROR: quedaron cambios sin confirmar. Ejecute publicar_web.bat manualmente."
} else {
    Escribir "ERROR: el servidor no recibio el ultimo commit (local $($local.Substring(0,7)) / remoto $(if($remoto){$remoto.Substring(0,7)}else{'desconocido'}))."
}
exit 1

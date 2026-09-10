@echo off
chcp 65001 > nul
REM ============================================================
REM  Publicacion AUTOMATICA (desatendida) del Dashboard Ejecutivo
REM  en GitHub Pages. Pensado para el Programador de tareas de
REM  Windows: no muestra ventanas de pausa y deja registro en
REM  LOGS\publicacion_web.log
REM
REM  Solo LEE la base de datos y publica index.html.
REM  Nunca modifica el repositorio documental original.
REM ============================================================

set "PATH=%LOCALAPPDATA%\Programs\Git\cmd;%LOCALAPPDATA%\Programs\GitHubCLI\bin;%PATH%"
set "RAIZ=%~dp0"
set "LOG=%RAIZ%LOGS\publicacion_web.log"

if not exist "%RAIZ%LOGS" mkdir "%RAIZ%LOGS"

echo. >> "%LOG%"
echo ============================================================ >> "%LOG%"
echo [%date% %time%] Iniciando publicacion automatica >> "%LOG%"

cd /d "%RAIZ%SISTEMA"
"%LOCALAPPDATA%\Programs\Python\Python312\python.exe" generar_dashboard_ejecutivo.py >> "%LOG%" 2>&1
if errorlevel 1 (
    echo [%date% %time%] ERROR: fallo la generacion del dashboard. >> "%LOG%"
    exit /b 1
)

cd /d "%RAIZ%"

git diff --quiet && git diff --cached --quiet
if errorlevel 1 (
    git add -A >> "%LOG%" 2>&1
    git commit -m "Actualizacion automatica del dashboard - %date% %time%" >> "%LOG%" 2>&1
    git push origin main >> "%LOG%" 2>&1
    if errorlevel 1 (
        echo [%date% %time%] ERROR: no se pudo subir a GitHub. Revise la conexion. >> "%LOG%"
        exit /b 1
    )
    echo [%date% %time%] Publicacion completada correctamente. >> "%LOG%"
) else (
    echo [%date% %time%] Sin cambios en los datos: no se publica nada. >> "%LOG%"
)

exit /b 0

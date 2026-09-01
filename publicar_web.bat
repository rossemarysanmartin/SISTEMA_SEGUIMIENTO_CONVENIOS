@echo off
chcp 65001 > nul
title Publicar Convenios en GitHub Pages

echo ============================================================
echo   SISTEMA DE SEGUIMIENTO DE CONVENIOS - UTMACH
echo   Actualizando y Publicando en GitHub Pages...
echo ============================================================
echo.

set "PATH=%LOCALAPPDATA%\Programs\Git\cmd;%LOCALAPPDATA%\Programs\GitHubCLI\bin;%PATH%"

echo [1/3] Generando Dashboard Ejecutivo actualizado...
cd /d "%~dp0SISTEMA"
"%LOCALAPPDATA%\Programs\Python\Python312\python.exe" generar_dashboard_ejecutivo.py
if errorlevel 1 (
    echo [ERROR] Fall¢ la generaci¢n del dashboard.
    pause
    exit /b %errorlevel%
)

cd /d "%~dp0"

echo.
echo [2/3] Preparando cambios para GitHub...
git add .
git diff-index --quiet HEAD
if errorlevel 1 (
    git commit -m "Actualizacion automatica convenios - %date% %time%"
) else (
    echo No hay cambios nuevos en los datos.
)

echo.
echo [3/3] Subiendo cambios a GitHub Pages...
git push origin main
if errorlevel 1 (
    echo [ERROR] No se pudo subir a GitHub. Revisa tu conexion a Internet.
    pause
    exit /b %errorlevel%
)

echo.
echo ============================================================
echo   ≠PUBLICACI‡N COMPLETADA CON êXITO!
echo   Tu web actualizada est† disponible en:
echo   https://rossemarysanmartin.github.io/SISTEMA_SEGUIMIENTO_CONVENIOS/
echo ============================================================
echo.
pause

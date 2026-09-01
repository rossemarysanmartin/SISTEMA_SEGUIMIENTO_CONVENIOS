@echo off
chcp 65001 > nul
title Sistema de Seguimiento de Convenios - UTMACH

echo ============================================================
echo   SISTEMA DE SEGUIMIENTO DE CONVENIOS - UTMACH
echo   Iniciando aplicacion local...
echo ============================================================
echo.

set "PATH=%LOCALAPPDATA%\Programs\Git\cmd;%LOCALAPPDATA%\Programs\GitHubCLI\bin;%PATH%"

cd /d "%~dp0SISTEMA"

echo Abriendo navegador en http://127.0.0.1:5000 ...
start http://127.0.0.1:5000

echo.
echo Ejecutando servidor Flask (Presiona Ctrl+C para detenerlo)...
"%LOCALAPPDATA%\Programs\Python\Python312\python.exe" app.py

pause

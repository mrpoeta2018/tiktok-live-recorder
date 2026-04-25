@echo off
chcp 65001 >nul
title TikTok Live Recorder

:: ---- Buscar Python -----------------------------------------------
set PYTHON=

python --version >nul 2>&1
if not errorlevel 1 ( set "PYTHON=python" & goto :check_deps )

for %%V in (313 312 311 310 39 38) do (
    if exist "%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe" (
        set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe"
        goto :check_deps
    )
)
for %%V in (313 312 311 310 39 38) do (
    if exist "C:\Python%%V\python.exe" (
        set "PYTHON=C:\Python%%V\python.exe"
        goto :check_deps
    )
)

echo.
echo  ERROR: Python no encontrado en tu PC
echo.
echo  1. Ve a https://python.org/downloads
echo  2. Descarga Python 3.12
echo  3. Al instalar: marca "Add to PATH"
echo  4. Vuelve a ejecutar INICIAR.bat
echo.
pause
exit /b 1

:check_deps
:: ---- Verificar dependencias, instalar si faltan ------------------
"%PYTHON%" -c "import streamlink, demucs, librosa, tkinterdnd2" >nul 2>&1
if errorlevel 1 (
    echo.
    echo  Faltan dependencias. Instalando automaticamente...
    echo  Esto solo ocurre la primera vez.
    echo.
    call "%~dp0instalar.bat" /auto
    if errorlevel 1 (
        echo.
        echo  La instalacion automatica fallo.
        echo  Ejecuta instalar.bat manualmente y vuelve a intentar.
        echo.
        pause
        exit /b 1
    )
)

:: ---- Lanzar app --------------------------------------------------
cd /d "%~dp0"
"%PYTHON%" app.py
if errorlevel 1 (
    echo.
    echo  Ocurrio un error inesperado.
    echo  Intenta ejecutar instalar.bat y volver a intentar.
    echo.
    pause
)

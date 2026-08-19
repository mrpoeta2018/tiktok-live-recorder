@echo off
chcp 65001 >nul
title Instalador - TikTok Live Recorder

set AUTO=0
if "%1"=="/auto" set AUTO=1

if %AUTO%==0 (
    cls
    echo.
    echo  TikTok Live Recorder -- Instalador
    echo  Instala todo lo necesario. Solo debes hacerlo UNA VEZ.
    echo.
    echo  Presiona cualquier tecla para comenzar...
    pause >nul
)

:: ---- Buscar Python -----------------------------------------------
set PYTHON=

python --version >nul 2>&1
if not errorlevel 1 ( set "PYTHON=python" & goto :instalar )

for %%V in (313 312 311 310 39 38) do (
    if exist "%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe" (
        set "PYTHON=%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe"
        goto :instalar
    )
)
for %%V in (313 312 311 310 39 38) do (
    if exist "C:\Python%%V\python.exe" (
        set "PYTHON=C:\Python%%V\python.exe"
        goto :instalar
    )
)

echo.
echo  ERROR: Python no encontrado.
echo  Descarga Python 3.12 desde https://python.org
echo  Al instalar, marca "Add Python to PATH"
echo.
if %AUTO%==0 pause
exit /b 1

:instalar
if "%PYTHON%"=="" (
    echo  ERROR: No se pudo determinar la ruta de Python.
    if %AUTO%==0 pause
    exit /b 1
)

echo.
echo  Verificando motor de audio FFmpeg...
ffmpeg -version >nul 2>&1
if errorlevel 1 (
    echo  FFmpeg no encontrado. Instalando automaticamente...
    winget install ffmpeg --accept-package-agreements --accept-source-agreements
) else (
    echo  FFmpeg detectado.
)

echo.
echo  Python encontrado: %PYTHON%
echo.
echo  [1/6] Actualizando pip...
"%PYTHON%" -m pip install --upgrade pip >nul 2>&1

echo  [2/6] Instalando yt-dlp...
"%PYTHON%" -m pip install yt-dlp --upgrade >nul 2>&1

echo  [3/6] Instalando streamlink...
"%PYTHON%" -m pip install streamlink --upgrade >nul 2>&1

echo  [4/6] Instalando soporte TikTok...
"%PYTHON%" -m pip install curl_cffi --upgrade >nul 2>&1

echo  [5/6] Instalando Demucs + PyTorch (esto puede tardar varios minutos)...
"%PYTHON%" -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
"%PYTHON%" -m pip install demucs
"%PYTHON%" -m pip install "numpy<2" soundfile sounddevice

echo  [6/6] Instalando librosa...
"%PYTHON%" -m pip install librosa >nul 2>&1

echo  [7/8] Instalando soporte drag y drop...
"%PYTHON%" -m pip install tkinterdnd2 >nul 2>&1

echo  [8/9] Instalando Whisper para transcripcion de voz...
"%PYTHON%" -m pip install faster-whisper >nul 2>&1

echo  [9/9] Instalando soporte de metadatos MP3...
"%PYTHON%" -m pip install mutagen >nul 2>&1

echo.
echo  Verificando instalacion...
"%PYTHON%" -c "import streamlink, demucs, librosa, soundfile, sounddevice, tkinterdnd2; print('OK')"
if errorlevel 1 (
    echo.
    echo  ADVERTENCIA: Alguna dependencia no se instalo correctamente.
    echo  Intenta ejecutar este archivo como Administrador.
    echo.
    if %AUTO%==0 pause
    exit /b 1
)

echo.
if %AUTO%==0 (
    echo  Instalacion completada.
    echo  Ahora ejecuta INICIAR.bat para usar la app.
    echo.
    pause
)

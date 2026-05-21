@echo off
setlocal

cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
    echo Python launcher "py" is not installed.
    echo Install Python 3.10 or newer from https://www.python.org/downloads/windows/
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    py -3.11 -m venv .venv
    if errorlevel 1 py -3 -m venv .venv
)

call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip
python -m pip install -r "Test_generator\requirements.txt" pyinstaller

cd Test_generator
pyinstaller --noconfirm "ИИ-помощник учителя.spec"
if errorlevel 1 (
    echo.
    echo Build failed.
    pause
    exit /b 1
)

set "APP_DIR=dist\ИИ-помощник учителя"
if not exist "%APP_DIR%\models" mkdir "%APP_DIR%\models"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p = Join-Path $env:APP_DIR 'models\PUT-GGUF-MODEL-HERE.txt'; 'Put a .gguf model file in this folder. The app will find it and load it automatically on next start.' | Set-Content -LiteralPath $p -Encoding UTF8"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Compress-Archive -Path $env:APP_DIR -DestinationPath '..\СКАЧАТЬ-ГОТОВОЕ-ПРИЛОЖЕНИЕ-windows.zip' -Force"

echo.
echo Done: Test_generator\dist\ИИ-помощник учителя\ИИ-помощник учителя.exe
echo ZIP:  СКАЧАТЬ-ГОТОВОЕ-ПРИЛОЖЕНИЕ-windows.zip
pause

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
python -m pip install "PySide6>=6.6.0" "python-docx>=1.1.0" "pypdf>=4.0.0" pyinstaller cmake ninja
set "FORCE_CMAKE=1"
set "CMAKE_ARGS=-DGGML_NATIVE=OFF -DGGML_AVX=OFF -DGGML_AVX2=OFF -DGGML_AVX512=OFF -DGGML_AVX512_VBMI=OFF -DGGML_AVX512_VNNI=OFF -DGGML_FMA=OFF -DGGML_F16C=OFF -DGGML_CUDA=OFF -DGGML_BLAS=OFF"
python -m pip install --force-reinstall --no-cache-dir --no-binary=llama-cpp-python llama-cpp-python==0.3.23

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

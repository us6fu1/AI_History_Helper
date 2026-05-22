@echo off
chcp 65001 >nul
echo ================================================
echo   Установка зависимостей (CPU-сборка)
echo ================================================
echo.

:: Проверяем Python
python --version 2>nul
if errorlevel 1 (
    echo [ОШИБКА] Python не найден. Установите Python 3.10+
    echo Скачать: https://www.python.org/downloads/
    pause
    exit /b 1
)

echo [1/5] Обновление pip...
python -m pip install --upgrade pip

echo.
echo [2/5] Установка PySide6 (интерфейс)...
pip install "PySide6>=6.6.0"

echo.
echo [3/5] Установка python-docx (экспорт Word)...
pip install "python-docx>=1.1.0"

echo.
echo [4/5] Установка llama-cpp-python (CPU-версия)...
set "FORCE_CMAKE=1"
set "CMAKE_ARGS=-DGGML_NATIVE=OFF -DGGML_AVX=OFF -DGGML_AVX2=OFF -DGGML_AVX512=OFF -DGGML_AVX512_VBMI=OFF -DGGML_AVX512_VNNI=OFF -DGGML_FMA=OFF -DGGML_F16C=OFF -DGGML_CUDA=OFF -DGGML_BLAS=OFF"
pip install --upgrade --no-cache-dir --no-binary=llama-cpp-python "llama-cpp-python==0.3.23"
if errorlevel 1 (
    echo [ОШИБКА] Не удалось установить llama-cpp-python.
    echo Проверьте версию Python (3.10/3.11/3.12), Visual Studio Build Tools и доступ к интернету.
    echo Установщик собирает совместимую CPU-версию без AVX/AVX2/FMA/F16C.
    pause
    exit /b 1
)

echo.
echo [5/5] Создание папки для моделей...
if not exist "%~dp0..\models" mkdir "%~dp0..\models"

echo.
echo ================================================
echo   Установка завершена!
echo ================================================
echo.
echo ТЕКУЩАЯ МОДЕЛЬ ПРОЕКТА:
echo   models\Qwen3.5-4B.Q4_K_M.gguf  (~2.5 GB)
echo.
echo Если файла нет — положите туда любой Qwen-GGUF в формате Q4_K_M.
echo Запасные варианты, проверенные с этим кодом:
echo   - Qwen2.5-3B-Instruct-Q4_K_M.gguf  (~2 GB)   — для слабого CPU
echo   - Qwen2.5-7B-Instruct-Q4_K_M.gguf  (~4.5 GB) — если есть 16 GB RAM и время
echo.
echo Запуск: выполните в этой папке (Test_generator)  python main.py
echo Описание: README.md здесь же.
echo.
pause

#!/bin/bash
# Установка зависимостей для Генератора тестов по истории
# Linux / macOS

echo "================================================"
echo "  Установка зависимостей для Генератора тестов"
echo "================================================"
echo ""

# Проверяем Python
if ! command -v python3 &> /dev/null; then
    echo "[ОШИБКА] Python3 не найден. Установите Python 3.10+"
    echo "Ubuntu/Debian: sudo apt install python3 python3-pip"
    echo "macOS: brew install python3"
    exit 1
fi

python3 --version
echo ""

echo "[1/4] Обновление pip..."
python3 -m pip install --upgrade pip

echo ""
echo "[2/4] Установка PySide6 (интерфейс)..."
pip3 install PySide6

echo ""
echo "[3/4] Установка python-docx (экспорт Word)..."
pip3 install python-docx

echo ""
echo "[4/4] Установка llama-cpp-python..."
echo ""
echo "Выберите вариант:"
echo "  1) Только CPU"
echo "  2) С CUDA (NVIDIA GPU)"
echo "  3) С Metal (Apple Silicon)"
read -p "Ваш выбор (1/2/3): " choice

case $choice in
    2)
        echo "Установка с CUDA..."
        CMAKE_ARGS="-DLLAMA_CUDA=on" pip3 install llama-cpp-python
        ;;
    3)
        echo "Установка с Metal (Apple Silicon)..."
        CMAKE_ARGS="-DLLAMA_METAL=on" pip3 install llama-cpp-python
        ;;
    *)
        echo "Установка CPU-версии..."
        pip3 install llama-cpp-python
        ;;
esac

echo ""
echo "================================================"
echo "  Установка завершена!"
echo "================================================"
echo ""
echo "Скачайте GGUF-модель:"
echo "  https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF"
echo ""
echo "Запуск: python3 main.py"
echo "Описание: см. README.md в этой папке."

"""Shared filesystem paths for source runs and PyInstaller builds."""
from __future__ import annotations

import sys
import os
from pathlib import Path


APP_NAME = "ИИ-помощник учителя"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_resource_dir() -> Path:
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS")).resolve()
    return Path(__file__).resolve().parent


def repo_resource_dir() -> Path:
    if is_frozen():
        return app_resource_dir()
    return Path(__file__).resolve().parents[1]


def user_app_dir() -> Path:
    return Path.home() / "Documents" / APP_NAME


def user_data_dir() -> Path:
    custom = os.environ.get("AI_HISTORY_HELPER_DATA_DIR", "").strip()
    if custom:
        return Path(custom)
    return user_app_dir() / "data"


def default_models_dir() -> Path:
    return user_app_dir() / "Модели"


def default_export_dir() -> Path:
    return user_app_dir() / "Тесты Docx"

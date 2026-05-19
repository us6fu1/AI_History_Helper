"""
Главное окно PySide6; палитра и карточки — COLORS / make_card().
"""
import os
import sys
import json
import threading
import datetime
import logging
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox, QSpinBox,
    QTextEdit, QLineEdit, QFrame, QScrollArea,
    QFileDialog, QMessageBox, QStackedWidget,
    QSizePolicy, QProgressBar, QDialog,
    QDialogButtonBox, QFormLayout, QGroupBox,
    QCheckBox, QButtonGroup, QRadioButton,
    QListWidget, QListWidgetItem, QSplitter,
    QTabWidget, QApplication, QGraphicsDropShadowEffect,
    QInputDialog,
)
from PySide6.QtCore import (
    Qt, QThread, Signal, QSize, QTimer,
    QPropertyAnimation, QEasingCurve, QObject, QEvent,
)
from PySide6.QtGui import (
    QFont, QIcon, QPixmap, QPainter, QColor, QImage,
    QPen, QBrush, QFontMetrics, QCursor, QFontDatabase,
)

logger = logging.getLogger(__name__)


ASSETS_DIR = Path(__file__).parent / "assets"
ICONS_DIR = ASSETS_DIR / "icons"
LOGO_PATH = ASSETS_DIR / "logo.png"

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DOCX_EXPORT_SUBDIR = Path("Materials") / "Тесты Docx"
<<<<<<< HEAD
EXTERNAL_MODELS_DIR = Path.home() / "Documents" / "ИИ-помощник учителя" / "Модели"
=======
>>>>>>> 06236faa0a59c3fe63a9caebf58e61189dc30581


def pixmap_from_icon_file(icon_file: Path, target_side: int = 20) -> QPixmap:
    """
    Растровые форматы — через QPixmap.
    SVG — через QSvgRenderer: на части систем QPixmap не подхватывает SVG-плагин, иконки пропадают.
    """
    if not icon_file.exists():
        return QPixmap()
    pix = QPixmap(str(icon_file))
    if not pix.isNull():
        return pix.scaled(
            target_side,
            target_side,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    if icon_file.suffix.lower() != ".svg":
        return QPixmap()
    try:
        from PySide6.QtSvg import QSvgRenderer

        renderer = QSvgRenderer(str(icon_file))
        if not renderer.isValid():
            return QPixmap()
        sz = renderer.defaultSize()
        if sz.width() <= 0 or sz.height() <= 0:
            return QPixmap()
        pm = QPixmap(sz)
        pm.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pm)
        renderer.render(painter)
        painter.end()
        return pm.scaled(
            target_side,
            target_side,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    except Exception as e:
        logger.warning("Не удалось загрузить SVG-иконку %s: %s", icon_file, e)
        return QPixmap()


def default_docx_export_dir() -> str:
    """Папка экспорта по умолчанию: AI_Helper/Materials/Тесты Docx."""
    d = REPO_ROOT / DEFAULT_DOCX_EXPORT_SUBDIR
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError:
        logger.warning("Не удалось создать папку экспорта: %s", d)
    return str(d)


def icon_path(name: str) -> str:
    """Возвращает строковый путь к иконке (для QSS)."""
    p = ICONS_DIR / name
    return str(p).replace("\\", "/")


def load_icon(name: str) -> QIcon:
    """Создаёт QIcon из файла в assets/icons."""
    p = ICONS_DIR / name
    if not p.exists():
        return QIcon()
    if p.suffix.lower() == ".svg":
        pm = pixmap_from_icon_file(p, 64)
        return QIcon(pm) if not pm.isNull() else QIcon()
    return QIcon(str(p))


_LOGO_CACHE: dict[tuple, QPixmap] = {}
LOGO_OUTLINE_PATH = ASSETS_DIR / "logo_outline.png"


def _build_logo_outline_png() -> bool:
    """Однократно превращает logo.png (без альфы) в logo_outline.png
    (белый контур + альфа из яркости). Записывает в assets/."""
    if LOGO_OUTLINE_PATH.exists():
        return True
    if not LOGO_PATH.exists():
        return False

    src = QImage(str(LOGO_PATH))
    if src.isNull():
        return False
    src = src.convertToFormat(QImage.Format.Format_ARGB32)

    src = src.scaled(
        1024, 1024,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )

    w, h = src.width(), src.height()
    out = QImage(w, h, QImage.Format.Format_ARGB32)
    out.fill(Qt.GlobalColor.transparent)

    bytes_total = w * h * 4
    src_data = bytes(src.bits()[:bytes_total])
    out_arr = bytearray(bytes_total)

    for i in range(0, bytes_total, 4):
        sb, sg, sr = src_data[i], src_data[i + 1], src_data[i + 2]
        luma = (sr * 299 + sg * 587 + sb * 114) // 1000
        if luma < 80:
            a = 0
        elif luma > 230:
            a = 255
        else:
            a = int((luma - 80) * 255 / 150)
        out_arr[i]     = 255
        out_arr[i + 1] = 255
        out_arr[i + 2] = 255
        out_arr[i + 3] = a

    out.bits()[:bytes_total] = bytes(out_arr)
    return out.save(str(LOGO_OUTLINE_PATH), "PNG")


def tinted_pixmap(src_path: str, color: str, size: int = 64) -> QPixmap:
    """Возвращает QPixmap-силуэт указанного цвета.

    Использует preprocessed `logo_outline.png` (белый контур с альфой).
    Окрашивание делается через CompositionMode_SourceIn — быстро.
    """
    key = (color, size)
    cached = _LOGO_CACHE.get(key)
    if cached is not None and not cached.isNull():
        return cached

    if not _build_logo_outline_png():
        return QPixmap()

    base = QPixmap(str(LOGO_OUTLINE_PATH))
    if base.isNull():
        return QPixmap()

    base = base.scaled(
        size, size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )

    out = QPixmap(base.size())
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.drawPixmap(0, 0, base)
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    p.fillRect(out.rect(), QColor(color))
    p.end()

    _LOGO_CACHE[key] = out
    return out


def app_icon() -> QIcon:
    """
    Иконка приложения (окно и панель задач).

    На Windows панель задач лучше отрабатывает, если у QIcon есть явные записи
    16×16 … 256×256 (один файл .ico с одним кадром Qt иногда «теряется» как
    программная ассоциация к python.exe).
    """
<<<<<<< HEAD
    app_ico_file = ASSETS_DIR / "app.ico"
    fallback_ico_file = ASSETS_DIR / "logo.ico"
=======
    ico_file = ASSETS_DIR / "logo.ico"
>>>>>>> 06236faa0a59c3fe63a9caebf58e61189dc30581
    icon = QIcon()

    sizes = (16, 20, 24, 32, 40, 48, 64, 128, 256)

<<<<<<< HEAD
    if app_ico_file.exists():
        loaded = QIcon(str(app_ico_file))
        if not loaded.isNull():
            return loaded

    if fallback_ico_file.exists():
        loaded = QIcon(str(fallback_ico_file))
        if not loaded.isNull():
            return loaded

=======
>>>>>>> 06236faa0a59c3fe63a9caebf58e61189dc30581
    def append_from_png(path: Path) -> bool:
        nonlocal icon
        if not path.exists():
            return False
        original = QPixmap(str(path))
        if original.isNull():
            return False
        icon = QIcon()
        for sz in sizes:
            canvas = QPixmap(sz, sz)
            canvas.fill(Qt.GlobalColor.transparent)
            scaled = original.scaled(
                sz,
                sz,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            painter = QPainter(canvas)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            x = (sz - scaled.width()) // 2
            y = (sz - scaled.height()) // 2
            painter.drawPixmap(x, y, scaled)
            painter.end()
            icon.addPixmap(canvas)
        return True

    if append_from_png(LOGO_PATH):
        return icon

<<<<<<< HEAD
=======
    if ico_file.exists():
        loaded = QIcon(str(ico_file))
        if not loaded.isNull():
            return loaded

>>>>>>> 06236faa0a59c3fe63a9caebf58e61189dc30581
    if append_from_png(ASSETS_DIR / "logo_old_backup.png"):
        return icon

    return QIcon()


COLORS = {
    # Sidebar (тёмный графит)
    "sidebar_bg_top":     "#1F2125",
    "sidebar_bg_bottom":  "#16181B",
    "sidebar_hover":      "rgba(255,255,255,0.06)",
    "sidebar_active":     "rgba(255,255,255,0.09)",
    "sidebar_active_border": "rgba(255,255,255,0.14)",
    "sidebar_text":       "#E5E7EB",
    "sidebar_text_dim":   "#9CA0A8",
    "sidebar_separator":  "rgba(255,255,255,0.08)",

    # Main canvas
    "main_bg":            "#F4F5F7",
    "card_bg":            "#FFFFFF",
    "card_border":        "#E6E7EB",
    "card_border_strong": "#D9DBDF",

    # Accents (графит вместо фиолетового)
    "accent":             "#2D2F36",
    "accent_hover":       "#3A3C44",
    "accent_pressed":     "#1F2125",
    "accent_subtle":      "#EFF0F3",
    "accent_subtle_text": "#3A3C44",

    # Buttons
    "btn_inactive_bg":    "#FFFFFF",
    "btn_inactive_text":  "#2D2F36",
    "btn_inactive_border":"#D9DBDF",
    "btn_disabled_bg":    "#EDEEF1",
    "btn_disabled_text":  "#9CA0A8",

    # Text hierarchy
    "text_primary":       "#1A1B1F",
    "text_secondary":     "#4B4D54",
    "text_muted":         "#84868D",
    "text_on_accent":     "#FFFFFF",

    # Inputs
    "input_bg":           "#FFFFFF",
    "input_border":       "#D9DBDF",
    "input_border_focus": "#2D2F36",
    "input_text":         "#1A1B1F",

    # Status / states
    "status_bg":          "#F0F1F4",
    "status_border":      "#E0E2E6",
    "success":            "#1F7A41",
    "success_subtle":     "#E8F4ED",
    "success_border":     "#BEDEC9",
    "warning":            "#9A6300",
    "error":              "#B23A48",

    # Зелёные акценты (тон совпадает с индикатором модели)
    "green":              "#34A853",
    "green_hover":        "#2E9347",
    "green_pressed":      "#256E37",
    "green_subtle":       "#E9F6ED",
    "green_subtle_2":     "#D6EFDD",
    "green_border":       "#B6E0C0",
    "green_glow":         "rgba(52, 168, 83, 0.22)",
}

STYLE_CARD = f"""
    QFrame {{
        background-color: {COLORS['card_bg']};
        border: 1px solid {COLORS['card_border']};
        border-radius: 12px;
    }}
"""

STYLE_LABEL_TITLE = f"""
    QLabel {{
        color: {COLORS['text_primary']};
        font-size: 13px;
        font-weight: 600;
        background: transparent;
        border: none;
        letter-spacing: 0.1px;
    }}
"""

STYLE_LABEL_BODY = f"""
    QLabel {{
        color: {COLORS['text_secondary']};
        font-size: 12px;
        background: transparent;
        border: none;
    }}
"""

STYLE_LABEL_MUTED = f"""
    QLabel {{
        color: {COLORS['text_muted']};
        font-size: 11px;
        background: transparent;
        border: none;
    }}
"""

STYLE_INPUT = f"""
    QLineEdit, QTextEdit, QComboBox, QSpinBox {{
        background-color: {COLORS['input_bg']};
        color: {COLORS['input_text']};
        border: 1px solid {COLORS['input_border']};
        border-radius: 8px;
        padding: 8px 12px;
        font-size: 13px;
        font-weight: 500;
        selection-background-color: {COLORS['green']};
        selection-color: white;
    }}
    QLineEdit:hover, QTextEdit:hover, QComboBox:hover, QSpinBox:hover {{
        border-color: {COLORS['card_border_strong']};
    }}
    QLineEdit:focus, QTextEdit:focus, QSpinBox:focus, QComboBox:focus {{
        border: 1.5px solid {COLORS['green']};
        outline: none;
    }}
    QComboBox::drop-down {{
        subcontrol-origin: padding;
        subcontrol-position: top right;
        width: 28px;
        border: none;
        background: transparent;
    }}
    QComboBox::down-arrow {{
        image: url({icon_path('chevron-down.svg')});
        width: 14px;
        height: 14px;
    }}
    QComboBox QAbstractItemView {{
        background-color: {COLORS['card_bg']};
        color: {COLORS['text_primary']};
        border: 1px solid {COLORS['card_border_strong']};
        border-radius: 8px;
        selection-background-color: {COLORS['accent_subtle']};
        selection-color: {COLORS['text_primary']};
        font-size: 13px;
        padding: 4px;
        outline: 0;
    }}
    QSpinBox::up-button, QSpinBox::down-button {{
        width: 0px;
        height: 0px;
        border: none;
    }}
"""

STYLE_BTN_PRIMARY = f"""
    QPushButton {{
        background-color: {COLORS['accent']};
        color: {COLORS['text_on_accent']};
        border: 1px solid {COLORS['accent']};
        border-radius: 8px;
        padding: 10px 20px;
        font-size: 13px;
        font-weight: 600;
        letter-spacing: 0.2px;
    }}
    QPushButton:hover {{
        background-color: {COLORS['accent_hover']};
        border-color: {COLORS['accent_hover']};
    }}
    QPushButton:pressed {{
        background-color: {COLORS['accent_pressed']};
    }}
    QPushButton:disabled {{
        background-color: {COLORS['btn_disabled_bg']};
        color: {COLORS['btn_disabled_text']};
        border-color: {COLORS['card_border']};
        font-weight: 500;
    }}
"""

STYLE_BTN_SECONDARY = f"""
    QPushButton {{
        background-color: {COLORS['btn_inactive_bg']};
        color: {COLORS['btn_inactive_text']};
        border: 1px solid {COLORS['btn_inactive_border']};
        border-radius: 8px;
        padding: 8px 16px;
        font-size: 12px;
        font-weight: 500;
    }}
    QPushButton:hover {{
        background-color: {COLORS['green_subtle']};
        border-color: {COLORS['green_border']};
        color: {COLORS['green_pressed']};
    }}
    QPushButton:pressed {{
        background-color: {COLORS['green_subtle_2']};
    }}
    QPushButton:disabled {{
        background-color: {COLORS['btn_disabled_bg']};
        color: {COLORS['btn_disabled_text']};
        border-color: {COLORS['card_border']};
    }}
"""

STYLE_BTN_CTA = f"""
    QPushButton {{
        background-color: {COLORS['green']};
        color: {COLORS['text_on_accent']};
        border: 1px solid {COLORS['green_pressed']};
        border-radius: 10px;
        padding: 12px 22px;
        font-size: 13px;
        font-weight: 600;
        letter-spacing: 0.2px;
    }}
    QPushButton:hover {{
        background-color: {COLORS['green_hover']};
        border-color: {COLORS['green_pressed']};
    }}
    QPushButton:pressed {{
        background-color: {COLORS['green_pressed']};
    }}
    QPushButton:disabled {{
        background-color: {COLORS['btn_disabled_bg']};
        color: {COLORS['btn_disabled_text']};
        border-color: {COLORS['card_border']};
    }}
"""

STYLE_ASSISTANT_BUSY = f"""
    QProgressBar {{
        border: none;
        border-radius: 4px;
        background-color: {COLORS['green_subtle']};
        min-height: 6px;
        max-height: 6px;
    }}
    QProgressBar::chunk {{
        background-color: {COLORS['green']};
        border-radius: 4px;
    }}
"""

STYLE_BTN_TOGGLE_ACTIVE = f"""
    QPushButton {{
        background-color: {COLORS['accent']};
        color: {COLORS['text_on_accent']};
        border: 1px solid {COLORS['accent']};
        border-radius: 8px;
        padding: 8px 14px;
        font-size: 12px;
        font-weight: 600;
    }}
    QPushButton:hover {{
        background-color: {COLORS['accent_hover']};
        border-color: {COLORS['accent_hover']};
    }}
"""

STYLE_BTN_TOGGLE_INACTIVE = f"""
    QPushButton {{
        background-color: {COLORS['btn_inactive_bg']};
        color: {COLORS['text_secondary']};
        border: 1px solid {COLORS['btn_inactive_border']};
        border-radius: 8px;
        padding: 8px 14px;
        font-size: 12px;
        font-weight: 500;
    }}
    QPushButton:hover {{
        background-color: {COLORS['green_subtle']};
        border-color: {COLORS['green_border']};
        color: {COLORS['accent']};
    }}
"""

STYLE_SIDEBAR_BTN_ACTIVE = f"""
    QPushButton {{
        background-color: {COLORS['sidebar_active']};
        color: {COLORS['sidebar_text']};
        border: 1px solid {COLORS['sidebar_active_border']};
        border-left: 3px solid {COLORS['green']};
        border-radius: 10px;
        padding: 11px 14px 11px 12px;
        font-size: 13px;
        font-weight: 600;
        text-align: left;
    }}
"""

STYLE_SIDEBAR_BTN_INACTIVE = f"""
    QPushButton {{
        background-color: transparent;
        color: {COLORS['sidebar_text']};
        border: 1px solid transparent;
        border-radius: 10px;
        padding: 11px 14px;
        font-size: 13px;
        font-weight: 500;
        text-align: left;
    }}
    QPushButton:hover {{
        background-color: {COLORS['sidebar_hover']};
        color: {COLORS['sidebar_text']};
    }}
"""

STYLE_CHECKBOX = f"""
    QCheckBox {{
        color: {COLORS['text_primary']};
        font-size: 13px;
        font-weight: 500;
        background: transparent;
        spacing: 10px;
        padding: 4px 0;
    }}
    QCheckBox:disabled {{
        color: {COLORS['text_muted']};
    }}
    QCheckBox::indicator {{
        width: 18px;
        height: 18px;
        border: 1.5px solid {COLORS['input_border']};
        border-radius: 5px;
        background:
    }}
    QCheckBox::indicator:hover {{
        border-color: {COLORS['green']};
        background: {COLORS['green_subtle']};
    }}
    QCheckBox::indicator:checked {{
        background: {COLORS['green']};
        border: 1.5px solid {COLORS['green']};
        image: url({icon_path('check.svg')});
    }}
    QCheckBox::indicator:checked:hover {{
        background: {COLORS['green_hover']};
        border-color: {COLORS['green_hover']};
    }}
"""

# Радиокнопки в едином стиле
STYLE_RADIO = f"""
    QRadioButton {{
        color: {COLORS['text_primary']};
        font-size: 13px;
        font-weight: 500;
        background: transparent;
        spacing: 10px;
        padding: 4px 0;
    }}
    QRadioButton::indicator {{
        width: 18px;
        height: 18px;
        border: 1.5px solid {COLORS['input_border']};
        border-radius: 9px;
        background:
    }}
    QRadioButton::indicator:hover {{
        border-color: {COLORS['accent']};
    }}
    QRadioButton::indicator:checked {{
        border: 5px solid {COLORS['accent']};
        background:
    }}
"""

STYLE_SCROLLBAR = f"""
    QScrollBar:vertical {{
        background: transparent;
        width: 10px;
        margin: 4px;
        border: none;
    }}
    QScrollBar::handle:vertical {{
        background: {COLORS['card_border_strong']};
        border-radius: 4px;
        min-height: 30px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {COLORS['text_muted']};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0;
        background: transparent;
    }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
        background: transparent;
    }}
    QScrollBar:horizontal {{
        background: transparent;
        height: 10px;
        margin: 4px;
        border: none;
    }}
    QScrollBar::handle:horizontal {{
        background: {COLORS['card_border_strong']};
        border-radius: 4px;
        min-width: 30px;
    }}
"""


class GenerationWorker(QThread):
    """Выполняет генерацию вопросов в фоновом потоке."""
    progress = Signal(str)
    # Не называем Signal «finished»: у QThread уже есть служебный сигнал finished(),
    # затенение ломает жизненный цикл потока и может ронять процесс при выходе.
    generation_finished = Signal(list)
    generation_error = Signal(str)

    def __init__(
        self,
        generator,
        topic: str,
        question_type: str,
        count: int,
        difficulty: str,
        custom_prompt: str,
        include_answers: bool,
        include_explanations: bool,
        bank_folder: Optional[str] = None,
    ):
        super().__init__()
        self.generator = generator
        self.topic = topic
        self.question_type = question_type
        self.count = count
        self.difficulty = difficulty
        self.custom_prompt = custom_prompt
        self.include_answers = include_answers
        self.include_explanations = include_explanations
        self.bank_folder = bank_folder

    def run(self):
        try:
            questions = self.generator.generate(
                topic=self.topic,
                question_type=self.question_type,
                count=self.count,
                difficulty=self.difficulty,
                custom_prompt=self.custom_prompt,
                include_answers=self.include_answers,
                include_explanations=self.include_explanations,
                progress_callback=lambda msg: self.progress.emit(msg),
                bank_folder=self.bank_folder,
            )
            self.generation_finished.emit(questions)
        except Exception as e:
            self.generation_error.emit(str(e))


class ModelLoadWorker(QThread):
    """Загружает модель в фоновом потоке."""
    progress = Signal(str)
    model_load_finished = Signal(bool)
    model_load_error = Signal(str)

    def __init__(
        self,
        runner,
        path: str,
<<<<<<< HEAD
        n_ctx: Optional[int] = None,
        n_threads: Optional[int] = None,
        n_gpu_layers: int = -2,
=======
        n_ctx: int,
        n_threads: int,
        n_gpu_layers: int = 0,
>>>>>>> 06236faa0a59c3fe63a9caebf58e61189dc30581
        n_batch: int = 256,
    ):
        super().__init__()
        self.runner = runner
        self.path = path
        self.n_ctx = n_ctx
        self.n_threads = n_threads
        self.n_gpu_layers = n_gpu_layers
        self.n_batch = n_batch

    def run(self):
        try:
            ok = self.runner.load_model(
                self.path,
                n_ctx=self.n_ctx,
                n_threads=self.n_threads,
                n_gpu_layers=self.n_gpu_layers,
                n_batch=self.n_batch,
                progress_callback=lambda msg: self.progress.emit(msg),
            )
            self.model_load_finished.emit(ok)
        except Exception as e:
            self.model_load_error.emit(str(e))


class TestAssistantWorker(QThread):
    """Обработка запроса учителя к готовому тесту через локальную LLM."""

    assistant_finished = Signal(str, object)
    assistant_error = Signal(str)

    def __init__(
        self,
        generator,
        model_runner,
        questions: list,
        topic: str,
        difficulty: str,
        bank_folder: Optional[str],
        user_message: str,
    ):
        super().__init__()
        self.generator = generator
        self.model_runner = model_runner
        self._qs = list(questions)
        self._topic = topic
        self._difficulty = difficulty or "medium"
        self._bank_folder = bank_folder
        self._user_message = user_message

    def run(self):
        from test_assistant import run_test_assistant_turn

        try:
            reply, _updated = run_test_assistant_turn(
                self.generator,
                self.model_runner,
                questions=self._qs,
                topic=self._topic,
                difficulty=self._difficulty,
                bank_folder=self._bank_folder,
                user_message=self._user_message,
            )
            self.assistant_finished.emit(reply, self._qs)
        except Exception as e:
            logger.exception("Ассистент теста: ошибка выполнения")
            self.assistant_error.emit(str(e))


def make_card(parent=None, *, with_shadow: bool = True) -> QFrame:
    """Создаёт карточку с лёгкой тенью."""
    frame = QFrame(parent)
    frame.setStyleSheet(STYLE_CARD)
    if with_shadow:
        shadow = QGraphicsDropShadowEffect(frame)
        shadow.setBlurRadius(14)
        shadow.setOffset(0, 2)
        shadow.setColor(QColor(28, 30, 36, 18))
        frame.setGraphicsEffect(shadow)
    return frame


def make_label(text: str, style: str = "body", parent=None) -> QLabel:
    styles = {
        "title": STYLE_LABEL_TITLE,
        "body": STYLE_LABEL_BODY,
        "muted": STYLE_LABEL_MUTED,
    }
    label = QLabel(text, parent)
    label.setStyleSheet(styles.get(style, STYLE_LABEL_BODY))
    label.setWordWrap(True)
    return label


def make_separator(parent=None) -> QFrame:
    sep = QFrame(parent)
    sep.setFrameShape(QFrame.Shape.HLine)
    sep.setStyleSheet(f"QFrame {{ background: {COLORS['card_border']}; border: none; max-height: 1px; }}")
    return sep


class Toast(QFrame):
    """Кастомное всплывающее уведомление поверх главного окна.

    Появляется с лёгким fade-in внизу справа, через несколько секунд исчезает.
    Поддерживает дополнительную кнопку (например, «Открыть папку»).
    """

    def __init__(
        self,
        parent: QWidget,
        title: str,
        message: str,
        kind: str = "success",
        action_text: str | None = None,
        action_callback=None,
        duration_ms: int = 5000,
    ):
        super().__init__(parent)
        self._duration_ms = duration_ms
        self._action_callback = action_callback

        kind_map = {
            "success": (COLORS["green"], COLORS["green_pressed"], COLORS["green_subtle"]),
            "error":   (COLORS["error"], "#7B2230", "#FBE9EC"),
            "info":    (COLORS["accent"], COLORS["accent_pressed"], COLORS["accent_subtle"]),
        }
        accent, accent_dark, soft = kind_map.get(kind, kind_map["success"])

        self.setObjectName("toast")
        self.setStyleSheet(f"""
            QFrame
                background: {COLORS['card_bg']};
                border: 1px solid {COLORS['card_border']};
                border-left: 4px solid {accent};
                border-radius: 12px;
            }}
            QFrame
            QFrame
                color: {COLORS['text_primary']};
                font-size: 13px;
                font-weight: 700;
            }}
            QFrame
                color: {COLORS['text_secondary']};
                font-size: 12px;
            }}
            QFrame
                background: {soft};
                color: {accent_dark};
                border: 1px solid transparent;
                border-radius: 8px;
                padding: 6px 12px;
                font-size: 12px;
                font-weight: 600;
            }}
            QFrame
                background: {accent};
                color: white;
            }}
        """)

        # Тень для премиальности
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(34)
        shadow.setOffset(0, 10)
        shadow.setColor(QColor(20, 24, 30, 80))
        self.setGraphicsEffect(shadow)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(12)

        # Иконка-кружок
        icon_lbl = QLabel("✓" if kind == "success" else "i" if kind == "info" else "!")
        icon_lbl.setFixedSize(28, 28)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setStyleSheet(f"""
            QLabel {{
                background: {accent};
                color: white;
                border-radius: 14px;
                font-size: 14px;
                font-weight: 700;
            }}
        """)
        lay.addWidget(icon_lbl)

        text_box = QVBoxLayout()
        text_box.setSpacing(2)
        title_lbl = QLabel(title)
        title_lbl.setObjectName("toast-title")
        msg_lbl = QLabel(message)
        msg_lbl.setObjectName("toast-msg")
        msg_lbl.setWordWrap(True)
        text_box.addWidget(title_lbl)
        text_box.addWidget(msg_lbl)
        lay.addLayout(text_box, 1)

        if action_text and action_callback:
            act_btn = QPushButton(action_text)
            act_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            act_btn.clicked.connect(self._on_action)
            lay.addWidget(act_btn)

        # Кнопка закрытия
        close_btn = QPushButton("×")
        close_btn.setFixedSize(24, 24)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {COLORS['text_muted']};
                border: none;
                font-size: 18px;
                font-weight: 500;
            }}
            QPushButton:hover {{
                color: {COLORS['text_primary']};
                background: {COLORS['accent_subtle']};
                border-radius: 12px;
            }}
        """)
        close_btn.clicked.connect(self._fade_out)
        lay.addWidget(close_btn)

    def _on_action(self):
        try:
            if self._action_callback:
                self._action_callback()
        finally:
            self._fade_out()

    def show_animated(self):
        parent = self.parent()
        if parent is None:
            self.show()
            return

        self.adjustSize()
        # Размещение: правый нижний угол с отступом
        margin = 24
        target_x = parent.width() - self.width() - margin
        target_y = parent.height() - self.height() - margin

        # Стартовая позиция чуть ниже целевой
        self.move(target_x, target_y + 30)
        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()

        # Анимация: opacity + slide-up
        self._anim_pos = QPropertyAnimation(self, b"pos", self)
        self._anim_pos.setDuration(220)
        self._anim_pos.setStartValue(self.pos())
        self._anim_pos.setEndValue(self.pos().__class__(target_x, target_y))
        self._anim_pos.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim_pos.start()

        self._anim_op = QPropertyAnimation(self, b"windowOpacity", self)
        self._anim_op.setDuration(220)
        self._anim_op.setStartValue(0.0)
        self._anim_op.setEndValue(1.0)
        self._anim_op.start()

        QTimer.singleShot(self._duration_ms, self._fade_out)

    def _fade_out(self):
        try:
            self._anim_close = QPropertyAnimation(self, b"windowOpacity", self)
            self._anim_close.setDuration(180)
            self._anim_close.setStartValue(self.windowOpacity())
            self._anim_close.setEndValue(0.0)
            self._anim_close.finished.connect(self.deleteLater)
            self._anim_close.start()
        except Exception:
            self.deleteLater()


def show_toast(
    parent: QWidget,
    title: str,
    message: str,
    kind: str = "success",
    action_text: str | None = None,
    action_callback=None,
    duration_ms: int = 5000,
) -> Toast:
    """Удобная функция для показа toast-уведомления."""
    toast = Toast(parent, title, message, kind, action_text, action_callback, duration_ms)
    toast.show_animated()
    return toast



class ModelSettingsPage(QWidget):
    """Inline-страница настроек модели (раньше была QDialog)."""

    back_clicked = Signal()

    def __init__(self, runner, registry, parent=None):
        super().__init__(parent)
        self.runner = runner
        self.registry = registry
        self.worker: Optional[QThread] = None
        self.setStyleSheet(f"""
            QWidget {{ background: {COLORS['main_bg']}; }}
            QGroupBox {{
                font-size: 13px;
                font-weight: 600;
                color: {COLORS['text_primary']};
                border: 1px solid {COLORS['card_border']};
                border-radius: 10px;
                margin-top: 14px;
                padding-top: 10px;
                background: {COLORS['card_bg']};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 14px;
                padding: 0 8px;
                color: {COLORS['text_primary']};
            }}
        """)
        self._build_ui()

    # Сохраняем интерфейс old API: accept() вызывается через близкие места.
    def accept(self):
        self.back_clicked.emit()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setSpacing(14)
        outer.setContentsMargins(28, 26, 28, 26)

        # --- Шапка: назад + заголовок ---
        header = QHBoxLayout()
        header.setSpacing(12)
        back_btn = QPushButton("←  Назад")
        back_btn.setStyleSheet(STYLE_BTN_SECONDARY)
        back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        back_btn.setFixedWidth(110)
        back_btn.clicked.connect(self.back_clicked.emit)

        title = QLabel("Настройки модели")
        title.setStyleSheet(f"""
            QLabel {{
                color: {COLORS['text_primary']};
                font-size: 19px;
                font-weight: 700;
                background: transparent;
                border: none;
                letter-spacing: -0.2px;
            }}
        """)
        header.addWidget(back_btn)
        header.addWidget(title)
        header.addStretch()
        outer.addLayout(header)
        outer.addWidget(make_separator())

        # Внутренняя обёртка-карточка для всей формы
        form_card = make_card()
        layout = QVBoxLayout(form_card)
        layout.setSpacing(14)
        layout.setContentsMargins(20, 20, 20, 20)
        outer.addWidget(form_card)
        outer.addStretch()

        # --- Выбор модели ---
<<<<<<< HEAD
        model_group = QGroupBox("Внешняя GGUF-модель")
=======
        model_group = QGroupBox("GGUF-модель")
>>>>>>> 06236faa0a59c3fe63a9caebf58e61189dc30581
        model_lay = QVBoxLayout(model_group)
        model_lay.setSpacing(8)

        # Путь к файлу
        path_row = QHBoxLayout()
        self.path_edit = QLineEdit()
<<<<<<< HEAD
        self.path_edit.setPlaceholderText("Выберите скачанный .gguf файл нейросети...")
=======
        self.path_edit.setPlaceholderText("Путь к .gguf файлу...")
>>>>>>> 06236faa0a59c3fe63a9caebf58e61189dc30581
        self.path_edit.setStyleSheet(STYLE_INPUT)

        last = self.registry.get_last_model_path()
        if last:
            self.path_edit.setText(last)

        browse_btn = QPushButton("Обзор")
        browse_btn.setStyleSheet(STYLE_BTN_SECONDARY)
        browse_btn.setFixedWidth(80)
        browse_btn.clicked.connect(self._browse_model)

        path_row.addWidget(self.path_edit)
        path_row.addWidget(browse_btn)
        model_lay.addLayout(path_row)

        # Подсказка
        hint = QLabel(
<<<<<<< HEAD
            "Нейросеть не входит в приложение и хранится отдельным .gguf файлом.\n"
            "1. Скачайте модель GGUF с Hugging Face, например Qwen2.5-3B-Instruct-Q4_K_M.gguf или Qwen2.5-7B-Instruct-Q4_K_M.gguf.\n"
            f"2. Положите файл в папку: {EXTERNAL_MODELS_DIR}\n"
            "3. Нажмите «Обзор», выберите .gguf файл и нажмите «Загрузить модель»."
=======
            "Рекомендуется: Qwen3.5-4B.Q4_K_M.gguf (~2.5 GB) — лучший баланс на CPU\n"
            "Запасные варианты: Qwen2.5-3B-Instruct (~2 GB) или Qwen2.5-7B-Instruct (~4.5 GB)\n"
            "Файлы лежат в подпапке models/ проекта."
>>>>>>> 06236faa0a59c3fe63a9caebf58e61189dc30581
        )
        hint.setStyleSheet(f"color: {COLORS['text_muted']}; font-size: 11px; background: transparent; border: none;")
        hint.setWordWrap(True)
        model_lay.addWidget(hint)

        layout.addWidget(model_group)

        # --- Параметры ---
        params_group = QGroupBox("Параметры загрузки")
        params_lay = QFormLayout(params_group)
        params_lay.setSpacing(10)

<<<<<<< HEAD
        # Авто-режим оставляет подбор железа загрузчику модели.
        from model_runner import AUTO_N_GPU_LAYERS
        self._auto_gpu_layers = AUTO_N_GPU_LAYERS

        try:
            from model_runner import choose_auto_context_tokens, choose_auto_cpu_threads

            auto_threads = choose_auto_cpu_threads()
            auto_ctx = choose_auto_context_tokens()
        except Exception:
            auto_threads = max(1, (os.cpu_count() or 4) // 2)
            auto_ctx = 8000

        auto_label_style = (
            f"color: {COLORS['text_primary']}; font-size: 12px; "
            f"background: {COLORS['input_bg']}; border: 1px solid {COLORS['input_border']}; "
            "border-radius: 8px; padding: 8px 10px;"
        )

        self.ctx_value_label = QLabel(f"Авто: {auto_ctx} токенов")
        self.ctx_value_label.setToolTip(
            "Размер контекста выбирается автоматически по оперативной памяти устройства."
        )
        self.ctx_value_label.setStyleSheet(auto_label_style)

        self.threads_value_label = QLabel(f"Авто: {auto_threads} потоков")
        self.threads_value_label.setToolTip(
            "Число потоков выбирается автоматически по процессору этого устройства."
        )
        self.threads_value_label.setStyleSheet(auto_label_style)

        self.gpu_value_label = QLabel("Авто")
        self.gpu_value_label.setToolTip(
            "GPU-режим выбирается автоматически: NVIDIA используется только при подходящей сборке llama-cpp-python."
        )
        self.gpu_value_label.setStyleSheet(auto_label_style)

        lbl_style = f"color: {COLORS['text_primary']}; font-size: 12px; font-weight: 600; background: transparent; border: none;"
        for lbl, widget in [
            ("Контекст:", self.ctx_value_label),
            ("Потоки CPU:", self.threads_value_label),
            ("GPU:", self.gpu_value_label),
=======
        # Авто-определяем число физических ядер для дефолта
        from model_runner import ModelRunner

        try:
            from model_runner import detect_physical_cores

            phys_cores = detect_physical_cores()
        except Exception:
            phys_cores = max(1, (os.cpu_count() or 4) // 2)

        self.ctx_spin = QSpinBox()
        self.ctx_spin.setRange(2048, 8192)
        self.ctx_spin.setValue(ModelRunner.DEFAULT_PARAMS["n_ctx"])
        self.ctx_spin.setSingleStep(512)
        self.ctx_spin.setStyleSheet(STYLE_INPUT)

        self.threads_spin = QSpinBox()
        self.threads_spin.setRange(1, 64)
        self.threads_spin.setValue(phys_cores)
        self.threads_spin.setStyleSheet(STYLE_INPUT)

        self.gpu_spin = QSpinBox()
        self.gpu_spin.setRange(-1, 999)
        self.gpu_spin.setValue(max(-1, self.registry.get_last_n_gpu_layers()))
        self.gpu_spin.setToolTip(
            "−1: все слои на GPU (llama.cpp). 0: только CPU. "
            "1…N: сколько слоёв выгрузить на GPU."
        )
        self.gpu_spin.setStyleSheet(STYLE_INPUT)

        lbl_style = f"color: {COLORS['text_primary']}; font-size: 12px; font-weight: 600; background: transparent; border: none;"
        for lbl, widget in [
            ("Контекст (токены):", self.ctx_spin),
            ("Потоков CPU:", self.threads_spin),
            ("Слоёв GPU:", self.gpu_spin),
>>>>>>> 06236faa0a59c3fe63a9caebf58e61189dc30581
        ]:
            label = QLabel(lbl)
            label.setStyleSheet(lbl_style)
            params_lay.addRow(label, widget)

        gpu_hint = QLabel(
<<<<<<< HEAD
            "Параметры железа выбираются автоматически при каждой загрузке модели: контекст — по RAM, "
            "CPU-потоки — по ядрам процессора, GPU — по видеокарте и сборке llama-cpp-python."
=======
            "0 или «CPU» — только процессор; −1 — все слои на GPU (нужен llama-cpp с CUDA/Vulkan). "
            "Переменная HISTORY_TEST_N_GPU_LAYERS переопределяет это при загрузке."
>>>>>>> 06236faa0a59c3fe63a9caebf58e61189dc30581
        )
        gpu_hint.setWordWrap(True)
        gpu_hint.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-size: 11px; background: transparent; border: none;"
        )
        params_lay.addRow("", gpu_hint)

        layout.addWidget(params_group)

        # --- Статус ---
        status_group = QGroupBox("Статус")
        status_lay = QVBoxLayout(status_group)

        self.status_label = QLabel("Модель не загружена")
        self.status_label.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-size: 12px; background: transparent; border: none;"
        )
        status_lay.addWidget(self.status_label)

        self.progress_label = QLabel("")
        self.progress_label.setStyleSheet(
            f"color: {COLORS['accent']}; font-size: 11px; background: transparent; border: none;"
        )
        status_lay.addWidget(self.progress_label)

        layout.addWidget(status_group)

        if self.runner.is_loaded:
            self.status_label.setText(f"Загружена: {self.runner.model_name}")
            self.status_label.setStyleSheet(
                f"color: {COLORS['success']}; font-size: 12px; background: transparent; border: none;"
            )
<<<<<<< HEAD
            self._update_auto_values_labels()
=======
>>>>>>> 06236faa0a59c3fe63a9caebf58e61189dc30581

        # --- Кнопки ---
        btn_row = QHBoxLayout()

        self.load_btn = QPushButton("Загрузить модель")
        self.load_btn.setStyleSheet(STYLE_BTN_PRIMARY)
        self.load_btn.clicked.connect(self._load_model)

        self.unload_btn = QPushButton("Выгрузить")
        self.unload_btn.setStyleSheet(STYLE_BTN_SECONDARY)
        self.unload_btn.clicked.connect(self._unload_model)
        self.unload_btn.setEnabled(self.runner.is_loaded)

        close_btn = QPushButton("Закрыть")
        close_btn.setStyleSheet(STYLE_BTN_SECONDARY)
        close_btn.clicked.connect(self.accept)

        btn_row.addWidget(self.load_btn)
        btn_row.addWidget(self.unload_btn)
        btn_row.addStretch()
        btn_row.addWidget(close_btn)

        layout.addLayout(btn_row)

<<<<<<< HEAD
    def _update_auto_values_labels(self):
        info = self.runner.model_info() if getattr(self.runner, "is_loaded", False) else {}
        ctx = info.get("n_ctx")
        if ctx:
            self.ctx_value_label.setText(f"Авто: {ctx} токенов")
        else:
            try:
                from model_runner import choose_auto_context_tokens

                self.ctx_value_label.setText(f"Авто: {choose_auto_context_tokens()} токенов")
            except Exception:
                self.ctx_value_label.setText("Авто")

        gen = info.get("n_threads")
        prompt = info.get("n_threads_batch")
        if gen and prompt:
            text = f"Авто: генерация {gen} пот., промпт {prompt} пот."
        elif gen:
            text = f"Авто: {gen} потоков"
        else:
            try:
                from model_runner import choose_auto_cpu_threads

                text = f"Авто: {choose_auto_cpu_threads()} потоков"
            except Exception:
                text = "Авто"
        self.threads_value_label.setText(text)

        n_gl = info.get("n_gpu_layers")
        using_gpu = bool(info.get("using_gpu"))
        if n_gl is not None:
            if using_gpu:
                self.gpu_value_label.setText(f"Авто: GPU, слоёв {n_gl}")
            else:
                self.gpu_value_label.setText("Авто: CPU")
        else:
            self.gpu_value_label.setText("Авто")

    def _browse_model(self):
        # Модель хранится вне приложения, чтобы установщик не весил несколько гигабайт.
        try:
            EXTERNAL_MODELS_DIR.mkdir(parents=True, exist_ok=True)
            default_dir = str(EXTERNAL_MODELS_DIR)
        except Exception:
            default_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "models")
            if not os.path.exists(default_dir):
                default_dir = ""
=======
    def _browse_model(self):
        # Путь по умолчанию к папке с моделями
        default_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "models")
        if not os.path.exists(default_dir):
            default_dir = ""
>>>>>>> 06236faa0a59c3fe63a9caebf58e61189dc30581
        
        path, _ = QFileDialog.getOpenFileName(
            self, "Выберите GGUF-модель", default_dir, "GGUF Files (*.gguf);;All Files (*)"
        )
        if path:
            self.path_edit.setText(path)

    def _load_model(self):
        path = self.path_edit.text().strip()
        if not path:
            QMessageBox.warning(self, "Ошибка", "Укажите путь к файлу модели (.gguf)")
            return

        self.load_btn.setEnabled(False)
        self.status_label.setText("Загрузка...")
        self.status_label.setStyleSheet(
            f"color: {COLORS['warning']}; font-size: 12px; background: transparent; border: none;"
        )

        prev = self.worker
        if isinstance(prev, QThread) and prev.isRunning():
            prev.wait(300_000)

        self.worker = ModelLoadWorker(
            self.runner, path,
<<<<<<< HEAD
            n_ctx=None,
            n_threads=None,
            n_gpu_layers=self._auto_gpu_layers,
=======
            n_ctx=self.ctx_spin.value(),
            n_threads=self.threads_spin.value(),
            n_gpu_layers=self.gpu_spin.value(),
>>>>>>> 06236faa0a59c3fe63a9caebf58e61189dc30581
            n_batch=768,
        )
        self.worker.progress.connect(self.progress_label.setText)
        self.worker.model_load_finished.connect(self._on_loaded)
        self.worker.model_load_error.connect(self._on_error)
        self.worker.start()

    def _on_loaded(self, ok: bool):
        if ok:
            self.status_label.setText(f"Загружена: {self.runner.model_name}")
            self.status_label.setStyleSheet(
                f"color: {COLORS['success']}; font-size: 12px; background: transparent; border: none;"
            )
            self.registry.save_last_model_path(
                self.path_edit.text().strip(),
<<<<<<< HEAD
                n_gpu_layers=self._auto_gpu_layers,
            )
            self._update_auto_values_labels()
=======
                n_gpu_layers=self.gpu_spin.value(),
            )
>>>>>>> 06236faa0a59c3fe63a9caebf58e61189dc30581
            self.unload_btn.setEnabled(True)
        self.load_btn.setEnabled(True)
        self.progress_label.setText("")

    def _on_error(self, msg: str):
        self.status_label.setText(f"Ошибка: {msg[:80]}")
        self.status_label.setStyleSheet(
            f"color: {COLORS['error']}; font-size: 12px; background: transparent; border: none;"
        )
        self.load_btn.setEnabled(True)
        QMessageBox.critical(self, "Ошибка загрузки модели", msg)

    def _unload_model(self):
        self.runner.unload_model()
        self.status_label.setText("Модель выгружена")
        self.status_label.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-size: 12px; background: transparent; border: none;"
        )
<<<<<<< HEAD
        self._update_auto_values_labels()
=======
>>>>>>> 06236faa0a59c3fe63a9caebf58e61189dc30581
        self.unload_btn.setEnabled(False)


class ExportDialog(QDialog):
    def __init__(self, questions, topic, textbook_name, variant_num, parent=None):
        super().__init__(parent)
        self.questions = questions
        self.topic = topic
        self.textbook_name = textbook_name
        self.variant_num = variant_num
        self.setWindowTitle("Экспорт в Word")
        self.setMinimumSize(460, 400)
        self.setStyleSheet(f"QDialog {{ background: {COLORS['main_bg']}; }}")
        self._build_ui()

    def _build_ui(self):
        self.setStyleSheet(f"QDialog {{ background: {COLORS['main_bg']}; }}")
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 22, 24, 22)

        # Заголовок
        title = QLabel("Экспорт теста в Word")
        title.setStyleSheet(f"""
            QLabel {{
                color: {COLORS['text_primary']};
                font-size: 17px;
                font-weight: 700;
                background: transparent;
                border: none;
                letter-spacing: -0.2px;
            }}
        """)
        subtitle = QLabel("Имя файла будет составлено автоматически на основе класса и темы")
        subtitle.setStyleSheet(f"""
            QLabel {{
                color: {COLORS['text_muted']};
                font-size: 12px;
                background: transparent;
                border: none;
            }}
        """)
        subtitle.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(make_separator())

        # Карточка-форма
        form = make_card()
        form_lay = QVBoxLayout(form)
        form_lay.setContentsMargins(18, 16, 18, 16)
        form_lay.setSpacing(12)

        # === Класс ===
        cls_row = QVBoxLayout()
        cls_row.setSpacing(6)
        cls_lbl = QLabel("Класс")
        cls_lbl.setStyleSheet(STYLE_LABEL_TITLE)
        self.class_edit = QLineEdit()
        self.class_edit.setPlaceholderText("Например: 10А")
        self.class_edit.setStyleSheet(STYLE_INPUT)
        self.class_edit.setMinimumHeight(36)
        self.class_edit.textChanged.connect(self._update_filename_preview)
        cls_row.addWidget(cls_lbl)
        cls_row.addWidget(self.class_edit)
        form_lay.addLayout(cls_row)

        # === Чекбоксы: содержимое ===
        cb_lbl = QLabel("Содержимое документа")
        cb_lbl.setStyleSheet(STYLE_LABEL_TITLE)
        form_lay.addWidget(cb_lbl)

        self.cb_with_answers = QCheckBox("Включить правильные ответы")
        self.cb_with_answers.setStyleSheet(STYLE_CHECKBOX)
        self.cb_with_answers.setCursor(Qt.CursorShape.PointingHandCursor)

        self.cb_with_explanations = QCheckBox("Включить пояснения к ответам")
        self.cb_with_explanations.setStyleSheet(STYLE_CHECKBOX)
        self.cb_with_explanations.setCursor(Qt.CursorShape.PointingHandCursor)

        self.cb_with_answer_sheet = QCheckBox("Лист ответов отдельной страницей")
        self.cb_with_answer_sheet.setStyleSheet(STYLE_CHECKBOX)
        self.cb_with_answer_sheet.setCursor(Qt.CursorShape.PointingHandCursor)

        form_lay.addWidget(self.cb_with_answers)
        form_lay.addWidget(self.cb_with_explanations)
        form_lay.addWidget(self.cb_with_answer_sheet)

        # === Папка для сохранения ===
        path_lbl = QLabel("Папка для сохранения")
        path_lbl.setStyleSheet(STYLE_LABEL_TITLE)
        form_lay.addWidget(path_lbl)

        path_row = QHBoxLayout()
        path_row.setSpacing(8)
        self.save_path_edit = QLineEdit()
        self.save_path_edit.setText(default_docx_export_dir())
        self.save_path_edit.setStyleSheet(STYLE_INPUT)
        self.save_path_edit.setMinimumHeight(36)

        browse_btn = QPushButton("Обзор")
        browse_btn.setStyleSheet(STYLE_BTN_SECONDARY)
        browse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        browse_btn.setFixedWidth(90)
        browse_btn.clicked.connect(self._browse_save_path)

        path_row.addWidget(self.save_path_edit, 1)
        path_row.addWidget(browse_btn)
        form_lay.addLayout(path_row)

        # === Превью имени файла ===
        self.filename_preview = QLabel("")
        self.filename_preview.setStyleSheet(f"""
            QLabel {{
                color: {COLORS['text_secondary']};
                font-size: 12px;
                font-weight: 500;
                background: {COLORS['accent_subtle']};
                border: 1px solid {COLORS['card_border']};
                border-radius: 8px;
                padding: 8px 12px;
            }}
        """)
        self.filename_preview.setWordWrap(True)
        form_lay.addWidget(self.filename_preview)

        layout.addWidget(form)

        # === Кнопки ===
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        cancel_btn = QPushButton("Отмена")
        cancel_btn.setStyleSheet(STYLE_BTN_SECONDARY)
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.clicked.connect(self.reject)

        export_btn = QPushButton("Экспортировать")
        export_btn.setStyleSheet(STYLE_BTN_CTA)
        export_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        export_btn.clicked.connect(self._do_export)

        btn_row.addStretch()
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(export_btn)
        layout.addLayout(btn_row)

        self._update_filename_preview()

    def _build_filename(self) -> str:
        """Имя файла: «Тест_{класс}_{тема}_В{N}_{дата}.docx»."""
        cls = self.class_edit.text().strip() if hasattr(self, "class_edit") else ""
        safe_class = "".join(c for c in cls if c.isalnum() or c in "АБВГДЕабвгде")[:10]
        safe_topic = "".join(c for c in self.topic if c.isalnum() or c in " _-")[:40].strip().replace(" ", "_")
        date = datetime.datetime.now().strftime("%Y%m%d")
        parts = ["Тест"]
        if safe_class:
            parts.append(safe_class)
        parts.append(safe_topic or "Тема")
        parts.append(f"В{self.variant_num}")
        parts.append(date)
        return "_".join(parts) + ".docx"

    def _update_filename_preview(self, *_):
        name = self._build_filename()
        self.filename_preview.setText(f"Имя файла:  {name}")

    def _browse_save_path(self):
        start = self.save_path_edit.text().strip()
        if not start or not os.path.isdir(start):
            start = default_docx_export_dir()
        folder = QFileDialog.getExistingDirectory(
            self,
            "Выберите папку",
            start,
        )
        if folder:
            self.save_path_edit.setText(folder)

    def _do_export(self):
        from export_docx import DocxExporter, check_docx_available

        if not check_docx_available():
            QMessageBox.critical(
                self, "Ошибка",
                "Библиотека python-docx не установлена.\n"
                "Установите: pip install python-docx"
            )
            return

        include_answers = self.cb_with_answers.isChecked()
        include_explanations = self.cb_with_explanations.isChecked()
        include_answer_sheet = self.cb_with_answer_sheet.isChecked()

        folder = (
            self.save_path_edit.text().strip() or default_docx_export_dir()
        )
        full_path = os.path.join(folder, self._build_filename())

        try:
            exporter = DocxExporter()
            saved_path = exporter.export(
                questions=self.questions,
                topic=self.topic,
                textbook_name=self.textbook_name,
                variant_num=self.variant_num,
                include_answers=include_answers,
                include_explanations=include_explanations,
                include_answer_sheet=include_answer_sheet,
                output_path=full_path,
                class_grade=self.class_edit.text().strip(),
            )
            self._exported_path = saved_path
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка экспорта", str(e))


class _ScrollAreaWheelForwarder(QObject):
    """Пересылает колесо мыши со встроенных полей во внешнюю прокрутку страницы результатов."""

    def __init__(self, scroll: QScrollArea):
        super().__init__(scroll)
        self._scroll = scroll

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.Wheel:
            bar = self._scroll.verticalScrollBar()
            if bar is not None:
                delta = ev.angleDelta().y()
                if delta:
                    bar.setValue(bar.value() - (delta * bar.singleStep()) // 120)
                elif ev.pixelDelta().y():
                    bar.setValue(bar.value() - ev.pixelDelta().y())
                else:
                    return False
                return True
        return False


class ResultsPage(QWidget):
    """Отображает список сгенерированных вопросов."""

    back_clicked = Signal()
    export_clicked = Signal(list, str, str, int)
    assistant_request = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._questions = []
        self._topic = ""
        self._textbook = ""
        self._variant = 1
        self._assistant_bank_folder = None
        self._assistant_difficulty = "medium"
        self._variants_bundle = None
        self._build_ui()
        self._assistant_busy_timer = QTimer(self)
        self._assistant_busy_timer.timeout.connect(self._on_assistant_busy_pulse)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(28, 26, 28, 26)
        self.setStyleSheet(f"background: {COLORS['main_bg']};")

        # Заголовок
        header = QHBoxLayout()
        header.setSpacing(12)
        back_btn = QPushButton("←  Назад")
        back_btn.setStyleSheet(STYLE_BTN_SECONDARY)
        back_btn.setFixedWidth(110)
        back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        back_btn.clicked.connect(self.back_clicked.emit)

        self.title_label = QLabel("Результаты генерации")
        self.title_label.setStyleSheet(f"""
            QLabel {{
                color: {COLORS['text_primary']};
                font-size: 19px;
                font-weight: 700;
                background: transparent;
                border: none;
                letter-spacing: -0.2px;
            }}
        """)

        self.export_btn = QPushButton("Экспорт в Word")
        self.export_btn.setStyleSheet(STYLE_BTN_PRIMARY)
        self.export_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.export_btn.clicked.connect(self._export)

        header.addWidget(back_btn)
        header.addWidget(self.title_label)
        header.addStretch()
        header.addWidget(self.export_btn)
        layout.addLayout(header)

        self.results_scroll = QScrollArea()
        self.results_scroll.setWidgetResizable(True)
        self.results_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.results_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.results_scroll.setStyleSheet(
            "QScrollArea { border: none; background: transparent; }"
            + STYLE_SCROLLBAR
        )

        self.results_content = QWidget()
        self.results_content.setStyleSheet(f"background: {COLORS['main_bg']};")
        results_body = QVBoxLayout(self.results_content)
        results_body.setSpacing(14)
        results_body.setContentsMargins(0, 0, 10, 0)

        self.info_label = QLabel("")
        self.info_label.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-size: 12px; background: transparent; border: none;"
        )
        results_body.addWidget(self.info_label)

        self.assistant_panel = make_card()
        ap_lay = QVBoxLayout(self.assistant_panel)
        ap_lay.setContentsMargins(16, 12, 16, 14)
        ap_lay.setSpacing(8)

        ah = QLabel("Ассистент по тесту")
        ah.setStyleSheet(
            f"font-size: 14px; font-weight: 700; color: {COLORS['text_primary']}; "
            "background: transparent; border: none;"
        )
        ahint = QLabel(
            "Опишите, что сделать с уже собранным тестом. Примеры: «Замени вопрос 6», "
            "«Поставь другой вопрос вместо второго». Поддерживается несколько номеров в одной фразе.\n\n"
            "Замены подбираются из банка вопросов (тот же тип задания), если тест изначально "
            "строился из банка; модель только планирует и выбирает кандидата."
        )
        ahint.setWordWrap(True)
        ahint.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-size: 11px; background: transparent; border: none;"
        )

        self.assistant_prompt_edit = QTextEdit()
        self.assistant_prompt_edit.setPlaceholderText(
            "Например: замени шестой вопрос похожим по теме"
        )
        self.assistant_prompt_edit.setMinimumHeight(72)
        self.assistant_prompt_edit.setMaximumHeight(102)
        self.assistant_prompt_edit.setAcceptRichText(False)
        self.assistant_prompt_edit.setStyleSheet(STYLE_INPUT)

        self.assistant_busy_bar = QProgressBar()
        self.assistant_busy_bar.setRange(0, 100)
        self.assistant_busy_bar.setValue(0)
        self.assistant_busy_bar.setTextVisible(False)
        self.assistant_busy_bar.setVisible(False)
        self.assistant_busy_bar.setStyleSheet(STYLE_ASSISTANT_BUSY)
        self.assistant_busy_bar.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.assistant_busy_bar.setFixedHeight(7)

        assistant_row = QHBoxLayout()
        assistant_row.setSpacing(12)
        self.assistant_run_btn = QPushButton("Выполнить запрос")
        self.assistant_run_btn.setStyleSheet(STYLE_BTN_CTA)
        self.assistant_run_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.assistant_run_btn.setMinimumWidth(180)
        self.assistant_run_btn.clicked.connect(self._on_assistant_send)
        assistant_row.addStretch()
        assistant_row.addWidget(self.assistant_run_btn)

        self.assistant_status_label = QLabel("")
        self.assistant_status_label.setWordWrap(True)
        self.assistant_status_label.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 12px; background: transparent; border: none;"
        )

        ap_lay.addWidget(ah)
        ap_lay.addWidget(ahint)
        ap_lay.addWidget(self.assistant_prompt_edit)
        ap_lay.addWidget(self.assistant_busy_bar)
        ap_lay.addLayout(assistant_row)
        ap_lay.addWidget(self.assistant_status_label)

        results_body.addWidget(self.assistant_panel)
        results_body.addWidget(make_separator())

        self.questions_container = QWidget()
        self.questions_container.setStyleSheet(f"background: {COLORS['main_bg']};")
        self.questions_layout = QVBoxLayout(self.questions_container)
        self.questions_layout.setSpacing(12)
        self.questions_layout.setContentsMargins(0, 0, 0, 12)

        results_body.addWidget(self.questions_container)

        self.results_scroll.setWidget(self.results_content)
        layout.addWidget(self.results_scroll, 1)

        self._assistant_wheel_forwarder = _ScrollAreaWheelForwarder(self.results_scroll)
        self.assistant_prompt_edit.installEventFilter(self._assistant_wheel_forwarder)

    def _stop_assistant_busy_pulse(self):
        self._assistant_busy_timer.stop()

    def _on_assistant_busy_pulse(self):
        """Анимация полосы: стабильно работает в любой теме Qt."""
        bar = self.assistant_busy_bar
        if bar.maximum() <= 0:
            return
        n = bar.value() + 5
        if n > bar.maximum():
            n = 0
        bar.setValue(n)

    def _clear_question_cards(self):
        while self.questions_layout.count():
            item = self.questions_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _populate_single_variant_cards(self, questions: list):
        """Перестраивает список карточек для одного варианта."""
        self._clear_question_cards()
        for i, q in enumerate(questions, start=1):
            self.questions_layout.addWidget(self._make_question_card(i, q))
        self.questions_layout.addStretch()

    def set_assistant_busy(self, busy: bool, message: str = ""):
        self.assistant_run_btn.setEnabled(not busy)
        self.assistant_prompt_edit.setReadOnly(busy)
        if busy:
            self.assistant_run_btn.setText("Обработка…")
            self.assistant_busy_bar.setRange(0, 100)
            self.assistant_busy_bar.setValue(0)
            self.assistant_busy_bar.setVisible(True)
            self._assistant_busy_timer.start(52)
            if message:
                self.assistant_status_label.setText(message)
        else:
            self._stop_assistant_busy_pulse()
            self.assistant_run_btn.setText("Выполнить запрос")
            self.assistant_busy_bar.setVisible(False)
            self.assistant_busy_bar.setValue(0)

    def set_assistant_status_text(self, text: str):
        self.assistant_status_label.setText(text)

    def apply_assistant_questions(self, questions: list):
        """После успешного прохода ассистента: обновляет список и карточки."""
        self._questions = questions
        self.info_label.setText(
            f"Сгенерировано вопросов: {len(questions)} | Источник: {self._textbook}"
        )
        self._populate_single_variant_cards(questions)
        self.title_label.setText(f"Тест: {self._topic} · Вариант {self._variant}")

    def _on_assistant_send(self):
        if self._variants_bundle is not None:
            QMessageBox.information(
                self,
                "Ассистент по тесту",
                "Редактирование через ассистента доступно для одного варианта. "
                "Откройте один вариант из истории или сгенерируйте один вариант.",
            )
            return
        txt = self.assistant_prompt_edit.toPlainText().strip()
        if not txt:
            self.assistant_status_label.setText("Введите текст запроса и нажмите «Выполнить».")
            return
        self.assistant_request.emit(txt)

    def show_questions(
        self,
        questions: list,
        topic: str,
        textbook: str,
        variant: int = 1,
        bank_folder: Optional[str] = None,
        difficulty: Optional[str] = None,
    ):
        self._variants_bundle = None
        self._questions = questions
        self._topic = topic
        self._textbook = textbook
        self._variant = variant
        bf = (bank_folder or "").strip()
        self._assistant_bank_folder = bf if bf else None
        d = (difficulty or "medium").strip().lower()
        self._assistant_difficulty = d if d in ("easy", "medium", "hard") else "medium"

        self.title_label.setText(f"Тест: {topic} · Вариант {variant}")
        self.info_label.setText(
            f"Сгенерировано вопросов: {len(questions)} | Источник: {textbook}"
        )

        self.assistant_panel.setVisible(True)
        self.set_assistant_busy(False)
        self.assistant_status_label.setText("")
        self.assistant_prompt_edit.setReadOnly(False)
        self.assistant_run_btn.setEnabled(True)
        self.assistant_prompt_edit.setPlaceholderText(
            "Например: замени шестой вопрос похожим по теме"
        )
        self._populate_single_variant_cards(questions)

    def show_variants_bundle(
        self,
        variants: list[tuple[int, list]],
        topic: str,
        textbook: str,
        bank_folder: Optional[str] = None,
        difficulty: Optional[str] = None,
    ):
        """Один общий экран генерации для нескольких вариантов (сквозная нумерация)."""
        self._variants_bundle = variants
        self._questions = variants[0][1] if variants else []
        self._topic = topic
        self._textbook = textbook
        self._variant = variants[0][0] if variants else 1
        bf = (bank_folder or "").strip()
        self._assistant_bank_folder = bf if bf else None
        d = (difficulty or "medium").strip().lower()
        self._assistant_difficulty = d if d in ("easy", "medium", "hard") else "medium"

        vn = len(variants)
        if vn % 100 in (11, 12, 13, 14):
            vword = "вариантов"
        elif vn % 10 == 1:
            vword = "вариант"
        elif vn % 10 in (2, 3, 4):
            vword = "варианта"
        else:
            vword = "вариантов"
        total_q = sum(len(qs) for _, qs in variants)
        self.title_label.setText(f"Тест: {topic} · {vn} {vword}")
        self.info_label.setText(
            f"Вариантов: {vn}, всего вопросов: {total_q}. Источник: {textbook}"
        )

        self.assistant_panel.setVisible(True)
        self.set_assistant_busy(False)
        self.assistant_prompt_edit.clear()
        self.assistant_prompt_edit.setPlaceholderText(
            "Недоступно: на экране несколько вариантов контрольной."
        )
        self.assistant_prompt_edit.setReadOnly(True)
        self.assistant_run_btn.setEnabled(False)
        self.assistant_status_label.setText(
            "Редактирование через ассистента доступно только для одного варианта на экране. "
            "Укажите «Вариантов: 1» при генерации или откройте из истории запись с одним вариантом."
        )

        while self.questions_layout.count():
            item = self.questions_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        glob_i = 0
        for vnum, qs in variants:
            band = QLabel(f"━━━ Вариант {vnum} ━━━")
            band.setStyleSheet(f"""
                QLabel {{
                    color: {COLORS['accent']};
                    font-size: 12px;
                    font-weight: 700;
                    background: transparent;
                    border: none;
                    letter-spacing: 0.06em;
                }}
            """)
            self.questions_layout.addWidget(band)
            for q in qs:
                glob_i += 1
                card = self._make_question_card(glob_i, q)
                self.questions_layout.addWidget(card)

        self.questions_layout.addStretch()

    def _make_question_card(self, num: int, question) -> QFrame:
        """Создаёт карточку вопроса."""
        q = question.to_dict() if hasattr(question, "to_dict") else question

        card = make_card()
        card_lay = QVBoxLayout(card)
        card_lay.setSpacing(8)
        card_lay.setContentsMargins(16, 14, 16, 14)

        head_row = QHBoxLayout()

        num_badge = QLabel(f"{num}")
        num_badge.setStyleSheet(f"""
            QLabel {{
                background: {COLORS['accent_subtle']};
                color: {COLORS['accent']};
                font-size: 12px;
                font-weight: 700;
                padding: 2px 8px;
                border-radius: 10px;
                border: none;
            }}
        """)
        num_badge.setFixedSize(36, 24)
        num_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)

        q_type = q.get("question_type", "test")
        type_names = {
            "test": "Тест",
            "open": "Открытый",
            "match": "Сопоставление",
            "chronology": "Хронология",
        }
        type_badge = QLabel(type_names.get(q_type, q_type))
        type_badge.setStyleSheet(f"""
            QLabel {{
                background: {COLORS['status_bg']};
                color: {COLORS['accent_subtle_text']};
                font-size: 11px;
                font-weight: 600;
                padding: 2px 8px;
                border-radius: 10px;
                border: none;
            }}
        """)

        meta_style = f"""
            QLabel {{
                color: {COLORS['text_muted']};
                font-size: 11px;
                background: transparent;
                border: none;
            }}
        """
        page_badge = None
        if q.get("source_page"):
            page_badge = QLabel(f"Страница: {q['source_page']}")
            page_badge.setStyleSheet(meta_style)
        para_badge = None
        sp = str(q.get("source_paragraph") or "").strip()
        if sp:
            para_badge = QLabel(f"Параграф: {sp}")
            para_badge.setStyleSheet(meta_style)

        head_row.addWidget(num_badge)
        head_row.addWidget(type_badge)
        if page_badge:
            head_row.addWidget(page_badge)
        if para_badge:
            head_row.addWidget(para_badge)
        head_row.addStretch()

        card_lay.addLayout(head_row)

        q_text = QLabel(q.get("text", ""))
        q_text.setStyleSheet(f"""
            QLabel {{
                color: {COLORS['text_primary']};
                font-size: 13px;
                font-weight: 600;
                background: transparent;
                border: none;
            }}
        """)
        q_text.setWordWrap(True)
        card_lay.addWidget(q_text)

        options = q.get("options", [])
        correct = q.get("correct_answer", "")
        option_letters = ["А", "Б", "В", "Г", "Д"]

        if options:
            opts_frame = QFrame()
            opts_frame.setStyleSheet(f"""
                QFrame {{
                    background: {COLORS['status_bg']};
                    border: 1px solid {COLORS['card_border']};
                    border-radius: 8px;
                }}
            """)
            opts_lay = QVBoxLayout(opts_frame)
            opts_lay.setSpacing(4)
            opts_lay.setContentsMargins(10, 8, 10, 8)

            for j, opt in enumerate(options[:5]):
                opt_row = QHBoxLayout()
                letter = option_letters[j] if j < len(option_letters) else str(j + 1)

                is_correct = correct and opt.strip().lower() == correct.strip().lower()

                letter_lbl = QLabel(f"{letter})")
                letter_lbl.setStyleSheet(f"""
                    QLabel {{
                        color: {COLORS['accent'] if is_correct else COLORS['text_muted']};
                        font-size: 12px;
                        font-weight: 700;
                        background: transparent;
                        border: none;
                        min-width: 20px;
                    }}
                """)
                letter_lbl.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

                opt_lbl = QLabel(opt)
                opt_lbl.setStyleSheet(f"""
                    QLabel {{
                        color: {COLORS['success'] if is_correct else COLORS['text_secondary']};
                        font-size: 12px;
                        font-weight: {'700' if is_correct else '500'};
                        background: transparent;
                        border: none;
                    }}
                """)
                opt_lbl.setWordWrap(True)

                opt_row.addWidget(letter_lbl)
                opt_row.addWidget(opt_lbl, 1)
                opts_lay.addLayout(opt_row)

            card_lay.addWidget(opts_frame)

        if q.get("explanation"):
            exp_lbl = QLabel(q["explanation"])
            exp_lbl.setStyleSheet(f"""
                QLabel {{
                    color: {COLORS['text_muted']};
                    font-size: 11px;
                    font-style: italic;
                    background: transparent;
                    border: none;
                }}
            """)
            exp_lbl.setWordWrap(True)
            card_lay.addWidget(exp_lbl)

        return card

    def _export(self):
        self.export_clicked.emit(
            self._questions, self._topic, self._textbook, self._variant
        )



class AllTestsPage(QWidget):
    """Показывает историю всех сгенерированных тестов."""

    view_clicked = Signal(str)
    back_clicked = Signal()

    def __init__(self, storage, parent=None):
        super().__init__(parent)
        self.storage = storage
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(28, 26, 28, 26)
        self.setStyleSheet(f"background: {COLORS['main_bg']};")

        # Заголовок
        header = QHBoxLayout()
        header.setSpacing(12)
        back_btn = QPushButton("←  Назад")
        back_btn.setStyleSheet(STYLE_BTN_SECONDARY)
        back_btn.setFixedWidth(110)
        back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        back_btn.clicked.connect(self.back_clicked.emit)

        title = QLabel("Все сгенерированные тесты")
        title.setStyleSheet(f"""
            QLabel {{
                color: {COLORS['text_primary']};
                font-size: 19px;
                font-weight: 700;
                background: transparent;
                border: none;
                letter-spacing: -0.2px;
            }}
        """)

        header.addWidget(back_btn)
        header.addWidget(title)
        header.addStretch()
        layout.addLayout(header)

        layout.addWidget(make_separator())

        # Скролл
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(
            "QScrollArea { border: none; background: transparent; }"
            + STYLE_SCROLLBAR
        )

        self.list_container = QWidget()
        self.list_container.setStyleSheet(f"background: {COLORS['main_bg']};")
        self.list_layout = QVBoxLayout(self.list_container)
        self.list_layout.setSpacing(8)
        self.list_layout.setContentsMargins(0, 0, 0, 12)

        scroll.setWidget(self.list_container)
        layout.addWidget(scroll)

    def refresh(self):
        """Обновляет список тестов."""
        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        tests = self.storage.get_all()
        if not tests:
            empty = QLabel("Тестов пока нет. Создайте первый тест!")
            empty.setStyleSheet(
                f"color: {COLORS['text_muted']}; font-size: 14px; background: transparent; border: none;"
            )
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.list_layout.addWidget(empty)
        else:
            for test in tests:
                row = self._make_test_row(test)
                self.list_layout.addWidget(row)

        self.list_layout.addStretch()

    def _make_test_row(self, test: dict) -> QFrame:
        card = make_card()
        row = QHBoxLayout(card)
        row.setContentsMargins(16, 12, 16, 12)

        info_lay = QVBoxLayout()
        topic_lbl = QLabel(test.get("topic", "—"))
        topic_lbl.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 13px; font-weight: 600; background: transparent; border: none;"
        )
        if test.get("multi_variant"):
            nvar = int(test.get("variant_count") or len(test.get("variants") or []) or 1)
            meta_lbl = QLabel(
                f"{nvar} вар. · всего вопросов: {test.get('count', 0)} · "
                f"{test.get('date', '')}"
            )
        else:
            meta_lbl = QLabel(
                f"{test.get('textbook', '')} · {test.get('count', 0)} вопр. · "
                f"В{test.get('variant', 1)} · {test.get('date', '')} {test.get('time', '')}"
            )
        meta_lbl.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-size: 11px; background: transparent; border: none;"
        )
        info_lay.addWidget(topic_lbl)
        info_lay.addWidget(meta_lbl)

        view_btn = QPushButton("Открыть")
        view_btn.setStyleSheet(STYLE_BTN_SECONDARY)
        view_btn.setFixedWidth(90)
        test_id = test.get("id", "")
        view_btn.clicked.connect(lambda _, tid=test_id: self.view_clicked.emit(tid))

        row.addLayout(info_lay, 1)
        row.addWidget(view_btn)

        return card



class TextbooksPage(QWidget):
    textbook_selected = Signal(str, str)
    back_clicked = Signal()

    def __init__(self, registry, parent=None):
        super().__init__(parent)
        self.registry = registry
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(28, 26, 28, 26)
        self.setStyleSheet(f"background: {COLORS['main_bg']};")

        header = QHBoxLayout()
        header.setSpacing(12)
        back_btn = QPushButton("←  Назад")
        back_btn.setStyleSheet(STYLE_BTN_SECONDARY)
        back_btn.setFixedWidth(110)
        back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        back_btn.clicked.connect(self.back_clicked.emit)

        title = QLabel("Банки вопросов")
        title.setStyleSheet(f"""
            QLabel {{
                color: {COLORS['text_primary']};
                font-size: 19px;
                font-weight: 700;
                background: transparent;
                border: none;
                letter-spacing: -0.2px;
            }}
        """)

        add_bank_btn = QPushButton("+ Банк вопросов")
        add_bank_btn.setStyleSheet(STYLE_BTN_PRIMARY)
        add_bank_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_bank_btn.clicked.connect(self._add_question_bank)

        header.addWidget(back_btn)
        header.addWidget(title)
        header.addStretch()
        header.addWidget(add_bank_btn)
        layout.addLayout(header)

        layout.addWidget(make_separator())

        hint = QLabel(
            "Добавьте папку с файлами *.json (ключ «questions»). "
            "Модель только подбирает номера заданий из банка по теме; тексты вопросов из PDF не генерируются."
        )
        hint.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-size: 11px; background: transparent; border: none;"
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.index_progress = QLabel("")
        self.index_progress.setStyleSheet(
            f"color: {COLORS['accent']}; font-size: 12px; background: transparent; border: none;"
        )
        layout.addWidget(self.index_progress)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(
            "QScrollArea { border: none; background: transparent; }"
            + STYLE_SCROLLBAR
        )

        self.list_container = QWidget()
        self.list_container.setStyleSheet(f"background: {COLORS['main_bg']};")
        self.list_layout = QVBoxLayout(self.list_container)
        self.list_layout.setSpacing(8)
        self.list_layout.setContentsMargins(0, 0, 0, 12)

        scroll.setWidget(self.list_container)
        layout.addWidget(scroll)

        self.refresh()

    def refresh(self):
        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        books = self.registry.get_all()
        if not books:
            empty = QLabel("Банки не добавлены. Нажмите «+ Банк вопросов».")
            empty.setStyleSheet(
                f"color: {COLORS['text_muted']}; font-size: 14px; background: transparent; border: none;"
            )
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.list_layout.addWidget(empty)
        else:
            for book in books:
                row = self._make_book_row(book)
                self.list_layout.addWidget(row)

        self.list_layout.addStretch()

    def _make_book_row(self, book: dict) -> QFrame:
        card = make_card()
        row = QHBoxLayout(card)
        row.setContentsMargins(16, 12, 16, 12)

        info_lay = QVBoxLayout()
        name_lbl = QLabel(book["name"])
        name_lbl.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 13px; font-weight: 600; background: transparent; border: none;"
        )
        path_lbl = QLabel(book["file"])
        path_lbl.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-size: 10px; background: transparent; border: none;"
        )
        badge = QLabel("Банк")
        badge.setStyleSheet(
            f"color: {COLORS['accent']}; font-size: 10px; font-weight: 600; background: transparent; border: none;"
        )
        info_lay.addWidget(name_lbl)
        info_lay.addWidget(badge)
        info_lay.addWidget(path_lbl)

        use_btn = QPushButton("Использовать")
        use_btn.setStyleSheet(STYLE_BTN_PRIMARY)
        use_btn.setMinimumWidth(140)
        use_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        use_btn.clicked.connect(lambda _, b=book: self._use_bank(b))

        del_btn = QPushButton("Удалить")
        del_btn.setStyleSheet(STYLE_BTN_SECONDARY)
        del_btn.setFixedWidth(80)
        del_btn.clicked.connect(lambda _, b=book: self._delete_book(b))

        row.addLayout(info_lay, 1)
        row.addWidget(use_btn)
        row.addWidget(del_btn)

        return card

    def _add_question_bank(self):
        """Добавляет папку с JSON-файлами вопросов."""
        root = Path(__file__).resolve().parents[1]
        default_dir = str(root.parent / "Materials" / "Вопросы")
        if not os.path.isdir(default_dir):
            default_dir = str(root)

        folder = QFileDialog.getExistingDirectory(
            self,
            "Папка с JSON-банком вопросов",
            default_dir,
            QFileDialog.Option.ShowDirsOnly,
        )
        if not folder:
            return

        from PySide6.QtWidgets import QInputDialog

        name, ok = QInputDialog.getText(
            self,
            "Название банка",
            "Как показывать в списке (напр. История 5 кл · банк):",
            text=os.path.basename(os.path.normpath(folder)),
        )
        if not ok or not name.strip():
            return

        err = ""
        ok_add = False
        try:
            ok_add = self.registry.add_bank(name.strip(), folder)
        except Exception as e:
            err = str(e)

        if not ok_add:
            msg = err or (
                "Не удалось добавить банк. Проверьте папку: нужны файлы *.json "
                'с ключом \"questions\" (кроме manifest.json).'
            )
            QMessageBox.warning(self, "Ошибка", msg)
            return

        self.refresh()
        self._use_bank({"name": name.strip(), "file": os.path.abspath(folder), "kind": "bank"})

    def _use_bank(self, book: dict):
        from question_bank import QuestionBankIndex, validate_bank_folder

        ok, message = validate_bank_folder(book["file"])
        if not ok:
            QMessageBox.warning(self, f"Банк «{book['name']}»", message)
            self.index_progress.setText("")
            return
        try:
            n = QuestionBankIndex(book["file"]).count()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", str(e))
            self.index_progress.setText("")
            return

        self.index_progress.setText(
            f"Банк «{book['name']}» подключён. Вопросов в файлах: {n}"
        )
        self.textbook_selected.emit(book["name"], book["file"])

    def _delete_book(self, book: dict):
        reply = QMessageBox.question(
            self, "Подтверждение",
            f"Удалить «{book['name']}» из списка?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.registry.remove(book["name"])
            self.refresh()


class HomePage(QWidget):
    generate_requested = Signal(dict)
    open_textbooks = Signal()
    textbook_choice_changed = Signal(str)

    def __init__(self, model_runner, storage, textbook_registry, parent=None):
        super().__init__(parent)
        self.model_runner = model_runner
        self.storage = storage
        self.textbook_registry = textbook_registry
        self._current_textbook_name = ""
        self._current_textbook_file = ""
        self._build_ui()

    QTYPE_META = [
        ("test",       "Тест",          "qtype-test.svg",   "4 варианта ответа"),
        ("open",       "Открытый",      "qtype-open.svg",   "развёрнутый ответ"),
        ("match",      "Сопоставление", "qtype-match.svg",  "соотнести пары"),
        ("chronology", "Хронология",    "qtype-chrono.svg", "порядок событий"),
    ]

    def _build_ui(self):
        self.setStyleSheet(f"background: {COLORS['main_bg']};")

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(24, 18, 24, 18)

        header_row = QHBoxLayout()
        header_row.setSpacing(12)
        h1 = QLabel("Создание нового теста")
        h1.setStyleSheet(f"""
            QLabel {{
                color: {COLORS['text_primary']};
                font-size: 20px;
                font-weight: 700;
                background: transparent;
                border: none;
                letter-spacing: -0.2px;
            }}
        """)
        self.total_badge = QLabel("Всего вопросов: 10")
        self.total_badge.setStyleSheet(f"""
            QLabel {{
                color: {COLORS['green_pressed']};
                background: {COLORS['green_subtle']};
                border: 1px solid {COLORS['green_border']};
                border-radius: 999px;
                padding: 4px 12px;
                font-size: 12px;
                font-weight: 600;
            }}
        """)
        header_row.addWidget(h1)
        header_row.addStretch()
        header_row.addWidget(self.total_badge)
        layout.addLayout(header_row)

        row1 = QHBoxLayout()
        row1.setSpacing(12)

        book_card = make_card()
        book_lay = QVBoxLayout(book_card)
        book_lay.setContentsMargins(16, 12, 16, 12)
        book_lay.setSpacing(8)

        book_title = QLabel("Банк вопросов")
        book_title.setStyleSheet(STYLE_LABEL_TITLE)

        book_row = QHBoxLayout()
        book_row.setSpacing(8)

        self.book_combo = QComboBox()
        self.book_combo.setStyleSheet(STYLE_INPUT)
        self.book_combo.setMinimumHeight(36)
        self.book_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.book_combo.addItem("— Банк не выбран —")
        self._refresh_book_combo()
        self.book_combo.currentIndexChanged.connect(self._on_book_combo_changed)

        add_book_btn = QPushButton("＋")
        add_book_btn.setStyleSheet(f"""
            QPushButton {{
                background: {COLORS['card_bg']};
                color: {COLORS['text_primary']};
                border: 1px solid {COLORS['btn_inactive_border']};
                border-radius: 8px;
                font-size: 16px;
                font-weight: 500;
                min-width: 36px; max-width: 36px;
                min-height: 36px; max-height: 36px;
            }}
            QPushButton:hover {{
                background: {COLORS['green_subtle']};
                border-color: {COLORS['green_border']};
                color: {COLORS['green_pressed']};
            }}
        """)
        add_book_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_book_btn.setToolTip("Добавить банк вопросов")
        add_book_btn.clicked.connect(self.open_textbooks.emit)

        book_row.addWidget(self.book_combo, 1)
        book_row.addWidget(add_book_btn)

        book_lay.addWidget(book_title)
        book_lay.addLayout(book_row)
        row1.addWidget(book_card, 3)

        nums_card = make_card()
        nums_lay = QVBoxLayout(nums_card)
        nums_lay.setContentsMargins(16, 12, 16, 12)
        nums_lay.setSpacing(8)

        nums_title = QLabel("Количество")
        nums_title.setStyleSheet(STYLE_LABEL_TITLE)

        nums_row = QHBoxLayout()
        nums_row.setSpacing(14)

        q_block = QHBoxLayout()
        q_block.setSpacing(8)
        q_lbl = QLabel("Вопросов")
        q_lbl.setStyleSheet(f"""
            QLabel {{
                color: {COLORS['text_muted']};
                font-size: 11px; font-weight: 500;
                background: transparent; border: none;
            }}
        """)
        self.count_value = QLabel("10")
        self.count_value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.count_value.setFixedSize(46, 36)
        self.count_value.setStyleSheet(f"""
            QLabel {{
                color: {COLORS['text_primary']};
                background: {COLORS['accent_subtle']};
                border: 1px solid {COLORS['btn_inactive_border']};
                border-radius: 8px;
                font-size: 14px;
                font-weight: 700;
            }}
        """)
        q_block.addWidget(q_lbl)
        q_block.addWidget(self.count_value)
        nums_row.addLayout(q_block)

        sep_v = QFrame()
        sep_v.setFrameShape(QFrame.Shape.VLine)
        sep_v.setStyleSheet(
            f"QFrame {{ background: {COLORS['card_border']}; border: none; max-width: 1px; }}"
        )
        nums_row.addWidget(sep_v)

        v_block = QHBoxLayout()
        v_block.setSpacing(6)
        v_lbl = QLabel("Вариантов")
        v_lbl.setStyleSheet(q_lbl.styleSheet())

        v_minus = self._make_stepper_btn("−")
        v_plus = self._make_stepper_btn("+")
        self.variants_spin = QSpinBox()
        self.variants_spin.setRange(1, 10)
        self.variants_spin.setValue(1)
        self.variants_spin.setStyleSheet(STYLE_INPUT)
        self.variants_spin.setFixedWidth(48)
        self.variants_spin.setMinimumHeight(36)
        self.variants_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.variants_spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self.variants_spin.setReadOnly(True)
        v_minus.clicked.connect(lambda: self.variants_spin.setValue(max(1, self.variants_spin.value() - 1)))
        v_plus.clicked.connect(lambda: self.variants_spin.setValue(min(10, self.variants_spin.value() + 1)))

        v_block.addWidget(v_lbl)
        v_block.addWidget(v_minus)
        v_block.addWidget(self.variants_spin)
        v_block.addWidget(v_plus)
        nums_row.addLayout(v_block)
        nums_row.addStretch()

        nums_lay.addWidget(nums_title)
        nums_lay.addLayout(nums_row)
        row1.addWidget(nums_card, 4)

        diff_card = make_card()
        diff_lay = QVBoxLayout(diff_card)
        diff_lay.setContentsMargins(16, 12, 16, 12)
        diff_lay.setSpacing(8)

        diff_title = QLabel("Сложность")
        diff_title.setStyleSheet(STYLE_LABEL_TITLE)
        diff_btns = QHBoxLayout()
        diff_btns.setSpacing(6)

        self.diff_group = []
        self._selected_difficulty = "medium"
        for key, label in [("easy", "Лёгкая"), ("medium", "Средняя"), ("hard", "Сложная")]:
            btn = QPushButton(label)
            btn.setProperty("diff_key", key)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setMinimumHeight(36)
            btn.setStyleSheet(STYLE_BTN_TOGGLE_ACTIVE if key == "medium" else STYLE_BTN_TOGGLE_INACTIVE)
            btn.clicked.connect(lambda _, k=key: self._select_difficulty(k))
            self.diff_group.append(btn)
            diff_btns.addWidget(btn)

        diff_lay.addWidget(diff_title)
        diff_lay.addLayout(diff_btns)
        row1.addWidget(diff_card, 4)

        layout.addLayout(row1)

        topic_card = make_card()
        topic_lay = QVBoxLayout(topic_card)
        topic_lay.setContentsMargins(16, 12, 16, 12)
        topic_lay.setSpacing(8)

        topic_title = QLabel("Тема")
        topic_title.setStyleSheet(STYLE_LABEL_TITLE)

        self.topic_edit = QLineEdit()
        self.topic_edit.setPlaceholderText("Например: Отмена крепостного права")
        self.topic_edit.setStyleSheet(STYLE_INPUT)
        self.topic_edit.setMinimumHeight(36)

        prompt_title = QLabel("Дополнительные инструкции (необязательно)")
        prompt_title.setStyleSheet(f"""
            QLabel {{
                color: {COLORS['text_secondary']};
                font-size: 12px;
                font-weight: 500;
                background: transparent;
                border: none;
                margin-top: 2px;
            }}
        """)

        self.custom_prompt_edit = QTextEdit()
        self.custom_prompt_edit.setPlaceholderText(
            "Например: «Сделай вопросы про даты и исторических деятелей» "
            "или «Используй только факты из параграфа 12»"
        )
        self.custom_prompt_edit.setStyleSheet(STYLE_INPUT)
        self.custom_prompt_edit.setFixedHeight(64)

        topic_lay.addWidget(topic_title)
        topic_lay.addWidget(self.topic_edit)
        topic_lay.addWidget(prompt_title)
        topic_lay.addWidget(self.custom_prompt_edit)
        layout.addWidget(topic_card)

        types_card = make_card()
        types_lay = QVBoxLayout(types_card)
        types_lay.setContentsMargins(16, 12, 16, 12)
        types_lay.setSpacing(10)

        types_header = QHBoxLayout()
        types_title = QLabel("Тип вопросов")
        types_title.setStyleSheet(STYLE_LABEL_TITLE)
        types_hint = QLabel("Можно комбинировать — общее количество складывается")
        types_hint.setStyleSheet(STYLE_LABEL_MUTED)
        types_header.addWidget(types_title)
        types_header.addStretch()
        types_header.addWidget(types_hint)
        types_lay.addLayout(types_header)

        types_row = QHBoxLayout()
        types_row.setSpacing(10)

        self.type_counts: dict[str, int] = {k: 0 for k, *_ in self.QTYPE_META}
        self.type_counts["test"] = 10
        self._type_value_labels: dict[str, QLabel] = {}

        for key, name, icon_name, descr in self.QTYPE_META:
            card = self._make_qtype_card(key, name, icon_name, descr)
            types_row.addWidget(card, 1)

        types_lay.addLayout(types_row)
        layout.addWidget(types_card)

        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(12)

        recent_card = make_card()
        recent_lay = QVBoxLayout(recent_card)
        recent_lay.setContentsMargins(16, 12, 16, 12)
        recent_lay.setSpacing(8)

        recent_header = QHBoxLayout()
        recent_title = QLabel("Последние тесты")
        recent_title.setStyleSheet(STYLE_LABEL_TITLE)
        self.all_tests_btn = QPushButton("Все  →")
        self.all_tests_btn.setStyleSheet(STYLE_BTN_SECONDARY)
        self.all_tests_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.all_tests_btn.setFixedHeight(28)
        recent_header.addWidget(recent_title)
        recent_header.addStretch()
        recent_header.addWidget(self.all_tests_btn)
        recent_lay.addLayout(recent_header)

        self.recent_list_lay = QVBoxLayout()
        self.recent_list_lay.setSpacing(6)
        recent_lay.addLayout(self.recent_list_lay)
        recent_lay.addStretch()

        self.show_more_btn = QPushButton()
        self.show_more_btn.setVisible(False)

        bottom_row.addWidget(recent_card, 5)

        gen_panel = QFrame()
        gen_panel.setStyleSheet("QFrame { background: transparent; border: none; }")
        gen_panel_lay = QVBoxLayout(gen_panel)
        gen_panel_lay.setSpacing(8)
        gen_panel_lay.setContentsMargins(0, 0, 0, 0)

        self.cb_explanations = QCheckBox("Включить пояснения к ответам")
        self.cb_explanations.setChecked(True)
        self.cb_explanations.setStyleSheet(STYLE_CHECKBOX)
        self.cb_explanations.setCursor(Qt.CursorShape.PointingHandCursor)

        self.gen_btn = QPushButton("Сгенерировать тест")
        self.gen_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.gen_btn.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0 {COLORS['green']}, stop:1 {COLORS['green_pressed']}
                );
                color: white;
                border: 1px solid {COLORS['green_pressed']};
                border-radius: 12px;
                padding: 16px 24px;
                font-size: 14px;
                font-weight: 700;
                letter-spacing: 0.3px;
                min-height: 56px;
            }}
            QPushButton:hover {{
                background: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0 {COLORS['green_hover']}, stop:1 {COLORS['green_pressed']}
                );
            }}
            QPushButton:pressed {{
                background: {COLORS['green_pressed']};
            }}
            QPushButton:disabled {{
                background: {COLORS['btn_disabled_bg']};
                color: {COLORS['btn_disabled_text']};
                border-color: {COLORS['card_border']};
            }}
        """)
        self.gen_btn.clicked.connect(self._on_generate)
        self.gen_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        gen_shadow = QGraphicsDropShadowEffect(self.gen_btn)
        gen_shadow.setBlurRadius(22)
        gen_shadow.setOffset(0, 6)
        gen_shadow.setColor(QColor(52, 168, 83, 90))
        self.gen_btn.setGraphicsEffect(gen_shadow)

        self.gen_progress = QProgressBar()
        self.gen_progress.setRange(0, 0)
        self.gen_progress.setVisible(False)
        self.gen_progress.setTextVisible(False)
        self.gen_progress.setFixedHeight(4)
        self.gen_progress.setStyleSheet(f"""
            QProgressBar {{
                background: {COLORS['card_border']};
                border: none;
                border-radius: 2px;
            }}
            QProgressBar::chunk {{
                background: {COLORS['green']};
                border-radius: 2px;
            }}
        """)

        self.gen_status_label = QLabel("")
        self.gen_status_label.setStyleSheet(f"""
            QLabel {{
                color: {COLORS['text_secondary']};
                font-size: 11px;
                font-weight: 500;
                background: transparent;
                border: none;
            }}
        """)
        self.gen_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.gen_status_label.setWordWrap(True)

        gen_panel_lay.addWidget(self.cb_explanations)
        gen_panel_lay.addWidget(self.gen_btn)
        gen_panel_lay.addWidget(self.gen_progress)
        gen_panel_lay.addWidget(self.gen_status_label)

        bottom_row.addWidget(gen_panel, 4)
        layout.addLayout(bottom_row)

        self._refresh_total_badge()

    def _make_qtype_card(self, key: str, name: str, icon_name: str, descr: str) -> QFrame:
        """Карточка типа вопросов: иконка, название, степпер +/−."""
        card = QFrame()
        card.setObjectName(f"qtype_{key}")
        card.setStyleSheet(f"""
            QFrame {{
                background: {COLORS['card_bg']};
                border: 1px solid {COLORS['card_border']};
                border-radius: 10px;
            }}
        """)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)

        # Шапка: иконка + название
        head = QHBoxLayout()
        head.setSpacing(8)
        icon_lbl = QLabel()
        pix = pixmap_from_icon_file(ICONS_DIR / icon_name, 20)
        if not pix.isNull():
            icon_lbl.setPixmap(pix)
        name_lbl = QLabel(name)
        name_lbl.setStyleSheet(f"""
            QLabel {{
                color: {COLORS['text_primary']};
                font-size: 13px;
                font-weight: 600;
            }}
        """)
        head.addWidget(icon_lbl)
        head.addWidget(name_lbl)
        head.addStretch()
        lay.addLayout(head)

        descr_lbl = QLabel(descr)
        descr_lbl.setStyleSheet(f"""
            QLabel {{
                color: {COLORS['text_muted']};
                font-size: 11px;
            }}
        """)
        lay.addWidget(descr_lbl)

        # Степпер
        step = QHBoxLayout()
        step.setSpacing(6)
        minus = self._make_stepper_btn("−")
        plus = self._make_stepper_btn("+")
        value = QLabel(str(self.type_counts.get(key, 0)))
        value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        value.setFixedSize(40, 30)
        value.setStyleSheet(f"""
            QLabel {{
                color: {COLORS['text_primary']};
                background: {COLORS['accent_subtle']};
                border: 1px solid {COLORS['btn_inactive_border']};
                border-radius: 7px;
                font-size: 13px;
                font-weight: 700;
            }}
        """)
        # Уменьшим размер степперов в карточке
        for b in (minus, plus):
            b.setFixedSize(30, 30)

        minus.clicked.connect(lambda _, k=key: self._adjust_type_count(k, -1))
        plus.clicked.connect(lambda _, k=key: self._adjust_type_count(k, +1))

        step.addWidget(minus)
        step.addWidget(value, 1)
        step.addWidget(plus)
        lay.addLayout(step)

        self._type_value_labels[key] = value
        return card

    def _adjust_type_count(self, key: str, delta: int):
        """Изменяет счётчик типа и синхронизирует общее количество."""
        current = self.type_counts.get(key, 0)
        new_val = max(0, min(30, current + delta))
        if new_val == current:
            return
        self.type_counts[key] = new_val
        if key in self._type_value_labels:
            self._type_value_labels[key].setText(str(new_val))
        self._refresh_total_badge()

    def _refresh_total_badge(self):
        """Пересчитывает общее количество вопросов и обновляет бейдж."""
        total = sum(self.type_counts.values())
        self.count_value.setText(str(total))
        self.total_badge.setText(f"Всего вопросов: {total}")
        # Подсветка: красный, если 0; зелёный, если > 0
        if total == 0:
            self.total_badge.setStyleSheet(f"""
                QLabel {{
                    color: {COLORS['error']};
                    background: #FBE9EC;
                    border: 1px solid {COLORS['error']};
                    border-radius: 999px;
                    padding: 4px 12px;
                    font-size: 12px;
                    font-weight: 600;
                }}
            """)
        else:
            self.total_badge.setStyleSheet(f"""
                QLabel {{
                    color: {COLORS['green_pressed']};
                    background: {COLORS['green_subtle']};
                    border: 1px solid {COLORS['green_border']};
                    border-radius: 999px;
                    padding: 4px 12px;
                    font-size: 12px;
                    font-weight: 600;
                }}
            """)

    def _make_stepper_btn(self, symbol: str) -> QPushButton:
        """Кнопка-степпер ± для счётчиков."""
        btn = QPushButton(symbol)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(f"""
            QPushButton {{
                background: {COLORS['card_bg']};
                color: {COLORS['text_primary']};
                border: 1px solid {COLORS['btn_inactive_border']};
                border-radius: 8px;
                font-size: 16px;
                font-weight: 500;
                min-width: 36px; max-width: 36px;
                min-height: 36px; max-height: 36px;
            }}
            QPushButton:hover {{
                background: {COLORS['accent_subtle']};
                border-color: {COLORS['card_border_strong']};
            }}
            QPushButton:pressed {{
                background: {COLORS['status_bg']};
            }}
        """)
        return btn


    def _select_difficulty(self, key: str):
        self._selected_difficulty = key
        for btn in self.diff_group:
            if btn.property("diff_key") == key:
                btn.setStyleSheet(STYLE_BTN_TOGGLE_ACTIVE)
            else:
                btn.setStyleSheet(STYLE_BTN_TOGGLE_INACTIVE)

    def _on_generate(self):
        topic = self.topic_edit.text().strip()
        if not topic:
            QMessageBox.warning(self, "Тема не указана", "Введите тему для генерации вопросов.")
            self.topic_edit.setFocus()
            return

        sel_name = (self._current_textbook_name or "").strip()
        book = self.textbook_registry.get_by_name(sel_name) if sel_name else None
        textbook_display = (
            sel_name if sel_name and not sel_name.startswith("—") else ""
        )

        if not book:
            QMessageBox.warning(
                self,
                "Банк не выбран",
                "Выберите банк вопросов в списке или добавьте папку в разделе «Банки вопросов».",
            )
            return

        if not book.get("file") or not os.path.isdir(book["file"]):
            QMessageBox.warning(
                self,
                "Банк недоступен",
                "Папка банка не найдена. Добавьте или выберите банк заново.",
            )
            return

        if not self.model_runner.is_loaded:
            QMessageBox.warning(
                self, "Модель не загружена",
                "Сначала загрузите модель в разделе «Настройки модели»."
            )
            return

        distribution = {k: v for k, v in self.type_counts.items() if v > 0}
        total = sum(distribution.values())
        if total == 0:
            QMessageBox.warning(
                self, "Не выбраны вопросы",
                "Укажите количество хотя бы для одного типа вопросов."
            )
            return

        params = {
            "topic": topic,
            "type_distribution": distribution,
            "count": total,
            "difficulty": self._selected_difficulty,
            "custom_prompt": self.custom_prompt_edit.toPlainText().strip(),
            "include_answers": True,
            "include_explanations": self.cb_explanations.isChecked(),
            "num_variants": self.variants_spin.value(),
            "bank_folder": os.path.abspath(book["file"]),
            "textbook_name": textbook_display,
        }
        self.generate_requested.emit(params)

    def set_generating(self, is_generating: bool, status: str = ""):
        self.gen_btn.setEnabled(not is_generating)
        self.gen_progress.setVisible(is_generating)
        if is_generating:
            self.gen_btn.setText("Выполняется генерация...")
        else:
            self.gen_btn.setText("Сгенерировать тест")
        self.gen_status_label.setText(status)

    def set_textbook(self, name: str, filepath: str = ""):
        self._current_textbook_name = name
        self._current_textbook_file = filepath
        idx = self.book_combo.findText(name)
        if idx >= 0:
            self.book_combo.setCurrentIndex(idx)
        else:
            self.book_combo.addItem(name)
            self.book_combo.setCurrentText(name)

    def _refresh_book_combo(self):
        from textbook_registry import TextbookRegistry
        reg = TextbookRegistry()
        current = self.book_combo.currentText()
        self.book_combo.blockSignals(True)
        self.book_combo.clear()
        self.book_combo.addItem("— Банк не выбран —")
        for book in reg.get_all():
            self.book_combo.addItem(book["name"])
        idx = self.book_combo.findText(current)
        if idx >= 0:
            self.book_combo.setCurrentIndex(idx)
        self.book_combo.blockSignals(False)

    def _on_book_combo_changed(self, idx: int):
        if idx <= 0:
            return
        selected = self.book_combo.itemText(idx).strip()
        if selected:
            self.textbook_choice_changed.emit(selected)

    def refresh_recent_tests(self, storage):
        """Всегда показывает 2 последних теста (без раскрытия)."""
        while self.recent_list_lay.count():
            item = self.recent_list_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        tests = storage.get_recent(limit=2)
        if not tests:
            empty = QLabel("Тестов пока нет")
            empty.setStyleSheet(f"""
                QLabel {{
                    color: {COLORS['text_muted']};
                    font-size: 12px;
                    background: transparent;
                    border: none;
                    padding: 8px 4px;
                }}
            """)
            self.recent_list_lay.addWidget(empty)
            return

        for test in tests:
            wrapper = QFrame()
            wrapper.setStyleSheet(f"""
                QFrame {{
                    background: {COLORS['status_bg']};
                    border: 1px solid {COLORS['card_border']};
                    border-radius: 8px;
                }}
                QFrame:hover {{
                    background: {COLORS['accent_subtle']};
                    border-color: {COLORS['card_border_strong']};
                }}
                QFrame QLabel {{ background: transparent; border: none; }}
            """)
            wrapper_lay = QHBoxLayout(wrapper)
            wrapper_lay.setContentsMargins(12, 10, 12, 10)
            wrapper_lay.setSpacing(8)

            info_lay = QVBoxLayout()
            info_lay.setSpacing(2)

            topic_lbl = QLabel(test.get("topic", "—"))
            topic_lbl.setStyleSheet(f"""
                QLabel {{
                    color: {COLORS['text_primary']};
                    font-size: 12px;
                    font-weight: 600;
                }}
            """)
            if test.get("multi_variant"):
                nvar = int(test.get("variant_count") or len(test.get("variants") or []) or 1)
                meta_lbl = QLabel(
                    f"{nvar} вар. · всего: {test.get('count', 0)} · {test.get('date', '')}"
                )
            else:
                meta_lbl = QLabel(
                    f"{test.get('count', 0)} вопр. · {test.get('date', '')}"
                )
            meta_lbl.setStyleSheet(f"""
                QLabel {{
                    color: {COLORS['text_muted']};
                    font-size: 11px;
                }}
            """)
            info_lay.addWidget(topic_lbl)
            info_lay.addWidget(meta_lbl)

            wrapper_lay.addLayout(info_lay, 1)
            self.recent_list_lay.addWidget(wrapper)

    def _show_more_tests(self):
        """Заглушка для обратной совместимости (кнопка скрыта)."""
        pass



class AboutPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background: {COLORS['main_bg']};")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(18)

        title = QLabel("Генератор тестов по истории")
        title.setStyleSheet(f"""
            QLabel {{
                color: {COLORS['text_primary']};
                font-size: 22px;
                font-weight: 700;
                background: transparent;
                border: none;
                letter-spacing: -0.3px;
            }}
        """)
        layout.addWidget(title)

        layout.addWidget(make_separator())

        info_text = """
<b>Версия:</b> 1.0.0<br><br>
<b>Описание:</b><br>
Приложение для сборки тестов из готовых JSON-банков вопросов.<br>
Локальная модель подбирает задания по теме; интернет не нужен.<br><br>
<b>Технологии:</b><br>
• Интерфейс: PySide6<br>
• Нейросеть: llama-cpp-python (GGUF-модели)<br>
• Рекомендуемая модель: Qwen2.5-3B/7B-Instruct<br>
• Экспорт: python-docx (.docx)<br><br>
<b>Как использовать:</b><br>
<<<<<<< HEAD
1. Скачайте GGUF-модель отдельно от приложения<br>
2. Положите .gguf файл в папку «Документы / ИИ-помощник учителя / Модели» или в любое удобное место<br>
3. В разделе «Банки вопросов» добавьте папку с JSON<br>
4. В «Настройки модели» выберите .gguf файл и нажмите «Загрузить»<br>
5. На главной странице выберите банк, введите тему и нажмите «Сгенерировать тест»<br>
6. Экспортируйте результат в Word<br><br>
=======
1. Скачайте GGUF-модель (например, Qwen2.5-3B-Instruct-Q4_K_M.gguf)<br>
2. В разделе «Банки вопросов» добавьте папку с JSON<br>
3. В «Настройки модели» укажите путь к модели и нажмите «Загрузить»<br>
4. На главной странице выберите банк, введите тему и нажмите «Сгенерировать тест»<br>
5. Экспортируйте результат в Word<br><br>
>>>>>>> 06236faa0a59c3fe63a9caebf58e61189dc30581
<b>Ресурсы для скачивания моделей:</b><br>
• https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF<br>
• https://huggingface.co/Qwen/Qwen2.5-7B-Instruct-GGUF
        """

        info_lbl = QLabel(info_text)
        info_lbl.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 12px; background: transparent; border: none; line-height: 1.6;"
        )
        info_lbl.setWordWrap(True)
        info_lbl.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(info_lbl)

        layout.addStretch()



class MainWindow(QMainWindow):
    """Главное окно приложения."""

    @staticmethod
    def _join_worker(worker: Optional[QThread], timeout_ms: int = 180_000) -> None:
        if worker is None or not isinstance(worker, QThread):
            return
        if worker.isRunning():
            worker.wait(timeout_ms)

    @staticmethod
    def _bank_folder_for_saved_textbook(registry, textbook_name: str) -> Optional[str]:
        """Если сохранённый тест связан с записью-банком в реестре — путь к папке JSON."""
        name = (textbook_name or "").strip()
        if not name:
            return None
        item = registry.get_by_name(name)
        if not item or item.get("kind") != "bank":
            return None
        p = item.get("file") or ""
        return p if isinstance(p, str) and os.path.isdir(p) else None

    @staticmethod
    def _infer_difficulty_from_questions(questions: list) -> str:
        for q in questions:
            d = str(getattr(q, "difficulty", "") or "").strip().lower()
            if d in ("easy", "medium", "hard"):
                return d
        return "medium"

    def __init__(self):
        super().__init__()
        self.setWindowTitle("ИИ-помощник учителя · Генератор тестов")
        app_inst = QApplication.instance()
        if app_inst is not None and not app_inst.windowIcon().isNull():
            self.setWindowIcon(app_inst.windowIcon())
        else:
            self.setWindowIcon(app_icon())
        self.setMinimumSize(1180, 760)
<<<<<<< HEAD
        self.resize(1280, 820)
=======
        # Запускаем в полноэкранном режиме
        self.showMaximized()
>>>>>>> 06236faa0a59c3fe63a9caebf58e61189dc30581

        # Инициализируем компоненты
        self._init_components()

        # Строим UI
        self._build_ui()

        # Обновляем недавние тесты
        self.home_page.refresh_recent_tests(self.storage)

        # Статус-бар
        self._update_status_bar()

        # Таймер обновления статуса
        self._status_timer = QTimer()
        self._status_timer.timeout.connect(self._update_status_bar)
        self._status_timer.start(2000)

        # Загружаем последнюю модель если есть
        self._try_auto_load_model()

        # Загружаем последний банк из реестра, если есть
        self._try_auto_load_textbook()

    def closeEvent(self, event):
        st = getattr(self, "_status_timer", None)
        if isinstance(st, QTimer) and st is not None:
            st.stop()
        MainWindow._join_worker(getattr(self, "_generation_worker", None))
        MainWindow._join_worker(getattr(self, "_assistant_worker", None))
        MainWindow._join_worker(getattr(self.model_page, "worker", None))
        super().closeEvent(event)

    def _init_components(self):
        """Инициализирует все бизнес-компоненты."""
        from model_runner import ModelRunner, ModelRegistry
        from textbook_registry import TextbookRegistry
        from question_generator import QuestionGenerator, TestStorage

        self.model_runner = ModelRunner()
        self.model_registry = ModelRegistry()
        self.textbook_registry = TextbookRegistry()
        self.generator = QuestionGenerator(self.model_runner)
        self.storage = TestStorage()

        self._assistant_worker: Optional[TestAssistantWorker] = None

        self._generation_worker: Optional[GenerationWorker] = None
        self._current_variant = 1
        self._pending_variants = 0
        self._generated_questions_buffer: list = []
        self._current_params: dict = {}

    def _build_ui(self):
        """Строит главный layout."""
        central = QWidget()
        central.setStyleSheet(f"background: {COLORS['main_bg']};")
        self.setCentralWidget(central)

        main_row = QHBoxLayout(central)
        main_row.setSpacing(0)
        main_row.setContentsMargins(0, 0, 0, 0)

        # Боковая панель
        sidebar = self._build_sidebar()
        main_row.addWidget(sidebar)

        # Основная часть
        right_side = QVBoxLayout()
        right_side.setSpacing(0)
        right_side.setContentsMargins(0, 0, 0, 0)

        # Стек страниц
        self.stack = QStackedWidget()
        self.stack.setStyleSheet(f"background: {COLORS['main_bg']};")

        # Создаём страницы
        self.home_page = HomePage(
            self.model_runner, self.storage, self.textbook_registry
        )
        self.home_page.generate_requested.connect(self._start_generation)
        self.home_page.open_textbooks.connect(lambda: self._show_page("textbooks"))
        self.home_page.textbook_choice_changed.connect(self._on_home_textbook_choice)
        self.home_page.all_tests_btn.clicked.connect(lambda: self._show_page("all_tests"))
        self.home_page.show_more_btn.clicked.connect(lambda: self._show_page("all_tests"))

        self.textbooks_page = TextbooksPage(
            self.textbook_registry
        )
        self.textbooks_page.textbook_selected.connect(self._on_textbook_selected)
        self.textbooks_page.back_clicked.connect(lambda: self._show_page("home"))

        self.results_page = ResultsPage()
        self.results_page.back_clicked.connect(lambda: self._show_page("home"))
        self.results_page.export_clicked.connect(self._do_export)
        self.results_page.assistant_request.connect(self._on_results_assistant_request)

        self.all_tests_page = AllTestsPage(self.storage)
        self.all_tests_page.back_clicked.connect(lambda: self._show_page("home"))
        self.all_tests_page.view_clicked.connect(self._view_saved_test)

        self.about_page = AboutPage()

        self.model_page = ModelSettingsPage(self.model_runner, self.model_registry)
        self.model_page.back_clicked.connect(self._on_model_back)

        self.stack.addWidget(self.home_page)       # 0
        self.stack.addWidget(self.textbooks_page)  # 1
        self.stack.addWidget(self.results_page)    # 2
        self.stack.addWidget(self.all_tests_page)  # 3
        self.stack.addWidget(self.about_page)      # 4
        self.stack.addWidget(self.model_page)      # 5

        right_side.addWidget(self.stack, 1)

        right_widget = QWidget()
        right_widget.setLayout(right_side)
        right_widget.setStyleSheet(f"background: {COLORS['main_bg']};")
        main_row.addWidget(right_widget, 1)

    def _build_sidebar(self) -> QWidget:
        """Тёмный графитовый sidebar с градиентом, логотипом и иконками меню."""
        sidebar = QWidget()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(232)
        sidebar.setStyleSheet(f"""
            QWidget#Sidebar {{
                background: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0 {COLORS['sidebar_bg_top']},
                    stop:1 {COLORS['sidebar_bg_bottom']}
                );
                border: none;
            }}
            QWidget#Sidebar QLabel {{ background: transparent; border: none; }}
        """)

        lay = QVBoxLayout(sidebar)
        lay.setSpacing(4)
        lay.setContentsMargins(0, 8, 0, 22)

        logo_frame = QFrame()
        logo_frame.setStyleSheet(f"QFrame {{ background: {COLORS['sidebar_bg_top']}; border: none; }}")
        logo_lay = QVBoxLayout(logo_frame)
        logo_lay.setContentsMargins(16, 8, 16, 8)
        logo_lay.setSpacing(0)

        logo_icon = QLabel()
        logo_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if LOGO_PATH.exists():
            pixmap = QPixmap(str(LOGO_PATH))
            if not pixmap.isNull():
                target_width = 156
                dpr = 2.0
                scaled_pixmap = pixmap.scaled(
                    int(target_width * dpr), 
                    int(target_width * dpr),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                scaled_pixmap.setDevicePixelRatio(dpr)
                logo_icon.setPixmap(scaled_pixmap)
                logo_icon.setFixedSize(target_width, target_width)
        logo_icon.setStyleSheet(f"QLabel {{ background: {COLORS['sidebar_bg_top']}; border: none; }}")

        logo_lay.addWidget(logo_icon, 0, Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(logo_frame)
        lay.addSpacing(8)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(
            f"QFrame {{ background: {COLORS['sidebar_separator']}; "
            "border: none; max-height: 1px; }"
        )
        lay.addWidget(sep)
        lay.addSpacing(14)

        section_lbl = QLabel("МЕНЮ")
        section_lbl.setStyleSheet(f"""
            QLabel {{
                color: {COLORS['sidebar_text_dim']};
                font-size: 10px;
                font-weight: 600;
                letter-spacing: 1.4px;
                background: transparent;
                border: none;
                padding: 0 6px 6px 6px;
            }}
        """)
        lay.addWidget(section_lbl)

        self._nav_buttons: dict[str, QPushButton] = {}
        nav_items = [
            ("home",       "Главная",          "home.svg"),
            ("textbooks",  "Банки вопросов",   "book.svg"),
            ("all_tests",  "История тестов",   "tests.svg"),
            ("model",      "Настройки модели", "model.svg"),
            ("about",      "О программе",      "about.svg"),
        ]

        for key, label, icon_name in nav_items:
            btn = QPushButton("  " + label)
            btn.setIcon(load_icon(icon_name))
            btn.setIconSize(QSize(18, 18))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(
                STYLE_SIDEBAR_BTN_ACTIVE if key == "home" else STYLE_SIDEBAR_BTN_INACTIVE
            )
            btn.setMinimumHeight(40)
            btn.setCheckable(False)
            btn.clicked.connect(lambda _, k=key: self._nav_clicked(k))
            lay.addWidget(btn)
            self._nav_buttons[key] = btn

        lay.addStretch()

        self.sidebar_model_card = QFrame()
        self.sidebar_model_card.setObjectName("ModelStatusCard")
        self.sidebar_model_card.setStyleSheet(f"""
            QFrame#ModelStatusCard {{
                background: rgba(255,255,255,0.04);
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 10px;
            }}
            QFrame#ModelStatusCard QLabel {{ background: transparent; border: none; }}
        """)
        status_lay = QVBoxLayout(self.sidebar_model_card)
        status_lay.setContentsMargins(12, 10, 12, 10)
        status_lay.setSpacing(2)

        status_top = QHBoxLayout()
        status_top.setSpacing(8)
        status_top.setContentsMargins(0, 0, 0, 0)

        self.sidebar_status_dot = QLabel("●")
        self.sidebar_status_dot.setStyleSheet(
            f"QLabel {{ color: {COLORS['text_muted']}; font-size: 12px; }}"
        )
        self.sidebar_status_text = QLabel("Модель не загружена")
        self.sidebar_status_text.setStyleSheet(f"""
            QLabel {{
                color: {COLORS['sidebar_text_dim']};
                font-size: 11px;
                font-weight: 600;
                letter-spacing: 0.2px;
            }}
        """)
        status_top.addWidget(self.sidebar_status_dot)
        status_top.addWidget(self.sidebar_status_text)
        status_top.addStretch()
        status_lay.addLayout(status_top)

        self.sidebar_model_name = QLabel("")
        self.sidebar_model_name.setStyleSheet(f"""
            QLabel {{
                color: rgba(255,255,255,0.55);
                font-size: 10px;
                font-weight: 500;
            }}
        """)
        self.sidebar_model_name.setWordWrap(True)
        status_lay.addWidget(self.sidebar_model_name)

        lay.addWidget(self.sidebar_model_card)

        return sidebar


    PAGE_MAP = {
        "home":       0,
        "textbooks":  1,
        "results":    2,
        "all_tests":  3,
        "about":      4,
        "model":      5,
    }

    def _nav_clicked(self, key: str):
        self._show_page(key)

    def _on_model_back(self):
        self._show_page("home")
        self._update_status_bar()

    def _show_page(self, key: str):
        idx = self.PAGE_MAP.get(key)
        if idx is None:
            return
        self.stack.setCurrentIndex(idx)

        nav_key = key if key in self._nav_buttons else "home"
        for k, btn in self._nav_buttons.items():
            btn.setStyleSheet(
                STYLE_SIDEBAR_BTN_ACTIVE if k == nav_key else STYLE_SIDEBAR_BTN_INACTIVE
            )

        if key == "all_tests":
            self.all_tests_page.refresh()
        elif key == "home":
            self.home_page.refresh_recent_tests(self.storage)


    def _on_textbook_selected(self, name: str, filepath: str):
        self.home_page.set_textbook(name, filepath)
        self.textbook_registry.save_last_textbook_path(filepath)
        self._show_page("home")
        self._update_status_bar()

    def _on_home_textbook_choice(self, name: str):
        book = self.textbook_registry.get_by_name(name)
        if not book:
            return
        self.textbooks_page._use_bank(book)


    def _open_model_settings(self):
        """Совместимость со старым API: показываем inline-страницу."""
        self._show_page("model")

    def _try_auto_load_model(self):
        """
        Пытается автоматически загрузить последнюю использованную модель.
<<<<<<< HEAD
        GPU/CPU выбираются автоматически, если пользователь не задал ручной режим.
        HISTORY_TEST_N_GPU_LAYERS всё ещё может переопределить GPU-слои.
=======
        n_gpu_layers из config.json; может переопределяться HISTORY_TEST_N_GPU_LAYERS.
>>>>>>> 06236faa0a59c3fe63a9caebf58e61189dc30581
        """
        path = self.model_registry.get_last_model_path()
        if path and os.path.exists(path):
            try:
<<<<<<< HEAD
                from model_runner import AUTO_N_GPU_LAYERS

                self.model_runner.load_model(
                    path,
                    n_ctx=None,
                    n_threads=None,
                    n_gpu_layers=AUTO_N_GPU_LAYERS,
                    n_batch=256,
                )
                if hasattr(self, "model_page"):
                    self.model_page._update_auto_values_labels()
=======
                self.model_runner.load_model(
                    path,
                    n_ctx=self.model_runner.DEFAULT_PARAMS["n_ctx"],
                    n_threads=None,
                    n_gpu_layers=self.model_registry.get_last_n_gpu_layers(),
                    n_batch=256,
                )
>>>>>>> 06236faa0a59c3fe63a9caebf58e61189dc30581
            except Exception as e:
                logger.warning(f"Автозагрузка модели не удалась: {e}")
        self._update_status_bar()

    def _try_auto_load_textbook(self):
        """Подключает последний банк из реестра."""
        last_path = self.textbook_registry.get_last_textbook_path()
        if last_path and os.path.exists(last_path):
            last_abs = os.path.abspath(last_path)
            for book in self.textbook_registry.get_all():
                if os.path.abspath(book.get("file", "")) != last_abs:
                    continue
                self._on_textbook_selected(book["name"], book["file"])
                return

        books = self.textbook_registry.get_all()
        if books:
            self.home_page.set_textbook(books[0]["name"], books[0]["file"])


    def _start_generation(self, params: dict):
        """Запускает генерацию (возможно нескольких вариантов и нескольких типов)."""
        self._current_params = params
        self._current_variant = 1
        self._pending_variants = params.get("num_variants", 1)
        self._generated_questions_buffer = []

        # Распределение по типам и порядок обхода
        distribution = params.get("type_distribution") or {
            params.get("question_type", "test"): params.get("count", 10)
        }
        self._type_queue = [(t, n) for t, n in distribution.items() if n > 0]
        self._variant_questions_buffer: list = []
        self._current_type_idx = 0

        self.home_page.set_generating(True, "Запуск генерации...")
        self._generate_next_type()

    def _generate_next_type(self):
        """Запускает генерацию вопросов одного типа в рамках текущего варианта."""
        params = self._current_params
        if self._current_type_idx >= len(self._type_queue):
            self._on_variant_done(self._variant_questions_buffer)
            return

        qtype, qcount = self._type_queue[self._current_type_idx]
        type_progress = (
            f" · {qtype} ({qcount})"
            if len(self._type_queue) > 1 else ""
        )
        self.home_page.set_generating(
            True,
            f"Вариант {self._current_variant} из {self._pending_variants}{type_progress}…"
        )

        self._generation_worker = GenerationWorker(
            generator=self.generator,
            topic=params["topic"],
            question_type=qtype,
            count=qcount,
            difficulty=params["difficulty"],
            custom_prompt=params["custom_prompt"],
            include_answers=params["include_answers"],
            include_explanations=params["include_explanations"],
            bank_folder=params.get("bank_folder"),
        )
        self._generation_worker.progress.connect(
            lambda msg: self.home_page.set_generating(True, msg)
        )
        self._generation_worker.generation_finished.connect(self._on_type_done)
        self._generation_worker.generation_error.connect(self._on_generation_error)
        self._generation_worker.start()

    def _on_type_done(self, questions: list):
        """Получены вопросы одного типа — добавляем и переходим к следующему."""
        if questions:
            self._variant_questions_buffer.extend(questions)
        self._current_type_idx += 1
        self._generate_next_type()

    def _on_variant_done(self, questions: list):
        """Все типы для варианта собраны — вкладка буфера, затем следующий вариант или сохранение."""
        params = self._current_params
        vn = self._current_variant

        if questions:
            from question_generator import sort_questions_for_test

            self._generated_questions_buffer.append((vn, sort_questions_for_test(questions)))

        self._current_variant += 1
        self._variant_questions_buffer = []
        self._current_type_idx = 0

        if self._current_variant <= self._pending_variants:
            self._generate_next_type()
        else:
            self.home_page.set_generating(False, "")
            self.home_page.refresh_recent_tests(self.storage)
            self._update_status_bar()

            buf = self._generated_questions_buffer
            if buf:
                primary_type = self._type_queue[0][0] if self._type_queue else "test"
                if len(buf) == 1:
                    variant_num, first_qs = buf[0]
                    self.storage.save_test(
                        topic=params["topic"],
                        textbook_name=params.get("textbook_name", ""),
                        questions=first_qs,
                        variant_num=variant_num,
                        question_type=primary_type,
                    )
                    self.results_page.show_questions(
                        questions=first_qs,
                        topic=params["topic"],
                        textbook=params.get("textbook_name", ""),
                        variant=variant_num,
                        bank_folder=params.get("bank_folder"),
                        difficulty=params.get("difficulty"),
                    )
                else:
                    self.storage.save_generation_session(
                        topic=params["topic"],
                        textbook_name=params.get("textbook_name", ""),
                        batches=buf,
                        question_type=primary_type,
                    )
                    self.results_page.show_variants_bundle(
                        buf,
                        topic=params["topic"],
                        textbook=params.get("textbook_name", ""),
                        bank_folder=params.get("bank_folder"),
                        difficulty=params.get("difficulty"),
                    )
                self._show_page("results")
            else:
                QMessageBox.warning(
                    self, "Предупреждение",
                    "Не удалось сгенерировать ни одного валидного вопроса.\n"
                    "Попробуйте:\n"
                    "• Уточнить тему или сменить банк вопросов\n"
                    "• Уменьшить количество вопросов или изменить типы"
                )

    def _on_generation_error(self, error: str):
        self.home_page.set_generating(False, "")
        QMessageBox.critical(self, "Ошибка генерации", error)


    def _do_export(self, questions: list, topic: str, textbook: str, variant: int):
        bundle = getattr(self.results_page, "_variants_bundle", None)
        qs = questions
        vnum = variant
        if bundle and len(bundle) > 1:
            labels = [
                f"Вариант {vn} ({len(q_list)} вопр.)"
                for vn, q_list in bundle
            ]
            item, ok = QInputDialog.getItem(
                self,
                "Экспорт в Word",
                "Какой вариант сохранить в документ?",
                labels,
                0,
                False,
            )
            if not ok:
                return
            idx = labels.index(item)
            vnum, qs = bundle[idx][0], bundle[idx][1]
        dlg = ExportDialog(qs, topic, textbook, vnum, self)
        result = dlg.exec()
        if result == QDialog.DialogCode.Accepted:
            saved_path = getattr(dlg, "_exported_path", None)
            if saved_path:
                folder = os.path.dirname(saved_path)
                fname = os.path.basename(saved_path)

                def _open_folder():
                    try:
                        if sys.platform == "win32":
                            os.startfile(folder)
                        elif sys.platform == "darwin":
                            os.system(f'open "{folder}"')
                        else:
                            os.system(f'xdg-open "{folder}"')
                    except Exception:
                        pass

                show_toast(
                    self,
                    title="Тест экспортирован",
                    message=fname,
                    kind="success",
                    action_text="Открыть папку",
                    action_callback=_open_folder,
                )

    def _on_results_assistant_request(self, user_message: str):
        rp = self.results_page
        if getattr(rp, "_variants_bundle", None) is not None:
            return
        if not getattr(self.model_runner, "is_loaded", False):
            QMessageBox.warning(
                self,
                "Модель не загружена",
                "Чтобы ассистент спланировал правки и выбрал замену из банка, "
                "сначала загрузите GGUF-модель в разделе «Настройки модели».",
            )
            return

        MainWindow._join_worker(getattr(self, "_assistant_worker", None))
        rp.assistant_prompt_edit.clear()
        rp.set_assistant_busy(True, "Запрос к модели и подбор из банка…")

        worker = TestAssistantWorker(
            self.generator,
            self.model_runner,
            list(rp._questions),
            rp._topic,
            rp._assistant_difficulty,
            rp._assistant_bank_folder,
            user_message,
        )
        self._assistant_worker = worker

        def on_fin(reply: str, qs):
            if self._assistant_worker is not worker:
                return
            rp.set_assistant_busy(False)
            rp.apply_assistant_questions(list(qs))
            rp.set_assistant_status_text(reply)

        def on_err(msg: str):
            if self._assistant_worker is not worker:
                return
            rp.set_assistant_busy(False)
            rp.set_assistant_status_text(msg)

        worker.assistant_finished.connect(on_fin)
        worker.assistant_error.connect(on_err)
        worker.start()

    def _view_saved_test(self, test_id: str):
        """Открывает сохранённый тест из истории."""
        test = self.storage.get_by_id(test_id)
        if not test:
            return

        from question_generator import Question, normalized_test_variants

        pairs = normalized_test_variants(test)
        if not pairs:
            return
        if len(pairs) == 1:
            vn, qdicts = pairs[0]
            questions = [Question.from_dict(q) for q in qdicts]
            bank_folder = MainWindow._bank_folder_for_saved_textbook(
                self.textbook_registry, test.get("textbook", "")
            )
            diff = MainWindow._infer_difficulty_from_questions(questions)
            self.results_page.show_questions(
                questions=questions,
                topic=test.get("topic", ""),
                textbook=test.get("textbook", ""),
                variant=vn,
                bank_folder=bank_folder,
                difficulty=diff,
            )
        else:
            bundle = [(vn, [Question.from_dict(q) for q in qdicts]) for vn, qdicts in pairs]
            bank_folder = MainWindow._bank_folder_for_saved_textbook(
                self.textbook_registry, test.get("textbook", "")
            )
            flat_for_diff: list = []
            for _, qs in bundle:
                flat_for_diff.extend(qs)
            diff = MainWindow._infer_difficulty_from_questions(flat_for_diff)
            self.results_page.show_variants_bundle(
                bundle,
                topic=test.get("topic", ""),
                textbook=test.get("textbook", ""),
                bank_folder=bank_folder,
                difficulty=diff,
            )
        self._show_page("results")

    # ---------------------------------------------------------------- #
    #  Статус                                                           #
    # ---------------------------------------------------------------- #

    def _update_status_bar(self):
        """Обновляет индикатор модели в sidebar (статус-бар внизу удалён)."""
        if self.model_runner.is_loaded:
            mode = "GPU" if getattr(self.model_runner, "using_gpu", False) else "CPU"
            self.sidebar_status_dot.setText("●")
            self.sidebar_status_dot.setStyleSheet(f"""
                QLabel {{
                    color: #6FE3A1;
                    font-size: 14px;
                    background: transparent;
                    border: none;
                }}
            """)
            self.sidebar_status_text.setText(f"Модель загружена · {mode}")
            self.sidebar_status_text.setStyleSheet(f"""
                QLabel {{
                    color: #FFFFFF;
                    font-size: 11px;
                    font-weight: 600;
                    letter-spacing: 0.2px;
                    background: transparent;
                    border: none;
                }}
            """)
            self.sidebar_model_name.setText(self.model_runner.model_name[:30])
            self.sidebar_model_card.setStyleSheet(f"""
                QFrame#ModelStatusCard {{
                    background: rgba(111, 227, 161, 0.07);
                    border: 1px solid rgba(111, 227, 161, 0.30);
                    border-radius: 10px;
                }}
                QFrame#ModelStatusCard QLabel {{ background: transparent; border: none; }}
            """)
            if not self.sidebar_model_card.graphicsEffect():
                glow = QGraphicsDropShadowEffect(self.sidebar_model_card)
                glow.setBlurRadius(22)
                glow.setOffset(0, 0)
                glow.setColor(QColor(111, 227, 161, 90))
                self.sidebar_model_card.setGraphicsEffect(glow)
        else:
            self.sidebar_status_dot.setText("○")
            self.sidebar_status_dot.setStyleSheet(f"""
                QLabel {{
                    color: {COLORS['sidebar_text_dim']};
                    font-size: 12px;
                    background: transparent;
                    border: none;
                }}
            """)
            self.sidebar_status_text.setText("Модель не загружена")
            self.sidebar_status_text.setStyleSheet(f"""
                QLabel {{
                    color: {COLORS['sidebar_text_dim']};
                    font-size: 11px;
                    font-weight: 600;
                    background: transparent;
                    border: none;
                }}
            """)
            self.sidebar_model_name.setText("")
            self.sidebar_model_card.setStyleSheet(f"""
                QFrame#ModelStatusCard {{
                    background: rgba(255,255,255,0.04);
                    border: 1px solid rgba(255,255,255,0.08);
                    border-radius: 10px;
                }}
                QFrame#ModelStatusCard QLabel {{ background: transparent; border: none; }}
            """)
            self.sidebar_model_card.setGraphicsEffect(None)

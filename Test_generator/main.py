"""
Точка входа GUI. ENV для BLAS/OpenMP (один поток) задаётся до импортов NumPy / llama.
"""
import sys
import os


def _configure_cpu_threads():
    for var in (
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "BLIS_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
        "NUMEXPR_NUM_THREADS",
    ):
        os.environ.setdefault(var, "1")
    os.environ.setdefault("GGML_CUDA_NO_PINNED", "1")
    os.environ.setdefault("LLAMA_NO_METAL", "1")


def _boost_process_priority():
    """Windows: класс приоритета CPU и сброс affinity (см. HISTORY_TEST_*). POSIX: os.nice(-5)."""
    if sys.platform != "win32":
        try:
            os.nice(-5)
        except (AttributeError, OSError, PermissionError):
            pass
        return

    priority_name = os.environ.get("HISTORY_TEST_PRIORITY", "high").lower()
    affinity_reset = os.environ.get("HISTORY_TEST_AFFINITY_RESET", "1") == "1"

    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32

        priority_map = {
            "normal":       0x00000020,
            "above":        0x00008000,
            "high":         0x00000080,
            "realtime":     0x00000100,
        }
        prio = priority_map.get(priority_name, 0x80)
        handle = kernel32.GetCurrentProcess()
        kernel32.SetPriorityClass(handle, prio)

        if affinity_reset:
            DWORD_PTR = ctypes.c_size_t
            process_mask = DWORD_PTR(0)
            system_mask = DWORD_PTR(0)
            ok = kernel32.GetProcessAffinityMask(
                handle,
                ctypes.byref(process_mask),
                ctypes.byref(system_mask),
            )
            if ok and system_mask.value:
                kernel32.SetProcessAffinityMask(handle, system_mask.value)

        try:
            min_ws = 256 * 1024 * 1024
            max_ws = 3 * 1024 * 1024 * 1024
            kernel32.SetProcessWorkingSetSize(handle, min_ws, max_ws)
        except Exception:
            pass

    except Exception:
        pass


_configure_cpu_threads()
_boost_process_priority()

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontDatabase, QIcon

from ui import MainWindow, app_icon, COLORS


def _pick_ui_font() -> QFont:
    available = set(QFontDatabase.families())
    preferred = [
        "Inter", "SF Pro Text", "SF UI Text",
        "Segoe UI Variable", "Segoe UI",
        "Helvetica Neue", "Roboto", "system-ui",
    ]
    for name in preferred:
        if name in available:
            f = QFont(name, 10)
            f.setHintingPreference(QFont.HintingPreference.PreferDefaultHinting)
            f.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
            return f
    fallback = QFont()
    ps = fallback.pointSize()
    if ps <= 0:
        fallback.setPointSize(10)
    return fallback


def main():
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "HistoryTestGen.AITestGenerator.1.0"
            )
        except Exception:
            pass

    app = QApplication(sys.argv)
    app.setApplicationName("Генератор тестов по истории")
    app.setApplicationVersion("1.0.0")
    app.setOrganizationName("HistoryTestGen")

    _ico = app_icon()
    app.setWindowIcon(_ico)

    app.setFont(_pick_ui_font())

    app.setStyleSheet(
        f"""
        QToolTip {{
            background-color: {COLORS["card_bg"]};
            color: {COLORS["text_primary"]};
            border: 1px solid {COLORS["card_border"]};
            border-radius: 6px;
            padding: 6px 10px;
            font-size: 12px;
        }}
        QMessageBox {{
            background-color: {COLORS["main_bg"]};
        }}
        QMessageBox QLabel {{
            color: {COLORS["text_primary"]};
            font-size: 13px;
            min-width: 360px;
        }}
        QMessageBox QPushButton {{
            background-color: {COLORS["btn_inactive_bg"]};
            color: {COLORS["btn_inactive_text"]};
            border: 1px solid {COLORS["btn_inactive_border"]};
            border-radius: 8px;
            padding: 8px 16px;
            min-width: 90px;
            font-weight: 500;
        }}
        QMessageBox QPushButton:hover {{
            background-color: {COLORS["accent_subtle"]};
            border-color: {COLORS["card_border_strong"]};
        }}
        QMessageBox QPushButton:default {{
            background-color: {COLORS["accent"]};
            color: {COLORS["text_on_accent"]};
            border: 1px solid {COLORS["accent_pressed"]};
        }}
        QMessageBox QPushButton:default:hover {{
            background-color: {COLORS["accent_hover"]};
        }}
        QScrollBar:vertical {{
            background: transparent;
            width: 10px;
            margin: 4px;
            border: none;
        }}
        QScrollBar::handle:vertical {{
            background: {COLORS["card_border_strong"]};
            border-radius: 4px;
            min-height: 30px;
        }}
        QScrollBar::handle:vertical:hover {{
            background: {COLORS["text_muted"]};
        }}
        QScrollBar::add-line:vertical,
        QScrollBar::sub-line:vertical {{
            height: 0px;
            background: transparent;
        }}
        QScrollBar::add-page:vertical,
        QScrollBar::sub-page:vertical {{
            background: transparent;
        }}
        QScrollBar:horizontal {{
            background: transparent;
            height: 10px;
            margin: 4px;
            border: none;
        }}
        QScrollBar::handle:horizontal {{
            background: {COLORS["card_border_strong"]};
            border-radius: 4px;
            min-width: 30px;
        }}
        QScrollBar::handle:horizontal:hover {{
            background: {COLORS["text_muted"]};
        }}
        QScrollBar::add-line:horizontal,
        QScrollBar::sub-line:horizontal {{
            width: 0px;
            background: transparent;
        }}
    """
    )

    window = MainWindow()
    window.setWindowIcon(_ico)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()

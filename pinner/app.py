"""Application bootstrap (kept separate from ``main.py`` for testability)."""
from __future__ import annotations

import sys

from PyQt6.QtWidgets import QApplication

from . import APP_NAME
from .core.bootstrap import open_repository
from .ui.icons import IconProvider
from .ui.main_window import MainWindow
from .ui.theme import apply_theme


def create_app(argv: list[str] | None = None) -> QApplication:
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(APP_NAME)
    apply_theme(app)
    app.setWindowIcon(IconProvider().get("app"))
    return app


def run() -> int:
    app = create_app()
    window = MainWindow(open_repository())
    window.show()
    return app.exec()

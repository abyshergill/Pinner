"""Apply the system look-and-feel to the QApplication."""
from __future__ import annotations

import sys

from PyQt6.QtWidgets import QApplication, QStyleFactory

from .styles import STYLESHEET, choose_style_name


def apply_theme(app: QApplication) -> None:
    """Follow the OS light/dark setting and accent colour."""
    style = choose_style_name(QStyleFactory.keys(), sys.platform)
    if style:
        app.setStyle(style)
    app.setStyleSheet(STYLESHEET)

"""Shared helpers for the Qt UI tests (skip cleanly when PyQt6 is missing)."""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtWidgets import QApplication
    HAVE_QT = True
except ImportError:  # pragma: no cover
    QApplication = None
    HAVE_QT = False

requires_qt = unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")

_app = None


def get_app():
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication([])
    return _app

"""Tiny wrappers around modal Qt dialogs.

Kept in one module so the tests can replace them and so the widgets stay
free of blocking calls.
"""
from __future__ import annotations

from PyQt6.QtWidgets import QFileDialog, QInputDialog, QLineEdit, QMessageBox, QWidget


def ask_text(parent: QWidget, title: str, label: str, text: str = "") -> str | None:
    value, ok = QInputDialog.getText(parent, title, label, QLineEdit.EchoMode.Normal, text)
    return value if ok else None


def confirm(parent: QWidget, title: str, message: str) -> bool:
    answer = QMessageBox.question(
        parent, title, message,
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )
    return answer == QMessageBox.StandardButton.Yes


def show_error(parent: QWidget, message: str, title: str = "Error") -> None:
    QMessageBox.critical(parent, title, message)


def show_warning(parent: QWidget, message: str, title: str = "Warning") -> None:
    QMessageBox.warning(parent, title, message)


def show_info(parent: QWidget, message: str, title: str = "Pinner") -> None:
    QMessageBox.information(parent, title, message)


def ask_open_file(parent: QWidget, title: str, name_filter: str) -> str | None:
    path, _ = QFileDialog.getOpenFileName(parent, title, "", name_filter)
    return path or None


def ask_save_file(parent: QWidget, title: str, default_name: str, name_filter: str) -> str | None:
    path, _ = QFileDialog.getSaveFileName(parent, title, default_name, name_filter)
    return path or None

"""Open folders, files/apps and web links using the OS defaults."""
from __future__ import annotations

import os
import platform
import subprocess
import webbrowser
from typing import Callable

from .models import Item, ItemKind


class LaunchError(Exception):
    """Raised when an item cannot be opened."""


class Launcher:
    """Side effects are injectable so the class is easy to test."""

    def __init__(
        self,
        system: str | None = None,
        popen: Callable[..., object] = subprocess.Popen,
        browser_open: Callable[[str], bool] = webbrowser.open,
        startfile: Callable[[str], None] | None = None,
    ) -> None:
        self._system = system or platform.system()
        self._popen = popen
        self._browser_open = browser_open
        self._startfile = startfile or getattr(os, "startfile", None)

    def open_item(self, item: Item) -> None:
        if item.kind is ItemKind.URL:
            self.open_url(item.target)
        elif item.kind is ItemKind.FOLDER:
            self.open_folder(item.target)
        else:
            self.open_file(item.target)

    def open_url(self, url: str) -> None:
        if not self._browser_open(url):
            raise LaunchError(f"Could not open link:\n{url}")

    def open_folder(self, path: str) -> None:
        path = os.path.expanduser(path)
        if not os.path.isdir(path):
            raise LaunchError(f"Folder not found:\n{path}")
        self._open_with_os(path)

    def open_file(self, path: str) -> None:
        path = os.path.expanduser(path)
        if not os.path.exists(path):
            raise LaunchError(f"File not found:\n{path}")
        self._open_with_os(path)

    def reveal(self, path: str) -> None:
        """Show a file/folder in the system file manager (selected where supported)."""
        path = os.path.expanduser(path)
        if not os.path.exists(path):
            raise LaunchError(f"Not found:\n{path}")
        try:
            if self._system == "Windows":
                self._popen(["explorer", f"/select,{os.path.normpath(path)}"])
            elif self._system == "Darwin":
                self._popen(["open", "-R", path])
            else:  # no portable "select" on Linux: open the containing folder
                folder = path if os.path.isdir(path) else os.path.dirname(path) or "."
                self._popen(["xdg-open", folder])
        except OSError as exc:
            raise LaunchError(f"Could not open:\n{path}\n\n{exc}") from exc

    def _open_with_os(self, path: str) -> None:
        try:
            if self._system == "Windows" and self._startfile is not None:
                self._startfile(path)
            elif self._system == "Darwin":
                self._popen(["open", path])
            else:
                self._popen(["xdg-open", path])
        except OSError as exc:
            raise LaunchError(f"Could not open:\n{path}\n\n{exc}") from exc

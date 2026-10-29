"""Turns the logical icon names from ``icon_paths`` into ``QIcon`` objects."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtGui import QIcon

from .. import icon_paths
from ..core.models import ItemKind, Section


class IconProvider:
    """Loads icons lazily from the paths declared in ``icon_paths.py``."""

    def __init__(self, paths: dict[str, Path] | None = None) -> None:
        self._paths = dict(paths if paths is not None else icon_paths.ICON_PATHS)
        self._cache: dict[str, QIcon] = {}

    def get(self, name: str) -> QIcon:
        """Return the icon, or an empty ``QIcon`` if the file is missing."""
        if name not in self._cache:
            path = self._paths.get(name)
            self._cache[name] = QIcon(str(path)) if path and Path(path).is_file() else QIcon()
        return self._cache[name]

    def for_kind(self, kind: ItemKind) -> QIcon:
        return self.get(ItemKind(kind).value)

    def for_section_group(self, section: Section) -> QIcon:
        return self.get("group_paths" if Section(section) is Section.PATHS else "group_browser")

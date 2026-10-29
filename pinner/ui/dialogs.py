"""Add / edit dialog for folder paths, files/apps and web links.

When opened for Browser Bookmarks (``section=Section.BROWSER``) it only offers web links.
"""
from __future__ import annotations

import os

from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core.dropped import entry_from_source
from ..core.models import (
    ALLOWED_KINDS,
    BROWSER_LINKS_ONLY,
    ItemKind,
    Section,
    ValidationError,
    clean_name,
    clean_target,
    has_web_scheme,
)
from . import dnd

KIND_LABELS = {
    ItemKind.FOLDER: "Folder",
    ItemKind.FILE: "File / App",
    ItemKind.URL: "Web link",
}


class DropLineEdit(QLineEdit):
    """A line edit that takes a dropped file / folder / link instead of pasting ``file:///``."""

    def __init__(self, *args, on_source=None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._on_source = on_source
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event) -> None:
        if dnd.can_accept(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    dragMoveEvent = dragEnterEvent

    def dropEvent(self, event) -> None:
        sources = dnd.sources_from_mime(event.mimeData())
        if sources and self._on_source:
            self._on_source(sources[0])
            event.acceptProposedAction()
        else:
            event.ignore()


class ItemDialog(QDialog):
    """Collects (kind, display name, target) for one entry."""

    def __init__(self, parent: QWidget | None = None, *, kind: ItemKind = ItemKind.FOLDER,
                 name: str = "", target: str = "", editing: bool = False,
                 section: Section | None = None) -> None:
        super().__init__(parent)
        self.section = Section(section) if section is not None else None
        self.allowed = [k for k in KIND_LABELS if self.section is None or k in ALLOWED_KINDS[self.section]]
        self.links_only = self.allowed == [ItemKind.URL]
        noun = "bookmark" if self.links_only else "entry"
        self.setWindowTitle(f"Edit {noun}" if editing else f"Add {noun}")
        self.setMinimumWidth(500)
        self.setAcceptDrops(True)

        self.kind_combo = QComboBox(self)
        for k in self.allowed:
            self.kind_combo.addItem(KIND_LABELS[k], k.value)
        index = self.kind_combo.findData(ItemKind(kind).value)
        self.kind_combo.setCurrentIndex(index if index >= 0 else 0)

        self.target_edit = DropLineEdit(target, on_source=self.apply_source)
        self.browse_btn = QPushButton("Browse…")
        self.name_edit = QLineEdit(name)
        self.name_edit.setPlaceholderText("Display name, e.g. a customer or project name")
        self.drop_hint = QLabel(
            "Tip: paste a web link or drag one from your browser onto this window.\n"
            "Only links are allowed in bookmarks - files and folders are not."
            if self.links_only else
            "Tip: drag a file, folder or link from your file manager / browser onto this window.")
        self.drop_hint.setObjectName("Hint")
        self.drop_hint.setWordWrap(True)
        self.error_label = QLabel("")
        self.error_label.setObjectName("Error")
        self.error_label.setWordWrap(True)

        target_row = QHBoxLayout()
        target_row.addWidget(self.target_edit, 1)
        target_row.addWidget(self.browse_btn)

        form = QFormLayout()
        if self.links_only:
            self.kind_combo.hide()                 # nothing to choose: bookmarks are always links
        else:
            form.addRow("Type", self.kind_combo)
        form.addRow("Link" if self.links_only else "Location", target_row)
        form.addRow("Name", self.name_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        self.ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.addLayout(form)
        layout.addWidget(self.drop_hint)
        layout.addWidget(self.error_label)
        layout.addWidget(buttons)

        self.browse_btn.clicked.connect(lambda _checked=False: self._browse())
        self.kind_combo.currentIndexChanged.connect(lambda _i=0: self._kind_changed())
        self._kind_changed()

    # ---------------------------------------------------------------- API
    def kind(self) -> ItemKind:
        return ItemKind(self.kind_combo.currentData())

    def values(self) -> tuple[ItemKind, str, str]:
        """Validated ``(kind, name, target)``; raises ``ValidationError``."""
        kind = self.kind()
        target = clean_target(kind, self.target_edit.text(), self.section)
        name = self.name_edit.text().strip() or self._suggest_name(kind, target)
        return kind, clean_name(name), target

    def apply_source(self, source: str) -> bool:
        """Fill type, full path/link and name from a dropped file, folder or link."""
        try:
            if self.links_only and not has_web_scheme(source):
                raise ValidationError(BROWSER_LINKS_ONLY)
            kind, name, target = entry_from_source(source)
            if kind not in self.allowed:
                raise ValidationError(BROWSER_LINKS_ONLY)
        except ValidationError as exc:
            self.error_label.setText(str(exc))
            return False
        self.error_label.setText("")
        self.kind_combo.setCurrentIndex(self.kind_combo.findData(kind.value))
        self.target_edit.setText(target)
        self.name_edit.setText(name)  # a drop always proposes the real file name
        return True

    # ------------------------------------------------------ drag and drop
    def dragEnterEvent(self, event) -> None:
        if dnd.can_accept(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    dragMoveEvent = dragEnterEvent

    def dropEvent(self, event) -> None:
        sources = dnd.sources_from_mime(event.mimeData())
        if sources and self.apply_source(sources[0]):
            event.acceptProposedAction()
        else:
            event.ignore()

    # ------------------------------------------------------------ helpers
    @staticmethod
    def _suggest_name(kind: ItemKind, target: str) -> str:
        if kind is ItemKind.URL:
            return target.split("://", 1)[-1].split("/", 1)[0] or target
        return os.path.basename(target.rstrip("/\\")) or target

    def _kind_changed(self) -> None:
        is_url = self.kind() is ItemKind.URL
        self.browse_btn.setVisible(not is_url)
        self.target_edit.setPlaceholderText(
            "https://example.com" if is_url else "Choose or drop a path…")

    def _browse(self) -> None:
        if self.kind() is ItemKind.FOLDER:
            chosen = QFileDialog.getExistingDirectory(self, "Select folder")
        else:
            chosen, _ = QFileDialog.getOpenFileName(self, "Select file or application")
        if chosen:
            self.target_edit.setText(chosen)
            if not self.name_edit.text().strip():
                self.name_edit.setText(self._suggest_name(self.kind(), chosen))

    def _on_accept(self) -> None:
        try:
            self.values()
        except ValidationError as exc:
            self.error_label.setText(str(exc))
            return
        self.accept()

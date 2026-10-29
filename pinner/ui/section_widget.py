"""One tab: a single tree of folders, sub-folders and the entries inside them.

The same widget powers both the *Paths* tab and the *Browser Bookmarks* tab;
only the ``Section`` differs.

* Folders and sub-folders can be nested to any depth.
* **Paths**: entries are folder paths, files/apps and web links.  Drag files /
  folders / links from the OS onto the tree to add them with their full path.
* **Browser Bookmarks**: entries are *web links only*.  The Add menu offers
  nothing else, dropped files / folders are refused, and bookmarks can be
  imported from / exported to a browser bookmarks file.
* Drag an entry onto another folder to move it.
"""
from __future__ import annotations

import re
from pathlib import Path

from PyQt6.QtCore import QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core import bookmarks, dropped
from ..core.launcher import LaunchError, Launcher
from ..core.models import (
    ALLOWED_KINDS, DuplicateNameError, Group, Item, ItemKind, Section, ValidationError,
)
from ..core.repository import Repository
from . import dnd, prompts
from .dialogs import ItemDialog
from .icons import IconProvider

ID_ROLE = Qt.ItemDataRole.UserRole
TYPE_ROLE = Qt.ItemDataRole.UserRole.value + 1   # plain int: PyQt6 enums don't support '+' on all versions
GROUP, ITEM = "group", "item"

_ADD_LABELS = {ItemKind.URL: "Web link…", ItemKind.FOLDER: "Folder…", ItemKind.FILE: "File / App…"}
IMPORT_FILTER = "Bookmark files (*.html *.htm *.json);;All files (*)"
EXPORT_FILTER = "Bookmarks HTML (*.html)"

_TEXT = {
    Section.PATHS: {
        "hint": "Create a folder (e.g. one per customer), add sub-folders, then pin folders, files and links inside.\n"
                "Tip: drag files or folders from your file manager onto this list.",
        "default_kind": ItemKind.FOLDER,
        "add_tip": "Add a link, folder or file to the selected folder",
        "open_tip": "Open the selected folder, file or link  (Enter / double-click)",
    },
    Section.BROWSER: {
        "hint": "Bookmarks hold web links only - files and folders can't be added here.\n"
                "Tip: drag a link from your browser onto a folder, or use Import / Export to share "
                "bookmarks with Chrome, Edge, Firefox or Safari.",
        "default_kind": ItemKind.URL,
        "add_tip": "Add a web link to the selected folder",
        "open_tip": "Open the selected link in your browser  (Enter / double-click)",
    },
}


class DropTree(QTreeWidget):
    """Tree that accepts files/links dropped from outside and entry moves from inside."""

    sources_dropped = pyqtSignal(list, object)   # [str], target group id or None
    item_moved = pyqtSignal(int, int)            # item id, target group id
    enter_pressed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None, links_only: bool = False) -> None:
        super().__init__(parent)
        self.links_only = links_only      # Browser Bookmarks: refuse local files and folders
        self.setAcceptDrops(True)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.enter_pressed.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def _accepts(self, event) -> bool:
        if event.source() is self:
            node = self.currentItem()
            return node is not None and node.data(0, TYPE_ROLE) == ITEM
        if self.links_only:
            return dnd.can_accept_links(event.mimeData())
        return dnd.can_accept(event.mimeData())

    def dragEnterEvent(self, event) -> None:
        if self._accepts(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    dragMoveEvent = dragEnterEvent

    def _target_group(self, event) -> int | None:
        node = self.itemAt(event.position().toPoint())
        if node is None:
            return None
        if node.data(0, TYPE_ROLE) == GROUP:
            return node.data(0, ID_ROLE)
        parent = node.parent()
        return parent.data(0, ID_ROLE) if parent is not None else None

    def dropEvent(self, event) -> None:
        # Never call super(): Qt's own row re-ordering would desync the tree from the database.
        if not self._accepts(event):
            event.ignore()
            return
        target = self._target_group(event)
        # The work is deferred (QTimer 0) so the tree is not rebuilt while Qt is still inside the drag.
        if event.source() is self:
            node = self.currentItem()
            if target is not None:
                item_id = node.data(0, ID_ROLE)
                QTimer.singleShot(0, lambda: self.item_moved.emit(item_id, target))
        else:
            mime = event.mimeData()
            sources = dnd.links_from_mime(mime) if self.links_only else dnd.sources_from_mime(mime)
            QTimer.singleShot(0, lambda: self.sources_dropped.emit(sources, target))
        # CopyAction = "handled".  With MoveAction Qt would delete the dragged row (or the user's
        # original file) after the drop, which made moved entries vanish until the next refresh.
        if event.possibleActions() & Qt.DropAction.CopyAction:
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
        else:
            event.acceptProposedAction()


class SectionWidget(QWidget):
    def __init__(self, section: Section, repo: Repository, launcher: Launcher,
                 icons: IconProvider, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.section = Section(section)
        self.links_only = self.section is Section.BROWSER      # bookmarks: web links only
        # Entry types the Add menus may offer - driven by the same rule the repository enforces.
        self.addable_kinds = [k for k in (ItemKind.URL, ItemKind.FOLDER, ItemKind.FILE)
                              if k in ALLOWED_KINDS[self.section]]
        self.repo = repo
        self.launcher = launcher
        self.icons = icons
        self._text = _TEXT[self.section]
        self._collapsed: set[int] = set()
        self._nodes: dict[tuple[str, int], QTreeWidgetItem] = {}
        self._build_ui()
        self.refresh_tree()

    # ================================================================ UI
    def _build_ui(self) -> None:
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("🔍 Search name or location…")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(lambda _t="": self.refresh_tree())

        self.new_folder_btn = QPushButton("+ Folder")
        self.new_folder_btn.setToolTip("New top-level folder")
        self.new_folder_btn.clicked.connect(lambda _checked=False: self.add_group())

        self.new_subfolder_btn = QPushButton("+ Sub-folder")
        self.new_subfolder_btn.setToolTip("New folder inside the selected folder")
        self.new_subfolder_btn.clicked.connect(lambda _checked=False: self.add_subgroup())

        self.add_btn = QPushButton("+ Link" if self.links_only else "+ Add")
        self.add_btn.setObjectName("PrimaryButton")
        self.add_btn.setToolTip(self._text["add_tip"])
        if self.links_only:       # nothing to choose between: bookmarks are always web links
            self.add_btn.clicked.connect(lambda _checked=False: self.add_item(ItemKind.URL))
        else:
            self.add_btn.setMenu(self._build_add_menu(self.add_btn))

        self.import_btn = QPushButton("Import…")
        self.import_btn.setToolTip("Import bookmarks from a browser (bookmarks HTML file)")
        self.import_btn.clicked.connect(lambda _checked=False: self.import_bookmarks())
        self.export_btn = QPushButton("Export…")
        self.export_btn.setToolTip("Export all bookmarks as a file any browser can import")
        self.export_btn.clicked.connect(lambda _checked=False: self.export_bookmarks())
        if not self.links_only:      # only hide(): setVisible(True) on a parentless widget would pop it up as a window
            self.import_btn.hide()
            self.export_btn.hide()

        self.open_btn = QPushButton("▶ Open")
        self.open_btn.setObjectName("PinButton")
        self.open_btn.setToolTip(self._text["open_tip"])
        self.open_btn.clicked.connect(lambda _checked=False: self.open_selected())

        top = QHBoxLayout()
        top.addWidget(self.search_edit, 1)
        top.addWidget(self.open_btn)
        top.addWidget(self.new_folder_btn)
        top.addWidget(self.new_subfolder_btn)
        top.addWidget(self.add_btn)
        top.addWidget(self.import_btn)
        top.addWidget(self.export_btn)

        self.tree = DropTree(links_only=self.links_only)
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["Name", "Location", ""])
        self.tree.setIconSize(QSize(22, 22))
        self.tree.setUniformRowHeights(True)
        self.tree.setExpandsOnDoubleClick(False)   # double-click opens entries; folders toggle in open_selected()
        self.tree.setColumnWidth(0, 340)
        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._tree_menu)
        self.tree.itemDoubleClicked.connect(lambda *_: self.open_selected())
        self.tree.currentItemChanged.connect(lambda *_: self._update_buttons())
        self.tree.itemExpanded.connect(self._on_expanded)
        self.tree.itemCollapsed.connect(self._on_collapsed)
        self.tree.enter_pressed.connect(self.open_selected)
        self.tree.sources_dropped.connect(self._on_sources_dropped)
        self.tree.item_moved.connect(self._on_item_moved)

        self.hint_label = QLabel(self._text["hint"])
        self.hint_label.setObjectName("Hint")
        self.hint_label.setWordWrap(True)
        self.status_label = QLabel("")
        self.status_label.setObjectName("Status")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(8)
        layout.addLayout(top)
        layout.addWidget(self.tree, 1)
        layout.addWidget(self.hint_label)
        layout.addWidget(self.status_label)

    def _build_add_menu(self, owner: QWidget) -> QMenu:
        menu = QMenu(owner)
        for kind in self.addable_kinds:
            label = _ADD_LABELS[kind]
            action = QAction(self.icons.for_kind(kind), label, menu)
            action.triggered.connect(lambda _checked=False, k=kind: self.add_item(k))
            menu.addAction(action)
        return menu

    # ============================================================== tree
    def _on_expanded(self, node: QTreeWidgetItem) -> None:
        if node.data(0, TYPE_ROLE) == GROUP and not self._searching():
            self._collapsed.discard(node.data(0, ID_ROLE))

    def _on_collapsed(self, node: QTreeWidgetItem) -> None:
        if node.data(0, TYPE_ROLE) == GROUP and not self._searching():
            self._collapsed.add(node.data(0, ID_ROLE))

    def _searching(self) -> bool:
        return bool(self.search_edit.text().strip())

    @staticmethod
    def _matches(item: Item, needle: str) -> bool:
        return needle in item.name.lower() or needle in item.target.lower()

    def refresh_tree(self, select: tuple[str, int] | None = None) -> None:
        """Rebuild the tree from the database (optionally selecting ``(type, id)``)."""
        keep = select or self.current_key()
        groups = self.repo.list_groups(self.section)
        items = self.repo.list_section_items(self.section)
        needle = self.search_edit.text().strip().lower()

        children: dict[int | None, list[Group]] = {}
        for g in groups:
            children.setdefault(g.parent_id, []).append(g)
        entries: dict[int, list[Item]] = {}
        for it in items:
            entries.setdefault(it.group_id, []).append(it)

        self.tree.blockSignals(True)
        self.tree.clear()
        self._nodes = {}

        def build(group: Group, parent: QTreeWidgetItem | None, show_all: bool) -> bool:
            node = QTreeWidgetItem(parent) if parent is not None else QTreeWidgetItem(self.tree)
            node.setText(0, group.name)
            node.setIcon(0, self.icons.for_section_group(self.section))
            node.setData(0, ID_ROLE, group.id)
            node.setData(0, TYPE_ROLE, GROUP)
            self._nodes[(GROUP, group.id)] = node
            everything = show_all or not needle or needle in group.name.lower()
            visible = everything
            for child in children.get(group.id, []):
                visible |= build(child, node, everything)
            for it in entries.get(group.id, []):
                if everything or self._matches(it, needle):
                    self._add_item_node(node, it)
                    visible = True
            if not visible:
                (parent if parent is not None else self.tree.invisibleRootItem()).removeChild(node)
                self._nodes.pop((GROUP, group.id), None)
            return visible

        for root in children.get(None, []):
            build(root, None, False)

        for (kind, ident), node in self._nodes.items():
            if kind == GROUP:
                node.setExpanded(bool(needle) or ident not in self._collapsed)
        self.tree.blockSignals(False)

        target = self._nodes.get(keep) if keep else None
        if target is None and self.tree.topLevelItemCount():
            target = self.tree.topLevelItem(0)
        if target is not None:
            self.tree.setCurrentItem(target)
        self._update_buttons()
        n_groups = sum(1 for k in self._nodes if k[0] == GROUP)
        n_items = len(self._nodes) - n_groups
        self.status_label.setText(f"{n_groups} folder(s) · {n_items} entr{'y' if n_items == 1 else 'ies'}")

    def _add_item_node(self, parent: QTreeWidgetItem, item: Item) -> None:
        node = QTreeWidgetItem(parent)
        node.setText(0, ("★ " if item.is_pinned else "") + item.name)
        node.setText(1, item.target)
        node.setIcon(0, self.icons.for_kind(item.kind))
        node.setToolTip(0, item.target)
        node.setToolTip(1, item.target)
        node.setData(0, ID_ROLE, item.id)
        node.setData(0, TYPE_ROLE, ITEM)
        node.setFlags(node.flags() & ~Qt.ItemFlag.ItemIsDropEnabled)
        self._nodes[(ITEM, item.id)] = node

        open_btn = QPushButton("Open")
        open_btn.setObjectName("OpenButton")
        open_btn.setToolTip(f"Open {item.target}")
        open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        open_btn.clicked.connect(lambda _checked=False, i=item.id: self.open_item(i))
        self.tree.setItemWidget(node, 2, open_btn)

    def _update_buttons(self) -> None:
        has_group = self.current_group_id() is not None
        self.new_subfolder_btn.setEnabled(has_group)
        self.add_btn.setEnabled(has_group)
        self.open_btn.setEnabled(self.selected_item_id() is not None)

    # ---------------------------------------------------------- selection
    def current_key(self) -> tuple[str, int] | None:
        node = self.tree.currentItem()
        return (node.data(0, TYPE_ROLE), node.data(0, ID_ROLE)) if node else None

    def current_group_id(self) -> int | None:
        """The selected folder - or the folder holding the selected entry."""
        key = self.current_key()
        if key is None:
            return None
        if key[0] == GROUP:
            return key[1]
        return self.repo.get_item(key[1]).group_id

    def selected_item_id(self) -> int | None:
        key = self.current_key()
        return key[1] if key and key[0] == ITEM else None

    def select_group(self, group_id: int) -> None:
        node = self._nodes.get((GROUP, group_id))
        if node is not None:
            self.tree.setCurrentItem(node)

    # ============================================================ folders
    def add_group(self, name: str | None = None, parent_id: int | None = None) -> Group | None:
        """Create a folder (top level unless ``parent_id`` is given)."""
        if name is None:
            title = "New sub-folder" if parent_id is not None else "New folder"
            name = prompts.ask_text(self, title, "Folder name:")
            if name is None:
                return None
        try:
            group = self.repo.create_group(self.section, name, parent_id)
        except (ValidationError, DuplicateNameError) as exc:
            prompts.show_warning(self, str(exc))
            return None
        if parent_id is not None:
            self._collapsed.discard(parent_id)
        self.refresh_tree(select=(GROUP, group.id))
        return group

    def add_subgroup(self, name: str | None = None) -> Group | None:
        """Create a folder inside the selected folder."""
        parent_id = self.current_group_id()
        if parent_id is None:
            prompts.show_warning(self, "Select a folder first.")
            return None
        return self.add_group(name, parent_id)

    def rename_group(self, new_name: str | None = None) -> None:
        key = self.current_key()
        if key is None or key[0] != GROUP:
            return
        if new_name is None:
            new_name = prompts.ask_text(self, "Rename folder", "Folder name:", self.repo.get_group(key[1]).name)
            if new_name is None:
                return
        try:
            self.repo.rename_group(key[1], new_name)
        except (ValidationError, DuplicateNameError) as exc:
            prompts.show_warning(self, str(exc))
            return
        self.refresh_tree(select=key)

    def delete_group(self, confirmed: bool | None = None) -> None:
        key = self.current_key()
        if key is None or key[0] != GROUP:
            return
        if confirmed is None:
            confirmed = prompts.confirm(
                self, "Delete folder",
                f"Delete '{self.repo.get_group(key[1]).name}' with all its sub-folders and entries?\n"
                "This cannot be undone.")
        if confirmed:
            self.repo.delete_group(key[1])
            self.refresh_tree()

    def group_path(self, group_id: int) -> str:
        by_id = {g.id: g for g in self.repo.list_groups(self.section)}
        parts: list[str] = []
        current = by_id.get(group_id)
        while current is not None:
            parts.append(current.name)
            current = by_id.get(current.parent_id) if current.parent_id else None
        return " / ".join(reversed(parts))

    # =============================================================== items
    def add_item(self, kind: ItemKind | None = None,
                 values: tuple[ItemKind, str, str] | None = None) -> Item | None:
        """Add an entry to the selected folder (``values`` skips the dialog)."""
        gid = self.current_group_id()
        if gid is None:
            prompts.show_warning(self, "Create or select a folder first.")
            return None
        if values is None:
            dialog = ItemDialog(self, kind=kind or self._text["default_kind"], section=self.section)
            if not dialog.exec():
                return None
            values = dialog.values()
        k, name, target = values
        try:
            item = self.repo.add_item(gid, k, name, target)
        except ValidationError as exc:
            prompts.show_warning(self, str(exc))
            return None
        self._collapsed.discard(gid)
        self.refresh_tree(select=(ITEM, item.id))
        return item

    def add_sources(self, sources: list[str], group_id: int | None = None):
        """Add dropped files / folders / links (full path incl. file name) to a folder."""
        gid = group_id if group_id is not None else self.current_group_id()
        if gid is None:
            prompts.show_warning(self, "Create or select a folder first.")
            return None
        result = dropped.add_sources(self.repo, gid, sources)
        self._collapsed.discard(gid)
        self.refresh_tree(select=(ITEM, result.added[-1].id) if result.added else None)
        self.status_label.setText(f"{result.summary()} → {self.group_path(gid)}")
        if result.failed:
            prompts.show_warning(self, "Could not add:\n" + "\n".join(result.failed))
        return result

    # ===================================================== import / export
    def import_bookmarks(self, path: str | None = None, group_id: int | None = None):
        """Import a browser bookmarks file (HTML, Chrome/Edge ``Bookmarks`` or Firefox JSON).

        Folders are merged by name and duplicate links are skipped.  ``group_id`` imports
        inside that folder; ``None`` imports at the top level.
        """
        if not self.links_only:
            return None
        if path is None:
            path = prompts.ask_open_file(self, "Import bookmarks", IMPORT_FILTER)
            if not path:
                return None
        try:
            tree = bookmarks.read_bookmark_file(path)
            result = bookmarks.import_bookmarks(self.repo, tree, group_id)
        except (ValidationError, KeyError) as exc:
            prompts.show_warning(self, str(exc), "Import bookmarks")
            return None
        if group_id is not None:
            self._collapsed.discard(group_id)
        self.refresh_tree()
        self.status_label.setText(f"Imported: {result.summary()}")
        prompts.show_info(self, result.summary(), "Import finished")
        return result

    def export_bookmarks(self, path: str | None = None, group_id: int | None = None):
        """Export every bookmark (or one folder) as a bookmarks HTML file."""
        if not self.links_only:
            return None
        if path is None:
            stem = "pinner-bookmarks"
            if group_id is not None:
                stem = re.sub(r'[\\/:*?"<>|]+', "_", self.repo.get_group(group_id).name) or stem
            path = prompts.ask_save_file(self, "Export bookmarks", f"{stem}.html", EXPORT_FILTER)
            if not path:
                return None
            if not Path(path).suffix:
                path += ".html"
        try:
            result = bookmarks.export_to_file(self.repo, path, group_id)
        except (ValidationError, KeyError) as exc:
            prompts.show_warning(self, str(exc), "Export bookmarks")
            return None
        self.status_label.setText(f"{result.summary()} → {result.path}")
        prompts.show_info(self, f"{result.summary()}\n\n{result.path}\n\n"
                                "In your browser: Settings → Bookmarks → Import bookmarks → choose this file.",
                          "Export finished")
        return result

    def _on_sources_dropped(self, sources: list[str], group_id: int | None) -> None:
        self.add_sources(sources, group_id)

    def _on_item_moved(self, item_id: int, group_id: int) -> None:
        try:
            self.repo.move_item(item_id, group_id)
        except (ValidationError, KeyError) as exc:
            prompts.show_warning(self, str(exc))
            return
        self._collapsed.discard(group_id)
        self.refresh_tree(select=(ITEM, item_id))

    def edit_selected(self, values: tuple[ItemKind, str, str] | None = None) -> None:
        """Edit the selected entry (dialog) or rename the selected folder."""
        key = self.current_key()
        if key is None:
            return
        if key[0] == GROUP:
            self.rename_group()
            return
        item = self.repo.get_item(key[1])
        if values is None:
            dialog = ItemDialog(self, kind=item.kind, name=item.name, target=item.target, editing=True,
                                section=self.section)
            if not dialog.exec():
                return
            values = dialog.values()
        kind, name, target = values
        try:
            self.repo.update_item(item.id, kind=kind, name=name, target=target)
        except ValidationError as exc:
            prompts.show_warning(self, str(exc))
            return
        self.refresh_tree(select=key)

    def open_item(self, item_id: int) -> bool:
        """Open one entry: folder in the file manager, file/app with its default program, link in the browser."""
        try:
            item = self.repo.get_item(item_id)
        except KeyError:
            return False
        try:
            self.launcher.open_item(item)
        except LaunchError as exc:
            prompts.show_error(self, str(exc))
            return False
        self.status_label.setText(f"Opened {item.name}")
        return True

    def open_selected(self) -> None:
        """Open the selected entry (a selected folder just expands / collapses)."""
        key = self.current_key()
        if key is None:
            return
        if key[0] == GROUP:
            node = self.tree.currentItem()
            node.setExpanded(not node.isExpanded())
            return
        self.open_item(key[1])

    def reveal_selected(self) -> None:
        """Show the selected file/folder in the system file manager."""
        item_id = self.selected_item_id()
        if item_id is None:
            return
        item = self.repo.get_item(item_id)
        if item.kind is ItemKind.URL:
            return
        try:
            self.launcher.reveal(item.target)
        except LaunchError as exc:
            prompts.show_error(self, str(exc))

    def toggle_pin_selected(self) -> None:
        item_id = self.selected_item_id()
        if item_id is None:
            return
        item = self.repo.get_item(item_id)
        self.repo.set_pinned(item_id, not item.is_pinned)
        self.refresh_tree(select=(ITEM, item_id))

    def move_selected(self, group_id: int) -> None:
        item_id = self.selected_item_id()
        if item_id is not None:
            self._on_item_moved(item_id, group_id)

    def delete_selected(self, confirmed: bool | None = None) -> None:
        """Remove the selected entry, or delete the selected folder."""
        key = self.current_key()
        if key is None:
            return
        if key[0] == GROUP:
            self.delete_group(confirmed)
            return
        if confirmed is None:
            confirmed = prompts.confirm(self, "Remove entry", "Remove this entry from the list?")
        if confirmed:
            self.repo.delete_item(key[1])
            self.refresh_tree()

    def copy_selected(self) -> None:
        item_id = self.selected_item_id()
        if item_id is not None:
            QApplication.clipboard().setText(self.repo.get_item(item_id).target)
            self.status_label.setText("Copied to clipboard")

    # ========================================================= context menu
    def _tree_menu(self, pos) -> None:
        # NOTE: lambdas on purpose - Qt passes `checked` to bound methods that have
        # optional parameters, which would corrupt `values=` / `confirmed=`.
        node = self.tree.itemAt(pos)
        menu = QMenu(self)
        if node is None:
            menu.addAction("New folder", lambda: self.add_group())
            if self.links_only:
                menu.addSeparator()
                menu.addAction("Import bookmarks…", lambda: self.import_bookmarks())
                menu.addAction("Export bookmarks…", lambda: self.export_bookmarks())
        else:
            self.tree.setCurrentItem(node)
            if node.data(0, TYPE_ROLE) == GROUP:
                gid = node.data(0, ID_ROLE)
                menu.addAction("New sub-folder", lambda: self.add_subgroup())
                if self.links_only:
                    menu.addAction(self.icons.for_kind(ItemKind.URL), "Add link…",
                                   lambda: self.add_item(ItemKind.URL))
                    menu.addSeparator()
                    menu.addAction("Import bookmarks here…", lambda: self.import_bookmarks(group_id=gid))
                    menu.addAction("Export this folder…", lambda: self.export_bookmarks(group_id=gid))
                else:
                    add_menu = menu.addMenu("Add")
                    for kind in self.addable_kinds:
                        add_menu.addAction(self.icons.for_kind(kind), _ADD_LABELS[kind],
                                           lambda _checked=False, k=kind: self.add_item(k))
                menu.addSeparator()
                menu.addAction("Rename…", lambda: self.rename_group())
                menu.addAction("Delete folder…", lambda: self.delete_group())
            else:
                item = self.repo.get_item(node.data(0, ID_ROLE))
                menu.addAction(self.icons.for_kind(item.kind), "Open", lambda: self.open_selected())
                if item.kind is not ItemKind.URL:
                    menu.addAction("Show in folder", lambda: self.reveal_selected())
                menu.addAction("Edit…", lambda: self.edit_selected())
                menu.addAction("Unpin from top" if item.is_pinned else "Pin to top of folder",
                               lambda: self.toggle_pin_selected())
                menu.addAction("Copy link" if self.links_only else "Copy path / link",
                               lambda: self.copy_selected())
                move_menu = menu.addMenu("Move to")
                for group in self.repo.list_groups(self.section):
                    if group.id != item.group_id:
                        move_menu.addAction(self.group_path(group.id),
                                            lambda _checked=False, gid=group.id: self.move_selected(gid))
                move_menu.setEnabled(not move_menu.isEmpty())
                menu.addSeparator()
                menu.addAction("Remove…", lambda: self.delete_selected())
        menu.exec(self.tree.viewport().mapToGlobal(pos))

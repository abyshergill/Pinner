"""CRUD operations for folders (groups), items and settings."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Iterator

from .database import Database
from .models import (
    DuplicateNameError,
    Group,
    Item,
    ItemKind,
    Section,
    ValidationError,
    check_kind_allowed,
    clean_name,
    validate_entry,
)


def _group(row: sqlite3.Row) -> Group:
    return Group(row["id"], Section(row["section"]), row["name"], row["parent_id"])


def _item(row: sqlite3.Row) -> Item:
    return Item(
        row["id"],
        row["group_id"],
        ItemKind(row["kind"]),
        row["name"],
        row["target"],
        bool(row["is_pinned"]),
    )


class Repository:
    """All persistence goes through here; the UI never sees SQL."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self._in_batch = False

    # -------------------------------------------------------- transactions
    @contextmanager
    def _tx(self) -> Iterator[None]:
        """One write = one transaction (unless a :meth:`batch` is already open)."""
        if self._in_batch:
            yield
        else:
            with self.db.conn:
                yield

    @contextmanager
    def batch(self) -> Iterator[None]:
        """Group many writes into a single all-or-nothing transaction (fast bulk imports)."""
        if self._in_batch:
            yield
            return
        self._in_batch = True
        try:
            with self.db.conn:       # commit on success, roll back on any exception
                yield
        finally:
            self._in_batch = False

    # ------------------------------------------------------------- groups
    def create_group(self, section: Section, name: str, parent_id: int | None = None) -> Group:
        name = clean_name(name, "Folder name")
        if parent_id is not None:
            parent = self.get_group(parent_id)
            if parent.section != section:
                raise ValidationError("Parent folder belongs to a different section.")
        try:
            with self._tx():
                cur = self.db.conn.execute(
                    "INSERT INTO groups (section, name, parent_id) VALUES (?, ?, ?)",
                    (Section(section).value, name, parent_id),
                )
        except sqlite3.IntegrityError as exc:
            raise DuplicateNameError(f"A folder named '{name}' already exists here.") from exc
        return self.get_group(cur.lastrowid)

    def get_group(self, group_id: int) -> Group:
        row = self.db.conn.execute("SELECT * FROM groups WHERE id = ?", (group_id,)).fetchone()
        if row is None:
            raise KeyError(f"Folder {group_id} not found")
        return _group(row)

    def find_group(self, section: Section, name: str, parent_id: int | None = None) -> Group | None:
        """The sibling folder called ``name`` (case-insensitive), or ``None``."""
        row = self.db.conn.execute(
            "SELECT * FROM groups WHERE section = ? AND IFNULL(parent_id, 0) = ? "
            "AND name = ? COLLATE NOCASE",
            (Section(section).value, parent_id or 0, (name or "").strip()),
        ).fetchone()
        return _group(row) if row else None

    def list_groups(self, section: Section) -> list[Group]:
        rows = self.db.conn.execute(
            "SELECT * FROM groups WHERE section = ? ORDER BY name COLLATE NOCASE",
            (Section(section).value,),
        ).fetchall()
        return [_group(r) for r in rows]

    def rename_group(self, group_id: int, name: str) -> Group:
        name = clean_name(name, "Folder name")
        self.get_group(group_id)
        try:
            with self._tx():
                self.db.conn.execute("UPDATE groups SET name = ? WHERE id = ?", (name, group_id))
        except sqlite3.IntegrityError as exc:
            raise DuplicateNameError(f"A folder named '{name}' already exists here.") from exc
        return self.get_group(group_id)

    def delete_group(self, group_id: int) -> None:
        """Delete a folder together with its sub-folders and items."""
        with self._tx():
            self.db.conn.execute("DELETE FROM groups WHERE id = ?", (group_id,))

    # -------------------------------------------------------------- items
    def add_item(self, group_id: int, kind: ItemKind, name: str, target: str,
                 is_pinned: bool = False) -> Item:
        """Add an entry.  Browser Bookmark folders accept web links only."""
        section = self.get_group(group_id).section
        kind, name, target = validate_entry(section, kind, name, target)
        with self._tx():
            cur = self.db.conn.execute(
                "INSERT INTO items (group_id, kind, name, target, is_pinned) VALUES (?,?,?,?,?)",
                (group_id, kind.value, name, target, int(is_pinned)),
            )
        return self.get_item(cur.lastrowid)

    def get_item(self, item_id: int) -> Item:
        row = self.db.conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        if row is None:
            raise KeyError(f"Item {item_id} not found")
        return _item(row)

    def list_items(self, group_id: int) -> list[Item]:
        """Pinned items first, then alphabetical."""
        rows = self.db.conn.execute(
            "SELECT * FROM items WHERE group_id = ? "
            "ORDER BY is_pinned DESC, name COLLATE NOCASE, id",
            (group_id,),
        ).fetchall()
        return [_item(r) for r in rows]

    def list_section_items(self, section: Section) -> list[Item]:
        """Every item in a section (pinned first, then by name)."""
        rows = self.db.conn.execute(
            "SELECT i.* FROM items i JOIN groups g ON g.id = i.group_id WHERE g.section = ? "
            "ORDER BY i.is_pinned DESC, i.name COLLATE NOCASE, i.id",
            (Section(section).value,),
        ).fetchall()
        return [_item(r) for r in rows]

    def search_items(self, section: Section, text: str) -> list[Item]:
        """Search names and targets of every item in a section."""
        escaped = text.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        like = f"%{escaped}%"
        rows = self.db.conn.execute(
            "SELECT i.* FROM items i JOIN groups g ON g.id = i.group_id "
            "WHERE g.section = ? AND (i.name LIKE ? ESCAPE '\\' OR i.target LIKE ? ESCAPE '\\') "
            "ORDER BY i.is_pinned DESC, i.name COLLATE NOCASE, i.id",
            (Section(section).value, like, like),
        ).fetchall()
        return [_item(r) for r in rows]

    def update_item(self, item_id: int, *, name: str | None = None, target: str | None = None,
                    kind: ItemKind | None = None) -> Item:
        """Change the display name (alias), target and/or kind of an item."""
        current = self.get_item(item_id)
        section = self.get_group(current.group_id).section
        new_kind = ItemKind(kind) if kind is not None else current.kind
        new_kind, new_name, new_target = validate_entry(
            section,
            new_kind,
            name if name is not None else current.name,
            target if target is not None else current.target,
        )
        with self._tx():
            self.db.conn.execute(
                "UPDATE items SET kind = ?, name = ?, target = ? WHERE id = ?",
                (new_kind.value, new_name, new_target, item_id),
            )
        return self.get_item(item_id)

    def set_pinned(self, item_id: int, pinned: bool) -> Item:
        self.get_item(item_id)
        with self._tx():
            self.db.conn.execute("UPDATE items SET is_pinned = ? WHERE id = ?", (int(pinned), item_id))
        return self.get_item(item_id)

    def move_item(self, item_id: int, group_id: int) -> Item:
        item = self.get_item(item_id)
        target_section = self.get_group(group_id).section
        if target_section != self.get_group(item.group_id).section:
            raise ValidationError("Items can only be moved within the same section.")
        check_kind_allowed(target_section, item.kind)
        with self._tx():
            self.db.conn.execute("UPDATE items SET group_id = ? WHERE id = ?", (group_id, item_id))
        return self.get_item(item_id)

    def delete_item(self, item_id: int) -> None:
        with self._tx():
            self.db.conn.execute("DELETE FROM items WHERE id = ?", (item_id,))

    # ----------------------------------------------------------- settings
    def get_setting(self, key: str, default: str | None = None) -> str | None:
        row = self.db.conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self._tx():
            self.db.conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    def get_bool(self, key: str, default: bool = False) -> bool:
        value = self.get_setting(key)
        return default if value is None else value == "1"

    def set_bool(self, key: str, value: bool) -> None:
        self.set_setting(key, "1" if value else "0")

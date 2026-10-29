"""SQLite connection management and schema."""
from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 2

_SCHEMA = """
CREATE TABLE IF NOT EXISTS groups (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    section     TEXT    NOT NULL CHECK (section IN ('paths', 'browser')),
    name        TEXT    NOT NULL,
    parent_id   INTEGER REFERENCES groups(id) ON DELETE CASCADE,
    created_at  TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Sibling folders must have unique names (case-insensitive).
CREATE UNIQUE INDEX IF NOT EXISTS ux_groups_sibling_name
    ON groups (section, IFNULL(parent_id, 0), name COLLATE NOCASE);

CREATE TABLE IF NOT EXISTS items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id    INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    kind        TEXT    NOT NULL CHECK (kind IN ('folder', 'file', 'url')),
    name        TEXT    NOT NULL,
    target      TEXT    NOT NULL,
    is_pinned   INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_items_group ON items (group_id);

-- Safety net: Browser Bookmarks hold web links only, whatever code writes to the database.
CREATE TRIGGER IF NOT EXISTS trg_bookmarks_links_only_insert
BEFORE INSERT ON items
WHEN NEW.kind <> 'url'
     AND (SELECT section FROM groups WHERE id = NEW.group_id) = 'browser'
BEGIN
    SELECT RAISE(ABORT, 'Browser Bookmarks accept web links only');
END;

CREATE TRIGGER IF NOT EXISTS trg_bookmarks_links_only_update
BEFORE UPDATE OF kind, group_id ON items
WHEN NEW.kind <> 'url'
     AND (SELECT section FROM groups WHERE id = NEW.group_id) = 'browser'
BEGIN
    SELECT RAISE(ABORT, 'Browser Bookmarks accept web links only');
END;

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class Database:
    """Thin wrapper owning one SQLite connection.

    ``path=":memory:"`` is supported (used heavily by the tests).
    """

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._init_schema()

    def _init_schema(self) -> None:
        with self.conn:
            self.conn.executescript(_SCHEMA)
            self.conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

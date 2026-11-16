//! SQLite connection management and schema.

use std::path::Path;

use rusqlite::Connection;

use crate::config::expand_user;
use crate::models::Result;

pub const SCHEMA_VERSION: i64 = 2;

const SCHEMA: &str = "
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
";

/// Thin wrapper owning one SQLite connection.
pub struct Database {
    pub conn: Connection,
}

impl Database {
    pub fn open(path: impl AsRef<Path>) -> Result<Self> {
        let raw = path.as_ref().to_string_lossy().to_string();
        let path = expand_user(&raw);
        if let Some(parent) = path.parent().filter(|p| !p.as_os_str().is_empty()) {
            std::fs::create_dir_all(parent)
                .map_err(|e| crate::models::Error::Database(format!("Cannot create {}: {e}", parent.display())))?;
        }
        Self::init(Connection::open(path)?)
    }

    pub fn in_memory() -> Result<Self> {
        Self::init(Connection::open_in_memory()?)
    }

    fn init(conn: Connection) -> Result<Self> {
        conn.execute_batch("PRAGMA foreign_keys = ON")?;
        conn.execute_batch(SCHEMA)?;
        conn.execute_batch(&format!("PRAGMA user_version = {SCHEMA_VERSION}"))?;
        Ok(Self { conn })
    }
}

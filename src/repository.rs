//! CRUD operations for folders (groups), items and settings.

use std::cell::Cell;

use rusqlite::{params, OptionalExtension, Row};

use crate::database::Database;
use crate::models::{
    check_kind_allowed, clean_name, validate_entry, validation, Error, Group, Item, ItemKind, Result, Section,
};

fn group_from(row: &Row) -> rusqlite::Result<Group> {
    let section: String = row.get("section")?;
    Ok(Group {
        id: row.get("id")?,
        section: Section::parse(&section).unwrap_or(Section::Paths),
        name: row.get("name")?,
        parent_id: row.get("parent_id")?,
    })
}

fn item_from(row: &Row) -> rusqlite::Result<Item> {
    let kind: String = row.get("kind")?;
    Ok(Item {
        id: row.get("id")?,
        group_id: row.get("group_id")?,
        kind: ItemKind::parse(&kind).unwrap_or(ItemKind::File),
        name: row.get("name")?,
        target: row.get("target")?,
        is_pinned: row.get::<_, i64>("is_pinned")? != 0,
    })
}

fn is_constraint(e: &rusqlite::Error) -> bool {
    matches!(e, rusqlite::Error::SqliteFailure(f, _) if f.code == rusqlite::ErrorCode::ConstraintViolation)
}

/// All persistence goes through here; the UI never sees SQL.
pub struct Repository {
    pub db: Database,
    in_batch: Cell<bool>,
}

impl Repository {
    pub fn new(db: Database) -> Self {
        Self { db, in_batch: Cell::new(false) }
    }

    pub fn in_memory() -> Result<Self> {
        Ok(Self::new(Database::in_memory()?))
    }

    /// Group many writes into a single all-or-nothing transaction (fast bulk imports).
    pub fn batch<T>(&self, f: impl FnOnce() -> Result<T>) -> Result<T> {
        if self.in_batch.get() {
            return f();
        }
        self.db.conn.execute_batch("BEGIN")?;
        self.in_batch.set(true);
        let result = f();
        self.in_batch.set(false);
        match result {
            Ok(v) => {
                self.db.conn.execute_batch("COMMIT")?;
                Ok(v)
            }
            Err(e) => {
                let _ = self.db.conn.execute_batch("ROLLBACK");
                Err(e)
            }
        }
    }

    // ------------------------------------------------------------- groups
    pub fn create_group(&self, section: Section, name: &str, parent_id: Option<i64>) -> Result<Group> {
        let name = clean_name(name, "Folder name")?;
        if let Some(pid) = parent_id {
            if self.get_group(pid)?.section != section {
                return validation("Parent folder belongs to a different section.");
            }
        }
        let res = self.db.conn.execute(
            "INSERT INTO groups (section, name, parent_id) VALUES (?, ?, ?)",
            params![section.as_str(), name, parent_id],
        );
        match res {
            Ok(_) => self.get_group(self.db.conn.last_insert_rowid()),
            Err(e) if is_constraint(&e) => {
                Err(Error::DuplicateName(format!("A folder named '{name}' already exists here.")))
            }
            Err(e) => Err(e.into()),
        }
    }

    pub fn get_group(&self, id: i64) -> Result<Group> {
        self.db
            .conn
            .query_row("SELECT * FROM groups WHERE id = ?", [id], group_from)
            .optional()?
            .ok_or_else(|| Error::NotFound(format!("Folder {id} not found")))
    }

    /// The sibling folder called `name` (case-insensitive).
    pub fn find_group(&self, section: Section, name: &str, parent_id: Option<i64>) -> Result<Option<Group>> {
        Ok(self
            .db
            .conn
            .query_row(
                "SELECT * FROM groups WHERE section = ? AND IFNULL(parent_id, 0) = ? AND name = ? COLLATE NOCASE",
                params![section.as_str(), parent_id.unwrap_or(0), name.trim()],
                group_from,
            )
            .optional()?)
    }

    pub fn list_groups(&self, section: Section) -> Result<Vec<Group>> {
        let mut stmt = self
            .db
            .conn
            .prepare("SELECT * FROM groups WHERE section = ? ORDER BY name COLLATE NOCASE, id")?;
        let rows = stmt.query_map([section.as_str()], group_from)?;
        Ok(rows.collect::<rusqlite::Result<_>>()?)
    }

    pub fn rename_group(&self, id: i64, name: &str) -> Result<Group> {
        let name = clean_name(name, "Folder name")?;
        self.get_group(id)?;
        match self.db.conn.execute("UPDATE groups SET name = ? WHERE id = ?", params![name, id]) {
            Ok(_) => self.get_group(id),
            Err(e) if is_constraint(&e) => {
                Err(Error::DuplicateName(format!("A folder named '{name}' already exists here.")))
            }
            Err(e) => Err(e.into()),
        }
    }

    /// Delete a folder together with its sub-folders and items.
    pub fn delete_group(&self, id: i64) -> Result<()> {
        self.db.conn.execute("DELETE FROM groups WHERE id = ?", [id])?;
        Ok(())
    }

    // -------------------------------------------------------------- items
    /// Add an entry. Browser Bookmark folders accept web links only.
    pub fn add_item(&self, group_id: i64, kind: ItemKind, name: &str, target: &str, pinned: bool) -> Result<Item> {
        let section = self.get_group(group_id)?.section;
        let (kind, name, target) = validate_entry(section, kind, name, target)?;
        self.db.conn.execute(
            "INSERT INTO items (group_id, kind, name, target, is_pinned) VALUES (?,?,?,?,?)",
            params![group_id, kind.as_str(), name, target, pinned as i64],
        )?;
        self.get_item(self.db.conn.last_insert_rowid())
    }

    pub fn get_item(&self, id: i64) -> Result<Item> {
        self.db
            .conn
            .query_row("SELECT * FROM items WHERE id = ?", [id], item_from)
            .optional()?
            .ok_or_else(|| Error::NotFound(format!("Item {id} not found")))
    }

    /// Pinned items first, then alphabetical.
    pub fn list_items(&self, group_id: i64) -> Result<Vec<Item>> {
        let mut stmt = self.db.conn.prepare(
            "SELECT * FROM items WHERE group_id = ? ORDER BY is_pinned DESC, name COLLATE NOCASE, id",
        )?;
        let rows = stmt.query_map([group_id], item_from)?;
        Ok(rows.collect::<rusqlite::Result<_>>()?)
    }

    /// Every item in a section (pinned first, then by name).
    pub fn list_section_items(&self, section: Section) -> Result<Vec<Item>> {
        let mut stmt = self.db.conn.prepare(
            "SELECT i.* FROM items i JOIN groups g ON g.id = i.group_id WHERE g.section = ? \
             ORDER BY i.is_pinned DESC, i.name COLLATE NOCASE, i.id",
        )?;
        let rows = stmt.query_map([section.as_str()], item_from)?;
        Ok(rows.collect::<rusqlite::Result<_>>()?)
    }

    /// Search names and targets of every item in a section.
    pub fn search_items(&self, section: Section, text: &str) -> Result<Vec<Item>> {
        let escaped = text.trim().replace('\\', "\\\\").replace('%', "\\%").replace('_', "\\_");
        let like = format!("%{escaped}%");
        let mut stmt = self.db.conn.prepare(
            "SELECT i.* FROM items i JOIN groups g ON g.id = i.group_id \
             WHERE g.section = ? AND (i.name LIKE ? ESCAPE '\\' OR i.target LIKE ? ESCAPE '\\') \
             ORDER BY i.is_pinned DESC, i.name COLLATE NOCASE, i.id",
        )?;
        let rows = stmt.query_map(params![section.as_str(), like, like], item_from)?;
        Ok(rows.collect::<rusqlite::Result<_>>()?)
    }

    /// Change the display name (alias), target and/or kind of an item.
    pub fn update_item(
        &self,
        id: i64,
        name: Option<&str>,
        target: Option<&str>,
        kind: Option<ItemKind>,
    ) -> Result<Item> {
        let current = self.get_item(id)?;
        let section = self.get_group(current.group_id)?.section;
        let (kind, name, target) = validate_entry(
            section,
            kind.unwrap_or(current.kind),
            name.unwrap_or(&current.name),
            target.unwrap_or(&current.target),
        )?;
        self.db.conn.execute(
            "UPDATE items SET kind = ?, name = ?, target = ? WHERE id = ?",
            params![kind.as_str(), name, target, id],
        )?;
        self.get_item(id)
    }

    pub fn set_pinned(&self, id: i64, pinned: bool) -> Result<Item> {
        self.get_item(id)?;
        self.db.conn.execute("UPDATE items SET is_pinned = ? WHERE id = ?", params![pinned as i64, id])?;
        self.get_item(id)
    }

    pub fn move_item(&self, id: i64, group_id: i64) -> Result<Item> {
        let item = self.get_item(id)?;
        let target_section = self.get_group(group_id)?.section;
        if target_section != self.get_group(item.group_id)?.section {
            return validation("Items can only be moved within the same section.");
        }
        check_kind_allowed(target_section, item.kind)?;
        self.db.conn.execute("UPDATE items SET group_id = ? WHERE id = ?", params![group_id, id])?;
        self.get_item(id)
    }

    pub fn delete_item(&self, id: i64) -> Result<()> {
        self.db.conn.execute("DELETE FROM items WHERE id = ?", [id])?;
        Ok(())
    }

    // ----------------------------------------------------------- settings
    pub fn get_setting(&self, key: &str) -> Result<Option<String>> {
        Ok(self
            .db
            .conn
            .query_row("SELECT value FROM settings WHERE key = ?", [key], |r| r.get(0))
            .optional()?)
    }

    pub fn set_setting(&self, key: &str, value: &str) -> Result<()> {
        self.db.conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) \
             ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            params![key, value],
        )?;
        Ok(())
    }

    pub fn get_bool(&self, key: &str, default: bool) -> bool {
        match self.get_setting(key) {
            Ok(Some(v)) => v == "1",
            _ => default,
        }
    }

    pub fn set_bool(&self, key: &str, value: bool) -> Result<()> {
        self.set_setting(key, if value { "1" } else { "0" })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn repo() -> Repository {
        Repository::in_memory().unwrap()
    }

    #[test]
    fn groups_crud_and_nesting() {
        let r = repo();
        let a = r.create_group(Section::Paths, " Customers ", None).unwrap();
        assert_eq!(a.name, "Customers");
        let b = r.create_group(Section::Paths, "Acme", Some(a.id)).unwrap();
        assert_eq!(b.parent_id, Some(a.id));
        assert!(r.create_group(Section::Browser, "x", Some(a.id)).is_err());
        assert_eq!(r.rename_group(b.id, "Acme Inc").unwrap().name, "Acme Inc");
        r.delete_group(a.id).unwrap();
        assert!(r.get_group(b.id).is_err());
    }

    #[test]
    fn sibling_names_are_unique_case_insensitive() {
        let r = repo();
        r.create_group(Section::Paths, "Work", None).unwrap();
        assert!(matches!(r.create_group(Section::Paths, "work", None), Err(Error::DuplicateName(_))));
        // same name in a different parent / section is fine
        let p = r.create_group(Section::Paths, "P", None).unwrap();
        r.create_group(Section::Paths, "Work", Some(p.id)).unwrap();
        r.create_group(Section::Browser, "Work", None).unwrap();
        let other = r.create_group(Section::Paths, "Other", None).unwrap();
        assert!(matches!(r.rename_group(other.id, "WORK"), Err(Error::DuplicateName(_))));
    }

    #[test]
    fn items_sorted_pinned_first() {
        let r = repo();
        let g = r.create_group(Section::Paths, "G", None).unwrap();
        r.add_item(g.id, ItemKind::File, "beta", "/b", false).unwrap();
        r.add_item(g.id, ItemKind::File, "Alpha", "/a", false).unwrap();
        let z = r.add_item(g.id, ItemKind::Folder, "zed", "/z", false).unwrap();
        r.set_pinned(z.id, true).unwrap();
        let names: Vec<_> = r.list_items(g.id).unwrap().into_iter().map(|i| i.name).collect();
        assert_eq!(names, ["zed", "Alpha", "beta"]);
    }

    #[test]
    fn bookmarks_reject_non_links_everywhere() {
        let r = repo();
        let g = r.create_group(Section::Browser, "B", None).unwrap();
        assert!(r.add_item(g.id, ItemKind::File, "f", "/x", false).is_err());
        assert!(r.add_item(g.id, ItemKind::Url, "l", "/usr/x", false).is_err());
        let it = r.add_item(g.id, ItemKind::Url, "l", "example.com", false).unwrap();
        assert_eq!(it.target, "https://example.com");
        assert!(r.update_item(it.id, None, None, Some(ItemKind::File)).is_err());
        // database trigger is the last line of defence
        let raw = r.db.conn.execute(
            "INSERT INTO items (group_id, kind, name, target) VALUES (?, 'file', 'x', '/x')",
            [g.id],
        );
        assert!(raw.is_err());
    }

    #[test]
    fn move_stays_within_section() {
        let r = repo();
        let a = r.create_group(Section::Paths, "A", None).unwrap();
        let b = r.create_group(Section::Paths, "B", None).unwrap();
        let w = r.create_group(Section::Browser, "W", None).unwrap();
        let it = r.add_item(a.id, ItemKind::File, "f", "/f", false).unwrap();
        assert_eq!(r.move_item(it.id, b.id).unwrap().group_id, b.id);
        assert!(r.move_item(it.id, w.id).is_err());
    }

    #[test]
    fn search_matches_name_and_target_and_escapes() {
        let r = repo();
        let g = r.create_group(Section::Paths, "G", None).unwrap();
        r.add_item(g.id, ItemKind::File, "Report", "/docs/q1.txt", false).unwrap();
        r.add_item(g.id, ItemKind::File, "100%_done", "/x", false).unwrap();
        assert_eq!(r.search_items(Section::Paths, "report").unwrap().len(), 1);
        assert_eq!(r.search_items(Section::Paths, "q1").unwrap().len(), 1);
        assert_eq!(r.search_items(Section::Paths, "%_").unwrap().len(), 1);
        assert_eq!(r.search_items(Section::Paths, "%").unwrap().len(), 1);
    }

    #[test]
    fn update_and_delete_item() {
        let r = repo();
        let g = r.create_group(Section::Paths, "G", None).unwrap();
        let it = r.add_item(g.id, ItemKind::File, "n", "/n", false).unwrap();
        let up = r.update_item(it.id, Some("New"), Some("/new"), None).unwrap();
        assert_eq!((up.name.as_str(), up.target.as_str()), ("New", "/new"));
        assert!(r.update_item(it.id, Some(" "), None, None).is_err());
        r.delete_item(it.id).unwrap();
        assert!(r.get_item(it.id).is_err());
    }

    #[test]
    fn settings_roundtrip() {
        let r = repo();
        assert_eq!(r.get_setting("k").unwrap(), None);
        assert!(r.get_bool("b", true));
        r.set_bool("b", false).unwrap();
        assert!(!r.get_bool("b", true));
        r.set_setting("k", "v1").unwrap();
        r.set_setting("k", "v2").unwrap();
        assert_eq!(r.get_setting("k").unwrap().as_deref(), Some("v2"));
    }

    #[test]
    fn batch_rolls_back_on_error() {
        let r = repo();
        let res: Result<()> = r.batch(|| {
            r.create_group(Section::Paths, "A", None)?;
            r.create_group(Section::Paths, "A", None)?;
            Ok(())
        });
        assert!(res.is_err());
        assert!(r.list_groups(Section::Paths).unwrap().is_empty());
        r.batch(|| r.create_group(Section::Paths, "A", None).map(|_| ())).unwrap();
        assert_eq!(r.list_groups(Section::Paths).unwrap().len(), 1);
    }
}

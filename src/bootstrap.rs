//! Wires the database together and seeds first-run data.

use std::path::Path;

use crate::config::default_db_path;
use crate::database::Database;
use crate::models::{Result, Section};
use crate::repository::Repository;

pub const DEFAULT_FOLDERS: [(Section, &str); 2] =
    [(Section::Paths, "General"), (Section::Browser, "Bookmarks")];

/// Make sure each section has at least one folder to add things to.
pub fn ensure_default_folders(repo: &Repository) -> Result<()> {
    for (section, name) in DEFAULT_FOLDERS {
        if repo.list_groups(section)?.is_empty() {
            repo.create_group(section, name, None)?;
        }
    }
    Ok(())
}

/// Open (and initialise) the database and seed the default folders.
pub fn open_repository(db_path: Option<&Path>) -> Result<Repository> {
    let path = db_path.map(Path::to_path_buf).unwrap_or_else(default_db_path);
    let repo = Repository::new(Database::open(path)?);
    ensure_default_folders(&repo)?;
    Ok(repo)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn seeds_defaults_once() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("sub").join("p.db");
        let repo = open_repository(Some(&path)).unwrap();
        assert_eq!(repo.list_groups(Section::Paths).unwrap()[0].name, "General");
        assert_eq!(repo.list_groups(Section::Browser).unwrap()[0].name, "Bookmarks");
        drop(repo);
        let repo = open_repository(Some(&path)).unwrap();
        assert_eq!(repo.list_groups(Section::Paths).unwrap().len(), 1);
    }
}

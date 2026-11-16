//! Turn dropped files / folders / links into entries (GUI-free, testable).

use std::collections::HashSet;
use std::path::{Component, Path, PathBuf};

use crate::config::expand_user;
use crate::models::{
    has_web_scheme, normalize_url, validation, Item, ItemKind, Result, Section, BROWSER_LINKS_ONLY,
};
use crate::repository::Repository;

fn percent_decode(s: &str) -> String {
    let b = s.as_bytes();
    let mut out = Vec::with_capacity(b.len());
    let mut i = 0;
    while i < b.len() {
        if b[i] == b'%' && i + 2 < b.len() {
            let hex = |c: u8| (c as char).to_digit(16);
            if let (Some(h), Some(l)) = (hex(b[i + 1]), hex(b[i + 2])) {
                out.push((h * 16 + l) as u8);
                i += 3;
                continue;
            }
        }
        out.push(b[i]);
        i += 1;
    }
    String::from_utf8_lossy(&out).into_owned()
}

fn file_url_to_path(source: &str) -> String {
    let rest = &source[7..]; // after "file://"
    let (host, path) = match rest.find('/') {
        Some(i) => (&rest[..i], &rest[i..]),
        None => (rest, ""),
    };
    let mut path = percent_decode(path);
    // file:///C:/x  ->  C:/x
    let b = path.as_bytes();
    if b.len() >= 3 && b[0] == b'/' && b[1].is_ascii_alphabetic() && b[2] == b':' {
        path.remove(0);
    }
    if !host.is_empty() && host != "localhost" {
        return format!("//{host}{path}"); // UNC share
    }
    path
}

/// Collapse `.` and `..` lexically (like Python's `os.path.normpath`).
fn normalize_path(p: &Path) -> PathBuf {
    let mut out = PathBuf::new();
    for c in p.components() {
        match c {
            Component::CurDir => {}
            Component::ParentDir => {
                if !out.pop() {
                    out.push("..");
                }
            }
            other => out.push(other.as_os_str()),
        }
    }
    if out.as_os_str().is_empty() {
        PathBuf::from(".")
    } else {
        out
    }
}

/// Classify a dropped path or link as `(kind, display_name, target)`.
///
/// * `http(s)://`, `ftp://`, `mailto:` -> web link (name = host)
/// * existing directory -> folder; existing file -> file / app
/// * the target keeps the **full path including the file name**.
pub fn entry_from_source(source: &str) -> Result<(ItemKind, String, String)> {
    let source = source.trim().trim_matches('"');
    if source.is_empty() {
        return validation("Nothing to add.");
    }
    if has_web_scheme(source) {
        let url = normalize_url(source)?;
        let name = match url.split_once("://") {
            Some((_, rest)) => rest.split('/').next().unwrap_or("").to_string(),
            None => url.clone(),
        };
        let name = if name.is_empty() { url.clone() } else { name };
        return Ok((ItemKind::Url, name, url));
    }

    let mut raw = source.to_string();
    if raw.to_lowercase().starts_with("file://") {
        raw = file_url_to_path(&raw);
    }
    let path = normalize_path(&expand_user(&raw));
    let kind = if path.is_dir() {
        ItemKind::Folder
    } else if path.exists() {
        ItemKind::File
    } else {
        return validation(format!("Not found: {source}"));
    };
    let name = path
        .file_name()
        .map(|n| n.to_string_lossy().into_owned())
        .unwrap_or_else(|| path.display().to_string()); // drive / filesystem roots have no file name
    Ok((kind, name, path.display().to_string()))
}

#[derive(Debug, Default)]
pub struct DropResult {
    pub added: Vec<Item>,
    /// Already in the folder.
    pub skipped: usize,
    pub failed: Vec<String>,
}

impl DropResult {
    pub fn summary(&self) -> String {
        let mut parts = vec![format!("Added {}", self.added.len())];
        if self.skipped > 0 {
            parts.push(format!("{} already there", self.skipped));
        }
        if !self.failed.is_empty() {
            parts.push(format!("{} failed", self.failed.len()));
        }
        parts.join(", ")
    }
}

/// Add every dropped source to `group_id` (duplicates are skipped).
///
/// In a Browser Bookmarks folder only web links are accepted: dropped files and
/// folders are reported in `failed` and never stored.
pub fn add_sources(repo: &Repository, group_id: i64, sources: &[String]) -> Result<DropResult> {
    let mut result = DropResult::default();
    let links_only = repo.get_group(group_id)?.section == Section::Browser;
    let mut existing: HashSet<String> =
        repo.list_items(group_id)?.into_iter().map(|i| i.target.to_lowercase()).collect();
    for source in sources {
        let (kind, name, target) = match entry_from_source(source) {
            Ok(e) if links_only && e.0 != ItemKind::Url => {
                result.failed.push(format!("{BROWSER_LINKS_ONLY}\n  ({source})"));
                continue;
            }
            Ok(e) => e,
            Err(e) => {
                result.failed.push(e.to_string());
                continue;
            }
        };
        if existing.contains(&target.to_lowercase()) {
            result.skipped += 1;
            continue;
        }
        match repo.add_item(group_id, kind, &name, &target, false) {
            Ok(item) => {
                existing.insert(target.to_lowercase());
                result.added.push(item);
            }
            Err(e) => result.failed.push(format!("{source}: {e}")),
        }
    }
    Ok(result)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn classifies_links_folders_files() {
        let dir = tempfile::tempdir().unwrap();
        let f = dir.path().join("a.txt");
        std::fs::write(&f, "x").unwrap();

        let (k, n, t) = entry_from_source("https://example.com/page").unwrap();
        assert_eq!((k, n.as_str(), t.as_str()), (ItemKind::Url, "example.com", "https://example.com/page"));

        let (k, n, t) = entry_from_source(&format!("\"{}\"", f.display())).unwrap();
        assert_eq!((k, n.as_str()), (ItemKind::File, "a.txt"));
        assert_eq!(t, f.display().to_string());

        let (k, n, _) = entry_from_source(dir.path().to_str().unwrap()).unwrap();
        assert_eq!(k, ItemKind::Folder);
        assert_eq!(n, dir.path().file_name().unwrap().to_string_lossy());
    }

    #[test]
    fn file_urls_are_decoded() {
        let dir = tempfile::tempdir().unwrap();
        let f = dir.path().join("my file.txt");
        std::fs::write(&f, "x").unwrap();
        let url = format!("file://{}", f.display().to_string().replace(' ', "%20"));
        let (k, n, t) = entry_from_source(&url).unwrap();
        assert_eq!((k, n.as_str()), (ItemKind::File, "my file.txt"));
        assert_eq!(t, f.display().to_string());
    }

    #[test]
    fn file_url_forms() {
        assert_eq!(file_url_to_path("file:///C:/a%20b"), "C:/a b");
        assert_eq!(file_url_to_path("file://srv/share/x"), "//srv/share/x");
        assert_eq!(file_url_to_path("file://localhost/tmp/x"), "/tmp/x");
    }

    #[test]
    fn rejects_empty_and_missing() {
        assert!(entry_from_source("  ").is_err());
        assert!(entry_from_source("/no/such/thing/xyz").is_err());
    }

    #[test]
    fn add_sources_skips_duplicates_and_reports_failures() {
        let repo = Repository::in_memory().unwrap();
        let g = repo.create_group(Section::Paths, "G", None).unwrap();
        let dir = tempfile::tempdir().unwrap();
        let src = vec![
            dir.path().display().to_string(),
            dir.path().display().to_string(),
            "https://a.org".to_string(),
            "/nope/nope".to_string(),
        ];
        let r = add_sources(&repo, g.id, &src).unwrap();
        assert_eq!((r.added.len(), r.skipped, r.failed.len()), (2, 1, 1));
        assert_eq!(r.summary(), "Added 2, 1 already there, 1 failed");
    }

    #[test]
    fn bookmarks_only_take_links() {
        let repo = Repository::in_memory().unwrap();
        let g = repo.create_group(Section::Browser, "B", None).unwrap();
        let dir = tempfile::tempdir().unwrap();
        let r = add_sources(&repo, g.id, &[dir.path().display().to_string(), "https://a.org".into()]).unwrap();
        assert_eq!((r.added.len(), r.failed.len()), (1, 1));
        assert!(repo.list_items(g.id).unwrap().iter().all(|i| i.kind == ItemKind::Url));
    }
}

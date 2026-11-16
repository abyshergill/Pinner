//! Plain data objects and validation helpers shared across layers.

use std::fmt;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum Section {
    Paths,
    Browser,
}

impl Section {
    pub fn as_str(self) -> &'static str {
        match self {
            Section::Paths => "paths",
            Section::Browser => "browser",
        }
    }
    pub fn parse(s: &str) -> Option<Section> {
        match s {
            "paths" => Some(Section::Paths),
            "browser" => Some(Section::Browser),
            _ => None,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum ItemKind {
    Folder,
    File,
    Url,
}

impl ItemKind {
    pub const ALL: [ItemKind; 3] = [ItemKind::Folder, ItemKind::File, ItemKind::Url];

    pub fn as_str(self) -> &'static str {
        match self {
            ItemKind::Folder => "folder",
            ItemKind::File => "file",
            ItemKind::Url => "url",
        }
    }
    pub fn parse(s: &str) -> Option<ItemKind> {
        match s {
            "folder" => Some(ItemKind::Folder),
            "file" => Some(ItemKind::File),
            "url" => Some(ItemKind::Url),
            _ => None,
        }
    }
    pub fn label(self) -> &'static str {
        match self {
            ItemKind::Folder => "Folder",
            ItemKind::File => "File / App",
            ItemKind::Url => "Web link",
        }
    }
}

/// Which kinds of entry each section accepts. Browser Bookmarks hold web links only.
pub fn allowed_kinds(section: Section) -> &'static [ItemKind] {
    match section {
        Section::Paths => &ItemKind::ALL,
        Section::Browser => &[ItemKind::Url],
    }
}

pub const BROWSER_LINKS_ONLY: &str =
    "Browser Bookmarks accept web links only - files and folders are not allowed.";

/// A user-created folder (can be nested).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Group {
    pub id: i64,
    pub section: Section,
    pub name: String,
    pub parent_id: Option<i64>,
}

/// A pinned folder path, file/app path or web link.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Item {
    pub id: i64,
    pub group_id: i64,
    pub kind: ItemKind,
    pub name: String,
    pub target: String,
    pub is_pinned: bool,
}

/// Errors surfaced to the user.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Error {
    /// User input is not acceptable.
    Validation(String),
    /// A sibling folder with the same name already exists.
    DuplicateName(String),
    /// A bookmark file could not be read.
    BookmarkFile(String),
    /// Something that was looked up does not exist.
    NotFound(String),
    /// Database failure.
    Database(String),
}

impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Error::Validation(m)
            | Error::DuplicateName(m)
            | Error::BookmarkFile(m)
            | Error::NotFound(m)
            | Error::Database(m) => f.write_str(m),
        }
    }
}

impl std::error::Error for Error {}

impl From<rusqlite::Error> for Error {
    fn from(e: rusqlite::Error) -> Self {
        Error::Database(e.to_string())
    }
}

pub type Result<T> = std::result::Result<T, Error>;

pub fn validation<T>(msg: impl Into<String>) -> Result<T> {
    Err(Error::Validation(msg.into()))
}

/// Prefixes that count as a *web* link.
pub const WEB_PREFIXES: [&str; 4] = ["http://", "https://", "ftp://", "mailto:"];
const ALLOWED_SCHEMES: [&str; 5] = ["http", "https", "ftp", "file", "mailto"];
const BOOKMARK_SCHEMES: [&str; 4] = ["http", "https", "ftp", "mailto"];

/// Length of a leading `scheme` (`[a-zA-Z][a-zA-Z0-9+.-]*`), or 0.
fn scheme_len(text: &str) -> usize {
    let mut chars = text.char_indices();
    match chars.next() {
        Some((_, c)) if c.is_ascii_alphabetic() => {}
        _ => return 0,
    }
    let mut end = 1;
    for (i, c) in chars {
        if c.is_ascii_alphanumeric() || matches!(c, '+' | '.' | '-') {
            end = i + c.len_utf8();
        } else {
            break;
        }
    }
    end
}

/// `scheme://` prefix: returns the scheme when present.
fn url_scheme(text: &str) -> Option<&str> {
    let n = scheme_len(text);
    (n > 0 && text[n..].starts_with("://")).then(|| &text[..n])
}

/// `javascript:`, `data:`, `about:` ... (but not `host:8080`).
fn pseudo_scheme(text: &str) -> Option<&str> {
    let n = scheme_len(text);
    if n == 0 {
        return None;
    }
    let rest = text[n..].strip_prefix(':')?;
    if rest.chars().next().is_some_and(|c| c.is_ascii_digit()) {
        return None;
    }
    Some(&text[..n])
}

/// `C:\x`, `C:/x`, `\\server`, `/usr`, `~/x`
fn looks_like_local_path(text: &str) -> bool {
    let b = text.as_bytes();
    if b.len() >= 3 && b[0].is_ascii_alphabetic() && b[1] == b':' && (b[2] == b'\\' || b[2] == b'/') {
        return true;
    }
    text.starts_with("\\\\") || text.starts_with('/') || text.starts_with('~')
}

pub fn clean_name(name: &str, what: &str) -> Result<String> {
    let name = name.trim();
    if name.is_empty() {
        return validation(format!("{what} cannot be empty."));
    }
    Ok(name.to_string())
}

/// Return a launchable URL; add `https://` when no scheme was typed.
pub fn normalize_url(url: &str) -> Result<String> {
    let mut url = url.trim().to_string();
    if url.is_empty() {
        return validation("Link cannot be empty.");
    }
    if url.to_lowercase().starts_with("mailto:") {
        return Ok(url);
    }
    if url_scheme(&url).is_none() {
        url = format!("https://{url}");
    }
    let (scheme, rest) = url.split_once("://").expect("scheme ensured above");
    let scheme = scheme.to_lowercase();
    if !ALLOWED_SCHEMES.contains(&scheme.as_str()) {
        return validation(format!("Unsupported link type: {scheme}://"));
    }
    if scheme != "file" && rest.trim_matches('/').is_empty() {
        return validation("Link has no address.");
    }
    Ok(url)
}

/// True for text that starts with `http://`, `https://`, `ftp://` or `mailto:`.
pub fn has_web_scheme(text: &str) -> bool {
    let t = text.trim().to_lowercase();
    WEB_PREFIXES.iter().any(|p| t.starts_with(p))
}

/// Like [`normalize_url`] but for Browser Bookmarks: **web links only**.
pub fn normalize_bookmark_url(url: &str) -> Result<String> {
    let text = url.trim();
    if text.is_empty() {
        return validation("Link cannot be empty.");
    }
    if looks_like_local_path(text) || text.to_lowercase().starts_with("file:") {
        return validation(BROWSER_LINKS_ONLY);
    }
    if text.chars().any(char::is_whitespace) {
        return validation("A link cannot contain spaces.");
    }
    if let Some(p) = pseudo_scheme(text) {
        if url_scheme(text).is_none() && !p.eq_ignore_ascii_case("mailto") {
            return validation(format!("Unsupported link type: {}:", p.to_lowercase()));
        }
    }
    let normalized = normalize_url(text)?;
    let scheme = match normalized.split_once("://") {
        Some((s, _)) => s.to_lowercase(),
        None => "mailto".to_string(),
    };
    if !BOOKMARK_SCHEMES.contains(&scheme.as_str()) {
        return validation(BROWSER_LINKS_ONLY);
    }
    Ok(normalized)
}

/// Validate/normalise the target for an item of `kind`.
pub fn clean_target(kind: ItemKind, target: &str, section: Option<Section>) -> Result<String> {
    if kind == ItemKind::Url {
        return if section == Some(Section::Browser) {
            normalize_bookmark_url(target)
        } else {
            normalize_url(target)
        };
    }
    clean_name(target, "Path")
}

pub fn check_kind_allowed(section: Section, kind: ItemKind) -> Result<()> {
    if allowed_kinds(section).contains(&kind) {
        Ok(())
    } else {
        validation(BROWSER_LINKS_ONLY)
    }
}

/// Single gatekeeper for "can this entry live in this section?".
pub fn validate_entry(
    section: Section,
    kind: ItemKind,
    name: &str,
    target: &str,
) -> Result<(ItemKind, String, String)> {
    check_kind_allowed(section, kind)?;
    Ok((kind, clean_name(name, "Name")?, clean_target(kind, target, Some(section))?))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn name_is_trimmed_and_required() {
        assert_eq!(clean_name("  a ", "Name").unwrap(), "a");
        assert!(clean_name("   ", "Name").is_err());
    }

    #[test]
    fn url_gets_https() {
        assert_eq!(normalize_url("example.com").unwrap(), "https://example.com");
        assert_eq!(normalize_url("HTTP://x.org").unwrap(), "HTTP://x.org");
        assert_eq!(normalize_url("mailto:a@b.c").unwrap(), "mailto:a@b.c");
        assert_eq!(normalize_url("file:///tmp/x").unwrap(), "file:///tmp/x");
    }

    #[test]
    fn url_rejections() {
        assert!(normalize_url("").is_err());
        assert!(normalize_url("gopher://x").is_err());
        assert!(normalize_url("https://").is_err());
    }

    #[test]
    fn bookmark_urls_are_web_only() {
        for bad in ["C:\\x", "C:/x", "/usr/x", "~/x", "\\\\srv\\share", "file:///x", "javascript:alert(1)",
                    "chrome://settings", "a b", "about:blank"] {
            assert!(normalize_bookmark_url(bad).is_err(), "{bad}");
        }
        assert_eq!(normalize_bookmark_url("example.com").unwrap(), "https://example.com");
        assert_eq!(normalize_bookmark_url("localhost:8080").unwrap(), "https://localhost:8080");
        assert_eq!(normalize_bookmark_url("mailto:x@y.z").unwrap(), "mailto:x@y.z");
        assert_eq!(normalize_bookmark_url("ftp://h/f").unwrap(), "ftp://h/f");
    }

    #[test]
    fn browser_section_rejects_files() {
        assert!(validate_entry(Section::Browser, ItemKind::File, "n", "/x").is_err());
        assert!(validate_entry(Section::Paths, ItemKind::File, "n", "/x").is_ok());
    }

    #[test]
    fn web_scheme_detection() {
        assert!(has_web_scheme(" HTTPS://a"));
        assert!(has_web_scheme("mailto:a@b"));
        assert!(!has_web_scheme("file:///a"));
    }
}

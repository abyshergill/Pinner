//! Import / export of browser bookmarks (GUI-free, fully testable).
//!
//! Reading
//! -------
//! * **Bookmarks HTML** ("Netscape bookmark file") - exported by Chrome, Edge, Brave,
//!   Opera, Vivaldi, Firefox and Safari. This is the format to use.
//! * **Chrome / Edge / Brave** `Bookmarks` profile file (JSON, no extension).
//! * **Firefox** bookmark backup (`.json`).
//!
//! Writing
//! -------
//! * Bookmarks HTML, which every browser above can import.
//!
//! Only *web links* (`http`, `https`, `ftp`, `mailto`) are ever imported. Bookmarklets
//! (`javascript:`), internal pages (`chrome://`, `about:`, `place:`) and local `file:`
//! links are skipped and counted.

use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use serde_json::Value;

use crate::config::expand_user;
use crate::models::{
    clean_name, has_web_scheme, normalize_bookmark_url, Error, Group, Item, ItemKind, Result, Section,
};
use crate::repository::Repository;

pub const MAX_FILE_BYTES: u64 = 50 * 1024 * 1024;
/// Deeper folders are flattened (guards against hostile files).
pub const MAX_DEPTH: usize = 64;
pub const UNTITLED_FOLDER: &str = "Untitled folder";
pub const LOOSE_LINKS_FOLDER: &str = "Imported bookmarks";

fn file_err<T>(msg: impl Into<String>) -> Result<T> {
    Err(Error::BookmarkFile(msg.into()))
}

// -------------------------------------------------------------- data model
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BookmarkLink {
    pub title: String,
    pub url: String,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct BookmarkFolder {
    pub name: String,
    pub folders: Vec<BookmarkFolder>,
    pub links: Vec<BookmarkLink>,
}

impl BookmarkFolder {
    pub fn new(name: impl Into<String>) -> Self {
        Self { name: name.into(), ..Default::default() }
    }
    pub fn count_links(&self) -> usize {
        self.links.len() + self.folders.iter().map(Self::count_links).sum::<usize>()
    }
    pub fn count_folders(&self) -> usize {
        self.folders.len() + self.folders.iter().map(Self::count_folders).sum::<usize>()
    }
}

/// A parsed (or about-to-be-exported) set of bookmarks.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct BookmarkTree {
    pub root: BookmarkFolder,
    /// Entries that are not plain web links.
    pub skipped: usize,
}

impl BookmarkTree {
    pub fn link_count(&self) -> usize {
        self.root.count_links()
    }
    pub fn folder_count(&self) -> usize {
        self.root.count_folders()
    }
}

/// A clean web link, or `None` for anything else (javascript:, chrome://, file:, ...).
fn accept_url(url: Option<&str>) -> Option<String> {
    let url = url?;
    if url.is_empty() || !has_web_scheme(url) {
        return None;
    }
    normalize_bookmark_url(url).ok()
}

fn collapse_ws(s: &str) -> String {
    s.split_whitespace().collect::<Vec<_>>().join(" ")
}

fn link_title(title: Option<&str>, url: &str) -> String {
    let t = collapse_ws(title.unwrap_or(""));
    if !t.is_empty() {
        return t;
    }
    let host = url.split_once("://").map_or(url, |(_, r)| r).split('/').next().unwrap_or("");
    if host.is_empty() { url.to_string() } else { host.to_string() }
}

fn folder_name(name: Option<&str>) -> String {
    let n = collapse_ws(name.unwrap_or(""));
    if n.is_empty() { UNTITLED_FOLDER.to_string() } else { n }
}

// ------------------------------------------------------------ HTML parsing
fn decode_entities(s: &str) -> String {
    if !s.contains('&') {
        return s.to_string();
    }
    let mut out = String::with_capacity(s.len());
    let mut rest = s;
    while let Some(i) = rest.find('&') {
        out.push_str(&rest[..i]);
        rest = &rest[i..];
        let decoded = rest[1..].find(';').filter(|&e| e <= 10).and_then(|e| {
            let name = &rest[1..1 + e];
            let ch = match name {
                "amp" => Some('&'),
                "lt" => Some('<'),
                "gt" => Some('>'),
                "quot" => Some('"'),
                "apos" => Some('\''),
                "nbsp" => Some('\u{a0}'),
                _ => name.strip_prefix('#').and_then(|n| {
                    let code = match n.strip_prefix(['x', 'X']) {
                        Some(h) => u32::from_str_radix(h, 16).ok()?,
                        None => n.parse().ok()?,
                    };
                    char::from_u32(code)
                }),
            };
            ch.map(|c| (c, e + 2))
        });
        match decoded {
            Some((c, used)) => {
                out.push(c);
                rest = &rest[used..];
            }
            None => {
                out.push('&');
                rest = &rest[1..];
            }
        }
    }
    out.push_str(rest);
    out
}

enum Token {
    Start(String, Vec<(String, String)>),
    End(String),
    Text(String),
}

/// A small, forgiving HTML tokenizer: enough for bookmark files (unclosed tags included).
fn tokenize(html: &str) -> Vec<Token> {
    let b = html.as_bytes();
    let mut tokens = Vec::new();
    let mut i = 0;
    let mut text_start = 0;
    let flush = |tokens: &mut Vec<Token>, from: usize, to: usize| {
        if to > from {
            tokens.push(Token::Text(decode_entities(&html[from..to])));
        }
    };
    while i < b.len() {
        if b[i] != b'<' {
            i += 1;
            continue;
        }
        let next = b.get(i + 1).copied().unwrap_or(0);
        if html[i..].starts_with("<!--") {
            flush(&mut tokens, text_start, i);
            i = html[i + 4..].find("-->").map_or(b.len(), |e| i + 4 + e + 3);
            text_start = i;
        } else if next == b'!' || next == b'?' {
            flush(&mut tokens, text_start, i);
            i = html[i..].find('>').map_or(b.len(), |e| i + e + 1);
            text_start = i;
        } else if next.is_ascii_alphabetic() || next == b'/' {
            flush(&mut tokens, text_start, i);
            let (tok, end) = parse_tag(html, i);
            tokens.push(tok);
            i = end;
            text_start = i;
        } else {
            i += 1; // a literal '<'
        }
    }
    flush(&mut tokens, text_start, b.len());
    tokens
}

/// Parse the tag starting at `start` (`html[start] == '<'`); returns the token and the end index.
fn parse_tag(html: &str, start: usize) -> (Token, usize) {
    let b = html.as_bytes();
    let mut i = start + 1;
    let closing = b[i] == b'/';
    if closing {
        i += 1;
    }
    let name_start = i;
    while i < b.len() && !b[i].is_ascii_whitespace() && b[i] != b'>' && b[i] != b'/' {
        i += 1;
    }
    let name = html[name_start..i].to_ascii_lowercase();
    let mut attrs = Vec::new();
    loop {
        while i < b.len() && (b[i].is_ascii_whitespace() || b[i] == b'/') {
            i += 1;
        }
        if i >= b.len() {
            break;
        }
        if b[i] == b'>' {
            i += 1;
            break;
        }
        let a_start = i;
        while i < b.len() && !b[i].is_ascii_whitespace() && !matches!(b[i], b'=' | b'>' | b'/') {
            i += 1;
        }
        let a_name = html[a_start..i].to_ascii_lowercase();
        while i < b.len() && b[i].is_ascii_whitespace() {
            i += 1;
        }
        let mut value = String::new();
        if i < b.len() && b[i] == b'=' {
            i += 1;
            while i < b.len() && b[i].is_ascii_whitespace() {
                i += 1;
            }
            if i < b.len() && (b[i] == b'"' || b[i] == b'\'') {
                let q = b[i];
                let v_start = i + 1;
                let v_end = b[v_start..].iter().position(|&c| c == q).map_or(b.len(), |p| v_start + p);
                value = decode_entities(&html[v_start..v_end]);
                i = (v_end + 1).min(b.len());
            } else {
                let v_start = i;
                while i < b.len() && !b[i].is_ascii_whitespace() && b[i] != b'>' {
                    i += 1;
                }
                value = decode_entities(&html[v_start..i]);
            }
        }
        if a_name.is_empty() {
            i += 1; // stray '=' or similar: make progress
        } else {
            attrs.push((a_name, value));
        }
    }
    let tok = if closing { Token::End(name) } else { Token::Start(name, attrs) };
    (tok, i)
}

/// Flat arena of folders so the parser can keep a stack of indices.
struct HtmlBuilder {
    /// (folder, parent index)
    nodes: Vec<(BookmarkFolder, Option<usize>)>,
    stack: Vec<usize>,
    skipped: usize,
    open_folder: Option<usize>,
    h3: Option<String>,
    a: Option<String>,
    href: Option<String>,
}

impl HtmlBuilder {
    fn new() -> Self {
        Self {
            nodes: vec![(BookmarkFolder::new(""), None)],
            stack: vec![0],
            skipped: 0,
            open_folder: None,
            h3: None,
            a: None,
            href: None,
        }
    }

    /// Close the link being read (also handles `<A>` tags that are never closed).
    fn finish_link(&mut self) {
        let Some(title) = self.a.take() else { return };
        let href = self.href.take();
        match accept_url(href.as_deref()) {
            None => self.skipped += 1,
            Some(url) => {
                let top = *self.stack.last().unwrap();
                let link = BookmarkLink { title: link_title(Some(&title), &url), url };
                self.nodes[top].0.links.push(link);
            }
        }
    }

    fn feed(&mut self, tokens: Vec<Token>) {
        for tok in tokens {
            match tok {
                Token::Start(tag, attrs) => {
                    if matches!(tag.as_str(), "a" | "dt" | "dl" | "h3") {
                        self.finish_link();
                    }
                    match tag.as_str() {
                        "h3" => self.h3 = Some(String::new()),
                        "a" => {
                            self.open_folder = None;
                            self.href = attrs.into_iter().rev().find(|(k, _)| k == "href").map(|(_, v)| v);
                            self.a = Some(String::new());
                        }
                        "dl" => {
                            let top = self.open_folder.take().unwrap_or(*self.stack.last().unwrap());
                            self.stack.push(top);
                        }
                        _ => {}
                    }
                }
                Token::End(tag) => match tag.as_str() {
                    "h3" if self.h3.is_some() => {
                        let name = folder_name(self.h3.take().as_deref());
                        if self.stack.len() < MAX_DEPTH {
                            let parent = *self.stack.last().unwrap();
                            self.nodes.push((BookmarkFolder::new(name), Some(parent)));
                            self.open_folder = Some(self.nodes.len() - 1);
                        } else {
                            self.open_folder = None;
                        }
                    }
                    "a" => self.finish_link(),
                    "dl" => {
                        self.finish_link();
                        if self.stack.len() > 1 {
                            self.stack.pop();
                        }
                        self.open_folder = None;
                    }
                    _ => {}
                },
                Token::Text(t) => {
                    if let Some(h) = self.h3.as_mut() {
                        h.push_str(&t);
                    } else if let Some(a) = self.a.as_mut() {
                        a.push_str(&t);
                    }
                }
            }
        }
        self.finish_link();
    }

    fn into_tree(mut self) -> BookmarkTree {
        // Children always come after their parent in `nodes`, so fold from the back
        // (inserting at 0 restores document order).
        for idx in (1..self.nodes.len()).rev() {
            let (folder, parent) = std::mem::take(&mut self.nodes[idx]);
            self.nodes[parent.unwrap()].0.folders.insert(0, folder);
        }
        BookmarkTree { root: self.nodes.swap_remove(0).0, skipped: self.skipped }
    }
}

pub fn parse_html(text: &str) -> BookmarkTree {
    let mut b = HtmlBuilder::new();
    b.feed(tokenize(text));
    b.into_tree()
}

// ------------------------------------------------------------ JSON parsing
/// Fill `folder` from a Chrome (`name`/`url`) or Firefox (`title`/`uri`) node.
fn walk_json(node: &Value, folder: &mut BookmarkFolder, skipped: &mut usize, depth: usize) {
    let Some(children) = node.get("children").and_then(Value::as_array) else { return };
    for child in children {
        let Some(obj) = child.as_object() else { continue };
        let str_of = |k: &str| obj.get(k).and_then(Value::as_str).filter(|s| !s.is_empty());
        if obj.contains_key("children") {
            if depth < MAX_DEPTH {
                let mut sub = BookmarkFolder::new(folder_name(str_of("name").or(str_of("title"))));
                walk_json(child, &mut sub, skipped, depth + 1);
                folder.folders.push(sub);
            } else {
                walk_json(child, folder, skipped, depth);
            }
            continue;
        }
        let Some(url) = str_of("url").or(str_of("uri")) else { continue }; // separators etc.
        match accept_url(Some(url)) {
            None => *skipped += 1,
            Some(u) => {
                let title = link_title(str_of("name").or(str_of("title")), &u);
                folder.links.push(BookmarkLink { title, url: u });
            }
        }
    }
}

pub fn parse_json(text: &str) -> Result<BookmarkTree> {
    let Ok(data) = serde_json::from_str::<Value>(text) else {
        return file_err("This file is not valid bookmark JSON.");
    };
    let mut tree = BookmarkTree::default();
    let mut skipped = 0;
    match &data {
        Value::Object(map) if map.get("roots").is_some_and(Value::is_object) => {
            // Chrome / Edge / Brave
            for (key, node) in map["roots"].as_object().unwrap() {
                let has_children = node.get("children").and_then(Value::as_array).is_some_and(|c| !c.is_empty());
                if has_children {
                    let name = node.get("name").and_then(Value::as_str).filter(|s| !s.is_empty()).unwrap_or(key);
                    let mut sub = BookmarkFolder::new(folder_name(Some(name)));
                    walk_json(node, &mut sub, &mut skipped, 1);
                    tree.root.folders.push(sub);
                }
            }
        }
        Value::Object(_) => walk_json(&data, &mut tree.root, &mut skipped, 0), // Firefox backup
        Value::Array(_) => {
            let wrapped = serde_json::json!({ "children": data });
            walk_json(&wrapped, &mut tree.root, &mut skipped, 0);
        }
        _ => {}
    }
    tree.skipped = skipped;
    Ok(tree)
}

// --------------------------------------------------------------- file read
pub fn decode_bytes(raw: &[u8]) -> String {
    let utf16 = |bytes: &[u8], le: bool| {
        let units: Vec<u16> = bytes
            .chunks_exact(2)
            .map(|c| if le { u16::from_le_bytes([c[0], c[1]]) } else { u16::from_be_bytes([c[0], c[1]]) })
            .collect();
        String::from_utf16_lossy(&units)
    };
    if let Some(rest) = raw.strip_prefix(&[0xff, 0xfe]) {
        return utf16(rest, true);
    }
    if let Some(rest) = raw.strip_prefix(&[0xfe, 0xff]) {
        return utf16(rest, false);
    }
    let raw = raw.strip_prefix(&[0xef, 0xbb, 0xbf]).unwrap_or(raw);
    String::from_utf8_lossy(raw).into_owned()
}

/// Auto-detect HTML vs JSON and parse. Errors if nothing usable was found.
pub fn parse_bookmarks(text: &str) -> Result<BookmarkTree> {
    let stripped = text.trim_start();
    let tree = if stripped.starts_with(['{', '[']) { parse_json(stripped)? } else { parse_html(text) };
    if tree.link_count() == 0 && tree.folder_count() == 0 {
        if tree.skipped > 0 {
            return file_err(format!(
                "No web links found ({} non-web bookmark(s) were ignored).",
                tree.skipped
            ));
        }
        return file_err(
            "No bookmarks found in this file.\n\
             Export your bookmarks from the browser as an HTML file and choose that file.",
        );
    }
    Ok(tree)
}

pub fn read_bookmark_file(path: impl AsRef<Path>) -> Result<BookmarkTree> {
    let path = expand_user(&path.as_ref().to_string_lossy());
    let size = std::fs::metadata(&path)
        .map_err(|e| Error::BookmarkFile(format!("Cannot read file:\n{}\n\n{e}", path.display())))?
        .len();
    if size > MAX_FILE_BYTES {
        return file_err("This file is too large to be a bookmarks file.");
    }
    let raw = std::fs::read(&path)
        .map_err(|e| Error::BookmarkFile(format!("Cannot read file:\n{}\n\n{e}", path.display())))?;
    parse_bookmarks(&decode_bytes(&raw))
}

// ------------------------------------------------------------------ import
#[derive(Debug, Default, Clone, PartialEq, Eq)]
pub struct ImportResult {
    pub folders_created: usize,
    pub links_added: usize,
    /// Link already present in that folder.
    pub duplicates: usize,
    /// Not a web link (javascript:, chrome://, file: ...).
    pub skipped: usize,
}

impl ImportResult {
    pub fn summary(&self) -> String {
        let mut parts = vec![
            format!("{} link(s) added", self.links_added),
            format!("{} folder(s) created", self.folders_created),
        ];
        if self.duplicates > 0 {
            parts.push(format!("{} duplicate(s) skipped", self.duplicates));
        }
        if self.skipped > 0 {
            parts.push(format!("{} non-web bookmark(s) ignored", self.skipped));
        }
        parts.join(", ")
    }
}

struct Importer<'a> {
    repo: &'a Repository,
    result: ImportResult,
    known: HashMap<i64, HashSet<String>>,
}

impl Importer<'_> {
    fn add_links(&mut self, links: &[BookmarkLink], gid: i64) -> Result<()> {
        if !self.known.contains_key(&gid) {
            let set = self.repo.list_items(gid)?.into_iter().map(|i| i.target.to_lowercase()).collect();
            self.known.insert(gid, set);
        }
        for link in links {
            let key = link.url.to_lowercase();
            if self.known[&gid].contains(&key) {
                self.result.duplicates += 1;
                continue;
            }
            self.repo.add_item(gid, ItemKind::Url, &link.title, &link.url, false)?;
            self.known.get_mut(&gid).unwrap().insert(key);
            self.result.links_added += 1;
        }
        Ok(())
    }

    fn get_or_create(&mut self, name: &str, parent: Option<i64>) -> Result<i64> {
        let name = clean_name(name, "Name")?;
        if let Some(g) = self.repo.find_group(Section::Browser, &name, parent)? {
            return Ok(g.id);
        }
        let g = self.repo.create_group(Section::Browser, &name, parent)?;
        self.result.folders_created += 1;
        Ok(g.id)
    }

    fn walk(&mut self, folder: &BookmarkFolder, gid: i64) -> Result<()> {
        self.add_links(&folder.links, gid)?;
        for sub in &folder.folders {
            let child = self.get_or_create(&sub.name, Some(gid))?;
            self.walk(sub, child)?;
        }
        Ok(())
    }
}

/// Merge `tree` into Browser Bookmarks.
///
/// * Folders are matched by name (case-insensitive) and merged; new ones are created.
/// * A link whose address is already in the same folder is not added again.
/// * `parent_id` imports inside that folder; `None` imports at the top level.
/// * Everything happens in one transaction: either all of it is imported or none.
pub fn import_bookmarks(repo: &Repository, tree: &BookmarkTree, parent_id: Option<i64>) -> Result<ImportResult> {
    if let Some(pid) = parent_id {
        if repo.get_group(pid)?.section != Section::Browser {
            return crate::models::validation("Bookmarks can only be imported into Browser Bookmarks.");
        }
    }
    let mut imp = Importer {
        repo,
        result: ImportResult { skipped: tree.skipped, ..Default::default() },
        known: HashMap::new(),
    };
    repo.batch(|| {
        if !tree.root.links.is_empty() {
            let gid = match parent_id {
                Some(p) => p,
                None => imp.get_or_create(LOOSE_LINKS_FOLDER, None)?,
            };
            imp.add_links(&tree.root.links, gid)?;
        }
        for sub in &tree.root.folders {
            let gid = imp.get_or_create(&sub.name, parent_id)?;
            imp.walk(sub, gid)?;
        }
        Ok(())
    })?;
    Ok(imp.result)
}

// ------------------------------------------------------------------ export
type Children = HashMap<Option<i64>, Vec<Group>>;
type ItemsByGroup = HashMap<i64, Vec<Item>>;

fn build_folder(group: &Group, depth: usize, children: &Children, items: &ItemsByGroup, skipped: &mut usize) -> BookmarkFolder {
    let mut folder = BookmarkFolder::new(group.name.clone());
    for it in items.get(&group.id).into_iter().flatten() {
        if it.kind == ItemKind::Url {
            folder.links.push(BookmarkLink { title: it.name.clone(), url: it.target.clone() });
        } else {
            *skipped += 1;
        }
    }
    if depth < MAX_DEPTH {
        for c in children.get(&Some(group.id)).into_iter().flatten() {
            folder.folders.push(build_folder(c, depth + 1, children, items, skipped));
        }
    }
    folder
}

/// Collect Browser Bookmarks (everything, or one folder with its sub-folders).
///
/// Entries that are not web links (only possible in databases created before
/// links-only was enforced) are left out and counted in `skipped`.
pub fn build_tree(repo: &Repository, group_id: Option<i64>) -> Result<BookmarkTree> {
    let mut children: Children = HashMap::new();
    for g in repo.list_groups(Section::Browser)? {
        children.entry(g.parent_id).or_default().push(g);
    }
    let mut items: ItemsByGroup = HashMap::new();
    for it in repo.list_section_items(Section::Browser)? {
        items.entry(it.group_id).or_default().push(it);
    }
    let mut tree = BookmarkTree::default();
    let mut skipped = 0;
    match group_id {
        None => {
            for g in children.get(&None).into_iter().flatten() {
                tree.root.folders.push(build_folder(g, 0, &children, &items, &mut skipped));
            }
        }
        Some(id) => {
            let g = repo.get_group(id)?;
            tree.root.folders.push(build_folder(&g, 0, &children, &items, &mut skipped));
        }
    }
    tree.skipped = skipped;
    Ok(tree)
}

fn esc(text: &str) -> String {
    text.replace('&', "&amp;").replace('<', "&lt;").replace('>', "&gt;").replace('"', "&quot;").replace('\'', "&#x27;")
}

fn render(folder: &BookmarkFolder, depth: usize, stamp: u64, out: &mut Vec<String>) {
    let pad = "    ".repeat(depth);
    for sub in &folder.folders {
        out.push(format!("{pad}<DT><H3 ADD_DATE=\"{stamp}\" LAST_MODIFIED=\"{stamp}\">{}</H3>", esc(&sub.name)));
        out.push(format!("{pad}<DL><p>"));
        render(sub, depth + 1, stamp, out);
        out.push(format!("{pad}</DL><p>"));
    }
    for link in &folder.links {
        out.push(format!("{pad}<DT><A HREF=\"{}\" ADD_DATE=\"{stamp}\">{}</A>", esc(&link.url), esc(&link.title)));
    }
}

/// Render `tree` as a Netscape bookmark file that browsers can import.
pub fn export_html(tree: &BookmarkTree, now: Option<u64>, title: &str) -> String {
    let stamp = now.unwrap_or_else(|| SystemTime::now().duration_since(UNIX_EPOCH).map_or(0, |d| d.as_secs()));
    let mut out = vec![
        "<!DOCTYPE NETSCAPE-Bookmark-file-1>".to_string(),
        "<!-- This is an automatically generated file. It will be read and overwritten. DO NOT EDIT! -->".into(),
        "<META HTTP-EQUIV=\"Content-Type\" CONTENT=\"text/html; charset=UTF-8\">".into(),
        format!("<TITLE>{}</TITLE>", esc(title)),
        format!("<H1>{}</H1>", esc(title)),
        "<DL><p>".into(),
    ];
    render(&tree.root, 1, stamp, &mut out);
    out.push("</DL><p>".into());
    out.join("\n") + "\n"
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ExportResult {
    pub path: PathBuf,
    pub folders: usize,
    pub links: usize,
    pub skipped: usize,
}

impl ExportResult {
    pub fn summary(&self) -> String {
        let mut text = format!("Exported {} link(s) in {} folder(s)", self.links, self.folders);
        if self.skipped > 0 {
            let noun = if self.skipped == 1 { "entry" } else { "entries" };
            text += &format!(" ({} non-link {noun} left out)", self.skipped);
        }
        text
    }
}

/// Write Browser Bookmarks (or one folder) to `path` as bookmarks HTML.
pub fn export_to_file(repo: &Repository, path: impl AsRef<Path>, group_id: Option<i64>) -> Result<ExportResult> {
    let path = expand_user(&path.as_ref().to_string_lossy());
    let tree = build_tree(repo, group_id)?;
    std::fs::write(&path, export_html(&tree, None, "Pinner Bookmarks"))
        .map_err(|e| Error::BookmarkFile(format!("Cannot write file:\n{}\n\n{e}", path.display())))?;
    Ok(ExportResult { folders: tree.folder_count(), links: tree.link_count(), skipped: tree.skipped, path })
}

#[cfg(test)]
mod tests {
    use super::*;

    const SAMPLE: &str = r#"<!DOCTYPE NETSCAPE-Bookmark-file-1>
<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">
<TITLE>Bookmarks</TITLE>
<H1>Bookmarks</H1>
<DL><p>
    <DT><H3 ADD_DATE="1">Bookmarks bar</H3>
    <DL><p>
        <DT><A HREF="https://example.com/" ADD_DATE="1">Example &amp; Co</A>
        <DT><A HREF="javascript:alert(1)">Bookmarklet</A>
        <DT><H3>Work</H3>
        <DL><p>
            <DT><A HREF="https://work.example/x?a=1&amp;b=2">Work   site</A>
            <DT><A HREF="chrome://settings">Settings</A>
        </DL><p>
        <DT><A HREF="mailto:me@example.com"></A>
    </DL><p>
    <DT><A HREF="http://loose.example">Loose</A>
</DL><p>
"#;

    #[test]
    fn parses_netscape_html() {
        let t = parse_html(SAMPLE);
        assert_eq!(t.skipped, 2);
        assert_eq!(t.link_count(), 4);
        assert_eq!(t.folder_count(), 2);
        assert_eq!(t.root.links[0].url, "http://loose.example");
        let bar = &t.root.folders[0];
        assert_eq!(bar.name, "Bookmarks bar");
        assert_eq!(bar.links[0], BookmarkLink { title: "Example & Co".into(), url: "https://example.com/".into() });
        assert_eq!(bar.links[1].title, "mailto:me@example.com");
        let work = &bar.folders[0];
        assert_eq!(work.name, "Work");
        assert_eq!(work.links[0].title, "Work site");
        assert_eq!(work.links[0].url, "https://work.example/x?a=1&b=2");
    }

    #[test]
    fn tolerates_unclosed_and_garbage() {
        let t = parse_html("<DL><DT><H3>F</H3><DL><DT><A HREF='https://a.org'>A<DT><A HREF=https://b.org>B</DL>x < y");
        assert_eq!(t.folder_count(), 1);
        assert_eq!(t.link_count(), 2);
        assert_eq!(t.root.folders[0].links[1].title, "B");
    }

    #[test]
    fn folder_order_is_document_order() {
        let t = parse_html("<DL><DT><H3>A</H3><DL></DL><DT><H3>B</H3><DL></DL><DT><H3>C</H3><DL></DL></DL>");
        let names: Vec<_> = t.root.folders.iter().map(|f| f.name.as_str()).collect();
        assert_eq!(names, ["A", "B", "C"]);
    }

    #[test]
    fn parses_chrome_json() {
        let json = r#"{"roots":{"bookmark_bar":{"name":"Bookmarks bar","children":[
            {"type":"url","name":"A","url":"https://a.org"},
            {"type":"url","name":"JS","url":"javascript:void(0)"},
            {"name":"Sub","children":[{"name":"B","url":"https://b.org"}]}]},
            "other":{"name":"Other","children":[]}}}"#;
        let t = parse_bookmarks(json).unwrap();
        assert_eq!((t.link_count(), t.folder_count(), t.skipped), (2, 2, 1));
        assert_eq!(t.root.folders[0].name, "Bookmarks bar");
    }

    #[test]
    fn parses_firefox_json() {
        let json = r#"{"title":"","children":[{"title":"Menu","children":[{"title":"F","uri":"https://f.org"},
            {"title":"place","uri":"place:type=6"}]}]}"#;
        let t = parse_bookmarks(json).unwrap();
        assert_eq!((t.link_count(), t.skipped), (1, 1));
        assert_eq!(t.root.folders[0].name, "Menu");
    }

    #[test]
    fn errors_for_unusable_files() {
        assert!(matches!(parse_bookmarks("{ nope"), Err(Error::BookmarkFile(_))));
        assert!(parse_bookmarks("hello world").is_err());
        let e = parse_bookmarks(r#"<DL><DT><A HREF="javascript:x">x</A></DL>"#).unwrap_err();
        assert!(e.to_string().contains("1 non-web"));
    }

    #[test]
    fn decodes_utf16_and_bom() {
        let mut raw = vec![0xff, 0xfe];
        for u in "<DL><DT><A HREF=\"https://a.org\">é</A></DL>".encode_utf16() {
            raw.extend(u.to_le_bytes());
        }
        assert!(decode_bytes(&raw).contains("https://a.org"));
        assert_eq!(decode_bytes(b"\xef\xbb\xbfhi"), "hi");
    }

    #[test]
    fn import_merges_and_is_idempotent() {
        let repo = Repository::in_memory().unwrap();
        let tree = parse_html(SAMPLE);
        let r1 = import_bookmarks(&repo, &tree, None).unwrap();
        assert_eq!((r1.links_added, r1.folders_created, r1.duplicates, r1.skipped), (4, 3, 0, 2));
        let r2 = import_bookmarks(&repo, &tree, None).unwrap();
        assert_eq!((r2.links_added, r2.folders_created, r2.duplicates), (0, 0, 4));
        assert!(repo.find_group(Section::Browser, "imported BOOKMARKS", None).unwrap().is_some());
    }

    #[test]
    fn import_into_folder_and_rejects_paths_section() {
        let repo = Repository::in_memory().unwrap();
        let target = repo.create_group(Section::Browser, "T", None).unwrap();
        let tree = parse_html(SAMPLE);
        import_bookmarks(&repo, &tree, Some(target.id)).unwrap();
        assert!(repo.find_group(Section::Browser, "Bookmarks bar", Some(target.id)).unwrap().is_some());
        assert_eq!(repo.list_items(target.id).unwrap().len(), 1); // the loose link
        let p = repo.create_group(Section::Paths, "P", None).unwrap();
        assert!(import_bookmarks(&repo, &tree, Some(p.id)).is_err());
    }

    #[test]
    fn export_then_reimport_roundtrips() {
        let repo = Repository::in_memory().unwrap();
        import_bookmarks(&repo, &parse_html(SAMPLE), None).unwrap();
        let tree = build_tree(&repo, None).unwrap();
        let html = export_html(&tree, Some(42), "Pinner Bookmarks");
        assert!(html.starts_with("<!DOCTYPE NETSCAPE-Bookmark-file-1>"));
        assert!(html.contains("ADD_DATE=\"42\""));
        assert!(html.contains("Example &amp; Co"));

        let again = Repository::in_memory().unwrap();
        import_bookmarks(&again, &parse_bookmarks(&html).unwrap(), None).unwrap();
        assert_eq!(build_tree(&again, None).unwrap(), tree);
    }

    #[test]
    fn export_single_folder_and_file() {
        let repo = Repository::in_memory().unwrap();
        import_bookmarks(&repo, &parse_html(SAMPLE), None).unwrap();
        let bar = repo.find_group(Section::Browser, "Bookmarks bar", None).unwrap().unwrap();
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("out.html");
        let res = export_to_file(&repo, &path, Some(bar.id)).unwrap();
        assert_eq!((res.folders, res.links), (2, 3));
        assert!(!std::fs::read_to_string(&path).unwrap().contains("loose.example"));
        assert_eq!(read_bookmark_file(&path).unwrap().link_count(), 3);
        assert_eq!(res.summary(), "Exported 3 link(s) in 2 folder(s)");
    }

    #[test]
    fn read_errors() {
        assert!(read_bookmark_file("/no/such/file.html").is_err());
    }
}

"""Import / export of browser bookmarks (Qt-free, fully testable).

Reading
-------
* **Bookmarks HTML** ("Netscape bookmark file") - exported by Chrome, Edge, Brave,
  Opera, Vivaldi, Firefox and Safari.  This is the format to use.
* **Chrome / Edge / Brave** ``Bookmarks`` profile file (JSON, no extension).
* **Firefox** bookmark backup (``.json``).

Writing
-------
* Bookmarks HTML, which every browser above can import.

Only *web links* (``http``, ``https``, ``ftp``, ``mailto``) are ever imported.
Bookmarklets (``javascript:``), internal pages (``chrome://``, ``about:``,
``place:``) and local ``file:`` links are skipped and counted.
"""
from __future__ import annotations

import html
import json
import time
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path

from .models import (
    ItemKind,
    Section,
    ValidationError,
    clean_name,
    has_web_scheme,
    normalize_bookmark_url,
)
from .repository import Repository

MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_DEPTH = 64                      # deeper folders are flattened (guards against hostile files)
UNTITLED_FOLDER = "Untitled folder"
LOOSE_LINKS_FOLDER = "Imported bookmarks"


class BookmarkFileError(ValidationError):
    """The chosen file is not a readable bookmarks file."""


# --------------------------------------------------------------- data model
@dataclass
class BookmarkLink:
    title: str
    url: str


@dataclass
class BookmarkFolder:
    name: str
    folders: list["BookmarkFolder"] = field(default_factory=list)
    links: list[BookmarkLink] = field(default_factory=list)

    def count_links(self) -> int:
        return len(self.links) + sum(f.count_links() for f in self.folders)

    def count_folders(self) -> int:
        return len(self.folders) + sum(f.count_folders() for f in self.folders)


@dataclass
class BookmarkTree:
    """A parsed (or about-to-be-exported) set of bookmarks."""
    root: BookmarkFolder = field(default_factory=lambda: BookmarkFolder(""))
    skipped: int = 0            # entries that are not plain web links

    @property
    def link_count(self) -> int:
        return self.root.count_links()

    @property
    def folder_count(self) -> int:
        return self.root.count_folders()


def _accept_url(url: str | None) -> str | None:
    """A clean web link, or ``None`` for anything else (javascript:, chrome://, file:, ...)."""
    if not url or not has_web_scheme(url):
        return None
    try:
        return normalize_bookmark_url(url)
    except ValidationError:
        return None


def _link_title(title: str | None, url: str) -> str:
    title = " ".join((title or "").split())
    if title:
        return title
    return url.split("://", 1)[-1].split("/", 1)[0] or url


def _folder_name(name: str | None) -> str:
    return " ".join((name or "").split()) or UNTITLED_FOLDER


# ------------------------------------------------------------- HTML parsing
class _NetscapeParser(HTMLParser):
    """Walks ``<DL>/<DT><H3>/<DT><A>`` bookmark files, tolerating unclosed tags.

    Every attribute is prefixed ``bm_`` so it can never clash with the private
    attributes of :class:`html.parser.HTMLParser` (they differ between Python versions).
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.bm_tree = BookmarkTree()
        self.bm_stack: list[BookmarkFolder] = [self.bm_tree.root]
        self.bm_open_folder: BookmarkFolder | None = None     # folder waiting for its <DL>
        self.bm_h3: list[str] | None = None
        self.bm_a: list[str] | None = None
        self.bm_href: str | None = None

    def bm_finish_link(self) -> None:
        """Close the link being read (also handles ``<A>`` tags that are never closed)."""
        if self.bm_a is None:
            return
        title, self.bm_a = "".join(self.bm_a), None
        url = _accept_url(self.bm_href)
        if url is None:
            self.bm_tree.skipped += 1
        else:
            self.bm_stack[-1].links.append(BookmarkLink(_link_title(title, url), url))
        self.bm_href = None

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in ("a", "dt", "dl", "h3"):
            self.bm_finish_link()
        if tag == "h3":
            self.bm_h3 = []
        elif tag == "a":
            self.bm_open_folder = None
            self.bm_href = dict(attrs).get("href")
            self.bm_a = []
        elif tag == "dl":
            self.bm_stack.append(self.bm_open_folder if self.bm_open_folder is not None else self.bm_stack[-1])
            self.bm_open_folder = None

    def handle_endtag(self, tag: str) -> None:
        if tag == "h3" and self.bm_h3 is not None:
            name, self.bm_h3 = _folder_name("".join(self.bm_h3)), None
            if len(self.bm_stack) < MAX_DEPTH:
                folder = BookmarkFolder(name)
                self.bm_stack[-1].folders.append(folder)
                self.bm_open_folder = folder
            else:
                self.bm_open_folder = None
        elif tag == "a":
            self.bm_finish_link()
        elif tag == "dl":
            self.bm_finish_link()
            if len(self.bm_stack) > 1:
                self.bm_stack.pop()
            self.bm_open_folder = None

    def handle_data(self, data: str) -> None:
        if self.bm_h3 is not None:
            self.bm_h3.append(data)
        elif self.bm_a is not None:
            self.bm_a.append(data)


def parse_html(text: str) -> BookmarkTree:
    parser = _NetscapeParser()
    parser.feed(text)
    parser.close()
    parser.bm_finish_link()
    return parser.bm_tree


# ------------------------------------------------------------- JSON parsing
def _walk_json(node: dict, folder: BookmarkFolder, tree: BookmarkTree, depth: int) -> None:
    """Fill ``folder`` from a Chrome (``name``/``url``) or Firefox (``title``/``uri``) node."""
    for child in node.get("children") or []:
        if not isinstance(child, dict):
            continue
        if "children" in child:
            if depth < MAX_DEPTH:
                sub = BookmarkFolder(_folder_name(child.get("name") or child.get("title")))
                folder.folders.append(sub)
                _walk_json(child, sub, tree, depth + 1)
            else:
                _walk_json(child, folder, tree, depth)
            continue
        url = child.get("url") or child.get("uri")
        if url is None:
            continue                       # separators and other non-link nodes
        accepted = _accept_url(url)
        if accepted is None:
            tree.skipped += 1
        else:
            folder.links.append(BookmarkLink(_link_title(child.get("name") or child.get("title"), accepted), accepted))


def parse_json(text: str) -> BookmarkTree:
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise BookmarkFileError("This file is not valid bookmark JSON.") from exc
    tree = BookmarkTree()
    if isinstance(data, dict) and isinstance(data.get("roots"), dict):          # Chrome / Edge / Brave
        for key, node in data["roots"].items():
            if isinstance(node, dict) and node.get("children"):
                sub = BookmarkFolder(_folder_name(node.get("name") or key))
                tree.root.folders.append(sub)
                _walk_json(node, sub, tree, 1)
    elif isinstance(data, dict):                                                 # Firefox backup
        _walk_json(data, tree.root, tree, 0)
    elif isinstance(data, list):
        _walk_json({"children": data}, tree.root, tree, 0)
    return tree


# ---------------------------------------------------------------- file read
def decode_bytes(raw: bytes) -> str:
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16", errors="replace")
    return raw.decode("utf-8-sig", errors="replace")


def parse_bookmarks(text: str) -> BookmarkTree:
    """Auto-detect HTML vs JSON and parse.  Raises :class:`BookmarkFileError` if nothing usable."""
    stripped = (text or "").lstrip()
    tree = parse_json(stripped) if stripped[:1] in ("{", "[") else parse_html(text or "")
    if tree.link_count == 0 and tree.folder_count == 0:
        if tree.skipped:
            raise BookmarkFileError(f"No web links found ({tree.skipped} non-web bookmark(s) were ignored).")
        raise BookmarkFileError(
            "No bookmarks found in this file.\n"
            "Export your bookmarks from the browser as an HTML file and choose that file.")
    return tree


def read_bookmark_file(path: str | Path) -> BookmarkTree:
    path = Path(path).expanduser()
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise BookmarkFileError(f"Cannot read file:\n{path}\n\n{exc}") from exc
    if size > MAX_FILE_BYTES:
        raise BookmarkFileError("This file is too large to be a bookmarks file.")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise BookmarkFileError(f"Cannot read file:\n{path}\n\n{exc}") from exc
    return parse_bookmarks(decode_bytes(raw))


# ------------------------------------------------------------------ import
@dataclass
class ImportResult:
    folders_created: int = 0
    links_added: int = 0
    duplicates: int = 0         # link already present in that folder
    skipped: int = 0            # not a web link (javascript:, chrome://, file: ...)

    def summary(self) -> str:
        parts = [f"{self.links_added} link(s) added", f"{self.folders_created} folder(s) created"]
        if self.duplicates:
            parts.append(f"{self.duplicates} duplicate(s) skipped")
        if self.skipped:
            parts.append(f"{self.skipped} non-web bookmark(s) ignored")
        return ", ".join(parts)


def import_bookmarks(repo: Repository, tree: BookmarkTree, parent_id: int | None = None) -> ImportResult:
    """Merge ``tree`` into Browser Bookmarks.

    * Folders are matched by name (case-insensitive) and merged; new ones are created.
    * A link whose address is already in the same folder is not added again.
    * ``parent_id`` imports inside that folder; ``None`` imports at the top level.
    * Everything happens in one transaction: either all of it is imported or none.
    """
    if parent_id is not None and repo.get_group(parent_id).section is not Section.BROWSER:
        raise ValidationError("Bookmarks can only be imported into Browser Bookmarks.")
    result = ImportResult(skipped=tree.skipped)
    known: dict[int, set[str]] = {}

    def existing(gid: int) -> set[str]:
        if gid not in known:
            known[gid] = {i.target.lower() for i in repo.list_items(gid)}
        return known[gid]

    def add_links(links: list[BookmarkLink], gid: int) -> None:
        seen = existing(gid)
        for link in links:
            key = link.url.lower()
            if key in seen:
                result.duplicates += 1
                continue
            repo.add_item(gid, ItemKind.URL, link.title, link.url)
            seen.add(key)
            result.links_added += 1

    def get_or_create(name: str, parent: int | None) -> int:
        name = clean_name(name)
        group = repo.find_group(Section.BROWSER, name, parent)
        if group is None:
            group = repo.create_group(Section.BROWSER, name, parent)
            result.folders_created += 1
        return group.id

    def walk(folder: BookmarkFolder, gid: int) -> None:
        add_links(folder.links, gid)
        for sub in folder.folders:
            walk(sub, get_or_create(sub.name, gid))

    with repo.batch():
        if tree.root.links:
            add_links(tree.root.links, parent_id if parent_id is not None
                      else get_or_create(LOOSE_LINKS_FOLDER, None))
        for sub in tree.root.folders:
            walk(sub, get_or_create(sub.name, parent_id))
    return result


# ------------------------------------------------------------------ export
def build_tree(repo: Repository, group_id: int | None = None) -> BookmarkTree:
    """Collect Browser Bookmarks (everything, or one folder with its sub-folders).

    Entries that are not web links (only possible in databases created before
    links-only was enforced) are left out and counted in ``skipped``.
    """
    groups = repo.list_groups(Section.BROWSER)
    children: dict[int | None, list] = {}
    for g in groups:
        children.setdefault(g.parent_id, []).append(g)
    items: dict[int, list] = {}
    for it in repo.list_section_items(Section.BROWSER):
        items.setdefault(it.group_id, []).append(it)

    tree = BookmarkTree()

    def build(group, depth: int = 0) -> BookmarkFolder:
        folder = BookmarkFolder(group.name)
        for it in items.get(group.id, []):
            if it.kind is ItemKind.URL:
                folder.links.append(BookmarkLink(it.name, it.target))
            else:
                tree.skipped += 1
        if depth < MAX_DEPTH:
            folder.folders = [build(c, depth + 1) for c in children.get(group.id, [])]
        return folder

    if group_id is None:
        tree.root.folders = [build(g) for g in children.get(None, [])]
    else:
        tree.root.folders = [build(repo.get_group(group_id))]
    return tree


def export_html(tree: BookmarkTree, now: int | None = None, title: str = "Pinner Bookmarks") -> str:
    """Render ``tree`` as a Netscape bookmark file that browsers can import."""
    stamp = int(time.time() if now is None else now)
    esc = lambda text: html.escape(text, quote=True)       # noqa: E731
    out = [
        "<!DOCTYPE NETSCAPE-Bookmark-file-1>",
        "<!-- This is an automatically generated file. It will be read and overwritten. DO NOT EDIT! -->",
        '<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">',
        f"<TITLE>{esc(title)}</TITLE>",
        f"<H1>{esc(title)}</H1>",
        "<DL><p>",
    ]

    def render(folder: BookmarkFolder, depth: int) -> None:
        pad = "    " * depth
        for sub in folder.folders:
            out.append(f'{pad}<DT><H3 ADD_DATE="{stamp}" LAST_MODIFIED="{stamp}">{esc(sub.name)}</H3>')
            out.append(f"{pad}<DL><p>")
            render(sub, depth + 1)
            out.append(f"{pad}</DL><p>")
        for link in folder.links:
            out.append(f'{pad}<DT><A HREF="{esc(link.url)}" ADD_DATE="{stamp}">{esc(link.title)}</A>')

    render(tree.root, 1)
    out.append("</DL><p>")
    return "\n".join(out) + "\n"


@dataclass
class ExportResult:
    path: Path
    folders: int
    links: int
    skipped: int = 0

    def summary(self) -> str:
        text = f"Exported {self.links} link(s) in {self.folders} folder(s)"
        if self.skipped:
            text += f" ({self.skipped} non-link entr{'y' if self.skipped == 1 else 'ies'} left out)"
        return text


def export_to_file(repo: Repository, path: str | Path, group_id: int | None = None) -> ExportResult:
    """Write Browser Bookmarks (or one folder) to ``path`` as bookmarks HTML."""
    path = Path(path).expanduser()
    tree = build_tree(repo, group_id)
    try:
        path.write_text(export_html(tree), encoding="utf-8")
    except OSError as exc:
        raise BookmarkFileError(f"Cannot write file:\n{path}\n\n{exc}") from exc
    return ExportResult(path, tree.folder_count, tree.link_count, tree.skipped)

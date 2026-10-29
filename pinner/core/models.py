"""Plain data objects and validation helpers shared across layers."""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class Section(str, Enum):
    """Top-level areas that own their own tree of folders."""
    PATHS = "paths"
    BROWSER = "browser"


class ItemKind(str, Enum):
    """What an entry points at (drives icon + how it is opened)."""
    FOLDER = "folder"
    FILE = "file"
    URL = "url"


# Which kinds of entry each section accepts.  Browser Bookmarks hold web links only.
ALLOWED_KINDS: dict[Section, frozenset[ItemKind]] = {
    Section.PATHS: frozenset(ItemKind),
    Section.BROWSER: frozenset({ItemKind.URL}),
}

BROWSER_LINKS_ONLY = "Browser Bookmarks accept web links only - files and folders are not allowed."


@dataclass(frozen=True)
class Group:
    """A user-created folder (can be nested)."""
    id: int
    section: Section
    name: str
    parent_id: int | None = None


@dataclass(frozen=True)
class Item:
    """A pinned folder path, file/app path or web link."""
    id: int
    group_id: int
    kind: ItemKind
    name: str
    target: str
    is_pinned: bool = False


class ValidationError(ValueError):
    """Raised when user input is not acceptable."""


class DuplicateNameError(ValidationError):
    """Raised when a sibling folder with the same name already exists."""


_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://")
_ALLOWED_SCHEMES = ("http", "https", "ftp", "file", "mailto")

# What counts as a *web* link (bookmarks, dropped links, imported browser bookmarks).
WEB_PREFIXES = ("http://", "https://", "ftp://", "mailto:")
_BOOKMARK_SCHEMES = ("http", "https", "ftp", "mailto")
_PSEUDO_SCHEME_RE = re.compile(r"^([a-zA-Z][a-zA-Z0-9+.\-]*):(?!\d)")      # javascript:..., data:..., about:... (not host:8080)
_LOCAL_PATH_RE = re.compile(r"^(?:[a-zA-Z]:[\\/]|\\\\|/|~)")   # C:\x, C:/x, \\server, /usr, ~/x


def clean_name(name: str, what: str = "Name") -> str:
    name = (name or "").strip()
    if not name:
        raise ValidationError(f"{what} cannot be empty.")
    return name


def normalize_url(url: str) -> str:
    """Return a launchable URL; add ``https://`` when no scheme was typed."""
    url = (url or "").strip()
    if not url:
        raise ValidationError("Link cannot be empty.")
    if url.lower().startswith("mailto:"):
        return url
    if not _SCHEME_RE.match(url):
        url = "https://" + url
    scheme = url.split("://", 1)[0].lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise ValidationError(f"Unsupported link type: {scheme}://")
    host_part = url.split("://", 1)[1]
    if scheme != "file" and not host_part.strip("/"):
        raise ValidationError("Link has no address.")
    return url


def has_web_scheme(text: str) -> bool:
    """True for text that starts with ``http://``, ``https://``, ``ftp://`` or ``mailto:``."""
    return (text or "").strip().lower().startswith(WEB_PREFIXES)


def normalize_bookmark_url(url: str) -> str:
    """Like :func:`normalize_url` but for Browser Bookmarks: **web links only**.

    Rejects local paths (``C:\\x``, ``/usr/x``, ``~/x``, ``\\\\server\\share``), ``file://`` links,
    ``javascript:``/``chrome://`` style pseudo-links and anything containing spaces.
    """
    text = (url or "").strip()
    if not text:
        raise ValidationError("Link cannot be empty.")
    if _LOCAL_PATH_RE.match(text) or text.lower().startswith("file:"):
        raise ValidationError(BROWSER_LINKS_ONLY)
    if re.search(r"\s", text):
        raise ValidationError("A link cannot contain spaces.")
    pseudo = _PSEUDO_SCHEME_RE.match(text)
    if pseudo and not _SCHEME_RE.match(text) and pseudo.group(1).lower() != "mailto":
        raise ValidationError(f"Unsupported link type: {pseudo.group(1).lower()}:")
    normalized = normalize_url(text)
    scheme = normalized.split("://", 1)[0].lower() if "://" in normalized else "mailto"
    if scheme not in _BOOKMARK_SCHEMES:
        raise ValidationError(BROWSER_LINKS_ONLY)
    return normalized


def clean_target(kind: ItemKind, target: str, section: Section | None = None) -> str:
    """Validate/normalise the target for an item of ``kind``."""
    if kind is ItemKind.URL:
        if section is not None and Section(section) is Section.BROWSER:
            return normalize_bookmark_url(target)
        return normalize_url(target)
    return clean_name(target, "Path")


def validate_entry(section: Section, kind: ItemKind, name: str, target: str) -> tuple[ItemKind, str, str]:
    """Single gatekeeper for "can this entry live in this section?".

    Returns the cleaned ``(kind, name, target)`` or raises :class:`ValidationError`.
    """
    section, kind = Section(section), ItemKind(kind)
    check_kind_allowed(section, kind)
    return kind, clean_name(name), clean_target(kind, target, section)


def check_kind_allowed(section: Section, kind: ItemKind) -> None:
    if ItemKind(kind) not in ALLOWED_KINDS[Section(section)]:
        raise ValidationError(BROWSER_LINKS_ONLY)

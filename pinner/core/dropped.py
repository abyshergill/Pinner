"""Turn dropped files / folders / links into entries (Qt-free, testable)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

from .models import (
    BROWSER_LINKS_ONLY,
    WEB_PREFIXES,
    Item,
    ItemKind,
    Section,
    ValidationError,
    normalize_url,
)
from .repository import Repository


def _file_url_to_path(source: str) -> str:
    parsed = urlparse(source)
    path = url2pathname(unquote(parsed.path))
    if parsed.netloc and parsed.netloc != "localhost":  # UNC share: file://server/share/x
        path = f"//{parsed.netloc}{path}"
    return path


def entry_from_source(source: str) -> tuple[ItemKind, str, str]:
    """Classify a dropped path or link as ``(kind, display_name, target)``.

    * ``http(s)://``, ``ftp://``, ``mailto:`` -> web link (name = host)
    * existing directory -> folder; existing file -> file / app
    * the target keeps the **full path including the file name**.
    """
    source = (source or "").strip().strip('"')
    if not source:
        raise ValidationError("Nothing to add.")

    lowered = source.lower()
    if lowered.startswith(WEB_PREFIXES):
        url = normalize_url(source)
        name = url.split("://", 1)[-1].split("/", 1)[0] if "://" in url else url
        return ItemKind.URL, name or url, url

    if lowered.startswith("file://"):
        source = _file_url_to_path(source)

    path = os.path.normpath(os.path.expanduser(source))
    if os.path.isdir(path):
        kind = ItemKind.FOLDER
    elif os.path.exists(path):
        kind = ItemKind.FILE
    else:
        raise ValidationError(f"Not found: {source}")
    name = os.path.basename(path.rstrip("/\\")) or path  # drive roots have no basename
    return kind, name, path


@dataclass
class DropResult:
    added: list[Item] = field(default_factory=list)
    skipped: int = 0                      # already in the folder
    failed: list[str] = field(default_factory=list)

    def summary(self) -> str:
        parts = [f"Added {len(self.added)}"]
        if self.skipped:
            parts.append(f"{self.skipped} already there")
        if self.failed:
            parts.append(f"{len(self.failed)} failed")
        return ", ".join(parts)


def add_sources(repo: Repository, group_id: int, sources: list[str]) -> DropResult:
    """Add every dropped source to ``group_id`` (duplicates are skipped).

    In a Browser Bookmarks folder only web links are accepted: dropped files and
    folders are reported in ``failed`` and never stored.
    """
    result = DropResult()
    links_only = repo.get_group(group_id).section is Section.BROWSER
    existing = {i.target.lower() for i in repo.list_items(group_id)}
    for source in sources:
        try:
            kind, name, target = entry_from_source(source)
            if links_only and kind is not ItemKind.URL:
                raise ValidationError(f"{BROWSER_LINKS_ONLY}\n  ({source})")
        except ValidationError as exc:
            result.failed.append(str(exc))
            continue
        if target.lower() in existing:
            result.skipped += 1
            continue
        try:
            result.added.append(repo.add_item(group_id, kind, name, target))
        except ValidationError as exc:
            result.failed.append(f"{source}: {exc}")
            continue
        existing.add(target.lower())
    return result

"""Drag & drop helpers shared by the tree and the Add/Edit dialog."""
from __future__ import annotations

from PyQt6.QtCore import QMimeData

from ..core.models import has_web_scheme


def sources_from_mime(mime: QMimeData) -> list[str]:
    """Local file paths (full path + file name) or link strings from a drop."""
    if mime.hasUrls():
        return [u.toLocalFile() if u.isLocalFile() else u.toString() for u in mime.urls()]
    if mime.hasText():
        text = mime.text().strip()
        if text and "\n" not in text:  # a single pasted path or link
            return [text]
    return []


def links_from_mime(mime: QMimeData) -> list[str]:
    """Only the *web links* in a drop - local files and folders are filtered out.

    Used by Browser Bookmarks, which accept links and nothing else.
    """
    return [s for s in sources_from_mime(mime) if has_web_scheme(s)]


def can_accept(mime: QMimeData) -> bool:
    return mime.hasUrls() or (mime.hasText() and "\n" not in mime.text().strip())


def can_accept_links(mime: QMimeData) -> bool:
    return bool(links_from_mime(mime))

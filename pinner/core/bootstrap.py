"""Wires the database together and seeds first-run data."""
from __future__ import annotations

from pathlib import Path

from ..config import default_db_path
from .database import Database
from .models import Section
from .repository import Repository

DEFAULT_FOLDERS = {Section.PATHS: "General", Section.BROWSER: "Bookmarks"}


def ensure_default_folders(repo: Repository) -> None:
    """Make sure each section has at least one folder to add things to."""
    for section, name in DEFAULT_FOLDERS.items():
        if not repo.list_groups(section):
            repo.create_group(section, name)


def open_repository(db_path: str | Path | None = None) -> Repository:
    """Open (and initialise) the database and seed the default folders."""
    db = Database(db_path or default_db_path())
    repo = Repository(db)
    ensure_default_folders(repo)
    return repo

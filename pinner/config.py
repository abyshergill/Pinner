"""Runtime configuration (storage locations)."""
from __future__ import annotations

import os
from pathlib import Path

DB_ENV_VAR = "PINNER_DB"
DB_FILE_NAME = "pinner.db"

# Root folder of the project (the folder that contains main.py).
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def default_db_path() -> Path:
    """Where the SQLite database lives: ``<project root>/pinner.db``.

    Override with the ``PINNER_DB`` environment variable.
    """
    override = os.environ.get(DB_ENV_VAR)
    if override:
        return Path(override).expanduser()
    return PROJECT_ROOT / DB_FILE_NAME

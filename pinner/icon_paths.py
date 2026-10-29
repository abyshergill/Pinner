"""Single place that defines where every icon used by the application lives.

Nothing else in the code base hard-codes an icon path.  To re-skin the app,
drop new files into ``assets/icons`` (or point these constants somewhere
else) -- no UI code needs to change.
"""
from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Allow packagers / users to relocate the icon directory.
ICON_DIR = Path(os.environ.get("PINNER_ICON_DIR", PROJECT_ROOT / "assets" / "icons"))

# Application / window icon
APP_ICON = ICON_DIR / "app.svg"

# Icons that identify what an entry is
FOLDER_ICON = ICON_DIR / "folder.svg"
FILE_ICON = ICON_DIR / "file.svg"
URL_ICON = ICON_DIR / "url.svg"

# Icons for the user-created folders (groups) in each tab
PATH_GROUP_ICON = ICON_DIR / "group_paths.svg"
BROWSER_GROUP_ICON = ICON_DIR / "group_browser.svg"

# Always-on-top / window pinning
WINDOW_PIN_ICON = ICON_DIR / "window_pin.svg"

# Logical name -> path.  UI code only ever asks for logical names.
ICON_PATHS: dict[str, Path] = {
    "app": APP_ICON,
    "folder": FOLDER_ICON,
    "file": FILE_ICON,
    "url": URL_ICON,
    "group_paths": PATH_GROUP_ICON,
    "group_browser": BROWSER_GROUP_ICON,
    "window_pin": WINDOW_PIN_ICON,
}

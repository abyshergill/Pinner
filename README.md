# Pinner

A desktop app (PyQt6) to organise the folders, files, apps and web links you open every day —
grouped in your own folders (e.g. one per customer or project) and stored in SQLite.

## Features

| Area | What you can do |
|------|-----------------|
| **Paths tab** | One tree of your own folders and **sub-folders** (any depth). Inside each, pin **folders, files/apps and web links**. |
| **Browser Bookmarks tab** | Same tree for bookmarks, but **web links only**: bookmark folders (and sub-folders) containing links. Files and folders cannot be added here. |
| **Import / export bookmarks** | **Import…** reads a bookmarks file from Chrome, Edge, Brave, Firefox, Safari, Opera or Vivaldi; **Export…** writes a file any of them can import. See [Bookmarks](#bookmarks-import-export-and-links-only). |
| **Drag & drop** | On the **Paths** tab, drop files, folders or browser links onto the tree (on **Browser Bookmarks** only links are accepted): the **full path including the file name** is stored automatically. Drop onto a folder to choose where it goes; drag an entry onto another folder to move it. The Add dialog accepts drops too. |
| **Friendly names** | Every entry has an editable display name (a customer name instead of a raw path). |
| **Icons** | Folder / file / link entries each have their own icon. |
| **Pin to top** | Right-click an entry → *Pin to top of folder* (★). |
| **Search** | Filters the tree by name or location; matching entries keep their folder chain. |
| **Open** | Every entry has a green **Open** button on its row, plus **▶ Open** in the toolbar, **Enter** / double-click, and right-click → *Open* / *Show in folder*. Folders open in the file manager, files with their default program, links in your browser. |
| **Always on Top tab** | Choose a window from a **drop-down** (a live **preview** screenshot is shown), choose its **priority** from a second drop-down, click *Pin on Top*. Priority 1 stays above all other pinned windows; reorder with ▲/▼. (Windows) |
| **Pins end with the app** | Closing Pinner (or quitting) un-pins every window it pinned **unless** you tick *Active after the application stop* (unchecked by default; the choice is remembered). Windows that were already always-on-top beforehand are left as they were. |
| **Keep Pinner on top** | Checkbox in the header; remembered between runs (all platforms). |
| **System theme** | Follows your OS light/dark mode and accent colour; no hard-coded colours or fonts. |
| **SQLite storage** | `pinner.db` in the project root, next to `main.py` (override with `PINNER_DB`). |

Double-click an entry to open it. Right-click a folder for New sub-folder / Add / Rename / Delete (on Browser Bookmarks also *Import bookmarks here…* and *Export this folder…*), or an entry for Edit, Copy, Move to, Remove.

## Works on Windows, macOS and Linux

Pinner is cross-platform: the same code runs on all three, follows each system's own look (light/dark mode and accent colour) and opens things with each system's own tools.

| Feature | Windows | macOS | Linux |
|---------|:-------:|:-----:|:-----:|
| Paths: folders, sub-folders, files/apps, links | ✅ | ✅ | ✅ |
| Browser Bookmarks (links only) + import / export | ✅ | ✅ | ✅ |
| Drag & drop, search, pin to top, friendly names | ✅ | ✅ | ✅ |
| Open entries | default program | `open` | `xdg-open` |
| Show in folder | selects the file in Explorer | selects it in Finder | opens the containing folder |
| Keep Pinner on top (header checkbox) | ✅ | ✅ | ✅ (some Linux window managers, e.g. Wayland, may ignore it) |
| **Always on Top tab** (pin *other* apps' windows) | ✅ needs `pywin32` | ➖ not available | ➖ not available |

* On macOS and Linux the *Always on Top* tab is simply disabled and shows a short notice. Everything else works the same.
* Linux needs `xdg-open` (installed on almost every desktop).
* Tested on Linux (the automated tests). Windows and macOS behaviour for opening files, *Show in folder* and window pinning follows the OS commands above; if something misbehaves on your system, please open an issue.

## Bookmarks: import, export and links only

### Links only
The **Browser Bookmarks** tab stores **web links** (`http`, `https`, `ftp`, `mailto`) and nothing else. It is enforced in four places, so there is no way around it:

| Layer | What happens |
|-------|--------------|
| **UI** | The tab has a single **+ Link** button (no *Folder* / *File* choices). The Add dialog only offers *Web link*. Right-click menus offer *Add link…* only. |
| **Drag & drop** | Dropping a file or folder on the bookmarks list is refused (forbidden cursor). Dragging a link from a browser works. |
| **Code** | `Repository.add_item`, `update_item` and `move_item` reject non-links for Browser folders, including local paths typed as links (`C:\x`, `/usr/x`, `~/x`, `\\server\share`), `file://` links, `javascript:` and `chrome://`. |
| **Database** | SQLite triggers abort any `INSERT` / `UPDATE` that would put a file or folder into a bookmarks folder. |

Folders still exist for organising bookmarks; it is the *entries* inside them that must be links. The **Paths** tab is unchanged: folders, files/apps and links.

### Import
1. In your browser, export your bookmarks to a file:
   * **Chrome / Edge / Brave / Opera / Vivaldi**: Bookmark manager → ⋮ menu → *Export bookmarks* (HTML).
   * **Firefox**: Library (Ctrl+Shift+O) → *Import and Backup* → *Export Bookmarks to HTML…*.
   * **Safari**: File → *Export* → *Bookmarks…*.
2. In Pinner open **Browser Bookmarks** → **Import…** and choose the file.
   Right-click a folder → *Import bookmarks here…* to import inside that folder instead of at the top level.

What import does:
* Browser folders (*Bookmarks bar*, *Other bookmarks*, your own sub-folders…) become Pinner folders and sub-folders.
* Folders are **merged by name** (case-insensitive) with ones you already have; a link already in the same folder is **skipped**, so importing the same file twice is safe.
* Non-web bookmarks (bookmarklets `javascript:`, `chrome://`, `about:`, `place:`, local `file:` links) are **ignored** and counted in the summary.
* It is all-or-nothing: if anything goes wrong, nothing is imported.
* Also understood: the Chrome / Edge / Brave `Bookmarks` profile file and Firefox `.json` backups.

### Export
**Export…** writes every bookmark as a standard *Netscape bookmarks HTML* file (folders and sub-folders preserved). Right-click a folder → *Export this folder…* to export only that folder.
Then in the browser: *Import bookmarks* → *Bookmarks HTML file* → choose the file (Chrome: ⋮ → Bookmarks → *Import bookmarks*; Firefox: Library → *Import and Backup* → *Import Bookmarks from HTML…*).

> Databases created by an earlier version may still contain a file/folder entry inside Bookmarks. It stays visible and can be opened, edited into a link, or removed, but it cannot be moved, and it is left out of exports (the export summary tells you how many).


## Getting started (for forks and contributors)

### Requirements
* **Python 3.10 or newer** (3.12 is what the project was developed on)
* **Windows, macOS or Linux.** Everything works on all three except the *Always on Top* tab, which uses `pywin32` and the Win32 API
  and is therefore Windows-only (on macOS and Linux that one tab shows a notice and is disabled).
  See [Works on Windows, macOS and Linux](#works-on-windows-macos-and-linux).
* `git`

### 1. Fork and clone
```bash
git clone https://github.com/<your-username>/<your-fork>.git
cd <your-fork>
```

### 2. Create a virtual environment
```bash
# Windows (PowerShell)
python -m venv .venv
.venv\Scripts\Activate.ps1

# macOS / Linux
python3 -m venv .venv
source .venv/bin/activate
```
`.venv/` is already in `.gitignore`.

### 3. Install dependencies
```bash
pip install -r requirements.txt        # to run the app
pip install -r requirements-dev.txt    # to run the app AND the tests (adds pytest)
```
`pywin32` is only installed on Windows (`sys_platform == "win32"` marker in `requirements.txt`).

### 4. Run the app
```bash
python main.py
```
On first run Pinner creates **`pinner.db`** next to `main.py` with two starter folders ("General" and "Bookmarks").
That file is git-ignored, so your data is never committed. Delete it to start fresh.

## Running the tests

```bash
pip install -r requirements-dev.txt
pytest                         # whole suite
```

No `pytest`? The suite is plain `unittest`, so this works too:
```bash
python -m unittest discover -s tests -t .
```

Run from the **project root** (the folder containing `main.py` and `pytest.ini`) so `import pinner` resolves.

### Useful variations
```bash
pytest -v                                   # list every test
pytest tests/test_repository.py             # one file
pytest tests/test_repository.py -k move     # tests whose name contains "move"
pytest -x                                   # stop at the first failure
pytest -rs                                  # show why tests were skipped
```

### What the tests cover

| Group | Files | Needs PyQt6? |
|-------|-------|--------------|
| **Core logic** (SQLite repository, models and validation, links-only rules, **bookmark import/export**, launcher, window pinner and priorities, drop handling, bootstrap, icon paths, stylesheet rules) | `test_repository.py`, `test_models.py`, `test_bookmarks.py`, `test_launcher.py`, `test_window_pinner.py`, `test_dropped.py`, `test_bootstrap.py`, `test_icon_paths.py`, `test_styles.py` | No (stylesheet tests run without a GUI) |
| **UI widgets** (tree, dialog, icons, main window, Always on Top panel) | `test_ui_section_widget.py`, `test_ui_dialog_and_icons.py`, `test_ui_main_window.py` | Yes |

How the suite is set up:
* **UI tests run headless.** `tests/qt_support.py` sets `QT_QPA_PLATFORM=offscreen`, so no window appears and no display is needed (CI-friendly).
* **UI tests skip, not fail, when PyQt6 is missing.** If you see many `skipped`, run `pytest -rs`. The reason is "PyQt6 is not installed".
  Run `pip install -r requirements-dev.txt`, then re-run.
* **Your real data is never touched.** Tests use an in-memory SQLite database (`:memory:`) or temporary folders.
* **No real windows are pinned.** The Windows pinning code is tested through a fake backend and fake `win32` objects, so the suite runs on any OS.
  Because of this, the tests can't prove how pinning, window previews or the system theme look and behave on a real desktop.
  Before opening a pull request that touches those areas, try them by hand on Windows with `python main.py`.
* **An icon-path guard test** (`test_icon_paths.py`) fails if any module other than `pinner/icon_paths.py` hard-codes an icon path.
* **A stylesheet guard test** (`test_styles.py`) fails if `px` font sizes come back (they cause `QFont::setPointSize: Point size <= 0`).

### Adding your own tests
1. Put the file in `tests/` named `test_<something>.py`, with `unittest.TestCase` classes and `test_*` methods.
2. Keep logic in `pinner/core/` (no Qt) where you can, so it is testable without a GUI.
3. For widget tests, import the helpers and decorate the class:
   ```python
   from tests.qt_support import requires_qt, get_app

   @requires_qt
   class MyWidgetTests(unittest.TestCase):
       @classmethod
       def setUpClass(cls):
           get_app()          # one shared QApplication
   ```
4. Use `Database(":memory:")` for storage and `tempfile.TemporaryDirectory()` for files.
5. Do not call real Win32 functions in tests. Pass a fake backend to `WindowPinner` instead.

### Troubleshooting
| Symptom | Fix |
|---------|-----|
| `ModuleNotFoundError: No module named 'pinner'` | Run from the project root, not from inside `tests/`. |
| `No module named 'PyQt6'` or UI tests all skipped | `pip install -r requirements-dev.txt` in the active virtual environment. |
| `pytest: command not found` | Activate the venv, or use `python -m pytest`, or the `unittest` command above. |
| `xdg-open: command not found` on Linux (nothing opens) | Install it: `sudo apt install xdg-utils` (Debian/Ubuntu) or `sudo dnf install xdg-utils` (Fedora). |
| Qt platform plugin error on a Linux CI box | Install the system libs (e.g. `libegl1`, `libxkbcommon0`) and keep `QT_QPA_PLATFORM=offscreen`. |
| *Always on Top* tab is disabled | Expected on macOS and Linux (Windows only). On Windows, `pywin32` is missing: run `pip install pywin32`. |
| A test left `pinner.db` in the project root | Tests shouldn't do that. Delete the file and check the new test uses `:memory:`. |

## Configuration

| Environment variable | Purpose | Default |
|----------------------|---------|---------|
| `PINNER_DB` | Path of the SQLite database file | `<project root>/pinner.db` |
| `PINNER_ICON_DIR` | Folder holding the icon files | `<project root>/assets/icons` |

```bash
# example: use a throwaway database while developing
PINNER_DB=/tmp/pinner-dev.db python main.py              # macOS / Linux
$env:PINNER_DB="$env:TEMP\pinner-dev.db"; python main.py   # PowerShell
```

## Contributing checklist
1. Create a branch: `git checkout -b my-change`
2. Make your change and add or update tests.
3. Run `pytest` and make sure nothing fails.
4. For UI or pinning changes, also run `python main.py` and try the feature (pinning other windows needs Windows; if you change opening files or *Show in folder*, try it on macOS / Linux too if you can).
5. Commit, push to your fork, and open a pull request.

## Project layout

```
main.py                     entry point
assets/icons/*.svg          icon files
pinner/
  icon_paths.py             ★ the single file that defines every icon path
  config.py                 database location (<project root>/pinner.db)
  app.py                    QApplication bootstrap
  core/                     Qt-free logic (easy to test)
    models.py               Section / ItemKind / Group / Item + validation (ALLOWED_KINDS: bookmarks = links only)
    database.py             SQLite connection + schema (+ triggers that keep bookmarks links-only)
    repository.py           all CRUD + settings (+ batch() transactions)
    bookmarks.py            browser bookmarks import (HTML/JSON) and export (HTML)
    launcher.py             open folders / files / links per OS
    window_pinner.py        always-on-top + priority list + window snapshots (backend interface)
    dropped.py              dropped file/folder/link -> entry (full path + name; links only for bookmarks)
    bootstrap.py            wiring + first-run folders
  ui/                       PyQt6 widgets
    styles.py  theme.py     system-theme styling (pt units only, palette() colours)
    icons.py  prompts.py  dnd.py  dialogs.py
    section_widget.py       folder/sub-folder/entry tree (both tabs; import/export + links-only on bookmarks)
    window_pinner_panel.py  "Always on Top" tab (window + priority drop-downs)
    main_window.py
tests/                      unittest/pytest suite (see "Running the tests")
  qt_support.py             headless Qt helpers + @requires_qt
pytest.ini                  pytest config (testpaths = tests)
requirements.txt            runtime dependencies
requirements-dev.txt        runtime + pytest
```

### Changing icons
Edit `pinner/icon_paths.py` (or set `PINNER_ICON_DIR` to a folder containing the same file names).
It is the only place icon paths are defined; the guard test fails otherwise.

## License
MIT

## Notes
* The window preview uses `PrintWindow` (needs `pywin32`). Minimised windows cannot be captured, so they show "Preview not available".
* With *Active after the application stop* ticked, windows stay on top after Pinner closes; they can't be managed from Pinner again (window handles change), so close them, or toggle always-on-top in the other app, to undo it.
* Pinner reads bookmark **files** you export from a browser; it does not read a running browser's profile or sync with it. Re-export and re-import to refresh (duplicates are skipped).
* Everything is named `pinner`: the package, the tests' imports, the environment variables (`PINNER_DB`, `PINNER_ICON_DIR`) and the database file (`pinner.db`, created in the project root on first run). Data from earlier versions is not carried over.
* If Pinner is killed (Task Manager / crash) it cannot un-pin windows; use *Pin on Top → Unpin* in another run, or close and re-open the target app.

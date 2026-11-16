# Pinner

A desktop app (Rust + [egui](https://github.com/emilk/egui)) to organise the folders, files, apps and web links you open every day —
grouped in your own folders (e.g. one per customer or project) and stored in SQLite.

## Features

| Area | What you can do |
|------|-----------------|
| **Paths tab** | One tree of your own folders and **sub-folders** (any depth). Inside each, pin **folders, files/apps and web links**. |
| **Browser Bookmarks tab** | Same tree for bookmarks, but **web links only**: bookmark folders (and sub-folders) containing links. Files and folders cannot be added here. |
| **Import / export bookmarks** | **Import…** reads a bookmarks file from Chrome, Edge, Brave, Firefox, Safari, Opera or Vivaldi; **Export…** writes a file any of them can import. See [Bookmarks](#bookmarks-import-export-and-links-only). |
| **Drag & drop** | On the **Paths** tab, drop files, folders or browser links onto the tree (on **Browser Bookmarks** only links are accepted): the **full path including the file name** is stored automatically. Files dropped on the window go into the selected folder; use right-click → *Move to* to move an entry. The Add dialog accepts drops too. |
| **Friendly names** | Every entry has an editable display name (a customer name instead of a raw path). |
| **Icons** | Folder / file / link entries each have their own icon. |
| **Pin to top** | Right-click an entry → *Pin to top of folder* (★). |
| **Search** | Filters the tree by name or location; matching entries keep their folder chain. |
| **Open** | Every entry has a green **Open** button on its row, plus **▶ Open** in the toolbar, **Enter** / double-click, and right-click → *Open* / *Show in folder*. Folders open in the file manager, files with their default program, links in your browser. |
| **Always on Top tab** | Choose a window from a **drop-down**, choose its **priority** from a second drop-down, click *Pin on Top*. Priority 1 stays above all other pinned windows; reorder with ▲/▼. (Windows) |
| **Pins end with the app** | Closing Pinner (or quitting) un-pins every window it pinned **unless** you tick *Active after the application stop* (unchecked by default; the choice is remembered). Windows that were already always-on-top beforehand are left as they were. |
| **About tab** | Version, license and links to the author's GitHub profile and the project repository. |
| **Keep Pinner on top** | Checkbox in the header; remembered between runs (all platforms). |
| **System theme** | Follows your OS light/dark mode and accent colour; no hard-coded colours or fonts. |
| **SQLite storage** | `pinner.db` next to the executable (or the project folder when run with `cargo run`); override with `PINNER_DB`. |

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
| **Always on Top tab** (pin *other* apps' windows) | ✅ | ➖ not available | ➖ not available |

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
* A recent **Rust toolchain** ([rustup.rs](https://rustup.rs)), edition 2021
* **Windows, macOS or Linux.** Everything works on all three except the *Always on Top* tab, which uses the Win32 API
  and is Windows-only. On Linux you also need the usual GUI development libraries (e.g. `libxkbcommon-dev`, `libgtk-3-dev` for file dialogs).
* `git`

### Build and run
```bash
git clone https://github.com/abyshergill/Pinner.git
cd Pinner
cargo run --release
```
On first run Pinner creates **`pinner.db`** with two starter folders ("General" and "Bookmarks").
The file is git-ignored. Delete it to start fresh. SQLite is bundled, so nothing else needs installing.

## Running the tests
```bash
cargo test
```
The tests cover the data model and validation, the SQLite repository (including the links-only trigger and transactions),
bookmark import/export (HTML, Chrome JSON, Firefox JSON), the launcher, dropped-file handling, bootstrap and the window-pinner priority logic
(through a fake backend, so no real window is touched). They use in-memory databases or temporary folders, never your real data.

## Configuration

| Environment variable | Purpose | Default |
|----------------------|---------|---------|
| `PINNER_DB` | Path of the SQLite database file | `pinner.db` next to the executable (project folder under `cargo run`) |

```bash
PINNER_DB=/tmp/pinner-dev.db cargo run              # macOS / Linux
$env:PINNER_DB="$env:TEMP\pinner-dev.db"; cargo run   # PowerShell
```

## Contributing checklist
1. Create a branch: `git checkout -b my-change`
2. Make your change and add or update tests.
3. Run `cargo test` and make sure nothing fails.
4. For UI or pinning changes, also run the app and try the feature (pinning other windows needs Windows).
5. Commit, push to your fork, and open a pull request.

## Project layout

```
Cargo.toml
assets/icons/*.svg          icon artwork
src/
  main.rs                   entry point
  lib.rs                    GUI-free library (everything below is unit-tested)
  models.rs                 Section / ItemKind / Group / Item + validation (bookmarks = links only)
  database.rs               SQLite connection + schema (+ triggers that keep bookmarks links-only)
  repository.rs             all CRUD + settings (+ batch() transactions)
  bookmarks.rs              browser bookmarks import (HTML/JSON) and export (HTML)
  launcher.rs               open folders / files / links per OS
  window_pinner.rs          always-on-top + priority list (Win32 backend / unavailable backend)
  dropped.rs                dropped file/folder/link -> entry (full path + name)
  bootstrap.rs  config.rs   wiring, first-run folders, database location
  ui/                       egui front end
    mod.rs                  window, header, tabs
    section.rs              folder/sub-folder/entry tree (both tabs; import/export + links-only on bookmarks)
    pinner_panel.rs         "Always on Top" tab
```

## License
MIT

## Notes
* This is the Rust rewrite of the original Python/PyQt6 version. Databases created by the Python version use the same schema and open unchanged.
* The live window **preview** of the Python version is not implemented in the Rust version yet.
* With *Active after the application stop* ticked, windows stay on top after Pinner closes; they can't be managed from Pinner again (window handles change), so close them, or toggle always-on-top in the other app, to undo it.
* Pinner reads bookmark **files** you export from a browser; it does not read a running browser's profile or sync with it. Re-export and re-import to refresh (duplicates are skipped).
* If Pinner is killed (Task Manager / crash) it cannot un-pin windows; close and re-open the target app.

"""'Always on Top' for *other* applications' windows (Windows only).

Several windows can be pinned at once.  They are kept in a **priority list**:
priority 1 is displayed above every other pinned window, priority 2 above
priority 3, and so on.  (Windows keeps topmost windows in the order they were
last made topmost, so the list is re-applied lowest-priority first.)

The OS calls live behind a small backend interface so the logic is testable
and the app still starts on macOS / Linux (feature disabled there).
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class WindowInfo:
    hwnd: int
    title: str
    is_topmost: bool = False


@dataclass(frozen=True)
class PinnedWindow:
    hwnd: int
    title: str
    was_topmost: bool = False   # already "always on top" before we pinned it


@dataclass(frozen=True)
class WindowSnapshot:
    """A screenshot of a window: 32-bit pixels in B, G, R, X byte order."""
    width: int
    height: int
    stride: int      # bytes per row
    data: bytes


class WindowPinError(Exception):
    """Raised when a window cannot be pinned/unpinned."""


class WindowBackend(Protocol):
    available: bool
    reason: str

    def list_windows(self) -> list[WindowInfo]: ...
    def set_topmost(self, hwnd: int, topmost: bool) -> None: ...
    def capture(self, hwnd: int) -> WindowSnapshot | None: ...


class UnavailableBackend:
    """Used when the platform / dependencies don't support window pinning."""

    available = False

    def __init__(self, reason: str) -> None:
        self.reason = reason

    def list_windows(self) -> list[WindowInfo]:
        return []

    def set_topmost(self, hwnd: int, topmost: bool) -> None:
        raise WindowPinError(self.reason)

    def capture(self, hwnd: int) -> WindowSnapshot | None:
        return None


class Win32Backend:
    """pywin32 implementation (``pip install pywin32``)."""

    available = True
    reason = ""

    def __init__(self) -> None:
        import win32con  # noqa: WPS433 - imported lazily on purpose
        import win32gui

        self._con = win32con
        self._gui = win32gui

    def list_windows(self) -> list[WindowInfo]:
        found: list[WindowInfo] = []
        gui, con = self._gui, self._con

        def visit(hwnd, _):
            if not gui.IsWindowVisible(hwnd):
                return True
            title = gui.GetWindowText(hwnd).strip()
            if title:
                ex_style = gui.GetWindowLong(hwnd, con.GWL_EXSTYLE)
                found.append(WindowInfo(hwnd, title, bool(ex_style & con.WS_EX_TOPMOST)))
            return True

        gui.EnumWindows(visit, None)
        return found

    def set_topmost(self, hwnd: int, topmost: bool) -> None:
        con = self._con
        flags = con.SWP_NOMOVE | con.SWP_NOSIZE
        z_order = con.HWND_TOPMOST if topmost else con.HWND_NOTOPMOST
        try:
            self._gui.SetWindowPos(hwnd, z_order, 0, 0, 0, 0, flags)
        except Exception as exc:  # pywintypes.error
            raise WindowPinError(f"Failed to modify window state:\n{exc}") from exc


    @staticmethod
    def _print_window(hwnd: int, hdc: int) -> bool:
        """Ask the window to paint itself into ``hdc`` (works even when it is covered).

        Flag 2 = PW_RENDERFULLCONTENT, needed for modern (DWM / Chromium / UWP) windows.
        """
        import ctypes
        return bool(ctypes.windll.user32.PrintWindow(hwnd, hdc, 2))

    def capture(self, hwnd: int) -> WindowSnapshot | None:
        """Screenshot of ``hwnd``; ``None`` if minimised, closed or not capturable."""
        try:
            import win32ui
        except ImportError:
            return None
        gui = self._gui
        try:
            if gui.IsIconic(hwnd):
                return None
            left, top, right, bottom = gui.GetWindowRect(hwnd)
            width, height = right - left, bottom - top
            if width <= 0 or height <= 0:
                return None
            hwnd_dc = gui.GetWindowDC(hwnd)
        except Exception:  # window vanished / access denied
            return None
        mfc_dc = save_dc = bitmap = None
        try:
            mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
            save_dc = mfc_dc.CreateCompatibleDC()
            bitmap = win32ui.CreateBitmap()
            bitmap.CreateCompatibleBitmap(mfc_dc, width, height)
            save_dc.SelectObject(bitmap)
            self._print_window(hwnd, save_dc.GetSafeHdc())
            info = bitmap.GetInfo()
            return WindowSnapshot(info["bmWidth"], info["bmHeight"], info["bmWidthBytes"],
                                  bytes(bitmap.GetBitmapBits(True)))
        except Exception:
            return None
        finally:
            if bitmap is not None:
                gui.DeleteObject(bitmap.GetHandle())
            if save_dc is not None:
                save_dc.DeleteDC()
            if mfc_dc is not None:
                mfc_dc.DeleteDC()
            gui.ReleaseDC(hwnd, hwnd_dc)


def create_backend(platform_name: str | None = None) -> WindowBackend:
    """Pick the right backend for this machine."""
    platform_name = platform_name or sys.platform
    if not platform_name.startswith("win"):
        return UnavailableBackend("Pinning other windows is only supported on Windows.")
    try:
        return Win32Backend()
    except ImportError:
        return UnavailableBackend("Install 'pywin32' to enable pinning other windows.")


class WindowPinner:
    """Window listing plus the ordered (priority) list of pinned windows."""

    def __init__(self, backend: WindowBackend | None = None, own_titles: tuple[str, ...] = ()) -> None:
        self.backend = backend or create_backend()
        self._own_titles = tuple(t.lower() for t in own_titles)
        self._pinned: list[PinnedWindow] = []
        # Off by default: pinned windows are released when the application stops.
        self.keep_pinned_on_exit = False

    @property
    def available(self) -> bool:
        return self.backend.available

    @property
    def reason(self) -> str:
        return self.backend.reason

    @property
    def pinned(self) -> list[PinnedWindow]:
        """Pinned windows, highest priority first (a copy)."""
        return list(self._pinned)

    def priority_of(self, hwnd: int) -> int | None:
        for index, p in enumerate(self._pinned):
            if p.hwnd == hwnd:
                return index + 1
        return None

    # ------------------------------------------------------------ listing
    def list_windows(self, text: str = "") -> list[WindowInfo]:
        """Visible, titled windows (excluding this app), sorted by title."""
        needle = text.strip().lower()
        windows = [
            w for w in self.backend.list_windows()
            if w.title.lower() not in self._own_titles and needle in w.title.lower()
        ]
        return sorted(windows, key=lambda w: (w.title.lower(), w.hwnd))

    def prune(self, open_hwnds: set[int]) -> bool:
        """Forget pinned windows that no longer exist; True if the list changed."""
        kept = [p for p in self._pinned if p.hwnd in open_hwnds]
        changed = len(kept) != len(self._pinned)
        self._pinned = kept
        return changed

    # ---------------------------------------------------------- pin logic
    def pin(self, hwnd: int, title: str = "", priority: int = 1, was_topmost: bool = False) -> None:
        """Pin ``hwnd`` at ``priority`` (1 = highest); re-pinning just re-prioritises."""
        previous = next((p for p in self._pinned if p.hwnd == hwnd), None)
        if previous is not None:          # keep the *original* state across re-pins
            was_topmost = previous.was_topmost
        self._insert(hwnd, title, priority, was_topmost)
        self._apply(must_succeed=hwnd)

    def move(self, hwnd: int, priority: int) -> None:
        """Change the priority of an already pinned window."""
        current = next((p for p in self._pinned if p.hwnd == hwnd), None)
        if current is None:
            raise WindowPinError("That window is not pinned.")
        self._insert(hwnd, current.title, priority, current.was_topmost)
        self._apply(must_succeed=hwnd)

    def unpin(self, hwnd: int) -> None:
        self._pinned = [p for p in self._pinned if p.hwnd != hwnd]
        self.backend.set_topmost(hwnd, False)

    def unpin_all(self) -> None:
        errors = []
        for p in self.pinned:
            try:
                self.unpin(p.hwnd)
            except WindowPinError as exc:  # window may have been closed meanwhile
                errors.append(str(exc))
        if errors:
            raise WindowPinError(errors[0])

    def release_all(self) -> int:
        """Stop pinning everything - call when the application exits.  Never raises.

        Windows that were already "always on top" before we touched them keep
        that state; everything we pinned goes back to normal.  Returns how
        many windows were released.
        """
        pinned, self._pinned = self._pinned, []
        released = 0
        for p in pinned:
            if p.was_topmost:
                continue
            try:
                self.backend.set_topmost(p.hwnd, False)
                released += 1
            except Exception:  # window already closed, access denied, ...
                pass
        return released

    def release_on_exit(self) -> int:
        """Called when the application stops.

        Releases every pinned window - unless the user ticked
        "Active after the application stop", in which case the windows are left
        on top.  Never raises.  Returns how many windows were released.
        """
        if self.keep_pinned_on_exit:
            return 0
        return self.release_all()

    def snapshot(self, hwnd: int) -> WindowSnapshot | None:
        """Preview image of a window, or ``None`` when unavailable."""
        capture = getattr(self.backend, "capture", None)
        if capture is None:
            return None
        try:
            return capture(hwnd)
        except Exception:
            return None

    # ------------------------------------------------------------ helpers
    def _insert(self, hwnd: int, title: str, priority: int, was_topmost: bool = False) -> None:
        self._pinned = [p for p in self._pinned if p.hwnd != hwnd]
        index = max(0, min(int(priority) - 1, len(self._pinned)))
        self._pinned.insert(index, PinnedWindow(hwnd, title, was_topmost))

    def _apply(self, must_succeed: int | None = None) -> None:
        """Re-assert topmost, lowest priority first so priority 1 ends up on top."""
        errors: dict[int, WindowPinError] = {}
        for p in reversed(self._pinned):
            try:
                self.backend.set_topmost(p.hwnd, True)
            except WindowPinError as exc:
                errors[p.hwnd] = exc
        if errors:  # stale windows (closed, access denied) leave the list
            self._pinned = [p for p in self._pinned if p.hwnd not in errors]
        if must_succeed in errors:
            raise errors[must_succeed]

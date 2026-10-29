import sys
import types
import unittest
from unittest import mock

from pinner.core import window_pinner as wp
from pinner.core.window_pinner import (
    UnavailableBackend, WindowInfo, WindowPinError, WindowPinner, WindowSnapshot, create_backend,
)


class FakeBackend:
    available = True
    reason = ""

    def __init__(self, windows):
        self.windows = list(windows)
        self.calls = []

    def list_windows(self):
        return list(self.windows)

    def set_topmost(self, hwnd, topmost):
        self.calls.append((hwnd, topmost))


class WindowPinnerTests(unittest.TestCase):
    def setUp(self):
        self.backend = FakeBackend([
            WindowInfo(3, "Zoom"), WindowInfo(1, "notepad"), WindowInfo(2, "Pinner"),
            WindowInfo(4, "Notes - Chrome", True),
        ])
        self.pinner = WindowPinner(self.backend, own_titles=("Pinner",))

    def test_sorted_case_insensitive_and_hides_own_window(self):
        self.assertEqual([w.title for w in self.pinner.list_windows()],
                         ["notepad", "Notes - Chrome", "Zoom"])

    def test_filter(self):
        self.assertEqual([w.hwnd for w in self.pinner.list_windows("NOTE")], [1, 4])
        self.assertEqual(self.pinner.list_windows("nothing"), [])

    def test_duplicate_titles_kept_distinct_by_handle(self):
        self.backend.windows = [WindowInfo(10, "Same"), WindowInfo(11, "Same")]
        self.assertEqual([w.hwnd for w in self.pinner.list_windows()], [10, 11])

    def test_pin_and_unpin_delegate_by_handle(self):
        self.pinner.pin(11, "Eleven")
        self.pinner.unpin(11)
        self.assertEqual(self.backend.calls, [(11, True), (11, False)])
        self.assertEqual(self.pinner.pinned, [])


class PriorityTests(unittest.TestCase):
    def setUp(self):
        self.backend = FakeBackend([])
        self.pinner = WindowPinner(self.backend)

    def titles(self):
        return [p.title for p in self.pinner.pinned]

    def test_default_priority_is_highest(self):
        self.pinner.pin(1, "A")
        self.pinner.pin(2, "B")  # priority defaults to 1 -> above A
        self.assertEqual(self.titles(), ["B", "A"])

    def test_explicit_priority_positions_window(self):
        self.pinner.pin(1, "A")
        self.pinner.pin(2, "B", priority=2)
        self.pinner.pin(3, "C", priority=2)
        self.assertEqual(self.titles(), ["A", "C", "B"])

    def test_priority_is_clamped(self):
        self.pinner.pin(1, "A")
        self.pinner.pin(2, "B", priority=99)
        self.pinner.pin(3, "C", priority=-5)
        self.assertEqual(self.titles(), ["C", "A", "B"])

    def test_reapplied_lowest_priority_first_so_highest_ends_on_top(self):
        self.pinner.pin(1, "A")
        self.backend.calls.clear()
        self.pinner.pin(2, "B", priority=2)       # order: A, B
        self.assertEqual(self.backend.calls, [(2, True), (1, True)])  # B first, A last = A on top
        self.backend.calls.clear()
        self.pinner.pin(3, "C", priority=1)       # order: C, A, B
        self.assertEqual(self.backend.calls, [(2, True), (1, True), (3, True)])

    def test_repinning_moves_instead_of_duplicating(self):
        self.pinner.pin(1, "A")
        self.pinner.pin(2, "B")
        self.pinner.pin(1, "A", priority=1)
        self.assertEqual(self.titles(), ["A", "B"])

    def test_move_changes_priority(self):
        for h, t in ((1, "A"), (2, "B"), (3, "C")):
            self.pinner.pin(h, t, priority=99)    # A, B, C
        self.pinner.move(3, 1)
        self.assertEqual(self.titles(), ["C", "A", "B"])
        self.assertEqual(self.pinner.priority_of(3), 1)
        self.assertIsNone(self.pinner.priority_of(42))

    def test_move_unpinned_window_errors(self):
        with self.assertRaises(WindowPinError):
            self.pinner.move(5, 1)

    def test_unpin_removes_and_clears_topmost(self):
        self.pinner.pin(1, "A")
        self.pinner.pin(2, "B")
        self.pinner.unpin(1)
        self.assertEqual(self.titles(), ["B"])
        self.assertEqual(self.backend.calls[-1], (1, False))

    def test_unpin_all(self):
        self.pinner.pin(1, "A")
        self.pinner.pin(2, "B")
        self.backend.calls.clear()
        self.pinner.unpin_all()
        self.assertEqual(self.pinner.pinned, [])
        self.assertEqual(sorted(self.backend.calls), [(1, False), (2, False)])

    def test_prune_forgets_closed_windows_without_touching_os(self):
        self.pinner.pin(1, "A")
        self.pinner.pin(2, "B")
        self.backend.calls.clear()
        self.assertTrue(self.pinner.prune({2}))
        self.assertEqual(self.titles(), ["B"])
        self.assertFalse(self.pinner.prune({2}))
        self.assertEqual(self.backend.calls, [])

    def test_failure_on_requested_window_raises_and_drops_it(self):
        class Picky(FakeBackend):
            def set_topmost(self, hwnd, topmost):
                if hwnd == 2:
                    raise WindowPinError("denied")
                super().set_topmost(hwnd, topmost)
        pinner = WindowPinner(Picky([]))
        pinner.pin(1, "A")
        with self.assertRaises(WindowPinError):
            pinner.pin(2, "B")
        self.assertEqual([p.hwnd for p in pinner.pinned], [1])

    def test_stale_other_window_is_dropped_silently(self):
        class Dying(FakeBackend):
            def set_topmost(self, hwnd, topmost):
                if hwnd == 1 and self.calls and self.calls[-1][0] == 1 and getattr(self, "kill", False):
                    raise WindowPinError("gone")
                if hwnd == 1 and getattr(self, "kill", False):
                    raise WindowPinError("gone")
                super().set_topmost(hwnd, topmost)
        backend = Dying([])
        pinner = WindowPinner(backend)
        pinner.pin(1, "A")
        backend.kill = True            # window A closes
        pinner.pin(2, "B")             # re-applying A fails, B succeeds
        self.assertEqual([p.hwnd for p in pinner.pinned], [2])


class BackendSelectionTests(unittest.TestCase):
    def test_non_windows_is_unavailable(self):
        backend = create_backend("linux")
        self.assertIsInstance(backend, UnavailableBackend)
        self.assertFalse(backend.available)
        self.assertEqual(backend.list_windows(), [])
        with self.assertRaises(WindowPinError):
            backend.set_topmost(1, True)

    def test_windows_without_pywin32_is_unavailable(self):
        with mock.patch.dict(sys.modules, {"win32gui": None, "win32con": None}):
            backend = create_backend("win32")
        self.assertFalse(backend.available)
        self.assertIn("pywin32", backend.reason)

    def test_pinner_reports_unavailable(self):
        pinner = WindowPinner(UnavailableBackend("nope"))
        self.assertFalse(pinner.available)
        self.assertEqual(pinner.reason, "nope")


class Win32BackendTests(unittest.TestCase):
    """Exercise the real Win32Backend logic against fake win32 modules."""

    def setUp(self):
        con = types.SimpleNamespace(
            SWP_NOMOVE=2, SWP_NOSIZE=1, HWND_TOPMOST=-1, HWND_NOTOPMOST=-2,
            GWL_EXSTYLE=-20, WS_EX_TOPMOST=8)
        self.wins = {
            1: ("Visible", True, 0),
            2: ("", True, 0),                 # no title -> skipped
            3: ("Hidden", False, 0),          # invisible -> skipped
            4: ("  Topmost  ", True, 8),
        }
        self.set_calls = []
        outer = self

        class Gui:
            @staticmethod
            def EnumWindows(cb, extra):
                for hwnd in outer.wins:
                    cb(hwnd, extra)

            @staticmethod
            def IsWindowVisible(h): return outer.wins[h][1]
            @staticmethod
            def GetWindowText(h): return outer.wins[h][0]
            @staticmethod
            def GetWindowLong(h, idx): return outer.wins[h][2]

            @staticmethod
            def SetWindowPos(*args):
                if outer.fail:
                    raise RuntimeError("access denied")
                outer.set_calls.append(args)

        self.fail = False
        patcher = mock.patch.dict(sys.modules, {"win32con": con, "win32gui": Gui})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.backend = wp.Win32Backend()

    def test_lists_only_visible_titled_windows_with_topmost_flag(self):
        got = {(w.hwnd, w.title, w.is_topmost) for w in self.backend.list_windows()}
        self.assertEqual(got, {(1, "Visible", False), (4, "Topmost", True)})

    def test_set_topmost_uses_correct_flags(self):
        self.backend.set_topmost(1, True)
        self.backend.set_topmost(1, False)
        self.assertEqual(self.set_calls[0], (1, -1, 0, 0, 0, 0, 3))
        self.assertEqual(self.set_calls[1], (1, -2, 0, 0, 0, 0, 3))

    def test_os_failure_becomes_window_pin_error(self):
        self.fail = True
        with self.assertRaises(WindowPinError):
            self.backend.set_topmost(1, True)

    def test_create_backend_on_windows_uses_win32(self):
        self.assertIsInstance(create_backend("win32"), wp.Win32Backend)


class ReleaseTests(unittest.TestCase):
    """Pins must not outlive the application."""

    def setUp(self):
        self.backend = FakeBackend([])
        self.pinner = WindowPinner(self.backend)

    def test_release_all_unpins_every_window_and_clears_list(self):
        self.pinner.pin(1, "A")
        self.pinner.pin(2, "B")
        self.backend.calls.clear()
        self.assertEqual(self.pinner.release_all(), 2)
        self.assertEqual(sorted(self.backend.calls), [(1, False), (2, False)])
        self.assertEqual(self.pinner.pinned, [])

    def test_release_all_with_nothing_pinned_is_a_noop(self):
        self.assertEqual(self.pinner.release_all(), 0)
        self.assertEqual(self.backend.calls, [])

    def test_release_all_is_idempotent(self):
        self.pinner.pin(1, "A")
        self.pinner.release_all()
        self.backend.calls.clear()
        self.assertEqual(self.pinner.release_all(), 0)
        self.assertEqual(self.backend.calls, [])

    def test_release_all_never_raises_even_if_windows_are_gone(self):
        class Gone(FakeBackend):
            def set_topmost(self, hwnd, topmost):
                if not topmost:
                    raise WindowPinError("window closed")
                super().set_topmost(hwnd, topmost)
        pinner = WindowPinner(Gone([]))
        pinner.pin(1, "A")
        pinner.pin(2, "B")
        self.assertEqual(pinner.release_all(), 0)      # nothing raised
        self.assertEqual(pinner.pinned, [])

    def test_windows_that_were_already_topmost_keep_their_state(self):
        self.pinner.pin(1, "Already top", was_topmost=True)
        self.pinner.pin(2, "Ours")
        self.backend.calls.clear()
        self.assertEqual(self.pinner.release_all(), 1)
        self.assertEqual(self.backend.calls, [(2, False)])

    def test_repinning_keeps_original_topmost_state(self):
        self.pinner.pin(1, "A", was_topmost=True)
        self.pinner.pin(1, "A", priority=1, was_topmost=False)   # e.g. refreshed list
        self.assertTrue(self.pinner.pinned[0].was_topmost)
        self.pinner.move(1, 1)
        self.assertTrue(self.pinner.pinned[0].was_topmost)

    def test_explicit_unpin_always_clears_topmost(self):
        self.pinner.pin(1, "A", was_topmost=True)
        self.backend.calls.clear()
        self.pinner.unpin(1)
        self.assertEqual(self.backend.calls, [(1, False)])


class KeepAfterExitTests(unittest.TestCase):
    """The 'Active after the application stop' option."""

    def setUp(self):
        self.backend = FakeBackend([])
        self.pinner = WindowPinner(self.backend)
        self.pinner.pin(1, "A")
        self.pinner.pin(2, "B")
        self.backend.calls.clear()

    def test_default_is_off_so_pins_end_with_the_app(self):
        self.assertFalse(self.pinner.keep_pinned_on_exit)
        self.assertEqual(self.pinner.release_on_exit(), 2)
        self.assertEqual(sorted(self.backend.calls), [(1, False), (2, False)])

    def test_when_on_windows_are_left_pinned(self):
        self.pinner.keep_pinned_on_exit = True
        self.assertEqual(self.pinner.release_on_exit(), 0)
        self.assertEqual(self.backend.calls, [])          # OS never asked to unpin
        self.assertEqual(len(self.pinner.pinned), 2)

    def test_toggling_back_off_releases_again(self):
        self.pinner.keep_pinned_on_exit = True
        self.pinner.keep_pinned_on_exit = False
        self.assertEqual(self.pinner.release_on_exit(), 2)

    def test_explicit_unpin_and_release_all_ignore_the_option(self):
        self.pinner.keep_pinned_on_exit = True
        self.pinner.unpin(1)
        self.assertEqual(self.backend.calls, [(1, False)])
        self.assertEqual(self.pinner.release_all(), 1)


class SnapshotTests(unittest.TestCase):
    def test_delegates_to_backend_capture(self):
        snap = WindowSnapshot(2, 1, 8, b"\x00" * 8)

        class Cap(FakeBackend):
            def capture(self, hwnd):
                return snap if hwnd == 1 else None
        pinner = WindowPinner(Cap([]))
        self.assertIs(pinner.snapshot(1), snap)
        self.assertIsNone(pinner.snapshot(2))

    def test_backend_without_capture_or_failing_capture_gives_none(self):
        self.assertIsNone(WindowPinner(FakeBackend([])).snapshot(1))

        class Boom(FakeBackend):
            def capture(self, hwnd):
                raise RuntimeError("boom")
        self.assertIsNone(WindowPinner(Boom([])).snapshot(1))

    def test_unavailable_backend_has_no_preview(self):
        self.assertIsNone(WindowPinner(UnavailableBackend("x")).snapshot(1))


class Win32CaptureTests(unittest.TestCase):
    """Win32Backend.capture() against fake win32gui / win32ui."""

    def setUp(self):
        self.log = []
        self.iconic = False
        self.rect = (10, 20, 14, 22)        # 4 x 2 px
        outer = self

        con = types.SimpleNamespace(GWL_EXSTYLE=-20, WS_EX_TOPMOST=8, SWP_NOMOVE=2, SWP_NOSIZE=1,
                                    HWND_TOPMOST=-1, HWND_NOTOPMOST=-2)

        class Gui:
            @staticmethod
            def IsIconic(h): return outer.iconic
            @staticmethod
            def GetWindowRect(h): return outer.rect
            @staticmethod
            def GetWindowDC(h): outer.log.append("getdc"); return 111
            @staticmethod
            def ReleaseDC(h, dc): outer.log.append("releasedc")
            @staticmethod
            def DeleteObject(o): outer.log.append("deleteobj")

        class Dc:
            def CreateCompatibleDC(self): return Dc()
            def SelectObject(self, b): pass
            def GetSafeHdc(self): return 222
            def DeleteDC(self): outer.log.append("deletedc")

        class Bmp:
            def CreateCompatibleBitmap(self, dc, w, h): outer.size = (w, h)
            def GetInfo(self): return {"bmWidth": outer.size[0], "bmHeight": outer.size[1],
                                       "bmWidthBytes": outer.size[0] * 4}
            def GetBitmapBits(self, as_bytes): return b"\x01\x02\x03\x00" * (outer.size[0] * outer.size[1])
            def GetHandle(self): return 333

        ui = types.SimpleNamespace(CreateDCFromHandle=lambda h: Dc(), CreateBitmap=lambda: Bmp())
        patcher = mock.patch.dict(sys.modules, {"win32con": con, "win32gui": Gui, "win32ui": ui})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.backend = wp.Win32Backend()
        self.printed = []
        self.backend._print_window = lambda hwnd, hdc: self.printed.append((hwnd, hdc)) or True

    def test_capture_returns_pixels_and_geometry(self):
        snap = self.backend.capture(5)
        self.assertEqual((snap.width, snap.height, snap.stride), (4, 2, 16))
        self.assertEqual(len(snap.data), 4 * 2 * 4)
        self.assertEqual(self.printed, [(5, 222)])

    def test_gdi_resources_are_always_released(self):
        self.backend.capture(5)
        self.assertEqual(sorted(self.log), sorted(["getdc", "releasedc", "deleteobj", "deletedc", "deletedc"]))

    def test_minimised_window_has_no_preview(self):
        self.iconic = True
        self.assertIsNone(self.backend.capture(5))
        self.assertEqual(self.printed, [])

    def test_zero_size_window_has_no_preview(self):
        self.rect = (0, 0, 0, 0)
        self.assertIsNone(self.backend.capture(5))

    def test_failure_while_painting_returns_none_and_still_releases(self):
        def boom(hwnd, hdc): raise OSError("denied")
        self.backend._print_window = boom
        self.assertIsNone(self.backend.capture(5))
        self.assertIn("releasedc", self.log)
        self.assertIn("deleteobj", self.log)

    def test_missing_win32ui_returns_none(self):
        with mock.patch.dict(sys.modules, {"win32ui": None}):
            self.assertIsNone(self.backend.capture(5))


if __name__ == "__main__":
    unittest.main()

import unittest
from unittest import mock

from tests.qt_support import get_app, requires_qt

from pinner.core.database import Database
from pinner.core.models import Section
from pinner.core.repository import Repository
from pinner.core.window_pinner import (
    UnavailableBackend, WindowInfo, WindowPinError, WindowPinner, WindowSnapshot,
)


class FakeBackend:
    available = True
    reason = ""

    def __init__(self):
        self.windows = [WindowInfo(1, "Notepad"), WindowInfo(2, "Calc", True), WindowInfo(3, "Pinner")]
        self.calls = []
        self.fail = False

    def list_windows(self):
        return list(self.windows)

    def set_topmost(self, hwnd, topmost):
        if self.fail:
            raise WindowPinError("denied")
        self.calls.append((hwnd, topmost))

    def capture(self, hwnd):
        if hwnd == 1:   # Notepad: a 4x2 solid red image (B,G,R,X)
            return WindowSnapshot(4, 2, 16, bytes([0, 0, 255, 0]) * 8)
        return None     # everything else: minimised / protected


@requires_qt
class MainWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        get_app()

    def setUp(self):
        from pinner.core.bootstrap import ensure_default_folders
        from pinner.ui.main_window import MainWindow
        self.db = Database(":memory:")
        self.repo = Repository(self.db)
        ensure_default_folders(self.repo)
        self.backend = FakeBackend()
        self.pinner = WindowPinner(self.backend, own_titles=("Pinner",))
        self.win = MainWindow(self.repo, launcher=mock.Mock(), pinner=self.pinner)

    def tearDown(self):
        self.win.close()
        self.win.deleteLater()
        self.db.close()

    def test_three_tabs(self):
        self.assertEqual([self.win.tabs.tabText(i) for i in range(3)],
                         ["Paths", "Browser Bookmarks", "Always on Top"])

    def test_default_folders_visible_in_each_section_tab(self):
        self.assertEqual(self.win.paths_tab.tree.topLevelItem(0).text(0), "General")
        self.assertEqual(self.win.browser_tab.tree.topLevelItem(0).text(0), "Bookmarks")

    def test_window_icon_set_from_icon_paths(self):
        self.assertFalse(self.win.windowIcon().isNull())

    def test_stay_on_top_toggle_sets_flag_and_persists(self):
        self.assertFalse(self.win.is_stay_on_top())
        self.win.on_top_check.setChecked(True)
        self.assertTrue(self.win.is_stay_on_top())
        self.assertTrue(self.repo.get_bool("self_always_on_top"))
        self.win.on_top_check.setChecked(False)
        self.assertFalse(self.win.is_stay_on_top())
        self.assertFalse(self.repo.get_bool("self_always_on_top"))

    def test_stay_on_top_restored_on_next_start(self):
        from pinner.ui.main_window import MainWindow
        self.repo.set_bool("self_always_on_top", True)
        other = MainWindow(self.repo, launcher=mock.Mock(), pinner=self.pinner)
        self.assertTrue(other.on_top_check.isChecked())
        self.assertTrue(other.is_stay_on_top())
        other.deleteLater()

    # ------------------------------------------------------ window pinner
    def combo_titles(self):
        c = self.win.pinner_tab.window_combo
        return [c.itemText(i) for i in range(c.count())]

    def select_window(self, hwnd):
        c = self.win.pinner_tab.window_combo
        c.setCurrentIndex(c.findData(hwnd))

    def test_window_dropdown_lists_windows_excluding_self_and_marks_topmost(self):
        self.assertEqual(self.combo_titles(), ["📌 Calc", "Notepad"])

    def test_priority_dropdown_grows_with_pinned_windows(self):
        panel = self.win.pinner_tab
        self.assertEqual([panel.priority_combo.itemData(i) for i in range(panel.priority_combo.count())], [1])
        self.select_window(1)
        panel.pin_selected()
        self.assertEqual(panel.priority_combo.count(), 2)
        self.assertIn("highest", panel.priority_combo.itemText(0))

    def test_pin_uses_chosen_priority(self):
        panel = self.win.pinner_tab
        self.select_window(1)
        panel.pin_selected()                       # Notepad -> 1
        self.select_window(2)
        panel.priority_combo.setCurrentIndex(panel.priority_combo.findData(2))
        panel.pin_selected()                       # Calc -> 2
        rows = [panel.pinned_list.item(i).text() for i in range(panel.pinned_list.count())]
        self.assertEqual(rows, ["1.  Notepad", "2.  Calc"])
        self.assertEqual([p.hwnd for p in self.pinner.pinned], [1, 2])

    def test_default_priority_puts_new_pin_on_top(self):
        panel = self.win.pinner_tab
        self.select_window(1)
        panel.pin_selected()
        self.select_window(2)
        panel.pin_selected()
        self.assertEqual([p.hwnd for p in self.pinner.pinned], [2, 1])
        # lowest priority applied first, highest last
        self.assertEqual(self.backend.calls[-2:], [(1, True), (2, True)])

    def test_raise_and_lower_change_priority(self):
        panel = self.win.pinner_tab
        for h in (1, 2):
            self.select_window(h)
            panel.priority_combo.setCurrentIndex(panel.priority_combo.count() - 1)  # lowest
            panel.pin_selected()                    # order: 1, 2
        panel.pinned_list.setCurrentRow(1)          # window 2
        panel.btn_raise.click()
        self.assertEqual([p.hwnd for p in self.pinner.pinned], [2, 1])
        panel.btn_lower.click()
        self.assertEqual([p.hwnd for p in self.pinner.pinned], [1, 2])
        self.assertEqual(panel.selected_pinned_hwnd(), 2)    # selection follows the window

    def test_unpin_selected_and_unpin_all(self):
        panel = self.win.pinner_tab
        for h in (1, 2):
            self.select_window(h)
            panel.pin_selected()
        panel.pinned_list.setCurrentRow(0)
        panel.btn_unpin.click()
        self.assertEqual(len(self.pinner.pinned), 1)
        panel.btn_unpin_all.click()
        self.assertEqual(self.pinner.pinned, [])
        self.assertEqual(panel.pinned_list.count(), 0)
        self.assertEqual(panel.priority_combo.count(), 1)

    def test_closed_windows_are_dropped_from_priority_list_on_refresh(self):
        panel = self.win.pinner_tab
        self.select_window(1)
        panel.pin_selected()
        self.backend.windows = [w for w in self.backend.windows if w.hwnd != 1]
        panel.load_windows()
        self.assertEqual(panel.pinned_list.count(), 0)

    def test_pin_without_selection_warns(self):
        from pinner.ui import prompts
        self.backend.windows = []
        self.win.pinner_tab.load_windows()
        with mock.patch.object(prompts, "show_warning") as warn:
            self.win.pinner_tab.pin_selected()
        warn.assert_called_once()
        self.assertEqual(self.backend.calls, [])

    def test_pin_failure_is_reported(self):
        from pinner.ui import prompts
        self.backend.fail = True
        with mock.patch.object(prompts, "show_error") as err:
            self.win.pinner_tab.pin_selected()
        err.assert_called_once()
        self.assertEqual(self.win.pinner_tab.pinned_list.count(), 0)


    # ------------------------------------------ "Active after the application stop"
    def test_app_is_named_pinner(self):
        from pinner import APP_NAME
        self.assertEqual(APP_NAME, "Pinner")
        self.assertEqual(self.win.windowTitle(), "Pinner")
        self.assertIn("Pinner", self.win.on_top_check.text())

    def test_keep_after_exit_checkbox_exists_and_is_unchecked_by_default(self):
        box = self.win.pinner_tab.keep_after_exit_check
        self.assertEqual(box.text(), "Active after the application stop")
        self.assertFalse(box.isChecked())
        self.assertFalse(self.pinner.keep_pinned_on_exit)
        self.assertFalse(self.repo.get_bool("keep_pins_after_exit"))

    def test_unchecked_close_unpins(self):
        self.select_window(1)
        self.win.pinner_tab.pin_selected()
        self.backend.calls.clear()
        self.win.close()
        self.assertEqual(self.backend.calls, [(1, False)])

    def test_checked_close_leaves_windows_pinned(self):
        self.win.pinner_tab.keep_after_exit_check.setChecked(True)
        self.assertTrue(self.pinner.keep_pinned_on_exit)
        self.select_window(1)
        self.win.pinner_tab.pin_selected()
        self.backend.calls.clear()
        self.win.close()
        self.assertEqual(self.backend.calls, [])           # nothing un-pinned

    def test_checked_app_quit_also_leaves_windows_pinned(self):
        from PyQt6.QtWidgets import QApplication
        self.win.pinner_tab.keep_after_exit_check.setChecked(True)
        self.select_window(1)
        self.win.pinner_tab.pin_selected()
        self.backend.calls.clear()
        QApplication.instance().aboutToQuit.emit()
        self.assertEqual(self.backend.calls, [])

    def test_unchecking_again_restores_release_on_close(self):
        box = self.win.pinner_tab.keep_after_exit_check
        box.setChecked(True)
        box.setChecked(False)
        self.select_window(1)
        self.win.pinner_tab.pin_selected()
        self.backend.calls.clear()
        self.win.close()
        self.assertEqual(self.backend.calls, [(1, False)])

    def test_choice_is_remembered_for_next_start(self):
        from pinner.ui.main_window import MainWindow
        self.win.pinner_tab.keep_after_exit_check.setChecked(True)
        self.assertTrue(self.repo.get_bool("keep_pins_after_exit"))
        pinner2 = WindowPinner(FakeBackend([]))
        other = MainWindow(self.repo, launcher=mock.Mock(), pinner=pinner2)
        self.assertTrue(other.pinner_tab.keep_after_exit_check.isChecked())
        self.assertTrue(pinner2.keep_pinned_on_exit)
        other.deleteLater()

    def test_checkbox_disabled_when_pinning_is_unavailable(self):
        from pinner.ui.main_window import MainWindow
        w = MainWindow(self.repo, launcher=mock.Mock(), pinner=WindowPinner(UnavailableBackend("x")))
        self.assertFalse(w.pinner_tab.keep_after_exit_check.isEnabled())
        w.deleteLater()

    # ------------------------------------------------- unpin on close / quit
    def test_closing_the_window_unpins_everything_we_pinned(self):
        panel = self.win.pinner_tab
        for h in (1, 2):
            self.select_window(h)
            panel.pin_selected()
        self.backend.calls.clear()
        self.win.close()
        self.assertEqual(sorted(self.backend.calls), [(1, False), (2, False)])
        self.assertEqual(self.pinner.pinned, [])

    def test_app_quit_also_releases_pins(self):
        from PyQt6.QtWidgets import QApplication
        self.select_window(1)
        self.win.pinner_tab.pin_selected()
        self.backend.calls.clear()
        QApplication.instance().aboutToQuit.emit()
        self.assertEqual(self.backend.calls, [(1, False)])

    def test_close_with_nothing_pinned_is_quiet(self):
        self.backend.calls.clear()
        self.win.close()
        self.assertEqual(self.backend.calls, [])

    def test_windows_already_topmost_are_left_alone_on_close(self):
        self.select_window(2)                      # Calc is already 📌 topmost
        self.win.pinner_tab.pin_selected()
        self.backend.calls.clear()
        self.win.close()
        self.assertEqual(self.backend.calls, [])

    def test_close_survives_pin_errors(self):
        self.select_window(1)
        self.win.pinner_tab.pin_selected()
        self.backend.fail = True
        self.win.close()                           # must not raise
        self.assertEqual(self.pinner.pinned, [])

    # ------------------------------------------------------------- preview
    def test_selecting_a_window_shows_its_preview(self):
        panel = self.win.pinner_tab
        self.select_window(1)
        self.assertTrue(panel.show_preview(panel.selected_hwnd()))
        self.assertFalse(panel.preview_label.pixmap().isNull())
        self.assertIn("Notepad", panel.preview_caption.text())
        self.assertIn("4×2", panel.preview_caption.text())

    def test_preview_unavailable_shows_message(self):
        panel = self.win.pinner_tab
        self.select_window(2)
        self.assertFalse(panel.show_preview(2))
        self.assertTrue(panel.preview_label.pixmap().isNull())
        self.assertIn("not available", panel.preview_label.text())

    def test_changing_selection_schedules_a_debounced_preview(self):
        panel = self.win.pinner_tab
        self.select_window(2)
        self.select_window(1)
        self.assertTrue(panel._preview_timer.isActive())
        self.assertEqual(panel._pending_preview, 1)

    def test_selecting_in_pinned_list_previews_that_window(self):
        panel = self.win.pinner_tab
        self.select_window(1)
        panel.pin_selected()
        panel.pinned_list.setCurrentRow(0)
        self.assertEqual(panel._pending_preview, 1)

    def test_no_selection_clears_preview(self):
        panel = self.win.pinner_tab
        panel.show_preview(1)
        panel.show_preview(None)
        self.assertTrue(panel.preview_label.pixmap().isNull())
        self.assertIn("Select a window", panel.preview_label.text())

    def test_unavailable_backend_disables_panel(self):
        from pinner.ui.main_window import MainWindow
        w = MainWindow(self.repo, launcher=mock.Mock(),
                       pinner=WindowPinner(UnavailableBackend("Only on Windows")))
        self.assertFalse(w.pinner_tab.btn_pin.isEnabled())
        self.assertFalse(w.pinner_tab.window_combo.isEnabled())
        self.assertEqual(w.pinner_tab.status_label.text(), "Only on Windows")
        w.deleteLater()

    def test_sections_are_wired_to_correct_section(self):
        self.assertEqual(self.win.paths_tab.section, Section.PATHS)
        self.assertEqual(self.win.browser_tab.section, Section.BROWSER)


if __name__ == "__main__":
    unittest.main()

import os
import tempfile
import unittest
from unittest import mock

from tests.qt_support import get_app, requires_qt

from pinner.core.database import Database
from pinner.core.launcher import LaunchError
from pinner.core.models import ItemKind, Section
from pinner.core.repository import Repository


@requires_qt
class SectionWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        get_app()

    def setUp(self):
        from pinner.ui import prompts
        from pinner.ui.icons import IconProvider
        from pinner.ui.section_widget import SectionWidget

        self.prompts = prompts
        self.db = Database(":memory:")
        self.repo = Repository(self.db)
        self.launcher = mock.Mock()
        self.widget = SectionWidget(Section.PATHS, self.repo, self.launcher, IconProvider())
        for name in ("show_warning", "show_error"):
            p = mock.patch.object(prompts, name)
            setattr(self, name, p.start())
            self.addCleanup(p.stop)

    def tearDown(self):
        self.widget.deleteLater()
        self.db.close()

    # helpers
    def top_names(self):
        t = self.widget.tree
        return [t.topLevelItem(i).text(0) for i in range(t.topLevelItemCount())]

    def node(self, kind, ident):
        return self.widget._nodes[(kind, ident)]

    # ------------------------------------------------------------ folders
    def test_starts_empty_with_actions_disabled(self):
        self.assertEqual(self.widget.tree.topLevelItemCount(), 0)
        self.assertFalse(self.widget.add_btn.isEnabled())
        self.assertFalse(self.widget.new_subfolder_btn.isEnabled())
        self.assertTrue(self.widget.new_folder_btn.isEnabled())

    def test_new_folder_listed_and_selected(self):
        g = self.widget.add_group("Acme")
        self.assertEqual(self.top_names(), ["Acme"])
        self.assertEqual(self.widget.current_group_id(), g.id)
        self.assertTrue(self.widget.add_btn.isEnabled())
        self.assertTrue(self.widget.new_subfolder_btn.isEnabled())

    def test_prompt_cancel_creates_nothing(self):
        with mock.patch.object(self.prompts, "ask_text", return_value=None):
            self.assertIsNone(self.widget.add_group())
        self.assertEqual(self.repo.list_groups(Section.PATHS), [])

    def test_duplicate_folder_warns(self):
        self.widget.add_group("Acme")
        self.assertIsNone(self.widget.add_group("acme"))
        self.show_warning.assert_called_once()

    def test_subfolders_nest_to_any_depth(self):
        a = self.widget.add_group("A")
        b = self.widget.add_subgroup("B")
        c = self.widget.add_subgroup("C")
        self.assertEqual(self.top_names(), ["A"])
        self.assertEqual(self.node(GROUP, a.id).child(0).text(0), "B")
        self.assertEqual(self.node(GROUP, b.id).child(0).text(0), "C")
        self.assertEqual(self.widget.group_path(c.id), "A / B / C")
        self.assertEqual(self.widget.current_group_id(), c.id)

    def test_new_top_level_folder_even_when_a_folder_is_selected(self):
        self.widget.add_group("A")
        self.widget.add_group("B")
        self.assertEqual(self.top_names(), ["A", "B"])

    def test_subfolder_button_without_selection_warns(self):
        self.assertIsNone(self.widget.add_subgroup("X"))
        self.show_warning.assert_called_once()

    def test_rename_and_delete_folder(self):
        g = self.widget.add_group("Old")
        self.widget.rename_group("New")
        self.assertEqual(self.repo.get_group(g.id).name, "New")
        self.widget.delete_group(confirmed=False)
        self.assertEqual(len(self.repo.list_groups(Section.PATHS)), 1)
        self.widget.delete_group(confirmed=True)
        self.assertEqual(self.repo.list_groups(Section.PATHS), [])
        self.assertEqual(self.widget.tree.topLevelItemCount(), 0)

    def test_delete_folder_removes_subfolders_and_entries(self):
        a = self.widget.add_group("A")
        self.widget.add_subgroup("B")
        self.widget.add_item(values=(ItemKind.FOLDER, "x", "/x"))
        self.widget.select_group(a.id)
        self.widget.delete_group(confirmed=True)
        self.assertEqual(self.repo.list_section_items(Section.PATHS), [])

    # ------------------------------------------------------------ entries
    def test_entries_of_every_kind_appear_inside_their_folder(self):
        g = self.widget.add_group("Acme")
        self.widget.add_item(values=(ItemKind.FOLDER, "Assets", "/a"))
        self.widget.add_item(values=(ItemKind.FILE, "Tool", "/t"))
        self.widget.add_item(values=(ItemKind.URL, "Portal", "https://p.example.com"))
        parent = self.node(GROUP, g.id)
        self.assertEqual(parent.childCount(), 3)
        by_name = {parent.child(i).text(0): parent.child(i) for i in range(3)}
        self.assertEqual(by_name["Assets"].text(1), "/a")
        self.assertEqual(by_name["Portal"].text(1), "https://p.example.com")
        self.assertFalse(by_name["Portal"].icon(0).isNull())

    def test_entries_can_live_in_subfolders(self):
        self.widget.add_group("A")
        sub = self.widget.add_subgroup("Sub")
        item = self.widget.add_item(values=(ItemKind.URL, "deep", "example.com"))
        self.assertEqual(item.group_id, sub.id)
        self.assertIs(self.node("item", item.id).parent(), self.node(GROUP, sub.id))

    def test_adding_while_entry_selected_goes_to_its_folder(self):
        g = self.widget.add_group("A")
        first = self.widget.add_item(values=(ItemKind.FOLDER, "one", "/1"))
        self.assertEqual(self.widget.current_key(), ("item", first.id))
        second = self.widget.add_item(values=(ItemKind.FOLDER, "two", "/2"))
        self.assertEqual(second.group_id, g.id)

    def test_add_without_folder_warns(self):
        self.assertIsNone(self.widget.add_item(values=(ItemKind.FOLDER, "x", "/x")))
        self.show_warning.assert_called_once()

    def test_invalid_entry_warns_and_is_not_saved(self):
        self.widget.add_group("A")
        self.assertIsNone(self.widget.add_item(values=(ItemKind.URL, "bad", "ssh://host")))
        self.show_warning.assert_called_once()
        self.assertEqual(self.repo.list_section_items(Section.PATHS), [])

    def test_edit_changes_display_name_only(self):
        self.widget.add_group("A")
        item = self.widget.add_item(values=(ItemKind.FOLDER, "old", "/p"))
        self.widget.edit_selected(values=(ItemKind.FOLDER, "Customer X", "/p"))
        got = self.repo.get_item(item.id)
        self.assertEqual((got.name, got.target), ("Customer X", "/p"))

    def test_pin_marks_entry_and_sorts_first(self):
        g = self.widget.add_group("A")
        self.widget.add_item(values=(ItemKind.FOLDER, "a", "/a"))
        z = self.widget.add_item(values=(ItemKind.FOLDER, "z", "/z"))
        self.widget.toggle_pin_selected()
        parent = self.node(GROUP, g.id)
        self.assertEqual(parent.child(0).text(0), "★ z")
        self.widget.toggle_pin_selected()
        self.assertEqual(parent.child(0).text(0), "a")
        self.assertFalse(self.repo.get_item(z.id).is_pinned)

    def test_delete_entry(self):
        self.widget.add_group("A")
        self.widget.add_item(values=(ItemKind.FOLDER, "a", "/a"))
        self.widget.delete_selected(confirmed=False)
        self.assertEqual(len(self.repo.list_section_items(Section.PATHS)), 1)
        self.widget.delete_selected(confirmed=True)
        self.assertEqual(self.repo.list_section_items(Section.PATHS), [])

    def test_move_entry_to_other_folder(self):
        a = self.widget.add_group("A")
        b = self.widget.add_group("B")
        item = self.widget.add_item(values=(ItemKind.FOLDER, "x", "/x"))   # in B
        self.widget.move_selected(a.id)
        self.assertEqual(self.repo.get_item(item.id).group_id, a.id)
        self.assertEqual(self.repo.list_items(b.id), [])

    def test_open_entry_calls_launcher_and_reports_errors(self):
        self.widget.add_group("A")
        self.widget.add_item(values=(ItemKind.URL, "site", "example.com"))
        self.widget.open_selected()
        self.assertEqual(self.launcher.open_item.call_args.args[0].target, "https://example.com")
        self.launcher.open_item.side_effect = LaunchError("nope")
        self.widget.open_selected()
        self.show_error.assert_called_once_with(self.widget, "nope")

    def test_open_on_a_folder_does_nothing(self):
        self.widget.add_group("A")
        self.widget.open_selected()
        self.launcher.open_item.assert_not_called()

    # --------------------------------------------------------------- drag
    def test_dropped_file_gets_full_path_with_file_name(self):
        g = self.widget.add_group("Drops")
        with tempfile.TemporaryDirectory() as tmp:
            f = os.path.join(tmp, "spec sheet.xlsx")
            open(f, "w").close()
            self.widget.tree.sources_dropped.emit([f, tmp], g.id)
            items = {i.name: i for i in self.repo.list_items(g.id)}
        self.assertEqual(items["spec sheet.xlsx"].target, f)
        self.assertEqual(items["spec sheet.xlsx"].kind, ItemKind.FILE)
        self.assertEqual(items[os.path.basename(tmp)].kind, ItemKind.FOLDER)
        self.assertIn("Added 2", self.widget.status_label.text())

    def test_drop_without_target_uses_selected_folder(self):
        self.widget.add_group("A")
        b = self.widget.add_group("B")
        self.widget.tree.sources_dropped.emit(["https://example.com/x"], None)
        [item] = self.repo.list_items(b.id)
        self.assertEqual(item.kind, ItemKind.URL)

    def test_drop_with_nothing_selected_warns(self):
        self.widget.tree.sources_dropped.emit(["https://example.com"], None)
        self.show_warning.assert_called_once()

    def test_drop_of_missing_path_reports_failure(self):
        g = self.widget.add_group("A")
        self.widget.tree.sources_dropped.emit(["/definitely/not/here"], g.id)
        self.show_warning.assert_called_once()
        self.assertEqual(self.repo.list_items(g.id), [])

    def test_dragging_entry_onto_folder_moves_it(self):
        a = self.widget.add_group("A")
        self.widget.add_group("B")
        item = self.widget.add_item(values=(ItemKind.FOLDER, "x", "/x"))
        self.widget.tree.item_moved.emit(item.id, a.id)
        self.assertEqual(self.repo.get_item(item.id).group_id, a.id)


    # ------------------------------------------------------- open actions
    def test_every_entry_row_has_a_visible_open_button(self):
        self.widget.add_group("A")
        a = self.widget.add_item(values=(ItemKind.FOLDER, "Assets", "/a"))
        b = self.widget.add_item(values=(ItemKind.FILE, "Doc", "/d.pdf"))
        c = self.widget.add_item(values=(ItemKind.URL, "Site", "example.com"))
        for item in (a, b, c):
            btn = self.widget.tree.itemWidget(self.node("item", item.id), 2)
            self.assertIsNotNone(btn)
            self.assertEqual(btn.text(), "Open")
        # folders (groups) have no Open button
        self.assertIsNone(self.widget.tree.itemWidget(self.widget.tree.topLevelItem(0), 2))

    def test_row_open_button_opens_that_entry_even_if_not_selected(self):
        self.widget.add_group("A")
        first = self.widget.add_item(values=(ItemKind.FOLDER, "one", "/one"))
        self.widget.add_item(values=(ItemKind.FILE, "two", "/two"))        # now selected
        self.widget.tree.itemWidget(self.node("item", first.id), 2).click()
        self.assertEqual(self.launcher.open_item.call_args.args[0].id, first.id)
        self.assertIn("Opened one", self.widget.status_label.text())

    def test_toolbar_open_button_enabled_only_for_entries(self):
        self.assertFalse(self.widget.open_btn.isEnabled())
        g = self.widget.add_group("A")
        self.assertFalse(self.widget.open_btn.isEnabled())                  # folder selected
        self.widget.add_item(values=(ItemKind.FOLDER, "one", "/one"))
        self.assertTrue(self.widget.open_btn.isEnabled())                   # entry selected
        self.widget.select_group(g.id)
        self.assertFalse(self.widget.open_btn.isEnabled())

    def test_toolbar_open_button_opens_selected_entry(self):
        self.widget.add_group("A")
        self.widget.add_item(values=(ItemKind.FILE, "Doc", "/d.pdf"))
        self.widget.open_btn.click()
        self.assertEqual(self.launcher.open_item.call_args.args[0].target, "/d.pdf")

    def test_enter_key_opens_selected_entry(self):
        self.widget.add_group("A")
        self.widget.add_item(values=(ItemKind.FOLDER, "one", "/one"))
        self.widget.tree.enter_pressed.emit()
        self.launcher.open_item.assert_called_once()

    def test_open_failure_shows_error(self):
        self.widget.add_group("A")
        item = self.widget.add_item(values=(ItemKind.FOLDER, "gone", "/gone"))
        self.launcher.open_item.side_effect = LaunchError("Folder not found:\n/gone")
        self.assertFalse(self.widget.open_item(item.id))
        self.show_error.assert_called_once()

    def test_open_on_folder_node_toggles_expansion(self):
        g = self.widget.add_group("A")
        self.widget.add_item(values=(ItemKind.FOLDER, "one", "/one"))
        self.widget.select_group(g.id)
        node = self.node(GROUP, g.id)
        self.assertTrue(node.isExpanded())
        self.widget.open_selected()
        self.assertFalse(node.isExpanded())
        self.widget.open_selected()
        self.assertTrue(node.isExpanded())
        self.launcher.open_item.assert_not_called()

    def test_show_in_folder_reveals_files_but_not_links(self):
        self.widget.add_group("A")
        self.widget.add_item(values=(ItemKind.FILE, "Doc", "/x/d.pdf"))
        self.widget.reveal_selected()
        self.launcher.reveal.assert_called_once_with("/x/d.pdf")
        self.launcher.reveal.reset_mock()
        self.widget.add_item(values=(ItemKind.URL, "Site", "example.com"))
        self.widget.reveal_selected()
        self.launcher.reveal.assert_not_called()

    def test_open_item_for_deleted_entry_is_harmless(self):
        self.assertFalse(self.widget.open_item(9999))

    # ------------------------------------------------------------- search
    def test_search_shows_matching_entries_with_their_folder_chain(self):
        self.widget.add_group("A")
        self.widget.add_subgroup("Sub")
        self.widget.add_item(values=(ItemKind.FOLDER, "Acme Drive", "/a"))
        self.widget.add_group("B")
        self.widget.add_item(values=(ItemKind.URL, "Other", "other.com"))
        self.widget.search_edit.setText("acme")
        keys = set(self.widget._nodes)
        self.assertEqual(sum(1 for k in keys if k[0] == "item"), 1)
        self.assertEqual(self.top_names(), ["A"])           # B has no match -> hidden
        self.widget.search_edit.setText("zzz")
        self.assertEqual(self.widget.tree.topLevelItemCount(), 0)
        self.widget.search_edit.setText("")
        self.assertEqual(self.top_names(), ["A", "B"])

    def test_search_on_folder_name_shows_its_contents(self):
        self.widget.add_group("Customer ACME")
        self.widget.add_item(values=(ItemKind.FOLDER, "docs", "/d"))
        self.widget.search_edit.setText("acme")
        self.assertEqual(sum(1 for k in self.widget._nodes if k[0] == "item"), 1)

    # ------------------------------------------------------------- misc
    def test_collapsed_state_survives_refresh(self):
        a = self.widget.add_group("A")
        self.widget.add_subgroup("B")
        self.node(GROUP, a.id).setExpanded(False)
        self.widget.refresh_tree()
        self.assertFalse(self.node(GROUP, a.id).isExpanded())

    def test_browser_section_defaults_to_link(self):
        from pinner.ui.icons import IconProvider
        from pinner.ui.section_widget import SectionWidget
        w = SectionWidget(Section.BROWSER, self.repo, self.launcher, IconProvider())
        self.assertEqual(w._text["default_kind"], ItemKind.URL)
        w.deleteLater()

    def test_sections_do_not_leak_into_each_other(self):
        from pinner.ui.icons import IconProvider
        from pinner.ui.section_widget import SectionWidget
        browser = SectionWidget(Section.BROWSER, self.repo, self.launcher, IconProvider())
        self.widget.add_group("Only paths")
        browser.refresh_tree()
        self.assertEqual(browser.tree.topLevelItemCount(), 0)
        browser.deleteLater()


class FakeDropEvent:
    """Just enough of QDropEvent for DropTree.dropEvent / dragEnterEvent."""

    def __init__(self, source=None, mime=None, actions=None):
        from PyQt6.QtCore import QPointF, Qt
        self._source, self._mime = source, mime
        self._actions = actions if actions is not None else (Qt.DropAction.CopyAction | Qt.DropAction.MoveAction)
        self._pos = QPointF(1, 1)
        self.action = None
        self.accepted = None

    def source(self): return self._source
    def mimeData(self): return self._mime
    def position(self): return self._pos
    def possibleActions(self): return self._actions
    def setDropAction(self, action): self.action = action
    def acceptProposedAction(self): self.accepted = True
    def accept(self): self.accepted = True
    def ignore(self): self.accepted = False


def mime_with(*urls, text=None):
    from PyQt6.QtCore import QMimeData, QUrl
    mime = QMimeData()
    if urls:
        mime.setUrls([QUrl(u) if "://" in u or u.startswith("mailto:") else QUrl.fromLocalFile(u) for u in urls])
    if text is not None:
        mime.setText(text)
    return mime


@requires_qt
class DropMoveTests(unittest.TestCase):
    """Moving an entry by drag & drop must show it in the new folder immediately."""

    @classmethod
    def setUpClass(cls):
        get_app()

    def setUp(self):
        from pinner.ui import prompts
        from pinner.ui.icons import IconProvider
        from pinner.ui.section_widget import SectionWidget
        self.db = Database(":memory:")
        self.repo = Repository(self.db)
        self.widget = SectionWidget(Section.PATHS, self.repo, mock.Mock(), IconProvider())
        for name in ("show_warning", "show_error"):
            p = mock.patch.object(prompts, name)
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        self.widget.deleteLater()
        self.db.close()

    def test_internal_drop_reports_copy_so_qt_does_not_delete_the_dragged_row(self):
        from PyQt6.QtCore import Qt
        from PyQt6.QtTest import QTest
        a = self.widget.add_group("A")
        b = self.widget.add_group("B")
        item = self.widget.add_item(values=(ItemKind.FOLDER, "x", "/x"))        # selected, in B
        tree = self.widget.tree
        tree._target_group = lambda _event: a.id
        event = FakeDropEvent(source=tree)
        tree.dropEvent(event)
        self.assertEqual(event.action, Qt.DropAction.CopyAction)
        self.assertTrue(event.accepted)
        QTest.qWait(30)                                       # deferred move runs on the next event-loop turn
        self.assertEqual(self.repo.get_item(item.id).group_id, a.id)
        self.assertIn(("item", item.id), self.widget._nodes)
        self.assertIs(self.widget._nodes[("item", item.id)].parent(), self.widget._nodes[("group", a.id)])

    def test_external_drop_is_copy_and_deferred(self):
        from PyQt6.QtCore import Qt
        from PyQt6.QtTest import QTest
        g = self.widget.add_group("Drops")
        tree = self.widget.tree
        tree._target_group = lambda _event: g.id
        event = FakeDropEvent(source=None, mime=mime_with("https://example.com/a"))
        tree.dropEvent(event)
        self.assertEqual(event.action, Qt.DropAction.CopyAction)
        QTest.qWait(30)
        self.assertEqual([i.target for i in self.repo.list_items(g.id)], ["https://example.com/a"])


@requires_qt
class BrowserBookmarksTests(unittest.TestCase):
    """The Browser Bookmarks tab accepts web links only and can import / export bookmarks."""

    @classmethod
    def setUpClass(cls):
        get_app()

    def setUp(self):
        from pinner.ui import prompts
        from pinner.ui.icons import IconProvider
        from pinner.ui.section_widget import SectionWidget

        self.db = Database(":memory:")
        self.repo = Repository(self.db)
        self.launcher = mock.Mock()
        self.widget = SectionWidget(Section.BROWSER, self.repo, self.launcher, IconProvider())
        self.paths_widget = SectionWidget(Section.PATHS, self.repo, self.launcher, IconProvider())
        self.patched = {}
        for name in ("show_warning", "show_error", "show_info"):
            p = mock.patch.object(prompts, name)
            self.patched[name] = p.start()
            self.addCleanup(p.stop)
        self.group = self.widget.add_group("Bookmarks")

    def tearDown(self):
        self.widget.deleteLater()
        self.paths_widget.deleteLater()
        self.db.close()

    # ---------------------------------------------------------------- UI
    def test_only_links_can_be_added_from_the_ui(self):
        self.assertEqual(self.widget.addable_kinds, [ItemKind.URL])
        self.assertIsNone(self.widget.add_btn.menu())               # no menu: a plain "+ Link" button
        self.assertEqual(self.paths_widget.addable_kinds, [ItemKind.URL, ItemKind.FOLDER, ItemKind.FILE])
        self.assertIsNotNone(self.paths_widget.add_btn.menu())

    def test_import_export_buttons_only_on_the_bookmarks_tab(self):
        self.assertFalse(self.widget.import_btn.isHidden())
        self.assertFalse(self.widget.export_btn.isHidden())
        self.assertTrue(self.paths_widget.import_btn.isHidden())
        self.assertTrue(self.paths_widget.export_btn.isHidden())

    def test_adding_file_or_folder_values_is_refused(self):
        for kind in (ItemKind.FILE, ItemKind.FOLDER):
            self.assertIsNone(self.widget.add_item(values=(kind, "x", "/tmp/x")))
        self.assertEqual(self.patched["show_warning"].call_count, 2)
        self.assertEqual(self.repo.list_items(self.group.id), [])

    def test_adding_a_link_works(self):
        item = self.widget.add_item(values=(ItemKind.URL, "Site", "example.com"))
        self.assertEqual(item.target, "https://example.com")

    def test_dialog_for_bookmarks_offers_links_only(self):
        from unittest import mock as m
        with m.patch("pinner.ui.section_widget.ItemDialog") as dialog_cls:
            dialog_cls.return_value.exec.return_value = 0
            self.widget.add_item()
        self.assertEqual(dialog_cls.call_args.kwargs["section"], Section.BROWSER)
        self.assertEqual(dialog_cls.call_args.kwargs["kind"], ItemKind.URL)

    def test_dropped_files_and_folders_are_refused_links_are_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = os.path.join(tmp, "a.txt")
            open(f, "w").close()
            self.widget.tree.sources_dropped.emit([f, tmp, "https://example.com/x"], self.group.id)
        self.assertEqual([i.target for i in self.repo.list_items(self.group.id)], ["https://example.com/x"])
        self.patched["show_warning"].assert_called_once()

    def test_tree_only_accepts_link_drags(self):
        tree = self.widget.tree
        self.assertTrue(tree.links_only)
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(tree._accepts(FakeDropEvent(mime=mime_with(tmp))))                      # folder
            f = os.path.join(tmp, "a.txt")
            open(f, "w").close()
            self.assertFalse(tree._accepts(FakeDropEvent(mime=mime_with(f))))                        # file
        self.assertFalse(tree._accepts(FakeDropEvent(mime=mime_with(text="C:\\Users\\me\\a.txt"))))   # pasted path
        self.assertTrue(tree._accepts(FakeDropEvent(mime=mime_with("https://example.com"))))         # link
        self.assertFalse(self.paths_widget.tree.links_only)
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(self.paths_widget.tree._accepts(FakeDropEvent(mime=mime_with(tmp))))    # Paths: still fine

    def test_dropping_a_file_on_the_bookmarks_tree_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            event = FakeDropEvent(mime=mime_with(tmp))
            self.widget.tree.dropEvent(event)
        self.assertFalse(event.accepted)
        self.assertEqual(self.repo.list_items(self.group.id), [])

    def test_links_from_mime_filters_out_local_paths(self):
        from pinner.ui import dnd
        with tempfile.TemporaryDirectory() as tmp:
            mime = mime_with("https://a.example", tmp)
            self.assertEqual([u.rstrip("/") for u in dnd.links_from_mime(mime)], ["https://a.example"])
            self.assertTrue(dnd.can_accept_links(mime))
            self.assertFalse(dnd.can_accept_links(mime_with(tmp)))

    def test_paths_tab_has_no_import_export(self):
        self.assertIsNone(self.paths_widget.import_bookmarks("whatever.html"))
        self.assertIsNone(self.paths_widget.export_bookmarks("whatever.html"))

    # ------------------------------------------------------ import / export
    HTML = ('<DL><DT><H3>Bar</H3><DL><DT><A HREF="https://a.example">A</A>'
            '<DT><A HREF="javascript:1">x</A></DL></DL>')

    def test_import_from_file_shows_folders_and_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "b.html")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(self.HTML)
            result = self.widget.import_bookmarks(path)
        self.assertEqual(result.links_added, 1)
        bar = self.repo.find_group(Section.BROWSER, "Bar")
        self.assertEqual([i.target for i in self.repo.list_items(bar.id)], ["https://a.example"])
        self.assertIn(("group", bar.id), self.widget._nodes)
        self.assertIn("Imported", self.widget.status_label.text())
        self.patched["show_info"].assert_called_once()

    def test_import_into_the_selected_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "b.html")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(self.HTML)
            self.widget.import_bookmarks(path, group_id=self.group.id)
        self.assertIsNotNone(self.repo.find_group(Section.BROWSER, "Bar", self.group.id))

    def test_bad_import_file_warns_and_changes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "b.html")
            with open(path, "w") as fh:
                fh.write("not bookmarks")
            self.assertIsNone(self.widget.import_bookmarks(path))
        self.patched["show_warning"].assert_called_once()
        self.assertEqual(len(self.repo.list_groups(Section.BROWSER)), 1)

    def test_cancelled_file_dialog_does_nothing(self):
        from pinner.ui import prompts
        with mock.patch.object(prompts, "ask_open_file", return_value=None), \
                mock.patch.object(prompts, "ask_save_file", return_value=None):
            self.assertIsNone(self.widget.import_bookmarks())
            self.assertIsNone(self.widget.export_bookmarks())
        self.patched["show_warning"].assert_not_called()

    def test_export_writes_a_bookmarks_file_and_round_trips(self):
        self.widget.add_item(values=(ItemKind.URL, "Site", "example.com"))
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "out.html")
            result = self.widget.export_bookmarks(path)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        self.assertEqual(result.links, 1)
        self.assertIn('<A HREF="https://example.com"', text)
        self.assertIn("Bookmarks</H3>", text)

    def test_export_adds_html_extension_to_chosen_name(self):
        from pinner.ui import prompts
        with tempfile.TemporaryDirectory() as tmp:
            chosen = os.path.join(tmp, "mybookmarks")
            with mock.patch.object(prompts, "ask_save_file", return_value=chosen):
                result = self.widget.export_bookmarks()
            self.assertTrue(os.path.exists(chosen + ".html"))
        self.assertEqual(str(result.path), chosen + ".html")

    def test_export_single_folder(self):
        other = self.widget.add_group("Other")
        self.widget.add_item(values=(ItemKind.URL, "Keep", "keep.example"))
        self.widget.select_group(self.group.id)
        self.widget.add_item(values=(ItemKind.URL, "Skip", "skip.example"))
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "one.html")
            self.widget.export_bookmarks(path, group_id=other.id)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        self.assertIn("keep.example", text)
        self.assertNotIn("skip.example", text)


GROUP = "group"

if __name__ == "__main__":
    unittest.main()

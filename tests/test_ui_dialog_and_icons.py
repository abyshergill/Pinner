import unittest

from tests.qt_support import get_app, requires_qt

from pinner.core.models import ItemKind, Section, ValidationError


@requires_qt
class ItemDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        get_app()

    def make(self, **kw):
        from pinner.ui.dialogs import ItemDialog
        return ItemDialog(**kw)

    def test_url_values_normalised_and_name_suggested(self):
        d = self.make(kind=ItemKind.URL)
        d.target_edit.setText("docs.example.com/guide")
        kind, name, target = d.values()
        self.assertEqual((kind, name, target),
                         (ItemKind.URL, "docs.example.com", "https://docs.example.com/guide"))

    def test_explicit_name_wins(self):
        d = self.make(kind=ItemKind.FOLDER)
        d.target_edit.setText("/data/acme/")
        d.name_edit.setText("Customer ACME")
        self.assertEqual(d.values(), (ItemKind.FOLDER, "Customer ACME", "/data/acme/"))

    def test_name_suggested_from_path(self):
        d = self.make(kind=ItemKind.FILE)
        d.target_edit.setText("/opt/tools/runner.sh")
        self.assertEqual(d.values()[1], "runner.sh")

    def test_empty_target_invalid_and_error_shown_on_accept(self):
        d = self.make()
        with self.assertRaises(ValidationError):
            d.values()
        d._on_accept()
        self.assertNotEqual(d.error_label.text(), "")
        self.assertFalse(d.result())  # not accepted

    # ---- bookmarks: links only
    def test_bookmark_dialog_offers_only_web_links(self):
        d = self.make(kind=ItemKind.FOLDER, section=Section.BROWSER)       # even if asked for a folder
        self.assertEqual(d.kind_combo.count(), 1)
        self.assertEqual(d.kind(), ItemKind.URL)
        self.assertTrue(d.kind_combo.isHidden())
        self.assertTrue(d.links_only)

    def test_bookmark_dialog_rejects_paths(self):
        d = self.make(section=Section.BROWSER)
        for bad in ("C:\\Users\\me\\a.txt", "/usr/bin/tool", "file:///tmp/x"):
            d.target_edit.setText(bad)
            with self.assertRaises(ValidationError):
                d.values()
            d._on_accept()
            self.assertFalse(d.result())
            self.assertNotEqual(d.error_label.text(), "")

    def test_bookmark_dialog_accepts_links(self):
        d = self.make(section=Section.BROWSER)
        d.target_edit.setText("docs.example.com/guide")
        self.assertEqual(d.values(),
                         (ItemKind.URL, "docs.example.com", "https://docs.example.com/guide"))

    def test_bookmark_dialog_refuses_a_dropped_file_or_folder(self):
        import tempfile
        d = self.make(section=Section.BROWSER)
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(d.apply_source(tmp))
            self.assertNotEqual(d.error_label.text(), "")
            self.assertEqual(d.target_edit.text(), "")
        self.assertTrue(d.apply_source("https://example.com/page"))
        self.assertEqual(d.target_edit.text(), "https://example.com/page")

    def test_paths_dialog_still_offers_everything(self):
        d = self.make(section=Section.PATHS)
        self.assertEqual(d.kind_combo.count(), 3)
        self.assertFalse(d.links_only)

    def test_browse_button_hidden_for_links(self):
        d = self.make(kind=ItemKind.URL)
        self.assertTrue(d.browse_btn.isHidden())
        d.kind_combo.setCurrentIndex(d.kind_combo.findData("folder"))
        self.assertFalse(d.browse_btn.isHidden())

    def test_drop_of_file_fills_full_path_name_and_type(self):
        import tempfile, os
        with tempfile.TemporaryDirectory() as tmp:
            f = os.path.join(tmp, "plan.docx")
            open(f, "w").close()
            d = self.make(kind=ItemKind.URL)          # wrong type on purpose
            self.assertTrue(d.apply_source(f))
            self.assertEqual(d.values(), (ItemKind.FILE, "plan.docx", f))
            self.assertEqual(d.target_edit.text(), f)
            self.assertTrue(d.apply_source(tmp))
            self.assertEqual(d.kind(), ItemKind.FOLDER)

    def test_drop_of_link_switches_to_web_link(self):
        d = self.make(kind=ItemKind.FOLDER)
        self.assertTrue(d.apply_source("https://example.com/a"))
        self.assertEqual(d.values(), (ItemKind.URL, "example.com", "https://example.com/a"))

    def test_drop_of_missing_path_shows_error_and_keeps_fields(self):
        d = self.make(target="/keep/me")
        self.assertFalse(d.apply_source("/no/such/thing"))
        self.assertNotEqual(d.error_label.text(), "")
        self.assertEqual(d.target_edit.text(), "/keep/me")

    def test_drop_target_edit_forwards_to_dialog(self):
        from PyQt6.QtCore import QMimeData, QUrl
        d = self.make()
        mime = QMimeData()
        mime.setUrls([QUrl("https://example.com/z")])
        from pinner.ui import dnd
        self.assertEqual(dnd.sources_from_mime(mime), ["https://example.com/z"])
        self.assertTrue(dnd.can_accept(mime))
        self.assertFalse(dnd.can_accept(QMimeData()))
        d.target_edit._on_source("https://example.com/z")
        self.assertEqual(d.kind(), ItemKind.URL)

    def test_editing_prefills(self):
        d = self.make(kind=ItemKind.URL, name="n", target="https://x.com", editing=True)
        self.assertEqual(d.name_edit.text(), "n")
        self.assertEqual(d.kind(), ItemKind.URL)


@requires_qt
class IconProviderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        get_app()

    def test_icons_load_from_icon_paths(self):
        from pinner.ui.icons import IconProvider
        icons = IconProvider()
        for name in ("app", "folder", "file", "url", "window_pin"):
            with self.subTest(icon=name):
                self.assertFalse(icons.get(name).isNull())

    def test_missing_icon_gives_null_icon_without_crashing(self):
        from pinner.ui.icons import IconProvider
        icons = IconProvider({"ghost": "/no/such/file.svg"})
        self.assertTrue(icons.get("ghost").isNull())
        self.assertTrue(icons.get("unknown").isNull())

    def test_icons_follow_custom_path_mapping(self):
        from pinner import icon_paths
        from pinner.ui.icons import IconProvider
        icons = IconProvider({"folder": icon_paths.APP_ICON})
        self.assertFalse(icons.for_kind(ItemKind.FOLDER).isNull())


if __name__ == "__main__":
    unittest.main()

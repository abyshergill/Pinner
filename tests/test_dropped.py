import os
import tempfile
import unittest

from pinner.core.database import Database
from pinner.core.dropped import add_sources, entry_from_source
from pinner.core.models import ItemKind, Section, ValidationError
from pinner.core.repository import Repository


class EntryFromSourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = os.path.join(self.tmp.name, "Customer ACME")
        os.mkdir(self.folder)
        self.file = os.path.join(self.folder, "report v2.pdf")
        open(self.file, "w").close()

    def test_file_keeps_full_path_including_file_name(self):
        kind, name, target = entry_from_source(self.file)
        self.assertEqual(kind, ItemKind.FILE)
        self.assertEqual(name, "report v2.pdf")
        self.assertEqual(target, self.file)  # path AND file name

    def test_directory_is_a_folder(self):
        kind, name, target = entry_from_source(self.folder + os.sep)
        self.assertEqual((kind, name), (ItemKind.FOLDER, "Customer ACME"))
        self.assertEqual(target, self.folder)

    def test_file_url_is_decoded(self):
        url = "file://" + self.file.replace(" ", "%20")
        kind, name, target = entry_from_source(url)
        self.assertEqual((kind, name, target), (ItemKind.FILE, "report v2.pdf", self.file))

    def test_quoted_path_from_explorer_copy_as_path(self):
        self.assertEqual(entry_from_source(f'"{self.file}"')[2], self.file)

    def test_web_links(self):
        self.assertEqual(entry_from_source("https://docs.example.com/a/b"),
                         (ItemKind.URL, "docs.example.com", "https://docs.example.com/a/b"))
        self.assertEqual(entry_from_source("mailto:a@b.com")[0], ItemKind.URL)

    def test_missing_or_empty_rejected(self):
        for bad in ("", "   ", os.path.join(self.tmp.name, "nope.txt")):
            with self.subTest(bad=bad):
                with self.assertRaises(ValidationError):
                    entry_from_source(bad)


class AddSourcesTests(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.addCleanup(self.db.close)
        self.repo = Repository(self.db)
        self.group = self.repo.create_group(Section.PATHS, "Drop zone")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.a = os.path.join(self.tmp.name, "a.txt")
        open(self.a, "w").close()
        self.d = os.path.join(self.tmp.name, "dir")
        os.mkdir(self.d)

    def test_adds_mixed_sources(self):
        res = add_sources(self.repo, self.group.id, [self.a, self.d, "example.com"])
        # "example.com" is not a path or a URL scheme -> failed, others fine
        self.assertEqual(len(res.added), 2)
        self.assertEqual(len(res.failed), 1)
        kinds = {i.kind for i in self.repo.list_items(self.group.id)}
        self.assertEqual(kinds, {ItemKind.FILE, ItemKind.FOLDER})

    def test_duplicates_skipped_including_within_one_drop(self):
        res = add_sources(self.repo, self.group.id, [self.a, self.a])
        self.assertEqual((len(res.added), res.skipped), (1, 1))
        res = add_sources(self.repo, self.group.id, [self.a])
        self.assertEqual((len(res.added), res.skipped), (0, 1))
        self.assertEqual(len(self.repo.list_items(self.group.id)), 1)

    def test_summary_text(self):
        res = add_sources(self.repo, self.group.id, [self.a, self.a, "/no/such/file"])
        self.assertEqual(res.summary(), "Added 1, 1 already there, 1 failed")

    def test_links_dropped_from_browser(self):
        res = add_sources(self.repo, self.group.id, ["https://example.com/page"])
        [item] = res.added
        self.assertEqual((item.kind, item.name), (ItemKind.URL, "example.com"))


class BrowserDropTests(unittest.TestCase):
    """Dropping onto a Browser Bookmarks folder keeps links and refuses files / folders."""

    def setUp(self):
        self.db = Database(":memory:")
        self.addCleanup(self.db.close)
        self.repo = Repository(self.db)
        self.group = self.repo.create_group(Section.BROWSER, "Bookmarks")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.file = os.path.join(self.tmp.name, "a.txt")
        open(self.file, "w").close()

    def test_links_are_added(self):
        res = add_sources(self.repo, self.group.id, ["https://example.com/a", "http://example.org"])
        self.assertEqual(len(res.added), 2)
        self.assertTrue(all(i.kind is ItemKind.URL for i in self.repo.list_items(self.group.id)))

    def test_files_and_folders_are_refused_and_not_stored(self):
        res = add_sources(self.repo, self.group.id, [self.file, self.tmp.name])
        self.assertEqual(res.added, [])
        self.assertEqual(len(res.failed), 2)
        self.assertEqual(self.repo.list_items(self.group.id), [])

    def test_mixed_drop_keeps_only_the_links(self):
        res = add_sources(self.repo, self.group.id, [self.file, "https://example.com", self.tmp.name])
        self.assertEqual([i.target for i in res.added], ["https://example.com"])
        self.assertEqual(len(res.failed), 2)

    def test_file_url_is_refused(self):
        res = add_sources(self.repo, self.group.id, ["file:///etc/hosts"])
        self.assertEqual(res.added, [])
        self.assertEqual(len(res.failed), 1)

    def test_paths_folder_still_takes_files(self):
        paths = self.repo.create_group(Section.PATHS, "General")
        res = add_sources(self.repo, paths.id, [self.file])
        self.assertEqual(res.added[0].kind, ItemKind.FILE)


if __name__ == "__main__":
    unittest.main()

import os
import sqlite3
import tempfile
import unittest

from pinner.core.database import Database
from pinner.core.models import DuplicateNameError, ItemKind, Section, ValidationError
from pinner.core.repository import Repository


class RepoTestCase(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.repo = Repository(self.db)

    def tearDown(self):
        self.db.close()


class GroupTests(RepoTestCase):
    def test_create_and_list_sorted_case_insensitive(self):
        self.repo.create_group(Section.PATHS, "beta")
        self.repo.create_group(Section.PATHS, "Alpha")
        self.assertEqual([g.name for g in self.repo.list_groups(Section.PATHS)], ["Alpha", "beta"])

    def test_sections_are_independent(self):
        self.repo.create_group(Section.PATHS, "Work")
        self.repo.create_group(Section.BROWSER, "Work")  # same name, other section: fine
        self.assertEqual(len(self.repo.list_groups(Section.PATHS)), 1)
        self.assertEqual(len(self.repo.list_groups(Section.BROWSER)), 1)

    def test_blank_name_rejected(self):
        with self.assertRaises(ValidationError):
            self.repo.create_group(Section.PATHS, "   ")

    def test_duplicate_sibling_rejected_case_insensitive(self):
        self.repo.create_group(Section.PATHS, "Acme")
        with self.assertRaises(DuplicateNameError):
            self.repo.create_group(Section.PATHS, "ACME")

    def test_duplicate_root_names_rejected_even_with_null_parent(self):
        # NULL parent_id must not defeat the unique index
        self.repo.create_group(Section.BROWSER, "Docs")
        with self.assertRaises(DuplicateNameError):
            self.repo.create_group(Section.BROWSER, "Docs")

    def test_same_name_allowed_under_different_parents(self):
        a = self.repo.create_group(Section.PATHS, "A")
        b = self.repo.create_group(Section.PATHS, "B")
        self.repo.create_group(Section.PATHS, "Sub", a.id)
        self.repo.create_group(Section.PATHS, "Sub", b.id)
        self.assertEqual(len(self.repo.list_groups(Section.PATHS)), 4)

    def test_nested_groups_keep_parent(self):
        a = self.repo.create_group(Section.PATHS, "A")
        sub = self.repo.create_group(Section.PATHS, "Sub", a.id)
        self.assertEqual(sub.parent_id, a.id)

    def test_parent_must_be_in_same_section(self):
        a = self.repo.create_group(Section.PATHS, "A")
        with self.assertRaises(ValidationError):
            self.repo.create_group(Section.BROWSER, "X", a.id)

    def test_rename(self):
        g = self.repo.create_group(Section.PATHS, "Old")
        self.assertEqual(self.repo.rename_group(g.id, " New ").name, "New")

    def test_rename_to_existing_name_rejected(self):
        self.repo.create_group(Section.PATHS, "One")
        two = self.repo.create_group(Section.PATHS, "Two")
        with self.assertRaises(DuplicateNameError):
            self.repo.rename_group(two.id, "one")

    def test_delete_cascades_to_children_and_items(self):
        a = self.repo.create_group(Section.PATHS, "A")
        sub = self.repo.create_group(Section.PATHS, "Sub", a.id)
        item = self.repo.add_item(sub.id, ItemKind.FOLDER, "x", "/x")
        self.repo.delete_group(a.id)
        self.assertEqual(self.repo.list_groups(Section.PATHS), [])
        with self.assertRaises(KeyError):
            self.repo.get_item(item.id)

    def test_get_missing_group(self):
        with self.assertRaises(KeyError):
            self.repo.get_group(999)


class ItemTests(RepoTestCase):
    def setUp(self):
        super().setUp()
        self.group = self.repo.create_group(Section.PATHS, "Customers")

    def test_add_each_kind(self):
        f = self.repo.add_item(self.group.id, ItemKind.FOLDER, "Acme Assets", "/data/acme")
        fi = self.repo.add_item(self.group.id, ItemKind.FILE, "Tool", "/bin/tool")
        u = self.repo.add_item(self.group.id, ItemKind.URL, "Portal", "portal.acme.com")
        self.assertEqual((f.kind, fi.kind, u.kind), (ItemKind.FOLDER, ItemKind.FILE, ItemKind.URL))
        self.assertEqual(u.target, "https://portal.acme.com")  # normalised

    def test_add_validates(self):
        with self.assertRaises(ValidationError):
            self.repo.add_item(self.group.id, ItemKind.FOLDER, "", "/x")
        with self.assertRaises(ValidationError):
            self.repo.add_item(self.group.id, ItemKind.FOLDER, "n", "")
        with self.assertRaises(ValidationError):
            self.repo.add_item(self.group.id, ItemKind.URL, "n", "ssh://host")

    def test_add_to_missing_group(self):
        with self.assertRaises(KeyError):
            self.repo.add_item(999, ItemKind.FOLDER, "n", "/x")

    def test_list_sorted_with_pinned_first(self):
        self.repo.add_item(self.group.id, ItemKind.FOLDER, "b", "/b")
        a = self.repo.add_item(self.group.id, ItemKind.FOLDER, "a", "/a")
        z = self.repo.add_item(self.group.id, ItemKind.FOLDER, "z", "/z")
        self.assertEqual([i.name for i in self.repo.list_items(self.group.id)], ["a", "b", "z"])
        self.repo.set_pinned(z.id, True)
        names = [i.name for i in self.repo.list_items(self.group.id)]
        self.assertEqual(names, ["z", "a", "b"])
        self.repo.set_pinned(z.id, False)
        self.assertFalse(self.repo.get_item(z.id).is_pinned)
        self.assertEqual(a.name, "a")

    def test_rename_alias_without_changing_target(self):
        i = self.repo.add_item(self.group.id, ItemKind.FOLDER, "old", "/p")
        j = self.repo.update_item(i.id, name="Customer ACME")
        self.assertEqual((j.name, j.target), ("Customer ACME", "/p"))

    def test_update_target_and_kind_revalidates(self):
        i = self.repo.add_item(self.group.id, ItemKind.FOLDER, "n", "/p")
        j = self.repo.update_item(i.id, kind=ItemKind.URL, target="example.com")
        self.assertEqual((j.kind, j.target), (ItemKind.URL, "https://example.com"))
        with self.assertRaises(ValidationError):
            self.repo.update_item(i.id, name="  ")

    def test_move_within_section(self):
        other = self.repo.create_group(Section.PATHS, "Other")
        i = self.repo.add_item(self.group.id, ItemKind.FOLDER, "n", "/p")
        self.assertEqual(self.repo.move_item(i.id, other.id).group_id, other.id)

    def test_move_across_sections_rejected(self):
        b = self.repo.create_group(Section.BROWSER, "B")
        i = self.repo.add_item(self.group.id, ItemKind.FOLDER, "n", "/p")
        with self.assertRaises(ValidationError):
            self.repo.move_item(i.id, b.id)

    def test_delete_item(self):
        i = self.repo.add_item(self.group.id, ItemKind.FOLDER, "n", "/p")
        self.repo.delete_item(i.id)
        self.assertEqual(self.repo.list_items(self.group.id), [])

    def test_search_matches_name_and_target_within_section_only(self):
        self.repo.add_item(self.group.id, ItemKind.FOLDER, "Acme Drive", "/data/x")
        self.repo.add_item(self.group.id, ItemKind.URL, "Wiki", "wiki.acme.com")
        browser = self.repo.create_group(Section.BROWSER, "B")
        self.repo.add_item(browser.id, ItemKind.URL, "Acme Mail", "mail.acme.com")
        names = sorted(i.name for i in self.repo.search_items(Section.PATHS, "acme"))
        self.assertEqual(names, ["Acme Drive", "Wiki"])

    def test_search_treats_wildcards_literally(self):
        self.repo.add_item(self.group.id, ItemKind.FOLDER, "100% done", "/a")
        self.repo.add_item(self.group.id, ItemKind.FOLDER, "other", "/b")
        self.assertEqual([i.name for i in self.repo.search_items(Section.PATHS, "%")], ["100% done"])
        self.assertEqual(self.repo.search_items(Section.PATHS, "_"), [])


class SectionItemsTests(RepoTestCase):
    def test_list_section_items_spans_nested_groups_and_only_that_section(self):
        a = self.repo.create_group(Section.PATHS, "A")
        sub = self.repo.create_group(Section.PATHS, "Sub", a.id)
        b = self.repo.create_group(Section.BROWSER, "B")
        self.repo.add_item(a.id, ItemKind.FOLDER, "one", "/1")
        self.repo.add_item(sub.id, ItemKind.FILE, "two", "/2")
        self.repo.add_item(b.id, ItemKind.URL, "web", "example.com")
        names = sorted(i.name for i in self.repo.list_section_items(Section.PATHS))
        self.assertEqual(names, ["one", "two"])


class BrowserLinksOnlyTests(RepoTestCase):
    """Browser Bookmarks accept web links only - files and folders are refused everywhere."""

    def setUp(self):
        super().setUp()
        self.bm = self.repo.create_group(Section.BROWSER, "Bookmarks")
        self.paths = self.repo.create_group(Section.PATHS, "General")

    def test_link_is_accepted(self):
        item = self.repo.add_item(self.bm.id, ItemKind.URL, "Site", "example.com")
        self.assertEqual((item.kind, item.target), (ItemKind.URL, "https://example.com"))

    def test_file_and_folder_are_rejected(self):
        for kind in (ItemKind.FILE, ItemKind.FOLDER):
            with self.subTest(kind=kind):
                with self.assertRaises(ValidationError):
                    self.repo.add_item(self.bm.id, kind, "x", "/tmp/x")
        self.assertEqual(self.repo.list_items(self.bm.id), [])

    def test_local_path_or_file_url_disguised_as_link_is_rejected(self):
        for target in ("C:\\data\\a.txt", "/etc/hosts", "file:///etc/hosts"):
            with self.subTest(target=target):
                with self.assertRaises(ValidationError):
                    self.repo.add_item(self.bm.id, ItemKind.URL, "x", target)

    def test_cannot_turn_a_link_into_a_file_or_folder(self):
        item = self.repo.add_item(self.bm.id, ItemKind.URL, "Site", "example.com")
        with self.assertRaises(ValidationError):
            self.repo.update_item(item.id, kind=ItemKind.FILE, target="/tmp/x")
        with self.assertRaises(ValidationError):
            self.repo.update_item(item.id, target="C:\\x\\y.txt")
        self.assertEqual(self.repo.get_item(item.id).target, "https://example.com")

    def test_link_can_still_be_renamed_and_retargeted(self):
        item = self.repo.add_item(self.bm.id, ItemKind.URL, "Site", "example.com")
        changed = self.repo.update_item(item.id, name="Docs", target="docs.example.com")
        self.assertEqual((changed.name, changed.target), ("Docs", "https://docs.example.com"))

    def test_paths_section_is_unchanged(self):
        for kind, target in ((ItemKind.FILE, "/tmp/f"), (ItemKind.FOLDER, "/tmp/d"), (ItemKind.URL, "x.com")):
            self.repo.add_item(self.paths.id, kind, "n", target)
        self.assertEqual(len(self.repo.list_items(self.paths.id)), 3)

    def test_file_cannot_be_moved_into_bookmarks(self):
        f = self.repo.add_item(self.paths.id, ItemKind.FILE, "f", "/tmp/f")
        with self.assertRaises(ValidationError):
            self.repo.move_item(f.id, self.bm.id)
        self.assertEqual(self.repo.get_item(f.id).group_id, self.paths.id)

    def test_links_move_between_bookmark_folders(self):
        other = self.repo.create_group(Section.BROWSER, "Other")
        item = self.repo.add_item(self.bm.id, ItemKind.URL, "Site", "example.com")
        self.assertEqual(self.repo.move_item(item.id, other.id).group_id, other.id)

    def test_database_trigger_blocks_raw_sql_inserts_and_updates(self):
        conn = self.db.conn
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO items (group_id, kind, name, target) VALUES (?, 'file', 'x', '/x')",
                         (self.bm.id,))
        conn.rollback()
        link = self.repo.add_item(self.bm.id, ItemKind.URL, "Site", "example.com")
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("UPDATE items SET kind = 'folder' WHERE id = ?", (link.id,))
        conn.rollback()
        f = self.repo.add_item(self.paths.id, ItemKind.FILE, "f", "/tmp/f")
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("UPDATE items SET group_id = ? WHERE id = ?", (self.bm.id, f.id))
        conn.rollback()
        self.assertEqual(self.repo.get_item(f.id).group_id, self.paths.id)

    def test_legacy_file_entry_in_bookmarks_can_be_pinned_removed_or_turned_into_a_link(self):
        # a row written before links-only existed (triggers dropped to simulate the old database)
        self.db.conn.execute("DROP TRIGGER trg_bookmarks_links_only_insert")
        cur = self.db.conn.execute(
            "INSERT INTO items (group_id, kind, name, target) VALUES (?, 'file', 'old', '/old.txt')", (self.bm.id,))
        old_id = cur.lastrowid
        self.assertTrue(self.repo.set_pinned(old_id, True).is_pinned)             # harmless edits still work
        other = self.repo.create_group(Section.BROWSER, "Other")
        with self.assertRaises(ValidationError):                                  # but it cannot be moved around
            self.repo.move_item(old_id, other.id)
        with self.assertRaises(ValidationError):                                  # nor renamed while still a file
            self.repo.update_item(old_id, name="renamed")
        fixed = self.repo.update_item(old_id, kind=ItemKind.URL, target="example.com")
        self.assertEqual((fixed.kind, fixed.target), (ItemKind.URL, "https://example.com"))
        self.repo.delete_item(old_id)
        self.assertEqual(self.repo.list_items(self.bm.id), [])

    def test_trigger_does_not_block_pinning_a_link(self):
        link = self.repo.add_item(self.bm.id, ItemKind.URL, "Site", "example.com")
        self.assertTrue(self.repo.set_pinned(link.id, True).is_pinned)


class FindGroupAndBatchTests(RepoTestCase):
    def test_find_group_is_case_insensitive_and_scoped(self):
        a = self.repo.create_group(Section.BROWSER, "Work")
        sub = self.repo.create_group(Section.BROWSER, "Docs", a.id)
        self.assertEqual(self.repo.find_group(Section.BROWSER, "work").id, a.id)
        self.assertEqual(self.repo.find_group(Section.BROWSER, " DOCS ", a.id).id, sub.id)
        self.assertIsNone(self.repo.find_group(Section.BROWSER, "Docs"))          # not at top level
        self.assertIsNone(self.repo.find_group(Section.PATHS, "Work"))            # other section

    def test_batch_commits_everything_on_success(self):
        with self.repo.batch():
            g = self.repo.create_group(Section.BROWSER, "B")
            self.repo.add_item(g.id, ItemKind.URL, "a", "a.com")
            self.repo.add_item(g.id, ItemKind.URL, "b", "b.com")
        self.assertEqual(len(self.repo.list_items(g.id)), 2)

    def test_batch_rolls_back_everything_on_error(self):
        with self.assertRaises(RuntimeError):
            with self.repo.batch():
                g = self.repo.create_group(Section.BROWSER, "B")
                self.repo.add_item(g.id, ItemKind.URL, "a", "a.com")
                raise RuntimeError("boom")
        self.assertEqual(self.repo.list_groups(Section.BROWSER), [])

    def test_batch_survives_a_duplicate_folder_error_inside(self):
        with self.repo.batch():
            self.repo.create_group(Section.BROWSER, "B")
            with self.assertRaises(DuplicateNameError):
                self.repo.create_group(Section.BROWSER, "b")
            self.repo.create_group(Section.BROWSER, "C")
        self.assertEqual([g.name for g in self.repo.list_groups(Section.BROWSER)], ["B", "C"])

    def test_nested_batches_and_normal_writes_afterwards(self):
        with self.repo.batch():
            with self.repo.batch():
                self.repo.create_group(Section.BROWSER, "A")
        self.repo.create_group(Section.BROWSER, "B")     # plain write still commits
        self.assertFalse(self.db.conn.in_transaction)
        self.assertEqual(len(self.repo.list_groups(Section.BROWSER)), 2)


class SettingsTests(RepoTestCase):
    def test_roundtrip_and_defaults(self):
        self.assertIsNone(self.repo.get_setting("x"))
        self.assertEqual(self.repo.get_setting("x", "d"), "d")
        self.repo.set_setting("x", "1")
        self.repo.set_setting("x", "2")  # upsert
        self.assertEqual(self.repo.get_setting("x"), "2")

    def test_bool(self):
        self.assertFalse(self.repo.get_bool("flag"))
        self.assertTrue(self.repo.get_bool("flag", True))
        self.repo.set_bool("flag", True)
        self.assertTrue(self.repo.get_bool("flag"))
        self.repo.set_bool("flag", False)
        self.assertFalse(self.repo.get_bool("flag", True))


class PersistenceTests(unittest.TestCase):
    def test_data_survives_reopen_and_creates_parent_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "nested", "dir", "pm.db")
            with Database(path) as db:
                repo = Repository(db)
                g = repo.create_group(Section.PATHS, "Keep")
                repo.add_item(g.id, ItemKind.URL, "Site", "example.com")
            with Database(path) as db:
                repo = Repository(db)
                [g] = repo.list_groups(Section.PATHS)
                [i] = repo.list_items(g.id)
                self.assertEqual((g.name, i.name), ("Keep", "Site"))

    def test_foreign_keys_enforced(self):
        with Database(":memory:") as db:
            import sqlite3
            with self.assertRaises(sqlite3.IntegrityError):
                with db.conn:
                    db.conn.execute(
                        "INSERT INTO items (group_id, kind, name, target) VALUES (42,'url','n','t')")


if __name__ == "__main__":
    unittest.main()

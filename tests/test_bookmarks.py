import json
import os
import tempfile
import unittest

from pinner.core import bookmarks as bm
from pinner.core.database import Database
from pinner.core.models import ItemKind, Section, ValidationError
from pinner.core.repository import Repository

CHROME_HTML = """<!DOCTYPE NETSCAPE-Bookmark-file-1>
<!-- This is an automatically generated file. It will be read and overwritten. DO NOT EDIT! -->
<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">
<TITLE>Bookmarks</TITLE>
<H1>Bookmarks</H1>
<DL><p>
    <DT><H3 ADD_DATE="1600000000" LAST_MODIFIED="1600000001" PERSONAL_TOOLBAR_FOLDER="true">Bookmarks bar</H3>
    <DL><p>
        <DT><A HREF="https://example.com/?a=1&amp;b=2" ADD_DATE="1600000000">Example &amp; Co</A>
        <DT><H3 ADD_DATE="1600000000">Work</H3>
        <DL><p>
            <DT><A HREF="https://jira.example.com/browse" ADD_DATE="1">Jira</A>
            <DT><A HREF="javascript:alert(1)">Bookmarklet</A>
            <DT><H3>Deep</H3>
            <DL><p>
                <DT><A HREF="ftp://files.example.com/pub">Files</A>
            </DL><p>
        </DL><p>
    </DL><p>
    <DT><H3 ADD_DATE="1600000000">Other bookmarks</H3>
    <DL><p>
        <DT><A HREF="chrome://settings">Settings</A>
        <DT><A HREF="file:///C:/Users/me/report.pdf">Local report</A>
        <DT><A HREF="mailto:team@example.com">Mail the team</A>
    </DL><p>
</DL><p>
"""

FIREFOX_HTML = """<!DOCTYPE NETSCAPE-Bookmark-file-1>
<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">
<TITLE>Bookmarks</TITLE>
<H1>Bookmarks Menu</H1>

<DL><p>
    <DT><H3 ADD_DATE="1" LAST_MODIFIED="2" PERSONAL_TOOLBAR_FOLDER="true">Bookmarks Toolbar</H3>
    <DL><p>
        <DT><A HREF="https://www.mozilla.org/" ADD_DATE="1" ICON_URI="fake-favicon-uri:https://www.mozilla.org/" ICON="data:image/png;base64,AAAA">Mozilla</A>
        <DD>A description line that must be ignored
        <HR>
        <DT><A HREF="place:parent=1234&amp;queryType=1">A smart folder</A>
    </DL><p>
    <DT><H3 ADD_DATE="1">Empty folder</H3>
    <DL><p>
    </DL><p>
</DL>
"""

CHROME_JSON = json.dumps({
    "checksum": "x",
    "roots": {
        "bookmark_bar": {"type": "folder", "name": "Bookmarks bar", "children": [
            {"type": "url", "name": "Example", "url": "https://example.com"},
            {"type": "folder", "name": "Work", "children": [
                {"type": "url", "name": "Jira", "url": "https://jira.example.com"},
                {"type": "url", "name": "Bookmarklet", "url": "javascript:void(0)"},
            ]},
        ]},
        "other": {"type": "folder", "name": "Other bookmarks", "children": []},
        "synced": {"type": "folder", "name": "Mobile bookmarks", "children": [
            {"type": "url", "name": "", "url": "http://m.example.com/page"}]},
        "sync_transaction_version": "3",
    },
    "version": 1,
})

FIREFOX_JSON = json.dumps({
    "title": "", "root": "placesRoot", "type": "text/x-moz-place-container", "children": [
        {"title": "Bookmarks Menu", "root": "bookmarksMenuFolder", "type": "text/x-moz-place-container", "children": [
            {"title": "Mozilla", "type": "text/x-moz-place", "uri": "https://www.mozilla.org/"},
            {"type": "text/x-moz-place-separator"},
            {"title": "Tab history", "type": "text/x-moz-place", "uri": "place:sort=8"},
        ]},
        {"title": "Bookmarks Toolbar", "type": "text/x-moz-place-container", "children": [
            {"title": "Rust", "type": "text/x-moz-place", "uri": "https://www.rust-lang.org/"}]},
    ]})


def names(folder):
    return [f.name for f in folder.folders]


class ParseHtmlTests(unittest.TestCase):
    def test_chrome_structure_titles_and_entities(self):
        tree = bm.parse_bookmarks(CHROME_HTML)
        self.assertEqual(names(tree.root), ["Bookmarks bar", "Other bookmarks"])
        bar = tree.root.folders[0]
        self.assertEqual(bar.links, [bm.BookmarkLink("Example & Co", "https://example.com/?a=1&b=2")])
        work = bar.folders[0]
        self.assertEqual((work.name, [l.title for l in work.links]), ("Work", ["Jira"]))
        self.assertEqual(work.folders[0].links[0].url, "ftp://files.example.com/pub")

    def test_non_web_bookmarks_are_skipped_and_counted(self):
        tree = bm.parse_bookmarks(CHROME_HTML)
        self.assertEqual(tree.skipped, 3)           # javascript:, chrome://, file:
        other = tree.root.folders[1]
        self.assertEqual([l.url for l in other.links], ["mailto:team@example.com"])
        self.assertEqual(tree.link_count, 4)
        self.assertEqual(tree.folder_count, 4)

    def test_firefox_html_with_icons_descriptions_and_separators(self):
        tree = bm.parse_bookmarks(FIREFOX_HTML)
        self.assertEqual(names(tree.root), ["Bookmarks Toolbar", "Empty folder"])
        self.assertEqual([l.title for l in tree.root.folders[0].links], ["Mozilla"])
        self.assertEqual(tree.skipped, 1)                                   # place: query
        self.assertEqual(tree.root.folders[1].links, [])                     # empty folder kept

    def test_links_outside_any_folder_land_on_the_root(self):
        tree = bm.parse_bookmarks('<DL><p><DT><A HREF="https://a.example">A</A></DL>')
        self.assertEqual([l.url for l in tree.root.links], ["https://a.example"])

    def test_missing_titles_get_sensible_defaults(self):
        tree = bm.parse_bookmarks('<DL><DT><H3></H3><DL><DT><A HREF="https://x.example/p"></A></DL></DL>')
        self.assertEqual(tree.root.folders[0].name, "Untitled folder")
        self.assertEqual(tree.root.folders[0].links[0].title, "x.example")

    def test_unclosed_and_uppercase_lowercase_tags_are_tolerated(self):
        text = '<dl><dt><h3>F</h3><dl><dt><a href="https://a.example">A<dt><a href="https://b.example">B</a></dl></dl>'
        tree = bm.parse_bookmarks(text)
        self.assertEqual(tree.root.folders[0].name, "F")
        self.assertEqual(tree.link_count, 2)

    def test_pathological_nesting_is_flattened_not_crashing(self):
        depth = bm.MAX_DEPTH + 40
        text = "".join(f"<DL><DT><H3>f{i}</H3>" for i in range(depth)) + '<DL><DT><A HREF="https://deep.example">d</A></DL>'
        tree = bm.parse_bookmarks(text)
        self.assertEqual(tree.link_count, 1)
        self.assertLessEqual(tree.folder_count, bm.MAX_DEPTH)

    def test_no_bookmarks_raises_helpful_error(self):
        for text in ("", "hello", "<html><body>nothing</body></html>"):
            with self.subTest(text=text):
                with self.assertRaises(bm.BookmarkFileError):
                    bm.parse_bookmarks(text)

    def test_only_non_web_bookmarks_raises(self):
        with self.assertRaises(bm.BookmarkFileError) as ctx:
            bm.parse_bookmarks('<DL><DT><A HREF="javascript:1">x</A></DL>')
        self.assertIn("1", str(ctx.exception))


class ParseJsonTests(unittest.TestCase):
    def test_chrome_edge_bookmarks_file(self):
        tree = bm.parse_bookmarks(CHROME_JSON)
        self.assertEqual(names(tree.root), ["Bookmarks bar", "Mobile bookmarks"])    # empty root dropped
        bar = tree.root.folders[0]
        self.assertEqual([l.title for l in bar.links], ["Example"])
        self.assertEqual(bar.folders[0].links[0].url, "https://jira.example.com")
        self.assertEqual(tree.skipped, 1)
        self.assertEqual(tree.root.folders[1].links[0].title, "m.example.com")        # blank name -> host

    def test_firefox_backup(self):
        tree = bm.parse_bookmarks(FIREFOX_JSON)
        self.assertEqual(names(tree.root), ["Bookmarks Menu", "Bookmarks Toolbar"])
        self.assertEqual(tree.link_count, 2)
        self.assertEqual(tree.skipped, 1)                                             # place:

    def test_invalid_json_is_a_file_error(self):
        with self.assertRaises(bm.BookmarkFileError):
            bm.parse_bookmarks("{not json")

    def test_json_without_bookmarks_is_rejected(self):
        with self.assertRaises(bm.BookmarkFileError):
            bm.parse_bookmarks('{"hello": "world"}')


class ReadFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def write(self, name, data: bytes):
        path = os.path.join(self.tmp.name, name)
        with open(path, "wb") as fh:
            fh.write(data)
        return path

    def test_utf8_with_bom_and_non_ascii_titles(self):
        html = '<DL><DT><H3>Café ☕</H3><DL><DT><A HREF="https://a.example">Zażółć</A></DL></DL>'
        tree = bm.read_bookmark_file(self.write("b.html", b"\xef\xbb\xbf" + html.encode("utf-8")))
        self.assertEqual(tree.root.folders[0].name, "Café ☕")
        self.assertEqual(tree.root.folders[0].links[0].title, "Zażółć")

    def test_utf16_file(self):
        html = '<DL><DT><A HREF="https://a.example">A</A></DL>'
        tree = bm.read_bookmark_file(self.write("b.html", html.encode("utf-16")))
        self.assertEqual(tree.link_count, 1)

    def test_missing_file_is_a_file_error(self):
        with self.assertRaises(bm.BookmarkFileError):
            bm.read_bookmark_file(os.path.join(self.tmp.name, "nope.html"))

    def test_file_error_is_a_validation_error_for_the_ui(self):
        self.assertTrue(issubclass(bm.BookmarkFileError, ValidationError))

    def test_oversized_file_rejected(self):
        path = self.write("big.html", b"x")
        original = bm.MAX_FILE_BYTES
        bm.MAX_FILE_BYTES = 0
        self.addCleanup(setattr, bm, "MAX_FILE_BYTES", original)
        with self.assertRaises(bm.BookmarkFileError):
            bm.read_bookmark_file(path)


class RepoCase(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.addCleanup(self.db.close)
        self.repo = Repository(self.db)

    def snapshot(self):
        """{ 'A / B': [urls] } for every Browser Bookmarks folder."""
        groups = {g.id: g for g in self.repo.list_groups(Section.BROWSER)}

        def path(g):
            return path(groups[g.parent_id]) + " / " + g.name if g.parent_id else g.name

        return {path(g): sorted(i.target for i in self.repo.list_items(g.id)) for g in groups.values()}


class ImportTests(RepoCase):
    def test_import_creates_folders_and_links(self):
        res = bm.import_bookmarks(self.repo, bm.parse_bookmarks(CHROME_HTML))
        self.assertEqual((res.links_added, res.folders_created, res.skipped), (4, 4, 3))
        snap = self.snapshot()
        self.assertEqual(snap["Bookmarks bar"], ["https://example.com/?a=1&b=2"])
        self.assertEqual(snap["Bookmarks bar / Work"], ["https://jira.example.com/browse"])
        self.assertEqual(snap["Bookmarks bar / Work / Deep"], ["ftp://files.example.com/pub"])
        self.assertEqual(snap["Other bookmarks"], ["mailto:team@example.com"])

    def test_only_links_are_ever_stored(self):
        bm.import_bookmarks(self.repo, bm.parse_bookmarks(CHROME_HTML))
        kinds = {i.kind for i in self.repo.list_section_items(Section.BROWSER)}
        self.assertEqual(kinds, {ItemKind.URL})
        self.assertEqual(self.repo.list_section_items(Section.PATHS), [])
        self.assertEqual(self.repo.list_groups(Section.PATHS), [])

    def test_importing_twice_adds_nothing_new(self):
        tree = bm.parse_bookmarks(CHROME_HTML)
        bm.import_bookmarks(self.repo, tree)
        before = self.snapshot()
        res = bm.import_bookmarks(self.repo, tree)
        self.assertEqual((res.links_added, res.folders_created, res.duplicates), (0, 0, 4))
        self.assertEqual(self.snapshot(), before)

    def test_merges_into_existing_folders_case_insensitively(self):
        existing = self.repo.create_group(Section.BROWSER, "bookmarks BAR")
        self.repo.add_item(existing.id, ItemKind.URL, "Mine", "https://mine.example")
        bm.import_bookmarks(self.repo, bm.parse_bookmarks(CHROME_HTML))
        self.assertEqual(len([g for g in self.repo.list_groups(Section.BROWSER) if g.parent_id is None]), 2)
        self.assertEqual(self.snapshot()["bookmarks BAR"],
                         ["https://example.com/?a=1&b=2", "https://mine.example"])

    def test_import_into_selected_folder(self):
        target = self.repo.create_group(Section.BROWSER, "Inbox")
        bm.import_bookmarks(self.repo, bm.parse_bookmarks(CHROME_HTML), parent_id=target.id)
        snap = self.snapshot()
        self.assertIn("Inbox / Bookmarks bar / Work", snap)
        self.assertNotIn("Bookmarks bar", snap)

    def test_loose_root_links_go_to_a_named_folder_or_the_target(self):
        tree = bm.parse_bookmarks('<DL><DT><A HREF="https://a.example">A</A></DL>')
        bm.import_bookmarks(self.repo, tree)
        self.assertEqual(self.snapshot(), {"Imported bookmarks": ["https://a.example"]})
        target = self.repo.create_group(Section.BROWSER, "Inbox")
        bm.import_bookmarks(self.repo, tree, parent_id=target.id)
        self.assertEqual(self.snapshot()["Inbox"], ["https://a.example"])

    def test_cannot_import_into_a_paths_folder(self):
        paths = self.repo.create_group(Section.PATHS, "General")
        with self.assertRaises(ValidationError):
            bm.import_bookmarks(self.repo, bm.parse_bookmarks(CHROME_HTML), parent_id=paths.id)
        self.assertEqual(self.repo.list_items(paths.id), [])

    def test_failed_import_changes_nothing(self):
        tree = bm.parse_bookmarks(CHROME_HTML)
        original = self.repo.add_item
        calls = {"n": 0}

        def flaky(*a, **kw):
            calls["n"] += 1
            if calls["n"] == 3:
                raise RuntimeError("disk full")
            return original(*a, **kw)

        self.repo.add_item = flaky
        with self.assertRaises(RuntimeError):
            bm.import_bookmarks(self.repo, tree)
        self.assertEqual(self.repo.list_groups(Section.BROWSER), [])
        self.assertEqual(self.repo.list_section_items(Section.BROWSER), [])

    def test_firefox_and_chrome_json_import(self):
        bm.import_bookmarks(self.repo, bm.parse_bookmarks(FIREFOX_JSON))
        bm.import_bookmarks(self.repo, bm.parse_bookmarks(CHROME_JSON))
        snap = self.snapshot()
        self.assertEqual(snap["Bookmarks Menu"], ["https://www.mozilla.org/"])
        self.assertEqual(snap["Mobile bookmarks"], ["http://m.example.com/page"])

    def test_large_import_is_fast_and_complete(self):
        links = "".join(f'<DT><A HREF="https://site{i}.example/p">Site {i}</A>' for i in range(3000))
        res = bm.import_bookmarks(self.repo, bm.parse_bookmarks(f"<DL><DT><H3>Big</H3><DL>{links}</DL></DL>"))
        self.assertEqual(res.links_added, 3000)

    def test_summary_mentions_every_non_zero_part(self):
        text = bm.ImportResult(folders_created=2, links_added=5, duplicates=1, skipped=3).summary()
        for part in ("5 link", "2 folder", "1 duplicate", "3 non-web"):
            self.assertIn(part, text)


class ExportTests(RepoCase):
    def setUp(self):
        super().setUp()
        bm.import_bookmarks(self.repo, bm.parse_bookmarks(CHROME_HTML))

    def test_output_is_a_netscape_bookmarks_file(self):
        out = bm.export_html(bm.build_tree(self.repo), now=1700000000)
        self.assertTrue(out.startswith("<!DOCTYPE NETSCAPE-Bookmark-file-1>"))
        self.assertIn('<DT><H3 ADD_DATE="1700000000" LAST_MODIFIED="1700000000">Bookmarks bar</H3>', out)
        self.assertIn('<A HREF="https://jira.example.com/browse" ADD_DATE="1700000000">Jira</A>', out)
        self.assertEqual(out.count("<DL><p>"), out.count("</DL><p>"))

    def test_special_characters_are_escaped(self):
        g = self.repo.create_group(Section.BROWSER, 'Q&A <"x">')
        self.repo.add_item(g.id, ItemKind.URL, 'a <b> & "c"', "https://e.example/?x=1&y=2")
        out = bm.export_html(bm.build_tree(self.repo, g.id))
        self.assertIn("Q&amp;A &lt;&quot;x&quot;&gt;", out)
        self.assertIn('HREF="https://e.example/?x=1&amp;y=2"', out)
        self.assertNotIn("<b>", out)

    def test_round_trip_keeps_folders_titles_and_urls(self):
        before = self.snapshot()
        out = bm.export_html(bm.build_tree(self.repo))
        other = Repository(Database(":memory:"))
        bm.import_bookmarks(other, bm.parse_bookmarks(out))
        again = RepoCase()
        again.repo = other
        self.assertEqual(again.snapshot(), before)
        titles = sorted(i.name for i in other.list_section_items(Section.BROWSER))
        self.assertEqual(titles, sorted(i.name for i in self.repo.list_section_items(Section.BROWSER)))

    def test_export_one_folder_only(self):
        work = self.repo.find_group(Section.BROWSER, "Work",
                                    self.repo.find_group(Section.BROWSER, "Bookmarks bar").id)
        tree = bm.build_tree(self.repo, work.id)
        self.assertEqual(names(tree.root), ["Work"])
        self.assertEqual(tree.link_count, 2)           # Jira + Files in Deep
        out = bm.export_html(tree)
        self.assertIn("Jira", out)
        self.assertNotIn("Example &amp; Co", out)
        self.assertNotIn("Other bookmarks", out)

    def test_empty_database_exports_valid_empty_file(self):
        empty = Repository(Database(":memory:"))
        out = bm.export_html(bm.build_tree(empty))
        self.assertIn("<DL><p>", out)
        self.assertEqual(bm.build_tree(empty).link_count, 0)

    def test_legacy_non_link_entries_are_left_out_and_counted(self):
        # a database written before links-only was enforced: bypass the guards on purpose
        g = self.repo.find_group(Section.BROWSER, "Other bookmarks")
        self.db.conn.execute("DROP TRIGGER trg_bookmarks_links_only_insert")
        self.db.conn.execute("INSERT INTO items (group_id, kind, name, target) VALUES (?, 'file', 'old', '/old.txt')",
                             (g.id,))
        tree = bm.build_tree(self.repo)
        self.assertEqual(tree.skipped, 1)
        self.assertNotIn("/old.txt", bm.export_html(tree))

    def test_export_to_file_writes_utf8_and_reports(self):
        g = self.repo.create_group(Section.BROWSER, "Café")
        self.repo.add_item(g.id, ItemKind.URL, "Zażółć", "https://a.example")
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "out.html")
            res = bm.export_to_file(self.repo, path)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        self.assertIn("Café", text)
        self.assertIn("Zażółć", text)
        self.assertEqual((res.links, res.folders), (5, 5))
        self.assertIn("5 link", res.summary())

    def test_export_to_unwritable_path_is_a_file_error(self):
        with self.assertRaises(bm.BookmarkFileError):
            bm.export_to_file(self.repo, os.path.join(tempfile.gettempdir(), "no", "such", "dir", "x.html"))


if __name__ == "__main__":
    unittest.main()

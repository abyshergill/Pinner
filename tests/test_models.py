import unittest

from pinner.core.models import (
    ALLOWED_KINDS,
    ItemKind,
    Section,
    ValidationError,
    clean_name,
    clean_target,
    has_web_scheme,
    normalize_bookmark_url,
    normalize_url,
    validate_entry,
)


class NormalizeUrlTests(unittest.TestCase):
    def test_adds_https_when_scheme_missing(self):
        self.assertEqual(normalize_url("example.com/a"), "https://example.com/a")

    def test_keeps_existing_scheme(self):
        self.assertEqual(normalize_url("http://example.com"), "http://example.com")
        self.assertEqual(normalize_url("  HTTPS://Example.com "), "HTTPS://Example.com")

    def test_mailto_is_allowed(self):
        self.assertEqual(normalize_url("mailto:a@b.com"), "mailto:a@b.com")

    def test_rejects_empty_and_unsafe_schemes(self):
        for bad in ("", "   ", "javascript://alert(1)", "ssh://host", "https://"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValidationError):
                    normalize_url(bad)


class CleanTests(unittest.TestCase):
    def test_clean_name_strips_and_rejects_blank(self):
        self.assertEqual(clean_name("  Acme  "), "Acme")
        with self.assertRaises(ValidationError):
            clean_name("   ")

    def test_clean_target_depends_on_kind(self):
        self.assertEqual(clean_target(ItemKind.URL, "example.com"), "https://example.com")
        self.assertEqual(clean_target(ItemKind.FOLDER, " /tmp/x "), "/tmp/x")
        with self.assertRaises(ValidationError):
            clean_target(ItemKind.FILE, "")


class BookmarkUrlTests(unittest.TestCase):
    def test_accepts_web_links_and_adds_https(self):
        self.assertEqual(normalize_bookmark_url("example.com/a"), "https://example.com/a")
        self.assertEqual(normalize_bookmark_url("http://example.com"), "http://example.com")
        self.assertEqual(normalize_bookmark_url("ftp://files.example.com/x"), "ftp://files.example.com/x")
        self.assertEqual(normalize_bookmark_url("mailto:a@b.com"), "mailto:a@b.com")
        self.assertEqual(normalize_bookmark_url("localhost:8080/app"), "https://localhost:8080/app")

    def test_rejects_local_files_and_folders(self):
        for bad in ("C:\\Users\\me\\report.pdf", "C:/Users/me", "\\\\server\\share\\x",
                    "/usr/local/bin/tool", "~/Documents", "file:///C:/x.txt", "FILE://server/x"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValidationError):
                    normalize_bookmark_url(bad)

    def test_rejects_pseudo_links_and_spaces(self):
        for bad in ("", "  ", "javascript:alert(1)", "data:text/html,hi", "about:blank",
                    "chrome://settings", "hello world", "ssh://host"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValidationError):
                    normalize_bookmark_url(bad)

    def test_paths_section_still_accepts_file_links(self):
        # only Browser Bookmarks are strict
        self.assertEqual(clean_target(ItemKind.URL, "file:///tmp/x", Section.PATHS), "file:///tmp/x")
        with self.assertRaises(ValidationError):
            clean_target(ItemKind.URL, "file:///tmp/x", Section.BROWSER)

    def test_has_web_scheme(self):
        self.assertTrue(has_web_scheme(" HTTPS://x.com"))
        self.assertTrue(has_web_scheme("mailto:a@b.c"))
        self.assertFalse(has_web_scheme("/tmp/x"))
        self.assertFalse(has_web_scheme("example.com"))
        self.assertFalse(has_web_scheme("file:///x"))


class SectionRulesTests(unittest.TestCase):
    def test_browser_allows_only_links_paths_allows_all(self):
        self.assertEqual(ALLOWED_KINDS[Section.BROWSER], frozenset({ItemKind.URL}))
        self.assertEqual(ALLOWED_KINDS[Section.PATHS], frozenset(ItemKind))

    def test_validate_entry_rejects_files_and_folders_in_browser(self):
        for kind in (ItemKind.FILE, ItemKind.FOLDER):
            with self.subTest(kind=kind):
                with self.assertRaises(ValidationError):
                    validate_entry(Section.BROWSER, kind, "x", "/tmp/x")

    def test_validate_entry_ok_cases(self):
        self.assertEqual(validate_entry(Section.BROWSER, ItemKind.URL, " Site ", "example.com"),
                         (ItemKind.URL, "Site", "https://example.com"))
        self.assertEqual(validate_entry(Section.PATHS, ItemKind.FILE, "f", "/tmp/f"),
                         (ItemKind.FILE, "f", "/tmp/f"))


if __name__ == "__main__":
    unittest.main()

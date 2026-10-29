import os
import tempfile
import unittest

from pinner.core.launcher import LaunchError, Launcher
from pinner.core.models import Item, ItemKind


def make_item(kind, target):
    return Item(1, 1, kind, "n", target)


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.popen_calls, self.browser_calls, self.startfile_calls = [], [], []
        self.browser_result = True

    def launcher(self, system):
        return Launcher(
            system=system,
            popen=lambda cmd: self.popen_calls.append(cmd),
            browser_open=lambda url: (self.browser_calls.append(url), self.browser_result)[1],
            startfile=lambda p: self.startfile_calls.append(p),
        )

    def test_url_opens_in_browser(self):
        self.launcher("Linux").open_item(make_item(ItemKind.URL, "https://example.com"))
        self.assertEqual(self.browser_calls, ["https://example.com"])
        self.assertEqual(self.popen_calls, [])

    def test_url_failure_raises(self):
        self.browser_result = False
        with self.assertRaises(LaunchError):
            self.launcher("Linux").open_url("https://example.com")

    def test_folder_per_platform(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.launcher("Linux").open_item(make_item(ItemKind.FOLDER, tmp))
            self.launcher("Darwin").open_item(make_item(ItemKind.FOLDER, tmp))
            self.launcher("Windows").open_item(make_item(ItemKind.FOLDER, tmp))
        self.assertEqual(self.popen_calls, [["xdg-open", tmp], ["open", tmp]])
        self.assertEqual(self.startfile_calls, [tmp])

    def test_file_opens(self):
        with tempfile.NamedTemporaryFile() as f:
            self.launcher("Linux").open_item(make_item(ItemKind.FILE, f.name))
            self.assertEqual(self.popen_calls, [["xdg-open", f.name]])

    def test_missing_paths_raise(self):
        missing = os.path.join(tempfile.gettempdir(), "definitely_missing_pm_test")
        with self.assertRaises(LaunchError):
            self.launcher("Linux").open_folder(missing)
        with self.assertRaises(LaunchError):
            self.launcher("Linux").open_file(missing)
        self.assertEqual(self.popen_calls, [])

    def test_file_path_is_not_a_folder(self):
        with tempfile.NamedTemporaryFile() as f:
            with self.assertRaises(LaunchError):
                self.launcher("Linux").open_folder(f.name)

    def test_os_error_wrapped(self):
        def boom(cmd):
            raise OSError("no opener")
        launcher = Launcher(system="Linux", popen=boom)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(LaunchError):
                launcher.open_folder(tmp)

    def test_reveal_per_platform(self):
        with tempfile.NamedTemporaryFile() as f:
            self.launcher("Darwin").reveal(f.name)
            self.launcher("Windows").reveal(f.name)
            self.launcher("Linux").reveal(f.name)
            self.assertEqual(self.popen_calls[0], ["open", "-R", f.name])
            self.assertEqual(self.popen_calls[1][0], "explorer")
            self.assertTrue(self.popen_calls[1][1].startswith("/select,"))
            self.assertEqual(self.popen_calls[2], ["xdg-open", os.path.dirname(f.name)])

    def test_reveal_directory_on_linux_opens_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.launcher("Linux").reveal(tmp)
            self.assertEqual(self.popen_calls, [["xdg-open", tmp]])

    def test_reveal_missing_raises(self):
        with self.assertRaises(LaunchError):
            self.launcher("Linux").reveal("/definitely/missing/pm")


if __name__ == "__main__":
    unittest.main()

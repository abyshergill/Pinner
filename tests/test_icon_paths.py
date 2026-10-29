import re
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from pinner import icon_paths

PACKAGE = Path(icon_paths.__file__).parent


class IconPathTests(unittest.TestCase):
    def test_every_declared_icon_exists_and_is_valid_svg(self):
        for name, path in icon_paths.ICON_PATHS.items():
            with self.subTest(icon=name):
                self.assertTrue(Path(path).is_file(), f"missing icon file: {path}")
                root = ET.parse(path).getroot()
                self.assertTrue(root.tag.endswith("svg"))

    def test_required_logical_names_present(self):
        for name in ("app", "folder", "file", "url", "group_paths", "group_browser", "window_pin"):
            self.assertIn(name, icon_paths.ICON_PATHS)

    def test_icon_dir_can_be_overridden_by_environment(self):
        import importlib
        import os
        from unittest import mock
        with mock.patch.dict(os.environ, {"PINNER_ICON_DIR": "/custom/icons"}):
            reloaded = importlib.reload(icon_paths)
            self.assertEqual(reloaded.APP_ICON, Path("/custom/icons/app.svg"))
        importlib.reload(icon_paths)

    def test_no_other_module_hardcodes_icon_files(self):
        """Icon file names must live only in icon_paths.py."""
        pattern = re.compile(r"\.(svg|png|ico|icns)\b", re.I)
        for py in PACKAGE.rglob("*.py"):
            if py.name == "icon_paths.py":
                continue
            with self.subTest(file=py.name):
                self.assertIsNone(pattern.search(py.read_text(encoding="utf-8")),
                                  f"{py} hard-codes an icon path")


if __name__ == "__main__":
    unittest.main()

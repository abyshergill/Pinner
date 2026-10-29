import re
import unittest
from pathlib import Path

from pinner.ui import styles

UI_DIR = Path(styles.__file__).parent


class StylesheetTests(unittest.TestCase):
    def test_no_pixel_font_sizes_which_cause_qfont_warning(self):
        """'QFont::setPointSize: Point size <= 0 (-1)' comes from px font sizes in a stylesheet."""
        self.assertIsNone(re.search(r"font-size\s*:\s*[\d.]+\s*px", styles.STYLESHEET))
        for py in UI_DIR.glob("*.py"):
            with self.subTest(file=py.name):
                src = py.read_text(encoding="utf-8")
                self.assertNotIn("setPixelSize", src)
                self.assertNotIn("setPointSize(-1", src)

    def test_font_sizes_use_points(self):
        sizes = re.findall(r"font-size\s*:\s*([\d.]+)(\w+)", styles.STYLESHEET)
        self.assertTrue(sizes)
        self.assertTrue(all(unit == "pt" for _, unit in sizes))

    def test_no_hardcoded_font_family_or_window_colours(self):
        """Fonts and base colours must come from the system theme."""
        css = styles.STYLESHEET
        self.assertNotIn("font-family", css)
        for rule in ("QMainWindow", "QDialog", "QLineEdit", "QListWidget", "QMenu", "QTabBar", "QWidget {"):
            self.assertNotIn(rule, css)
        self.assertNotIn("#1e1e2e", css)  # old fixed dark background

    def test_uses_system_palette(self):
        self.assertIn("palette(highlight)", styles.STYLESHEET)

    def test_braces_balanced(self):
        self.assertEqual(styles.STYLESHEET.count("{"), styles.STYLESHEET.count("}"))


class ChooseStyleTests(unittest.TestCase):
    def test_windows_prefers_windows11_then_fusion(self):
        self.assertEqual(styles.choose_style_name(["windowsvista", "Windows", "Fusion", "windows11"], "win32"),
                         "windows11")
        self.assertEqual(styles.choose_style_name(["windowsvista", "Windows", "Fusion"], "win32"), "Fusion")

    def test_other_platforms_keep_native_style(self):
        self.assertIsNone(styles.choose_style_name(["Fusion", "macos"], "darwin"))
        self.assertIsNone(styles.choose_style_name(["Fusion", "Windows"], "linux"))

    def test_nothing_suitable(self):
        self.assertIsNone(styles.choose_style_name(["windowsvista"], "win32"))


if __name__ == "__main__":
    unittest.main()

"""Qt-free styling helpers.

The application deliberately does NOT hard-code a colour scheme: the window,
text, list and input colours all come from the operating system (light or
dark).  The few rules below only add shape and use ``palette(...)`` so they
follow the system too.  All font sizes use ``pt`` - pixel sizes in a global
stylesheet are what trigger Qt's
"QFont::setPointSize: Point size <= 0 (-1)" warning.
"""
from __future__ import annotations

STYLESHEET = """
QLabel#Title { font-size: 15pt; font-weight: bold; }
QLabel#Hint, QLabel#Status { color: palette(placeholder-text); }
QLabel#Error { color: #d1495b; }

QPushButton#PrimaryButton {
    background-color: palette(highlight); color: palette(highlighted-text);
    border: none; border-radius: 6px; padding: 6px 14px; font-weight: bold;
}
QPushButton#PinButton {
    background-color: #2ea043; color: #ffffff;
    border: none; border-radius: 6px; padding: 6px 14px; font-weight: bold;
}
QPushButton#UnpinButton {
    background-color: #d1495b; color: #ffffff;
    border: none; border-radius: 6px; padding: 6px 14px; font-weight: bold;
}
QPushButton#OpenButton {
    background-color: #2ea043; color: #ffffff;
    border: none; border-radius: 5px; padding: 2px 12px; font-weight: bold;
}
QPushButton#PrimaryButton:hover, QPushButton#PinButton:hover, QPushButton#UnpinButton:hover,
QPushButton#OpenButton:hover {
    border: 2px solid palette(window-text);
}
QPushButton#PrimaryButton:disabled, QPushButton#PinButton:disabled, QPushButton#UnpinButton:disabled,
QPushButton#OpenButton:disabled {
    background-color: palette(mid); color: palette(placeholder-text); border: none;
}
QTreeWidget { padding: 4px; }
QTreeWidget::item { padding: 4px 2px; }
"""


def choose_style_name(available: list[str], platform: str) -> str | None:
    """Which Qt style gives proper light/dark support on this platform.

    * Windows: ``windows11`` (Qt >= 6.7) else ``Fusion`` - the classic
      ``windowsvista`` style ignores the system dark mode.
    * macOS / Linux: keep Qt's native default, which already follows the OS.
    """
    if platform.startswith("win"):
        lowered = {name.lower(): name for name in available}
        for wanted in ("windows11", "fusion"):
            if wanted in lowered:
                return lowered[wanted]
    return None

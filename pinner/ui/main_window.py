"""Top-level window: tabs + 'keep this window on top' switch."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QHBoxLayout, QLabel, QMainWindow, QTabWidget, QVBoxLayout, QWidget,
)

from .. import APP_NAME
from ..core.launcher import Launcher
from ..core.models import Section
from ..core.repository import Repository
from ..core.window_pinner import WindowPinner
from .icons import IconProvider
from .section_widget import SectionWidget
from .window_pinner_panel import WindowPinnerPanel

SETTING_SELF_ON_TOP = "self_always_on_top"
SETTING_KEEP_PINS = "keep_pins_after_exit"


class MainWindow(QMainWindow):
    def __init__(self, repo: Repository, launcher: Launcher | None = None,
                 pinner: WindowPinner | None = None, icons: IconProvider | None = None) -> None:
        super().__init__()
        self.repo = repo
        self.icons = icons or IconProvider()
        self.launcher = launcher or Launcher()
        self.pinner = pinner or WindowPinner(own_titles=(APP_NAME,))

        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(self.icons.get("app"))
        self.resize(980, 680)
        self.setMinimumSize(700, 480)

        title = QLabel(f"📁 {APP_NAME}")
        title.setObjectName("Title")
        self.on_top_check = QCheckBox(f"Keep {APP_NAME} always on top")
        self.on_top_check.toggled.connect(self.set_stay_on_top)

        header = QHBoxLayout()
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self.on_top_check)

        self.paths_tab = SectionWidget(Section.PATHS, repo, self.launcher, self.icons)
        self.browser_tab = SectionWidget(Section.BROWSER, repo, self.launcher, self.icons)
        self.pinner_tab = WindowPinnerPanel(self.pinner, self.icons)

        self.tabs = QTabWidget()
        self.tabs.addTab(self.paths_tab, self.icons.get("folder"), "Paths")
        self.tabs.addTab(self.browser_tab, self.icons.get("url"), "Browser Bookmarks")
        self.tabs.addTab(self.pinner_tab, self.icons.get("window_pin"), "Always on Top")
        self.tabs.currentChanged.connect(self._tab_changed)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(8)
        layout.addLayout(header)
        layout.addWidget(self.tabs, 1)
        self.setCentralWidget(central)

        self.pinner_tab.keep_after_exit_changed.connect(lambda on: self.repo.set_bool(SETTING_KEEP_PINS, on))
        self.pinner_tab.set_keep_after_exit(self.repo.get_bool(SETTING_KEEP_PINS, False))   # default: unchecked

        # Pinned windows must not outlive the app unless the user opted in: release on window close AND on quit.
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.release_pinned_windows)

        saved = self.repo.get_bool(SETTING_SELF_ON_TOP, False)
        self.on_top_check.setChecked(saved)  # triggers set_stay_on_top when True

    def set_stay_on_top(self, enabled: bool) -> None:
        """Toggle Qt's always-on-top hint for this window and remember the choice."""
        visible = self.isVisible()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, enabled)
        if visible:  # changing window flags hides the window
            self.show()
        self.repo.set_bool(SETTING_SELF_ON_TOP, enabled)

    def is_stay_on_top(self) -> bool:
        return bool(self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)

    def release_pinned_windows(self) -> int:
        """Un-pin our windows when the app stops (unless 'Active after the application stop' is ticked)."""
        return self.pinner.release_on_exit()

    def closeEvent(self, event) -> None:
        self.release_pinned_windows()
        super().closeEvent(event)

    def _tab_changed(self, index: int) -> None:
        if self.tabs.widget(index) is self.pinner_tab:
            self.pinner_tab.load_windows()

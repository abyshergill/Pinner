"""'Always on Top' tab - choose windows from a drop-down, preview them, set their priority."""
from __future__ import annotations

from PyQt6.QtCore import QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core.window_pinner import WindowPinError, WindowPinner, WindowSnapshot
from . import prompts
from .icons import IconProvider

HWND_ROLE = Qt.ItemDataRole.UserRole
PREVIEW_SIZE = QSize(420, 260)
PREVIEW_DELAY_MS = 150
NO_SELECTION_TEXT = "Select a window to see a preview"
NO_PREVIEW_TEXT = "Preview not available\n(minimised, protected or closed window)"


def snapshot_to_pixmap(snap: WindowSnapshot, size: QSize = PREVIEW_SIZE) -> QPixmap:
    """Convert a raw BGRX snapshot to a pixmap scaled to fit ``size``."""
    image = QImage(snap.data, snap.width, snap.height, snap.stride, QImage.Format.Format_RGB32).copy()
    return QPixmap.fromImage(image).scaled(
        size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)


class WindowPinnerPanel(QWidget):
    keep_after_exit_changed = pyqtSignal(bool)

    def __init__(self, pinner: WindowPinner, icons: IconProvider, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.pinner = pinner
        self.icons = icons
        self._titles: dict[int, str] = {}
        self._topmost: dict[int, bool] = {}
        self._pending_preview: int | None = None
        self._build_ui()
        self.load_windows()

    # ================================================================ UI
    def _build_ui(self) -> None:
        title = QLabel("Always on Top")
        title.setObjectName("Title")

        # --- choose a window + priority
        self.window_combo = QComboBox()
        self.window_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.window_combo.setMinimumContentsLength(30)
        self.window_combo.setMaxVisibleItems(18)
        self.window_combo.currentIndexChanged.connect(lambda _i=0: self._schedule_preview(self.selected_hwnd()))
        self.btn_refresh = QPushButton("Refresh")
        self.btn_refresh.clicked.connect(lambda _checked=False: self.load_windows())

        window_row = QHBoxLayout()
        window_row.addWidget(QLabel("Window"))
        window_row.addWidget(self.window_combo, 1)
        window_row.addWidget(self.btn_refresh)

        self.priority_combo = QComboBox()
        self.btn_pin = QPushButton("Pin on Top")
        self.btn_pin.setObjectName("PinButton")
        self.btn_pin.clicked.connect(lambda _checked=False: self.pin_selected())

        priority_row = QHBoxLayout()
        priority_row.addWidget(QLabel("Priority"))
        priority_row.addWidget(self.priority_combo)
        priority_row.addWidget(self.btn_pin)
        priority_row.addStretch(1)

        hint = QLabel("Priority 1 is shown above every other pinned window, 2 above 3, and so on.")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)

        self.keep_after_exit_check = QCheckBox("Active after the application stop")
        self.keep_after_exit_check.setChecked(False)       # default: pins end with the app
        self.keep_after_exit_check.setToolTip(
            "Unchecked (default): pinned windows are released when Pinner closes.\n"
            "Checked: they stay always-on-top after Pinner closes.\n"
            "You can then undo it by closing the window, or by pinning/unpinning it again in Pinner.")
        self.keep_after_exit_check.toggled.connect(self._on_keep_after_exit_toggled)

        # --- preview (left)
        self.preview_label = QLabel(NO_SELECTION_TEXT)
        self.preview_label.setObjectName("Hint")
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setFrameShape(QFrame.Shape.StyledPanel)
        self.preview_label.setMinimumSize(PREVIEW_SIZE)
        self.preview_caption = QLabel("")
        self.preview_caption.setObjectName("Status")
        self.preview_caption.setWordWrap(True)
        self.btn_refresh_preview = QPushButton("Refresh preview")
        self.btn_refresh_preview.clicked.connect(lambda _checked=False: self.show_preview(self._current_preview_hwnd()))

        preview_col = QVBoxLayout()
        preview_col.addWidget(QLabel("Preview"))
        preview_col.addWidget(self.preview_label)
        preview_col.addWidget(self.preview_caption)
        preview_col.addWidget(self.btn_refresh_preview)
        preview_col.addStretch(1)

        # --- pinned windows, in priority order (right)
        self.pinned_list = QListWidget()
        self.pinned_list.currentItemChanged.connect(lambda *_: self._schedule_preview(self.selected_pinned_hwnd()))
        self.btn_raise = QPushButton("▲ Higher")
        self.btn_raise.clicked.connect(lambda _checked=False: self.move_selected(-1))
        self.btn_lower = QPushButton("▼ Lower")
        self.btn_lower.clicked.connect(lambda _checked=False: self.move_selected(+1))
        self.btn_unpin = QPushButton("Unpin")
        self.btn_unpin.setObjectName("UnpinButton")
        self.btn_unpin.clicked.connect(lambda _checked=False: self.unpin_selected())
        self.btn_unpin_all = QPushButton("Unpin all")
        self.btn_unpin_all.clicked.connect(lambda _checked=False: self.unpin_all())

        buttons = QHBoxLayout()
        for b in (self.btn_raise, self.btn_lower, self.btn_unpin, self.btn_unpin_all):
            buttons.addWidget(b)

        pinned_col = QVBoxLayout()
        pinned_col.addWidget(QLabel("Pinned windows (highest priority first)"))
        pinned_col.addWidget(self.pinned_list, 1)
        pinned_col.addLayout(buttons)

        middle = QHBoxLayout()
        middle.setSpacing(16)
        middle.addLayout(preview_col)
        middle.addLayout(pinned_col, 1)

        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("Status")

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.addWidget(title)
        layout.addLayout(window_row)
        layout.addLayout(priority_row)
        layout.addWidget(hint)
        layout.addWidget(self.keep_after_exit_check)
        layout.addLayout(middle, 1)
        layout.addWidget(self.status_label)

        # debounce: don't screenshot on every arrow-key press in the drop-down
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(PREVIEW_DELAY_MS)
        self._preview_timer.timeout.connect(lambda: self.show_preview(self._pending_preview))

        if not self.pinner.available:
            for w in (self.window_combo, self.priority_combo, self.btn_refresh, self.btn_pin, self.pinned_list,
                      self.btn_raise, self.btn_lower, self.btn_unpin, self.btn_unpin_all, self.btn_refresh_preview,
                      self.keep_after_exit_check):
                w.setEnabled(False)
            self.status_label.setText(self.pinner.reason)

    # ===================================================== after-exit option
    def _on_keep_after_exit_toggled(self, checked: bool) -> None:
        self.pinner.keep_pinned_on_exit = bool(checked)
        self.keep_after_exit_changed.emit(bool(checked))
        self.status_label.setText(
            "Pinned windows will STAY on top after Pinner closes." if checked
            else "Pinned windows will be released when Pinner closes.")

    def set_keep_after_exit(self, enabled: bool) -> None:
        self.keep_after_exit_check.setChecked(bool(enabled))

    # ============================================================ preview
    def _schedule_preview(self, hwnd: int | None) -> None:
        self._pending_preview = hwnd
        self._preview_timer.start()

    def _current_preview_hwnd(self) -> int | None:
        return self._pending_preview if self._pending_preview is not None else self.selected_hwnd()

    def show_preview(self, hwnd: int | None) -> bool:
        """Show a screenshot of ``hwnd``; returns False when none could be taken."""
        self._preview_timer.stop()
        self._pending_preview = hwnd
        if hwnd is None or not self.pinner.available:
            self._clear_preview(NO_SELECTION_TEXT)
            return False
        snap = self.pinner.snapshot(hwnd)
        title = self._titles.get(hwnd) or next((p.title for p in self.pinner.pinned if p.hwnd == hwnd), "")
        if snap is None or snap.width <= 0 or snap.height <= 0:
            self._clear_preview(NO_PREVIEW_TEXT)
            self.preview_caption.setText(title)
            return False
        self.preview_label.setPixmap(snapshot_to_pixmap(snap))
        self.preview_caption.setText(f"{title}  ·  {snap.width}×{snap.height}")
        return True

    def _clear_preview(self, text: str) -> None:
        self.preview_label.setPixmap(QPixmap())
        self.preview_label.setText(text)
        self.preview_caption.setText("")

    # ========================================================== refreshing
    def load_windows(self) -> None:
        """Re-read open windows into the drop-down (📌 marks windows already on top)."""
        if not self.pinner.available:
            return
        previous = self.selected_hwnd()
        windows = self.pinner.list_windows()
        self._titles = {w.hwnd: w.title for w in windows}
        self._topmost = {w.hwnd: w.is_topmost for w in windows}
        closed = self.pinner.prune(set(self._titles))
        self.window_combo.blockSignals(True)
        self.window_combo.clear()
        for w in windows:
            self.window_combo.addItem(("📌 " if w.is_topmost else "") + w.title, w.hwnd)
            self.window_combo.setItemData(self.window_combo.count() - 1, w.title, Qt.ItemDataRole.ToolTipRole)
        index = self.window_combo.findData(previous) if previous is not None else -1
        if index >= 0:
            self.window_combo.setCurrentIndex(index)
        self.window_combo.blockSignals(False)
        self.refresh_pinned()
        self.status_label.setText("Some pinned windows were closed and were removed." if closed
                                  else f"Loaded {len(windows)} open windows.")
        self._schedule_preview(self.selected_hwnd())

    def refresh_pinned(self, select_hwnd: int | None = None) -> None:
        """Rebuild the priority list and the priority drop-down."""
        keep = select_hwnd if select_hwnd is not None else self.selected_pinned_hwnd()
        self.pinned_list.blockSignals(True)
        self.pinned_list.clear()
        pinned = self.pinner.pinned
        for rank, p in enumerate(pinned, start=1):
            row = QListWidgetItem(f"{rank}.  {p.title}")
            row.setData(HWND_ROLE, p.hwnd)
            row.setToolTip(p.title)
            self.pinned_list.addItem(row)
            if p.hwnd == keep:
                self.pinned_list.setCurrentItem(row)
        self.pinned_list.blockSignals(False)
        self._fill_priorities(len(pinned))

    def _fill_priorities(self, pinned_count: int) -> None:
        self.priority_combo.clear()
        for rank in range(1, pinned_count + 2):
            label = f"{rank}  (highest)" if rank == 1 else str(rank)
            self.priority_combo.addItem(label, rank)

    # =========================================================== selection
    def selected_hwnd(self) -> int | None:
        data = self.window_combo.currentData()
        return int(data) if data is not None else None

    def selected_priority(self) -> int:
        data = self.priority_combo.currentData()
        return int(data) if data is not None else 1

    def selected_pinned_hwnd(self) -> int | None:
        row = self.pinned_list.currentItem()
        return row.data(HWND_ROLE) if row else None

    # ============================================================== actions
    def pin_selected(self) -> None:
        hwnd = self.selected_hwnd()
        if hwnd is None:
            prompts.show_warning(self, "Please select a window from the drop-down first!", "Selection Error")
            return
        title = self._titles.get(hwnd, "")
        try:
            self.pinner.pin(hwnd, title, self.selected_priority(), was_topmost=self._topmost.get(hwnd, False))
        except WindowPinError as exc:
            prompts.show_error(self, str(exc), "Execution Error")
            self.refresh_pinned()
            return
        self.refresh_pinned(select_hwnd=hwnd)
        self.status_label.setText(f"'{title[:40]}' pinned with priority {self.pinner.priority_of(hwnd)}.")

    def move_selected(self, delta: int) -> None:
        """Raise (-1) or lower (+1) the selected pinned window's priority."""
        hwnd = self.selected_pinned_hwnd()
        if hwnd is None:
            return
        current = self.pinner.priority_of(hwnd)
        if current is None:
            return
        try:
            self.pinner.move(hwnd, current + delta)
        except WindowPinError as exc:
            prompts.show_error(self, str(exc), "Execution Error")
        self.refresh_pinned(select_hwnd=hwnd)

    def unpin_selected(self) -> None:
        hwnd = self.selected_pinned_hwnd()
        if hwnd is None:
            prompts.show_warning(self, "Select a pinned window in the list first!", "Selection Error")
            return
        title = self._titles.get(hwnd) or next((p.title for p in self.pinner.pinned if p.hwnd == hwnd), "")
        try:
            self.pinner.unpin(hwnd)
        except WindowPinError as exc:
            prompts.show_error(self, str(exc), "Execution Error")
        self.load_windows()
        self.status_label.setText(f"'{title[:40]}' unpinned.")

    def unpin_all(self) -> None:
        try:
            self.pinner.unpin_all()
        except WindowPinError as exc:
            prompts.show_error(self, str(exc), "Execution Error")
        self.load_windows()
        self.status_label.setText("All windows unpinned.")

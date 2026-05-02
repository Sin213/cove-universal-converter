from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QPoint,
    QPropertyAnimation,
    QSize,
    Qt,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QDesktopServices,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
    QIcon,
    QKeySequence,
    QMouseEvent,
    QPainter,
    QPixmap,
    QShortcut,
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from cove_converter import __version__, updater
from cove_converter.binaries import resource_path
from cove_converter.engines import worker_for
from cove_converter.routing import (
    SUPPORTED_FORMATS,
    effective_suffix,
    engine_for,
    info_for,
    targets_for,
)
from cove_converter.settings import ConversionSettings, default_settings
from cove_converter.ui.drop_zone import DropZone
from cove_converter.ui.file_row import FileRow, unique_path
from cove_converter.ui.formats_dialog import FormatsDialog
from cove_converter.ui.quality_dialog import QualityDialog
from cove_converter.ui.theme import BORDER_STRONG, SURFACE_2, category_for


_COL_FILE, _COL_TARGET, _COL_PROGRESS, _COL_STATUS = range(4)


# ---------------------------------------------------------------------------
# Inline SVG icons (so the bundle doesn't need separate icon assets)
# ---------------------------------------------------------------------------

_SVG_MIN = b"""<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 12 12' fill='none'
 stroke='currentColor' stroke-width='1.4' stroke-linecap='round'><path d='M2 6h8'/></svg>"""

_SVG_MAX = b"""<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 12 12' fill='none'
 stroke='currentColor' stroke-width='1.2'><rect x='2.5' y='2.5' width='7' height='7' rx='0.5'/></svg>"""

_SVG_CLOSE = b"""<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 12 12' fill='none'
 stroke='currentColor' stroke-width='1.4' stroke-linecap='round'><path d='M3 3l6 6M9 3l-6 6'/></svg>"""

_SVG_ARROW = b"""<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none'
 stroke='currentColor' stroke-width='2.2' stroke-linecap='round' stroke-linejoin='round'>
 <path d='M5 12h14'/><path d='m13 6 6 6-6 6'/></svg>"""

_SVG_GEAR = b"""<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none'
 stroke='currentColor' stroke-width='1.7' stroke-linecap='round' stroke-linejoin='round'>
 <circle cx='12' cy='12' r='3'/>
 <path d='M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1Z'/>
</svg>"""

_SVG_FOLDER = b"""<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none'
 stroke='currentColor' stroke-width='1.8' stroke-linecap='round' stroke-linejoin='round'>
 <path d='M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Z'/></svg>"""

_SVG_FOLDER_OPEN = b"""<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none'
 stroke='currentColor' stroke-width='1.8' stroke-linecap='round' stroke-linejoin='round'>
 <path d='M6 14 4 19a1 1 0 0 0 .94 1.34h13.45a1 1 0 0 0 .95-.69l1.93-5.85A1 1 0 0 0 20.32 12H8.06a1 1 0 0 0-.95.69L6 14Z'/>
 <path d='M3 17V6a2 2 0 0 1 2-2h3l2 2h6a2 2 0 0 1 2 2v3'/></svg>"""

_SVG_FILE_OPEN = b"""<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none'
 stroke='currentColor' stroke-width='1.8' stroke-linecap='round' stroke-linejoin='round'>
 <path d='M14 3v4a1 1 0 0 0 1 1h4'/>
 <path d='M19 9v10a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h7'/>
 <path d='m15 14 4-4M19 14v-4h-4'/></svg>"""

_SVG_X_SMALL = b"""<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 10' fill='none'
 stroke='currentColor' stroke-width='1.6' stroke-linecap='round'><path d='M2 2l6 6M8 2l-6 6'/></svg>"""

_SVG_FILE = b"""<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none'
 stroke='currentColor' stroke-width='1.6' stroke-linecap='round' stroke-linejoin='round'>
 <path d='M14 3v4a1 1 0 0 0 1 1h4'/>
 <path d='M17 21H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h7l5 5v11a2 2 0 0 1-2 2Z'/></svg>"""


_PIXMAP_CACHE: dict[tuple[int, int, str | None], QPixmap] = {}


def _screen_dpr() -> float:
    from PySide6.QtGui import QGuiApplication
    screen = QGuiApplication.primaryScreen()
    return float(screen.devicePixelRatio()) if screen is not None else 1.0


def _icon_pixmap(svg_bytes: bytes, size: int, color: str | None = None) -> QPixmap:
    """Render an inline SVG into a transparent, HiDPI-aware QPixmap.

    Cached by ``(svg_id, size, color)`` so the same icon isn't re-rasterized
    every time it's used."""
    key = (id(svg_bytes), size, color)
    cached = _PIXMAP_CACHE.get(key)
    if cached is not None:
        return cached

    src = svg_bytes
    if color and b"currentColor" in src:
        src = src.replace(b"currentColor", color.encode())
    dpr = _screen_dpr()
    px = max(1, int(round(size * dpr)))
    renderer = QSvgRenderer(src)
    pm = QPixmap(px, px)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    renderer.render(p)
    p.end()
    pm.setDevicePixelRatio(dpr)
    _PIXMAP_CACHE[key] = pm
    return pm


def _hidpi_pixmap(path: Path, size: int) -> QPixmap:
    """Load a raster icon and scale to ``size`` logical pixels with crisp
    HiDPI handling — render at ``size * devicePixelRatio`` physical pixels
    and tag the pixmap so Qt draws it at the right logical size."""
    src = QPixmap(str(path))
    if src.isNull():
        return src
    dpr = _screen_dpr()
    px = max(1, int(round(size * dpr)))
    pm = src.scaled(
        px, px,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    pm.setDevicePixelRatio(dpr)
    return pm


def _make_icon_button(svg: bytes, size: int = 14, *, object_name: str = "tbBtn",
                      tooltip: str = "", color: str = "#ececf1",
                      parent=None) -> QToolButton:
    btn = QToolButton(parent)
    btn.setObjectName(object_name)
    btn.setIcon(QIcon(_icon_pixmap(svg, size, color=color)))
    btn.setIconSize(QSize(size, size))
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    if tooltip:
        btn.setToolTip(tooltip)
    return btn


# ---------------------------------------------------------------------------
# Title bar
# ---------------------------------------------------------------------------


class TitleBar(QFrame):
    """Frameless-window title bar: icon + centered title/version + min/max/close.

    Drag anywhere on the bar (outside the buttons) to move the window using
    the platform's native window-move (so it works across X11/Wayland)."""

    minimize_clicked = Signal()
    maximize_clicked = Signal()
    close_clicked = Signal()

    HEIGHT = 44

    def __init__(self, version: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("titleBar")
        self.setFixedHeight(self.HEIGHT)
        self.setMouseTracking(True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 6, 0)
        layout.setSpacing(12)

        # ---- Icon (no surrounding box; icon stands on its own) ----
        icon_label = QLabel(self)
        icon_label.setObjectName("tbIcon")
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setFixedSize(28, 28)
        icon_path = resource_path("cove_icon.png")
        if icon_path.is_file():
            icon_label.setPixmap(_hidpi_pixmap(icon_path, 26))
        layout.addWidget(icon_label)

        layout.addStretch(1)

        # ---- Centered title (overlaid so the spacers stay flexible) ----
        center_wrap = QWidget(self)
        center_wrap.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        center_lay = QHBoxLayout(center_wrap)
        center_lay.setContentsMargins(0, 0, 0, 0)
        center_lay.setSpacing(10)
        center_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title = QLabel("Cove Universal Converter", center_wrap)
        title.setObjectName("tbTitle")
        center_lay.addWidget(title)

        version_chip = QLabel(f"v{version}", center_wrap)
        version_chip.setObjectName("tbVersion")
        center_lay.addWidget(version_chip)

        self._center_wrap = center_wrap
        center_wrap.setParent(self)
        center_wrap.show()

        # ---- Window controls ----
        controls = QWidget(self)
        ctrl_lay = QHBoxLayout(controls)
        ctrl_lay.setContentsMargins(0, 0, 0, 0)
        ctrl_lay.setSpacing(2)

        self._btn_min = _make_icon_button(
            _SVG_MIN, 12, tooltip="Minimize", color="#ececf1", parent=controls,
        )
        self._btn_min.setFixedSize(36, 30)
        self._btn_max = _make_icon_button(
            _SVG_MAX, 12, tooltip="Maximize", color="#ececf1", parent=controls,
        )
        self._btn_max.setFixedSize(36, 30)
        self._btn_close = _make_icon_button(
            _SVG_CLOSE, 12,
            object_name="tbBtnClose", tooltip="Close", color="#ececf1", parent=controls,
        )
        self._btn_close.setFixedSize(36, 30)

        self._btn_min.clicked.connect(self.minimize_clicked.emit)
        self._btn_max.clicked.connect(self.maximize_clicked.emit)
        self._btn_close.clicked.connect(self.close_clicked.emit)

        ctrl_lay.addWidget(self._btn_min)
        ctrl_lay.addWidget(self._btn_max)
        ctrl_lay.addWidget(self._btn_close)
        layout.addWidget(controls)

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        # Center the title overlay across the full bar width.
        self._center_wrap.setGeometry(0, 0, self.width(), self.HEIGHT)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self.window().windowHandle()
            if handle is not None:
                handle.startSystemMove()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.maximize_clicked.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


# ---------------------------------------------------------------------------
# Per-row widgets in the queue table
# ---------------------------------------------------------------------------


class _FileCell(QWidget):
    """File column: format-tinted ext badge + name + size, vertically centered."""

    def __init__(self, name: str, size: str, ext: str, parent=None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 6, 8, 6)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        badge = QLabel(ext.replace(".", "").upper(), self)
        badge.setObjectName("fbadge")
        badge.setProperty("cat", category_for(ext))
        badge.setFixedSize(34, 28)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(badge, alignment=Qt.AlignmentFlag.AlignVCenter)

        text_wrap = QWidget(self)
        text_col = QVBoxLayout(text_wrap)
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(2)
        text_col.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self._name = QLabel(name, text_wrap)
        self._name.setObjectName("fname")
        self._name.setToolTip(name)
        self._name.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        # Allow truncation rather than overflowing the cell.
        self._name.setMinimumWidth(0)
        self._name.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        text_col.addWidget(self._name)

        self._size = QLabel(size, text_wrap)
        self._size.setObjectName("fsize")
        text_col.addWidget(self._size)
        layout.addWidget(text_wrap, stretch=1, alignment=Qt.AlignmentFlag.AlignVCenter)


class _TargetCombo(QComboBox):
    def __init__(self, ext: str, current: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("qtarget")
        for t in targets_for(ext):
            self.addItem(t)
        self.setCurrentText(current)
        self.setCursor(Qt.CursorShape.PointingHandCursor)


class _ProgressCell(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 12, 8)
        layout.setSpacing(10)

        self.bar = QProgressBar(self)
        self.bar.setObjectName("qbar")
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(6)
        layout.addWidget(self.bar, stretch=1)

        self.pct = QLabel("—", self)
        self.pct.setObjectName("qpct")
        self.pct.setMinimumWidth(36)
        self.pct.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.pct)

    def set_progress(self, pct: int, *, state: str = "") -> None:
        self.bar.setValue(int(pct))
        # Only re-polish when the state actually changes — repolishing on
        # every progress tick is expensive and visually pointless.
        if self.bar.property("state") != state:
            self.bar.setProperty("state", state)
            self.bar.style().unpolish(self.bar)
            self.bar.style().polish(self.bar)
        if state == "done":
            self.pct.setText("100%")
        elif state == "ready":
            self.pct.setText("—")
        else:
            self.pct.setText(f"{int(pct)}%")


class _StatusCell(QWidget):
    _LABELS = {
        "ready":      ("Ready",      ""),
        "queued":     ("Queued",     "queued"),
        "processing": ("Processing", "processing"),
        "done":       ("Done",       "done"),
        "failed":     ("Failed",     "failed"),
        "unsupported": ("Unsupported", "failed"),
        "cancelled":  ("Cancelled",  ""),
    }

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 14, 8)
        layout.setSpacing(0)
        layout.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.chip = QLabel("Ready", self)
        self.chip.setObjectName("statChip")
        self.chip.setProperty("state", "")
        layout.addWidget(self.chip)

    def set_state(self, state: str, label: str | None = None) -> None:
        cfg = self._LABELS.get(state, ("Ready", ""))
        self.chip.setText(label or cfg[0])
        if self.chip.property("state") != cfg[1]:
            self.chip.setProperty("state", cfg[1])
            self.chip.style().unpolish(self.chip)
            self.chip.style().polish(self.chip)


# ---------------------------------------------------------------------------
# Toast
# ---------------------------------------------------------------------------


class _Toast(QFrame):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("toast")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 9, 16, 9)
        layout.setSpacing(10)

        self._pip = QLabel(self)
        self._pip.setObjectName("toastPip")
        self._pip.setFixedSize(7, 7)
        layout.addWidget(self._pip)

        self._label = QLabel("", self)
        self._label.setObjectName("toastText")
        layout.addWidget(self._label)

        effect = QGraphicsOpacityEffect(self)
        effect.setOpacity(0.0)
        self.setGraphicsEffect(effect)
        self._effect = effect

        self._anim = QPropertyAnimation(effect, b"opacity", self)
        self._anim.setDuration(180)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fading_out = False
        self._anim.finished.connect(self._on_anim_finished)

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._fade_out)
        self.hide()

    def show_message(self, text: str, kind: str = "good") -> None:
        self._label.setText(text)
        color = {"good": "#3ddc97", "warn": "#ffb454", "bad": "#ff6b6b"}.get(kind, "#3ddc97")
        self._pip.setStyleSheet(f"background: {color}; border-radius: 3px;")
        # Anchored just below the title bar so it never overlaps the action
        # row at the bottom (which now hosts the "Show output folder" button).
        if self.parentWidget() is not None:
            self.adjustSize()
            pw = self.parentWidget().width()
            self.move((pw - self.width()) // 2, 56)
        self.show()
        self.raise_()
        self._anim.stop()
        self._fading_out = False
        self._anim.setStartValue(self._effect.opacity())
        self._anim.setEndValue(1.0)
        self._anim.start()
        self._hide_timer.start(2400)

    def _fade_out(self) -> None:
        self._anim.stop()
        self._fading_out = True
        self._anim.setStartValue(self._effect.opacity())
        self._anim.setEndValue(0.0)
        self._anim.start()

    def _on_anim_finished(self) -> None:
        if self._fading_out and self._effect.opacity() < 0.05:
            self.hide()
            self._fading_out = False


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------


# Width of resize-grip border around the frameless window.
_RESIZE_MARGIN = 6


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"Cove Universal Converter v{__version__}")
        self.resize(1000, 700)
        self.setMinimumSize(820, 560)

        # Frameless + transparent so the rounded chrome shows.
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)

        icon_file = resource_path("cove_icon.png")
        if icon_file.is_file():
            self.setWindowIcon(QIcon(str(icon_file)))

        self.setAcceptDrops(True)

        self._rows: list[FileRow] = []
        self._row_widgets: list[dict] = []  # parallel list of cell widgets
        self._output_dir: Path | None = None
        self._settings: ConversionSettings = default_settings()

        self._pending_indices: list[int] = []
        self._active_indices: set[int] = set()
        self._batch_done = 0
        self._batch_failed = 0
        self._batch_skipped = 0
        self._batch_total = 0

        # ---- Frameless chrome ----
        outer = QWidget(self)
        outer.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        outer_layout = QVBoxLayout(outer)
        outer_layout.setContentsMargins(_RESIZE_MARGIN, _RESIZE_MARGIN, _RESIZE_MARGIN, _RESIZE_MARGIN)
        outer_layout.setSpacing(0)

        chrome = QFrame(outer)
        chrome.setObjectName("chromeRoot")
        chrome.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        # eventFilter(self) on chrome catches Enter events so we can clear
        # the resize cursor when the mouse leaves the margin into the content.
        chrome.installEventFilter(self)
        self._chrome = chrome
        outer_layout.addWidget(chrome, stretch=1)

        chrome_layout = QVBoxLayout(chrome)
        chrome_layout.setContentsMargins(0, 0, 0, 0)
        chrome_layout.setSpacing(0)

        self.title_bar = TitleBar(__version__, chrome)
        self.title_bar.minimize_clicked.connect(self.showMinimized)
        self.title_bar.maximize_clicked.connect(self._toggle_max)
        self.title_bar.close_clicked.connect(self.close)
        chrome_layout.addWidget(self.title_bar)

        # ---- Main content ----
        content = QWidget(chrome)
        content.setObjectName("chromeContent")
        chrome_layout.addWidget(content, stretch=1)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(14)

        self.drop_zone = DropZone()
        self.drop_zone.clicked.connect(self._browse_files)
        self.drop_zone.info_requested.connect(self._show_formats_dialog)
        layout.addWidget(self.drop_zone)

        layout.addWidget(self._build_queue(), stretch=1)
        layout.addLayout(self._build_save_row())
        layout.addLayout(self._build_action_row())

        self.setCentralWidget(outer)

        # ---- Toast (overlay) ----
        self._toast = _Toast(self)

        # ---- Shortcuts: delete to remove rows, Esc to clear-all? Just delete. ----
        del_sc = QShortcut(QKeySequence(Qt.Key.Key_Delete), self.table)
        del_sc.activated.connect(self._remove_selected_rows)
        bs_sc = QShortcut(QKeySequence(Qt.Key.Key_Backspace), self.table)
        bs_sc.activated.connect(self._remove_selected_rows)

        # ---- Updater ----
        self._updater = updater.UpdateController(
            parent=self,
            current_version=__version__,
            repo="Sin213/cove-universal-converter",
            app_display_name="Cove Universal Converter",
            cache_subdir="cove-universal-converter",
        )
        QTimer.singleShot(4000, self._updater.check)

    # =========================================================
    # Layout builders
    # =========================================================

    def _build_queue(self) -> QFrame:
        wrap = QFrame()
        wrap.setObjectName("queue")
        wrap.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        wrap_lay = QVBoxLayout(wrap)
        wrap_lay.setContentsMargins(0, 0, 0, 0)
        wrap_lay.setSpacing(0)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["File", "Convert to", "Progress", "Status"])
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setFrameShape(QFrame.Shape.NoFrame)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        self.table.verticalHeader().setDefaultSectionSize(56)
        self.table.setStyleSheet("QTableWidget { background: transparent; }")

        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(_COL_FILE, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(_COL_TARGET, QHeaderView.ResizeMode.Fixed)
        hh.setSectionResizeMode(_COL_PROGRESS, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(_COL_STATUS, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(_COL_TARGET, 110)
        self.table.setColumnWidth(_COL_STATUS, 130)

        wrap_lay.addWidget(self.table)

        # Empty-state overlay (shown when there are no rows)
        self._empty_state = QWidget(wrap)
        empty_lay = QVBoxLayout(self._empty_state)
        empty_lay.setContentsMargins(20, 30, 20, 30)
        empty_lay.setSpacing(10)
        empty_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Bigger, clearly-tinted file icon framed in a soft surface tile so
        # it reads at a glance instead of disappearing into the background.
        ico_tile = QFrame(self._empty_state)
        ico_tile.setFixedSize(56, 56)
        ico_tile.setStyleSheet(
            f"background: {SURFACE_2}; border: 1px solid {BORDER_STRONG};"
            "border-radius: 12px;"
        )
        tile_lay = QVBoxLayout(ico_tile)
        tile_lay.setContentsMargins(0, 0, 0, 0)
        tile_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ico = QLabel(ico_tile)
        ico.setPixmap(_icon_pixmap(_SVG_FILE, 28, color="#9a9aae"))
        ico.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tile_lay.addWidget(ico)
        empty_lay.addWidget(ico_tile, alignment=Qt.AlignmentFlag.AlignCenter)

        et = QLabel("No files in the queue", self._empty_state)
        et.setObjectName("emptyT")
        et.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_lay.addWidget(et)

        es = QLabel("drop above or click the zone to add files", self._empty_state)
        es.setObjectName("emptyS")
        es.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_lay.addWidget(es)

        wrap_lay.addWidget(self._empty_state, stretch=1)
        self._update_empty_state()
        return wrap

    def _build_save_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)

        save_label = QLabel("Save to:")
        save_label.setObjectName("saveLabel")
        row.addWidget(save_label)

        self._save_input = QFrame()
        self._save_input.setObjectName("saveInput")
        self._save_input.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._save_input.setFixedHeight(34)
        si_lay = QHBoxLayout(self._save_input)
        si_lay.setContentsMargins(12, 0, 8, 0)
        si_lay.setSpacing(6)

        self.dest_edit = QLineEdit(self._save_input)
        self.dest_edit.setObjectName("destEdit")
        self.dest_edit.setReadOnly(True)
        self.dest_edit.setPlaceholderText("Next to each source file")
        self.dest_edit.installEventFilter(self)
        si_lay.addWidget(self.dest_edit, stretch=1)

        self.dest_clear_btn = QToolButton(self._save_input)
        self.dest_clear_btn.setObjectName("clearInput")
        self.dest_clear_btn.setIcon(QIcon(_icon_pixmap(_SVG_X_SMALL, 16, color="#6b6b80")))
        self.dest_clear_btn.setIconSize(QSize(8, 8))
        self.dest_clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.dest_clear_btn.setToolTip("Reset — save next to each source file")
        self.dest_clear_btn.setVisible(False)
        self.dest_clear_btn.clicked.connect(self._clear_output_dir)
        si_lay.addWidget(self.dest_clear_btn)
        row.addWidget(self._save_input, stretch=1)

        self.dest_browse_btn = QPushButton(" Browse…")
        self.dest_browse_btn.setObjectName("btnGhost")
        self.dest_browse_btn.setIcon(QIcon(_icon_pixmap(_SVG_FOLDER, 26, color="#9a9aae")))
        self.dest_browse_btn.setIconSize(QSize(13, 13))
        self.dest_browse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.dest_browse_btn.clicked.connect(self._browse_output_dir)
        row.addWidget(self.dest_browse_btn)

        return row

    def _build_action_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)

        self.gear_btn = QToolButton()
        self.gear_btn.setObjectName("iconBtn")
        self.gear_btn.setIcon(QIcon(_icon_pixmap(_SVG_GEAR, 28, color="#9a9aae")))
        self.gear_btn.setIconSize(QSize(14, 14))
        self.gear_btn.setFixedSize(34, 34)
        self.gear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.gear_btn.setToolTip("Quality settings")
        self.gear_btn.clicked.connect(self._show_quality_dialog)
        row.addWidget(self.gear_btn)

        self.status_msg = QLabel("")
        self.status_msg.setObjectName("statusMsg")
        row.addWidget(self.status_msg)

        row.addStretch(1)

        # Revealed once a batch finishes with at least one successful output.
        self.open_file_btn = QPushButton(" Open file")
        self.open_file_btn.setObjectName("btnGhost")
        self.open_file_btn.setIcon(
            QIcon(_icon_pixmap(_SVG_FILE_OPEN, 26, color="#9a9aae")),
        )
        self.open_file_btn.setIconSize(QSize(13, 13))
        self.open_file_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_file_btn.setToolTip("Open the most recent converted file")
        self.open_file_btn.setVisible(False)
        self.open_file_btn.clicked.connect(self._open_last_file)
        row.addWidget(self.open_file_btn)

        self.show_folder_btn = QPushButton(" Show output folder")
        self.show_folder_btn.setObjectName("btnGhost")
        self.show_folder_btn.setIcon(
            QIcon(_icon_pixmap(_SVG_FOLDER_OPEN, 26, color="#9a9aae")),
        )
        self.show_folder_btn.setIconSize(QSize(13, 13))
        self.show_folder_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.show_folder_btn.setVisible(False)
        self.show_folder_btn.clicked.connect(self._show_output_folder)
        row.addWidget(self.show_folder_btn)

        self.clear_btn = QPushButton("Clear")
        self.clear_btn.setObjectName("btnGhost")
        self.clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_btn.clicked.connect(self._clear)
        row.addWidget(self.clear_btn)

        self.convert_btn = QPushButton(" Batch Convert All")
        self.convert_btn.setObjectName("btnPrimary")
        self.convert_btn.setIcon(QIcon(_icon_pixmap(_SVG_ARROW, 24, color="#06121a")))
        self.convert_btn.setIconSize(QSize(13, 13))
        self.convert_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.convert_btn.clicked.connect(self._convert_all)
        row.addWidget(self.convert_btn)
        return row

    # =========================================================
    # Drag / drop / browse
    # =========================================================

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.drop_zone.set_drag_active(True)
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        self.drop_zone.set_drag_active(False)
        event.accept()

    def dropEvent(self, event: QDropEvent) -> None:
        self.drop_zone.set_drag_active(False)
        paths: list[Path] = []
        for url in event.mimeData().urls():
            if not url.isLocalFile():
                continue
            p = Path(url.toLocalFile())
            if p.is_dir():
                paths.extend(self._walk_folder(p))
            elif p.is_file():
                paths.append(p)
        if paths:
            self._add_files(paths)
            event.acceptProposedAction()

    def _walk_folder(self, folder: Path) -> list[Path]:
        collected: list[Path] = []
        supported = set(SUPPORTED_FORMATS.keys())
        for p in folder.rglob("*"):
            if p.is_file() and effective_suffix(p) in supported:
                collected.append(p)
        return sorted(collected)

    def _browse_files(self) -> None:
        exts = sorted(SUPPORTED_FORMATS.keys())
        pattern = " ".join(f"*{e}" for e in exts)
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Select files to convert",
            str(Path.home()),
            f"Supported files ({pattern});;All files (*.*)",
        )
        if paths:
            self._add_files([Path(p) for p in paths])

    def _show_formats_dialog(self) -> None:
        FormatsDialog(self).exec()

    def _show_quality_dialog(self) -> None:
        dialog = QualityDialog(self._settings, self)
        if dialog.exec():
            self._settings = dialog.result_settings()
            self._toast.show_message("Quality settings saved")

    def _browse_output_dir(self) -> None:
        start = str(self._output_dir) if self._output_dir else str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, "Choose output folder", start)
        if folder:
            self._output_dir = Path(folder)
            self.dest_edit.setText(str(self._output_dir))
            self.dest_clear_btn.setVisible(True)

    def _clear_output_dir(self) -> None:
        self._output_dir = None
        self.dest_edit.clear()
        self.dest_clear_btn.setVisible(False)

    # =========================================================
    # Row management
    # =========================================================

    def _add_files(self, paths: list[Path]) -> None:
        accepted = 0
        for path in paths:
            info = info_for(effective_suffix(path))
            if info is None:
                continue
            row = FileRow(path=path, target_ext=info.targets[0])
            self._rows.append(row)
            self._append_table_row(row)
            accepted += 1

        if accepted:
            self._toast.show_message(f"Added {accepted} file{'s' if accepted != 1 else ''}")
        elif paths:
            self._toast.show_message("No supported files", "warn")
        self._update_empty_state()

    def _append_table_row(self, row: FileRow) -> None:
        r = self.table.rowCount()
        self.table.insertRow(r)

        size_text = self._human_size(row.path)
        ext = effective_suffix(row.path)
        file_cell = _FileCell(row.path.name, size_text, ext)
        self.table.setCellWidget(r, _COL_FILE, file_cell)

        target_combo = _TargetCombo(ext, row.target_ext, parent=self.table)
        target_combo.currentTextChanged.connect(
            lambda ext, rr=row: setattr(rr, "target_ext", ext),
        )
        wrap = QWidget(self.table)
        wlay = QHBoxLayout(wrap)
        wlay.setContentsMargins(8, 8, 8, 8)
        wlay.addWidget(target_combo)
        self.table.setCellWidget(r, _COL_TARGET, wrap)

        prog = _ProgressCell(self.table)
        self.table.setCellWidget(r, _COL_PROGRESS, prog)

        status = _StatusCell(self.table)
        self.table.setCellWidget(r, _COL_STATUS, status)

        self._row_widgets.append(
            {"file": file_cell, "target": target_combo, "progress": prog, "status": status},
        )

    def _human_size(self, path: Path) -> str:
        try:
            n = path.stat().st_size
        except OSError:
            return ""
        if n < 1024:
            return f"{n} B"
        if n < 1024 * 1024:
            return f"{n / 1024:.1f} KB"
        if n < 1024 * 1024 * 1024:
            return f"{n / (1024 * 1024):.1f} MB"
        return f"{n / (1024 * 1024 * 1024):.2f} GB"

    def _clear(self) -> None:
        for row in self._rows:
            if row.worker is not None:
                row.worker.cancel()
        self._rows.clear()
        self._row_widgets.clear()
        self.table.setRowCount(0)
        self._pending_indices.clear()
        self._active_indices.clear()
        self.status_msg.setText("")
        self.open_file_btn.setVisible(False)
        self.show_folder_btn.setVisible(False)
        self._update_empty_state()

    def _update_empty_state(self) -> None:
        empty = self.table.rowCount() == 0
        self._empty_state.setVisible(empty)
        self.table.setVisible(not empty)

    def _show_context_menu(self, pos: QPoint) -> None:
        index = self.table.indexAt(pos)
        if not index.isValid():
            return
        if not self.table.selectionModel().isSelected(index):
            self.table.clearSelection()
            self.table.selectRow(index.row())

        menu = QMenu(self)
        selected_rows = sorted({i.row() for i in self.table.selectionModel().selectedRows()})
        count = len(selected_rows)

        # Open / Show in folder are only meaningful on a single Done row.
        if count == 1:
            row_idx = selected_rows[0]
            row = self._rows[row_idx] if 0 <= row_idx < len(self._rows) else None
            if row is not None and row.status == "Done":
                open_action = QAction("Open file", menu)
                open_action.triggered.connect(lambda _=False, i=row_idx: self._open_row_file(i))
                menu.addAction(open_action)

                show_action = QAction("Show in folder", menu)
                show_action.triggered.connect(lambda _=False, i=row_idx: self._show_row_in_folder(i))
                menu.addAction(show_action)

                menu.addSeparator()
            elif row is not None and (row.status.startswith("Failed") or row.status == "Unsupported"):
                copy_err = QAction("Copy error details", menu)
                copy_err.triggered.connect(lambda _=False, i=row_idx: self._copy_row_error(i))
                menu.addAction(copy_err)
                menu.addSeparator()

        label = "Remove" if count <= 1 else f"Remove {count} items"
        remove_action = QAction(label, menu)
        remove_action.triggered.connect(self._remove_selected_rows)
        menu.addAction(remove_action)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _remove_selected_rows(self) -> None:
        rows = sorted({idx.row() for idx in self.table.selectionModel().selectedRows()}, reverse=True)
        for r in rows:
            if 0 <= r < len(self._rows):
                row = self._rows[r]
                if row.worker is not None and row.worker.isRunning():
                    row.worker.cancel()
                self._rows.pop(r)
                self._row_widgets.pop(r)
                self.table.removeRow(r)
        self._update_empty_state()

    # =========================================================
    # Conversion / queue
    # =========================================================

    def _convert_all(self) -> None:
        eligible: list[int] = []
        resolved: list[tuple[int, Path]] = []
        pre_skipped = 0
        pre_failed = 0
        for i, row in enumerate(self._rows):
            if row.status in ("Done", "Processing"):
                continue
            if engine_for(effective_suffix(row.path), row.target_ext) is None:
                self._set_status(i, "Unsupported")
                pre_skipped += 1
                continue
            out = row.resolve_output(self._output_dir)
            if out.resolve() == row.path.resolve():
                self._set_status(i, "Failed: output would overwrite source")
                pre_failed += 1
                continue
            eligible.append(i)
            resolved.append((i, out))

        if not eligible:
            self.status_msg.setText("Nothing to convert.")
            self._toast.show_message("Nothing to convert")
            return

        conflicts = [(i, out) for i, out in resolved if out.exists()]
        if conflicts:
            choice = self._ask_overwrite(conflicts)
            if choice == "cancel":
                return
            if choice == "rename":
                reserved: set[Path] = set()
                for i, out in conflicts:
                    candidate = unique_path(out, reserved)
                    self._rows[i].override_output = candidate
                    reserved.add(candidate)

        self.convert_btn.setEnabled(False)
        self.open_file_btn.setVisible(False)
        self.show_folder_btn.setVisible(False)
        self._batch_total = len(eligible)
        self._batch_done = 0
        self._batch_failed = pre_failed
        self._batch_skipped = pre_skipped
        self._pending_indices = list(eligible)
        # Mark all eligible rows as queued visually.
        for i in eligible:
            self._set_status(i, "Queued")
        self.status_msg.setText(f"Converting {self._batch_total}…")
        self._pump_queue()

    def _ask_overwrite(self, conflicts: list[tuple[int, Path]]) -> str:
        preview = "\n".join(f"• {p.name}" for _, p in conflicts[:8])
        if len(conflicts) > 8:
            preview += f"\n… and {len(conflicts) - 8} more"
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Files already exist")
        box.setText(f"{len(conflicts)} output file(s) already exist:")
        box.setInformativeText(preview)
        overwrite_btn = box.addButton("Overwrite", QMessageBox.ButtonRole.DestructiveRole)
        rename_btn    = box.addButton("Rename duplicates", QMessageBox.ButtonRole.ActionRole)
        cancel_btn    = box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(rename_btn)
        box.exec()
        clicked = box.clickedButton()
        if clicked is overwrite_btn:
            return "overwrite"
        if clicked is rename_btn:
            return "rename"
        return "cancel"

    def _pump_queue(self) -> None:
        while (
            self._pending_indices
            and len(self._active_indices) < max(1, self._settings.max_concurrent)
        ):
            index = self._pending_indices.pop(0)
            self._start_row(index)

        if not self._pending_indices and not self._active_indices and self._batch_total > 0:
            self._announce_batch_done()

    def _start_row(self, index: int) -> None:
        row = self._rows[index]
        engine = engine_for(effective_suffix(row.path), row.target_ext)
        if engine is None:
            self._set_status(index, "Unsupported")
            return

        output_path = row.resolve_output(self._output_dir)

        worker_cls = worker_for(engine)
        worker = worker_cls(row.path, output_path, self._settings)
        row.worker = worker

        worker.progress.connect(lambda pct, i=index: self._set_progress(i, pct))
        worker.status.connect(lambda text, i=index: self._set_status(i, text))
        worker.finished.connect(lambda i=index: self._on_worker_finished(i))
        self._active_indices.add(index)
        worker.start()

    def _on_worker_finished(self, index: int) -> None:
        self._active_indices.discard(index)
        if 0 <= index < len(self._rows):
            row = self._rows[index]
            status = row.status
            if status == "Done":
                self._batch_done += 1
                row.completed_output = row.resolve_output(self._output_dir)
            elif status.startswith("Failed"):
                self._batch_failed += 1
        self._pump_queue()

    def _announce_batch_done(self) -> None:
        total = self._batch_total
        done = self._batch_done
        failed = self._batch_failed
        skipped = self._batch_skipped
        if failed or skipped:
            parts = [f"✓ {done} of {total} done"]
            toast_parts = [f"{done} done"]
            if failed:
                parts.append(f"✗ {failed} failed")
                toast_parts.append(f"{failed} failed")
            if skipped:
                parts.append(f"⤼ {skipped} skipped")
                toast_parts.append(f"{skipped} skipped")
            msg = " · ".join(parts)
            self._toast.show_message(" · ".join(toast_parts), "warn")
        else:
            msg = f"✓ All {total} conversions complete"
            self._toast.show_message(msg)
        self.status_msg.setText(msg)
        QTimer.singleShot(8000, lambda: self.status_msg.setText(""))
        self.convert_btn.setEnabled(True)
        self._batch_total = 0
        self._batch_skipped = 0
        # Reveal the open-file / show-folder buttons if at least one
        # conversion succeeded.
        if done > 0 and self._last_output_file() is not None:
            self.open_file_btn.setVisible(True)
            self.show_folder_btn.setVisible(True)

    def _last_output_file(self) -> Path | None:
        """Path of the most recently completed conversion's output, or None."""
        for row in reversed(self._rows):
            if row.status == "Done":
                return row.completed_output or row.resolve_output(self._output_dir)
        return None

    def _last_output_folder(self) -> Path | None:
        """Best-effort: a folder a user could open to find the output."""
        if self._output_dir is not None:
            return self._output_dir
        last = self._last_output_file()
        return last.parent if last is not None else None

    def _show_output_folder(self) -> None:
        folder = self._last_output_folder()
        if folder is None:
            self._toast.show_message("No output folder yet", "warn")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _open_last_file(self) -> None:
        last = self._last_output_file()
        if last is None or not last.exists():
            self._toast.show_message("Converted file not found", "warn")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(last)))

    def _open_row_file(self, index: int) -> None:
        if not (0 <= index < len(self._rows)):
            return
        row = self._rows[index]
        out = row.completed_output or row.resolve_output(self._output_dir)
        if not out.exists():
            self._toast.show_message("Converted file not found", "warn")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(out)))

    def _show_row_in_folder(self, index: int) -> None:
        if not (0 <= index < len(self._rows)):
            return
        row = self._rows[index]
        out = row.completed_output or row.resolve_output(self._output_dir)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(out.parent)))

    def _copy_row_error(self, index: int) -> None:
        if not (0 <= index < len(self._rows)):
            return
        text = self._rows[index].status
        QApplication.clipboard().setText(text)
        self._toast.show_message("Error details copied")

    # =========================================================
    # Row status / tinting
    # =========================================================

    def _set_progress(self, index: int, pct: int) -> None:
        if 0 <= index < len(self._row_widgets):
            self._row_widgets[index]["progress"].set_progress(pct)
        if 0 <= index < len(self._rows):
            self._rows[index].progress = pct

    def _set_status(self, index: int, text: str) -> None:
        if not (0 <= index < len(self._row_widgets)):
            return
        cells = self._row_widgets[index]
        if text == "Done":
            cells["status"].set_state("done")
            cells["progress"].set_progress(100, state="done")
        elif text == "Processing":
            cells["status"].set_state("processing")
        elif text == "Queued":
            cells["status"].set_state("queued")
        elif text.startswith("Failed") or text == "Unsupported":
            cells["status"].set_state("failed", label="Failed" if text.startswith("Failed") else "Unsupported")
            cells["progress"].set_progress(self._rows[index].progress, state="failed")
        elif text == "Cancelled":
            cells["status"].set_state("cancelled", label="Cancelled")
        else:
            cells["status"].set_state("ready")

        if 0 <= index < len(self._rows):
            self._rows[index].status = text

    # =========================================================
    # Frameless window helpers
    # =========================================================

    def _toggle_max(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def eventFilter(self, obj, event):  # noqa: N802
        # The filter can fire during widget construction, before the
        # attributes it references exist — guard with getattr.
        dest_edit = getattr(self, "dest_edit", None)
        chrome = getattr(self, "_chrome", None)
        save_input = getattr(self, "_save_input", None)

        if dest_edit is not None and obj is dest_edit and save_input is not None:
            if event.type() == QEvent.Type.FocusIn:
                save_input.setProperty("focused", True)
                save_input.style().unpolish(save_input)
                save_input.style().polish(save_input)
            elif event.type() == QEvent.Type.FocusOut:
                save_input.setProperty("focused", False)
                save_input.style().unpolish(save_input)
                save_input.style().polish(save_input)
        # When the mouse re-enters the chrome (leaving the resize margin),
        # clear any resize cursor we set so it doesn't stick on top of
        # children that don't have their own cursor.
        elif chrome is not None and obj is chrome and event.type() == QEvent.Type.Enter:
            if self.cursor().shape() != Qt.CursorShape.ArrowCursor:
                self.unsetCursor()
        return super().eventFilter(obj, event)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        # Edge-resize via native window manager (Qt 5.15+).
        if event.button() == Qt.MouseButton.LeftButton and not self.isMaximized():
            edge = self._edge_at(event.position().toPoint())
            if edge:
                handle = self.windowHandle()
                if handle is not None:
                    handle.startSystemResize(edge)
                    event.accept()
                    return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        # mouseMoveEvent on the main window only fires while the mouse is over
        # its bare pixels (the 6 px resize margin). Inside the chrome widget,
        # this handler never sees the move — eventFilter() resets the cursor
        # on chrome's enterEvent so it doesn't stick.
        if not self.isMaximized():
            edge = self._edge_at(event.position().toPoint())
            if edge is not None:
                shape = self._cursor_for(edge)
                if self.cursor().shape() != shape:
                    self.setCursor(shape)
            elif self.cursor().shape() != Qt.CursorShape.ArrowCursor:
                self.unsetCursor()
        super().mouseMoveEvent(event)

    def _edge_at(self, pos: QPoint) -> Qt.Edge | None:
        m = _RESIZE_MARGIN
        w, h = self.width(), self.height()
        x, y = pos.x(), pos.y()
        left, right, top, bottom = x <= m, x >= w - m, y <= m, y >= h - m
        if top and left:     return Qt.Edge.TopEdge | Qt.Edge.LeftEdge
        if top and right:    return Qt.Edge.TopEdge | Qt.Edge.RightEdge
        if bottom and left:  return Qt.Edge.BottomEdge | Qt.Edge.LeftEdge
        if bottom and right: return Qt.Edge.BottomEdge | Qt.Edge.RightEdge
        if left:             return Qt.Edge.LeftEdge
        if right:            return Qt.Edge.RightEdge
        if top:              return Qt.Edge.TopEdge
        if bottom:           return Qt.Edge.BottomEdge
        return None

    @staticmethod
    def _cursor_for(edge) -> Qt.CursorShape:
        if edge is None:
            return Qt.CursorShape.ArrowCursor
        if edge == (Qt.Edge.TopEdge | Qt.Edge.LeftEdge) or edge == (Qt.Edge.BottomEdge | Qt.Edge.RightEdge):
            return Qt.CursorShape.SizeFDiagCursor
        if edge == (Qt.Edge.TopEdge | Qt.Edge.RightEdge) or edge == (Qt.Edge.BottomEdge | Qt.Edge.LeftEdge):
            return Qt.CursorShape.SizeBDiagCursor
        if edge in (Qt.Edge.LeftEdge, Qt.Edge.RightEdge):
            return Qt.CursorShape.SizeHorCursor
        if edge in (Qt.Edge.TopEdge, Qt.Edge.BottomEdge):
            return Qt.CursorShape.SizeVerCursor
        return Qt.CursorShape.ArrowCursor

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        # Keep the toast pinned just below the title bar.
        if hasattr(self, "_toast") and self._toast.isVisible():
            self._toast.adjustSize()
            self._toast.move((self.width() - self._toast.width()) // 2, 56)

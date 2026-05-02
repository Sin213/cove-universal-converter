from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMouseEvent, QPainter, QPainterPath, QPen, QColor
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QToolButton, QVBoxLayout, QWidget


_ARROW_DOWN_SVG = b"""
<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none'
     stroke='currentColor' stroke-width='1.8' stroke-linecap='round' stroke-linejoin='round'>
  <path d='M12 3v12'/><path d='m7 10 5 5 5-5'/><path d='M5 21h14'/>
</svg>
"""


_INFO_SVG = b"""
<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none'
     stroke='currentColor' stroke-width='2.0' stroke-linecap='round' stroke-linejoin='round'>
  <circle cx='12' cy='12' r='9'/>
  <path d='M12 8h.01'/><path d='M11 12h1v4h1'/>
</svg>
"""


class _SvgIcon(QWidget):
    """Tiny widget that paints an inline SVG with an explicit tint so it
    renders visibly on the dark Cove surface (instead of falling back to
    QSvgRenderer's default near-black for ``currentColor``)."""

    def __init__(self, svg_bytes: bytes, size: int, color: str = "#ececf1",
                 parent=None) -> None:
        super().__init__(parent)
        if b"currentColor" in svg_bytes:
            svg_bytes = svg_bytes.replace(b"currentColor", color.encode())
        self._renderer = QSvgRenderer(svg_bytes)
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self._renderer.render(p)


class _DzArt(QFrame):
    """The teal art tile in the drop zone (icon + gradient frame)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("dzArt")
        self.setFixedSize(44, 44)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(
            _SvgIcon(_ARROW_DOWN_SVG, 22, color="#50e6cf", parent=self),
            alignment=Qt.AlignmentFlag.AlignCenter,
        )


class DropZone(QFrame):
    """Drop target + click-to-browse with the Cove redesign visuals."""

    clicked = Signal()
    info_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("dropZone")
        self.setMinimumHeight(150)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setProperty("dragActive", False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(_DzArt(self), alignment=Qt.AlignmentFlag.AlignCenter)

        title_row = QHBoxLayout()
        title_row.setSpacing(0)
        title_row.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title = QLabel("Drop files here", self)
        title.setObjectName("dzTitle")
        title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        sep = QLabel("  or  ", self)
        sep.setObjectName("dzTitle")
        sep.setStyleSheet("color: #6b6b80; font-weight: 400;")
        sep.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        browse = QLabel("click to browse", self)
        browse.setObjectName("dzTitle")
        browse.setStyleSheet("color: #50e6cf;")
        browse.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        title_row.addWidget(title)
        title_row.addWidget(sep)
        title_row.addWidget(browse)
        layout.addLayout(title_row)

        sub = QLabel("video · audio · images · documents — i for the full list", self)
        sub.setObjectName("dzSub")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(sub)

        self.info_button = QToolButton(self)
        self.info_button.setObjectName("dzInfo")
        self.info_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.info_button.setToolTip("See all supported formats")
        self.info_button.setFixedSize(30, 30)
        self.info_button.clicked.connect(self.info_requested.emit)

        info_layout = QVBoxLayout(self.info_button)
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        info_layout.addWidget(
            _SvgIcon(_INFO_SVG, 16, color="#ececf1", parent=self.info_button),
        )
        self.info_button.raise_()

    def set_drag_active(self, active: bool) -> None:
        self.setProperty("dragActive", bool(active))
        self.style().unpolish(self)
        self.style().polish(self)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        margin = 14
        size = self.info_button.size()
        self.info_button.move(self.width() - size.width() - margin, margin)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)

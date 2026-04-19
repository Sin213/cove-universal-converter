from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QFrame, QLabel, QToolButton, QVBoxLayout


_DROP_QSS = """
QFrame#dropFrame {
    border: 2px dashed #5a5a5a;
    border-radius: 10px;
    background: #2a2a2a;
}
QFrame#dropFrame:hover {
    border-color: #3a7bd5;
    background: #2f2f2f;
}
QFrame#dropFrame[dragActive="true"] {
    border: 2px solid #3a7bd5;
    background: #253046;
}
QLabel#dropTitle { color: #dcdcdc; font-size: 16px; }
QLabel#dropHint  { color: #8a8a8a; font-size: 12px; }
QToolButton#infoButton {
    color: #cfcfcf;
    background: transparent;
    border: 1px solid #555;
    border-radius: 12px;
    font-size: 13px;
    font-weight: 600;
    min-width: 24px; max-width: 24px;
    min-height: 24px; max-height: 24px;
    padding: 0;
}
QToolButton#infoButton:hover { color: #ffffff; border-color: #3a7bd5; background: #333; }
"""


class DropZone(QFrame):
    """Drop target + click-to-browse. Also emits `info_requested` when the
    corner info button is clicked (drag / click pass through to the frame)."""

    clicked = Signal()
    info_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("dropFrame")
        self.setMinimumHeight(170)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(_DROP_QSS)
        self.setProperty("dragActive", False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 14, 14, 20)
        layout.setSpacing(6)

        layout.addStretch(1)

        self.title_label = QLabel("Drop files here", self)
        self.title_label.setObjectName("dropTitle")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(self.title_label)

        self.subtitle_label = QLabel("or click to browse", self)
        self.subtitle_label.setObjectName("dropTitle")
        self.subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.subtitle_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(self.subtitle_label)

        self.hint_label = QLabel(
            "Video, audio, images, documents — click ⓘ for the full list",
            self,
        )
        self.hint_label.setObjectName("dropHint")
        self.hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hint_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(self.hint_label)

        layout.addStretch(1)

        # Info button — overlaid in the top-right corner, repositioned on resize.
        self.info_button = QToolButton(self)
        self.info_button.setObjectName("infoButton")
        self.info_button.setText("ⓘ")
        self.info_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.info_button.setToolTip("View supported formats")
        self.info_button.clicked.connect(self.info_requested.emit)
        self.info_button.raise_()

    def set_drag_active(self, active: bool) -> None:
        self.setProperty("dragActive", bool(active))
        # Qt Style Sheets don't auto-refresh on dynamic-property change; force it.
        self.style().unpolish(self)
        self.style().polish(self)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        margin = 10
        size = self.info_button.sizeHint()
        self.info_button.move(
            self.width() - size.width() - margin,
            margin,
        )

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)

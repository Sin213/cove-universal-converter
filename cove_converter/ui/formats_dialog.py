from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from cove_converter.routing import FORMAT_CATEGORIES
from cove_converter.ui.theme import (
    CAT_ARCHIVE,
    CAT_AUDIO,
    CAT_DATA,
    CAT_DOC,
    CAT_IMAGE,
    CAT_SHEET,
    CAT_SUBTITLE,
    CAT_VIDEO,
)


_CATEGORY_COLOR = {
    "Video":        CAT_VIDEO,
    "Audio":        CAT_AUDIO,
    "Images":       CAT_IMAGE,
    "Documents":    CAT_DOC,
    "Subtitles":    CAT_SUBTITLE,
    "Spreadsheets": CAT_SHEET,
    "Archives":     CAT_ARCHIVE,
    "Data":         CAT_DATA,
}


_X_SVG = b"""<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 14 14' fill='none'
 stroke='currentColor' stroke-width='1.6' stroke-linecap='round'><path d='M3 3l8 8M11 3l-8 8'/></svg>"""


def _x_icon() -> QIcon:
    pm = QPixmap(28, 28)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    QSvgRenderer(_X_SVG.replace(b"currentColor", b"#9a9aae")).render(p)
    p.end()
    return QIcon(pm)


class _Pip(QLabel):
    def __init__(self, color: str, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(8, 8)
        self.setStyleSheet(f"background: {color}; border-radius: 4px;")


class _ChipFlow(QWidget):
    """Left-aligned flowing wrap of ext chips."""
    def __init__(self, items: list[str], parent=None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        outer.addLayout(row)
        row_count = 0
        max_per_row = 14  # heuristic; the actual wrapping comes from the dialog's width

        for text in items:
            chip = QLabel(text, self)
            chip.setObjectName("extChip")
            row.addWidget(chip)
            row_count += 1
            if row_count >= max_per_row:
                row.addStretch(1)
                row = QHBoxLayout()
                row.setContentsMargins(0, 0, 0, 0)
                row.setSpacing(6)
                outer.addLayout(row)
                row_count = 0
        row.addStretch(1)


class FormatsDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Supported formats")
        self.setModal(True)
        self.resize(560, 540)
        self.setObjectName("modalDialog")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        outer.addWidget(self._build_header())
        outer.addWidget(self._build_body(), stretch=1)
        outer.addWidget(self._build_footer())

    # ---- chrome ----

    def _build_header(self) -> QFrame:
        head = QFrame(self)
        head.setObjectName("modalHead")
        lay = QHBoxLayout(head)
        lay.setContentsMargins(20, 16, 14, 14)
        lay.setSpacing(0)

        title = QLabel("Supported formats", head)
        title.setObjectName("modalTitle")
        lay.addWidget(title)
        lay.addStretch(1)

        x = QToolButton(head)
        x.setObjectName("modalX")
        x.setIcon(_x_icon())
        x.setIconSize(QSize(14, 14))
        x.setFixedSize(26, 26)
        x.setCursor(Qt.CursorShape.PointingHandCursor)
        x.clicked.connect(self.reject)
        lay.addWidget(x)

        sep = QFrame(self)
        sep.setObjectName("sep")

        wrap = QFrame(self)
        wrap_lay = QVBoxLayout(wrap)
        wrap_lay.setContentsMargins(0, 0, 0, 0)
        wrap_lay.setSpacing(0)
        wrap_lay.addWidget(head)
        wrap_lay.addWidget(sep)
        return wrap

    def _build_body(self) -> QScrollArea:
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        body = QWidget()
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(20, 18, 20, 18)
        body_lay.setSpacing(18)

        for name, exts in FORMAT_CATEGORIES:
            block = QVBoxLayout()
            block.setContentsMargins(0, 0, 0, 0)
            block.setSpacing(10)

            head_row = QHBoxLayout()
            head_row.setContentsMargins(0, 0, 0, 0)
            head_row.setSpacing(8)
            head_row.addWidget(_Pip(_CATEGORY_COLOR.get(name, CAT_VIDEO)))
            label = QLabel(name, body)
            label.setObjectName("categoryLabel")
            head_row.addWidget(label)
            count = QLabel(f"· {len(exts)}", body)
            count.setObjectName("categoryLabel")
            count.setStyleSheet("color: #6b6b80;")
            head_row.addWidget(count)
            head_row.addStretch(1)
            block.addLayout(head_row)

            block.addWidget(_ChipFlow(list(exts), body))

            body_lay.addLayout(block)

        body_lay.addStretch(1)
        scroll.setWidget(body)
        return scroll

    def _build_footer(self) -> QFrame:
        sep = QFrame(self)
        sep.setObjectName("sep")

        foot = QFrame(self)
        foot.setObjectName("modalFoot")
        lay = QHBoxLayout(foot)
        lay.setContentsMargins(20, 12, 20, 14)
        lay.setSpacing(8)
        lay.addStretch(1)

        close_btn = QPushButton("Close", foot)
        close_btn.setObjectName("btnGhost")
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self.accept)
        lay.addWidget(close_btn)

        wrap = QFrame(self)
        wrap_lay = QVBoxLayout(wrap)
        wrap_lay.setContentsMargins(0, 0, 0, 0)
        wrap_lay.setSpacing(0)
        wrap_lay.addWidget(sep)
        wrap_lay.addWidget(foot)
        return wrap

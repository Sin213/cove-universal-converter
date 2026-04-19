from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from cove_converter.routing import FORMAT_CATEGORIES, targets_for


_DIALOG_QSS = """
QDialog { background: #1f1f1f; color: #e6e6e6; }
QLabel { color: #e6e6e6; }
QLabel#categoryHeader { font-size: 15px; font-weight: 600; color: #ffffff; padding-top: 4px; }
QLabel#chip {
    background: #2f2f2f;
    border: 1px solid #3a3a3a;
    border-radius: 10px;
    padding: 3px 10px;
    color: #dadada;
    font-size: 12px;
}
QLabel#targetLine { color: #9a9a9a; font-size: 12px; }
QFrame#separator { background: #333; max-height: 1px; min-height: 1px; border: none; }
QPushButton { background: #3a7bd5; color: white; border: none; padding: 6px 16px; border-radius: 6px; }
QPushButton:hover { background: #2f63a8; }
QScrollArea { border: none; background: #1f1f1f; }
"""


class _FlowRow(QWidget):
    """Horizontal chip strip that wraps if needed (simple left-aligned row)."""
    def __init__(self, items: list[str], parent=None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        for text in items:
            chip = QLabel(text, self)
            chip.setObjectName("chip")
            layout.addWidget(chip)
        layout.addStretch(1)


class FormatsDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Supported formats")
        self.setModal(True)
        self.resize(560, 520)
        self.setStyleSheet(_DIALOG_QSS)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(12)

        intro = QLabel(
            "Drop or select any of the file types below. "
            "The available conversion targets are shown beneath each group."
        )
        intro.setWordWrap(True)
        outer.addWidget(intro)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        content = QWidget()
        scroll.setWidget(content)
        outer.addWidget(scroll, stretch=1)

        body = QVBoxLayout(content)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(14)

        for i, (name, exts) in enumerate(FORMAT_CATEGORIES):
            if i > 0:
                sep = QFrame()
                sep.setObjectName("separator")
                body.addWidget(sep)

            header = QLabel(f"{name}  ·  {len(exts)}")
            header.setObjectName("categoryHeader")
            body.addWidget(header)

            body.addWidget(_FlowRow(list(exts)))

            # Show the union of outputs reachable from this category.
            reachable: set[str] = set()
            for e in exts:
                reachable.update(targets_for(e))
            if reachable:
                targets_line = QLabel(f"Converts to: {', '.join(sorted(reachable))}")
                targets_line.setObjectName("targetLine")
                targets_line.setWordWrap(True)
                body.addWidget(targets_line)

        body.addStretch(1)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        close_btn.setDefault(True)
        button_row.addWidget(close_btn)
        outer.addLayout(button_row)

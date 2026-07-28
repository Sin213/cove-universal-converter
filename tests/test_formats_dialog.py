from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QScrollArea  # noqa: E402

from cove_converter.ui.formats_dialog import FormatsDialog, _ChipFlow  # noqa: E402
from cove_converter.ui.theme import apply_global_theme  # noqa: E402


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_format_chips_wrap_without_horizontal_overflow() -> None:
    app = _app()
    apply_global_theme(app)
    dialog = FormatsDialog()
    try:
        dialog.show()
        app.processEvents()

        scroll = dialog.findChild(QScrollArea)
        flows = dialog.findChildren(_ChipFlow)
        video_chips = flows[0].findChildren(QLabel, "extChip")

        assert scroll.horizontalScrollBar().maximum() == 0
        assert len({chip.y() for chip in video_chips}) > 1

        dialog.resize(360, dialog.height())
        app.processEvents()

        assert scroll.horizontalScrollBar().maximum() == 0
        for flow in flows:
            assert all(
                chip.geometry().right() < flow.width()
                for chip in flow.findChildren(QLabel, "extChip")
            )
    finally:
        dialog.close()
        dialog.deleteLater()

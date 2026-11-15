import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QCoreApplication, QEvent


def test_output_selection_and_empty_selection_guard():
    from cove_converter.ui.outputs_dialog import OutputsDialog
    from cove_converter.settings import ConversionSettings
    app = QApplication.instance() or QApplication([])
    dialog = OutputsDialog((".jpg", ".webp"), (".jpg",), ConversionSettings())
    assert dialog.selected_targets() == (".jpg",)
    dialog.checks[".webp"].setChecked(True)
    assert dialog.selected_targets() == (".jpg", ".webp")
    for check in dialog.checks.values():
        check.setChecked(False)
    assert not dialog.apply_button.isEnabled()
    dialog.close()
    dialog.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()

"""Compact output selection and named presets, shared by row and batch UI."""
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QGridLayout,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QVBoxLayout,
)

from cove_converter.settings import PresetStore


class OutputsDialog(QDialog):
    def __init__(self, formats, selected, quality, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Output formats and presets")
        self.setMinimumWidth(440)
        self.quality = quality
        self.store = PresetStore()
        self.preset = None
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Select one or more output formats:"))
        grid = QGridLayout()
        self.checks = {}
        for index, target in enumerate(formats):
            check = QCheckBox(target)
            check.setChecked(target in selected)
            self.checks[target] = check
            grid.addWidget(check, index // 6, index % 6)
            check.toggled.connect(self._selection_changed)
        layout.addLayout(grid)
        if not formats:
            layout.addWidget(QLabel("These files share no output format. Apply a compatible preset below."))
        self.apply_all = QCheckBox("Apply to all compatible queued files")
        layout.addWidget(self.apply_all)
        layout.addWidget(QLabel("Presets include formats and current quality settings."))
        self.names = QComboBox()
        layout.addWidget(self.names)
        actions = QHBoxLayout()
        apply_preset = QPushButton("Apply preset")
        apply_preset.clicked.connect(self._apply_preset)
        delete = QPushButton("Delete preset")
        delete.clicked.connect(self._delete)
        actions.addWidget(apply_preset)
        actions.addWidget(delete)
        layout.addLayout(actions)
        save_row = QHBoxLayout()
        self.name = QLineEdit()
        self.name.setMaxLength(80)
        self.name.setPlaceholderText("Preset name")
        save = QPushButton("Save selection")
        save.clicked.connect(self._save)
        save_row.addWidget(self.name)
        save_row.addWidget(save)
        layout.addLayout(save_row)
        layout.addWidget(QLabel("Unsupported preset targets are skipped and reported.\nOutputs use the chosen destination; successful outputs are kept if another fails."))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Cancel)
        self.apply_button = buttons.button(QDialogButtonBox.StandardButton.Apply)
        self.apply_button.clicked.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._reload()
        self._selection_changed()

    def selected_targets(self):
        return tuple(target for target, check in self.checks.items() if check.isChecked())

    def _selection_changed(self):
        if hasattr(self, "apply_button"):
            self.apply_button.setEnabled(bool(self.selected_targets()))

    def _reload(self):
        self.presets = self.store.load()
        self.names.clear()
        self.names.addItems(self.presets)

    def _save(self):
        try:
            self.store.save(self.name.text(), self.selected_targets(), self.quality)
        except ValueError as exc:
            QMessageBox.warning(self, "Cannot save preset", str(exc))
            return
        self._reload()

    def _delete(self):
        try:
            self.store.delete(self.names.currentText())
        except ValueError as exc:
            QMessageBox.warning(self, "Cannot delete preset", str(exc))
        self._reload()

    def _apply_preset(self):
        self.preset = self.presets.get(self.names.currentText())
        if self.preset is not None:
            self.accept()

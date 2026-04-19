from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from cove_converter.settings import AUDIO_BITRATES, VIDEO_PRESETS, ConversionSettings


_DIALOG_QSS = """
QDialog { background: #1f1f1f; color: #e6e6e6; }
QLabel { color: #e6e6e6; }
QLabel#sectionHeader { font-size: 14px; font-weight: 600; color: #ffffff; padding-top: 4px; }
QLabel#hint { color: #8a8a8a; font-size: 11px; }
QLabel#banner {
    color: #dcdcdc;
    background: #2a2a2a;
    border: 1px solid #3a3a3a;
    border-radius: 6px;
    padding: 8px 10px;
    font-size: 12px;
}
QFrame#separator { background: #333; max-height: 1px; min-height: 1px; border: none; }
QCheckBox { color: #e6e6e6; spacing: 8px; }
QCheckBox::indicator { width: 16px; height: 16px; }
QComboBox, QSpinBox {
    background: #2a2a2a; color: #e6e6e6; border: 1px solid #444;
    padding: 4px 6px; border-radius: 4px;
}
QComboBox:disabled, QSpinBox:disabled { color: #666; }
QSlider::groove:horizontal { background: #2a2a2a; height: 4px; border-radius: 2px; }
QSlider::handle:horizontal { background: #3a7bd5; width: 14px; height: 14px; margin: -6px 0; border-radius: 7px; }
QSlider:disabled::handle:horizontal { background: #555; }
QPushButton { background: #3a7bd5; color: white; border: none; padding: 6px 14px; border-radius: 6px; }
QPushButton:hover { background: #2f63a8; }
QPushButton[text="Reset"] { background: #3a3a3a; }
QPushButton[text="Reset"]:hover { background: #4a4a4a; }
"""


class _LabeledSlider(QWidget):
    def __init__(self, minimum: int, maximum: int, initial: int, suffix: str = "", parent=None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.slider = QSlider(Qt.Orientation.Horizontal, self)
        self.slider.setRange(minimum, maximum)
        self.slider.setValue(initial)
        self.label = QLabel(f"{initial}{suffix}", self)
        self.label.setMinimumWidth(48)
        self.label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._suffix = suffix
        self.slider.valueChanged.connect(lambda v: self.label.setText(f"{v}{self._suffix}"))
        layout.addWidget(self.slider, stretch=1)
        layout.addWidget(self.label)

    def value(self) -> int:
        return self.slider.value()

    def set_value(self, v: int) -> None:
        self.slider.setValue(v)

    def setEnabled(self, enabled: bool) -> None:  # noqa: N802 - Qt name
        self.slider.setEnabled(enabled)
        self.label.setEnabled(enabled)
        super().setEnabled(enabled)


class QualityDialog(QDialog):
    def __init__(self, current: ConversionSettings, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Quality settings")
        self.setModal(True)
        self.setMinimumWidth(480)
        self.setStyleSheet(_DIALOG_QSS)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 16)
        outer.setSpacing(12)

        banner = QLabel(
            "By default, files are converted with near-lossless quality — nothing "
            "below is applied. Tick the box to take manual control if you'd like "
            "to trade quality for smaller output."
        )
        banner.setObjectName("banner")
        banner.setWordWrap(True)
        outer.addWidget(banner)

        self.enable_check = QCheckBox("Customize quality settings")
        self.enable_check.setChecked(current.use_custom_quality)
        self.enable_check.toggled.connect(self._on_toggle)
        outer.addWidget(self.enable_check)

        # Container for everything the checkbox toggles.
        self._quality_widgets: list[QWidget] = []

        outer.addWidget(self._section_header("Video"))
        video_form = QFormLayout()
        video_form.setSpacing(8)

        self.crf = _LabeledSlider(17, 32, current.video_crf)
        self._quality_widgets.append(self.crf)
        video_form.addRow(self._track_label("Quality (CRF):"), self.crf)

        self.preset_combo = QComboBox()
        for p in VIDEO_PRESETS:
            self.preset_combo.addItem(p)
        self.preset_combo.setCurrentText(current.video_preset)
        self._quality_widgets.append(self.preset_combo)
        video_form.addRow(self._track_label("Encoder preset:"), self.preset_combo)

        crf_hint = QLabel("Lower CRF = higher quality & bigger files. 23 is a balanced default.")
        crf_hint.setObjectName("hint")
        crf_hint.setWordWrap(True)
        self._quality_widgets.append(crf_hint)
        video_form.addRow("", crf_hint)
        outer.addLayout(video_form)

        outer.addWidget(self._separator())
        outer.addWidget(self._section_header("Audio"))
        audio_form = QFormLayout()
        audio_form.setSpacing(8)

        self.audio_combo = QComboBox()
        for b in AUDIO_BITRATES:
            self.audio_combo.addItem(f"{b} kbps", userData=b)
        idx = self.audio_combo.findData(current.audio_bitrate_kbps)
        self.audio_combo.setCurrentIndex(idx if idx >= 0 else self.audio_combo.count() - 1)
        self._quality_widgets.append(self.audio_combo)
        audio_form.addRow(self._track_label("Bitrate:"), self.audio_combo)

        audio_hint = QLabel("Applies to lossy output (mp3, aac, ogg, opus, m4a, wma).")
        audio_hint.setObjectName("hint")
        audio_hint.setWordWrap(True)
        self._quality_widgets.append(audio_hint)
        audio_form.addRow("", audio_hint)
        outer.addLayout(audio_form)

        outer.addWidget(self._separator())
        outer.addWidget(self._section_header("Images"))
        img_form = QFormLayout()
        img_form.setSpacing(8)
        self.jpeg = _LabeledSlider(60, 100, current.jpeg_quality, suffix="%")
        self._quality_widgets.append(self.jpeg)
        img_form.addRow(self._track_label("JPEG quality:"), self.jpeg)
        self.webp = _LabeledSlider(60, 100, current.webp_quality, suffix="%")
        self._quality_widgets.append(self.webp)
        img_form.addRow(self._track_label("WebP quality:"), self.webp)
        outer.addLayout(img_form)

        outer.addWidget(self._separator())
        outer.addWidget(self._section_header("Batch"))
        batch_form = QFormLayout()
        self.concurrent_spin = QSpinBox()
        self.concurrent_spin.setRange(1, 16)
        self.concurrent_spin.setValue(current.max_concurrent)
        batch_form.addRow("Max parallel conversions:", self.concurrent_spin)
        outer.addLayout(batch_form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Reset
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.Reset).clicked.connect(self._reset)
        outer.addWidget(buttons)

        self._on_toggle(current.use_custom_quality)

    def _track_label(self, text: str) -> QLabel:
        label = QLabel(text)
        self._quality_widgets.append(label)
        return label

    @staticmethod
    def _section_header(text: str) -> QLabel:
        header = QLabel(text)
        header.setObjectName("sectionHeader")
        return header

    @staticmethod
    def _separator() -> QFrame:
        sep = QFrame()
        sep.setObjectName("separator")
        return sep

    def _on_toggle(self, enabled: bool) -> None:
        for widget in self._quality_widgets:
            widget.setEnabled(enabled)

    def _reset(self) -> None:
        defaults = ConversionSettings()
        self.enable_check.setChecked(defaults.use_custom_quality)
        self.crf.set_value(defaults.video_crf)
        self.preset_combo.setCurrentText(defaults.video_preset)
        idx = self.audio_combo.findData(defaults.audio_bitrate_kbps)
        if idx >= 0:
            self.audio_combo.setCurrentIndex(idx)
        self.jpeg.set_value(defaults.jpeg_quality)
        self.webp.set_value(defaults.webp_quality)
        self.concurrent_spin.setValue(defaults.max_concurrent)

    def result_settings(self) -> ConversionSettings:
        return ConversionSettings(
            use_custom_quality=self.enable_check.isChecked(),
            video_crf=self.crf.value(),
            video_preset=self.preset_combo.currentText(),
            audio_bitrate_kbps=self.audio_combo.currentData(),
            jpeg_quality=self.jpeg.value(),
            webp_quality=self.webp.value(),
            max_concurrent=self.concurrent_spin.value(),
        )

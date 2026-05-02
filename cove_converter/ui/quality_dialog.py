from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from cove_converter.settings import AUDIO_BITRATES, VIDEO_PRESETS, ConversionSettings


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


class _Segmented(QFrame):
    """Segmented control: 1-of-N buttons. Emits the selected value via callback."""

    def __init__(self, options: list[str], current: str, on_change, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("seg")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(3, 3, 3, 3)
        lay.setSpacing(3)
        self._buttons: list[QPushButton] = []
        self._on_change = on_change
        for opt in options:
            btn = QPushButton(opt.capitalize() if opt.isalpha() else opt, self)
            btn.setObjectName("segBtn")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setProperty("active", opt == current)
            btn.clicked.connect(lambda _=False, o=opt: self._select(o))
            lay.addWidget(btn, stretch=1)
            self._buttons.append(btn)
        self._options = options
        self._current = current

    def _select(self, opt: str) -> None:
        self._current = opt
        for b, o in zip(self._buttons, self._options):
            b.setProperty("active", o == opt)
            b.style().unpolish(b)
            b.style().polish(b)
        if self._on_change:
            self._on_change(opt)

    def value(self) -> str:
        return self._current

    def set_value(self, opt: str) -> None:
        self._select(opt)

    def setEnabled(self, enabled: bool) -> None:  # noqa: N802
        for b in self._buttons:
            b.setEnabled(enabled)
        super().setEnabled(enabled)


class _SliderRow(QWidget):
    def __init__(self, minimum: int, maximum: int, initial: int, suffix: str = "", parent=None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        self.slider = QSlider(Qt.Orientation.Horizontal, self)
        self.slider.setRange(minimum, maximum)
        self.slider.setValue(initial)

        self.val = QLabel(f"{initial}{suffix}", self)
        self.val.setObjectName("sliderVal")
        self._suffix = suffix
        self.slider.valueChanged.connect(lambda v: self.val.setText(f"{v}{self._suffix}"))

        layout.addWidget(self.slider, stretch=1)
        layout.addWidget(self.val)

    def value(self) -> int:
        return self.slider.value()

    def set_value(self, v: int) -> None:
        self.slider.setValue(v)

    def setEnabled(self, enabled: bool) -> None:  # noqa: N802
        self.slider.setEnabled(enabled)
        self.val.setEnabled(enabled)
        super().setEnabled(enabled)


def _row_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("sectionLabel")
    return label


class QualityDialog(QDialog):
    def __init__(self, current: ConversionSettings, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Quality settings")
        self.setModal(True)
        self.resize(540, 600)

        self._tracked: list[QWidget] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        outer.addWidget(self._build_header())
        outer.addWidget(self._build_body(current), stretch=1)
        outer.addWidget(self._build_footer())

        self._on_toggle(current.use_custom_quality)

    # ---- chrome ----

    def _build_header(self) -> QFrame:
        head = QFrame(self)
        head.setObjectName("modalHead")
        lay = QHBoxLayout(head)
        lay.setContentsMargins(20, 16, 14, 14)
        lay.setSpacing(0)

        title = QLabel("Quality settings", head)
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

    def _build_body(self, current: ConversionSettings) -> QScrollArea:
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        body = QWidget()
        v = QVBoxLayout(body)
        v.setContentsMargins(20, 18, 20, 18)
        v.setSpacing(14)

        banner = QLabel(
            "By default, files are converted with near-lossless quality — nothing "
            "below is applied. Tick the box to take manual control.",
            body,
        )
        banner.setObjectName("banner")
        banner.setWordWrap(True)
        v.addWidget(banner)

        self.enable_check = QCheckBox("Customize quality settings")
        self.enable_check.setChecked(current.use_custom_quality)
        self.enable_check.toggled.connect(self._on_toggle)
        v.addWidget(self.enable_check)

        # Video preset (full ffmpeg list — round-trips every supported value).
        v.addLayout(self._labeled_row("Video preset"))
        self.video_combo = QComboBox(body)
        self.video_combo.addItems(list(VIDEO_PRESETS))
        if current.video_preset in VIDEO_PRESETS:
            self.video_combo.setCurrentText(current.video_preset)
        else:
            self.video_combo.setCurrentText("medium")
        v.addWidget(self.video_combo)
        self._tracked.append(self.video_combo)

        # Image quality (slider)
        self._img_label = QLabel(f"Image quality · {current.jpeg_quality}%")
        self._img_label.setObjectName("sectionLabel")
        v.addWidget(self._img_label)
        self.jpeg = _SliderRow(40, 100, current.jpeg_quality, suffix="%", parent=body)
        self.jpeg.slider.valueChanged.connect(
            lambda v: self._img_label.setText(f"Image quality · {v}%"),
        )
        v.addWidget(self.jpeg)
        self._tracked.append(self.jpeg)

        # Audio bitrate (full supported list — preserves 96 / 160 etc.).
        v.addLayout(self._labeled_row("Audio bitrate"))
        self.audio_combo = QComboBox(body)
        self.audio_combo.addItems([f"{b}k" for b in AUDIO_BITRATES])
        cur_bitrate = f"{current.audio_bitrate_kbps}k"
        if current.audio_bitrate_kbps in AUDIO_BITRATES:
            self.audio_combo.setCurrentText(cur_bitrate)
        else:
            self.audio_combo.setCurrentText("192k")
        v.addWidget(self.audio_combo)
        self._tracked.append(self.audio_combo)

        # Max concurrent (slider)
        self._conc_label = QLabel(f"Max concurrent · {current.max_concurrent}")
        self._conc_label.setObjectName("sectionLabel")
        v.addWidget(self._conc_label)
        self.concurrent = _SliderRow(1, 16, current.max_concurrent, suffix="", parent=body)
        self.concurrent.slider.valueChanged.connect(
            lambda v: self._conc_label.setText(f"Max concurrent · {v}"),
        )
        v.addWidget(self.concurrent)
        # Concurrency is independent of the use_custom_quality toggle.
        # (It still applies even when default quality is used.)

        # Advanced (CRF + WebP) — only matters when "customize" is on, kept compact.
        v.addWidget(self._sep())
        v.addLayout(self._labeled_row("Advanced"))

        adv = QHBoxLayout()
        adv.setContentsMargins(0, 0, 0, 0)
        adv.setSpacing(12)

        crf_col = QVBoxLayout()
        crf_col.setSpacing(6)
        crf_col.addWidget(_row_label("Video CRF"))
        self.crf = _SliderRow(17, 32, current.video_crf, parent=body)
        crf_col.addWidget(self.crf)
        adv.addLayout(crf_col, stretch=1)

        webp_col = QVBoxLayout()
        webp_col.setSpacing(6)
        webp_col.addWidget(_row_label("WebP quality"))
        self.webp = _SliderRow(60, 100, current.webp_quality, suffix="%", parent=body)
        webp_col.addWidget(self.webp)
        adv.addLayout(webp_col, stretch=1)

        v.addLayout(adv)
        self._tracked.append(self.crf)
        self._tracked.append(self.webp)

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

        cancel = QPushButton("Cancel", foot)
        cancel.setObjectName("btnGhost")
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.clicked.connect(self.reject)
        lay.addWidget(cancel)

        save = QPushButton("Save", foot)
        save.setObjectName("btnPrimary")
        save.setCursor(Qt.CursorShape.PointingHandCursor)
        save.setDefault(True)
        save.clicked.connect(self.accept)
        lay.addWidget(save)

        wrap = QFrame(self)
        wrap_lay = QVBoxLayout(wrap)
        wrap_lay.setContentsMargins(0, 0, 0, 0)
        wrap_lay.setSpacing(0)
        wrap_lay.addWidget(sep)
        wrap_lay.addWidget(foot)
        return wrap

    # ---- helpers ----

    @staticmethod
    def _labeled_row(text: str) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(_row_label(text))
        row.addStretch(1)
        return row

    @staticmethod
    def _sep() -> QFrame:
        sep = QFrame()
        sep.setObjectName("sep")
        return sep

    def _on_toggle(self, enabled: bool) -> None:
        for w in self._tracked:
            w.setEnabled(enabled)

    def result_settings(self) -> ConversionSettings:
        bitrate_str = self.audio_combo.currentText()
        bitrate = int(bitrate_str.rstrip("k"))
        return ConversionSettings(
            use_custom_quality=self.enable_check.isChecked(),
            video_crf=self.crf.value(),
            video_preset=self.video_combo.currentText(),
            audio_bitrate_kbps=bitrate,
            jpeg_quality=self.jpeg.value(),
            webp_quality=self.webp.value(),
            max_concurrent=self.concurrent.value(),
        )

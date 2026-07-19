"""Conversion-quality settings shared across workers.

Plain dataclass; lives for the app's lifetime on the MainWindow. Quality
settings are persisted to QSettings("Cove", "UniversalConverter") under the
"quality/" key group so they survive app restarts.

When ``use_custom_quality`` is False (the default) the ``effective_*`` methods
return near-lossless values that prioritise source fidelity over file size —
i.e. "don't mess with people's files". The user must explicitly opt in to the
sliders before they take effect.
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QSettings


VIDEO_PRESETS = ("ultrafast", "superfast", "veryfast", "faster", "fast",
                 "medium", "slow", "slower", "veryslow")
AUDIO_BITRATES = (96, 128, 160, 192, 256, 320)

# Near-lossless fallbacks used when the user hasn't opted into custom quality.
_DEFAULT_VIDEO_CRF    = 17
_DEFAULT_VIDEO_PRESET = "slow"
_DEFAULT_AUDIO_KBPS   = 320
_DEFAULT_JPEG_QUALITY = 95
_DEFAULT_WEBP_QUALITY = 95

_SETTINGS_ORG = "Cove"
_SETTINGS_APP = "UniversalConverter"
_GROUP       = "quality"


@dataclass
class ConversionSettings:
    use_custom_quality: bool = False

    # Values only apply when use_custom_quality is True.
    video_crf: int = 23
    video_preset: str = "medium"
    audio_bitrate_kbps: int = 192
    jpeg_quality: int = 92
    webp_quality: int = 90

    # Batch concurrency is independent of the quality toggle.
    max_concurrent: int = 3

    # PDF-specific. Off by default — Cove apps must never auto-degrade user
    # files. Only honoured by the pdf→pdf branch in PdfWorker.
    enhance_scanned_pdf: bool = False
    pdf_enhance_dpi: int = 200          # internal; not exposed in UI v1

    def effective_video_crf(self) -> int:
        return self.video_crf if self.use_custom_quality else _DEFAULT_VIDEO_CRF

    def effective_video_preset(self) -> str:
        return self.video_preset if self.use_custom_quality else _DEFAULT_VIDEO_PRESET

    def effective_audio_bitrate(self) -> int:
        return self.audio_bitrate_kbps if self.use_custom_quality else _DEFAULT_AUDIO_KBPS

    def effective_jpeg_quality(self) -> int:
        return self.jpeg_quality if self.use_custom_quality else _DEFAULT_JPEG_QUALITY

    def effective_webp_quality(self) -> int:
        return self.webp_quality if self.use_custom_quality else _DEFAULT_WEBP_QUALITY

    def save(self) -> None:
        """Persist quality settings to QSettings."""
        qs = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
        qs.beginGroup(_GROUP)
        qs.setValue("use_custom_quality", self.use_custom_quality)
        qs.setValue("video_crf", self.video_crf)
        qs.setValue("video_preset", self.video_preset)
        qs.setValue("audio_bitrate_kbps", self.audio_bitrate_kbps)
        qs.setValue("jpeg_quality", self.jpeg_quality)
        qs.setValue("webp_quality", self.webp_quality)
        qs.setValue("max_concurrent", self.max_concurrent)
        qs.endGroup()


def _stored_int(qs: QSettings, key: str, default: int, lo: int, hi: int) -> int:
    """Read a persisted int, surviving hand-edited / corrupted conf values.

    A non-numeric or missing value falls back to ``default`` instead of
    crashing the app at startup; out-of-range values are clamped."""
    try:
        value = int(qs.value(key, default))
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, value))


def load_settings() -> ConversionSettings:
    """Load quality settings from QSettings, falling back to defaults."""
    defaults = ConversionSettings()
    qs = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
    qs.beginGroup(_GROUP)
    s = ConversionSettings(
        use_custom_quality=bool(qs.value("use_custom_quality", defaults.use_custom_quality)),
        video_crf=_stored_int(qs, "video_crf", defaults.video_crf, 0, 51),
        video_preset=str(qs.value("video_preset", defaults.video_preset)),
        audio_bitrate_kbps=_stored_int(
            qs, "audio_bitrate_kbps", defaults.audio_bitrate_kbps, 32, 512),
        jpeg_quality=_stored_int(qs, "jpeg_quality", defaults.jpeg_quality, 1, 100),
        webp_quality=_stored_int(qs, "webp_quality", defaults.webp_quality, 1, 100),
        max_concurrent=_stored_int(qs, "max_concurrent", defaults.max_concurrent, 1, 16),
    )
    qs.endGroup()
    # Clamp video_preset to valid values in case stored value is stale.
    if s.video_preset not in VIDEO_PRESETS:
        s.video_preset = defaults.video_preset
    return s


def default_settings() -> ConversionSettings:
    return ConversionSettings()

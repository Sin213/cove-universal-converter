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

VIDEO_CODEC_KEYS = ("h264", "av1")
VIDEO_CODEC_OPTIONS = ("H.264", "AV1")
VIDEO_CODEC_KEY_MAP = dict(zip(VIDEO_CODEC_OPTIONS, VIDEO_CODEC_KEYS))
VIDEO_CODEC_LABEL_MAP = dict(zip(VIDEO_CODEC_KEYS, VIDEO_CODEC_OPTIONS))

M4A_CODEC_KEYS = ("aac", "alac")
M4A_CODEC_OPTIONS = ("AAC", "ALAC")
M4A_CODEC_KEY_MAP = dict(zip(M4A_CODEC_OPTIONS, M4A_CODEC_KEYS))
M4A_CODEC_LABEL_MAP = dict(zip(M4A_CODEC_KEYS, M4A_CODEC_OPTIONS))

# Video encoder preference. Independent of use_custom_quality: a hardware
# choice always applies (like max_concurrent). Unavailable vendors fall back
# to CPU inside the engine, so forcing one never fails a job.
ENCODER_KEYS = ("auto", "cpu", "nvenc", "amf")
ENCODER_OPTIONS = ("Automatic", "CPU", "NVIDIA (NVENC)", "AMD (AMF)")
ENCODER_KEY_MAP = dict(zip(ENCODER_OPTIONS, ENCODER_KEYS))
ENCODER_LABEL_MAP = dict(zip(ENCODER_KEYS, ENCODER_OPTIONS))

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

    # Hardware video encoder preference (auto/cpu/nvenc/amf). Independent of
    # the quality toggle; always applies. Only affects H.264/H.265/AV1 outputs.
    encoder_pref: str = "auto"
    video_codec: str = "h264"
    m4a_codec: str = "aac"

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
        qs.setValue("encoder_pref", self.encoder_pref)
        qs.setValue("video_codec", self.video_codec)
        qs.setValue("m4a_codec", self.m4a_codec)
        qs.endGroup()


def _stored_int(qs: QSettings, key: str, default: int, lo: int, hi: int) -> int:
    """Read a persisted int, surviving hand-edited / corrupted conf values.

    A non-numeric or missing value falls back to ``default`` instead of
    crashing the app at startup; out-of-range values are clamped."""
    raw_value = qs.value(key, default)
    if not isinstance(raw_value, (str, bytes, bytearray, int, float)):
        return default
    try:
        value = int(raw_value)
    except (TypeError, ValueError, OverflowError):
        return default
    return max(lo, min(hi, value))


def _stored_bool(qs: QSettings, key: str, default: bool) -> bool:
    """Read a persisted bool without treating the string ``"false"`` as true."""
    value = qs.value(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    return default


def load_settings() -> ConversionSettings:
    """Load quality settings from QSettings, falling back to defaults."""
    defaults = ConversionSettings()
    qs = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
    qs.beginGroup(_GROUP)
    s = ConversionSettings(
        use_custom_quality=_stored_bool(
            qs, "use_custom_quality", defaults.use_custom_quality
        ),
        video_crf=_stored_int(qs, "video_crf", defaults.video_crf, 0, 51),
        video_preset=str(qs.value("video_preset", defaults.video_preset)),
        audio_bitrate_kbps=_stored_int(
            qs, "audio_bitrate_kbps", defaults.audio_bitrate_kbps, 32, 512),
        jpeg_quality=_stored_int(qs, "jpeg_quality", defaults.jpeg_quality, 1, 100),
        webp_quality=_stored_int(qs, "webp_quality", defaults.webp_quality, 1, 100),
        max_concurrent=_stored_int(qs, "max_concurrent", defaults.max_concurrent, 1, 16),
        encoder_pref=str(qs.value("encoder_pref", defaults.encoder_pref)),
        video_codec=str(qs.value("video_codec", defaults.video_codec)),
        m4a_codec=str(qs.value("m4a_codec", defaults.m4a_codec)),
    )
    qs.endGroup()
    # Clamp video_preset to valid values in case stored value is stale.
    if s.video_preset not in VIDEO_PRESETS:
        s.video_preset = defaults.video_preset
    # Fall back to auto on an unknown/hand-edited encoder preference.
    if s.encoder_pref not in ENCODER_KEYS:
        s.encoder_pref = defaults.encoder_pref
    if s.video_codec not in VIDEO_CODEC_KEYS:
        s.video_codec = defaults.video_codec
    if s.m4a_codec not in M4A_CODEC_KEYS:
        s.m4a_codec = defaults.m4a_codec
    return s


def default_settings() -> ConversionSettings:
    return ConversionSettings()

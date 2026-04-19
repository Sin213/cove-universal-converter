"""Conversion-quality settings shared across workers.

Plain dataclass; lives for the app's lifetime on the MainWindow. No disk
persistence yet — add QSettings later if the user wants it.

When ``use_custom_quality`` is False (the default) the ``effective_*`` methods
return near-lossless values that prioritise source fidelity over file size —
i.e. "don't mess with people's files". The user must explicitly opt in to the
sliders before they take effect.
"""
from __future__ import annotations

from dataclasses import dataclass


VIDEO_PRESETS = ("ultrafast", "superfast", "veryfast", "faster", "fast",
                 "medium", "slow", "slower", "veryslow")
AUDIO_BITRATES = (96, 128, 160, 192, 256, 320)

# Near-lossless fallbacks used when the user hasn't opted into custom quality.
_DEFAULT_VIDEO_CRF    = 17
_DEFAULT_VIDEO_PRESET = "slow"
_DEFAULT_AUDIO_KBPS   = 320
_DEFAULT_JPEG_QUALITY = 95
_DEFAULT_WEBP_QUALITY = 95


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


def default_settings() -> ConversionSettings:
    return ConversionSettings()

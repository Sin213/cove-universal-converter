"""Regression tests for QualityDialog (Codex review #3).

The dialog must preserve the full supported settings ranges and round-trip
existing settings without lossy remapping:

  * every ffmpeg preset in `VIDEO_PRESETS`
  * every audio bitrate in `AUDIO_BITRATES` (including 96 and 160)
  * `max_concurrent` values up to 16
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from cove_converter.settings import (  # noqa: E402
    AUDIO_BITRATES,
    VIDEO_PRESETS,
    ConversionSettings,
)
from cove_converter.ui.quality_dialog import QualityDialog  # noqa: E402


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


class QualityDialogRoundTrip(unittest.TestCase):
    def setUp(self) -> None:
        self._app = _app()

    def _round_trip(self, settings: ConversionSettings) -> ConversionSettings:
        dlg = QualityDialog(settings)
        try:
            return dlg.result_settings()
        finally:
            dlg.deleteLater()

    def test_every_supported_preset_round_trips(self) -> None:
        for preset in VIDEO_PRESETS:
            with self.subTest(preset=preset):
                settings = ConversionSettings(
                    use_custom_quality=True, video_preset=preset,
                )
                self.assertEqual(self._round_trip(settings).video_preset, preset)

    def test_every_supported_bitrate_round_trips(self) -> None:
        for kbps in AUDIO_BITRATES:
            with self.subTest(kbps=kbps):
                settings = ConversionSettings(
                    use_custom_quality=True, audio_bitrate_kbps=kbps,
                )
                self.assertEqual(
                    self._round_trip(settings).audio_bitrate_kbps, kbps,
                )

    def test_audio_96_and_160_round_trip(self) -> None:
        # Specifically called out in the review — guarded against regression.
        for kbps in (96, 160):
            with self.subTest(kbps=kbps):
                self.assertIn(kbps, AUDIO_BITRATES)
                settings = ConversionSettings(
                    use_custom_quality=True, audio_bitrate_kbps=kbps,
                )
                self.assertEqual(
                    self._round_trip(settings).audio_bitrate_kbps, kbps,
                )

    def test_concurrency_above_eight_round_trips(self) -> None:
        for value in (9, 12, 16):
            with self.subTest(value=value):
                settings = ConversionSettings(
                    use_custom_quality=True, max_concurrent=value,
                )
                self.assertEqual(
                    self._round_trip(settings).max_concurrent, value,
                )


if __name__ == "__main__":
    unittest.main()

"""Tests for GPU hardware-encoder detection and the _build_cmd GPU branches.

No real ffmpeg or GPU is exercised: detection is driven through a monkeypatched
resolve() / probe, and the arg matrix monkeypatches the cached availability
verdicts. Mirrors tests/test_mp4_to_webm_size.py's worker-construction pattern.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from cove_converter.engines import hwaccel  # noqa: E402
from cove_converter.engines.ffmpeg import FFmpegWorker  # noqa: E402
from cove_converter.settings import (  # noqa: E402
    ConversionSettings,
    default_settings,
    load_settings,
)


def _build(out_ext: str, settings: ConversionSettings) -> list[str]:
    cls = FFmpegWorker
    w = cls.__new__(cls)
    w.input_path = Path("/tmp/in.mov")
    w.output_path = Path(f"/tmp/out{out_ext}")
    w._final_output_path = w.output_path
    w._owned_temp_path = None
    w.settings = settings
    w._cancel = False
    w.progress = mock.Mock()
    w.status = mock.Mock()
    w.finished_ok = mock.Mock()
    w.failed = mock.Mock()
    # _build_cmd resolves the ffmpeg path up front; stub it so these arg-only
    # assertions run on CI runners that have no ffmpeg installed.
    with mock.patch("cove_converter.engines.ffmpeg.resolve", lambda name: name):
        return w._build_cmd()


class DetectionGracefulFailure(unittest.TestCase):
    def setUp(self) -> None:
        hwaccel._nvenc_cache.clear()
        hwaccel._amf_cache.clear()

    def tearDown(self) -> None:
        hwaccel._nvenc_cache.clear()
        hwaccel._amf_cache.clear()

    def test_missing_binary_returns_false_and_caches(self) -> None:
        def _boom(_name: str) -> str:
            raise FileNotFoundError("no ffmpeg")

        with mock.patch.object(hwaccel, "resolve", _boom):
            self.assertFalse(hwaccel.nvenc_available("hevc_nvenc"))
            self.assertFalse(hwaccel.amf_available("hevc_amf"))
        # Verdict cached without raising.
        self.assertIn("hevc_nvenc", hwaccel._nvenc_cache)
        self.assertIn("hevc_amf", hwaccel._amf_cache)


class BuildCmdArgMatrix(unittest.TestCase):
    def setUp(self) -> None:
        hwaccel._nvenc_cache.clear()
        hwaccel._amf_cache.clear()
        self._patches = [
            mock.patch.object(hwaccel, "nvenc_available", lambda enc="hevc_nvenc": True),
            mock.patch.object(hwaccel, "amf_available", lambda enc="hevc_amf": True),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self) -> None:
        for p in self._patches:
            p.stop()

    def test_nvenc_preference_mp4(self) -> None:
        s = default_settings()
        s.encoder_pref = "nvenc"
        cmd = _build(".mp4", s)
        self.assertIn("h264_nvenc", cmd)
        self.assertIn("-cq", cmd)
        self.assertIn("-tune", cmd)
        self.assertIn("hq", cmd)
        self.assertIn("yuv420p", cmd)
        self.assertNotIn("-crf", cmd)
        self.assertNotIn("libx264", cmd)

    def test_amf_preference_mp4(self) -> None:
        s = default_settings()
        s.encoder_pref = "amf"
        cmd = _build(".mp4", s)
        self.assertIn("h264_amf", cmd)
        self.assertIn("-rc", cmd)
        self.assertIn("cqp", cmd)
        # AMF CQP uses per-frame-type quantizers, not a single -qp.
        self.assertIn("-qp_i", cmd)
        self.assertIn("-qp_p", cmd)
        self.assertIn("-qp_b", cmd)
        self.assertNotIn("-qp", cmd)
        self.assertIn("-quality", cmd)
        self.assertIn("transcoding", cmd)
        self.assertNotIn("-crf", cmd)

    def test_nvenc_preferred_on_auto_when_both_present(self) -> None:
        s = default_settings()
        s.encoder_pref = "auto"
        cmd = _build(".mp4", s)
        self.assertIn("h264_nvenc", cmd)
        self.assertNotIn("h264_amf", cmd)

    def test_webm_ignores_gpu_pref(self) -> None:
        s = default_settings()
        s.encoder_pref = "nvenc"
        cmd = _build(".webm", s)
        self.assertIn("libvpx-vp9", cmd)
        self.assertNotIn("h264_nvenc", cmd)
        self.assertNotIn("hevc_nvenc", cmd)

    def test_avi_ignores_gpu_pref(self) -> None:
        s = default_settings()
        s.encoder_pref = "amf"
        cmd = _build(".avi", s)
        self.assertIn("mpeg4", cmd)
        self.assertNotIn("h264_amf", cmd)

    def test_cpu_preference_unchanged(self) -> None:
        s = default_settings()
        s.encoder_pref = "cpu"
        cmd = _build(".mp4", s)
        self.assertIn("libx264", cmd)
        self.assertIn("-crf", cmd)
        self.assertIn("-preset", cmd)
        self.assertNotIn("h264_nvenc", cmd)
        self.assertNotIn("h264_amf", cmd)


class BuildCmdNoGpu(unittest.TestCase):
    """With every probe False, GPU prefs still emit valid CPU commands."""

    def setUp(self) -> None:
        hwaccel._nvenc_cache.clear()
        hwaccel._amf_cache.clear()
        self._patches = [
            mock.patch.object(hwaccel, "nvenc_available", lambda enc="hevc_nvenc": False),
            mock.patch.object(hwaccel, "amf_available", lambda enc="hevc_amf": False),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self) -> None:
        for p in self._patches:
            p.stop()

    def test_forced_unavailable_vendor_falls_back_to_cpu(self) -> None:
        s = default_settings()
        s.encoder_pref = "nvenc"
        cmd = _build(".mp4", s)
        self.assertIn("libx264", cmd)
        self.assertIn("-crf", cmd)
        self.assertNotIn("h264_nvenc", cmd)


class VerdictTriState(unittest.TestCase):
    """Cache-only verdicts must distinguish unknown from known-unavailable."""

    def setUp(self) -> None:
        hwaccel._nvenc_cache.clear()

    def tearDown(self) -> None:
        hwaccel._nvenc_cache.clear()

    def test_unknown_when_unprobed(self) -> None:
        self.assertIsNone(hwaccel.nvenc_verdict())

    def test_false_only_when_all_probed_and_failed(self) -> None:
        for enc in hwaccel.NVENC_ENCODERS:
            hwaccel._nvenc_cache[enc] = False
        self.assertIs(hwaccel.nvenc_verdict(), False)

    def test_true_when_any_available(self) -> None:
        hwaccel._nvenc_cache[hwaccel.NVENC_ENCODERS[0]] = True
        self.assertIs(hwaccel.nvenc_verdict(), True)


class DialogPreservesUnknownPref(unittest.TestCase):
    """A saved GPU pref must survive a dialog opened before probes complete."""

    def setUp(self) -> None:
        hwaccel._nvenc_cache.clear()
        hwaccel._amf_cache.clear()
        from PySide6.QtWidgets import QApplication

        self._app = QApplication.instance() or QApplication([])

    def tearDown(self) -> None:
        hwaccel._nvenc_cache.clear()
        hwaccel._amf_cache.clear()

    def test_unknown_verdict_keeps_saved_vendor(self) -> None:
        from cove_converter.ui.quality_dialog import QualityDialog

        # Empty caches -> verdict None (unknown); pref must not reset to auto.
        s = default_settings()
        s.encoder_pref = "nvenc"
        dlg = QualityDialog(s)
        try:
            self.assertEqual(dlg.result_settings().encoder_pref, "nvenc")
        finally:
            dlg.deleteLater()

    def test_known_unavailable_resets_to_auto(self) -> None:
        from cove_converter.ui.quality_dialog import QualityDialog

        for enc in hwaccel.NVENC_ENCODERS:
            hwaccel._nvenc_cache[enc] = False
        s = default_settings()
        s.encoder_pref = "nvenc"
        dlg = QualityDialog(s)
        try:
            self.assertEqual(dlg.result_settings().encoder_pref, "auto")
        finally:
            dlg.deleteLater()


class SettingsRoundTrip(unittest.TestCase):
    def test_encoder_pref_survives_save_load(self) -> None:
        from PySide6.QtCore import QSettings

        QSettings("Cove", "UniversalConverter").clear()
        s = default_settings()
        s.encoder_pref = "nvenc"
        s.save()
        try:
            self.assertEqual(load_settings().encoder_pref, "nvenc")
        finally:
            QSettings("Cove", "UniversalConverter").clear()

    def test_unknown_stored_value_falls_back_to_auto(self) -> None:
        from PySide6.QtCore import QSettings

        qs = QSettings("Cove", "UniversalConverter")
        qs.clear()
        qs.beginGroup("quality")
        qs.setValue("encoder_pref", "bogus")
        qs.endGroup()
        try:
            self.assertEqual(load_settings().encoder_pref, "auto")
        finally:
            qs.clear()


if __name__ == "__main__":
    unittest.main()

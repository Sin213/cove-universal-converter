"""Regression tests for subtitle text-level conversion (Codex review)."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from cove_converter.engines.subtitles import _srt_to_vtt, _vtt_to_srt  # noqa: E402


class VttToSrt(unittest.TestCase):
    def test_drops_cue_settings_from_timing_line(self) -> None:
        vtt = (
            "WEBVTT\n\n"
            "00:00:01.000 --> 00:00:02.000 align:start\n"
            "Hello\n"
        )
        srt = _vtt_to_srt(vtt)
        self.assertIn("00:00:01,000 --> 00:00:02,000\n", srt)
        self.assertNotIn("align:start", srt)

    def test_drops_multiple_cue_settings(self) -> None:
        vtt = (
            "WEBVTT\n\n"
            "00:00:01.000 --> 00:00:02.000 align:start line:90% position:50%\n"
            "Hi\n"
        )
        srt = _vtt_to_srt(vtt)
        timing_line = srt.splitlines()[1]
        self.assertEqual(timing_line, "00:00:01,000 --> 00:00:02,000")

    def test_no_settings_still_converts(self) -> None:
        vtt = (
            "WEBVTT\n\n"
            "00:00:01.000 --> 00:00:02.000\n"
            "Plain\n"
        )
        srt = _vtt_to_srt(vtt)
        self.assertIn("00:00:01,000 --> 00:00:02,000\n", srt)
        self.assertIn("Plain", srt)
        self.assertTrue(srt.startswith("1\n"))

    def test_numbers_cues_sequentially(self) -> None:
        vtt = (
            "WEBVTT\n\n"
            "00:00:01.000 --> 00:00:02.000 align:start\n"
            "One\n\n"
            "00:00:03.000 --> 00:00:04.000\n"
            "Two\n"
        )
        srt = _vtt_to_srt(vtt)
        self.assertIn("1\n00:00:01,000 --> 00:00:02,000\nOne", srt)
        self.assertIn("2\n00:00:03,000 --> 00:00:04,000\nTwo", srt)

    def test_skips_note_and_style_blocks(self) -> None:
        vtt = (
            "WEBVTT\n\n"
            "NOTE this is a note\n\n"
            "STYLE\n::cue { color:red }\n\n"
            "00:00:01.000 --> 00:00:02.000\n"
            "Body\n"
        )
        srt = _vtt_to_srt(vtt)
        self.assertNotIn("NOTE", srt)
        self.assertNotIn("STYLE", srt)
        self.assertIn("Body", srt)

    def test_skips_bare_keyword_metadata_blocks(self) -> None:
        vtt = (
            "WEBVTT\n\n"
            "NOTE\n\n"
            "STYLE\n::cue { color:red }\n\n"
            "REGION\nid:fred width:40%\n\n"
            "00:00:01.000 --> 00:00:02.000\n"
            "Body\n"
        )
        srt = _vtt_to_srt(vtt)
        # The metadata blocks must be dropped, not converted into cues.
        self.assertNotIn("REGION", srt)
        self.assertNotIn("STYLE", srt)
        self.assertIn("Body", srt)

    def test_cue_identifier_starting_with_note_preserved(self) -> None:
        vtt = (
            "WEBVTT\n\n"
            "NOTE1\n"
            "00:00:01.000 --> 00:00:02.000\n"
            "Body\n"
        )
        srt = _vtt_to_srt(vtt)
        self.assertIn("00:00:01,000 --> 00:00:02,000\n", srt)
        self.assertIn("Body", srt)
        self.assertTrue(srt.startswith("1\n"))

    def test_cue_identifier_starting_with_style_preserved(self) -> None:
        vtt = (
            "WEBVTT\n\n"
            "STYLE_A\n"
            "00:00:01.000 --> 00:00:02.000\n"
            "Body\n"
        )
        srt = _vtt_to_srt(vtt)
        self.assertIn("00:00:01,000 --> 00:00:02,000\n", srt)
        self.assertIn("Body", srt)

    def test_cue_identifier_starting_with_region_preserved(self) -> None:
        vtt = (
            "WEBVTT\n\n"
            "REGION42\n"
            "00:00:01.000 --> 00:00:02.000\n"
            "Body\n"
        )
        srt = _vtt_to_srt(vtt)
        self.assertIn("00:00:01,000 --> 00:00:02,000\n", srt)
        self.assertIn("Body", srt)

    def test_hourless_timestamp_padded_to_srt(self) -> None:
        vtt = (
            "WEBVTT\n\n"
            "01:02.345 --> 01:04.000\n"
            "Hourless\n"
        )
        srt = _vtt_to_srt(vtt)
        self.assertIn("00:01:02,345 --> 00:01:04,000\n", srt)
        self.assertIn("Hourless", srt)
        self.assertTrue(srt.startswith("1\n"))

    def test_hourless_with_cue_settings_strips_settings(self) -> None:
        vtt = (
            "WEBVTT\n\n"
            "01:02.345 --> 01:04.000 align:start line:90%\n"
            "Hi\n"
        )
        srt = _vtt_to_srt(vtt)
        timing_line = srt.splitlines()[1]
        self.assertEqual(timing_line, "00:01:02,345 --> 00:01:04,000")
        self.assertNotIn("align:start", srt)
        self.assertNotIn("line:90%", srt)

    def test_hourful_with_cue_settings_still_works(self) -> None:
        vtt = (
            "WEBVTT\n\n"
            "00:00:01.000 --> 00:00:02.000 align:start line:90%\n"
            "Body\n"
        )
        srt = _vtt_to_srt(vtt)
        timing_line = srt.splitlines()[1]
        self.assertEqual(timing_line, "00:00:01,000 --> 00:00:02,000")
        self.assertIn("Body", srt)


class SrtToVtt(unittest.TestCase):
    def test_basic_conversion(self) -> None:
        srt = (
            "1\n"
            "00:00:01,000 --> 00:00:02,000\n"
            "Hello\n"
        )
        vtt = _srt_to_vtt(srt)
        self.assertTrue(vtt.startswith("WEBVTT\n"))
        self.assertIn("00:00:01.000 --> 00:00:02.000", vtt)
        self.assertNotIn("\n1\n", vtt)


if __name__ == "__main__":
    unittest.main()

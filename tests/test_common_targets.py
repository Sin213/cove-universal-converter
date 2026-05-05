"""Unit tests for routing.common_targets — the intersection helper that
populates the Batch Format dropdown."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cove_converter.routing import common_targets, targets_for


def test_empty_input_returns_empty_tuple():
    assert common_targets([]) == ()


def test_single_extension_equals_targets_for():
    assert common_targets([".png"]) == targets_for(".png")


def test_unknown_extension_returns_empty():
    assert common_targets([".xyz"]) == ()


def test_image_video_mix_has_no_common_format():
    assert common_targets([".png", ".mp4"]) == ()


def test_two_pngs_match_full_png_targets():
    assert common_targets([".png", ".png"]) == targets_for(".png")


def test_png_and_jpg_intersect_to_their_overlap():
    result = common_targets([".png", ".jpg"])
    assert set(result) == set(targets_for(".png")) & set(targets_for(".jpg"))
    # Order follows the first input's targets_for ordering.
    expected_order = tuple(t for t in targets_for(".png") if t in set(result))
    assert result == expected_order


def test_audio_mix_keeps_full_audio_target_set():
    # mp3 + wav share every audio target by design.
    result = common_targets([".mp3", ".wav"])
    assert set(result) == set(targets_for(".mp3")) & set(targets_for(".wav"))
    # And nothing was reordered relative to the first input.
    assert result == tuple(t for t in targets_for(".mp3") if t in set(result))

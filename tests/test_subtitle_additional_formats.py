import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from cove_converter.engines.subtitles import (  # noqa: E402
    SubtitleWorker,
    _manual_convert,
    _sbv_to_srt,
    _srt_to_sbv,
)
from cove_converter.ui.main_window import (  # noqa: E402
    _SUBTITLE_STYLE_WARNING,
    _target_tooltip,
)


SBV_TEXT = (
    "00:00:01.250,00:00:02.500\n"
    "Hello\n"
    "world\n"
    "\n"
    "12:34:56.789,12:34:57.000\n"
    "Bye\n"
)
SRT_TEXT = (
    "1\n"
    "00:00:01,250 --> 00:00:02,500\n"
    "Hello\n"
    "world\n"
    "\n"
    "2\n"
    "12:34:56,789 --> 12:34:57,000\n"
    "Bye\n"
)


def test_sbv_srt_helpers_round_trip() -> None:
    assert _sbv_to_srt(SBV_TEXT) == SRT_TEXT
    assert _srt_to_sbv(SRT_TEXT) == SBV_TEXT


def test_sbv_to_srt_rejects_malformed_cue() -> None:
    malformed = SBV_TEXT + "\nnot a timestamp\nlost\n"
    with pytest.raises(RuntimeError, match="Invalid SBV timing in cue 3"):
        _sbv_to_srt(malformed)


def test_srt_to_sbv_rejects_malformed_cue() -> None:
    malformed = SRT_TEXT + "\n3\nnot a timestamp\nlost\n"
    with pytest.raises(RuntimeError, match="Invalid SRT timing in cue 3"):
        _srt_to_sbv(malformed)


def test_manual_sbv_vtt_conversion_round_trip() -> None:
    vtt_text = _manual_convert(SBV_TEXT, ".sbv", ".vtt")

    assert vtt_text.startswith("WEBVTT\n")
    assert "00:00:01.250 --> 00:00:02.500" in vtt_text
    assert _manual_convert(vtt_text, ".vtt", ".sbv") == SBV_TEXT


def test_sbv_to_ass_uses_temporary_srt_bridge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_path = tmp_path / "captions.sbv"
    output_path = tmp_path / "captions.ass"
    source_path.write_text(SBV_TEXT, encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_run_ffmpeg(
        _worker: SubtitleWorker, source: Path, target: Path, out_ext: str
    ) -> None:
        captured["source"] = source
        captured["target"] = target
        captured["out_ext"] = out_ext
        captured["source_text"] = source.read_text(encoding="utf-8")
        target.write_text("[Script Info]\n", encoding="utf-8")

    monkeypatch.setattr(SubtitleWorker, "_run_ffmpeg", fake_run_ffmpeg)

    SubtitleWorker(source_path, output_path)._convert()

    temporary_source = captured["source"]
    assert isinstance(temporary_source, Path)
    assert temporary_source.name == "source.srt"
    assert captured["source_text"] == SRT_TEXT
    assert captured["target"] == output_path
    assert captured["out_ext"] == ".ass"
    assert not temporary_source.exists()
    assert output_path.read_text(encoding="utf-8") == "[Script Info]\n"


def test_ass_to_sbv_uses_temporary_srt_bridge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_path = tmp_path / "captions.ass"
    output_path = tmp_path / "captions.sbv"
    source_path.write_text("[Script Info]\n", encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_run_ffmpeg(
        _worker: SubtitleWorker, source: Path, target: Path, out_ext: str
    ) -> None:
        captured["source"] = source
        captured["target"] = target
        captured["out_ext"] = out_ext
        target.write_text(SRT_TEXT, encoding="utf-8")

    monkeypatch.setattr(SubtitleWorker, "_run_ffmpeg", fake_run_ffmpeg)

    SubtitleWorker(source_path, output_path)._convert()

    temporary_target = captured["target"]
    assert isinstance(temporary_target, Path)
    assert captured["source"] == source_path
    assert temporary_target.name == "target.srt"
    assert captured["out_ext"] == ".srt"
    assert not temporary_target.exists()
    assert output_path.read_text(encoding="utf-8") == SBV_TEXT


@pytest.mark.parametrize("source_ext", [".ass", ".ssa"])
def test_ass_and_ssa_to_srt_show_style_loss_warning(source_ext: str) -> None:
    assert _target_tooltip(source_ext, ".srt") == _SUBTITLE_STYLE_WARNING

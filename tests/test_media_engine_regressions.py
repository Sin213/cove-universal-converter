from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest
from PIL import Image

from cove_converter.engines import ffmpeg as ffmpeg_engine
from cove_converter.engines import hwaccel
from cove_converter.engines.ffmpeg import FFmpegWorker, _audio_encode_args
from cove_converter.engines.pillow import PillowWorker
from cove_converter.settings import default_settings


def _ffmpeg_worker(output_suffix: str) -> FFmpegWorker:
    worker = FFmpegWorker.__new__(FFmpegWorker)
    worker.input_path = Path("/tmp/input.3gp")
    worker.output_path = Path(f"/tmp/output{output_suffix}")
    worker.settings = default_settings()
    worker.settings.encoder_pref = "cpu"
    worker._cancel = False
    worker.progress = mock.Mock()
    worker.status = mock.Mock()
    return worker


def _argument_value(cmd: list[str], flag: str) -> str:
    return cmd[cmd.index(flag) + 1]


def test_audio_args_keep_opus_and_vorbis_within_supported_limits() -> None:
    assert _audio_encode_args("libopus", 320) == [
        "-c:a",
        "libopus",
        "-b:a",
        "256k",
    ]
    assert _audio_encode_args("libvorbis", 320) == [
        "-c:a",
        "libvorbis",
        "-ar",
        "44100",
        "-b:a",
        "192k",
    ]
    assert _audio_encode_args("alac", 320) == ["-c:a", "alac"]


@pytest.mark.parametrize(
    ("suffix", "codec"),
    [
        (".aif", "pcm_s16be"),
        (".ac3", "ac3"),
        (".mp2", "mp2"),
        (".spx", "libspeex"),
        (".caf", "pcm_s16le"),
        (".au", "pcm_s16be"),
        (".wv", "wavpack"),
        (".voc", "pcm_s16le"),
        (".w64", "pcm_s16le"),
        (".mka", "libopus"),
        (".m4b", "aac"),
        (".oga", "libvorbis"),
        (".tta", "tta"),
        (".amr", "libopencore_amrnb"),
        (".weba", "libopus"),
    ],
)
def test_added_audio_outputs_use_verified_codecs(
    suffix: str, codec: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ffmpeg_engine, "resolve", lambda _name: "ffmpeg")
    cmd = _ffmpeg_worker(suffix)._build_cmd()

    assert "-vn" in cmd
    assert _argument_value(cmd, "-c:a") == codec


def test_weba_selects_webm_muxer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ffmpeg_engine, "resolve", lambda _name: "ffmpeg")
    cmd = _ffmpeg_worker(".weba")._build_cmd()

    assert _argument_value(cmd, "-f") == "webm"


@pytest.mark.parametrize(
    ("suffix", "expected_codec"),
    [
        (".mp4", "libaom-av1"),
        (".mkv", "libaom-av1"),
        (".mov", "libx264"),
    ],
)
def test_av1_setting_only_applies_to_mp4_and_mkv(
    suffix: str,
    expected_codec: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ffmpeg_engine, "resolve", lambda _name: "ffmpeg")
    worker = _ffmpeg_worker(suffix)
    worker.settings.video_codec = "av1"

    assert _argument_value(worker._build_cmd(), "-c:v") == expected_codec


@pytest.mark.parametrize(
    ("suffix", "expected_codec"),
    [
        (".m4a", "alac"),
        (".m4b", "aac"),
    ],
)
def test_alac_setting_only_applies_to_m4a(
    suffix: str,
    expected_codec: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ffmpeg_engine, "resolve", lambda _name: "ffmpeg")
    worker = _ffmpeg_worker(suffix)
    worker.settings.m4a_codec = "alac"

    assert _argument_value(worker._build_cmd(), "-c:a") == expected_codec


def test_amr_is_constrained_to_narrowband_audio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ffmpeg_engine, "resolve", lambda _name: "ffmpeg")
    cmd = _ffmpeg_worker(".amr")._build_cmd()

    assert _argument_value(cmd, "-ar") == "8000"
    assert _argument_value(cmd, "-ac") == "1"
    assert _argument_value(cmd, "-b:a") == "12.2k"


@pytest.mark.parametrize(
    ("suffix", "video_codec", "audio_codec"),
    [
        (".mxf", "mpeg2video", "pcm_s16le"),
        (".rm", "rv10", "ac3"),
        (".swf", "flv1", "libmp3lame"),
        (".vob", "mpeg2video", "mp2"),
        (".asf", "msmpeg4v3", "wmav2"),
        (".ogv", "libtheora", "libvorbis"),
        (".m2ts", "mpeg2video", "mp2"),
        (".mts", "mpeg2video", "mp2"),
        (".f4v", "libx264", "aac"),
        (".y4m", "rawvideo", None),
        (".ivf", "libvpx-vp9", None),
    ],
)
def test_added_video_outputs_use_verified_profiles(
    suffix: str,
    video_codec: str,
    audio_codec: str | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ffmpeg_engine, "resolve", lambda _name: "ffmpeg")
    cmd = _ffmpeg_worker(suffix)._build_cmd()

    assert _argument_value(cmd, "-c:v") == video_codec
    if audio_codec is None:
        assert "-an" in cmd
        assert "-c:a" not in cmd
    else:
        assert _argument_value(cmd, "-c:a") == audio_codec


def test_mxf_forces_48_khz_audio(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ffmpeg_engine, "resolve", lambda _name: "ffmpeg")
    cmd = _ffmpeg_worker(".mxf")._build_cmd()

    assert _argument_value(cmd, "-ar") == "48000"


def test_dv_remains_input_only() -> None:
    assert ".dv" not in ffmpeg_engine._VIDEO_CODEC


@pytest.mark.parametrize("suffix", [".webm", ".avi"])
def test_video_commands_scale_odd_dimensions_to_even(
    suffix: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ffmpeg_engine, "resolve", lambda _name: "ffmpeg")
    cmd = _ffmpeg_worker(suffix)._build_cmd()

    assert "scale=ceil(iw/2)*2:ceil(ih/2)*2" in cmd


def test_missing_ffmpeg_stderr_pipe_is_a_runtime_error(monkeypatch: pytest.MonkeyPatch) -> None:
    process = SimpleNamespace(
        stderr=None,
        terminate=mock.Mock(),
        wait=mock.Mock(return_value=0),
    )
    worker = _ffmpeg_worker(".ogg")
    monkeypatch.setattr(worker, "_build_cmd", lambda: ["ffmpeg"])
    monkeypatch.setattr(ffmpeg_engine.subprocess, "Popen", lambda *args, **kwargs: process)

    with pytest.raises(RuntimeError, match="stderr stream"):
        worker._convert()

    process.terminate.assert_called_once_with()
    process.wait.assert_called_once_with()


@pytest.mark.parametrize(
    ("returncode", "stdout", "expected"),
    [
        (0, " V..... h264_nvenc_encoder NVIDIA NVENC H.264 encoder", False),
        (0, " V....D h264_nvenc NVIDIA NVENC H.264 encoder", True),
        (1, " V....D h264_nvenc NVIDIA NVENC H.264 encoder", False),
    ],
)
def test_encoder_probe_requires_exact_successful_listing(
    monkeypatch: pytest.MonkeyPatch,
    returncode: int,
    stdout: str,
    expected: bool,
) -> None:
    monkeypatch.setattr(hwaccel, "resolve", lambda binary: binary)
    monkeypatch.setattr(
        hwaccel.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=returncode, stdout=stdout),
    )

    assert hwaccel._encoder_listed("h264_nvenc") is expected


def test_pillow_applies_exif_orientation(tmp_path: Path) -> None:
    source = tmp_path / "oriented.jpg"
    output = tmp_path / "oriented.png"
    image = Image.new("RGB", (2, 3), "red")
    exif = image.getexif()
    exif[274] = 6
    image.save(source, exif=exif)
    image.close()

    worker = PillowWorker.__new__(PillowWorker)
    worker.input_path = source
    worker.output_path = output
    worker.settings = default_settings()
    worker.progress = mock.Mock()
    worker._convert()

    with Image.open(output) as converted:
        assert converted.size == (3, 2)


def test_pillow_flattens_palette_transparency_for_bmp(tmp_path: Path) -> None:
    source = tmp_path / "transparent.png"
    output = tmp_path / "transparent.bmp"
    image = Image.new("P", (2, 1))
    image.putpalette([0, 0, 0, 255, 0, 0] + [0, 0, 0] * 254)
    image.putdata([0, 1])
    image.info["transparency"] = 0
    image.save(source)
    image.close()

    worker = PillowWorker.__new__(PillowWorker)
    worker.input_path = source
    worker.output_path = output
    worker.settings = default_settings()
    worker.progress = mock.Mock()
    worker._convert()

    with Image.open(output) as converted:
        with converted.convert("RGB") as rgb:
            assert rgb.getpixel((0, 0)) == (255, 255, 255)
            assert rgb.getpixel((1, 0)) == (255, 0, 0)

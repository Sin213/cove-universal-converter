from pathlib import Path
from unittest import mock

import pytest
from PIL import Image

from cove_converter.engines.pillow import PillowWorker
from cove_converter.settings import ConversionSettings, default_settings


def _convert(
    source: Path, output: Path, settings: ConversionSettings | None = None
) -> None:
    worker = PillowWorker.__new__(PillowWorker)
    worker.input_path = source
    worker.output_path = output
    worker.settings = settings or default_settings()
    worker.progress = mock.Mock()
    worker._convert()


@pytest.mark.parametrize("suffix", [".jfif", ".jpe"])
def test_jpeg_aliases_are_writable(tmp_path: Path, suffix: str) -> None:
    source = tmp_path / "source.png"
    output = tmp_path / f"converted{suffix}"
    with Image.new("RGB", (8, 8), "red") as image:
        image.save(source)

    _convert(source, output)

    with Image.open(output) as converted:
        assert converted.format == "JPEG"
        assert converted.mode == "RGB"


@pytest.mark.parametrize(
    ("suffix", "expected_mode", "magic"),
    [
        (".pgm", "L", b"P5"),
        (".pbm", "1", b"P4"),
    ],
)
def test_portable_anymap_output_matches_extension(
    tmp_path: Path,
    suffix: str,
    expected_mode: str,
    magic: bytes,
) -> None:
    source = tmp_path / "source.png"
    output = tmp_path / f"converted{suffix}"
    with Image.new("RGB", (8, 8), "red") as image:
        image.save(source)

    _convert(source, output)

    assert output.read_bytes().startswith(magic)
    with Image.open(output) as converted:
        assert converted.mode == expected_mode


@pytest.mark.parametrize("suffix", [".jp2", ".j2k", ".jpx"])
def test_jpeg2000_aliases_convert_palette_images(
    tmp_path: Path, suffix: str
) -> None:
    source = tmp_path / "palette.png"
    output = tmp_path / f"converted{suffix}"
    with Image.new("P", (8, 8)) as image:
        image.putpalette([255, 0, 0, 0, 255, 0] + [0, 0, 0] * 254)
        image.putdata([0, 1] * 32)
        image.save(source)

    _convert(source, output)

    with Image.open(output) as converted:
        assert converted.format == "JPEG2000"
        assert converted.mode == "RGB"


@pytest.mark.parametrize(
    ("mode", "source_suffix", "color"),
    [
        ("RGBA", ".png", (255, 0, 0, 128)),
        ("CMYK", ".tiff", (0, 255, 255, 0)),
    ],
)
def test_pcx_converts_unsupported_modes(
    tmp_path: Path, mode: str, source_suffix: str, color: tuple[int, ...]
) -> None:
    source = tmp_path / f"source{source_suffix}"
    output = tmp_path / "converted.pcx"
    with Image.new(mode, (8, 8), color) as image:
        image.save(source)

    _convert(source, output)

    with Image.open(output) as converted:
        assert converted.format == "PCX"
        assert converted.mode == "RGB"


def test_tga_converts_cmyk_images(tmp_path: Path) -> None:
    source = tmp_path / "source.tiff"
    output = tmp_path / "converted.tga"
    with Image.new("CMYK", (8, 8), (0, 255, 255, 0)) as image:
        image.save(source)

    _convert(source, output)

    with Image.open(output) as converted:
        assert converted.format == "TGA"
        assert converted.mode == "RGB"


def test_avif_uses_image_quality_setting(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    output = tmp_path / "converted.avif"
    with Image.new("RGB", (8, 8), "red") as image:
        image.save(source)
    settings = default_settings()
    settings.use_custom_quality = True
    settings.jpeg_quality = 73

    with mock.patch.object(Image.Image, "save", autospec=True) as save:
        _convert(source, output, settings)

    assert save.call_args.kwargs["quality"] == 73


def test_multipage_tiff_stays_multipage_when_converted_to_webp(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.tiff"
    output = tmp_path / "converted.webp"
    frames = [Image.new("RGB", (8, 8), color) for color in ("red", "green", "blue")]
    try:
        frames[0].save(source, save_all=True, append_images=frames[1:])
    finally:
        for frame in frames:
            frame.close()

    _convert(source, output)

    with Image.open(output) as converted:
        assert converted.n_frames == 3


def test_animated_webp_stays_multipage_when_converted_to_tiff(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.webp"
    output = tmp_path / "converted.tiff"
    frames = [Image.new("RGB", (8, 8), color) for color in ("red", "green", "blue")]
    try:
        frames[0].save(
            source,
            save_all=True,
            append_images=frames[1:],
            duration=[40, 50, 60],
            loop=0,
            lossless=True,
        )
    finally:
        for frame in frames:
            frame.close()

    _convert(source, output)

    with Image.open(output) as converted:
        assert converted.n_frames == 3

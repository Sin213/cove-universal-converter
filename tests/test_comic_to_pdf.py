from __future__ import annotations

import tarfile
import zipfile
from pathlib import Path

import pytest
from PIL import Image
from pypdf import PdfReader

from cove_converter.engines import pdf as pdf_engine
from cove_converter.engines.pdf import PdfWorker
from cove_converter.settings import ConversionSettings


ADVERTISED_IMAGE_EXTS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".jpe",
    ".jfif",
    ".webp",
    ".bmp",
    ".tiff",
    ".tif",
    ".ico",
    ".heic",
    ".heif",
    ".avif",
    ".jp2",
    ".j2k",
    ".jpx",
    ".tga",
    ".pcx",
    ".ppm",
    ".pgm",
    ".pbm",
    ".dds",
    ".icns",
}


def _make_comic(tmp_path: Path, extension: str) -> Path:
    pages = tmp_path / f"pages-{extension[1:]}" / "nested"
    pages.mkdir(parents=True)
    for name, width in (("page10.png", 110), ("page2.png", 102)):
        with Image.new("RGB", (width, 20), "navy") as image:
            image.save(pages / name)
    with Image.new("RGBA", (101, 20), (255, 0, 0, 0)) as image:
        image.save(pages / "page1.png")
    (pages / "page3.txt").write_text("not an image", encoding="utf-8")

    archive = tmp_path / f"book{extension}"
    if extension == ".cbz":
        with zipfile.ZipFile(archive, "w") as comic:
            for path in pages.parent.rglob("*"):
                if path.is_file():
                    comic.write(path, path.relative_to(pages.parent))
    else:
        with tarfile.open(archive, "w") as comic:
            comic.add(pages.parent, arcname="book")
    return archive


def test_image_to_pdf_accepts_all_advertised_pillow_inputs():
    assert ADVERTISED_IMAGE_EXTS <= pdf_engine._IMAGE_TO_PDF_EXTS


def test_prepare_pdf_image_flattens_transparency_to_rgb():
    with Image.new("RGBA", (2, 1), (255, 0, 0, 0)) as raw:
        raw.putpixel((1, 0), (255, 0, 0, 255))
        prepared = pdf_engine._prepare_pdf_image(raw)

    try:
        assert prepared.mode == "RGB"
        assert prepared.getpixel((0, 0)) == (255, 255, 255)
        assert prepared.getpixel((1, 0)) == (255, 0, 0)
    finally:
        prepared.close()


def test_multipage_tiff_to_pdf_preserves_all_frames(tmp_path: Path) -> None:
    source = tmp_path / "pages.tiff"
    output = tmp_path / "pages.pdf"
    frames = [
        Image.new("RGB", (101 + index, 20), color)
        for index, color in enumerate(("red", "green", "blue"))
    ]
    try:
        frames[0].save(source, save_all=True, append_images=frames[1:])
    finally:
        for frame in frames:
            frame.close()

    progress: list[int] = []
    pdf_engine._image_to_pdf(source, output, progress=progress.append)

    reader = PdfReader(output)
    assert len(reader.pages) == 3
    assert progress == sorted(progress)
    assert progress[-1] == 95


@pytest.mark.parametrize("extension", [".cbz", ".cbt"])
def test_comic_to_pdf_recurses_natural_sorts_and_ignores_non_images(
    tmp_path,
    extension,
):
    archive = _make_comic(tmp_path, extension)
    output = tmp_path / f"{extension[1:]}.pdf"
    progress: list[int] = []

    pdf_engine._comic_to_pdf(archive, output, progress=progress.append)

    reader = PdfReader(output)
    assert [round(float(page.mediabox.width)) for page in reader.pages] == [
        101,
        102,
        110,
    ]
    assert progress == sorted(progress)
    assert progress[0] == 5
    assert progress[-1] == 95


def test_comic_to_pdf_errors_when_archive_has_no_images(tmp_path):
    archive = tmp_path / "empty.cbz"
    with zipfile.ZipFile(archive, "w") as comic:
        comic.writestr("README.txt", "nothing to render")

    with pytest.raises(RuntimeError, match="no supported images"):
        pdf_engine._comic_to_pdf(archive, tmp_path / "out.pdf")


def test_comic_to_pdf_honours_early_cancellation(tmp_path):
    archive = _make_comic(tmp_path, ".cbz")
    output = tmp_path / "cancelled.pdf"
    progress: list[int] = []

    pdf_engine._comic_to_pdf(
        archive,
        output,
        progress=progress.append,
        cancelled=lambda: True,
    )

    assert not output.exists()
    assert progress == []


def test_pdf_worker_routes_cbt_to_comic_converter(tmp_path, monkeypatch):
    source = tmp_path / "book.cbt"
    destination = tmp_path / "book.pdf"
    source.touch()
    calls: list[tuple[Path, Path]] = []

    def fake_convert(src, dst, **_kwargs):
        calls.append((src, dst))

    monkeypatch.setattr(pdf_engine, "_comic_to_pdf", fake_convert)
    worker = PdfWorker(source, destination, settings=ConversionSettings())
    worker.output_path = destination
    worker._convert()

    assert calls == [(source, destination)]

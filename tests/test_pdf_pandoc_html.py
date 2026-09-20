"""Tests for the document→PDF (Pandoc) path.

Covers the previously-silent failure where ``_strip_inline_css`` would
crash with a raw ``TypeError`` because ``_pandoc_to_html`` returned
``None``. The UI rendered that as a bare "Failed" with no detail.

These tests prove:
  * ``_strip_inline_css(None)`` raises ``RuntimeError`` (not ``TypeError``).
  * ``_pandoc_to_html`` raises ``RuntimeError`` when subprocess returns 0
    but produces no stdout.
  * Pandoc is invoked with explicit ``-o -`` so HTML always lands on stdout.
  * A minimal generated EPUB round-trips through the path (skipped if
    pandoc is unavailable in the runner environment).
"""
from __future__ import annotations

import os
import shutil
import sys
import zipfile
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from cove_converter.engines import pdf as pdf_engine
from cove_converter.engines.pdf import (
    _html_to_pdf,
    _local_resource_callback,
    _pandoc_to_html,
    _strip_inline_css,
)


# ---- _strip_inline_css ------------------------------------------------------

def test_strip_inline_css_none_raises_runtime_error() -> None:
    with pytest.raises(RuntimeError) as excinfo:
        _strip_inline_css(None)
    assert "no html output" in str(excinfo.value).lower()


def test_strip_inline_css_passes_through_string() -> None:
    html = "<html><head><style>x{}</style></head><body>ok</body></html>"
    cleaned = _strip_inline_css(html)
    assert "<style>" not in cleaned
    assert "ok" in cleaned


# ---- _pandoc_to_html --------------------------------------------------------

def _fake_completed(stdout: str | None, *, returncode: int = 0, stderr: str = "") -> mock.Mock:
    fake = mock.Mock()
    fake.stdout = stdout
    fake.stderr = stderr
    fake.returncode = returncode
    return fake


def _mock_resolve(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub ``resolve()`` so tests don't need pandoc installed."""
    monkeypatch.setattr(pdf_engine, "resolve", lambda _name: "pandoc")


def test_pandoc_to_html_raises_when_stdout_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_resolve(monkeypatch)
    captured: dict[str, list[str]] = {}

    def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
        captured["cmd"] = list(cmd)
        return _fake_completed(stdout=None, returncode=0)

    monkeypatch.setattr(pdf_engine.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError) as excinfo:
        _pandoc_to_html(Path("/nonexistent/sample.epub"))
    assert "no HTML output" in str(excinfo.value)
    assert "-o" in captured["cmd"]
    assert captured["cmd"][captured["cmd"].index("-o") + 1] == "-"


def test_pandoc_to_html_raises_when_stdout_blank(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_resolve(monkeypatch)
    monkeypatch.setattr(
        pdf_engine.subprocess, "run", lambda *a, **k: _fake_completed("   \n\n  ", returncode=0)
    )
    with pytest.raises(RuntimeError) as excinfo:
        _pandoc_to_html(Path("/nonexistent/sample.epub"))
    assert "no HTML output" in str(excinfo.value)


def test_pandoc_to_html_propagates_stderr_on_nonzero(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_resolve(monkeypatch)
    monkeypatch.setattr(
        pdf_engine.subprocess, "run",
        lambda *a, **k: _fake_completed("", returncode=2, stderr="bad input file"),
    )
    with pytest.raises(RuntimeError) as excinfo:
        _pandoc_to_html(Path("/nonexistent/sample.epub"))
    assert "bad input file" in str(excinfo.value)


def test_pandoc_to_html_returns_string_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_resolve(monkeypatch)
    monkeypatch.setattr(
        pdf_engine.subprocess, "run",
        lambda *a, **k: _fake_completed("<html><body>hi</body></html>", returncode=0),
    )
    out = _pandoc_to_html(Path("/nonexistent/sample.epub"))
    assert isinstance(out, str)
    assert "hi" in out


def test_pandoc_uses_input_directory_as_resource_path(monkeypatch, tmp_path) -> None:
    _mock_resolve(monkeypatch)
    captured: dict[str, list[str]] = {}

    def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
        captured["cmd"] = list(cmd)
        return _fake_completed("<html><body>ok</body></html>")

    monkeypatch.setattr(pdf_engine.subprocess, "run", fake_run)
    source = tmp_path / "documents" / "input.md"
    _pandoc_to_html(source)
    assert f"--resource-path={source.parent.resolve()}" in captured["cmd"]


def test_html_to_pdf_embeds_relative_sibling_image(tmp_path) -> None:
    from PIL import Image
    from pypdf import PdfReader

    source = tmp_path / "page.html"
    image = tmp_path / "sibling.png"
    output = tmp_path / "out.pdf"
    Image.new("RGB", (80, 60), (220, 20, 20)).save(image)
    html_source = "<html><body><img src='sibling.png' /></body></html>"

    _html_to_pdf(html_source, output, source_path=source)

    resources = PdfReader(str(output)).pages[0]["/Resources"]
    assert resources.get("/XObject"), "relative sibling image was omitted"


def test_html_resource_callback_reports_remote_and_missing_resources(tmp_path) -> None:
    source = tmp_path / "safe" / "page.html"
    callback = _local_resource_callback(source)

    with pytest.raises(RuntimeError, match="offline"):
        callback("https://example.test/tracker.png", "")
    with pytest.raises(RuntimeError, match="Missing local resource"):
        callback("missing.png", "")


def test_html_resource_callback_rejects_percent_encoded_unc_path(tmp_path) -> None:
    """A percent-encoded UNC path has no literal backslash for the raw
    remote-resource check to catch, but decodes to a real network path
    (absolute on Windows) - reject it as remote after decoding too."""
    source = tmp_path / "page.html"
    callback = _local_resource_callback(source)

    with pytest.raises(RuntimeError, match="offline"):
        callback("%5c%5cserver%5cshare%5cimage.png", "")


def test_html_conversion_fails_on_missing_image(tmp_path) -> None:
    with pytest.raises(RuntimeError, match="Missing local resource"):
        _html_to_pdf('<img src="missing.png">', tmp_path / "out.pdf",
                     source_path=tmp_path / "in.html")


def test_html_resources_resolve_against_stylesheet_directory(tmp_path) -> None:
    css_dir = tmp_path / "styles"
    css_dir.mkdir()
    image = css_dir / "texture.png"
    image.write_bytes(b"resource")
    callback = _local_resource_callback(tmp_path / "in.html")
    assert callback("texture.png", str(css_dir)) == str(image)
    assert callback(image.as_uri(), "") == str(image)


# ---- generated-EPUB smoke ---------------------------------------------------

_EPUB_CONTAINER_XML = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""

_EPUB_OPF = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="bookid">test-book</dc:identifier>
    <dc:title>Tiny Test Book</dc:title>
    <dc:language>en</dc:language>
  </metadata>
  <manifest>
    <item id="ch1" href="ch1.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="ch1"/>
  </spine>
</package>
"""

_EPUB_CHAPTER = """<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml">
  <head><title>Ch 1</title></head>
  <body><h1>Hello</h1><p>World.</p></body>
</html>
"""


def _write_minimal_epub(target: Path) -> None:
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        # ``mimetype`` must be the first entry, stored uncompressed.
        info = zipfile.ZipInfo("mimetype")
        info.compress_type = zipfile.ZIP_STORED
        zf.writestr(info, "application/epub+zip")
        zf.writestr("META-INF/container.xml", _EPUB_CONTAINER_XML)
        zf.writestr("OEBPS/content.opf", _EPUB_OPF)
        zf.writestr("OEBPS/ch1.xhtml", _EPUB_CHAPTER)


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc not installed")
def test_generated_epub_roundtrips_through_pandoc(tmp_path: Path) -> None:
    epub = tmp_path / "tiny.epub"
    _write_minimal_epub(epub)
    html = _pandoc_to_html(epub)
    assert isinstance(html, str)
    assert html.strip(), "pandoc returned blank stdout for a valid EPUB"
    cleaned = _strip_inline_css(html)
    assert "Hello" in cleaned

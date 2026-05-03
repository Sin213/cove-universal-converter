"""Smoke tests for the Enhance Scanned PDF feature.

Fixtures are synthesised at runtime so nothing binary is committed. Tests
cover both the in-process ``_convert`` path *and* the
``BaseConverterWorker.run()`` lifecycle so the temp-file + ``os.replace``
finalisation and cancel-cleanup paths are exercised end-to-end.
"""
from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pypdfium2 as pdfium
import pytest
from PIL import Image, ImageDraw

from cove_converter.engines.pdf import PdfWorker, _enhance_scanned_pdf
from cove_converter.settings import ConversionSettings


# ---- Fixture builders ------------------------------------------------------

def _synth_scanned_pdf(
    path: Path,
    *,
    pages: int = 2,
    px_size: tuple[int, int] = (850, 1100),
    resolution: float = 100.0,
) -> None:
    """Tiny PDF that mimics a faded scan: gray-cast background above the
    whitening threshold (240 > 230) and mid-gray "text" so the contrast
    bump has something to darken. ``px_size`` and ``resolution`` together
    determine the embedded page dimensions in PDF points."""
    imgs = []
    for i in range(pages):
        img = Image.new("RGB", px_size, color=(240, 240, 240))
        draw = ImageDraw.Draw(img)
        for line in range(8):
            y = 60 + i * 40 + line * 18
            draw.text((60, y), f"P{i + 1} faded text line {line}", fill=(110, 110, 110))
        draw.line((60, 200, px_size[0] - 50, 200), fill=(180, 180, 180), width=1)
        imgs.append(img)
    imgs[0].save(path, "PDF", resolution=resolution,
                 save_all=True, append_images=imgs[1:])


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run_worker_direct(src: Path, dst: Path, *, enhance: bool, dpi: int = 150) -> None:
    """Drive ``PdfWorker._convert`` directly without spinning up a QThread."""
    settings = ConversionSettings(enhance_scanned_pdf=enhance, pdf_enhance_dpi=dpi)
    worker = PdfWorker(src, dst, settings=settings)
    worker.output_path = dst
    worker._convert()


def _run_worker_lifecycle(src: Path, dst: Path, *, enhance: bool, dpi: int = 150):
    """Drive the full ``BaseConverterWorker.run`` lifecycle synchronously
    (temp-file allocation + atomic ``os.replace``)."""
    settings = ConversionSettings(enhance_scanned_pdf=enhance, pdf_enhance_dpi=dpi)
    worker = PdfWorker(src, dst, settings=settings)
    worker.run()  # synchronous on the calling thread
    return worker


# ---- Fixtures --------------------------------------------------------------

@pytest.fixture
def scanned_pdf(tmp_path: Path) -> Path:
    p = tmp_path / "scanned.pdf"
    _synth_scanned_pdf(p, pages=2)
    return p


@pytest.fixture
def scanned_pdf_a4(tmp_path: Path) -> Path:
    """A4 page (595×842 pt). 826×1169 px at 100 dpi → 595×842 pt."""
    p = tmp_path / "scanned_a4.pdf"
    _synth_scanned_pdf(p, pages=2, px_size=(826, 1169), resolution=100.0)
    return p


# ---- Existing baseline -----------------------------------------------------

def test_off_toggle_is_byte_identical(scanned_pdf, tmp_path):
    out = tmp_path / "out.pdf"
    _run_worker_direct(scanned_pdf, out, enhance=False)
    assert out.exists()
    assert _sha256(out) == _sha256(scanned_pdf)


def test_on_toggle_brightens_background(scanned_pdf, tmp_path):
    out = tmp_path / "out.pdf"
    _run_worker_direct(scanned_pdf, out, enhance=True)
    assert out.exists()
    assert out.stat().st_size > 0

    src_img = pdfium.PdfDocument(str(scanned_pdf))[0].render(scale=1.0).to_pil().convert("L")
    out_img = pdfium.PdfDocument(str(out))[0].render(scale=1.0).to_pil().convert("L")

    # Sample a corner with no text — input ~239, output should be ~255.
    bg_src = sum(src_img.crop((10, 10, 50, 50)).tobytes())
    bg_out = sum(out_img.crop((10, 10, 50, 50)).tobytes())
    assert bg_out > bg_src, f"background should brighten ({bg_src} -> {bg_out})"


def test_on_toggle_darkens_text_regions(scanned_pdf, tmp_path):
    """Issue #4: contrast bump must measurably darken mid-gray text."""
    out = tmp_path / "out.pdf"
    _run_worker_direct(scanned_pdf, out, enhance=True)

    # Text is drawn between y=60..186, x=60..~400 in source pixel space.
    # Convert to render-coord region; both renders use scale=1.0 → same coords.
    src_img = pdfium.PdfDocument(str(scanned_pdf))[0].render(scale=1.0).to_pil().convert("L")
    out_img = pdfium.PdfDocument(str(out))[0].render(scale=1.0).to_pil().convert("L")

    region = (60, 60, 400, 200)
    src_bytes = src_img.crop(region).tobytes()
    out_bytes = out_img.crop(region).tobytes()

    # Find pixels that were "ink" in the source (anything noticeably below
    # paper). Compare the *minimum* luminance of those pixels — the text
    # strokes should be at least as dark afterwards (and on average darker).
    src_min = min(src_bytes)
    out_min = min(out_bytes)
    assert out_min <= src_min, (
        f"text strokes should not lighten ({src_min} -> {out_min})"
    )

    # Mean of darkest 10 % of pixels (the actual ink) should drop.
    src_sorted = sorted(src_bytes)[: max(1, len(src_bytes) // 10)]
    out_sorted = sorted(out_bytes)[: max(1, len(out_bytes) // 10)]
    src_ink_mean = sum(src_sorted) / len(src_sorted)
    out_ink_mean = sum(out_sorted) / len(out_sorted)
    assert out_ink_mean < src_ink_mean - 1, (
        f"text ink should darken ({src_ink_mean:.1f} -> {out_ink_mean:.1f})"
    )


def test_on_toggle_preserves_page_count_and_size(scanned_pdf, tmp_path):
    out = tmp_path / "out.pdf"
    _run_worker_direct(scanned_pdf, out, enhance=True)

    src_doc = pdfium.PdfDocument(str(scanned_pdf))
    out_doc = pdfium.PdfDocument(str(out))

    assert len(out_doc) == len(src_doc)

    for i in range(len(src_doc)):
        sw, sh = src_doc[i].get_size()
        ow, oh = out_doc[i].get_size()
        assert abs(sw - ow) < 1.0, f"page {i} width drifted {sw} -> {ow}"
        assert abs(sh - oh) < 1.0, f"page {i} height drifted {sh} -> {oh}"


def test_a4_page_size_preserved(scanned_pdf_a4, tmp_path):
    """Issue #4: page-size preservation must hold for non-Letter sizes."""
    out = tmp_path / "out_a4.pdf"
    _run_worker_direct(scanned_pdf_a4, out, enhance=True)

    src_doc = pdfium.PdfDocument(str(scanned_pdf_a4))
    out_doc = pdfium.PdfDocument(str(out))
    assert len(out_doc) == len(src_doc)

    # A4 is 595 × 842 pt — verify both source and output match it within 1 pt.
    for i in range(len(src_doc)):
        sw, sh = src_doc[i].get_size()
        ow, oh = out_doc[i].get_size()
        assert abs(sw - 595.0) < 1.0, f"src A4 width drifted ({sw})"
        assert abs(sh - 842.0) < 1.0, f"src A4 height drifted ({sh})"
        assert abs(sw - ow) < 1.0, f"page {i} width drifted {sw} -> {ow}"
        assert abs(sh - oh) < 1.0, f"page {i} height drifted {sh} -> {oh}"


def test_zero_page_pdf_raises(tmp_path):
    empty = tmp_path / "empty.pdf"
    empty.write_bytes(
        b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Count 0/Kids[]>>endobj\n"
        b"xref\n0 3\n0000000000 65535 f\n"
        b"0000000009 00000 n\n0000000055 00000 n\n"
        b"trailer<</Size 3/Root 1 0 R>>\nstartxref\n100\n%%EOF\n"
    )
    out = tmp_path / "out.pdf"
    with pytest.raises(RuntimeError):
        _run_worker_direct(empty, out, enhance=True)


def test_cancel_pre_loop_leaves_no_output(scanned_pdf, tmp_path):
    out = tmp_path / "out.pdf"
    settings = ConversionSettings(enhance_scanned_pdf=True, pdf_enhance_dpi=150)
    worker = PdfWorker(scanned_pdf, out, settings=settings)
    worker.output_path = out
    worker._cancel = True       # cancel before _convert ever runs the loop
    worker._convert()
    assert not out.exists()


def test_refuses_in_place_enhancement(scanned_pdf):
    with pytest.raises(RuntimeError, match="in place"):
        _enhance_scanned_pdf(scanned_pdf, scanned_pdf, dpi=150)


# ---- Lifecycle tests (Issue #3) -------------------------------------------

def test_lifecycle_finalises_via_temp_and_replace(scanned_pdf, tmp_path):
    """End-to-end through ``BaseConverterWorker.run()``: the worker must
    write to a sibling temp file and atomically ``os.replace`` it onto the
    final destination. Verifies no ``.cove-part-*`` artifacts remain."""
    out = tmp_path / "final.pdf"
    worker = _run_worker_lifecycle(scanned_pdf, out, enhance=True)

    # Final file present, populated, and the worker no longer owns a temp.
    assert out.exists()
    assert out.stat().st_size > 0
    assert worker._owned_temp_path is None
    assert worker.output_path == out

    # No ``.cove-part-*`` siblings left behind.
    leftovers = list(tmp_path.glob(".final.cove-part-*"))
    assert leftovers == [], f"stray temp artifacts: {leftovers}"

    # Page count preserved through the full lifecycle.
    src_doc = pdfium.PdfDocument(str(scanned_pdf))
    out_doc = pdfium.PdfDocument(str(out))
    assert len(out_doc) == len(src_doc)


def test_lifecycle_cancel_after_first_page_cleans_temp(scanned_pdf, tmp_path):
    """Issue #3: cancel after at least one rendered page must remove the
    partial temp output and leave no final file behind."""
    out = tmp_path / "cancelled.pdf"
    settings = ConversionSettings(enhance_scanned_pdf=True, pdf_enhance_dpi=150)
    worker = PdfWorker(scanned_pdf, out, settings=settings)

    # Flip _cancel after the first per-page progress emission (>5%, since
    # the pre-loop tick is exactly 5). Signals fire synchronously here
    # because ``run`` executes on the calling thread.
    triggered: list[int] = []

    def _on_progress(pct: int) -> None:
        if pct > 5 and not triggered:
            triggered.append(pct)
            worker._cancel = True
    worker.progress.connect(_on_progress)

    statuses: list[str] = []
    worker.status.connect(statuses.append)

    worker.run()

    # Cancellation must have been triggered after a real page render.
    assert triggered, "progress never advanced past pre-loop tick"
    assert "Cancelled" in statuses
    # Final output must NOT exist.
    assert not out.exists()
    # No leftover ``.cove-part-*`` siblings.
    leftovers = list(tmp_path.glob(".cancelled.cove-part-*"))
    assert leftovers == [], f"cancel left temp artifacts: {leftovers}"


# ---- Bounded-memory assembly (behavioural contract) -----------------------

def test_enhance_does_not_instantiate_pdfreader(scanned_pdf, tmp_path, monkeypatch):
    """Direct regression guard for the original memory bug.

    The previous implementation kept one ``pypdf.PdfReader`` per page in a
    list until ``writer.write()``; each reader internally pulls its
    single-page PDF into a ``BytesIO``, so memory grew with page count.
    The fix must not instantiate ``PdfReader`` at all during enhancement.
    """
    import pypdf

    instances: list[int] = []
    real_init = pypdf.PdfReader.__init__

    def _track(self, *args, **kwargs):
        instances.append(1)
        return real_init(self, *args, **kwargs)

    monkeypatch.setattr(pypdf.PdfReader, "__init__", _track)

    out = tmp_path / "out.pdf"
    _run_worker_direct(scanned_pdf, out, enhance=True)

    assert instances == [], (
        f"_enhance_scanned_pdf must not create any PdfReader objects "
        f"(got {len(instances)})"
    )


def test_enhance_appends_pages_one_at_a_time(scanned_pdf, tmp_path, monkeypatch):
    """Bounded-memory assembly contract.

    Pages must be written to ``dst`` incrementally. The first PDF save
    creates the file (``append=False``); every subsequent PDF save MUST
    pass ``append=True`` so PIL never holds a list of page bitmaps and
    only the in-flight page is resident.
    """
    real_save = Image.Image.save
    pdf_appends: list[bool] = []

    def _spy(self, fp, format=None, **kwargs):
        # Only count saves of the destination file, not fixture saves
        # to other temp paths.
        if format == "PDF" and Path(str(fp)).resolve() == out.resolve():
            pdf_appends.append(bool(kwargs.get("append", False)))
        return real_save(self, fp, format=format, **kwargs)

    out = tmp_path / "out.pdf"
    monkeypatch.setattr(Image.Image, "save", _spy)

    _run_worker_direct(scanned_pdf, out, enhance=True)

    src_pages = len(pdfium.PdfDocument(str(scanned_pdf)))
    assert len(pdf_appends) == src_pages, (
        f"expected one save per page ({src_pages}), got {pdf_appends}"
    )
    assert pdf_appends[0] is False, "first save must create the file (append=False)"
    for i, used_append in enumerate(pdf_appends[1:], start=1):
        assert used_append, f"page {i} save must use append=True (got {pdf_appends})"


def test_enhance_releases_each_pil_page_before_next(scanned_pdf, tmp_path, monkeypatch):
    """Bounded-memory contract — the PIL bitmap from page i-1 must be
    released before page i is rendered. At any single save call the only
    enhanced PIL image alive should be the one being written.
    """
    import weakref

    out = tmp_path / "out.pdf"
    real_save = Image.Image.save
    refs: list[weakref.ref] = []
    max_alive = [0]

    def _checkpoint(self, fp, format=None, **kwargs):
        if format == "PDF" and Path(str(fp)).resolve() == out.resolve():
            refs.append(weakref.ref(self))
            alive = sum(1 for r in refs if r() is not None)
            max_alive[0] = max(max_alive[0], alive)
        return real_save(self, fp, format=format, **kwargs)

    monkeypatch.setattr(Image.Image, "save", _checkpoint)

    _run_worker_direct(scanned_pdf, out, enhance=True)

    assert max_alive[0] <= 1, (
        f"expected at most 1 enhanced PIL image alive at any save call, "
        f"saw {max_alive[0]} — earlier page bitmaps are being retained"
    )


def test_lifecycle_failure_cleans_temp(scanned_pdf, tmp_path, monkeypatch):
    """If PIL fails mid-assembly the worker must clean up the partial
    ``.cove-part-*`` temp file and not leave a final output behind.
    Replaces the previous PdfReader-failure injection (PdfReader is no
    longer used by the enhancement path).
    """
    out = tmp_path / "fail.pdf"

    # Patch is installed AFTER the scanned_pdf fixture has already saved
    # its synthetic PDF, so any PDF save observed below is the enhancement
    # path writing to the worker-owned ``.cove-part-*`` temp file.
    real_save = Image.Image.save
    call_count = [0]

    def _bad_save(self, fp, format=None, **kwargs):
        if format == "PDF":
            call_count[0] += 1
            raise RuntimeError("synthetic PIL save failure")
        return real_save(self, fp, format=format, **kwargs)

    monkeypatch.setattr(Image.Image, "save", _bad_save)

    settings = ConversionSettings(enhance_scanned_pdf=True, pdf_enhance_dpi=150)
    worker = PdfWorker(scanned_pdf, out, settings=settings)
    statuses: list[str] = []
    worker.status.connect(statuses.append)
    worker.run()

    assert call_count[0] >= 1, "expected at least one save attempt before failure"
    assert any(s.startswith("Failed:") for s in statuses), statuses
    assert not out.exists(), "no final output should exist after failure"
    leftovers = list(tmp_path.glob(".fail.cove-part-*"))
    assert leftovers == [], f"failure left temp artifacts: {leftovers}"


def test_source_pdf_unchanged_after_enhance(scanned_pdf, tmp_path):
    """Belt-and-braces: the disk-spool refactor must not mutate the source."""
    before = _sha256(scanned_pdf)
    before_mtime = scanned_pdf.stat().st_mtime_ns
    out = tmp_path / "out.pdf"
    _run_worker_direct(scanned_pdf, out, enhance=True)
    assert _sha256(scanned_pdf) == before
    assert scanned_pdf.stat().st_mtime_ns == before_mtime

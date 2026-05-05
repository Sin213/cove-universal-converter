"""Tests for the smart-PDF (JavaScript) flattening path.

Covers:
  * ``has_pdf_javascript`` detection on raw bytes (positive and negative,
    streaming over the whole file with chunk-boundary overlap).
  * ``flatten_pdf`` rasterises every page via PDFium and rebuilds a
    valid multi-page PDF that preserves page count and page size.
  * Output validation: bad / partial output is removed, never published.
  * ``PdfWorker._convert`` routes JS PDFs through ``flatten_pdf`` only
    for PDF → PDF (rasterising destroys the text layer, so PDF → txt /
    md / html / docx / odt / rtf / epub keeps using ``pypdf``).
  * Plain PDFs skip the flatten path entirely.
  * ``FileRow.resolve_output`` does not collide with the source for
    the new ``.pdf`` default target.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pypdfium2 as pdfium
import pytest
from PIL import Image, ImageDraw

from cove_converter.engines import pdf as pdf_engine
from cove_converter.engines import pdf_flatten
from cove_converter.engines.pdf import PdfWorker
from cove_converter.engines.pdf_flatten import flatten_pdf, has_pdf_javascript
from cove_converter.settings import ConversionSettings
from cove_converter.ui.file_row import FileRow


# ---- Fixture builders ------------------------------------------------------

def _synth_plain_pdf(
    path: Path,
    *,
    pages: int = 1,
    px_size: tuple[int, int] = (400, 500),
    resolution: float = 72.0,
) -> None:
    """Real, valid PDF written by PIL — no JavaScript markers."""
    imgs = []
    for i in range(pages):
        img = Image.new("RGB", px_size, color=(255, 255, 255))
        ImageDraw.Draw(img).text((40, 40), f"plain page {i + 1}", fill=(0, 0, 0))
        imgs.append(img)
    imgs[0].save(
        path, "PDF", resolution=resolution,
        save_all=True, append_images=imgs[1:],
    )


def _synth_js_pdf(path: Path, *, pages: int = 1, **kw) -> None:
    """Valid PDF with an injected ``/JavaScript`` action so detection trips.

    Built on top of a PIL-rendered base PDF — the bytes between ``%PDF`` and
    ``%%EOF`` are a real PDF, with the JS marker appended in a comment block.
    ``has_pdf_javascript`` is a literal byte scan, so a comment is enough.
    """
    _synth_plain_pdf(path, pages=pages, **kw)
    with path.open("ab") as f:
        f.write(b"\n% /JavaScript /JS injected for routing test\n")


# ---- Detection -------------------------------------------------------------

def test_detect_plain_pdf_returns_false(tmp_path):
    p = tmp_path / "plain.pdf"
    _synth_plain_pdf(p)
    assert has_pdf_javascript(p) is False


def test_detect_js_marker_returns_true(tmp_path):
    p = tmp_path / "smart.pdf"
    _synth_js_pdf(p)
    assert has_pdf_javascript(p) is True


def test_detect_short_js_token_returns_true(tmp_path):
    p = tmp_path / "shortjs.pdf"
    _synth_plain_pdf(p)
    with p.open("ab") as f:
        f.write(b"\n% /JS appended\n")
    assert has_pdf_javascript(p) is True


def test_detect_missing_file_returns_false(tmp_path):
    assert has_pdf_javascript(tmp_path / "nope.pdf") is False


def test_detect_empty_file_returns_false(tmp_path):
    p = tmp_path / "empty.pdf"
    p.write_bytes(b"")
    assert has_pdf_javascript(p) is False


def test_detect_marker_in_central_region(tmp_path):
    """PDF object ordering is not guaranteed; markers can live in the
    middle of a large PDF. Streaming scan must catch them."""
    p = tmp_path / "central.pdf"
    marker = b"/JavaScript"
    size = 4 * 1024 * 1024
    pos = size // 2
    blob = bytearray(b"a" * pos)
    blob += marker
    blob += b"b" * (size - pos - len(marker))
    p.write_bytes(bytes(blob))
    assert has_pdf_javascript(p) is True


def test_detect_marker_straddling_chunk_boundary_mid_file(tmp_path):
    """Marker straddling a 1 MiB chunk boundary must still be caught
    via the carry-over between successive streaming chunks."""
    p = tmp_path / "mid_straddle.pdf"
    CHUNK = 1_048_576
    marker = b"/JavaScript"
    size = 4 * CHUNK + 12345
    pos = 2 * CHUNK - 5
    blob = bytearray(b"a" * pos)
    blob += marker
    blob += b"b" * (size - pos - len(marker))
    p.write_bytes(bytes(blob))
    assert has_pdf_javascript(p) is True


# ---- flatten_pdf direct (uses pypdfium2 under the hood) --------------------

def test_flatten_refuses_in_place(tmp_path):
    p = tmp_path / "x.pdf"
    _synth_plain_pdf(p)
    with pytest.raises(RuntimeError, match="in place"):
        flatten_pdf(p, p)


def test_flatten_preserves_page_count(tmp_path):
    """Acceptance #1: output page count must match input page count.
    The MPMB regression was: input 6 pages → output 1 page."""
    src = tmp_path / "in.pdf"
    _synth_js_pdf(src, pages=6)
    dst = tmp_path / "out.pdf"

    flatten_pdf(src, dst)

    assert dst.exists()
    out_doc = pdfium.PdfDocument(str(dst))
    try:
        assert len(out_doc) == 6
    finally:
        out_doc.close()


def test_flatten_preserves_a4_page_size(tmp_path):
    """Acceptance #2: A4 page (595×842 pt) input must produce an
    A4-sized output, not a Letter-size browser printout."""
    src = tmp_path / "a4.pdf"
    # 826×1169 px at 100 DPI → 595×842 pt (A4).
    _synth_js_pdf(src, pages=2, px_size=(826, 1169), resolution=100.0)
    dst = tmp_path / "out.pdf"

    flatten_pdf(src, dst)

    src_doc = pdfium.PdfDocument(str(src))
    out_doc = pdfium.PdfDocument(str(dst))
    try:
        assert len(out_doc) == len(src_doc)
        for i in range(len(src_doc)):
            sw, sh = src_doc[i].get_size()
            ow, oh = out_doc[i].get_size()
            assert abs(sw - 595.0) < 1.0, f"src A4 width drifted ({sw})"
            assert abs(sh - 842.0) < 1.0, f"src A4 height drifted ({sh})"
            assert abs(sw - ow) < 1.0, f"page {i} width drifted {sw} -> {ow}"
            assert abs(sh - oh) < 1.0, f"page {i} height drifted {sh} -> {oh}"
    finally:
        src_doc.close()
        out_doc.close()


def test_flatten_output_is_not_blank(tmp_path):
    """Acceptance #3: the output should visually contain content. The
    MPMB regression mode produced a uniform dark page. For a synthetic
    page with drawn text, the full rendered bitmap must show enough
    distinct luminance values to rule out a flat-fill blank page."""
    src = tmp_path / "in.pdf"
    _synth_js_pdf(src, pages=1)
    dst = tmp_path / "out.pdf"

    flatten_pdf(src, dst)

    out_doc = pdfium.PdfDocument(str(dst))
    try:
        bitmap = out_doc[0].render(scale=1.0)
        try:
            pil = bitmap.to_pil()
        finally:
            bitmap.close()
    finally:
        out_doc.close()
    if pil.mode != "L":
        pil = pil.convert("L")
    # Whole-page distinct-value count. Drawn text + antialiasing yields
    # well over 10 distinct grey levels; a uniformly-coloured page yields
    # 1 (or a handful from JPEG noise).
    distinct = len(set(pil.tobytes()))
    assert distinct > 10, (
        f"output page has only {distinct} distinct grey levels — "
        f"likely blank/dark"
    )


def test_flatten_zero_page_pdf_raises(tmp_path):
    """Acceptance #6: structurally-broken / empty input must raise a
    real ``RuntimeError`` and never produce an output file. The exact
    error message is implementation-dependent (PDFium may reject the
    file as unparseable rather than reporting zero pages); both wordings
    satisfy the contract."""
    empty = tmp_path / "empty.pdf"
    empty.write_bytes(
        b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Count 0/Kids[]>>endobj\n"
        b"xref\n0 3\n0000000000 65535 f\n"
        b"0000000009 00000 n\n0000000055 00000 n\n"
        b"trailer<</Size 3/Root 1 0 R>>\nstartxref\n100\n%%EOF\n"
    )
    dst = tmp_path / "out.pdf"
    with pytest.raises(RuntimeError):
        flatten_pdf(empty, dst)
    assert not dst.exists(), "no output file should remain after failure"


def test_flatten_invalid_input_raises_clear_error(tmp_path):
    """Acceptance #6: garbage input must surface a real exception."""
    junk = tmp_path / "junk.pdf"
    junk.write_bytes(b"this is not a pdf")
    dst = tmp_path / "out.pdf"
    with pytest.raises(RuntimeError):
        flatten_pdf(junk, dst)
    assert not dst.exists()


def test_flatten_preserves_color(tmp_path):
    """Acceptance: the rasterised output must keep colour. The MPMB
    follow-up regression was that the output looked stripped/plain —
    if rendering accidentally goes grayscale the chromatic-pixel count
    drops to ~0 here.
    """
    src = tmp_path / "in.pdf"
    # PDF page with a saturated red bar — distinct from any grey.
    img = Image.new("RGB", (400, 500), (255, 250, 240))
    ImageDraw.Draw(img).rectangle(
        [(20, 20), (380, 60)], fill=(200, 30, 30),
    )
    img.save(src, "PDF", resolution=72.0)
    with src.open("ab") as f:
        f.write(b"\n% /JavaScript injected\n")

    dst = tmp_path / "out.pdf"
    flatten_pdf(src, dst)

    out_doc = pdfium.PdfDocument(str(dst))
    try:
        bitmap = out_doc[0].render(scale=0.5)
        try:
            pil = bitmap.to_pil()
        finally:
            bitmap.close()
    finally:
        out_doc.close()

    if pil.mode != "RGB":
        pil = pil.convert("RGB")

    chromatic = 0
    for r, g, b in pil.getdata():
        if r != g or g != b:
            chromatic += 1
            if chromatic > 50:
                break
    assert chromatic > 50, (
        "flatten output is essentially grayscale — colour was lost "
        "between PDFium render and PDF assembly"
    )


def test_flatten_captures_init_forms_warnings(tmp_path, monkeypatch, caplog):
    """Acceptance: pypdfium2 emits XFA loader failures via
    ``warnings.warn`` (not raised exceptions). The flatten code must
    use ``catch_warnings(record=True)`` to capture them and route
    through the dedicated logger at INFO. ``except Warning`` alone
    only matches warnings raised as errors, which is not the default.
    """
    src = tmp_path / "in.pdf"
    _synth_js_pdf(src, pages=1)
    dst = tmp_path / "out.pdf"

    import warnings as _w

    real_init = pdfium.PdfDocument.init_forms

    def _init_with_warning(self, *a, **kw):
        _w.warn("synthetic XFA loader failure", UserWarning)
        return real_init(self, *a, **kw)

    monkeypatch.setattr(pdfium.PdfDocument, "init_forms", _init_with_warning)

    caplog.set_level("INFO", logger="cove_converter.pdf_flatten")
    flatten_pdf(src, dst)  # warning is non-fatal

    msgs = " | ".join(rec.getMessage() for rec in caplog.records)
    assert "form init warning" in msgs, (
        f"warnings.warn output from init_forms must be captured and "
        f"logged by the dedicated pdf_flatten logger; got: {msgs!r}"
    )
    assert "synthetic XFA loader failure" in msgs


def test_flatten_initializes_form_environment_before_rendering(tmp_path, monkeypatch):
    """Acceptance: form widget appearance streams are only drawn if
    PDFium's form environment was bootstrapped via ``init_forms()``
    BEFORE any page handle is taken. Without this, filled AcroForm
    fields, decorative form-layer graphics, and widget appearances
    silently disappear from the rendered output — which is what
    produced the "stripped/plain" MPMB output the user reported.
    """
    src = tmp_path / "in.pdf"
    _synth_js_pdf(src, pages=2)
    dst = tmp_path / "out.pdf"

    real_init = pdfium.PdfDocument.init_forms
    real_getitem = pdfium.PdfDocument.__getitem__

    init_calls: list[int] = []
    getitem_calls: list[int] = []

    def _track_init(self, *a, **kw):
        init_calls.append(len(getitem_calls))  # how many pages had been taken
        return real_init(self, *a, **kw)

    def _track_getitem(self, idx):
        getitem_calls.append(idx)
        return real_getitem(self, idx)

    monkeypatch.setattr(pdfium.PdfDocument, "init_forms", _track_init)
    monkeypatch.setattr(pdfium.PdfDocument, "__getitem__", _track_getitem)

    flatten_pdf(src, dst)

    assert init_calls, "init_forms() must be called during flatten"
    assert init_calls[0] == 0, (
        "init_forms() must be called BEFORE any page handles are taken "
        "(pypdfium2 contract); found page handles already taken="
        f"{init_calls[0]}"
    )
    assert getitem_calls, "expected page rendering to take place"


def test_flatten_progress_emitted(tmp_path):
    src = tmp_path / "in.pdf"
    _synth_js_pdf(src, pages=3)
    dst = tmp_path / "out.pdf"

    seen: list[int] = []
    flatten_pdf(src, dst, progress=seen.append)
    assert seen, "progress should fire at least once"
    assert max(seen) >= 90, f"progress must reach near-completion: {seen}"


def test_flatten_cancelled_removes_partial_output(tmp_path):
    """If cancelled mid-flight, the partial PDF must not survive."""
    src = tmp_path / "in.pdf"
    _synth_js_pdf(src, pages=4)
    dst = tmp_path / "out.pdf"

    state = {"calls": 0}

    def _cancel():
        state["calls"] += 1
        return state["calls"] > 1  # cancel after first page renders

    flatten_pdf(src, dst, cancelled=_cancel)
    assert not dst.exists(), "partial output must be removed on cancel"


def test_flatten_cancelled_after_assembly_removes_output(tmp_path):
    """Late-cancellation path: cancel becomes true AFTER ``save_all`` has
    already written ``dst`` but BEFORE the validation check runs. Without
    the post-assembly unlink, a complete-but-unwanted PDF is left on
    disk; the worker would then publish it as if successful."""
    src = tmp_path / "in.pdf"
    _synth_js_pdf(src, pages=2)
    dst = tmp_path / "out.pdf"

    # Flip ``cancel`` only at the very last check (after ``cancel`` has
    # already been queried during the render loop and post-render
    # checkpoint). flatten_pdf calls ``cancelled`` once per page in
    # the render loop, once after the ``with tempdir`` block, and once
    # again at the post-assembly checkpoint — flip on the LAST call.
    flips = {"calls": 0}

    def _cancel():
        flips["calls"] += 1
        # Pages=2 → 2 calls in render loop + 1 post-render +
        # 1 post-assembly = 4. Cancel exactly on the 4th call.
        return flips["calls"] >= 4

    flatten_pdf(src, dst, cancelled=_cancel)

    assert flips["calls"] >= 4, (
        f"expected at least 4 cancellation checks, got {flips['calls']}"
    )
    assert not dst.exists(), (
        "post-assembly cancellation must unlink the just-written dst"
    )


# ---- Output validation ----------------------------------------------------

def test_flatten_output_page_count_validation(tmp_path, monkeypatch):
    """If the assembled PDF ends up with a different page count than
    the input (renderer bug, save_all dropping ``append_images``,
    truncated write), the post-validation must trip and delete the
    bad output. This is the regression guard for the MPMB case where
    Chromium produced 1 page from a 6-page input."""
    src = tmp_path / "in.pdf"
    _synth_js_pdf(src, pages=4)
    dst = tmp_path / "out.pdf"

    real_save = Image.Image.save

    def _drop_append_images(self, fp, format=None, **kwargs):
        # Strip ``save_all`` / ``append_images`` so PIL writes only the
        # first page, simulating an assembler that dropped the rest.
        if format == "PDF":
            kwargs.pop("save_all", None)
            kwargs.pop("append_images", None)
        return real_save(self, fp, format=format, **kwargs)

    monkeypatch.setattr(Image.Image, "save", _drop_append_images)

    with pytest.raises(RuntimeError, match="page count mismatch"):
        flatten_pdf(src, dst)
    assert not dst.exists(), "bad output must be removed after validation fails"


def test_flatten_post_render_failures_log_through_dedicated_logger(tmp_path, monkeypatch, caplog):
    """Acceptance: every flatten failure path — including ones that
    fire AFTER the document opens (assemble, validate, page-count
    mismatch) — must emit a ``cove_converter.pdf_flatten`` ERROR
    record. Without the per-site log lines, a packaged build only
    sees the worker traceback and loses the renderer-specific cause.
    """
    src = tmp_path / "in.pdf"
    _synth_js_pdf(src, pages=4)
    dst = tmp_path / "out.pdf"

    real_save = Image.Image.save

    def _drop_append_images(self, fp, format=None, **kwargs):
        if format == "PDF":
            kwargs.pop("save_all", None)
            kwargs.pop("append_images", None)
        return real_save(self, fp, format=format, **kwargs)

    monkeypatch.setattr(Image.Image, "save", _drop_append_images)

    caplog.set_level("ERROR", logger="cove_converter.pdf_flatten")
    with pytest.raises(RuntimeError, match="page count mismatch"):
        flatten_pdf(src, dst)

    msgs = " | ".join(rec.getMessage() for rec in caplog.records)
    assert "page count mismatch" in msgs, (
        "post-render validation failure must log through "
        f"cove_converter.pdf_flatten; got: {msgs!r}"
    )


def test_flatten_output_size_floor_validation(tmp_path, monkeypatch):
    """A renderer that produces an absurdly tiny PDF (the MPMB regression
    mode: 1.1 KB for 6 pages) must trip the size floor and remove the
    bad output before the worker can publish it."""
    src = tmp_path / "in.pdf"
    _synth_js_pdf(src, pages=4)
    dst = tmp_path / "out.pdf"

    real_save = Image.Image.save

    def _replace_pdf_save_with_tiny(self, fp, format=None, **kwargs):
        if format == "PDF":
            # Write a real, parseable, but absurdly tiny PDF — same shape
            # as the Chromium-blank regression output. Page count happens
            # to match (both 0), so the size floor must be the catcher.
            Path(str(fp)).write_bytes(
                b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
                b"2 0 obj<</Type/Pages/Count 0/Kids[]>>endobj\n"
                b"xref\n0 3\n0000000000 65535 f\n"
                b"0000000009 00000 n\n0000000055 00000 n\n"
                b"trailer<</Size 3/Root 1 0 R>>\nstartxref\n100\n%%EOF\n"
            )
            return
        return real_save(self, fp, format=format, **kwargs)

    monkeypatch.setattr(Image.Image, "save", _replace_pdf_save_with_tiny)

    with pytest.raises(RuntimeError):
        flatten_pdf(src, dst)
    assert not dst.exists()


# ---- Routing through PdfWorker --------------------------------------------

def _drive_convert(src: Path, dst: Path) -> None:
    settings = ConversionSettings(enhance_scanned_pdf=False)
    worker = PdfWorker(src, dst, settings=settings)
    worker.output_path = dst
    worker._convert()


def test_plain_pdf_skips_flatten(tmp_path, monkeypatch):
    src = tmp_path / "plain.pdf"
    _synth_plain_pdf(src)
    dst = tmp_path / "out.pdf"

    calls: list[tuple[Path, Path]] = []

    def _spy(s, d, *, progress=None, cancelled=None):
        calls.append((s, d))

    monkeypatch.setattr(pdf_engine, "flatten_pdf", _spy)
    _drive_convert(src, dst)
    assert calls == [], "plain PDF must not be flattened"
    assert dst.exists() and dst.stat().st_size > 0


def test_js_pdf_to_pdf_is_flattened(tmp_path, monkeypatch):
    """JS PDF → PDF goes through flatten_pdf."""
    src = tmp_path / "smart.pdf"
    _synth_js_pdf(src)
    dst = tmp_path / "out.pdf"

    calls: list[tuple[Path, Path]] = []

    def _spy(s, d, *, progress=None, cancelled=None):
        calls.append((Path(s), Path(d)))
        Path(d).write_bytes(b"%PDF-1.4\n% flatten sentinel\n%%EOF\n")

    monkeypatch.setattr(pdf_engine, "flatten_pdf", _spy)
    _drive_convert(src, dst)

    assert len(calls) == 1
    flat_src, flat_dst = calls[0]
    assert flat_src == src
    # New design writes flatten output directly to the worker's output path.
    assert flat_dst == dst


def test_js_pdf_to_text_does_not_flatten(tmp_path, monkeypatch):
    """PDF → txt must keep using pypdf (which can read stored AcroForm
    field values directly). Rasterising would destroy the text layer
    and produce an empty .txt."""
    src = tmp_path / "smart.pdf"
    _synth_js_pdf(src)
    dst = tmp_path / "out.txt"

    flat_calls: list = []

    def _spy(*a, **kw):
        flat_calls.append(a)

    monkeypatch.setattr(pdf_engine, "flatten_pdf", _spy)
    _drive_convert(src, dst)

    assert flat_calls == [], (
        "PDF → text path must NOT route through flatten_pdf"
    )
    assert dst.exists()


def test_flatten_failure_in_worker_propagates(tmp_path, monkeypatch):
    src = tmp_path / "smart.pdf"
    _synth_js_pdf(src)
    dst = tmp_path / "out.pdf"

    def _boom(s, d, *, progress=None, cancelled=None):
        raise RuntimeError("synthetic flatten failure")

    monkeypatch.setattr(pdf_engine, "flatten_pdf", _boom)

    settings = ConversionSettings(enhance_scanned_pdf=False)
    worker = PdfWorker(src, dst, settings=settings)
    statuses: list[str] = []
    worker.status.connect(statuses.append)
    worker.run()

    assert any("synthetic flatten failure" in s for s in statuses)
    assert not dst.exists()


# ---- File-row default-output behaviour ------------------------------------

def test_pdf_to_pdf_default_output_does_not_overwrite_source(tmp_path):
    src = tmp_path / "MPMB.pdf"
    _synth_plain_pdf(src)
    row = FileRow(path=src, target_ext=".pdf")
    out = row.resolve_output(dest_dir=None)
    assert out.resolve() != src.resolve()
    assert out.suffix == ".pdf"
    assert out.parent == src.parent


def test_pdf_to_pdf_with_dest_dir_keeps_simple_name(tmp_path):
    src_dir = tmp_path / "in"
    src_dir.mkdir()
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    src = src_dir / "doc.pdf"
    _synth_plain_pdf(src)
    row = FileRow(path=src, target_ext=".pdf")
    out = row.resolve_output(dest_dir=out_dir)
    assert out == out_dir / "doc.pdf"


def test_pdf_to_other_extension_is_unchanged(tmp_path):
    src = tmp_path / "doc.pdf"
    _synth_plain_pdf(src)
    row = FileRow(path=src, target_ext=".txt")
    out = row.resolve_output(dest_dir=None)
    assert out == tmp_path / "doc.txt"

"""Flatten "smart" JavaScript-driven PDFs into static rasterised PDFs.

Some PDFs contain ``/JavaScript`` or ``/JS`` action dictionaries that fill
forms or render content at view time. ``pypdf`` and the rest of the existing
PDF pipeline don't execute that JavaScript, so the visible filled-out content
can look wrong or missing. The goal of this module is to render every page
of the input PDF into static page content and rebuild a new PDF whose pages
are baked images — no JavaScript, no form fields, just bitmaps.

Approach: ``pypdfium2`` is already a project dependency and is the right tool
here. ``PdfDocument(...)`` parses the file, ``page.render(scale=...)`` produces
a real bitmap of the page (the same renderer Chromium uses internally), and
PIL's incremental PDF writer assembles the rendered bitmaps into a multi-page
PDF — one page resident at a time, so memory stays bounded regardless of
input size or page count.

What this is NOT: a Chromium ``--print-to-pdf`` pipe. The previous Chromium
approach captured the browser's PDF *viewer* render rather than the PDF's
own page content; the result was a single Letter-size HeadlessChrome page
with the wrong content. PDFium-direct rendering avoids that entirely.

Honesty about scope: PDFium does not execute Acrobat-specific JavaScript at
render time. Field values that are *stored* in the PDF (typed by a user and
saved) render normally because they're real PDF object data. Field values
that would only be computed by Acrobat-side scripts at view time will NOT
appear in the flattened output. That's the deliberate trade-off — see
acceptance criterion #5 in the handoff.

Failure is loud by design. If the renderer can't open the PDF, if any page
fails to render, or if the assembled output fails its post-validation
checks (page count mismatch, suspiciously tiny size), we raise
``RuntimeError`` and remove the bad output. The caller never sees a
"successful" blank PDF.
"""
from __future__ import annotations

import logging
import tempfile
import threading
import warnings
from pathlib import Path
from typing import Callable

_log = logging.getLogger("cove_converter.pdf_flatten")


# PDFium's native API is not thread-safe. Concurrent ``PdfDocument`` /
# ``init_forms`` / ``page.render`` calls from worker threads (the batch path
# runs up to ``settings.max_concurrent`` workers in parallel) race on
# PDFium's process-global state, which surfaces as ``Failed to load page``
# / ``Data format error`` from pypdfium2 and — worse — occasional native
# crashes that bypass Python's exception handling and take the whole
# process down (the leftover empty ``.cove-part-*.pdf`` files we saw in
# the wild are the smoking gun: ``BaseConverterWorker._cleanup_temp``
# never ran). Serialise the entire flatten so concurrent batch workers
# can't trip the race. Single-file conversions hit this lock once and
# pay no contention.
_PDFIUM_LOCK = threading.Lock()


# Substring markers that the user's spec asks us to detect. ``/JavaScript``
# names the action type; ``/JS`` is the key whose value holds the script.
_JS_MARKERS: tuple[bytes, ...] = (b"/JavaScript", b"/JS")

# Bounded-memory streaming scan. PDF object ordering is not guaranteed —
# JavaScript action dictionaries can live in indirect objects or compressed
# object streams anywhere in the file, so a head+tail-only scan can miss
# them on large PDFs. We read the whole file but only ever hold one chunk
# (plus a tiny carry-over) in memory at a time.
_DETECT_CHUNK_BYTES = 1_048_576       # 1 MiB
# Carry-over between chunks so a marker that straddles a chunk boundary
# still appears whole in the next iteration's scan window. ``len(marker)
# - 1`` is the minimum guaranteeing that — anything shorter and the marker
# can split across the boundary without ever appearing whole in any buffer.
_BOUNDARY_OVERLAP = max(len(m) for m in _JS_MARKERS) - 1


# ---- Render parameters -----------------------------------------------------

# Render DPI for each page. 250 DPI keeps fine decorative artwork
# (D&D-style coloured borders, badge icons, hairline rules) crisp
# without blowing up output size. The same value is embedded in the
# output PDF's resolution field so the page size in points stays
# equal to the source page size.
_RENDER_DPI = 250

# JPEG quality for the rendered page bitmaps inside the output PDF.
# 92 preserves coloured graphics with no perceptible artefacts at
# normal viewing zoom while keeping the output an order of magnitude
# smaller than lossless PNG.
_JPEG_QUALITY = 92

# Per-page minimum size used by the post-flatten sanity check. The
# blank/dark Chromium output regression was ~1.1 KB for a single page;
# real rasterised pages are reliably tens of KB minimum. Multiplying by
# page count gives a floor that scales with the document and is loose
# enough that a small text-only page can never trip it.
_MIN_BYTES_PER_PAGE = 4 * 1024


# ---- Detection -------------------------------------------------------------

def has_pdf_javascript(path: Path) -> bool:
    """Return True if ``path`` looks like a JavaScript-bearing PDF.

    Streams the file in ``_DETECT_CHUNK_BYTES`` chunks, carrying
    ``_BOUNDARY_OVERLAP`` bytes between chunks so a marker straddling a
    chunk boundary is still seen whole in the next iteration. Bounded
    memory: at most one chunk plus the small carry-over is resident at
    any time, regardless of file size. Whole-file coverage is needed
    because PDF object ordering is not guaranteed — JavaScript action
    dictionaries can sit in indirect objects or compressed object
    streams anywhere in the file, not just the catalog at the head/tail.
    """
    try:
        size = path.stat().st_size
    except OSError:
        return False
    if size <= 0:
        return False

    try:
        with path.open("rb") as f:
            carry = b""
            while True:
                chunk = f.read(_DETECT_CHUNK_BYTES)
                if not chunk:
                    break
                window = carry + chunk
                for marker in _JS_MARKERS:
                    if marker in window:
                        return True
                # Keep the trailing ``_BOUNDARY_OVERLAP`` bytes so a marker
                # split across this chunk's end and the next chunk's start
                # is fully present in the next iteration's window.
                if _BOUNDARY_OVERLAP and len(window) > _BOUNDARY_OVERLAP:
                    carry = window[-_BOUNDARY_OVERLAP:]
                else:
                    carry = window
    except OSError:
        return False

    return False


# ---- Flatten ---------------------------------------------------------------

def flatten_pdf(
    src: Path,
    dst: Path,
    *,
    progress: Callable[[int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> None:
    """Rasterise every page of ``src`` and write a static multi-page PDF to ``dst``.

    Uses PDFium (via ``pypdfium2``) to render each page at ``_RENDER_DPI``,
    then PIL's incremental PDF writer to append the rendered bitmaps to
    ``dst`` one at a time. The page-by-page pattern keeps resident memory
    bounded to a single full-resolution bitmap regardless of page count.

    Page dimensions are preserved: ``page.render(scale=DPI/72)`` produces
    pixels = points * DPI / 72, and PIL's ``resolution=DPI`` makes the
    output PDF declare the same DPI, so output points = input points.

    Raises ``RuntimeError`` on any failure (encrypted source, render error,
    output validation mismatch). On failure, any partial output is removed
    so the caller never inherits a "successful" bad file.
    """
    if src.resolve() == dst.resolve():
        raise RuntimeError("Refusing to flatten PDF in place")

    # PDFium is not thread-safe. Serialise the body so concurrent batch
    # workers can't race PDFium's global state (see ``_PDFIUM_LOCK``).
    with _PDFIUM_LOCK:
        _flatten_pdf_locked(src, dst, progress=progress, cancelled=cancelled)


def _flatten_pdf_locked(
    src: Path,
    dst: Path,
    *,
    progress: Callable[[int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> None:
    # Imports are local because pypdfium2 / PIL are heavy and the module is
    # also imported for the cheap ``has_pdf_javascript`` detection path.
    import pypdfium2 as pdfium
    from PIL import Image

    _log.info("flatten: src=%s dst=%s dpi=%d", src, dst, _RENDER_DPI)

    try:
        pdf = pdfium.PdfDocument(str(src))
    except pdfium.PdfiumError as exc:
        msg = str(exc).lower()
        if "password" in msg or "encrypted" in msg:
            _log.error("flatten: PDF is password-protected: %s", exc)
            raise RuntimeError(
                "PDF is password-protected — flatten cannot run on an "
                "encrypted PDF without the password."
            ) from exc
        _log.error("flatten: could not open PDF: %s", exc)
        raise RuntimeError(f"Could not open PDF: {exc}") from exc

    # Bootstrap the form environment BEFORE getting the page count or any
    # page handles. pypdfium2's contract: "If form rendering is desired,
    # this method shall be called right after document construction,
    # before getting document length or page handles." Without this,
    # ``page.render(may_draw_forms=True)`` silently skips form widget
    # rendering — which is what makes filled-in AcroForm field values,
    # form-widget appearance streams, and decorative form-layer graphics
    # disappear from the output. Also handles XFA forms when PDFium has
    # XFA support compiled in. pypdfium2 reports XFA loader failures via
    # ``warnings.warn`` (NOT raised exceptions), so they have to be
    # captured through ``catch_warnings(record=True)`` rather than
    # ``except Warning`` (which only catches warnings raised as errors).
    # Capture and route them through the dedicated logger at INFO — the
    # form environment is still usable for AcroForm even when XFA fails.
    with warnings.catch_warnings(record=True) as _captured_warnings:
        warnings.simplefilter("always")
        try:
            pdf.init_forms()
        except pdfium.PdfiumError as exc:
            # Real failure (rare) — surface it.
            pdf.close()
            _log.error(
                "flatten: could not initialize PDF form environment: %s", exc,
            )
            raise RuntimeError(
                f"Could not initialize PDF form environment: {exc}"
            ) from exc
    for _w in _captured_warnings:
        _log.info(
            "flatten: form init warning (%s): %s",
            _w.category.__name__, _w.message,
        )

    try:
        n = len(pdf)
    except Exception as exc:
        pdf.close()
        _log.error("flatten: could not read page count: %s", exc)
        raise RuntimeError(f"Could not read PDF page count: {exc}") from exc

    if n == 0:
        pdf.close()
        _log.error("flatten: PDF contains no pages: %s", src)
        raise RuntimeError("PDF contains no pages")

    if progress:
        progress(5)

    # Two-phase assembly: render each page to a JPEG on disk (only one
    # full-resolution bitmap is alive at any moment), then PIL builds
    # the output PDF in a single ``save_all`` call. PIL's incremental
    # append-mode PDF writer falls over past ~4 pages with a "trailer
    # loop found" parser error, so the per-page-append idiom we use in
    # ``_enhance_scanned_pdf`` is not safe here. The tempdir is unlinked
    # automatically when the ``with`` block exits.
    scale = _RENDER_DPI / 72.0
    cancelled_early = False
    rendered_any = False
    with tempfile.TemporaryDirectory(prefix="cove-flatten-pages-") as tmpdir:
        page_files: list[Path] = []
        try:
            for i in range(n):
                if cancelled and cancelled():
                    cancelled_early = True
                    return

                try:
                    page = pdf[i]
                except Exception as exc:
                    _log.error(
                        "flatten: could not load page %d/%d: %s", i + 1, n, exc,
                    )
                    raise RuntimeError(
                        f"Could not load page {i + 1}/{n}: {exc}"
                    ) from exc

                try:
                    bitmap = page.render(scale=scale)
                    try:
                        pil = bitmap.to_pil()
                    finally:
                        bitmap.close()
                except Exception as exc:
                    page.close()
                    _log.error(
                        "flatten: could not render page %d/%d: %s",
                        i + 1, n, exc,
                    )
                    raise RuntimeError(
                        f"Could not render page {i + 1}/{n}: {exc}"
                    ) from exc
                page.close()

                if pil.mode != "RGB":
                    pil = pil.convert("RGB")

                page_path = Path(tmpdir) / f"page_{i:04d}.jpg"
                try:
                    pil.save(
                        str(page_path), "JPEG", quality=_JPEG_QUALITY,
                    )
                except Exception as exc:
                    _log.error(
                        "flatten: could not write page %d/%d bitmap to %s: %s",
                        i + 1, n, page_path, exc,
                    )
                    raise RuntimeError(
                        f"Could not write page {i + 1}/{n} bitmap: {exc}"
                    ) from exc
                finally:
                    pil.close()
                    del pil
                page_files.append(page_path)
                rendered_any = True

                if progress:
                    # Reserve 70 % of the bar for rendering, save the
                    # remainder for the assemble + validate steps.
                    progress(5 + int(70 * (i + 1) / n))
        finally:
            pdf.close()

        if cancelled and cancelled():
            return

        if not page_files:
            _log.error("flatten: no page bitmaps were produced from %s", src)
            raise RuntimeError("flatten produced no pages")

        try:
            first = Image.open(str(page_files[0]))
            extras = [Image.open(str(p)) for p in page_files[1:]]
            try:
                first.save(
                    str(dst), "PDF",
                    resolution=float(_RENDER_DPI),
                    save_all=True,
                    append_images=extras,
                )
            finally:
                first.close()
                for e in extras:
                    e.close()
        except Exception as exc:
            # Tempdir cleanup is automatic, but the partial dst file is
            # ours to drop.
            if dst.exists():
                try:
                    dst.unlink()
                except OSError:
                    pass
            _log.error(
                "flatten: could not assemble PDF from %d page bitmap(s): %s",
                len(page_files), exc,
            )
            raise RuntimeError(
                f"Could not assemble flattened PDF: {exc}"
            ) from exc

    # If we bailed before any page rendered, drop any partial dst.
    if (cancelled_early or not rendered_any) and dst.exists():
        try:
            dst.unlink()
        except OSError:
            pass

    if cancelled and cancelled():
        # Cancelled after the assemble step succeeded but before
        # validation — dst is a complete-but-unwanted PDF on disk.
        # Match the earlier cancellation paths: leave no output file
        # behind.
        if dst.exists():
            try:
                dst.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                pass
        return

    if progress:
        progress(85)

    # Post-write validation. Acceptance criterion #6 / "Suggested safety
    # checks" in the handoff: confirm the output is plausible before we
    # let the worker hand it off. On any failure, remove the bad output so
    # the BaseConverterWorker.run finalisation can never publish it.
    try:
        if not dst.exists():
            _log.error("flatten: validation found no output file at %s", dst)
            raise RuntimeError("flatten produced no output file")

        size = dst.stat().st_size
        floor = max(_MIN_BYTES_PER_PAGE, n * _MIN_BYTES_PER_PAGE)
        if size < floor:
            _log.error(
                "flatten: output failed size floor: size=%d floor=%d "
                "pages=%d dst=%s",
                size, floor, n, dst,
            )
            raise RuntimeError(
                f"flatten output is suspiciously small ({size} bytes for "
                f"{n} page{'s' if n != 1 else ''}; expected at least "
                f"{floor} bytes). The source may be encrypted, "
                f"unrenderable, or the renderer failed silently."
            )

        try:
            out_doc = pdfium.PdfDocument(str(dst))
            try:
                out_pages = len(out_doc)
            finally:
                out_doc.close()
        except pdfium.PdfiumError as exc:
            _log.error(
                "flatten: output is not a valid PDF: %s (dst=%s)", exc, dst,
            )
            raise RuntimeError(
                f"flatten output is not a valid PDF: {exc}"
            ) from exc

        if out_pages != n:
            _log.error(
                "flatten: output page count mismatch: input=%d output=%d dst=%s",
                n, out_pages, dst,
            )
            raise RuntimeError(
                f"flatten output page count mismatch: input={n}, "
                f"output={out_pages}"
            )
    except RuntimeError:
        try:
            dst.unlink()
        except OSError:
            pass
        raise

    _log.info(
        "flatten: ok pages=%d size=%d dst=%s "
        "(note: PDFium does not execute Acrobat-specific JavaScript; "
        "only stored field values are baked)",
        n, dst.stat().st_size, dst,
    )

    if progress:
        progress(98)

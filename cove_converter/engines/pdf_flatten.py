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
import warnings
from pathlib import Path
from typing import Callable

from cove_converter.engines.pdfium_runtime import PDFIUM_LOCK

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
    """Return whether the parsed document contains a JavaScript action.

    PDF strings and page content are deliberately never searched as raw
    bytes: visible text such as ``/JS`` must retain its selectable text layer.
    Walking parsed objects also resolves indirect objects and object streams,
    so valid compressed/indirect action dictionaries are still detected.
    """
    try:
        if path.stat().st_size <= 0:
            return False
    except OSError:
        return False

    try:
        from pypdf import PdfReader
        # Passing a filename makes pypdf copy the entire PDF into BytesIO.
        # Keep a seekable file open while inspecting just the action graph.
        with path.open("rb") as source:
            return _reader_has_javascript(PdfReader(source, strict=False))
    except Exception:  # unreadable/malformed PDFs are handled by conversion
        return False


# A dictionary is only something a PDF viewer will ever execute as
# JavaScript if it sits in one of a small number of *specific structural
# positions*: the catalog's /OpenAction, a document/page/annotation/field
# /AA (additional-actions) dict, an annotation or form field's /A, an
# action's own /Next chain, or the catalog's /Names -> /JavaScript name
# tree. Matching on bare key names anywhere in the object graph (the
# previous approach here) is unsound in both directions: a key literally
# named "/A" or "/Names" can appear on an arbitrary custom dictionary that
# has nothing to do with actions, and the reachability-tracking needed to
# avoid that can itself hide a real action if the same object is also
# reachable through an unrelated path. Walking the known positions
# explicitly avoids both failure modes.
def _reader_has_javascript(reader) -> bool:
    from pypdf.generic import (
        ArrayObject, ByteStringObject, DictionaryObject, IndirectObject,
        StreamObject,
    )

    def resolve(obj):
        try:
            if isinstance(obj, IndirectObject):
                return obj.get_object()
            return obj
        except Exception:
            return None

    # The action subtypes ISO 32000-1 actually defines as carrying an
    # executable /JS script: the standard /S /JavaScript action, and a
    # rendition action (/S /Rendition, embedded video/audio playback
    # control, Section 12.6.4.13). Other action subtypes (/GoTo, /URI,
    # /Named, ...) each define their own subtype-specific keys (/D, /URI,
    # /N, ...); an unrelated /JS entry incidentally present alongside one
    # of those is inert data per the subtype's own definition, not a
    # script - accepting /JS on ANY action regardless of subtype (a prior
    # version of this check) treated that inert data as executable and
    # rasterised ordinary PDFs unnecessarily.
    _JS_BEARING_ACTION_TYPES = frozenset({"/JavaScript", "/Rendition"})

    def is_js_action(obj) -> bool:
        try:
            return (
                isinstance(obj, DictionaryObject)
                and "/S" in obj
                and obj["/S"] in _JS_BEARING_ACTION_TYPES
                and "/JS" in obj
                and isinstance(
                    obj["/JS"], (str, bytes, ByteStringObject, StreamObject)
                )
            )
        except Exception:
            return False

    # A single action, possibly chained through /Next (a single action or an
    # array of actions - the one place PDF actually allows an array here).
    # Every PDF action dictionary requires an /S entry (its type); a
    # dictionary without one is never treated as an action or followed
    # further, so an attacker cannot smuggle a JS-shaped descendant into
    # detection just by attaching an inert key to an unrelated object.
    def action_has_js(action_ref, seen: set[int]) -> bool:
        pending = [action_ref]
        while pending:
            item = pending.pop()
            try:
                item = resolve(item)
                if isinstance(item, ArrayObject):
                    if id(item) in seen:
                        continue
                    seen.add(id(item))
                    pending.extend(item)
                    continue
                if not isinstance(item, DictionaryObject):
                    continue
                if id(item) in seen:
                    continue
                seen.add(id(item))
                if "/S" not in item:
                    continue
                if is_js_action(item):
                    return True
                if "/Next" in item:
                    pending.append(item["/Next"])
            except Exception:
                continue
        return False

    # /OpenAction is special: per spec it is EITHER a destination array
    # (``[page /Fit]``, ``[page /XYZ left top zoom]``, ...) OR a single
    # action dictionary - never an array of multiple actions. Treating its
    # array form as "an array of actions" (as /Next legitimately allows)
    # is what let a destination's incidental page-object keys be
    # misread as an action in earlier versions of this detector: a
    # destination array's elements are never actions, no matter what keys
    # they carry, so they must not be inspected as actions at all.
    def open_action_has_js(oa_ref, seen: set[int]) -> bool:
        oa = resolve(oa_ref)
        if isinstance(oa, ArrayObject):
            return False
        return action_has_js(oa, seen)

    # An additional-actions dict: each value is a single action (or a
    # /Next-chained one), keyed by trigger event name. Only the event keys
    # the owning structure actually defines (PDF 32000-1:2008 tables
    # 194/195/197) are trigger events; anything else is inert data someone
    # stashed under /AA and must not be treated as an action.
    def aa_has_js(aa_ref, allowed_keys: frozenset, seen: set[int]) -> bool:
        aa = resolve(aa_ref)
        if not isinstance(aa, DictionaryObject):
            return False
        try:
            values = [v for k, v in dict.items(aa) if k in allowed_keys]
        except Exception:
            return False
        return any(action_has_js(value, seen) for value in values)

    _PAGE_AA_KEYS = frozenset({"/O", "/C"})
    _ANNOT_AA_KEYS = frozenset({
        "/E", "/X", "/D", "/U", "/Fo", "/Bl", "/PO", "/PC", "/PV", "/PI",
    })
    _FIELD_AA_KEYS = frozenset({"/K", "/F", "/V", "/C"})
    _CATALOG_AA_KEYS = frozenset({"/WC", "/WS", "/DS", "/WP", "/DP"})

    # PDF name trees (the structure ``/Names -> /JavaScript`` uses) are
    # either a leaf node (a flat ``/Names`` array) or an intermediate node
    # with ``/Kids`` pointing to further child nodes - real documents with
    # many named scripts commonly split the tree this way. Collect every
    # action reference from every leaf, cycle-protected by node identity.
    def name_tree_action_refs(node_ref, seen_nodes: set[int]) -> list:
        refs: list = []
        stack = [node_ref]
        while stack:
            node = stack.pop()
            try:
                node = resolve(node)
                if not isinstance(node, DictionaryObject) or id(node) in seen_nodes:
                    continue
                seen_nodes.add(id(node))
                if "/Names" in node:
                    arr = resolve(node["/Names"])
                    if isinstance(arr, ArrayObject):
                        # Alternating (name, action-ref) pairs - the refs
                        # are at the odd indices.
                        refs.extend(list(arr)[1::2])
                if "/Kids" in node:
                    kids = resolve(node["/Kids"])
                    if isinstance(kids, ArrayObject):
                        stack.extend(kids)
            except Exception:
                continue
        return refs

    seen_actions: set[int] = set()
    seen_pages: set[int] = set()
    # A single indirect Widget-annotation dictionary is routinely referenced
    # from BOTH a page's /Annots array AND (as a merged field/widget) from
    # /AcroForm/Fields, with different action keys meaningful in each role
    # (an annotation's /A and /AA event set vs. a field's). Deduplicating
    # those two roles through one shared "seen" set let visiting it in one
    # role suppress ever checking the other role's actions - use separate
    # sets so each role is still examined once.
    seen_annots: set[int] = set()
    seen_fields: set[int] = set()

    try:
        root = resolve(reader.trailer["/Root"]) if "/Root" in reader.trailer else None
    except Exception:
        root = None
    if not isinstance(root, DictionaryObject):
        return False

    try:
        if "/OpenAction" in root and open_action_has_js(root["/OpenAction"], seen_actions):
            return True
    except Exception:
        pass

    try:
        if "/AA" in root and aa_has_js(root["/AA"], _CATALOG_AA_KEYS, seen_actions):
            return True
    except Exception:
        pass

    try:
        if "/Names" in root:
            names = resolve(root["/Names"])
            if isinstance(names, DictionaryObject) and "/JavaScript" in names:
                js_tree = names["/JavaScript"]
                for value in name_tree_action_refs(js_tree, set()):
                    if action_has_js(value, seen_actions):
                        return True
    except Exception:
        pass

    try:
        pages = list(reader.pages)
    except Exception:
        pages = []
    for page in pages:
        try:
            if not isinstance(page, DictionaryObject) or id(page) in seen_pages:
                continue
            seen_pages.add(id(page))
            if "/AA" in page and aa_has_js(page["/AA"], _PAGE_AA_KEYS, seen_actions):
                return True
            if "/Annots" not in page:
                continue
            annots = resolve(page["/Annots"])
            if not isinstance(annots, ArrayObject):
                continue
            for annot_ref in annots:
                annot = resolve(annot_ref)
                if not isinstance(annot, DictionaryObject) or id(annot) in seen_annots:
                    continue
                seen_annots.add(id(annot))
                if "/A" in annot and action_has_js(annot["/A"], seen_actions):
                    return True
                if "/AA" in annot and aa_has_js(annot["/AA"], _ANNOT_AA_KEYS, seen_actions):
                    return True
        except Exception:
            continue

    try:
        acro = resolve(root["/AcroForm"]) if "/AcroForm" in root else None
    except Exception:
        acro = None
    if isinstance(acro, DictionaryObject):
        try:
            fields = resolve(acro["/Fields"]) if "/Fields" in acro else None
        except Exception:
            fields = None
        stack = list(fields) if isinstance(fields, ArrayObject) else []
        while stack:
            field_ref = stack.pop()
            try:
                field = resolve(field_ref)
                if not isinstance(field, DictionaryObject) or id(field) in seen_fields:
                    continue
                seen_fields.add(id(field))
                if "/A" in field and action_has_js(field["/A"], seen_actions):
                    return True
                if "/AA" in field and aa_has_js(field["/AA"], _FIELD_AA_KEYS, seen_actions):
                    return True
                if "/Kids" in field:
                    kids = resolve(field["/Kids"])
                    if isinstance(kids, ArrayObject):
                        stack.extend(kids)
            except Exception:
                continue

    # Outline (bookmark) items form their own tree, navigated via /First
    # (first child) and /Next (next sibling) - a different meaning of
    # /Next than an action's chain, so this is deliberately not routed
    # through action_has_js's /Next handling. Each item may carry its own
    # /A action, triggered when the bookmark is clicked.
    try:
        outlines = resolve(root["/Outlines"]) if "/Outlines" in root else None
    except Exception:
        outlines = None
    if isinstance(outlines, DictionaryObject):
        seen_outline: set[int] = set()
        stack = [outlines["/First"]] if "/First" in outlines else []
        while stack:
            item_ref = stack.pop()
            try:
                item = resolve(item_ref)
                if not isinstance(item, DictionaryObject) or id(item) in seen_outline:
                    continue
                seen_outline.add(id(item))
                if "/A" in item and action_has_js(item["/A"], seen_actions):
                    return True
                if "/First" in item:
                    stack.append(item["/First"])
                if "/Next" in item:
                    stack.append(item["/Next"])
            except Exception:
                continue

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
    # workers can't race PDFium's global state (see ``PDFIUM_LOCK``).
    with PDFIUM_LOCK:
        _flatten_pdf_locked(src, dst, progress=progress, cancelled=cancelled)


def _flatten_pdf_locked(
    src: Path,
    dst: Path,
    *,
    progress: Callable[[int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> None:
    # The import is local because pypdfium2 is heavy and the module is also
    # imported for the cheap ``has_pdf_javascript`` detection path.
    import pypdfium2 as pdfium  # type: ignore[import-untyped]
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
        except Exception as exc:
            # Real failure (rare) - surface it. Catch any exception, not
            # only PdfiumError: an unclosed ``pdf`` here would otherwise
            # leak the native document past the point where the shared
            # lock is released, letting its eventual GC-triggered close
            # race another thread's PDFium call outside the lock.
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

    # Render and append one page at a time. Passing the explicit quality to
    # PIL's PDF writer encodes each bitmap once; the previous JPEG tempfile
    # spool decoded quality-92 JPEGs and then encoded them again at PIL's
    # default quality. Resident memory remains bounded to one page.
    scale = _RENDER_DPI / 72.0
    cancelled_early = False
    rendered_any = False
    try:
        # Inside the try/finally that owns ``pdf``: a ``progress`` callback
        # raising here must not leak the native document past the point
        # where the shared lock is released (see the init_forms note above).
        if progress:
            progress(5)

        for i in range(n):
            if cancelled and cancelled():
                cancelled_early = True
                break

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
                _log.error(
                    "flatten: could not render page %d/%d: %s",
                    i + 1, n, exc,
                )
                raise RuntimeError(
                    f"Could not render page {i + 1}/{n}: {exc}"
                ) from exc
            finally:
                page.close()

            try:
                if pil.mode != "RGB":
                    converted = pil.convert("RGB")
                    pil.close()
                    pil = converted
                pil.save(
                    str(dst), "PDF",
                    resolution=float(_RENDER_DPI),
                    quality=_JPEG_QUALITY,
                    append=rendered_any,
                )
            except Exception as exc:
                _log.error(
                    "flatten: could not write page %d/%d to PDF: %s",
                    i + 1, n, exc,
                )
                raise RuntimeError(
                    f"Could not assemble flattened PDF page {i + 1}/{n}: {exc}"
                ) from exc
            finally:
                pil.close()
                del pil
            rendered_any = True

            if progress:
                progress(5 + int(70 * (i + 1) / n))
    except Exception:
        try:
            dst.unlink()
        except OSError:
            pass
        raise
    finally:
        pdf.close()

    # If we bailed before any page rendered, drop any partial dst.
    if cancelled_early or not rendered_any:
        try:
            dst.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass
        return

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

    # Keep a checkpoint immediately before validation. This catches a cancel
    # delivered after the final page save/progress callback and ensures the
    # complete-but-unwanted output is removed.
    if cancelled and cancelled():
        try:
            dst.unlink()
        except OSError:
            pass
        return

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

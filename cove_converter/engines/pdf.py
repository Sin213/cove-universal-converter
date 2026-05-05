"""PDF worker — handles every conversion where .pdf is on either side.

- PDF → txt/md/html: extract text with pypdf (pure Python, cross-platform).
- PDF → docx/odt/rtf/epub: extract text with pypdf, then pipe through pandoc
  to the target document format. The result is text-only (formatting is lost)
  but the structure is editable — what matters when you need to revise a
  PDF in Word/LibreOffice/etc.
- ★ → .pdf: pandoc renders the input to standalone HTML, then xhtml2pdf
  produces the final PDF. Keeps us off of LaTeX / WeasyPrint system deps so
  the same code works on Arch and Windows from one pip install.
"""
from __future__ import annotations

import html
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable

from cove_converter.binaries import PANDOC, resolve
from cove_converter.engines.base import BaseConverterWorker
from cove_converter.engines.pdf_flatten import flatten_pdf, has_pdf_javascript


# ---- Scanned-PDF enhancement -----------------------------------------------
# Conservative pipeline tuned for faded office scans. Values are deliberately
# mild — destroying mid-greys / thin diagram lines is worse than leaving a
# faint background tint. Off by default; gated by ``enhance_scanned_pdf``.
_DEFAULT_DPI            = 200
_AUTOCONTRAST_CUTOFF    = 1
_BG_WHITEN_THRESHOLD    = 230          # 230..255 → 255
_TEXT_CONTRAST_GAIN     = 1.15
_UNSHARP_RADIUS         = 1.0
_UNSHARP_PERCENT        = 80
_UNSHARP_THRESHOLD      = 3
_REPACK_JPEG_QUALITY    = 88


# ---- Image → PDF -----------------------------------------------------------
_IMAGE_TO_PDF_EXTS = {".png", ".jpg", ".jpeg", ".webp"}


def _build_whiten_lut() -> list[int]:
    return [v if v < _BG_WHITEN_THRESHOLD else 255 for v in range(256)]


_WHITEN_LUT = _build_whiten_lut()


def _enhance_page(img):
    from PIL import Image, ImageEnhance, ImageFilter, ImageOps

    img = ImageOps.autocontrast(img, cutoff=_AUTOCONTRAST_CUTOFF)

    if img.mode == "L":
        img = img.point(_WHITEN_LUT)
    else:
        if img.mode != "RGB":
            img = img.convert("RGB")
        img = Image.merge(
            "RGB",
            tuple(band.point(_WHITEN_LUT) for band in img.split()),
        )

    img = ImageEnhance.Contrast(img).enhance(_TEXT_CONTRAST_GAIN)
    img = img.filter(ImageFilter.UnsharpMask(
        radius=_UNSHARP_RADIUS,
        percent=_UNSHARP_PERCENT,
        threshold=_UNSHARP_THRESHOLD,
    ))
    return img


def _enhance_scanned_pdf(
    src: Path,
    dst: Path,
    *,
    dpi: int = _DEFAULT_DPI,
    progress: Callable[[int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> None:
    """Render every page of ``src``, run the enhancement pipeline, and write
    a new PDF to ``dst``. Page dimensions are preserved by rendering at
    ``scale = dpi/72`` and embedding the same DPI in the output PDF.

    Bounded-memory assembly. Each page is rendered, enhanced, written to
    ``dst`` via PIL's incremental ``append=True`` PDF save, and released
    before the next page is touched. PIL's PdfParser opens the in-progress
    file in ``r+b`` mode but only re-reads the xref/trailer metadata when
    appending — page content streams stay on disk. Resident memory peaks
    at one full-resolution bitmap regardless of page count. No per-page
    PdfReader, PDF BytesIO, or PIL-image list is retained.
    """
    if src.resolve() == dst.resolve():
        raise RuntimeError("Refusing to enhance PDF in place")

    import pypdfium2 as pdfium

    if progress:
        progress(5)

    try:
        pdf = pdfium.PdfDocument(str(src))
    except pdfium.PdfiumError as exc:
        msg = str(exc).lower()
        if "password" in msg or "encrypted" in msg:
            raise RuntimeError(
                "PDF is password-protected — please unlock it first"
            ) from exc
        raise RuntimeError(f"Could not open PDF: {exc}") from exc

    n = len(pdf)
    if n == 0:
        pdf.close()
        raise RuntimeError("PDF contains no pages")

    wrote_any = False
    try:
        scale = dpi / 72.0
        for i in range(n):
            if cancelled and cancelled():
                return

            page = pdf[i]
            bitmap = page.render(scale=scale)
            try:
                pil = bitmap.to_pil()
            finally:
                bitmap.close()
            page.close()

            pil = _enhance_page(pil)
            if pil.mode != "RGB":
                pil = pil.convert("RGB")

            try:
                # First save creates ``dst`` (mkstemp pre-allocated an empty
                # file in the lifecycle path; PIL's "w+b" truncates it).
                # Every page after the first is appended in place, so the
                # bitmap from page i-1 is never resident at the same time
                # as the bitmap from page i.
                pil.save(
                    str(dst),
                    "PDF",
                    resolution=float(dpi),
                    quality=_REPACK_JPEG_QUALITY,
                    append=wrote_any,
                )
            finally:
                pil.close()
                del pil
            wrote_any = True

            if progress:
                progress(10 + int(85 * (i + 1) / n))
    finally:
        pdf.close()

    if cancelled and cancelled():
        return

    if progress:
        progress(95)


def _image_to_pdf(
    src: Path,
    dst: Path,
    *,
    progress: Callable[[int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> None:
    """Render a single raster image as a one-page PDF at ``dst``.

    Uses PIL's native PDF writer with ``resolution=72.0`` so the page size
    in points equals the image size in pixels (auto page size from image).
    Transparency is flattened onto white before save to match the JPEG
    idiom in ``cove_converter/engines/pillow.py``.
    """
    from PIL import Image, ImageOps

    if progress:
        progress(10)

    with Image.open(src) as raw:
        img = ImageOps.exif_transpose(raw)

    try:
        has_transparency = (
            img.mode in ("RGBA", "LA")
            or "transparency" in img.info
        )
        if has_transparency:
            background = Image.new("RGB", img.size, (255, 255, 255))
            rgba = img.convert("RGBA")
            background.paste(rgba, mask=rgba.split()[-1])
            img = background
        elif img.mode != "RGB":
            img = img.convert("RGB")

        if progress:
            progress(60)

        img.save(dst, "PDF", resolution=72.0)
    finally:
        img.close()

    if progress:
        progress(95)


# xhtml2pdf's CSS parser rejects modern selectors that pandoc's standalone
# HTML5 template ships with (e.g. ``:not(:hover)``), so the whole conversion
# fails before a single page is rendered. Strip embedded style/script blocks
# from the pandoc output before handing it to ``pisa.CreatePDF``. The
# document body remains intact — paragraphs, lists, and headings still
# round-trip fine, just without pandoc's default cosmetic styling.
_STYLE_OR_SCRIPT_BLOCK = re.compile(
    r"<(style|script)\b[^>]*>.*?</\1>",
    re.IGNORECASE | re.DOTALL,
)


def _strip_inline_css(html_source: str) -> str:
    return _STYLE_OR_SCRIPT_BLOCK.sub("", html_source)


def _no_window_kwargs() -> dict:
    if sys.platform.startswith("win"):
        return {"creationflags": 0x08000000}
    return {}


def _extract_pdf_text(pdf_path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(pdf_path))
    parts: list[str] = []
    for page in reader.pages:
        parts.append(page.extract_text() or "")
    return "\n\n".join(parts).strip() + "\n"


def _text_to_minimal_html(text: str) -> str:
    escaped = html.escape(text)
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'></head>"
        "<body><pre style='white-space: pre-wrap; font-family: sans-serif;'>"
        f"{escaped}</pre></body></html>"
    )


def _pandoc_to_html(input_path: Path) -> str:
    cmd = [
        resolve(PANDOC),
        str(input_path),
        "-t", "html5",
        "--standalone",
        "--embed-resources",
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        **_no_window_kwargs(),
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"pandoc exited {result.returncode}")
    return result.stdout


def _html_to_pdf(html_source: str, output_path: Path) -> None:
    from xhtml2pdf import pisa

    with output_path.open("wb") as f:
        result = pisa.CreatePDF(src=html_source, dest=f, encoding="utf-8")
    if result.err:
        raise RuntimeError(f"xhtml2pdf reported {result.err} error(s) while rendering PDF")


def _text_to_doc(text: str, output_path: Path) -> None:
    """Pipe extracted PDF text through pandoc to a doc/ebook target.

    The text is fed to pandoc as markdown so blank-line paragraph splits
    survive into the output. Used for PDF → docx / odt / rtf / epub."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", encoding="utf-8", delete=False,
    ) as tf:
        tf.write(text)
        temp_md = Path(tf.name)
    try:
        cmd = [
            resolve(PANDOC),
            str(temp_md),
            "-f", "markdown",
            "-o", str(output_path),
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            **_no_window_kwargs(),
        )
        if result.returncode != 0:
            raise RuntimeError(
                result.stderr.strip() or f"pandoc exited {result.returncode}"
            )
    finally:
        temp_md.unlink(missing_ok=True)


class PdfWorker(BaseConverterWorker):
    def _convert(self) -> None:
        in_ext  = self.input_path.suffix.lower()
        out_ext = self.output_path.suffix.lower()

        # "Smart" PDFs — JavaScript-driven content / form filling —
        # render visually wrong (or blank) under our normal byte-copy
        # path. Detect them by literal byte scan and rasterise every
        # page into a static multi-page PDF before downstream sees it.
        #
        # Scope is intentionally narrow: only PDF → PDF runs through
        # flatten. Rasterising destroys the text layer, so PDF →
        # txt/md/html/docx/odt/rtf/epub keeps using pypdf, which
        # already reads stored AcroForm field values directly.
        if (
            in_ext == ".pdf"
            and out_ext == ".pdf"
            and has_pdf_javascript(self.input_path)
        ):
            # Emit a small progress tick *before* flatten so the user
            # sees motion immediately even on a fast failure path.
            self.progress.emit(2)
            # ``flatten_pdf`` validates and removes its own bad output,
            # so it's safe to point it at ``self.output_path`` directly
            # — the worker-owned temp file. The atomic ``os.replace``
            # in BaseConverterWorker.run finalises it.
            flatten_pdf(
                self.input_path,
                self.output_path,
                progress=self.progress.emit,
                cancelled=lambda: self._cancel,
            )
            return

        # PDF → PDF: optional scan enhancement, otherwise byte-identical copy.
        # ``self.output_path`` is the worker-owned temp path; the atomic
        # ``os.replace`` in BaseConverterWorker.run finalises it.
        if in_ext == ".pdf" and out_ext == ".pdf":
            if self.settings.enhance_scanned_pdf:
                _enhance_scanned_pdf(
                    self.input_path,
                    self.output_path,
                    dpi=self.settings.pdf_enhance_dpi,
                    progress=self.progress.emit,
                    cancelled=lambda: self._cancel,
                )
            else:
                self.progress.emit(5)
                shutil.copyfile(self.input_path, self.output_path)
                self.progress.emit(95)
            return

        if in_ext == ".pdf":
            self.progress.emit(10)
            text = _extract_pdf_text(self.input_path)
            self.progress.emit(50)
            if out_ext in (".txt", ".md"):
                self.output_path.write_text(text, encoding="utf-8")
            elif out_ext in (".html", ".htm"):
                self.output_path.write_text(_text_to_minimal_html(text), encoding="utf-8")
            elif out_ext in (".docx", ".odt", ".rtf", ".epub"):
                _text_to_doc(text, self.output_path)
            else:
                raise RuntimeError(f"Unsupported PDF target: {out_ext}")
            self.progress.emit(95)
            return

        if out_ext == ".pdf" and in_ext in _IMAGE_TO_PDF_EXTS:
            _image_to_pdf(
                self.input_path,
                self.output_path,
                progress=self.progress.emit,
                cancelled=lambda: self._cancel,
            )
            return

        if out_ext == ".pdf":
            self.progress.emit(10)
            if in_ext in (".html", ".htm"):
                html_source = self.input_path.read_text(encoding="utf-8", errors="replace")
            elif in_ext == ".txt":
                html_source = _text_to_minimal_html(self.input_path.read_text(encoding="utf-8", errors="replace"))
            else:
                # Use a temp file so pandoc can sniff the format by extension.
                with tempfile.NamedTemporaryFile(suffix=in_ext, delete=False) as _:
                    pass  # pandoc reads the real input below
                html_source = _strip_inline_css(_pandoc_to_html(self.input_path))
            self.progress.emit(60)
            _html_to_pdf(html_source, self.output_path)
            return

        raise RuntimeError(f"PdfWorker cannot convert {in_ext} → {out_ext}")

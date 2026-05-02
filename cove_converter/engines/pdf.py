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
import subprocess
import sys
import tempfile
from pathlib import Path

from cove_converter.binaries import PANDOC, resolve
from cove_converter.engines.base import BaseConverterWorker


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

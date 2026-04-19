"""PDF worker — handles every conversion where .pdf is on either side.

- PDF → txt/md/html: extract text with pypdf (pure Python, cross-platform).
- ★ → .pdf: pandoc renders the input to standalone HTML, then xhtml2pdf
  produces the final PDF. Keeps us off of LaTeX / WeasyPrint system deps so
  the same code works on Arch and Windows from one pip install.
"""
from __future__ import annotations

import html
import subprocess
import sys
import tempfile
from pathlib import Path

from cove_converter.binaries import PANDOC, resolve
from cove_converter.engines.base import BaseConverterWorker


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


class PdfWorker(BaseConverterWorker):
    def _convert(self) -> None:
        in_ext  = self.input_path.suffix.lower()
        out_ext = self.output_path.suffix.lower()

        if in_ext == ".pdf":
            self.progress.emit(10)
            text = _extract_pdf_text(self.input_path)
            self.progress.emit(70)
            if out_ext in (".txt", ".md"):
                self.output_path.write_text(text, encoding="utf-8")
            elif out_ext in (".html", ".htm"):
                self.output_path.write_text(_text_to_minimal_html(text), encoding="utf-8")
            else:
                raise RuntimeError(f"Unsupported PDF target: {out_ext}")
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
                html_source = _pandoc_to_html(self.input_path)
            self.progress.emit(60)
            _html_to_pdf(html_source, self.output_path)
            return

        raise RuntimeError(f"PdfWorker cannot convert {in_ext} → {out_ext}")

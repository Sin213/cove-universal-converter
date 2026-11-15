"""Restricted SVG rendering in a disposable, deadline-limited process.

Only a self-contained vector subset reaches svglib. Never pass it an input
filename or base URL: references cannot resolve beside the user's input.
"""
from __future__ import annotations

import io
import math
import multiprocessing
import os
import re
import time
import xml.etree.ElementTree as ET

from cove_converter.engines.base import BaseConverterWorker

MAX_BYTES = 2 * 1024 * 1024
MAX_ELEMENTS = 10000
MAX_DEPTH = 64
MAX_DIMENSION = 8192
MAX_PIXELS = 16_000_000
MAX_ATTRIBUTE_LENGTH = 32_768
MAX_ATTRIBUTE_NUMBERS = 4096
MAX_COMPLEXITY = 250_000
MAX_MEMORY_BYTES = 512 * 1024 * 1024
TIMEOUT_SECONDS = 15
_TAGS = frozenset((
    "svg", "g", "defs", "path", "rect", "circle", "ellipse", "line",
    "polyline", "polygon", "text", "tspan", "linearGradient", "radialGradient",
    "stop", "clipPath", "title", "desc",
))
_SVG_NS = "{http://www.w3.org/2000/svg}"
_LOCAL_URL = re.compile(r"url\(\s*['\"]?#[A-Za-z_][\w.-]*['\"]?\s*\)", re.I)
_NUMBER = re.compile(r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?")


class _BuiltinFonts:
    """Never let an SVG-controlled family name reach file/fontconfig discovery."""
    def find_font(self, name, weight="normal", style="normal"):
        family = name.casefold()
        bold = weight in ("bold", "bolder", "600", "700", "800", "900")
        italic = style in ("italic", "oblique")
        if family in ("serif", "times", "times-roman", "times new roman"):
            font = ("Times-BoldItalic" if bold and italic else "Times-Bold" if bold
                    else "Times-Italic" if italic else "Times-Roman")
        else:
            base = "Courier" if family in ("monospace", "courier", "courier new") else "Helvetica"
            font = base + ("-BoldOblique" if bold and italic else "-Bold" if bold
                           else "-Oblique" if italic else "")
        return font, True


def _validated_svg(data: bytes) -> bytes:
    if len(data) > MAX_BYTES:
        raise ValueError("SVG exceeds the 2 MiB file limit")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeError as exc:
        raise ValueError("SVG must use UTF-8 encoding") from exc
    if "\x00" in text or re.search(r"<!\s*(DOCTYPE|ENTITY)|<\?", text, re.I):
        # An ordinary XML declaration is permitted, but no other PI/DTD.
        text = re.sub(r'^\s*<\?xml\s+[^?]*\?>', '', text, count=1)
        if "\x00" in text or re.search(r"<!\s*(DOCTYPE|ENTITY)|<\?", text, re.I):
            raise ValueError("SVG entities, DTDs and processing instructions are unsupported")
    depth = count = complexity = 0
    inherited_costs = [0]
    root = None
    try:
        for event, element in ET.iterparse(io.StringIO(text), events=("start", "end")):
            if event == "end":
                depth -= 1
                inherited_costs.pop()
                continue
            depth += 1
            count += 1
            if depth > MAX_DEPTH or count > MAX_ELEMENTS:
                raise ValueError("SVG exceeds element/depth limits")
            tag = element.tag.removeprefix(_SVG_NS)
            if tag not in _TAGS:
                raise ValueError(f"SVG feature is unsupported: {tag[:80]}")
            if root is None:
                root = element
                if tag != "svg":
                    raise ValueError("SVG root element is required")
            own_cost = 0
            for key, value in element.attrib.items():
                if len(value) > MAX_ATTRIBUTE_LENGTH:
                    raise ValueError("SVG exceeds attribute/list complexity limits")
                numbers = sum(1 for _ in _NUMBER.finditer(value))
                if numbers > MAX_ATTRIBUTE_NUMBERS:
                    raise ValueError("SVG exceeds attribute/list complexity limits")
                own_cost += len(value) + numbers
                name = key.rsplit("}", 1)[-1].lower()
                if name.startswith("on") or name in ("href", "base"):
                    raise ValueError("SVG resource references and event handlers are unsupported")
                # CSS escapes/comments can hide URLs or imports. Reject them
                # rather than implementing a second CSS parser/security policy.
                if "\\" in value or "/*" in value or "@" in value:
                    raise ValueError("SVG escaped CSS/imports are unsupported")
                remaining = _LOCAL_URL.sub("", value)
                if re.search(r"url\s*\(", remaining, re.I):
                    raise ValueError("SVG external resources are unsupported")
            # Conservatively charge ancestor attributes at every descendant:
            # a short inherited dash list can otherwise expand thousands of
            # times in svglib. This also bounds path/points/style processing.
            inherited_costs.append(inherited_costs[-1] + own_cost)
            complexity += inherited_costs[-1]
            if complexity > MAX_COMPLEXITY:
                raise ValueError("SVG exceeds inherited attribute complexity budget")
    except ET.ParseError as exc:
        raise ValueError("SVG is malformed") from exc
    if root is None:
        raise ValueError("SVG is empty")
    # svglib looks up defs/clipPath/gradients using SVG's default namespace.
    ET.register_namespace("", _SVG_NS[1:-1])
    return ET.tostring(root, encoding="utf-8")


def _limit_memory(budget: int) -> None:
    """Best-effort POSIX allocation limits, called only in renderer children."""
    if os.name != "posix":
        return
    import resource
    for name in ("RLIMIT_AS", "RLIMIT_DATA"):
        limit = getattr(resource, name, None)
        if limit is None:
            continue
        try:
            soft, hard = resource.getrlimit(limit)
            bounded = min([budget, *(n for n in (soft, hard) if n != resource.RLIM_INFINITY)])
            resource.setrlimit(limit, (bounded, hard))
        except (OSError, ValueError):
            # Some POSIX runtimes do not implement both limits. Validation and
            # the killable processing deadline still apply on those platforms.
            continue


def _render(data, output, target, jpeg_quality, webp_quality, connection, memory_limit_bytes=None):
    """Spawn entry point: parse and render without access to source paths."""
    try:
        if memory_limit_bytes is not None:
            _limit_memory(memory_limit_bytes)
        clean = _validated_svg(data)
        from svglib.svglib import svg2rlg
        from reportlab.graphics import renderPDF
        from reportlab.pdfgen.canvas import Canvas
        import pypdfium2 as pdfium

        drawing = svg2rlg(io.BytesIO(clean), font_map=_BuiltinFonts())
        if drawing is None:
            raise ValueError("SVG could not be rendered")
        width, height = drawing.width, drawing.height
        pixels = (width * 4 / 3, height * 4 / 3)  # SVG CSS pixels are 96 dpi.
        if (not all(math.isfinite(n) and 0 < n <= MAX_DIMENSION for n in pixels)
                or math.ceil(pixels[0]) * math.ceil(pixels[1]) > MAX_PIXELS):
            raise ValueError("SVG exceeds output dimension/pixel limits")
        pdf = io.BytesIO()
        canvas = Canvas(pdf, pagesize=(width, height))
        if target in (".jpg", ".pdf"):
            canvas.setFillColorRGB(1, 1, 1)
            canvas.rect(0, 0, width, height, fill=1, stroke=0)
        renderPDF.draw(drawing, canvas, 0, 0)
        canvas.showPage()
        canvas.save()
        if target == ".pdf":
            with open(output, "wb") as destination:
                destination.write(pdf.getvalue())
        else:
            with pdfium.PdfDocument(pdf.getvalue()) as document:
                page = document[0]
                bitmap = page.render(scale=4 / 3, fill_color=(0, 0, 0, 0))
                image = bitmap.to_pil()
                try:
                    if target == ".jpg":
                        image.convert("RGB").save(output, "JPEG", quality=jpeg_quality)
                    elif target == ".webp":
                        image.save(output, "WEBP", quality=webp_quality)
                    else:
                        image.save(output, "PNG")
                finally:
                    image.close()
                    bitmap.close()
                    page.close()
        connection.send(None)
    except MemoryError:
        connection.send("SVG renderer memory limit exceeded")
    except Exception as exc:
        connection.send(f"SVG conversion failed: {str(exc)[:500]}")
    finally:
        connection.close()


class SvgWorker(BaseConverterWorker):
    timeout_seconds = TIMEOUT_SECONDS
    memory_limit_bytes = MAX_MEMORY_BYTES

    def _convert(self):
        target = self.output_path.suffix.lower()
        if target not in (".png", ".jpg", ".webp", ".pdf"):
            raise ValueError("Unsupported SVG output format")
        if self._cancel:
            return
        with self.input_path.open("rb") as source:
            data = source.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ValueError("SVG exceeds the 2 MiB file limit")
        context = multiprocessing.get_context("spawn")
        reader, writer = context.Pipe(duplex=False)
        process = context.Process(target=_render, args=(
            data, str(self.output_path), target, self.settings.effective_jpeg_quality(),
            self.settings.effective_webp_quality(), writer, self.memory_limit_bytes,
        ), daemon=True)
        deadline = time.monotonic() + self.timeout_seconds
        try:
            process.start()
            writer.close()
            while process.is_alive():
                if self._cancel:
                    return
                if time.monotonic() >= deadline:
                    raise ValueError("SVG processing time limit exceeded (15 seconds)")
                process.join(0.02)
            if self._cancel:
                return
            if time.monotonic() >= deadline:
                raise ValueError("SVG processing time limit exceeded (15 seconds)")
            if process.exitcode != 0 or not reader.poll():
                raise ValueError("SVG renderer stopped unexpectedly (memory/resource limit or renderer error)")
            try:
                error = reader.recv()
            except EOFError as exc:
                raise ValueError("SVG renderer stopped unexpectedly") from exc
            if error:
                raise ValueError(error)
        finally:
            if process.is_alive():
                process.terminate()
                process.join(0.5)
                if process.is_alive():
                    process.kill()
                    process.join()
            reader.close()
            writer.close()
            if process.pid is not None:
                process.close()

"""SVG routes, real rendering, resource rejection and process lifetime."""
import hashlib
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PIL import Image
from pypdf import PdfReader

from cove_converter.engines import worker_for
from cove_converter.routing import engine_for, targets_for

SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="16"><rect width="8" height="8" fill="red"/></svg>'


def convert(tmp_path, text, target=".png", **options):
    from cove_converter.engines.svg import SvgWorker
    source = tmp_path / "source.svg"
    source.write_bytes(text if isinstance(text, bytes) else text.encode())
    output = tmp_path / ("result" + target)
    worker = SvgWorker(source, output)
    for key, value in options.items():
        setattr(worker, key, value)
    errors = []
    worker.failed.connect(lambda message, tb: errors.append(message))
    before = hashlib.sha256(source.read_bytes()).digest()
    worker.run()
    assert hashlib.sha256(source.read_bytes()).digest() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(
        ["source.svg"] + ([output.name] if output.exists() else [])
    )
    return output, errors


def test_svg_routes():
    assert targets_for(".svg") == (".png", ".jpg", ".webp", ".pdf")
    for target in targets_for(".svg"):
        assert engine_for(".svg", target) == "Svg"
        assert worker_for("Svg").__name__ == "SvgWorker"
    assert not engine_for(".svg", ".svg")


@pytest.mark.parametrize("target", [".png", ".jpg", ".webp", ".pdf"])
def test_svg_outputs_open_and_preserve_alpha_or_white(tmp_path, target):
    output, errors = convert(tmp_path, SVG, target)
    assert not errors
    if target == ".pdf":
        assert len(PdfReader(output).pages) == 1
    else:
        with Image.open(output) as image:
            assert image.size == (24, 16)
            if target in (".png", ".webp"):
                assert image.convert("RGBA").getpixel((20, 12))[3] == 0
            else:
                assert min(image.getpixel((20, 12))) > 240


@pytest.mark.parametrize("text", [
    '<svg>',
    '<!DOCTYPE svg [<!ENTITY x "boom">]><svg>&x;</svg>',
    b'\xff\xfe<\x00!\x00D\x00O\x00C\x00T\x00Y\x00P\x00E\x00',
    SVG.replace('<rect', '<image href="https://example.invalid/a.png"/><rect'),
    SVG.replace('<rect', '<image href="file:///etc/passwd"/><rect'),
    SVG.replace('<rect', '<image href="../secret.png"/><rect'),
    SVG.replace('<rect', '<use href="#a"/><rect'),
    SVG.replace('<rect', '<style>@import "https://example.invalid/x";</style><rect'),
    SVG.replace('fill="red"', 'fill="url(file:///etc/passwd)"'),
    SVG.replace('<rect', '<script>alert(1)</script><rect'),
    SVG.replace('width="24"', 'width="9999999"'),
    '<svg>' + '<g>' * 70 + '</g>' * 70 + '</svg>',
    '<svg>' + '<rect/>' * 10001 + '</svg>',
    '<svg>' + ' ' * (2 * 1024 * 1024) + '</svg>',
], ids=["malformed", "entity", "utf16", "http", "file", "relative", "use", "css", "paint", "script", "dimensions", "depth", "elements", "size"])
def test_hostile_or_unsupported_svg_fails_cleanly(tmp_path, text):
    output, errors = convert(tmp_path, text)
    assert errors and "SVG" in errors[0]
    assert not output.exists()


def test_svg_deadline_terminates_process_and_cleans(tmp_path):
    output, errors = convert(tmp_path, SVG, timeout_seconds=0)
    assert errors and "time limit" in errors[0]
    assert not output.exists()


def test_svg_precancel_does_not_publish(tmp_path):
    output, errors = convert(tmp_path, SVG, _cancel=True)
    assert not output.exists()
    assert not errors


def test_svg_resource_rejection_precedes_renderer_and_resource_access(tmp_path, monkeypatch):
    from cove_converter.engines.svg import _render
    import socket
    import svglib.svglib
    secret = tmp_path / "secret.png"
    secret.write_bytes(b"must never be read")
    link = tmp_path / "linked.png"
    link.symlink_to(secret)
    def forbidden(*args, **kwargs):
        pytest.fail("Resource or renderer accessed before rejecting unsafe SVG")
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(svglib.svglib, "svg2rlg", forbidden)
    class Result:
        error = None
        def send(self, value):
            self.error = value
        def close(self):
            pass
    for reference in (str(secret), str(link), "../secret.png", "http://127.0.0.1:9/x", "ftp://host/x"):
        result = Result()
        data = SVG.replace('<rect', f'<image href="{reference}"/><rect').encode()
        _render(data, str(tmp_path / "out.png"), ".png", 95, 95, result)
        assert result.error and "SVG" in result.error
    assert not (tmp_path / "out.png").exists()


def test_svg_fonts_cannot_probe_files_or_start_fontconfig(tmp_path, monkeypatch):
    from cove_converter.engines.svg import _render
    from svglib.fonts import FontMap
    def forbidden(*args, **kwargs):
        pytest.fail("SVG font name triggered filesystem/fontconfig discovery")
    monkeypatch.setattr(FontMap, "register_font", forbidden)
    monkeypatch.setattr(FontMap, "use_fontconfig", forbidden)
    class Result:
        error = "not rendered"
        def send(self, value):
            self.error = value
        def close(self):
            pass
    text = '<svg xmlns="http://www.w3.org/2000/svg" width="80" height="20"><text y="15" font-family="/tmp/secret.ttf">Hello</text></svg>'
    result = Result()
    _render(text.encode(), str(tmp_path / "out.png"), ".png", 95, 95, result)
    assert result.error is None
    with Image.open(tmp_path / "out.png") as image:
        assert image.size == (80, 20)


def test_svg_cancellation_stops_a_running_renderer(tmp_path, monkeypatch):
    import multiprocessing
    import time
    from types import SimpleNamespace
    from PySide6.QtWidgets import QApplication
    from cove_converter.engines.svg import SvgWorker
    app = QApplication.instance() or QApplication([])
    context = multiprocessing.get_context("spawn")
    processes = []
    def tracked_process(**kwargs):
        process = context.Process(**kwargs)
        processes.append(process)
        return process
    monkeypatch.setattr(multiprocessing, "get_context", lambda method: SimpleNamespace(
        Process=tracked_process, Pipe=context.Pipe,
    ))
    source = tmp_path / "source.svg"
    source.write_text(SVG)
    output = tmp_path / "result.png"
    worker = SvgWorker(source, output)
    worker.start()
    try:
        deadline = time.monotonic() + 5
        while not processes or processes[0].pid is None:
            assert time.monotonic() < deadline
            time.sleep(.001)
        worker.cancel()
        assert worker.wait(5000)
        app.processEvents()
        assert not output.exists()
        assert not list(tmp_path.glob(".*cove*"))
    finally:
        worker.cancel()
        assert worker.wait(5000)


def test_svg_rejects_inherited_dasharray_memory_amplification():
    from cove_converter.engines.svg import _validated_svg
    # Challenger regression: ~208 KB expands into 30 million inherited values.
    dasharray = "1 " * 100_000
    data = ('<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">'
            f'<g stroke="black" stroke-dasharray="{dasharray}">'
            + '<rect width="1" height="1"/>' * 300 + '</g></svg>').encode()
    assert len(data) < 220_000
    with pytest.raises(ValueError, match="SVG.*complexity"):
        _validated_svg(data)


@pytest.mark.parametrize("body", [
    '<g stroke-dasharray="' + '1 ' * 3000 + '">' + '<rect width="1" height="1"/>' * 100 + '</g>',
    '<polyline points="' + '0,0 ' * 3000 + '"/>',
    '<path d="M0 0 ' + 'L1 1 ' * 7000 + '"/>',
    '<g style="stroke-dasharray:' + '1 ' * 100_000 + '"><rect width="1" height="1"/></g>',
], ids=["inherited-budget", "points-numbers", "path-length", "inline-style"])
def test_svg_rejects_attribute_and_inherited_complexity(body):
    from cove_converter.engines.svg import _validated_svg
    data = f'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">{body}</svg>'.encode()
    with pytest.raises(ValueError, match="SVG.*complexity"):
        _validated_svg(data)


def test_svg_low_child_memory_budget_fails_cleanly(tmp_path):
    if os.name == "posix":
        import resource
        parent_limits = (resource.getrlimit(resource.RLIMIT_AS), resource.getrlimit(resource.RLIMIT_DATA))
    # A real spawned process gets too little headroom for renderer imports.
    output, errors = convert(tmp_path, SVG, memory_limit_bytes=32 * 1024 * 1024)
    if os.name == "posix":
        assert errors and "SVG" in errors[0] and "memory" in errors[0].lower()
        assert not output.exists()
        assert (resource.getrlimit(resource.RLIMIT_AS), resource.getrlimit(resource.RLIMIT_DATA)) == parent_limits
    else:
        # Windows has no resource.setrlimit; complexity/time limits still apply.
        assert not errors
        assert output.exists()


def test_svg_defs_clipping_is_applied_to_pixels(tmp_path):
    text = ('<svg xmlns="http://www.w3.org/2000/svg" width="24" height="16">'
            '<defs><clipPath id="clip"><rect width="8" height="16"/></clipPath></defs>'
            '<rect width="24" height="16" fill="red" clip-path="url(#clip)"/></svg>')
    output, errors = convert(tmp_path, text)
    assert not errors
    with Image.open(output) as image:
        rgba = image.convert("RGBA")
        assert rgba.getpixel((4, 8)) == (255, 0, 0, 255)
        assert rgba.getpixel((20, 8))[3] == 0


def test_svg_defs_gradient_is_applied_to_pixels(tmp_path):
    text = ('<svg xmlns="http://www.w3.org/2000/svg" width="80" height="16">'
            '<defs><linearGradient id="gradient"><stop offset="0" stop-color="red"/>'
            '<stop offset="1" stop-color="blue"/></linearGradient></defs>'
            '<rect width="80" height="16" fill="url(#gradient)"/></svg>')
    output, errors = convert(tmp_path, text)
    assert not errors
    with Image.open(output) as image:
        rgba = image.convert("RGBA")
        left, right = rgba.getpixel((8, 8)), rgba.getpixel((72, 8))
        assert left[3] == right[3] == 255
        assert left[0] > left[2] + 100
        assert right[2] > right[0] + 100

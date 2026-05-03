"""Regression: read-only image input must convert to PDF cleanly.

Reported: ``Permission denied`` on the worker-owned temp output path when
converting a read-only ``.jpeg`` from an external mount. The temp file is
created via ``tempfile.mkstemp`` (mode 0o600) and must remain writable for
the current user throughout ``_convert``; nothing in the lifecycle is
allowed to copy the source mode onto the temp before save.
"""
from __future__ import annotations

import hashlib
import os
import stat
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tempfile

from PIL import Image

from cove_converter.engines.pdf import PdfWorker
from cove_converter.settings import ConversionSettings


def _sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


@unittest.skipIf(sys.platform == "win32", "POSIX permission semantics only")
class ReadOnlySourceImageToPdf(unittest.TestCase):
    def _convert_readonly(self, ext: str, builder) -> None:
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / f"src{ext}"
            builder(src)
            os.chmod(src, 0o444)
            src_hash = _sha256(src)
            src_mode = stat.S_IMODE(src.stat().st_mode)

            dst = Path(td) / "out.pdf"
            worker = PdfWorker(src, dst, settings=ConversionSettings())
            worker.run()

            self.assertTrue(dst.exists(), "output PDF was not produced")
            self.assertGreater(dst.stat().st_size, 0)
            self.assertEqual(dst.read_bytes()[:5], b"%PDF-")

            # Source must be untouched: hash and read-only mode preserved.
            self.assertEqual(_sha256(src), src_hash)
            self.assertEqual(stat.S_IMODE(src.stat().st_mode), src_mode)
            self.assertEqual(src_mode, 0o444)

    def test_readonly_jpeg(self) -> None:
        def build(p: Path) -> None:
            Image.new("RGB", (40, 30), (10, 20, 30)).save(p, "JPEG")

        self._convert_readonly(".jpeg", build)

    def test_readonly_png(self) -> None:
        def build(p: Path) -> None:
            Image.new("RGB", (40, 30), (200, 50, 50)).save(p, "PNG")

        self._convert_readonly(".png", build)


if __name__ == "__main__":
    unittest.main()

"""Sanity tests for the smoke-conversion matrix builder.

These are intentionally cheap: we only verify the matrix can be built and
that every advertised category contributes at least one route. Actual
conversion correctness is exercised by ``scripts/smoke_conversions.py``,
which does shell out to ffmpeg/pandoc and is too heavy for the unit-test
suite."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from scripts import smoke_conversions as smoke  # noqa: E402
from cove_converter import routing  # noqa: E402


class MatrixBuilder(unittest.TestCase):
    def setUp(self) -> None:
        self.matrix = smoke.build_matrix()

    def test_matrix_nonempty(self) -> None:
        self.assertGreater(len(self.matrix), 0)

    def test_every_route_has_engine(self) -> None:
        for r in self.matrix:
            self.assertIn(r.engine, smoke.WORKER_REGISTRY,
                          f"route {r} routed to unknown engine {r.engine!r}")

    def test_every_route_input_is_supported(self) -> None:
        for r in self.matrix:
            self.assertIn(r.in_ext, routing.SUPPORTED_FORMATS,
                          f"route {r} uses unsupported input {r.in_ext}")

    def test_every_advertised_engine_appears(self) -> None:
        engines = {r.engine for r in self.matrix}
        # All engines except possibly experimental ones must contribute.
        for required in ("Pillow", "FFmpeg", "Pandoc", "Pdf",
                         "Subtitle", "Spreadsheet", "Archive", "Data"):
            self.assertIn(required, engines, f"engine missing from matrix: {required}")

    def test_pdf_pair_present(self) -> None:
        # The original failure motivating this harness was TXT -> PDF; pin
        # both directions so the matrix can never silently lose them.
        pairs = {(r.in_ext, r.out_ext) for r in self.matrix}
        self.assertIn((".txt", ".pdf"), pairs)
        self.assertIn((".pdf", ".txt"), pairs)

    def test_compound_targz_present(self) -> None:
        pairs = {(r.in_ext, r.out_ext) for r in self.matrix}
        self.assertIn((".tar.gz", ".zip"), pairs)
        self.assertIn((".zip", ".tgz"), pairs)


class SampleGenerators(unittest.TestCase):
    """Each *input* extension referenced by the matrix should either have a
    sample generator or be deferred to pandoc-driven generation. Catches the
    case where a new format gets added to routing without a sample for it."""

    def test_every_input_has_sample_path(self) -> None:
        unknown = []
        for in_ext in {r.in_ext for r in smoke.build_matrix()}:
            if in_ext not in smoke.SAMPLE_GENERATORS:
                unknown.append(in_ext)
        self.assertFalse(unknown, f"missing sample generators for: {unknown}")


if __name__ == "__main__":
    unittest.main()

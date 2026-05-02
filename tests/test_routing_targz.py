"""Regression tests for .tar.gz routing (Codex review #2).

Codex flagged that ``.tar.gz`` files were being dropped on the floor: the
archive worker accepted ``.gz`` internally but the routing table only
exposed ``.tgz``, and ``Path.suffix`` of ``foo.tar.gz`` is ``.gz`` (which
isn't a supported format). These tests pin the compound-suffix behaviour
so that fix doesn't silently regress."""
from __future__ import annotations

import os
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Headless Qt — file_row imports trigger PySide6 transitively only via
# main_window, but keep this for parity with sibling tests.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from cove_converter import routing  # noqa: E402
from cove_converter.engines import archives  # noqa: E402
from cove_converter.ui.file_row import FileRow  # noqa: E402


class EffectiveSuffix(unittest.TestCase):
    def test_tar_gz_recognised(self) -> None:
        self.assertEqual(routing.effective_suffix(Path("foo.tar.gz")), ".tar.gz")

    def test_tar_gz_case_insensitive(self) -> None:
        self.assertEqual(routing.effective_suffix(Path("FOO.TAR.GZ")), ".tar.gz")

    def test_tgz_unchanged(self) -> None:
        self.assertEqual(routing.effective_suffix(Path("foo.tgz")), ".tgz")

    def test_plain_gz_returns_gz(self) -> None:
        # ``effective_suffix`` reports the actual suffix; routing then
        # rejects ``.gz`` because it's not a SUPPORTED_FORMATS key.
        self.assertEqual(routing.effective_suffix(Path("foo.gz")), ".gz")

    def test_single_suffix_paths_unchanged(self) -> None:
        self.assertEqual(routing.effective_suffix(Path("foo.zip")), ".zip")
        self.assertEqual(routing.effective_suffix(Path("clip.mp4")), ".mp4")


class EffectiveStem(unittest.TestCase):
    def test_tar_gz_stem_strips_compound(self) -> None:
        self.assertEqual(routing.effective_stem(Path("foo.tar.gz")), "foo")

    def test_tar_gz_stem_with_parent(self) -> None:
        self.assertEqual(routing.effective_stem(Path("/a/b/foo.tar.gz")), "foo")

    def test_single_suffix_stem_unchanged(self) -> None:
        self.assertEqual(routing.effective_stem(Path("foo.tgz")), "foo")
        self.assertEqual(routing.effective_stem(Path("clip.mp4")), "clip")


class RoutingExposure(unittest.TestCase):
    def test_tar_gz_is_supported(self) -> None:
        self.assertIn(".tar.gz", routing.SUPPORTED_FORMATS)
        info = routing.info_for(".tar.gz")
        self.assertIsNotNone(info)
        self.assertEqual(info.engine, "Archive")

    def test_tgz_still_routes_to_archive(self) -> None:
        self.assertEqual(routing.info_for(".tgz").engine, "Archive")
        self.assertIn(".zip", routing.targets_for(".tgz"))

    def test_plain_gz_not_advertised(self) -> None:
        # ``.gz`` standalone must not be exposed as a tar-archive input.
        self.assertNotIn(".gz", routing.SUPPORTED_FORMATS)
        self.assertIsNone(routing.info_for(".gz"))

    def test_engine_for_tar_gz_endpoints(self) -> None:
        self.assertEqual(routing.engine_for(".tar.gz", ".zip"), "Archive")
        self.assertEqual(routing.engine_for(".zip", ".tar.gz"), "Archive")


class OutputResolution(unittest.TestCase):
    def test_tar_gz_input_zip_target(self) -> None:
        row = FileRow(path=Path("/tmp/sample.tar.gz"), target_ext=".zip")
        self.assertEqual(row.resolve_output(None), Path("/tmp/sample.zip"))

    def test_tar_gz_input_with_dest_dir(self) -> None:
        row = FileRow(path=Path("/tmp/sample.tar.gz"), target_ext=".tar")
        self.assertEqual(row.resolve_output(Path("/out")), Path("/out/sample.tar"))

    def test_tgz_input_unchanged(self) -> None:
        row = FileRow(path=Path("/tmp/data.tgz"), target_ext=".zip")
        self.assertEqual(row.resolve_output(None), Path("/tmp/data.zip"))

    def test_compound_target_extension(self) -> None:
        row = FileRow(path=Path("/tmp/data.zip"), target_ext=".tar.gz")
        self.assertEqual(row.resolve_output(None), Path("/tmp/data.tar.gz"))

    def test_unrelated_single_suffix_unchanged(self) -> None:
        row = FileRow(path=Path("/tmp/clip.mp4"), target_ext=".webm")
        self.assertEqual(row.resolve_output(None), Path("/tmp/clip.webm"))


class WorkerHandlesTarGz(unittest.TestCase):
    """End-to-end-ish: routing dispatches a real ``.tar.gz`` file through
    the archive worker's extract → repack pipeline. Confirms the pieces
    line up across modules, not just within routing.py."""

    def test_tar_gz_round_trip_to_zip(self) -> None:
        import time
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            src = tdp / "sample.tar.gz"
            with tarfile.open(src, "w:gz") as tf:
                import io
                payload = b"hello"
                info = tarfile.TarInfo(name="hello.txt")
                info.size = len(payload)
                # ZIP rejects timestamps before 1980 — give the entry a
                # real mtime so the repack step doesn't choke on it.
                info.mtime = int(time.time())
                tf.addfile(info, io.BytesIO(payload))

            # Routing layer claims the file.
            self.assertEqual(routing.effective_suffix(src), ".tar.gz")
            self.assertEqual(routing.engine_for(".tar.gz", ".zip"), "Archive")

            # Worker accepts the .gz suffix internally and extracts the
            # tar contents via the gzip mode.
            row = FileRow(path=src, target_ext=".zip")
            out = row.resolve_output(None)
            self.assertEqual(out, tdp / "sample.zip")

            # Drive the worker without spawning a QThread.
            from unittest import mock

            from cove_converter.engines.archives import ArchiveWorker
            w = ArchiveWorker.__new__(ArchiveWorker)
            w.input_path = src
            w.output_path = out
            w.progress = mock.Mock()
            w._convert()

            self.assertTrue(out.exists())
            import zipfile
            with zipfile.ZipFile(out, "r") as zf:
                self.assertIn("hello.txt", zf.namelist())


if __name__ == "__main__":
    unittest.main()

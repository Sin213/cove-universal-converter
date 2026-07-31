"""Regression tests for compound compressed-tar routing.

These tests pin both the long compound extensions and their short aliases so
they cannot silently regress to their final suffix (for example, ``.bz2``).
"""

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
from cove_converter.ui.file_row import FileRow, unique_path  # noqa: E402

COMPRESSED_TAR_EXTENSIONS = (
    ".tgz",
    ".tar.gz",
    ".tbz2",
    ".tar.bz2",
    ".txz",
    ".tar.xz",
)
COMPOUND_TAR_EXTENSIONS = (".tar.gz", ".tar.bz2", ".tar.xz")


class EffectiveSuffix(unittest.TestCase):
    def test_compound_extensions_recognised(self) -> None:
        for extension in COMPOUND_TAR_EXTENSIONS:
            with self.subTest(extension=extension):
                self.assertEqual(
                    routing.effective_suffix(Path(f"foo{extension}")),
                    extension,
                )

    def test_compound_extensions_case_insensitive(self) -> None:
        for extension in COMPOUND_TAR_EXTENSIONS:
            with self.subTest(extension=extension):
                self.assertEqual(
                    routing.effective_suffix(Path(f"FOO{extension.upper()}")),
                    extension,
                )

    def test_aliases_unchanged(self) -> None:
        for extension in (".tgz", ".tbz2", ".txz"):
            with self.subTest(extension=extension):
                self.assertEqual(
                    routing.effective_suffix(Path(f"foo{extension}")),
                    extension,
                )

    def test_plain_compression_suffixes_return_their_suffix(self) -> None:
        for extension in (".gz", ".bz2", ".xz"):
            with self.subTest(extension=extension):
                self.assertEqual(
                    routing.effective_suffix(Path(f"foo{extension}")),
                    extension,
                )

    def test_single_suffix_paths_unchanged(self) -> None:
        self.assertEqual(routing.effective_suffix(Path("foo.zip")), ".zip")
        self.assertEqual(routing.effective_suffix(Path("clip.mp4")), ".mp4")


class EffectiveStem(unittest.TestCase):
    def test_compound_stem_strips_full_extension(self) -> None:
        for extension in COMPOUND_TAR_EXTENSIONS:
            with self.subTest(extension=extension):
                self.assertEqual(
                    routing.effective_stem(Path(f"foo{extension}")),
                    "foo",
                )

    def test_compound_stem_with_parent(self) -> None:
        for extension in COMPOUND_TAR_EXTENSIONS:
            with self.subTest(extension=extension):
                self.assertEqual(
                    routing.effective_stem(Path(f"/a/b/foo{extension}")),
                    "foo",
                )

    def test_single_suffix_stem_unchanged(self) -> None:
        self.assertEqual(routing.effective_stem(Path("foo.tgz")), "foo")
        self.assertEqual(routing.effective_stem(Path("clip.mp4")), "clip")


class RoutingExposure(unittest.TestCase):
    def test_compressed_tar_extensions_are_supported(self) -> None:
        for extension in COMPRESSED_TAR_EXTENSIONS:
            with self.subTest(extension=extension):
                self.assertIn(extension, routing.SUPPORTED_FORMATS)
                info = routing.info_for(extension)
                self.assertIsNotNone(info)
                self.assertEqual(info.engine, "Archive")
                self.assertIn(".zip", routing.targets_for(extension))

    def test_plain_compression_suffixes_not_advertised(self) -> None:
        for extension in (".gz", ".bz2", ".xz"):
            with self.subTest(extension=extension):
                self.assertNotIn(extension, routing.SUPPORTED_FORMATS)
                self.assertIsNone(routing.info_for(extension))

    def test_engine_for_compressed_tar_endpoints(self) -> None:
        for extension in COMPRESSED_TAR_EXTENSIONS:
            with self.subTest(extension=extension):
                self.assertEqual(
                    routing.engine_for(extension, ".zip"),
                    "Archive",
                )
                self.assertEqual(
                    routing.engine_for(".zip", extension),
                    "Archive",
                )


class OutputResolution(unittest.TestCase):
    def test_unique_path_preserves_compound_suffix(self) -> None:
        for extension in COMPOUND_TAR_EXTENSIONS:
            with self.subTest(extension=extension), tempfile.TemporaryDirectory() as td:
                path = Path(td) / f"foo{extension}"
                path.touch()
                self.assertEqual(
                    unique_path(path),
                    Path(td) / f"foo (1){extension}",
                )

    def test_compressed_tar_input_zip_target(self) -> None:
        for extension in COMPRESSED_TAR_EXTENSIONS:
            with self.subTest(extension=extension):
                row = FileRow(
                    path=Path(f"/tmp/sample{extension}"),
                    target_ext=".zip",
                )
                self.assertEqual(
                    row.resolve_output(None),
                    Path("/tmp/sample.zip"),
                )

    def test_tar_gz_input_with_dest_dir(self) -> None:
        row = FileRow(path=Path("/tmp/sample.tar.gz"), target_ext=".tar")
        self.assertEqual(row.resolve_output(Path("/out")), Path("/out/sample.tar"))

    def test_tgz_input_unchanged(self) -> None:
        row = FileRow(path=Path("/tmp/data.tgz"), target_ext=".zip")
        self.assertEqual(row.resolve_output(None), Path("/tmp/data.zip"))

    def test_compound_target_extensions(self) -> None:
        for extension in COMPOUND_TAR_EXTENSIONS:
            with self.subTest(extension=extension):
                row = FileRow(
                    path=Path("/tmp/data.zip"),
                    target_ext=extension,
                )
                self.assertEqual(
                    row.resolve_output(None),
                    Path(f"/tmp/data{extension}"),
                )

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

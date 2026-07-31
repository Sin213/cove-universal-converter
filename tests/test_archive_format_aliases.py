from __future__ import annotations

import os
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from cove_converter.engines import archives


class ArchiveFormatAliasTests(unittest.TestCase):
    @staticmethod
    def _make_source(root: Path) -> Path:
        source = root / "source"
        nested = source / "nested"
        nested.mkdir(parents=True)
        (nested / "hello.txt").write_text("hello archive", encoding="utf-8")
        return source

    def test_compound_extension_and_tar_modes(self) -> None:
        self.assertEqual(archives._archive_ext(Path("bundle.tar.bz2")), ".tar.bz2")
        self.assertEqual(archives._archive_ext(Path("bundle.tar.xz")), ".tar.xz")
        self.assertEqual(archives._tar_mode(".tbz2", write=False), "r:bz2")
        self.assertEqual(archives._tar_mode(".tar.bz2", write=True), "w:bz2")
        self.assertEqual(archives._tar_mode(".txz", write=False), "r:xz")
        self.assertEqual(archives._tar_mode(".tar.xz", write=True), "w:xz")

    def test_pack_and_extract_supported_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_source(root)

            for extension in (
                ".tar.bz2",
                ".tbz2",
                ".tar.xz",
                ".txz",
                ".cbz",
                ".cbt",
            ):
                with self.subTest(extension=extension):
                    archive = root / f"bundle{extension}"
                    extracted = root / f"extract-{extension.replace('.', '-')}"
                    extracted.mkdir()

                    archives._pack_from(source, archive)
                    if extension == ".cbz":
                        self.assertTrue(zipfile.is_zipfile(archive))
                    else:
                        self.assertTrue(tarfile.is_tarfile(archive))

                    archives._extract_to(archive, extracted)
                    self.assertEqual(
                        (extracted / "nested" / "hello.txt").read_text(
                            encoding="utf-8"
                        ),
                        "hello archive",
                    )

    def test_worker_uses_final_compound_output_extension(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._make_source(root)
            input_archive = root / "input.tar"
            output_archive = root / "output.tar.bz2"
            archives._pack_from(source, input_archive)

            failures: list[str] = []
            worker = archives.ArchiveWorker(input_archive, output_archive)
            worker.failed.connect(failures.append)
            worker.run()

            self.assertEqual(failures, [])
            self.assertTrue(output_archive.exists())
            with tarfile.open(output_archive, "r:bz2") as tf:
                member = tf.extractfile("nested/hello.txt")
                self.assertIsNotNone(member)
                assert member is not None
                self.assertEqual(member.read(), b"hello archive")


if __name__ == "__main__":
    unittest.main()

"""Regression tests for bounded archive extraction (Codex review #1).

The limits in ``cove_converter.engines.archives`` cap how much data a malicious
or misbehaving archive can write to disk during conversion. We exercise each
guard with tiny synthetic archives plus monkey-patched limit constants — that
way the tests stay fast and don't actually need to fill the disk to prove the
guard fires."""
from __future__ import annotations

import os
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Headless Qt so importing engines.base (QThread/Signal) doesn't try to
# open a display on CI.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from cove_converter.engines import archives  # noqa: E402


class ZipLimits(unittest.TestCase):
    def _make_zip(self, path: Path, entries: int, payload: bytes = b"x") -> None:
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for i in range(entries):
                zf.writestr(f"f{i}.txt", payload)

    def test_too_many_members_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            src = tdp / "many.zip"
            dst = tdp / "out"
            dst.mkdir()
            self._make_zip(src, entries=12)
            with mock.patch.object(archives, "MAX_ARCHIVE_MEMBERS", 10):
                with zipfile.ZipFile(src, "r") as zf:
                    with self.assertRaises(archives.ArchiveTooLargeError):
                        archives._safe_zip_extract(zf, dst)

    def test_total_uncompressed_size_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            src = tdp / "big.zip"
            dst = tdp / "out"
            dst.mkdir()
            # 4 entries × 100 bytes = 400 declared bytes; cap at 200.
            self._make_zip(src, entries=4, payload=b"y" * 100)
            with mock.patch.object(archives, "MAX_EXTRACTED_BYTES", 200):
                with zipfile.ZipFile(src, "r") as zf:
                    with self.assertRaises(archives.ArchiveTooLargeError):
                        archives._safe_zip_extract(zf, dst)

    def test_per_entry_size_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            src = tdp / "fat.zip"
            dst = tdp / "out"
            dst.mkdir()
            self._make_zip(src, entries=1, payload=b"z" * 500)
            with mock.patch.object(archives, "MAX_SINGLE_ENTRY_BYTES", 100):
                with zipfile.ZipFile(src, "r") as zf:
                    with self.assertRaises(archives.ArchiveTooLargeError):
                        archives._safe_zip_extract(zf, dst)

    def test_normal_zip_extracts(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            src = tdp / "ok.zip"
            dst = tdp / "out"
            dst.mkdir()
            self._make_zip(src, entries=3, payload=b"hello")
            with zipfile.ZipFile(src, "r") as zf:
                archives._safe_zip_extract(zf, dst)
            self.assertEqual(sorted(p.name for p in dst.iterdir()),
                             ["f0.txt", "f1.txt", "f2.txt"])


class TarLimits(unittest.TestCase):
    def _make_tar(self, path: Path, entries: int, payload: bytes = b"x") -> None:
        with tarfile.open(path, "w") as tf:
            for i in range(entries):
                data = payload
                info = tarfile.TarInfo(name=f"f{i}.txt")
                info.size = len(data)
                import io
                tf.addfile(info, io.BytesIO(data))

    def test_too_many_members_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            src = tdp / "many.tar"
            dst = tdp / "out"
            dst.mkdir()
            self._make_tar(src, entries=12)
            with mock.patch.object(archives, "MAX_ARCHIVE_MEMBERS", 10):
                with tarfile.open(src, "r") as tf:
                    with self.assertRaises(archives.ArchiveTooLargeError):
                        archives._safe_tar_extract(tf, dst)

    def test_total_regular_file_size_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            src = tdp / "big.tar"
            dst = tdp / "out"
            dst.mkdir()
            self._make_tar(src, entries=4, payload=b"y" * 100)
            with mock.patch.object(archives, "MAX_EXTRACTED_BYTES", 200):
                with tarfile.open(src, "r") as tf:
                    with self.assertRaises(archives.ArchiveTooLargeError):
                        archives._safe_tar_extract(tf, dst)

    def test_per_entry_size_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            src = tdp / "fat.tar"
            dst = tdp / "out"
            dst.mkdir()
            self._make_tar(src, entries=1, payload=b"z" * 500)
            with mock.patch.object(archives, "MAX_SINGLE_ENTRY_BYTES", 100):
                with tarfile.open(src, "r") as tf:
                    with self.assertRaises(archives.ArchiveTooLargeError):
                        archives._safe_tar_extract(tf, dst)

    def test_normal_tar_extracts(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            src = tdp / "ok.tar"
            dst = tdp / "out"
            dst.mkdir()
            self._make_tar(src, entries=3, payload=b"hello")
            with tarfile.open(src, "r") as tf:
                archives._safe_tar_extract(tf, dst)
            self.assertEqual(sorted(p.name for p in dst.iterdir()),
                             ["f0.txt", "f1.txt", "f2.txt"])


class TarLinkRejection(unittest.TestCase):
    """Tar symlinks and hardlinks are rejected outright. Otherwise an
    archive could pass extraction byte limits with one large file plus
    many links to it, then be amplified during ZIP repack (which would
    dereference the link and write the bytes for every link)."""

    def _make_tar_with_link(
        self,
        path: Path,
        link_kind: str,
        payload: bytes = b"hello",
    ) -> None:
        import io
        with tarfile.open(path, "w") as tf:
            data = payload
            real = tarfile.TarInfo(name="real.bin")
            real.size = len(data)
            tf.addfile(real, io.BytesIO(data))
            link = tarfile.TarInfo(name="alias.bin")
            link.size = 0
            if link_kind == "symlink":
                link.type = tarfile.SYMTYPE
            elif link_kind == "hardlink":
                link.type = tarfile.LNKTYPE
            else:  # pragma: no cover - test programming error
                raise AssertionError(link_kind)
            link.linkname = "real.bin"
            tf.addfile(link)

    def test_tar_symlink_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            src = tdp / "sym.tar"
            dst = tdp / "out"
            dst.mkdir()
            self._make_tar_with_link(src, "symlink")
            with tarfile.open(src, "r") as tf:
                with self.assertRaises(RuntimeError):
                    archives._safe_tar_extract(tf, dst)

    def test_tar_hardlink_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            src = tdp / "hard.tar"
            dst = tdp / "out"
            dst.mkdir()
            self._make_tar_with_link(src, "hardlink")
            with tarfile.open(src, "r") as tf:
                with self.assertRaises(RuntimeError):
                    archives._safe_tar_extract(tf, dst)


class ZipPackSymlinkRejection(unittest.TestCase):
    """If a symlink survives into the extracted tree, ZIP repacking must
    refuse to dereference it. ``Path.is_file()`` follows links, so without
    an explicit ``is_symlink()`` check a single symlink could be inlined
    as the target's bytes — and many links could amplify the output."""

    def test_zip_pack_refuses_filesystem_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            src = tdp / "tree"
            src.mkdir()
            target = src / "real.bin"
            target.write_bytes(b"payload")
            link = src / "alias.bin"
            try:
                link.symlink_to(target)
            except (OSError, NotImplementedError):
                self.skipTest("filesystem does not support symlinks")
            dst = tdp / "out.zip"
            with self.assertRaises(RuntimeError):
                archives._pack_from(src, dst)

    def test_tar_pack_refuses_filesystem_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            src = tdp / "tree"
            src.mkdir()
            target = src / "real.bin"
            target.write_bytes(b"payload")
            link = src / "alias.bin"
            try:
                link.symlink_to(target)
            except (OSError, NotImplementedError):
                self.skipTest("filesystem does not support symlinks")
            dst = tdp / "out.tar"
            with self.assertRaises(RuntimeError):
                archives._pack_from(src, dst)


class RepackOutputCap(unittest.TestCase):
    """The repack stage enforces the same byte/member caps as extraction.
    Even though ``src`` was bounded, a logic bug here mustn't be able to
    fabricate an oversized output."""

    def test_repack_total_bytes_capped(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            src = tdp / "tree"
            src.mkdir()
            for i in range(4):
                (src / f"f{i}.bin").write_bytes(b"y" * 100)
            dst = tdp / "out.zip"
            with mock.patch.object(archives, "MAX_EXTRACTED_BYTES", 200):
                with self.assertRaises(archives.ArchiveTooLargeError):
                    archives._pack_from(src, dst)

    def test_repack_member_count_capped(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            src = tdp / "tree"
            src.mkdir()
            for i in range(12):
                (src / f"f{i}.bin").write_bytes(b"x")
            dst = tdp / "out.zip"
            with mock.patch.object(archives, "MAX_ARCHIVE_MEMBERS", 10):
                with self.assertRaises(archives.ArchiveTooLargeError):
                    archives._pack_from(src, dst)

    def test_repack_normal_tree_succeeds(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            src = tdp / "tree"
            src.mkdir()
            (src / "a.txt").write_text("alpha")
            (src / "b.txt").write_text("beta")
            (src / "sub").mkdir()
            (src / "sub" / "c.txt").write_text("gamma")
            dst = tdp / "out.zip"
            archives._pack_from(src, dst)
            with zipfile.ZipFile(dst, "r") as zf:
                names = sorted(zf.namelist())
            self.assertIn("a.txt", names)
            self.assertIn("b.txt", names)
            self.assertIn("sub/c.txt", names)


class DuplicateMemberRejection(unittest.TestCase):
    """ZIP/TAR allow duplicate member names; extracting them to a filesystem
    temp dir would silently overwrite earlier entries before repack. Validation
    must reject the archive up front."""

    def test_zip_duplicate_member_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            src = tdp / "dup.zip"
            dst = tdp / "out"
            dst.mkdir()
            with zipfile.ZipFile(src, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("data.txt", b"first")
                zf.writestr("data.txt", b"second")
            with zipfile.ZipFile(src, "r") as zf:
                with self.assertRaises(RuntimeError):
                    archives._safe_zip_extract(zf, dst)

    def test_zip_normalized_duplicate_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            src = tdp / "norm.zip"
            dst = tdp / "out"
            dst.mkdir()
            with zipfile.ZipFile(src, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("foo.txt", b"a")
                zf.writestr("./foo.txt", b"b")
            with zipfile.ZipFile(src, "r") as zf:
                with self.assertRaises(RuntimeError):
                    archives._safe_zip_extract(zf, dst)

    def test_zip_dir_file_collision_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            src = tdp / "coll.zip"
            dst = tdp / "out"
            dst.mkdir()
            with zipfile.ZipFile(src, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("foo/", b"")
                zf.writestr("foo", b"bytes")
            with zipfile.ZipFile(src, "r") as zf:
                with self.assertRaises(RuntimeError):
                    archives._safe_zip_extract(zf, dst)

    def test_tar_duplicate_member_rejected(self) -> None:
        import io
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            src = tdp / "dup.tar"
            dst = tdp / "out"
            dst.mkdir()
            with tarfile.open(src, "w") as tf:
                for payload in (b"first", b"second"):
                    info = tarfile.TarInfo(name="data.txt")
                    info.size = len(payload)
                    tf.addfile(info, io.BytesIO(payload))
            with tarfile.open(src, "r") as tf:
                with self.assertRaises(RuntimeError):
                    archives._safe_tar_extract(tf, dst)

    def test_tar_normalized_duplicate_rejected(self) -> None:
        import io
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            src = tdp / "norm.tar"
            dst = tdp / "out"
            dst.mkdir()
            with tarfile.open(src, "w") as tf:
                for name, payload in (("foo.txt", b"a"), ("./foo.txt", b"b")):
                    info = tarfile.TarInfo(name=name)
                    info.size = len(payload)
                    tf.addfile(info, io.BytesIO(payload))
            with tarfile.open(src, "r") as tf:
                with self.assertRaises(RuntimeError):
                    archives._safe_tar_extract(tf, dst)


class TarBackslashRejection(unittest.TestCase):
    """TAR member names containing ``\\`` must be rejected. Duplicate
    detection normalizes only POSIX paths, so on Windows ``a/b.txt`` and
    ``a\\b.txt`` resolve to the same on-disk path and one entry would
    silently overwrite the other before repacking."""

    def _make_tar_with_name(self, path: Path, name: str, payload: bytes = b"x") -> None:
        import io
        with tarfile.open(path, "w") as tf:
            info = tarfile.TarInfo(name=name)
            info.size = len(payload)
            tf.addfile(info, io.BytesIO(payload))

    def test_tar_backslash_path_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            src = tdp / "back.tar"
            dst = tdp / "out"
            dst.mkdir()
            self._make_tar_with_name(src, "a\\b.txt")
            with tarfile.open(src, "r") as tf:
                with self.assertRaises(RuntimeError):
                    archives._safe_tar_extract(tf, dst)

    def test_tar_mixed_separator_collision_rejected(self) -> None:
        import io
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            src = tdp / "mix.tar"
            dst = tdp / "out"
            dst.mkdir()
            with tarfile.open(src, "w") as tf:
                for name in ("a/b.txt", "a\\b.txt"):
                    info = tarfile.TarInfo(name=name)
                    info.size = 1
                    tf.addfile(info, io.BytesIO(b"x"))
            # Validation must reject the archive before any extraction.
            with tarfile.open(src, "r") as tf:
                with self.assertRaises(RuntimeError):
                    archives._safe_tar_extract(tf, dst)
            # Confirm nothing was written to dst.
            self.assertEqual(list(dst.iterdir()), [])

    def test_tar_normal_posix_paths_still_extract(self) -> None:
        import io
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            src = tdp / "ok.tar"
            dst = tdp / "out"
            dst.mkdir()
            with tarfile.open(src, "w") as tf:
                for name in ("dir/a.txt", "dir/sub/b.txt"):
                    info = tarfile.TarInfo(name=name)
                    info.size = 1
                    tf.addfile(info, io.BytesIO(b"x"))
            with tarfile.open(src, "r") as tf:
                archives._safe_tar_extract(tf, dst)
            self.assertTrue((dst / "dir" / "a.txt").is_file())
            self.assertTrue((dst / "dir" / "sub" / "b.txt").is_file())


class Pre1980TimestampRepack(unittest.TestCase):
    """TAR archives can legally carry mtimes before 1980 (epoch 0 is common in
    reproducible builds). Python's ZIP writer rejects those by default; the
    repack stage must clamp them to 1980-01-01 instead of failing the whole
    conversion."""

    def test_tar_to_zip_pre1980_file_mtime(self) -> None:
        import io
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            src_tar = tdp / "epoch.tar"
            payload = b"reproducible"
            with tarfile.open(src_tar, "w") as tf:
                info = tarfile.TarInfo(name="hello.txt")
                info.size = len(payload)
                info.mtime = 0  # 1970-01-01, well before the ZIP 1980 floor
                tf.addfile(info, io.BytesIO(payload))

            extracted = tdp / "extracted"
            extracted.mkdir()
            archives._extract_to(src_tar, extracted)
            # Sanity: extraction propagated the pre-1980 mtime to the FS.
            self.assertLess((extracted / "hello.txt").stat().st_mtime, 315532800)

            dst_zip = tdp / "out.zip"
            archives._pack_from(extracted, dst_zip)

            with zipfile.ZipFile(dst_zip, "r") as zf:
                names = zf.namelist()
                self.assertIn("hello.txt", names)
                info = zf.getinfo("hello.txt")
                # Clamped to 1980-01-01 00:00:00 or later.
                self.assertGreaterEqual(info.date_time, (1980, 1, 1, 0, 0, 0))
                self.assertEqual(zf.read("hello.txt"), payload)

    def test_tar_to_zip_pre1980_empty_dir_preserved(self) -> None:
        import io
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            src_tar = tdp / "epoch_dir.tar"
            with tarfile.open(src_tar, "w") as tf:
                d = tarfile.TarInfo(name="emptydir")
                d.type = tarfile.DIRTYPE
                d.mtime = 0
                tf.addfile(d)
                payload = b"x"
                f = tarfile.TarInfo(name="emptydir/keep.txt")
                f.size = len(payload)
                f.mtime = 0
                tf.addfile(f, io.BytesIO(payload))

            extracted = tdp / "extracted"
            extracted.mkdir()
            archives._extract_to(src_tar, extracted)
            # Force the dir mtime to pre-1980 in case extraction reset it.
            import os
            os.utime(extracted / "emptydir", (0, 0))

            dst_zip = tdp / "out.zip"
            archives._pack_from(extracted, dst_zip)

            with zipfile.ZipFile(dst_zip, "r") as zf:
                names = zf.namelist()
                self.assertIn("emptydir/", names)
                self.assertIn("emptydir/keep.txt", names)
                for n in names:
                    self.assertGreaterEqual(
                        zf.getinfo(n).date_time, (1980, 1, 1, 0, 0, 0)
                    )


class TempDirCleanedOnFailure(unittest.TestCase):
    """ArchiveWorker uses ``tempfile.TemporaryDirectory`` for extraction;
    confirm the directory is gone after a bounded-extraction failure so we
    don't leave partial output on the user's disk."""

    def test_zip_failure_removes_temp_dir(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            src = tdp / "many.zip"
            with zipfile.ZipFile(src, "w") as zf:
                for i in range(12):
                    zf.writestr(f"f{i}.txt", b"x")

            captured: dict[str, Path] = {}
            real_extract = archives._extract_to

            def spy_extract(s: Path, d: Path) -> None:
                captured["dir"] = d
                real_extract(s, d)

            with mock.patch.object(archives, "MAX_ARCHIVE_MEMBERS", 10), \
                 mock.patch.object(archives, "_extract_to", spy_extract):
                # Drive the worker's _convert path without spinning a QThread.
                from cove_converter.engines.archives import ArchiveWorker
                w = ArchiveWorker.__new__(ArchiveWorker)
                w.input_path = src
                w.output_path = tdp / "out.tar"
                # Stub the Qt signal — we only care about exception + cleanup.
                w.progress = mock.Mock()
                with self.assertRaises(archives.ArchiveTooLargeError):
                    w._convert()

            self.assertIn("dir", captured)
            self.assertFalse(captured["dir"].exists(),
                             "temp extraction dir should be cleaned up on failure")


if __name__ == "__main__":
    unittest.main()

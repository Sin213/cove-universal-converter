"""Regression: worker must verify temp-output writability and fall back.

On NTFS-3G / exFAT external mounts (e.g. ``/run/media/...``) ``mkstemp`` can
produce a sibling temp file that is reported writable for the creating user
but rejects ``open(..., "r+b")`` because the mount enforces a read-only
``fmask``. The previous defence (``os.chmod`` after mkstemp) silently
no-ops on those mounts, so PIL would later hit ``PermissionError`` when it
tried to write the PDF into the temp.

These tests simulate the failure mode by making the sibling temp's
``_verify_writable`` probe report False, and assert the worker falls back
to a system-temp output, finalises into the requested destination, leaves
the source untouched, and cleans up both temp files.
"""
from __future__ import annotations

import builtins
import errno
import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image

from cove_converter.engines import base as base_mod
from cove_converter.engines.pdf import PdfWorker
from cove_converter.settings import ConversionSettings


def _sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


@unittest.skipIf(sys.platform == "win32", "POSIX permission semantics only")
class WorkerTempWritabilityFallback(unittest.TestCase):
    def test_unwritable_sibling_temp_falls_back_to_system_temp(self) -> None:
        """Drives the original failure: ``_allocate_temp_output`` returns a
        sibling whose mode forbids reopen-for-write. Without the fix, PIL
        hits ``PermissionError`` mid-``_convert`` and the destination is
        never produced. With the fix, the worker probes for writability,
        falls back to a system-temp output, and finalises into the
        destination."""
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "in.jpeg"
            Image.new("RGB", (40, 30), (10, 20, 30)).save(src, "JPEG")
            src_hash = _sha256(src)
            dst = Path(td) / "out.pdf"

            real_alloc = base_mod._allocate_temp_output
            sibling_temps: list[Path] = []

            def alloc_and_disable_write(final: Path) -> Path:
                p = real_alloc(final)
                sibling_temps.append(p)
                # Strip every permission bit so a subsequent open for write
                # raises PermissionError. ``os.unlink`` still works because
                # the parent directory is writable.
                os.chmod(p, 0o000)
                return p

            with mock.patch.object(
                base_mod, "_allocate_temp_output", alloc_and_disable_write
            ):
                worker = PdfWorker(src, dst, settings=ConversionSettings())
                worker.run()

            # Final output landed at the requested destination.
            self.assertTrue(dst.exists(), "destination PDF was not produced")
            self.assertEqual(dst.read_bytes()[:5], b"%PDF-")
            self.assertGreater(dst.stat().st_size, 0)

            # Source untouched.
            self.assertEqual(_sha256(src), src_hash)

            # The unwritable sibling temp was discarded, not left behind.
            self.assertEqual(len(sibling_temps), 1)
            self.assertFalse(
                sibling_temps[0].exists(),
                "non-writable sibling temp was not cleaned up",
            )
            # No leftover ``.cove-part-*`` siblings in the destination dir.
            stragglers = list(dst.parent.glob(".*.cove-part-*"))
            self.assertEqual(stragglers, [], f"leftover sibling temps: {stragglers}")

            # Worker no longer holds any temp reference after success.
            self.assertIsNone(worker._owned_temp_path)

    def test_unwritable_sibling_via_verify_probe_falls_back(self) -> None:
        """Same fault path but driven by monkeypatching ``_verify_writable``
        to fail for the sibling-temp directory only — exercises the case
        where chmod happens to succeed on the bad mount yet open-for-write
        still rejects later (the original Codex finding)."""
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "in.png"
            Image.new("RGB", (40, 30), (200, 50, 50)).save(src, "PNG")
            src_hash = _sha256(src)
            dst = Path(td) / "out.pdf"
            sibling_dir = dst.parent.resolve()

            real_verify = base_mod._verify_writable

            def picky_verify(path: Path) -> bool:
                # Sibling temp lives in the destination directory; pretend
                # the mount rejects write probes there. Fallback in /tmp
                # gets the real probe and should pass.
                if Path(path).resolve().parent == sibling_dir:
                    return False
                return real_verify(path)

            with mock.patch.object(base_mod, "_verify_writable", picky_verify):
                worker = PdfWorker(src, dst, settings=ConversionSettings())
                worker.run()

            self.assertTrue(dst.exists())
            self.assertEqual(dst.read_bytes()[:5], b"%PDF-")
            self.assertEqual(_sha256(src), src_hash)
            # No leftover ``.cove-part-*`` siblings in the destination dir.
            stragglers = list(dst.parent.glob(".*.cove-part-*"))
            self.assertEqual(stragglers, [], f"leftover sibling temps: {stragglers}")
            self.assertIsNone(worker._owned_temp_path)


@unittest.skipIf(sys.platform == "win32", "POSIX permission semantics only")
class CrossFsExdevFinalisation(unittest.TestCase):
    """When the EXDEV path is taken, the worker must stage into the dest
    directory and only then atomically replace ``final``. A mid-copy
    failure must never be allowed to truncate or partially overwrite a
    pre-existing destination."""

    def _force_exdev_setup(self, td: Path):
        """Helpers shared by both EXDEV tests: a JPEG source, a sibling-
        temp allocator that produces a non-writable file (so the worker
        falls back to /tmp), and a replace-emulator that raises EXDEV
        only for cross-directory renames."""
        src = td / "in.jpeg"
        Image.new("RGB", (40, 30), (10, 20, 30)).save(src, "JPEG")

        real_alloc = base_mod._allocate_temp_output

        def alloc_unwritable(final: Path) -> Path:
            p = real_alloc(final)
            os.chmod(p, 0o000)
            return p

        real_replace = base_mod.os.replace

        def replace_emulating_exdev(s, d, *a, **k):
            if Path(s).parent.resolve() != Path(d).parent.resolve():
                raise OSError(errno.EXDEV, "Invalid cross-device link")
            return real_replace(s, d, *a, **k)

        return src, alloc_unwritable, replace_emulating_exdev

    def test_exdev_copy_failure_leaves_existing_final_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as td_str:
            td = Path(td_str)
            src, alloc_unwritable, replace_emulating_exdev = self._force_exdev_setup(td)
            src_hash = _sha256(src)

            dst = td / "out.pdf"
            original_dst_bytes = b"%PDF-1.4 ARCHIVED OLD CONTENT\n%%EOF\n"
            dst.write_bytes(original_dst_bytes)
            original_dst_hash = _sha256(dst)

            copyobj_calls: list[int] = []

            def failing_copyfileobj(src_fp, dst_fp, *a, **k):
                copyobj_calls.append(1)
                raise OSError("simulated cross-fs copy failure")

            with mock.patch.object(base_mod, "_allocate_temp_output", alloc_unwritable), \
                 mock.patch("cove_converter.engines.base.os.replace", replace_emulating_exdev), \
                 mock.patch("cove_converter.engines.base.shutil.copyfileobj", failing_copyfileobj):
                worker = PdfWorker(src, dst, settings=ConversionSettings())
                worker.run()

            # 1. Existing destination is byte-for-byte unchanged. The copy
            #    only ever wrote into the staging fd, never to ``final``.
            self.assertEqual(dst.read_bytes(), original_dst_bytes)
            self.assertEqual(_sha256(dst), original_dst_hash)

            # 2. The copy was attempted (proves the EXDEV branch ran).
            self.assertGreater(len(copyobj_calls), 0)

            # 3. No staging stragglers in the destination directory.
            stragglers = list(dst.parent.glob(".*.cove-final-*"))
            self.assertEqual(stragglers, [], f"leftover staging files: {stragglers}")

            # 4. Source untouched.
            self.assertEqual(_sha256(src), src_hash)

            # 5. Worker no longer holds any temp/staging refs.
            self.assertIsNone(worker._owned_temp_path)
            self.assertIsNone(worker._owned_staging_path)

    def test_exdev_success_uses_staging_then_atomic_replace(self) -> None:
        with tempfile.TemporaryDirectory() as td_str:
            td = Path(td_str)
            src, alloc_unwritable, replace_emulating_exdev = self._force_exdev_setup(td)
            src_hash = _sha256(src)

            dst = td / "out.pdf"
            original_dst_bytes = b"%PDF-1.4 PRE-EXISTING\n%%EOF\n"
            dst.write_bytes(original_dst_bytes)

            replace_calls: list[tuple[str, str]] = []
            real_replace = base_mod.os.replace

            def tracking_replace(s, d, *a, **k):
                replace_calls.append((str(s), str(d)))
                if Path(s).parent.resolve() != Path(d).parent.resolve():
                    raise OSError(errno.EXDEV, "Invalid cross-device link")
                return real_replace(s, d, *a, **k)

            with mock.patch.object(base_mod, "_allocate_temp_output", alloc_unwritable), \
                 mock.patch("cove_converter.engines.base.os.replace", tracking_replace):
                worker = PdfWorker(src, dst, settings=ConversionSettings())
                worker.run()

            # Final has been replaced with a real PDF (not the original).
            self.assertTrue(dst.exists())
            self.assertEqual(dst.read_bytes()[:5], b"%PDF-")
            self.assertNotEqual(dst.read_bytes(), original_dst_bytes)

            # The successful replace was staging → final (intra-fs, no EXDEV).
            # ``replace_calls`` will contain at least one EXDEV-raising call
            # (cross-dir temp → final) followed by the staging → final swap.
            staging_to_final = [
                (s, d) for s, d in replace_calls
                if Path(d).resolve() == dst.resolve()
                and Path(s).parent.resolve() == dst.parent.resolve()
                and ".cove-final-" in Path(s).name
            ]
            self.assertEqual(
                len(staging_to_final), 1,
                f"expected one staging→final replace, got {replace_calls}",
            )

            # No staging stragglers, source unchanged, slots cleared.
            stragglers = list(dst.parent.glob(".*.cove-final-*"))
            self.assertEqual(stragglers, [])
            self.assertEqual(_sha256(src), src_hash)
            self.assertIsNone(worker._owned_temp_path)
            self.assertIsNone(worker._owned_staging_path)

    def test_exdev_staging_path_is_not_reopened_for_write(self) -> None:
        """The fix: the EXDEV staging file must be written through the
        ``mkstemp`` fd, never reopened from its path. On NTFS-3G/exFAT
        mounts the path can refuse open-for-write even though mkstemp's
        original fd is writable — that is the original mount failure mode
        that drove the sibling-temp fallback in the first place. Reopening
        the staging path for write would just re-trip it.

        Drives the guarantee by patching ``builtins.open`` to refuse any
        write-mode open of a ``.cove-final-*`` path. With the fix the
        conversion succeeds because ``os.fdopen`` bypasses ``builtins.open``
        and writes through the mkstemp fd directly. Without the fix
        (``shutil.copyfile`` → reopen for write) the conversion fails
        and the destination is not produced."""
        with tempfile.TemporaryDirectory() as td_str:
            td = Path(td_str)
            src, alloc_unwritable, replace_emulating_exdev = self._force_exdev_setup(td)
            src_hash = _sha256(src)
            dst = td / "out.pdf"

            real_open = builtins.open
            denied_writes: list[str] = []

            def picky_open(file, mode="r", *args, **kwargs):
                try:
                    name = os.fspath(file)
                except TypeError:
                    # Plain int fd — not a path. Let it through.
                    return real_open(file, mode, *args, **kwargs)
                if isinstance(name, bytes):
                    name = name.decode("utf-8", errors="replace")
                base = os.path.basename(str(name))
                write_intent = any(c in mode for c in ("w", "a", "x", "+"))
                if ".cove-final-" in base and write_intent:
                    denied_writes.append(str(name))
                    raise PermissionError(
                        13,
                        "simulated mount: staging path not reopen-writable",
                        str(name),
                    )
                return real_open(file, mode, *args, **kwargs)

            with mock.patch.object(base_mod, "_allocate_temp_output", alloc_unwritable), \
                 mock.patch("cove_converter.engines.base.os.replace", replace_emulating_exdev), \
                 mock.patch.object(builtins, "open", picky_open):
                worker = PdfWorker(src, dst, settings=ConversionSettings())
                worker.run()

            # With the fix, the conversion completes through the mkstemp fd.
            self.assertTrue(dst.exists(), "destination PDF was not produced")
            self.assertEqual(dst.read_bytes()[:5], b"%PDF-")
            self.assertEqual(_sha256(src), src_hash)

            # The defining assertion: nothing ever reopened the staging
            # path for writing. If this list is non-empty, the EXDEV branch
            # regressed back to ``shutil.copyfile`` (or equivalent) and the
            # fix has been undone.
            self.assertEqual(
                denied_writes,
                [],
                f"EXDEV path reopened the staging file for writing: {denied_writes}",
            )

            stragglers = list(dst.parent.glob(".*.cove-final-*"))
            self.assertEqual(stragglers, [])
            self.assertIsNone(worker._owned_temp_path)
            self.assertIsNone(worker._owned_staging_path)


if __name__ == "__main__":
    unittest.main()

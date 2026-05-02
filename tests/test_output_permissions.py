"""Regression tests for converted-file permissions on POSIX (Codex review #3).

``tempfile.mkstemp`` creates files at mode 0600 and ``os.replace`` preserves
that, so without normalization every converted output became owner-only.
``_normalize_output_mode`` restores umask-default semantics for new files and
matches the existing destination's mode on overwrite.

The umask is captured once at module import (``DEFAULT_UMASK``) so worker
threads do not race on the process-global ``os.umask``."""
from __future__ import annotations

import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from cove_converter.engines import base  # noqa: E402
from cove_converter.engines.base import _normalize_output_mode  # noqa: E402


@unittest.skipIf(sys.platform == "win32", "POSIX permission semantics only")
class NormalizeOutputMode(unittest.TestCase):
    def test_new_file_uses_cached_umask(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "out.bin"
            # Simulate the post-replace state: file exists with 0600.
            out.write_bytes(b"data")
            os.chmod(out, 0o600)

            with mock.patch.object(base, "DEFAULT_UMASK", 0o022):
                _normalize_output_mode(out, prior_mode=None)

            mode = stat.S_IMODE(out.stat().st_mode)
            self.assertEqual(mode, 0o644)

    def test_overwrite_matches_prior_mode(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "out.bin"
            out.write_bytes(b"data")
            os.chmod(out, 0o600)

            # Caller captured 0o640 before the replace happened.
            _normalize_output_mode(out, prior_mode=0o100640)

            mode = stat.S_IMODE(out.stat().st_mode)
            self.assertEqual(mode, 0o640)

    def test_restrictive_cached_umask_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "out.bin"
            out.write_bytes(b"data")
            os.chmod(out, 0o600)

            with mock.patch.object(base, "DEFAULT_UMASK", 0o077):
                _normalize_output_mode(out, prior_mode=None)

            mode = stat.S_IMODE(out.stat().st_mode)
            self.assertEqual(mode, 0o600)

    def test_does_not_mutate_process_umask(self) -> None:
        """Workers must never call ``os.umask`` — it is process-global and
        racy across concurrent conversions."""
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "out.bin"
            out.write_bytes(b"data")
            os.chmod(out, 0o600)

            with mock.patch("cove_converter.engines.base.os.umask") as umask_call:
                _normalize_output_mode(out, prior_mode=None)
                _normalize_output_mode(out, prior_mode=0o100640)
                self.assertFalse(
                    umask_call.called,
                    "os.umask must not be called from worker conversion path",
                )


if __name__ == "__main__":
    unittest.main()

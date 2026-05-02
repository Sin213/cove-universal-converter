"""Regression tests for ``_allocate_temp_output`` (Codex review #2).

Prefixing the temp filename with the full final stem could push the result past
NAME_MAX (255 bytes on common filesystems) for long but otherwise valid output
names. The allocator now bounds the stem portion while preserving the suffix so
extension-based writers still behave."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from cove_converter.engines.base import _allocate_temp_output  # noqa: E402


class LongFilenameAllocation(unittest.TestCase):
    def test_long_stem_allocates_temp(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            # 240-byte stem is valid as a final filename on ext4/APFS but
            # would blow past 255 once ".cove-part-" + random + suffix are
            # added.
            long_stem = "a" * 240
            final = Path(td) / f"{long_stem}.mp4"
            tmp = _allocate_temp_output(final)
            try:
                self.assertTrue(tmp.exists())
                self.assertEqual(tmp.parent, final.parent)
                self.assertLess(
                    len(tmp.name.encode("utf-8")),
                    255,
                    "temp filename must stay under NAME_MAX",
                )
            finally:
                tmp.unlink(missing_ok=True)

    def test_temp_preserves_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            long_stem = "b" * 230
            final = Path(td) / f"{long_stem}.tar.gz"
            tmp = _allocate_temp_output(final)
            try:
                # mkstemp uses the literal ``suffix`` we hand it, so the
                # final extension is preserved verbatim.
                self.assertTrue(tmp.name.endswith(".gz"))
                self.assertEqual(tmp.suffix, final.suffix)
            finally:
                tmp.unlink(missing_ok=True)

    def test_short_stem_unchanged_behavior(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            final = Path(td) / "song.flac"
            tmp = _allocate_temp_output(final)
            try:
                self.assertIn("song", tmp.name)
                self.assertTrue(tmp.name.endswith(".flac"))
                self.assertIn(".cove-part-", tmp.name)
            finally:
                tmp.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()

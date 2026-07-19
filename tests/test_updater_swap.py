"""Unit tests for swap_in_appimage - versioned-filename install semantics."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cove_converter.updater import swap_in_appimage  # noqa: E402


class SwapInAppImageTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.cache = self.dir / "cache"
        self.cache.mkdir()
        self.old = self.dir / "cove-pdf-editor-1.2.0-x86_64.AppImage"
        self.old.write_bytes(b"old-binary")
        self._saved_env = os.environ.get("APPIMAGE")
        os.environ["APPIMAGE"] = str(self.old)

    def tearDown(self):
        if self._saved_env is None:
            os.environ.pop("APPIMAGE", None)
        else:
            os.environ["APPIMAGE"] = self._saved_env
        self._tmp.cleanup()

    def test_installs_under_new_versioned_name_and_keeps_old(self):
        new = self.cache / "cove-pdf-editor-1.3.0-x86_64.AppImage"
        new.write_bytes(b"new-binary")
        result, old = swap_in_appimage(new)
        self.assertEqual(result, self.dir / "cove-pdf-editor-1.3.0-x86_64.AppImage")
        self.assertEqual(old, self.old)
        self.assertEqual(result.read_bytes(), b"new-binary")
        self.assertTrue(os.access(result, os.X_OK))
        # The old binary is the rollback copy; the caller removes it only
        # after the relaunched process is confirmed started.
        self.assertTrue(self.old.exists())
        self.assertEqual(os.environ["APPIMAGE"], str(result))
        self.assertFalse(result.with_name(result.name + ".part").exists())

    def test_same_name_redownload_preserves_old_bytes_for_rollback(self):
        new = self.cache / self.old.name
        new.write_bytes(b"same-version-rebuild")
        result, rollback = swap_in_appimage(new)
        self.assertEqual(result, self.old)
        self.assertEqual(result.read_bytes(), b"same-version-rebuild")
        self.assertTrue(os.access(result, os.X_OK))
        # In-place replace would destroy the only copy of the old bytes;
        # they must survive in a distinct rollback sibling.
        self.assertEqual(
            rollback, self.old.with_name(self.old.name + ".cove-rollback"),
        )
        self.assertEqual(rollback.read_bytes(), b"old-binary")

    def test_checksum_mismatch_aborts_and_cleans_part_file(self):
        import hashlib
        new = self.cache / "cove-pdf-editor-1.3.0-x86_64.AppImage"
        new.write_bytes(b"new-binary")
        wrong = hashlib.sha256(b"different-bytes").hexdigest()
        with self.assertRaises(RuntimeError):
            swap_in_appimage(new, expected_sha256=wrong)
        target = self.dir / "cove-pdf-editor-1.3.0-x86_64.AppImage"
        self.assertFalse(target.with_name(target.name + ".part").exists())
        self.assertTrue(self.old.exists())
        self.assertEqual(os.environ["APPIMAGE"], str(self.old))

    def test_missing_appimage_env_raises(self):
        del os.environ["APPIMAGE"]
        new = self.cache / "cove-pdf-editor-1.3.0-x86_64.AppImage"
        new.write_bytes(b"new-binary")
        with self.assertRaises(RuntimeError):
            swap_in_appimage(new)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import re
import tomllib
import unittest
from pathlib import Path

import cove_converter
from cove_converter.version import validate_release, validate_version


ROOT = Path(__file__).resolve().parent.parent
RUNTIME_LOCK = ROOT / "requirements-runtime.lock"

_NAME_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9_.\-]*)")
_EXACT_PIN_RE = re.compile(r"^==(?!=)[0-9][0-9A-Za-z.+_\-]*\s*(?:;.*)?\\?\s*$")
_HASH_RE = re.compile(r"--hash=sha256:([0-9a-f]+)(?=\s|\\|$)")


def _canonicalize(name: str) -> str:
    """PEP 503 name canonicalization: case/separator-insensitive comparison."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _hash_locked_requirement_names(lock_path: Path) -> set[str]:
    """Return the set of canonical requirement names that are exactly pinned and hash-locked.

    Raises ``ValueError`` for any requirement line that is unpinned, missing a
    well-formed 64-hex-char sha256 hash, or declared more than once under its
    canonical (PEP 503) name, so callers can prove the hash-lock contract
    rather than merely inspect coverage.
    """
    blocks = re.split(r"\n(?=[A-Za-z0-9])", lock_path.read_text())
    names: list[str] = []
    for block in blocks:
        name_match = _NAME_RE.match(block)
        if not name_match:
            continue
        raw_name = name_match.group(1)
        canonical_name = _canonicalize(raw_name)
        first_line = block.split("\n", 1)[0]
        rest = first_line[len(raw_name):]
        if not _EXACT_PIN_RE.match(rest):
            raise ValueError(f"requirement {raw_name!r} in {lock_path} is not exactly pinned")
        hash_match = _HASH_RE.search(block)
        if hash_match is None or len(hash_match.group(1)) != 64:
            raise ValueError(f"requirement {raw_name!r} in {lock_path} is missing a sha256 hash")
        names.append(canonical_name)
    duplicates = {name for name in names if names.count(name) > 1}
    if duplicates:
        raise ValueError(f"duplicate requirement pins in {lock_path}: {sorted(duplicates)}")
    return set(names)


class ReleaseVersionTests(unittest.TestCase):
    def test_runtime_matches_package_metadata(self) -> None:
        self.assertEqual(
            validate_release(cove_converter.__version__, project_file=ROOT / "pyproject.toml"),
            cove_converter.__version__,
        )

    def test_tag_must_match_requested_version(self) -> None:
        self.assertEqual(validate_release("2.4.0", tag="v2.4.0"), "2.4.0")
        with self.assertRaisesRegex(ValueError, "does not match tag"):
            validate_release("2.4.1", tag="v2.4.0")

    def test_empty_tag_is_not_silently_accepted(self) -> None:
        with self.assertRaises(ValueError):
            validate_release("2.4.0", tag="")

    def test_requested_version_must_match_pyproject(self) -> None:
        with self.assertRaisesRegex(ValueError, "does not match"):
            validate_release("9.9.9", project_file=ROOT / "pyproject.toml")

    def test_unsafe_artifact_versions_are_rejected(self) -> None:
        for value in ("", "v", "2.4", "2.4.0/other", "2.4.0 latest"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_version(value)


class RuntimeLockContractTests(unittest.TestCase):
    def test_runtime_lock_is_fully_hash_locked(self) -> None:
        locked_names = _hash_locked_requirement_names(RUNTIME_LOCK)
        with (ROOT / "pyproject.toml").open("rb") as stream:
            dependencies = tomllib.load(stream)["project"]["dependencies"]
        top_level_names = {_canonicalize(re.split(r"[<>=~!; ]", dep, maxsplit=1)[0]) for dep in dependencies}
        missing = top_level_names - locked_names
        self.assertFalse(
            missing, f"pyproject.toml dependencies missing from {RUNTIME_LOCK.name}: {missing}"
        )

    def test_lock_hash_check_detects_missing_hash(self) -> None:
        import tempfile

        original = RUNTIME_LOCK.read_text()
        blocks = re.split(r"\n(?=[A-Za-z0-9])", original)
        first_requirement_index = next(
            i for i, block in enumerate(blocks) if _NAME_RE.match(block)
        )
        lines = blocks[first_requirement_index].split("\n")
        lines = [line for line in lines if "--hash=sha256:" not in line]
        blocks[first_requirement_index] = "\n".join(lines)
        weakened = "\n".join(blocks)
        self.assertNotIn(
            "--hash=sha256:", blocks[first_requirement_index], "test fixture left a hash behind"
        )
        with tempfile.TemporaryDirectory() as tmp:
            weakened_path = Path(tmp) / "requirements-runtime.lock"
            weakened_path.write_text(weakened)
            with self.assertRaisesRegex(ValueError, "missing a sha256 hash"):
                _hash_locked_requirement_names(weakened_path)

    def test_lock_hash_check_rejects_oversized_hash(self) -> None:
        import tempfile

        text = "demo==1.0.0 \\\n    --hash=sha256:" + "a" * 65 + "\n"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "requirements-runtime.lock"
            path.write_text(text)
            with self.assertRaisesRegex(ValueError, "missing a sha256 hash"):
                _hash_locked_requirement_names(path)

    def test_lock_hash_check_detects_canonicalized_duplicate_names(self) -> None:
        import tempfile

        valid_hash = "a" * 64
        text = (
            f"demo-pkg==1.0.0 \\\n    --hash=sha256:{valid_hash}\n"
            f"demo_pkg==1.0.0 \\\n    --hash=sha256:{valid_hash}\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "requirements-runtime.lock"
            path.write_text(text)
            with self.assertRaisesRegex(ValueError, "duplicate requirement pins"):
                _hash_locked_requirement_names(path)

    def test_lock_hash_check_rejects_unpinned_requirement(self) -> None:
        import tempfile

        text = "demo>=1.0.0 \\\n    --hash=sha256:" + "a" * 64 + "\n"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "requirements-runtime.lock"
            path.write_text(text)
            with self.assertRaisesRegex(ValueError, "not exactly pinned"):
                _hash_locked_requirement_names(path)

    def test_lock_hash_check_rejects_non_hex_hash_suffix(self) -> None:
        import tempfile

        text = "demo==1.0.0 \\\n    --hash=sha256:" + "a" * 64 + "z\n"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "requirements-runtime.lock"
            path.write_text(text)
            with self.assertRaisesRegex(ValueError, "missing a sha256 hash"):
                _hash_locked_requirement_names(path)

    def test_lock_hash_check_rejects_non_exact_specifiers(self) -> None:
        import tempfile

        valid_hash = "a" * 64
        for specifier in ("1.*", "1,!=1.1", "=1.0.0"):
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "requirements-runtime.lock"
                path.write_text(f"demo=={specifier} \\\n    --hash=sha256:{valid_hash}\n")
                with self.subTest(specifier=specifier), self.assertRaisesRegex(
                    ValueError, "not exactly pinned"
                ):
                    _hash_locked_requirement_names(path)


if __name__ == "__main__":
    unittest.main()

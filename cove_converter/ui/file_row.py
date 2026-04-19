from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class FileRow:
    path: Path
    target_ext: str
    status: str = "Pending"
    progress: int = 0
    worker: object | None = field(default=None, repr=False)
    # If set, overrides the computed path (used when the user chose to
    # rename duplicates in the overwrite-confirm dialog).
    override_output: Path | None = None

    def resolve_output(self, dest_dir: Path | None) -> Path:
        if self.override_output is not None:
            return self.override_output
        if dest_dir is None:
            return self.path.with_suffix(self.target_ext)
        return dest_dir / (self.path.stem + self.target_ext)


def unique_path(path: Path, reserved: set[Path] | None = None) -> Path:
    """Return ``path`` if it doesn't exist and isn't already reserved in this batch;
    otherwise append ``(1)``, ``(2)``… until an unused name is found."""
    reserved = reserved or set()
    if not path.exists() and path not in reserved:
        return path
    stem, suffix, parent = path.stem, path.suffix, path.parent
    for i in range(1, 1000):
        candidate = parent / f"{stem} ({i}){suffix}"
        if not candidate.exists() and candidate not in reserved:
            return candidate
    raise RuntimeError(f"Could not find a unique name for {path}")

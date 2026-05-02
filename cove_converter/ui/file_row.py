from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from cove_converter.routing import effective_stem


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
    # Path the worker actually wrote to. Captured on success so later
    # open/show actions don't recompute against a now-changed output dir.
    completed_output: Path | None = None

    def resolve_output(self, dest_dir: Path | None) -> Path:
        if self.override_output is not None:
            return self.override_output
        # ``effective_stem`` strips compound suffixes like ``.tar.gz`` so the
        # rebuilt name doesn't end up as ``foo.tar.zip``.
        stem = effective_stem(self.path)
        parent = self.path.parent if dest_dir is None else dest_dir
        return parent / (stem + self.target_ext)


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

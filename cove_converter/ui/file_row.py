from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from cove_converter.routing import effective_stem


@dataclass(eq=False)
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
    # Per-row Enhance-PDF toggle. UI surfaces this only when target_ext
    # is ``.pdf``; the engine itself only acts on PDF→PDF.
    enhance_pdf: bool = False

    def resolve_output(self, dest_dir: Path | None) -> Path:
        if self.override_output is not None:
            return self.override_output
        # ``effective_stem`` strips compound suffixes like ``.tar.gz`` so the
        # rebuilt name doesn't end up as ``foo.tar.zip``.
        stem = effective_stem(self.path)
        parent = self.path.parent if dest_dir is None else dest_dir
        candidate = parent / (stem + self.target_ext)
        # When target_ext matches the source extension and no separate
        # destination directory was chosen, the natural candidate path is
        # the source itself — which the overwrite guard rejects before
        # the worker runs. Nudge to a ``stem (1).ext`` variant so PDF→PDF
        # (the smart-PDF flatten path) works out of the box. Any further
        # collision with a non-source file still triggers the existing
        # overwrite-confirm dialog.
        if candidate.resolve() == self.path.resolve():
            candidate = parent / f"{stem} (1){self.target_ext}"
        return candidate


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

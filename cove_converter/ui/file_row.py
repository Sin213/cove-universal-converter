from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from cove_converter.routing import effective_stem, effective_suffix

if TYPE_CHECKING:
    from cove_converter.engines.base import BaseConverterWorker
    from cove_converter.settings import ConversionSettings


@dataclass(frozen=True)
class ConversionJob:
    """Validated paths and a private settings copy captured at enqueue time."""

    input_path: Path
    output_path: Path
    target_ext: str
    engine: str
    settings: ConversionSettings


@dataclass(eq=False)
class FileRow:
    path: Path
    target_ext: str
    status: str = "Pending"
    progress: int = 0
    worker: BaseConverterWorker | None = field(default=None, repr=False)
    job: ConversionJob | None = field(default=None, repr=False)
    # If set, overrides the computed path (used when the user chose to
    # rename duplicates in the overwrite-confirm dialog).
    override_output: Path | None = None
    # Path the worker actually wrote to. Captured on success so later
    # open/show actions don't recompute against a now-changed output dir.
    completed_output: Path | None = None
    # Per-row Enhance-PDF toggle. UI surfaces this only when target_ext
    # is ``.pdf``; the engine itself only acts on PDF→PDF.
    enhance_pdf: bool = False
    # Human-readable failure log captured from the worker. Set when a
    # row enters a Failed state so the UI can show *why* it failed
    # without users having to dig through terminal logs.
    error_log: str | None = None
    extra_targets: tuple[str, ...] = ()
    preset_settings: ConversionSettings | None = field(default=None, repr=False)
    jobs: tuple[ConversionJob, ...] = field(default=(), repr=False)
    job_index: int = 0
    target_status: str = "Pending"
    completed_outputs: list[Path] = field(default_factory=list)
    target_errors: list[str] = field(default_factory=list, repr=False)

    @property
    def selected_targets(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys((self.target_ext, *self.extra_targets)))

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


def path_key(path: Path) -> str:
    return str(path.resolve()).casefold()


def unique_path(path: Path, reserved: set[Path] | None = None) -> Path:
    """Return ``path`` if it doesn't exist and isn't already reserved in this batch;
    otherwise append ``(1)``, ``(2)``… until an unused name is found."""
    reserved_keys = {path_key(p) for p in (reserved or ())}
    existing = {p.name.casefold() for p in path.parent.iterdir()} if path.parent.exists() else set()
    if path.name.casefold() not in existing and path_key(path) not in reserved_keys:
        return path
    stem, parent = effective_stem(path), path.parent
    routed_suffix = effective_suffix(path)
    # Keep the caller's original suffix casing while treating recognised
    # compound extensions (for example ``.tar.gz``) as one extension.
    suffix = path.name[-len(routed_suffix):] if routed_suffix else ""
    for i in range(1, 1000):
        candidate = parent / f"{stem} ({i}){suffix}"
        if (candidate.name.casefold() not in existing
                and path_key(candidate) not in reserved_keys):
            return candidate
    raise RuntimeError(f"Could not find a unique name for {path}")

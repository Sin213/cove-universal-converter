from __future__ import annotations

import logging
import os
import stat
import sys
import tempfile
import traceback
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from cove_converter.settings import ConversionSettings, default_settings


_log = logging.getLogger("cove_converter.worker")


def _allocate_temp_output(final: Path) -> Path:
    """Create a unique, worker-owned temp file in the same directory as
    ``final`` and return its path. Same directory keeps ``os.replace``
    atomic (cross-fs renames silently fall back to copy+unlink).

    The basename uses a random component so we can never collide with a
    pre-existing user file. ``tempfile.mkstemp`` opens-and-creates the file
    atomically (O_CREAT | O_EXCL), which is the proof of ownership: any
    later cleanup is guaranteed to be unlinking *our* file, not someone
    else's. The original suffix is preserved so format-detecting writers
    (ffmpeg, pandoc, openpyxl, PIL) still see the right extension.
    """
    # Cap the stem portion so the full temp filename stays under common
    # NAME_MAX limits (255 bytes on ext4/APFS/NTFS). Components: leading
    # ``.`` (1) + stem + ``.cove-part-`` (11) + mkstemp randomness (8) +
    # suffix. Conservative budget = 200 bytes minus the suffix; truncate
    # in UTF-8 byte space so multi-byte filenames don't get split.
    suffix = final.suffix
    suffix_bytes = len(suffix.encode("utf-8"))
    max_stem_bytes = max(1, 200 - suffix_bytes)
    stem = final.stem
    encoded_stem = stem.encode("utf-8")
    if len(encoded_stem) > max_stem_bytes:
        stem = encoded_stem[:max_stem_bytes].decode("utf-8", errors="ignore") or "out"
    fd, tmp_str = tempfile.mkstemp(
        prefix=f".{stem}.cove-part-",
        suffix=suffix,
        dir=str(final.parent),
    )
    os.close(fd)
    return Path(tmp_str)


def _capture_process_umask() -> int:
    """Read and restore the process umask. Called once at module import on
    POSIX so worker threads never have to mutate the process-global umask."""
    if sys.platform == "win32":
        return 0
    current = os.umask(0)
    os.umask(current)
    return current


# Captured at import on the main thread. Workers must not call os.umask().
DEFAULT_UMASK = _capture_process_umask()


def _normalize_output_mode(final: Path, prior_mode: int | None) -> None:
    """On POSIX, ``tempfile.mkstemp`` creates files at 0600, and ``os.replace``
    preserves that mode at the final destination. Restore the mode a normal
    create would have produced: the prior file's mode if we overwrote one,
    otherwise ``0o666 & ~DEFAULT_UMASK``. Windows is a no-op.

    Uses the umask captured at module import — calling ``os.umask`` from worker
    threads is unsafe because it is process-global and other threads can create
    files while it is temporarily zeroed."""
    if sys.platform == "win32":
        return
    try:
        if prior_mode is not None:
            target_mode = stat.S_IMODE(prior_mode)
        else:
            target_mode = 0o666 & ~DEFAULT_UMASK
        os.chmod(final, target_mode)
    except OSError:
        pass


class BaseConverterWorker(QThread):
    progress = Signal(int)          # 0..100
    status   = Signal(str)          # "Processing" / "Done" / "Failed: …"
    finished_ok = Signal(Path)      # output path on success
    failed = Signal(str)            # error message

    def __init__(
        self,
        input_path: Path,
        output_path: Path,
        settings: ConversionSettings | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.input_path = Path(input_path)
        self._final_output_path = Path(output_path)
        # Real temp path is allocated in run() once the parent directory
        # exists; until then output_path mirrors the final destination so
        # callers that introspect it pre-run still see something sensible.
        self.output_path = self._final_output_path
        self._owned_temp_path: Path | None = None
        self.settings = settings or default_settings()
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:  # noqa: D401 - QThread entry point
        final = self._final_output_path
        try:
            self.status.emit("Processing")
            final.parent.mkdir(parents=True, exist_ok=True)
            # If we're overwriting, remember the prior file's mode so we can
            # restore it after the atomic replace (mkstemp creates at 0600).
            try:
                prior_mode: int | None = final.stat().st_mode
            except FileNotFoundError:
                prior_mode = None
            # Allocate a unique sibling temp path that *we* own. This is the
            # only file the worker is allowed to delete on cancel/failure.
            temp = _allocate_temp_output(final)
            self._owned_temp_path = temp
            self.output_path = temp
            self._convert()
            if self._cancel:
                self._cleanup_temp()
                self.status.emit("Cancelled")
                return
            os.replace(str(temp), str(final))
            self._owned_temp_path = None
            self.output_path = final
            _normalize_output_mode(final, prior_mode)
            self.progress.emit(100)
            self.status.emit("Done")
            self.finished_ok.emit(final)
        except Exception as exc:
            self._cleanup_temp()
            tb = traceback.format_exc()
            # Full diagnostic context goes to stderr / configured logger so a
            # GUI failure (which only surfaces "Failed: <msg>") still leaves a
            # complete trail in the terminal the user launched the app from.
            _log.error(
                "%s failed: input=%s output=%s engine=%s\n%s",
                type(self).__name__,
                self.input_path,
                self._final_output_path,
                type(self).__name__.replace("Worker", ""),
                tb,
            )
            self.status.emit(f"Failed: {exc}")
            self.failed.emit(str(exc))

    def _cleanup_temp(self) -> None:
        # Only ever unlink the path we created in this run. Never touch a
        # file we didn't allocate ourselves — even if a sibling happens to
        # share the old deterministic name.
        owned = self._owned_temp_path
        if owned is None:
            return
        try:
            owned.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass
        self._owned_temp_path = None

    def _convert(self) -> None:
        raise NotImplementedError

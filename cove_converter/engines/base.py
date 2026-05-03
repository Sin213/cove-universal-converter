from __future__ import annotations

import errno
import logging
import os
import shutil
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
    tmp = Path(tmp_str)
    # ``mkstemp`` creates at 0o600 on POSIX, but some filesystems (notably
    # NTFS-3G / exFAT external mounts under /run/media) report a more
    # restrictive mode driven by the mount's ``fmask``/``umask``, which can
    # leave the temp read-only even though we just created it. Try a chmod
    # to restore owner write — if the FS ignores it, the writability probe
    # in ``BaseConverterWorker.run`` will catch it and fall back to a
    # system-temp output. The final mode is normalised post-replace by
    # ``_normalize_output_mode``.
    if sys.platform != "win32":
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
    return tmp


def _verify_writable(path: Path) -> bool:
    """Confirm ``path`` can actually be reopened for writing.

    On NTFS-3G / exFAT mounts a freshly-``mkstemp``-ed file can be reported
    with a mount-enforced mode that forbids write even for the creating
    user, and ``os.chmod`` may silently no-op on those mounts. The only
    reliable signal is to actually open the path with write intent. We use
    ``r+b`` so the probe does not truncate or otherwise mutate a file that
    may already contain content (mkstemp leaves it empty, but this helper
    is generic).
    """
    try:
        with open(path, "r+b"):
            pass
    except OSError:
        return False
    return True


def _allocate_fallback_temp(suffix: str) -> Path:
    """Allocate a temp file in the system temp directory.

    Used only when ``_allocate_temp_output`` produced a sibling temp on the
    destination filesystem that turned out to be non-writable. The system
    temp dir is virtually always a normal POSIX filesystem (``tmpfs`` /
    ext4 / APFS / NTFS local), so a freshly-``mkstemp``-ed file is reliably
    writable for the current user."""
    fd, tmp_str = tempfile.mkstemp(prefix=".cove-part-", suffix=suffix)
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
        # Staging path used only on the cross-filesystem (EXDEV) finalisation
        # path. Tracked so cleanup on failure/cancel can remove it without
        # touching ``self._final_output_path``.
        self._owned_staging_path: Path | None = None
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
            # Probe the sibling temp for actual write capability. On NTFS-3G
            # / exFAT mounts the file can come back read-only despite our
            # chmod, in which case opening it for write later (PIL, ffmpeg,
            # pandoc, etc.) would fail with PermissionError mid-conversion.
            # Fall back to the system temp dir, which is virtually always a
            # normal POSIX filesystem.
            if not _verify_writable(temp):
                try:
                    temp.unlink()
                except OSError:
                    pass
                self._owned_temp_path = None
                fallback = _allocate_fallback_temp(final.suffix)
                if not _verify_writable(fallback):
                    try:
                        fallback.unlink()
                    except OSError:
                        pass
                    raise RuntimeError(
                        "Could not allocate a writable temp file for conversion"
                    )
                temp = fallback
                self._owned_temp_path = temp
            self.output_path = temp
            self._convert()
            if self._cancel:
                self._cleanup_temp()
                self.status.emit("Cancelled")
                return
            try:
                os.replace(str(temp), str(final))
            except OSError as exc:
                # Cross-filesystem rename (sibling fallback was redirected to
                # /tmp). ``os.rename`` returns EXDEV on POSIX in this case;
                # we have to physically copy. Crucially, never copy *over*
                # ``final`` — a mid-copy failure would truncate or partially
                # overwrite an existing destination, which is data loss.
                # Stage into a hidden sibling of ``final`` first, then atomic
                # intra-fs ``os.replace`` swaps it in. If anything goes wrong
                # before the swap, the pre-existing ``final`` is untouched.
                if exc.errno != errno.EXDEV:
                    raise
                # Cap the embedded ``final.name`` so the staging filename
                # stays under common NAME_MAX (255 bytes).
                embedded = final.name
                embedded_bytes = embedded.encode("utf-8")
                max_embedded = 200
                if len(embedded_bytes) > max_embedded:
                    embedded = (
                        embedded_bytes[:max_embedded].decode("utf-8", errors="ignore")
                        or "out"
                    )
                fd, staging_str = tempfile.mkstemp(
                    prefix=f".{embedded}.cove-final-",
                    suffix=".tmp",
                    dir=str(final.parent),
                )
                staging = Path(staging_str)
                self._owned_staging_path = staging
                # Write through the fd ``mkstemp`` already gave us — never
                # reopen the staging path for writing. On NTFS-3G / exFAT
                # external mounts the path can be unreopen-able for write
                # even though the create-time fd is writable, which is the
                # exact failure mode that drove the sibling-temp fallback in
                # the first place. ``shutil.copyfile`` would re-trip it by
                # opening the destination path for write internally; routing
                # the bytes through ``os.fdopen(fd, "wb")`` keeps us on the
                # original fd that mkstemp already proved writable.
                try:
                    with os.fdopen(fd, "wb") as staging_file, \
                            open(str(temp), "rb") as src_file:
                        shutil.copyfileobj(src_file, staging_file)
                        staging_file.flush()
                        os.fsync(staging_file.fileno())
                except Exception:
                    # Copy faulted (disk full, source unreadable, etc).
                    # ``with`` already closed the staging fd. ``final`` was
                    # never touched — only ``staging`` was written to.
                    try:
                        staging.unlink()
                    except (FileNotFoundError, OSError):
                        pass
                    self._owned_staging_path = None
                    raise
                if sys.platform != "win32":
                    try:
                        os.chmod(staging, 0o600)
                    except OSError:
                        pass
                try:
                    os.replace(str(staging), str(final))
                except Exception:
                    # Intra-fs rename failed after a successful copy. ``final``
                    # is still byte-for-byte its prior content — ``os.replace``
                    # is atomic on POSIX, so a failure here means the swap
                    # never happened.
                    try:
                        staging.unlink()
                    except (FileNotFoundError, OSError):
                        pass
                    self._owned_staging_path = None
                    raise
                # On success ``staging`` no longer exists — it was renamed
                # over ``final``. Drop the ownership slot and remove the
                # cross-fs source temp.
                self._owned_staging_path = None
                try:
                    os.unlink(str(temp))
                except OSError:
                    pass
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
        # Only ever unlink paths we created in this run. Never touch a file
        # we didn't allocate ourselves — even if a sibling happens to share
        # the old deterministic name. Staging is unlinked first because it
        # lives in the destination directory and is the more sensitive of
        # the two; the system-temp fallback comes after.
        for attr in ("_owned_staging_path", "_owned_temp_path"):
            owned: Path | None = getattr(self, attr, None)
            if owned is None:
                continue
            try:
                owned.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                pass
            setattr(self, attr, None)

    def _convert(self) -> None:
        raise NotImplementedError

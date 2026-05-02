"""Archive worker — converts between ZIP, TAR, and TAR.GZ (.tgz).

ZIP is the dominant cross-platform archive; TAR is the Unix native; TGZ
(gzipped tar) is the standard Linux distribution format. Conversion is
extract-and-repack: contents are decompressed to a temp dir, then re-packed
into the target container.

We deliberately don't try to preserve every quirk (extended attrs, sparse
files, hardlinks). The goal is "user has a ZIP and needs a TAR" — round-
tripping a kernel source tarball through ZIP is out of scope."""
from __future__ import annotations

import posixpath
import shutil
import tarfile
import tempfile
import zipfile
from pathlib import Path

from cove_converter.engines.base import BaseConverterWorker


# Bounded-extraction limits. A malformed or malicious archive (zip/tar bomb)
# can otherwise fill the user's temp partition during conversion. These are
# deliberately generous for normal use but cap the worst case.
MAX_ARCHIVE_MEMBERS = 100_000
MAX_EXTRACTED_BYTES = 8 * 1024 * 1024 * 1024  # 8 GiB total uncompressed
MAX_SINGLE_ENTRY_BYTES = 4 * 1024 * 1024 * 1024  # 4 GiB per file
MAX_COMPRESSION_RATIO = 200  # uncompressed / compressed; only checked when both > 1 KiB


class ArchiveTooLargeError(RuntimeError):
    """Raised when an archive's metadata or extracted contents exceed the
    bounded-extraction limits defined above."""


def _is_tar_like(ext: str) -> bool:
    return ext in (".tar", ".tgz", ".gz")


def _tar_mode(out_ext: str, *, write: bool) -> str:
    base = "w" if write else "r"
    if out_ext == ".tgz" or out_ext == ".gz":
        return f"{base}:gz"
    return base


def _dedup_key(name: str) -> str:
    """Normalize a member path for duplicate detection. Both ZIP and TAR use
    forward-slash paths; ``posixpath.normpath`` collapses ``./`` and ``//`` and
    strips trailing slashes — so ``foo``, ``./foo``, and ``foo/`` all map to
    the same key. This catches duplicate entries and file/dir-type collisions
    where one logical path appears twice and the second extract would overwrite
    the first."""
    if not name:
        return name
    return posixpath.normpath(name)


def _is_within(parent: Path, child: Path) -> bool:
    parent_resolved = parent.resolve()
    try:
        child_resolved = (parent / child).resolve()
    except (OSError, RuntimeError):
        return False
    try:
        child_resolved.relative_to(parent_resolved)
    except ValueError:
        return False
    return True


def _safe_zip_extract(zf: zipfile.ZipFile, dst: Path) -> None:
    infos = zf.infolist()
    if len(infos) > MAX_ARCHIVE_MEMBERS:
        raise ArchiveTooLargeError(
            f"zip has {len(infos)} members, exceeds limit {MAX_ARCHIVE_MEMBERS}"
        )

    declared_total = 0
    seen_paths: set[str] = set()
    for info in infos:
        name = info.filename
        if name.startswith("/") or "\\" in name:
            raise RuntimeError(f"Refusing absolute/backslash path in zip: {name!r}")
        if not _is_within(dst, Path(name)):
            raise RuntimeError(f"Refusing path-traversal entry in zip: {name!r}")
        # Reject duplicate normalized paths before extraction so the second
        # entry can't silently overwrite the first on disk. ZIP allows this
        # legally; we don't try to preserve it through extract-then-repack.
        key = _dedup_key(name)
        if key in seen_paths:
            raise RuntimeError(
                f"Refusing duplicate zip member path: {name!r}"
            )
        seen_paths.add(key)
        if info.file_size > MAX_SINGLE_ENTRY_BYTES:
            raise ArchiveTooLargeError(
                f"zip entry {name!r} declares {info.file_size} bytes, "
                f"exceeds per-entry limit {MAX_SINGLE_ENTRY_BYTES}"
            )
        # Refuse obviously suspicious compression ratios up front. Tiny
        # entries are exempt because their ratios are noisy.
        if (
            info.compress_size > 1024
            and info.file_size > 1024
            and info.file_size // max(info.compress_size, 1) > MAX_COMPRESSION_RATIO
        ):
            raise ArchiveTooLargeError(
                f"zip entry {name!r} has suspicious compression ratio "
                f"{info.file_size}:{info.compress_size}"
            )
        declared_total += info.file_size
        if declared_total > MAX_EXTRACTED_BYTES:
            raise ArchiveTooLargeError(
                f"zip declares {declared_total} uncompressed bytes, "
                f"exceeds total limit {MAX_EXTRACTED_BYTES}"
            )

    # Extract member-by-member so misleading metadata can't bypass the
    # cumulative byte cap. ``extract`` honours the same path validation we
    # already performed above (joined onto ``dst``); we re-stat the file
    # afterwards because ``info.file_size`` is attacker-controlled.
    written_total = 0
    for info in infos:
        zf.extract(info, dst)
        if info.is_dir():
            continue
        try:
            actual = (dst / info.filename).stat().st_size
        except OSError:
            actual = info.file_size
        if actual > MAX_SINGLE_ENTRY_BYTES:
            raise ArchiveTooLargeError(
                f"zip entry {info.filename!r} expanded to {actual} bytes, "
                f"exceeds per-entry limit {MAX_SINGLE_ENTRY_BYTES}"
            )
        written_total += actual
        if written_total > MAX_EXTRACTED_BYTES:
            raise ArchiveTooLargeError(
                f"zip extraction reached {written_total} bytes, "
                f"exceeds total limit {MAX_EXTRACTED_BYTES}"
            )


def _safe_tar_extract(tf: tarfile.TarFile, dst: Path) -> None:
    # `filter='data'` only exists on Python 3.12+; on 3.11 it raises
    # TypeError and the unfiltered extractall is the classic CVE-2007-4559
    # path-traversal sink. Validate every member up front regardless of
    # runtime so the guarantee holds across all supported Pythons.
    #
    # We allow only regular files and directories. Symlinks and hardlinks
    # are rejected outright — even when the target stays inside ``dst``,
    # repacking would dereference the link and copy the same in-tree file
    # into the output ZIP many times, blowing past the bounded-output cap
    # for free. Block/character devices, FIFOs, sockets and any other
    # special members are rejected for the same reason and because the
    # unfiltered ``extractall`` on 3.11 would otherwise call ``os.mknod``.
    members = tf.getmembers()
    if len(members) > MAX_ARCHIVE_MEMBERS:
        raise ArchiveTooLargeError(
            f"tar has {len(members)} members, exceeds limit {MAX_ARCHIVE_MEMBERS}"
        )

    declared_total = 0
    seen_paths: set[str] = set()
    for m in members:
        name = m.name
        if name.startswith("/") or name.startswith(("../", "..\\")):
            raise RuntimeError(f"Refusing absolute/parent path in tar: {name!r}")
        # Reject backslashes outright. On Windows ``a/b.txt`` and ``a\b.txt``
        # resolve to the same on-disk path, so silently normalizing would let
        # one entry overwrite another despite passing duplicate detection
        # (which keys off POSIX-normalized paths).
        if "\\" in name:
            raise RuntimeError(f"Refusing backslash path in tar: {name!r}")
        if not _is_within(dst, Path(name)):
            raise RuntimeError(f"Refusing path-traversal entry in tar: {name!r}")
        # Reject duplicate normalized paths before extraction so the second
        # entry can't silently overwrite the first on disk. TAR permits
        # repeated names; we don't try to preserve them through repack.
        key = _dedup_key(name)
        if key in seen_paths:
            raise RuntimeError(
                f"Refusing duplicate tar member path: {name!r}"
            )
        seen_paths.add(key)
        if m.isfile():
            if m.size > MAX_SINGLE_ENTRY_BYTES:
                raise ArchiveTooLargeError(
                    f"tar entry {name!r} declares {m.size} bytes, "
                    f"exceeds per-entry limit {MAX_SINGLE_ENTRY_BYTES}"
                )
            declared_total += m.size
            if declared_total > MAX_EXTRACTED_BYTES:
                raise ArchiveTooLargeError(
                    f"tar declares {declared_total} uncompressed bytes, "
                    f"exceeds total limit {MAX_EXTRACTED_BYTES}"
                )
            continue
        if m.isdir():
            continue
        if m.issym() or m.islnk():
            kind = "symlink" if m.issym() else "hardlink"
            raise RuntimeError(
                f"Refusing tar {kind} member: {name!r} -> {m.linkname!r}"
            )
        # Anything else (block/char dev, fifo, socket, contiguous, …) is
        # special and unsupported.
        kind = (
            "block-device" if m.isblk()
            else "char-device" if m.ischr()
            else "fifo" if m.isfifo()
            else f"type={m.type!r}"
        )
        raise RuntimeError(f"Refusing unsupported tar member ({kind}): {name!r}")

    # Extract one member at a time so we can re-check actual on-disk size
    # against the cumulative cap — tar headers are attacker-controlled.
    written_total = 0
    for m in members:
        try:
            tf.extract(m, dst, filter="data")
        except TypeError:
            tf.extract(m, dst)
        if not m.isfile():
            continue
        try:
            actual = (dst / m.name).stat().st_size
        except OSError:
            actual = m.size
        if actual > MAX_SINGLE_ENTRY_BYTES:
            raise ArchiveTooLargeError(
                f"tar entry {m.name!r} expanded to {actual} bytes, "
                f"exceeds per-entry limit {MAX_SINGLE_ENTRY_BYTES}"
            )
        written_total += actual
        if written_total > MAX_EXTRACTED_BYTES:
            raise ArchiveTooLargeError(
                f"tar extraction reached {written_total} bytes, "
                f"exceeds total limit {MAX_EXTRACTED_BYTES}"
            )


def _extract_to(src: Path, dst: Path) -> None:
    ext = src.suffix.lower()
    if ext == ".zip":
        with zipfile.ZipFile(src, "r") as zf:
            _safe_zip_extract(zf, dst)
    elif _is_tar_like(ext):
        with tarfile.open(src, _tar_mode(ext, write=False)) as tf:
            _safe_tar_extract(tf, dst)
    else:
        raise RuntimeError(f"Unsupported archive input: {ext}")


def _pack_from(src: Path, dst: Path) -> None:
    # Reuse the extraction caps as the repack output cap: even though we
    # already bounded what could land in ``src``, a stray FS symlink or a
    # logic bug here mustn't be able to fabricate an oversized output.
    # ``is_file()`` / ``is_dir()`` follow symlinks, so we test
    # ``is_symlink()`` *first* and skip those entries entirely — that
    # closes the bypass where one in-tree symlink could be packed many
    # times into the output ZIP/TAR.
    ext = dst.suffix.lower()
    member_count = 0
    written_total = 0

    def _check_member() -> None:
        nonlocal member_count
        member_count += 1
        if member_count > MAX_ARCHIVE_MEMBERS:
            raise ArchiveTooLargeError(
                f"repack would write more than {MAX_ARCHIVE_MEMBERS} members"
            )

    def _check_bytes(n: int, arcname: str) -> None:
        nonlocal written_total
        if n > MAX_SINGLE_ENTRY_BYTES:
            raise ArchiveTooLargeError(
                f"repack entry {arcname!r} is {n} bytes, "
                f"exceeds per-entry limit {MAX_SINGLE_ENTRY_BYTES}"
            )
        written_total += n
        if written_total > MAX_EXTRACTED_BYTES:
            raise ArchiveTooLargeError(
                f"repack reached {written_total} uncompressed bytes, "
                f"exceeds total limit {MAX_EXTRACTED_BYTES}"
            )

    if ext == ".zip":
        # ``strict_timestamps=False`` makes Python clamp file mtimes outside
        # the ZIP-supported range (1980-01-01 .. 2107-12-31) to the boundary
        # rather than raising. TAR/TGZ archives legally carry pre-1980 mtimes
        # (epoch 0 in reproducible builds), and without this flag ``zf.write``
        # rejects them and the whole conversion fails.
        with zipfile.ZipFile(
            dst, "w", compression=zipfile.ZIP_DEFLATED, strict_timestamps=False
        ) as zf:
            for path in sorted(src.rglob("*")):
                arcname = str(path.relative_to(src))
                if path.is_symlink():
                    # Refuse to dereference. A symlink in the extracted tree
                    # would be silently inlined as the target's bytes — and
                    # many symlinks pointing at one large file would amplify
                    # the output past the cap.
                    raise RuntimeError(
                        f"Refusing to repack filesystem symlink: {arcname!r}"
                    )
                if path.is_dir():
                    # ZIP marks a directory entry by trailing slash + size 0.
                    # Empty source dirs would otherwise be silently dropped.
                    _check_member()
                    zf.writestr(arcname.rstrip("/") + "/", "")
                elif path.is_file():
                    _check_member()
                    _check_bytes(path.stat().st_size, arcname)
                    zf.write(path, arcname=arcname)
    elif _is_tar_like(ext):
        # Add files and directories individually (recursive=False) — letting
        # tarfile walk directories on its own would double-add their contents.
        # Directory entries are emitted explicitly so empty dirs survive.
        with tarfile.open(dst, _tar_mode(ext, write=True)) as tf:
            for path in sorted(src.rglob("*")):
                arcname = str(path.relative_to(src))
                if path.is_symlink():
                    raise RuntimeError(
                        f"Refusing to repack filesystem symlink: {arcname!r}"
                    )
                if path.is_dir():
                    _check_member()
                    tf.add(str(path), arcname=arcname, recursive=False)
                elif path.is_file():
                    _check_member()
                    _check_bytes(path.stat().st_size, arcname)
                    tf.add(str(path), arcname=arcname, recursive=False)
    else:
        raise RuntimeError(f"Unsupported archive output: {ext}")


class ArchiveWorker(BaseConverterWorker):
    def _convert(self) -> None:
        in_ext = self.input_path.suffix.lower()
        out_ext = self.output_path.suffix.lower()
        if in_ext not in (".zip", ".tar", ".tgz", ".gz"):
            raise RuntimeError(f"ArchiveWorker cannot read {in_ext}")
        if out_ext not in (".zip", ".tar", ".tgz", ".gz"):
            raise RuntimeError(f"ArchiveWorker cannot write {out_ext}")

        self.progress.emit(10)

        with tempfile.TemporaryDirectory(prefix="cove-arch-") as tmp:
            tmp_path = Path(tmp)
            _extract_to(self.input_path, tmp_path)
            self.progress.emit(55)
            _pack_from(tmp_path, self.output_path)

        self.progress.emit(90)


# tools that import shutil during pack/unpack get pulled in; keep the
# explicit import so static analysis doesn't flag the helper above.
_ = shutil

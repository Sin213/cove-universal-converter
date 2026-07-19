"""Auto-updater backed by the GitHub releases API.

Philosophy: never silently replace the user's binary. A background thread
polls the releases API on startup; when a newer version is published, the
user gets a dialog and chooses whether to install.

AppImage installs can do the download-and-swap end-to-end (the kernel keeps
the running mmap alive across an overwrite, so replacing the file on disk
and re-execing works). Windows Setup, Portable, and .deb just open the
GitHub release page — the user runs the installer themselves.

Usage from a MainWindow:

    from . import updater
    from . import __version__

    self._updater = updater.UpdateController(
        parent=self,
        current_version=__version__,
        repo="Sin213/cove-universal-converter",
        app_display_name="Cove Universal Converter",
        cache_subdir="cove-universal-converter",
    )
    QTimer.singleShot(4000, self._updater.check)
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QMessageBox, QProgressDialog

from .system_open import open_url as _open_url


@dataclass
class UpdateInfo:
    latest_version: str
    release_url: str
    asset_name: str | None = None
    asset_url: str | None = None
    asset_size: int = 0


def _parse_version(v: str) -> tuple[int, ...]:
    """Parse a dotted version into a comparable tuple of ints.

    Handles any number of components (``1.2.3.4`` no longer truncates to
    ``1.2.3``). Non-digit suffixes within a component are ignored
    (``1.2.1+build5`` parses as ``1.2.1`` — pre-release/build metadata does
    not participate in ordering). Trailing zero components are stripped so
    ``1.2.3.0`` compares equal to ``1.2.3``."""
    v = v.strip().lstrip("vV")
    out: list[int] = []
    for part in v.split("."):
        digits = ""
        for ch in part:
            if ch.isdigit():
                digits += ch
            else:
                break
        out.append(int(digits) if digits else 0)
    while len(out) > 3 and out[-1] == 0:
        out.pop()
    while len(out) < 3:
        out.append(0)
    return tuple(out)


def version_newer(latest: str, current: str) -> bool:
    return _parse_version(latest) > _parse_version(current)


def bundle_kind() -> str:
    """Detect how this instance was packaged so we can pick the matching
    release asset for in-place update."""
    if os.environ.get("APPIMAGE"):
        return "appimage"
    if sys.platform == "win32":
        if not getattr(sys, "frozen", False):
            return "source"
        exe_dir = Path(sys.executable).resolve().parent
        # Explicit portable markers (the same convention portable.py keys
        # off) beat path heuristics — a Portable.exe kept under a path
        # containing "Program Files" must not be classified win-setup.
        if (exe_dir / "portable.marker").is_file() or (exe_dir / "cove-app-data").is_dir():
            return "win-portable"
        exe_str = str(exe_dir)
        if "Program Files" in exe_str or r"AppData\Local" in exe_str:
            return "win-setup"
        return "win-portable"
    if sys.platform.startswith("linux") and getattr(sys, "frozen", False):
        return "deb"
    return "source"


def preferred_asset(kind: str, assets: list[dict]) -> dict | None:
    def first_match(predicate) -> dict | None:
        return next((a for a in assets if predicate(a["name"].lower())), None)

    if kind == "appimage":
        return first_match(lambda n: n.endswith(".appimage"))
    if kind == "deb":
        return first_match(lambda n: n.endswith(".deb"))
    if kind == "win-setup":
        return first_match(lambda n: "setup" in n and n.endswith(".exe"))
    if kind == "win-portable":
        return first_match(lambda n: "portable" in n and n.endswith(".exe"))
    return None


def fetch_latest_release(repo: str, timeout: float = 8.0) -> dict | None:
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/releases/latest",
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"{repo.split('/')[-1]}-updater",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.load(resp)
    except Exception:  # noqa: BLE001
        return None


class UpdateCheckWorker(QObject):
    updateAvailable = Signal(object)   # UpdateInfo
    noUpdate = Signal()
    failed = Signal(str)

    def __init__(self, current_version: str, repo: str) -> None:
        super().__init__()
        self._current = current_version
        self._repo = repo

    def run(self) -> None:
        # Any escape here would leave the thread's event loop running with
        # no quit signal ever emitted, wedging every future check() — treat
        # a malformed API payload the same as an unreachable API.
        try:
            self._run()
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(f"unexpected release payload: {exc}")

    def _run(self) -> None:
        data = fetch_latest_release(self._repo)
        if data is None:
            self.failed.emit("could not reach the releases API")
            return
        tag = data.get("tag_name") or ""
        if not tag:
            self.failed.emit("release had no tag_name")
            return
        latest = tag.lstrip("vV")
        if not version_newer(latest, self._current):
            self.noUpdate.emit()
            return
        assets = data.get("assets") or []
        asset = preferred_asset(bundle_kind(), assets)
        info = UpdateInfo(
            latest_version=latest,
            release_url=(
                data.get("html_url")
                or f"https://github.com/{self._repo}/releases/tag/{tag}"
            ),
            asset_name=asset["name"] if asset else None,
            asset_url=asset["browser_download_url"] if asset else None,
            asset_size=int(asset["size"]) if asset else 0,
        )
        self.updateAvailable.emit(info)


def _parse_sidecar(text: str, asset_name: str) -> str | None:
    """Pull the SHA-256 hex digest for `asset_name` out of a sidecar body.

    Accepts either the bare ``sha256sum <file>`` single-line form
    (``<hex>  <name>``) or a multi-entry SHA256SUMS-style file. Returns the
    lowercase 64-char hex digest, or None if no matching line is found."""
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        if not parts:
            continue
        digest = parts[0].lower()
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            continue
        if len(parts) == 1:
            # Single-token sidecar — caller takes responsibility.
            return digest
        name_field = parts[1].lstrip("*").strip()
        if name_field == asset_name or Path(name_field).name == asset_name:
            return digest
    return None


def _fetch_sidecar(url: str, repo: str, timeout: float = 20.0) -> str:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": f"{repo.split('/')[-1]}-updater"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _hash_file(path: Path, chunk: int = 262144) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            block = f.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


class DownloadWorker(QObject):
    """Stream a URL to a destination file, emitting progress as a percentage.

    Before signalling ``finished``, fetches ``<url>.sha256`` from the same
    release and verifies the downloaded bytes match. A missing sidecar or
    digest mismatch is treated as a hard failure: the partial file is
    deleted and ``failed`` is emitted, so the swap/relaunch path is never
    reached without an end-to-end checksum match.
    """

    progress = Signal(int)           # 0–100
    finished = Signal(str, str)      # (installed/downloaded path, replaced old path or "")
    failed = Signal(str)

    def __init__(
        self,
        url: str,
        dest: Path,
        repo: str,
        asset_name: str,
        install_appimage: bool = False,
    ) -> None:
        super().__init__()
        self._url = url
        self._dest = dest
        self._repo = repo
        self._asset_name = asset_name
        self._install_appimage = install_appimage
        self._verified_digest: str | None = None
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        try:
            req = urllib.request.Request(
                self._url,
                headers={"User-Agent": f"{self._repo.split('/')[-1]}-updater"},
            )
            with urllib.request.urlopen(req, timeout=20) as resp:
                total = int(resp.headers.get("Content-Length") or 0)
                written = 0
                self._dest.parent.mkdir(parents=True, exist_ok=True)
                with open(self._dest, "wb") as f:
                    while True:
                        if self._cancelled:
                            raise RuntimeError("cancelled")
                        chunk = resp.read(262144)
                        if not chunk:
                            break
                        f.write(chunk)
                        written += len(chunk)
                        if total > 0:
                            self.progress.emit(int(written * 100 / total))
            self._verify_checksum()
            if self._install_appimage:
                # Last cancellation point before anything irreversible;
                # the swap also re-hashes right before the move (TOCTOU).
                if self._cancelled:
                    raise RuntimeError("cancelled")
                # Swapping here (worker thread) keeps a large cross-device
                # copy off the GUI thread.
                new_path, old_path = swap_in_appimage(
                    self._dest, expected_sha256=self._verified_digest,
                )
                self.finished.emit(str(new_path), str(old_path))
            else:
                self.finished.emit(str(self._dest), "")
        except Exception as exc:  # noqa: BLE001
            try:
                self._dest.unlink(missing_ok=True)
            except Exception:  # noqa: BLE001
                pass
            self.failed.emit(str(exc))

    def _verify_checksum(self) -> None:
        sidecar_url = f"{self._url}.sha256"
        try:
            body = _fetch_sidecar(sidecar_url, self._repo)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                f"checksum sidecar missing or unreachable ({sidecar_url}): {exc}"
            ) from exc
        expected = _parse_sidecar(body, self._asset_name)
        if not expected:
            raise RuntimeError(
                f"no SHA-256 entry for {self._asset_name!r} in sidecar at {sidecar_url}"
            )
        actual = _hash_file(self._dest)
        if actual != expected:
            raise RuntimeError(
                f"checksum mismatch for {self._asset_name}: "
                f"expected {expected}, got {actual}"
            )
        self._verified_digest = expected


def swap_in_appimage(
    new_path: Path, expected_sha256: str | None = None,
) -> tuple[Path, Path]:
    """Install `new_path` next to the running AppImage under its own
    versioned filename and return ``(new target path, old path)``.

    Keeping the release asset's filename (instead of overwriting the old
    file in place) matches electron-updater semantics and keeps the
    on-disk name truthful - external launchers like Cove Nexus derive the
    installed version from it.

    The old binary is deliberately NOT removed here: the returned second
    path is the rollback copy the caller keeps until the relaunched
    process is confirmed started. When the asset filename matches the
    running AppImage (same-name update), the replace would overwrite the
    only copy of the old bytes, so they are first preserved under a
    ``.cove-rollback`` sibling and that path is returned instead.
    If ``expected_sha256`` is given, the staged file is re-hashed right
    before the final rename so a file swapped under us between download
    verification and install is rejected."""
    current = os.environ.get("APPIMAGE")
    if not current:
        raise RuntimeError("APPIMAGE env var not set - not an AppImage install")
    old = Path(current).resolve()
    target = old.parent / new_path.name
    rollback = old
    made_rollback_copy = False
    tmp = target.with_name(target.name + ".part")
    try:
        if target == old:
            rollback = old.with_name(old.name + ".cove-rollback")
            shutil.copy2(old, rollback)
            made_rollback_copy = True
        shutil.move(str(new_path), str(tmp))
        if expected_sha256 is not None:
            actual = _hash_file(tmp)
            if actual != expected_sha256:
                raise RuntimeError(
                    f"checksum mismatch after staging: "
                    f"expected {expected_sha256}, got {actual}"
                )
        mode = os.stat(tmp).st_mode
        os.chmod(tmp, mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        os.replace(tmp, target)
    except Exception:
        # Never leave stale staging/rollback files next to the install on
        # failure (the old binary itself is untouched at this point).
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        if made_rollback_copy:
            try:
                rollback.unlink(missing_ok=True)
            except OSError:
                pass
        raise
    os.environ["APPIMAGE"] = str(target)
    return target, rollback


def relaunch(path: Path) -> None:
    """Spawn `path` detached from the current process group so it survives
    our own exit — the running process keeps the old binary mmap'd while
    the new one takes over the path on disk."""
    subprocess.Popen(
        [str(path)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        start_new_session=True,
    )


class UpdateController(QObject):
    """Attach to a QMainWindow. Call .check() to kick off a background poll;
    on a newer release it drives the prompt → download → swap → relaunch flow."""

    def __init__(
        self,
        parent,
        current_version: str,
        repo: str,
        app_display_name: str,
        cache_subdir: str,
    ) -> None:
        super().__init__(parent)
        self._parent = parent
        self._current = current_version
        self._repo = repo
        self._display_name = app_display_name
        self._cache_subdir = cache_subdir
        self._thread: QThread | None = None
        self._worker: UpdateCheckWorker | None = None
        self._download_thread: QThread | None = None
        self._download_worker: DownloadWorker | None = None
        self._progress: QProgressDialog | None = None
        self._prompt_shown = False
        app = QApplication.instance()
        if app is not None:
            # Qt destroys parented QThreads on teardown; give in-flight
            # check/download threads a chance to finish first, or the
            # process aborts with "QThread: Destroyed while thread is
            # still running".
            app.aboutToQuit.connect(self._shutdown_threads)

    def _shutdown_threads(self) -> None:
        for worker, thread in (
            (self._worker, self._thread),
            (self._download_worker, self._download_thread),
        ):
            if thread is None:
                continue
            if worker is not None:
                cancel = getattr(worker, "cancel", None)
                if cancel is not None:
                    cancel()
            thread.quit()
            thread.wait(10000)

    def check(self) -> None:
        if self._thread is not None:
            return
        thread = QThread(self)
        worker = UpdateCheckWorker(self._current, self._repo)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.updateAvailable.connect(thread.quit)
        worker.noUpdate.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.updateAvailable.connect(self._on_update_available, Qt.QueuedConnection)
        thread.finished.connect(self._on_check_done, Qt.QueuedConnection)
        self._thread = thread
        self._worker = worker
        thread.start()

    def _on_check_done(self) -> None:
        self._thread = None
        self._worker = None

    def _on_update_available(self, info: UpdateInfo) -> None:
        if self._prompt_shown:
            return
        self._prompt_shown = True
        self._prompt(info)

    def _prompt(self, info: UpdateInfo) -> None:
        kind = bundle_kind()
        can_auto_install = kind == "appimage" and bool(info.asset_url)

        msg = QMessageBox(self._parent)
        msg.setIcon(QMessageBox.Information)
        msg.setWindowTitle(f"{self._display_name} — update available")
        msg.setText(
            f"{self._display_name} v{info.latest_version} is available.\n"
            f"You're running v{self._current}.",
        )
        if can_auto_install:
            msg.setInformativeText(
                f"{info.asset_name} ({info.asset_size // (1024 * 1024)} MB). "
                "The app will restart after the update.",
            )
            install_btn = msg.addButton("Update now", QMessageBox.AcceptRole)
            open_btn = msg.addButton("View release", QMessageBox.HelpRole)
            msg.addButton("Later", QMessageBox.RejectRole)
        else:
            msg.setInformativeText(
                "Open the release page to download the latest installer.",
            )
            install_btn = None
            open_btn = msg.addButton("View release", QMessageBox.AcceptRole)
            msg.addButton("Later", QMessageBox.RejectRole)
        msg.exec()
        clicked = msg.clickedButton()
        if install_btn is not None and clicked is install_btn:
            self._install(info)
        elif open_btn is not None and clicked is open_btn:
            _open_url(info.release_url)

    def _install(self, info: UpdateInfo) -> None:
        if not info.asset_url or not info.asset_name:
            _open_url(info.release_url)
            return
        name = info.asset_name
        # The asset name comes straight from the release JSON; refuse
        # anything that could escape the cache dir when joined below.
        if (not name or name in (".", "..")
                or "/" in name or "\\" in name or ":" in name):
            _open_url(info.release_url)
            return
        cache = Path(os.path.expanduser(f"~/.cache/{self._cache_subdir}"))
        cache.mkdir(parents=True, exist_ok=True)
        dest = cache / name

        self._progress = QProgressDialog(
            f"Downloading {info.asset_name}…", "Cancel", 0, 100, self._parent,
        )
        self._progress.setWindowTitle(f"Updating {self._display_name}")
        self._progress.setAutoClose(False)
        self._progress.setAutoReset(False)
        self._progress.setMinimumDuration(0)
        self._progress.setValue(0)

        thread = QThread(self)
        worker = DownloadWorker(
            info.asset_url, dest, self._repo, name, install_appimage=True,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        # DirectConnection: the worker thread's event loop is blocked inside
        # run() for the whole download, so a (default) queued invocation of
        # cancel() would never be delivered until the download had already
        # finished. cancel() only sets a bool, so calling it from the GUI
        # thread is safe.
        self._progress.canceled.connect(worker.cancel, Qt.DirectConnection)
        worker.progress.connect(self._progress.setValue, Qt.QueuedConnection)
        # Bind the worker into the slot: reading self._download_worker there
        # would race _on_download_thread_done clearing the pointer.
        worker.finished.connect(
            lambda new, rb, w=worker: self._on_downloaded(new, rb, w),
            Qt.QueuedConnection,
        )
        worker.failed.connect(self._on_download_failed, Qt.QueuedConnection)
        thread.finished.connect(self._on_download_thread_done, Qt.QueuedConnection)
        self._download_thread = thread
        self._download_worker = worker
        thread.start()

    def _on_downloaded(
        self, new_path_str: str, rollback_str: str, worker: DownloadWorker,
    ) -> None:
        if self._progress is not None:
            self._progress.close()
        new_path = Path(new_path_str)
        rollback = Path(rollback_str) if rollback_str else None
        # A ``.cove-rollback`` sibling means the update reused the running
        # file's name and the old bytes only survive in that copy.
        same_name = (
            rollback is not None
            and rollback.name.endswith(".cove-rollback")
        )
        def _roll_back() -> None:
            # The old bytes were kept on disk for exactly this case.
            if rollback is None:
                return
            try:
                if same_name:
                    # Restore the old bytes over the overwritten file.
                    os.replace(rollback, new_path)
                else:
                    new_path.unlink(missing_ok=True)
                    os.environ["APPIMAGE"] = str(rollback)
            except OSError:
                pass

        if worker._cancelled:
            # Cancelled between swap completion and this slot: undo the
            # swap so a cancelled update never takes effect, not even on
            # the next launch.
            _roll_back()
            return
        try:
            relaunch(new_path)
        except Exception as exc:  # noqa: BLE001
            _roll_back()
            QMessageBox.warning(
                self._parent, "Update failed",
                f"Couldn't start the updated AppImage:\n{exc}\n"
                "The previous version was kept.",
            )
            return
        # New process is running; now it's safe to drop the old copy
        # (the previous versioned file, or the same-name rollback sibling).
        if rollback is not None and rollback != new_path:
            try:
                rollback.unlink()  # unlinking the running file is fine on Linux
            except OSError:
                pass
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def _on_download_failed(self, msg: str) -> None:
        if self._progress is not None:
            self._progress.close()
        if msg == "cancelled":
            # User-initiated; a warning box would be noise.
            return
        QMessageBox.warning(
            self._parent, "Update failed",
            f"The download didn't complete:\n{msg}",
        )

    def _on_download_thread_done(self) -> None:
        self._download_thread = None
        self._download_worker = None

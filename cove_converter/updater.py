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
        repo="Sin213/cove-pdf-editor",
        app_display_name="Cove PDF Editor",
        cache_subdir="cove-pdf-editor",
    )
    QTimer.singleShot(4000, self._updater.check)
"""
from __future__ import annotations

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


@dataclass
class UpdateInfo:
    latest_version: str
    release_url: str
    asset_name: str | None = None
    asset_url: str | None = None
    asset_size: int = 0


def _parse_version(v: str) -> tuple[int, int, int]:
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
        if len(out) == 3:
            break
    while len(out) < 3:
        out.append(0)
    return (out[0], out[1], out[2])


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
        exe_str = str(Path(sys.executable).resolve())
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


class DownloadWorker(QObject):
    """Stream a URL to a destination file, emitting progress as a percentage."""

    progress = Signal(int)           # 0–100
    finished = Signal(str)           # destination path
    failed = Signal(str)

    def __init__(self, url: str, dest: Path, repo: str) -> None:
        super().__init__()
        self._url = url
        self._dest = dest
        self._repo = repo
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
            self.finished.emit(str(self._dest))
        except Exception as exc:  # noqa: BLE001
            try:
                self._dest.unlink(missing_ok=True)
            except Exception:  # noqa: BLE001
                pass
            self.failed.emit(str(exc))


def swap_in_appimage(new_path: Path) -> Path:
    """Replace the running AppImage with `new_path`, leave it executable, and
    return its final path."""
    current = os.environ.get("APPIMAGE")
    if not current:
        raise RuntimeError("APPIMAGE env var not set — not an AppImage install")
    target = Path(current).resolve()
    shutil.move(str(new_path), str(target))
    mode = os.stat(target).st_mode
    os.chmod(target, mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return target


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
            QDesktopServices.openUrl(QUrl(info.release_url))

    def _install(self, info: UpdateInfo) -> None:
        if not info.asset_url or not info.asset_name:
            QDesktopServices.openUrl(QUrl(info.release_url))
            return
        cache = Path(os.path.expanduser(f"~/.cache/{self._cache_subdir}"))
        cache.mkdir(parents=True, exist_ok=True)
        dest = cache / info.asset_name

        self._progress = QProgressDialog(
            f"Downloading {info.asset_name}…", "Cancel", 0, 100, self._parent,
        )
        self._progress.setWindowTitle(f"Updating {self._display_name}")
        self._progress.setAutoClose(False)
        self._progress.setAutoReset(False)
        self._progress.setMinimumDuration(0)
        self._progress.setValue(0)

        thread = QThread(self)
        worker = DownloadWorker(info.asset_url, dest, self._repo)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        self._progress.canceled.connect(worker.cancel)
        worker.progress.connect(self._progress.setValue, Qt.QueuedConnection)
        worker.finished.connect(self._on_downloaded, Qt.QueuedConnection)
        worker.failed.connect(self._on_download_failed, Qt.QueuedConnection)
        thread.finished.connect(self._on_download_thread_done, Qt.QueuedConnection)
        self._download_thread = thread
        self._download_worker = worker
        thread.start()

    def _on_downloaded(self, path: str) -> None:
        if self._progress is not None:
            self._progress.close()
        try:
            new_path = swap_in_appimage(Path(path))
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(
                self._parent, "Update failed",
                f"Couldn't swap in the new AppImage:\n{exc}",
            )
            return
        relaunch(new_path)
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def _on_download_failed(self, msg: str) -> None:
        if self._progress is not None:
            self._progress.close()
        QMessageBox.warning(
            self._parent, "Update failed",
            f"The download didn't complete:\n{msg}",
        )

    def _on_download_thread_done(self) -> None:
        self._download_thread = None
        self._download_worker = None

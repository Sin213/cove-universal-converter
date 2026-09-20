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
import secrets
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QSignalBlocker, QTimer, Qt, Signal
from PySide6.QtWidgets import QApplication, QMessageBox, QProgressDialog

from .system_open import open_url as _open_url


_API_HOSTS = frozenset({"api.github.com"})
_ASSET_HOSTS = frozenset({
    "github.com",
    "github-releases.githubusercontent.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
})
_MAX_RELEASE_JSON_BYTES = 2 * 1024 * 1024
_MAX_SIDECAR_BYTES = 1024 * 1024
_STARTUP_TOKEN_ENV = "COVE_UPDATE_STARTUP_TOKEN"
_STARTUP_ACK_INTERVAL_MS = 100
_STARTUP_ACK_TIMEOUT_SECONDS = 20.0
_THREAD_SHUTDOWN_JOIN_SECONDS = 0.25
_network_context = threading.local()


def _interrupt_response(response) -> None:
    """Wake a concurrent urllib socket read before closing its response."""
    try:
        sock = getattr(getattr(response.fp, "raw", None), "_sock", None)
        if sock is not None:
            sock.shutdown(socket.SHUT_RDWR)
    except Exception:  # noqa: BLE001
        pass
    try:
        response.close()
    except Exception:  # noqa: BLE001
        pass


class _Cancellation:
    """Thread-safe cancellation that also interrupts an active HTTP read."""

    def __init__(self) -> None:
        self.event = threading.Event()
        self._lock = threading.Lock()
        self._response = None

    def cancel(self) -> None:
        self.event.set()
        with self._lock:
            response = self._response
        if response is not None:
            _interrupt_response(response)

    def track(self, response) -> None:
        with self._lock:
            self._response = response
        if self.event.is_set():
            _interrupt_response(response)
            raise RuntimeError("cancelled")

    def clear(self, response=None) -> None:
        with self._lock:
            if response is None or self._response is response:
                self._response = None


def _startup_ack_path(token: str) -> Path:
    return Path(tempfile.gettempdir()) / f".cove-update-{token}.ready"


def acknowledge_updated_startup() -> None:
    """Acknowledge that an updated process reached the GUI event loop."""
    token = os.environ.pop(_STARTUP_TOKEN_ENV, "")
    if len(token) != 64 or any(char not in "0123456789abcdef" for char in token):
        return
    path = _startup_ack_path(token)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags, 0o600)
        try:
            os.write(fd, token.encode("ascii"))
        finally:
            os.close(fd)
    except OSError:
        # Startup must not fail because an acknowledgement cannot be written.
        # The previous process will time out and retain its binary.
        pass


def _validate_repo(repo: str) -> tuple[str, str]:
    parts = repo.split("/")
    if (
        len(parts) != 2
        or any(part in {"", ".", ".."} for part in parts)
        or any(
            not all(char.isascii() and (char.isalnum() or char in "._-") for char in part)
            for part in parts
        )
    ):
        raise ValueError("invalid GitHub repository name")
    return parts[0], parts[1]


def _validate_https_url(url: str, allowed_hosts: frozenset[str]) -> None:
    if not isinstance(url, str) or any(ord(char) < 32 or ord(char) == 127 for char in url):
        raise ValueError("invalid URL")
    try:
        parsed = urllib.parse.urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("invalid URL") from exc
    hostname = parsed.hostname.casefold() if parsed.hostname else ""
    if (
        parsed.scheme.casefold() != "https"
        or hostname not in allowed_hosts
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
    ):
        raise ValueError("untrusted URL")


class _TrustedRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, allowed_hosts: frozenset[str]) -> None:
        super().__init__()
        self._allowed_hosts = allowed_hosts

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _validate_https_url(newurl, self._allowed_hosts)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open_trusted(
    request: urllib.request.Request,
    timeout: float,
    allowed_hosts: frozenset[str],
):
    _validate_https_url(request.full_url, allowed_hosts)
    opener = urllib.request.build_opener(_TrustedRedirectHandler(allowed_hosts))
    response = opener.open(request, timeout=timeout)  # nosec B310
    cancellation = getattr(_network_context, "cancellation", None)
    if cancellation is not None:
        cancellation.track(response)
    try:
        _validate_https_url(response.geturl(), allowed_hosts)
    except Exception:
        response.close()
        raise
    return response


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


def preferred_asset(kind: str, assets: list[object]) -> dict | None:
    def first_match(predicate) -> dict | None:
        return next(
            (
                asset
                for asset in assets
                if isinstance(asset, dict)
                and isinstance(asset.get("name"), str)
                and predicate(asset["name"].lower())
            ),
            None,
        )

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
    try:
        owner, name = _validate_repo(repo)
        req = urllib.request.Request(
            f"https://api.github.com/repos/{owner}/{name}/releases/latest",
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": f"{name}-updater",
            },
        )
        with _open_trusted(req, timeout, _API_HOSTS) as resp:
            body = resp.read(_MAX_RELEASE_JSON_BYTES + 1)
        if len(body) > _MAX_RELEASE_JSON_BYTES:
            return None
        data = json.loads(body)
        return data if isinstance(data, dict) else None
    except Exception:  # noqa: BLE001
        return None


class UpdateCheckWorker(QObject):
    updateAvailable = Signal(object)   # UpdateInfo
    noUpdate = Signal()
    failed = Signal(str)
    done = Signal()

    def __init__(self, current_version: str, repo: str) -> None:
        super().__init__()
        self._current = current_version
        self._repo = repo
        self._cancellation = _Cancellation()

    def cancel(self) -> None:
        self._cancellation.cancel()

    def run(self) -> None:
        # Treat malformed API payloads like an unreachable API, and always
        # emit done so the controller can permit a later check.
        _network_context.cancellation = self._cancellation
        try:
            self._run()
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(f"unexpected release payload: {exc}")
        finally:
            self._cancellation.clear()
            try:
                del _network_context.cancellation
            except AttributeError:
                pass
            self.done.emit()

    def _run(self) -> None:
        if self._cancellation.event.is_set():
            return
        data = fetch_latest_release(self._repo)
        if data is None:
            self.failed.emit("could not reach the releases API")
            return
        tag = data.get("tag_name")
        if not isinstance(tag, str) or not tag:
            self.failed.emit("release had no tag_name")
            return
        latest = tag.lstrip("vV")
        if not version_newer(latest, self._current):
            self.noUpdate.emit()
            return
        assets = data.get("assets")
        if not isinstance(assets, list):
            assets = []
        asset = preferred_asset(bundle_kind(), assets)
        asset_name = asset.get("name") if asset else None
        asset_url = asset.get("browser_download_url") if asset else None
        asset_size = asset.get("size", 0) if asset else 0
        if not isinstance(asset_name, str) or not isinstance(asset_url, str):
            asset_name = None
            asset_url = None
            asset_size = 0
        else:
            try:
                _validate_https_url(asset_url, _ASSET_HOSTS)
                asset_size = max(0, int(asset_size))
            except (TypeError, ValueError):
                asset_name = None
                asset_url = None
                asset_size = 0
        owner, name = _validate_repo(self._repo)
        release_tag = urllib.parse.quote(tag, safe="")
        info = UpdateInfo(
            latest_version=latest,
            release_url=f"https://github.com/{owner}/{name}/releases/tag/{release_tag}",
            asset_name=asset_name,
            asset_url=asset_url,
            asset_size=asset_size,
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
    _, name = _validate_repo(repo)
    req = urllib.request.Request(
        url,
        headers={"User-Agent": f"{name}-updater"},
    )
    with _open_trusted(req, timeout, _ASSET_HOSTS) as resp:
        body = resp.read(_MAX_SIDECAR_BYTES + 1)
    if len(body) > _MAX_SIDECAR_BYTES:
        raise ValueError("checksum sidecar is too large")
    return body.decode("utf-8", errors="replace")


def _hash_file(path: Path, chunk: int = 262144, cancelled=None) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            if cancelled is not None and cancelled():
                raise RuntimeError("cancelled")
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
    done = Signal()

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
        self._cancellation = _Cancellation()
        # Serializes cancel() against the swap-then-decide step below so the
        # decision to keep or roll back a completed swap is atomic with the
        # cancellation flag: cancel() either lands before the decision (seen
        # as True, rolled back) or blocks until finished has been queued.
        #
        # Accepted residual limitation: both this lock's acquisition in
        # cancel() and the shutdown join around it are bounded (see
        # _THREAD_SHUTDOWN_JOIN_SECONDS), by design - shutdown must not hang
        # indefinitely. If the code inside the lock (a local file rename or
        # a Qt signal emit) ever took longer than that bound, a decision
        # could still be mid-flight when the interpreter exits and daemon
        # threads are cut off. This requires an anomalously slow local
        # rename/emit (well beyond normal disk I/O) and has no bounded-wait
        # fix; closing it fully would need a durable on-disk journal a
        # future startup could use to self-heal. Accepted as out of scope
        # for this fix; not expected to occur under normal conditions.
        self._commit_lock = threading.Lock()

    def cancel(self) -> None:
        # Bounded: if the worker is holding the lock mid swap-commit
        # decision, wait for it to finish (so the flag it observes matches
        # the one it will act on) but never block shutdown indefinitely.
        acquired = self._commit_lock.acquire(timeout=_THREAD_SHUTDOWN_JOIN_SECONDS)
        try:
            self._cancelled = True
        finally:
            if acquired:
                self._commit_lock.release()
        self._cancellation.cancel()

    def run(self) -> None:
        _network_context.cancellation = self._cancellation
        try:
            _, repo_name = _validate_repo(self._repo)
            req = urllib.request.Request(
                self._url,
                headers={"User-Agent": f"{repo_name}-updater"},
            )
            with _open_trusted(req, 20, _ASSET_HOSTS) as resp:
                self._cancellation.track(resp)
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
                    cancelled=lambda: self._cancelled,
                )
                with self._commit_lock:
                    if self._cancelled:
                        UpdateController._roll_back_appimage(new_path, old_path)
                        raise RuntimeError("cancelled")
                    self.finished.emit(str(new_path), str(old_path))
            else:
                self.finished.emit(str(self._dest), "")
        except Exception as exc:  # noqa: BLE001
            try:
                self._dest.unlink(missing_ok=True)
            except Exception:  # noqa: BLE001
                pass
            self.failed.emit("cancelled" if self._cancelled else str(exc))
        finally:
            self._cancellation.clear()
            try:
                del _network_context.cancellation
            except AttributeError:
                pass
            self.done.emit()

    def _verify_checksum(self) -> None:
        if self._cancelled:
            raise RuntimeError("cancelled")
        parsed_url = urllib.parse.urlsplit(self._url)
        sidecar_url = urllib.parse.urlunsplit(
            parsed_url._replace(path=f"{parsed_url.path}.sha256")
        )
        try:
            body = _fetch_sidecar(sidecar_url, self._repo)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                f"checksum sidecar missing or unreachable ({sidecar_url}): {exc}"
            ) from exc
        if self._cancelled:
            raise RuntimeError("cancelled")
        expected = _parse_sidecar(body, self._asset_name)
        if not expected:
            raise RuntimeError(
                f"no SHA-256 entry for {self._asset_name!r} in sidecar at {sidecar_url}"
            )
        actual = _hash_file(self._dest, cancelled=lambda: self._cancelled)
        if actual != expected:
            raise RuntimeError(
                f"checksum mismatch for {self._asset_name}: "
                f"expected {expected}, got {actual}"
            )
        self._verified_digest = expected


def swap_in_appimage(
    new_path: Path, expected_sha256: str | None = None,
    *, cancelled=None,
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
        if cancelled and cancelled():
            raise RuntimeError("cancelled")
        if target == old:
            rollback = old.with_name(old.name + ".cove-rollback")
            shutil.copy2(old, rollback)
            made_rollback_copy = True
        if cancelled and cancelled():
            raise RuntimeError("cancelled")
        shutil.move(str(new_path), str(tmp))
        if expected_sha256 is not None:
            actual = _hash_file(tmp, cancelled=cancelled)
            if actual != expected_sha256:
                raise RuntimeError(
                    f"checksum mismatch after staging: "
                    f"expected {expected_sha256}, got {actual}"
                )
        mode = os.stat(tmp).st_mode
        os.chmod(tmp, mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        if cancelled and cancelled():
            raise RuntimeError("cancelled")
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


def relaunch(path: Path, startup_token: str | None = None) -> subprocess.Popen:
    """Spawn `path` detached from the current process group so it survives
    our own exit — the running process keeps the old binary mmap'd while
    the new one takes over the path on disk."""
    env = os.environ.copy()
    if startup_token is not None:
        env[_STARTUP_TOKEN_ENV] = startup_token
    return subprocess.Popen(
        [str(path)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        start_new_session=True,
        env=env,
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
        self._thread: threading.Thread | None = None
        self._worker: UpdateCheckWorker | None = None
        self._download_thread: threading.Thread | None = None
        self._download_worker: DownloadWorker | None = None
        self._progress: QProgressDialog | None = None
        self._prompt_shown = False
        self._relaunch_process: subprocess.Popen | None = None
        self._relaunch_timer: QTimer | None = None
        self._relaunch_token: str | None = None
        self._relaunch_deadline = 0.0
        self._relaunch_new_path: Path | None = None
        self._relaunch_rollback: Path | None = None
        self._shutting_down = False
        app = QApplication.instance()
        if app is not None:
            # Active responses are closed first. The bounded joins allow the
            # common path to clean up while daemon threads keep a slow DNS or
            # connect syscall from owning Qt objects during application exit.
            app.aboutToQuit.connect(self._shutdown_threads)

    def _shutdown_threads(self) -> None:
        # Flushing queued events below can deliver an already-pending
        # updateAvailable signal; block any handler that would show a new
        # modal prompt or start a new download during shutdown.
        self._shutting_down = True
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
            # cancel() (above) already waits, bounded, for an in-flight
            # swap-commit decision to finish before returning, so by this
            # point the worker's decision (finish or roll back) is settled
            # in the common case; this join only waits for its thread
            # object to fully terminate.
            thread.join(_THREAD_SHUTDOWN_JOIN_SECONDS)
        app = QApplication.instance()
        if app is not None:
            # A worker that finished (including a same-name swap already
            # written to disk) just before shutdown began has its
            # finished/failed signal queued but not yet delivered. Flush it
            # now so cancel()'s effect on _cancelled is observed by
            # _on_downloaded and an unacknowledged swap is rolled back
            # instead of left installed.
            app.processEvents()
        if self._relaunch_process is not None:
            # The child may have written its acknowledgement between the
            # last poll tick and shutdown starting. Check it directly rather
            # than unconditionally discarding an already-successful install.
            token = self._relaunch_token
            acknowledged = False
            if token is not None:
                try:
                    acknowledged = (
                        _startup_ack_path(token).read_text("ascii") == token
                    )
                except (OSError, UnicodeDecodeError):
                    acknowledged = False
            if acknowledged:
                self._finish_relaunch_success()
            else:
                self._finish_relaunch_failure("startup was cancelled", warn=False)

    def check(self) -> None:
        if self._shutting_down or self._thread is not None:
            return
        worker = UpdateCheckWorker(self._current, self._repo)
        thread = threading.Thread(
            target=worker.run,
            name="cove-update-check",
            daemon=True,
        )
        worker.updateAvailable.connect(
            self._on_update_available, Qt.ConnectionType.QueuedConnection
        )
        worker.done.connect(
            self._on_check_done, Qt.ConnectionType.QueuedConnection
        )
        self._thread = thread
        self._worker = worker
        thread.start()

    def _on_check_done(self) -> None:
        self._thread = None
        self._worker = None

    def _on_update_available(self, info: UpdateInfo) -> None:
        if self._shutting_down or self._prompt_shown:
            return
        self._prompt_shown = True
        self._prompt(info)

    def _prompt(self, info: UpdateInfo) -> None:
        kind = bundle_kind()
        can_auto_install = kind == "appimage" and bool(info.asset_url)

        msg = QMessageBox(self._parent)
        msg.setIcon(QMessageBox.Icon.Information)
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
            install_btn = msg.addButton(
                "Update now", QMessageBox.ButtonRole.AcceptRole
            )
            open_btn = msg.addButton(
                "View release", QMessageBox.ButtonRole.HelpRole
            )
            msg.addButton("Later", QMessageBox.ButtonRole.RejectRole)
        else:
            msg.setInformativeText(
                "Open the release page to download the latest installer.",
            )
            install_btn = None
            open_btn = msg.addButton(
                "View release", QMessageBox.ButtonRole.AcceptRole
            )
            msg.addButton("Later", QMessageBox.ButtonRole.RejectRole)
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

        worker = DownloadWorker(
            info.asset_url, dest, self._repo, name, install_appimage=True,
        )
        thread = threading.Thread(
            target=worker.run,
            name="cove-update-download",
            daemon=True,
        )
        # cancel() is thread-safe and closes the active response, allowing a
        # blocked network read to return promptly during user cancellation.
        self._progress.canceled.connect(
            worker.cancel, Qt.ConnectionType.DirectConnection
        )
        worker.progress.connect(
            self._progress.setValue, Qt.ConnectionType.QueuedConnection
        )
        # Bind the worker into the slot: reading self._download_worker there
        # would race _on_download_thread_done clearing the pointer.
        worker.finished.connect(
            lambda new, rb, w=worker: self._on_downloaded(new, rb, w),
            Qt.ConnectionType.QueuedConnection,
        )
        worker.failed.connect(
            self._on_download_failed, Qt.ConnectionType.QueuedConnection
        )
        worker.done.connect(
            self._on_download_thread_done, Qt.ConnectionType.QueuedConnection
        )
        self._download_thread = thread
        self._download_worker = worker
        thread.start()

    def _on_downloaded(
        self, new_path_str: str, rollback_str: str, worker: DownloadWorker,
    ) -> None:
        self._close_progress()
        new_path = Path(new_path_str)
        rollback = Path(rollback_str) if rollback_str else None
        if worker._cancelled:
            # Cancelled between swap completion and this slot: undo the
            # swap so a cancelled update never takes effect, not even on
            # the next launch.
            self._roll_back_appimage(new_path, rollback)
            return
        token = secrets.token_hex(32)
        ack_path = _startup_ack_path(token)
        try:
            ack_path.unlink(missing_ok=True)
        except OSError:
            pass
        try:
            process = relaunch(new_path, token)
        except Exception as exc:  # noqa: BLE001
            self._roll_back_appimage(new_path, rollback)
            QMessageBox.warning(
                self._parent, "Update failed",
                f"Couldn't start the updated AppImage:\n{exc}\n"
                "The previous version was kept.",
            )
            return

        # Popen succeeding only proves exec was attempted. Keep the rollback
        # binary until the replacement reaches its GUI event loop and writes
        # the launch-specific acknowledgement token.
        self._relaunch_process = process
        self._relaunch_token = token
        self._relaunch_deadline = time.monotonic() + _STARTUP_ACK_TIMEOUT_SECONDS
        self._relaunch_new_path = new_path
        self._relaunch_rollback = rollback
        timer = QTimer(self)
        timer.setInterval(_STARTUP_ACK_INTERVAL_MS)
        timer.timeout.connect(self._poll_relaunch)
        self._relaunch_timer = timer
        timer.start()

    @staticmethod
    def _roll_back_appimage(new_path: Path, rollback: Path | None) -> None:
        if rollback is None:
            return
        try:
            if rollback.name.endswith(".cove-rollback"):
                os.replace(rollback, new_path)
                os.environ["APPIMAGE"] = str(new_path)
            else:
                new_path.unlink(missing_ok=True)
                os.environ["APPIMAGE"] = str(rollback)
        except OSError:
            pass

    def _poll_relaunch(self) -> None:
        if self._shutting_down:
            # _shutdown_threads owns the pending relaunch during shutdown
            # (it does its own ack check); a timer tick flushed by its
            # event-processing pass must not race that or show a dialog.
            return
        process = self._relaunch_process
        token = self._relaunch_token
        if process is None or token is None:
            return
        try:
            exit_code = process.poll()
        except Exception as exc:  # noqa: BLE001
            self._finish_relaunch_failure(f"couldn't monitor startup: {exc}")
            return
        if exit_code is not None:
            self._finish_relaunch_failure(
                f"the updated AppImage exited during startup (code {exit_code})"
            )
            return
        try:
            acknowledged = _startup_ack_path(token).read_text("ascii") == token
        except (OSError, UnicodeDecodeError):
            acknowledged = False
        if acknowledged:
            self._finish_relaunch_success()
        elif time.monotonic() >= self._relaunch_deadline:
            self._finish_relaunch_failure(
                "the updated AppImage did not finish starting in time"
            )

    def _clear_relaunch_state(self) -> tuple[Path | None, Path | None]:
        timer = self._relaunch_timer
        if timer is not None:
            timer.stop()
            timer.deleteLater()
        token = self._relaunch_token
        if token is not None:
            try:
                _startup_ack_path(token).unlink(missing_ok=True)
            except OSError:
                pass
        new_path = self._relaunch_new_path
        rollback = self._relaunch_rollback
        self._relaunch_process = None
        self._relaunch_timer = None
        self._relaunch_token = None
        self._relaunch_new_path = None
        self._relaunch_rollback = None
        return new_path, rollback

    def _finish_relaunch_success(self) -> None:
        _new_path, rollback = self._clear_relaunch_state()
        if rollback is not None:
            try:
                rollback.unlink(missing_ok=True)
            except OSError:
                pass
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def _finish_relaunch_failure(self, reason: str, *, warn: bool = True) -> None:
        process = self._relaunch_process
        if process is not None:
            try:
                if process.poll() is None:
                    process.terminate()
            except Exception:  # noqa: BLE001
                pass
        new_path, rollback = self._clear_relaunch_state()
        if new_path is not None:
            self._roll_back_appimage(new_path, rollback)
        if warn:
            QMessageBox.warning(
                self._parent,
                "Update failed",
                f"{reason}.\nThe previous version was restored.",
            )

    def _on_download_failed(self, msg: str) -> None:
        self._close_progress()
        if msg == "cancelled" or self._shutting_down:
            # User-initiated, or delivered by shutdown's event flush: a
            # modal dialog must not block application exit.
            return
        QMessageBox.warning(
            self._parent, "Update failed",
            f"The download didn't complete:\n{msg}",
        )

    def _close_progress(self) -> None:
        if self._progress is not None:
            # QProgressDialog.close() emits canceled, even on successful
            # completion. Closing our own UI must not cancel/roll back the
            # worker that just finished installing the update.
            with QSignalBlocker(self._progress):
                self._progress.close()

    def _on_download_thread_done(self) -> None:
        self._download_thread = None
        self._download_worker = None

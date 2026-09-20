import os
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QProgressDialog

from cove_converter import updater


_APP = QApplication.instance() or QApplication([])


class _Process:
    def __init__(self) -> None:
        self.returncode = None
        self.terminated = False

    def poll(self):
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True


def _controller() -> updater.UpdateController:
    return updater.UpdateController(
        None, "1.0.0", "owner/repo", "Cove", "cove-test"
    )


def test_relaunch_keeps_rollback_until_explicit_startup_ack(
    tmp_path: Path, monkeypatch,
) -> None:
    old_path = tmp_path / "Cove-1.0.AppImage"
    new_path = tmp_path / "Cove-2.0.AppImage"
    old_path.write_bytes(b"old")
    new_path.write_bytes(b"new")
    process = _Process()
    monkeypatch.setenv("APPIMAGE", str(new_path))
    monkeypatch.setattr(updater, "_startup_ack_path", lambda token: tmp_path / token)
    monkeypatch.setattr(updater, "relaunch", lambda path, token: process)
    controller = _controller()

    controller._on_downloaded(
        str(new_path), str(old_path), SimpleNamespace(_cancelled=False)
    )

    assert old_path.read_bytes() == b"old"
    controller._poll_relaunch()
    assert old_path.exists(), "a live process without an acknowledgement is not healthy"

    token = controller._relaunch_token
    assert token is not None
    (tmp_path / token).write_text(token, encoding="ascii")
    controller._poll_relaunch()

    assert not old_path.exists()
    assert new_path.read_bytes() == b"new"
    assert not process.terminated


def test_shutdown_with_valid_unread_ack_completes_success_not_rollback(
    tmp_path: Path, monkeypatch,
) -> None:
    """The child may write its acknowledgement between the last poll tick
    and shutdown starting. Shutdown must check it directly rather than
    unconditionally discarding an already-successful install."""
    old_path = tmp_path / "Cove-1.0.AppImage"
    new_path = tmp_path / "Cove-2.0.AppImage"
    old_path.write_bytes(b"old")
    new_path.write_bytes(b"new")
    process = _Process()
    monkeypatch.setenv("APPIMAGE", str(new_path))
    monkeypatch.setattr(updater, "_startup_ack_path", lambda token: tmp_path / token)
    monkeypatch.setattr(updater, "relaunch", lambda path, token: process)
    controller = _controller()
    controller._on_downloaded(
        str(new_path), str(old_path), SimpleNamespace(_cancelled=False)
    )
    token = controller._relaunch_token
    assert token is not None
    (tmp_path / token).write_text(token, encoding="ascii")

    controller._shutdown_threads()

    assert not old_path.exists(), "a valid unread ack must be treated as success"
    assert new_path.read_bytes() == b"new"
    assert not process.terminated


def test_shutdown_waits_bounded_for_in_flight_commit_decision(
    tmp_path: Path, monkeypatch,
) -> None:
    old_path = tmp_path / "old.AppImage"
    new_path = tmp_path / "new.AppImage"
    old_path.write_bytes(b"old")
    new_path.write_bytes(b"new")
    worker = updater.DownloadWorker(
        "https://github.com/owner/repo/new.AppImage", new_path,
        "owner/repo", "new.AppImage",
    )
    started_decision = threading.Event()
    release_decision = threading.Event()
    rolled_back = threading.Event()

    def fake_run() -> None:
        with worker._commit_lock:
            started_decision.set()
            release_decision.wait(2)
            if worker._cancelled:
                updater.UpdateController._roll_back_appimage(new_path, old_path)
                rolled_back.set()

    controller = _controller()
    controller._download_worker = worker
    controller._download_thread = threading.Thread(target=fake_run)
    controller._download_thread.start()
    assert started_decision.wait(1)

    def release_after_delay() -> None:
        # Longer than one _THREAD_SHUTDOWN_JOIN_SECONDS window (0.25s) but
        # within cancel()'s bounded lock-acquire wait for the same value.
        time.sleep(updater._THREAD_SHUTDOWN_JOIN_SECONDS * 1.4)
        release_decision.set()

    threading.Thread(target=release_after_delay).start()

    controller._shutdown_threads()

    assert rolled_back.is_set(), (
        "shutdown returned before the in-flight commit decision finished"
    )
    assert not new_path.exists()
    assert old_path.read_bytes() == b"old"


def test_relaunch_exit_before_ack_restores_previous_appimage(
    tmp_path: Path, monkeypatch,
) -> None:
    old_path = tmp_path / "Cove-1.0.AppImage"
    new_path = tmp_path / "Cove-2.0.AppImage"
    old_path.write_bytes(b"old")
    new_path.write_bytes(b"new")
    process = _Process()
    monkeypatch.setenv("APPIMAGE", str(new_path))
    monkeypatch.setattr(updater, "_startup_ack_path", lambda token: tmp_path / token)
    monkeypatch.setattr(updater, "relaunch", lambda path, token: process)
    controller = _controller()
    controller._on_downloaded(
        str(new_path), str(old_path), SimpleNamespace(_cancelled=False)
    )

    process.returncode = 1
    with patch.object(updater.QMessageBox, "warning") as warning:
        controller._poll_relaunch()

    assert old_path.read_bytes() == b"old"
    assert not new_path.exists()
    assert os.environ["APPIMAGE"] == str(old_path)
    assert "code 1" in warning.call_args.args[2]


def test_relaunch_timeout_terminates_child_and_rolls_back(
    tmp_path: Path, monkeypatch,
) -> None:
    old_path = tmp_path / "Cove-1.0.AppImage"
    new_path = tmp_path / "Cove-2.0.AppImage"
    old_path.write_bytes(b"old")
    new_path.write_bytes(b"new")
    process = _Process()
    monkeypatch.setenv("APPIMAGE", str(new_path))
    monkeypatch.setattr(updater, "_startup_ack_path", lambda token: tmp_path / token)
    monkeypatch.setattr(updater, "relaunch", lambda path, token: process)
    controller = _controller()
    controller._on_downloaded(
        str(new_path), str(old_path), SimpleNamespace(_cancelled=False)
    )
    controller._relaunch_deadline = 0.0

    with patch.object(updater.QMessageBox, "warning"):
        controller._poll_relaunch()

    assert process.terminated
    assert old_path.read_bytes() == b"old"
    assert not new_path.exists()


def test_startup_ack_uses_valid_launch_token(tmp_path: Path, monkeypatch) -> None:
    token = "a" * 64
    monkeypatch.setenv(updater._STARTUP_TOKEN_ENV, token)
    monkeypatch.setattr(updater, "_startup_ack_path", lambda value: tmp_path / value)

    updater.acknowledge_updated_startup()

    assert (tmp_path / token).read_text("ascii") == token
    assert updater._STARTUP_TOKEN_ENV not in os.environ


def test_successful_download_dialog_close_does_not_cancel_install(tmp_path, monkeypatch):
    old_path, new_path = tmp_path / "old.AppImage", tmp_path / "new.AppImage"
    old_path.write_bytes(b"old")
    new_path.write_bytes(b"new")
    monkeypatch.setattr(updater, "relaunch", lambda path, token: _Process())
    monkeypatch.setattr(updater, "_startup_ack_path", lambda token: tmp_path / token)
    worker = updater.DownloadWorker(
        "https://github.com/owner/repo/new.AppImage", new_path,
        "owner/repo", "new.AppImage",
    )
    controller = _controller()
    progress = QProgressDialog("Downloading", "Cancel", 0, 100)
    progress.setAutoClose(False)
    progress.setMinimumDuration(0)
    progress.setValue(0)
    progress.canceled.connect(worker.cancel)
    controller._progress = progress
    controller._on_downloaded(str(new_path), str(old_path), worker)
    assert not worker._cancelled
    assert controller._relaunch_process is not None
    assert old_path.exists() and new_path.exists()
    controller._finish_relaunch_failure("test cleanup", warn=False)


def test_download_cancel_closes_blocked_response_and_finishes(
    tmp_path: Path, monkeypatch,
) -> None:
    class BlockingResponse:
        headers = {}

        def __init__(self) -> None:
            self.read_started = threading.Event()
            self.closed = threading.Event()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.close()

        def read(self, _size):
            self.read_started.set()
            self.closed.wait(2)
            raise OSError("response closed")

        def close(self) -> None:
            self.closed.set()

    response = BlockingResponse()
    worker = updater.DownloadWorker(
        "https://github.com/owner/repo/Cove.AppImage",
        tmp_path / "Cove.AppImage",
        "owner/repo",
        "Cove.AppImage",
    )
    failures = []
    worker.failed.connect(failures.append)
    monkeypatch.setattr(updater, "_open_trusted", lambda *args: response)
    thread = threading.Thread(target=worker.run)
    thread.start()
    assert response.read_started.wait(1)

    worker.cancel()
    thread.join(1)
    _APP.processEvents()

    assert not thread.is_alive()
    assert response.closed.is_set()
    assert failures == ["cancelled"]
    assert not (tmp_path / "Cove.AppImage").exists()


def test_shutdown_wait_is_bounded_and_cancels_workers() -> None:
    class Worker:
        def __init__(self) -> None:
            self.cancelled = False

        def cancel(self) -> None:
            self.cancelled = True

    class Thread:
        def __init__(self) -> None:
            self.joins = []

        def join(self, timeout) -> None:
            self.joins.append(timeout)

    controller = _controller()
    check_worker, download_worker = Worker(), Worker()
    check_thread, download_thread = Thread(), Thread()
    controller._worker = check_worker
    controller._thread = check_thread
    controller._download_worker = download_worker
    controller._download_thread = download_thread

    controller._shutdown_threads()

    assert check_worker.cancelled and download_worker.cancelled
    assert isinstance(updater._THREAD_SHUTDOWN_JOIN_SECONDS, (int, float))
    assert 0 < updater._THREAD_SHUTDOWN_JOIN_SECONDS <= 5
    assert check_thread.joins == [updater._THREAD_SHUTDOWN_JOIN_SECONDS]
    assert download_thread.joins == [updater._THREAD_SHUTDOWN_JOIN_SECONDS]


def test_interrupt_response_shuts_down_underlying_socket() -> None:
    class FakeSock:
        def __init__(self) -> None:
            self.shutdown_arg = None

        def shutdown(self, how) -> None:
            self.shutdown_arg = how

    class FakeRaw:
        def __init__(self, sock) -> None:
            self._sock = sock

    class FakeFp:
        def __init__(self, sock) -> None:
            self.raw = FakeRaw(sock)

    class FakeResponse:
        def __init__(self, sock) -> None:
            self.fp = FakeFp(sock)
            self.closed = False

        def close(self) -> None:
            self.closed = True

    import socket

    sock = FakeSock()
    response = FakeResponse(sock)

    updater._interrupt_response(response)

    assert sock.shutdown_arg == socket.SHUT_RDWR
    assert response.closed


def test_relaunch_forwards_startup_token_to_child_env(tmp_path: Path, monkeypatch) -> None:
    captured = {}

    def fake_popen(args, **kwargs):
        captured["env"] = kwargs.get("env")
        return _Process()

    monkeypatch.setattr(updater.subprocess, "Popen", fake_popen)
    token = "b" * 64

    updater.relaunch(tmp_path / "Cove.AppImage", token)

    assert captured["env"][updater._STARTUP_TOKEN_ENV] == token


def test_shutdown_rolls_back_swap_completed_just_before_quit(
    tmp_path: Path, monkeypatch,
) -> None:
    """A same-name swap that finished (and posted its `finished` signal) an
    instant before app shutdown must be rolled back, not left installed,
    even though `_on_downloaded` never had a chance to run beforehand."""
    old_path = tmp_path / "Cove.AppImage"
    new_path = tmp_path / "Cove.AppImage.new"
    old_path.write_bytes(b"old")
    new_path.write_bytes(b"new")
    monkeypatch.setattr(updater, "relaunch", lambda path, token: _Process())
    monkeypatch.setattr(updater, "_startup_ack_path", lambda token: tmp_path / token)

    worker = updater.DownloadWorker(
        "https://github.com/owner/repo/Cove.AppImage",
        new_path, "owner/repo", "Cove.AppImage",
    )
    controller = _controller()
    controller._download_worker = worker
    controller._download_thread = threading.Thread(target=lambda: None)
    controller._download_thread.start()
    controller._download_thread.join()

    # Simulate the worker already having succeeded and queued its
    # `finished` signal for delivery, exactly as production wires it
    # (QueuedConnection), right before an aboutToQuit-triggered shutdown.
    # The queued emit does not invoke the slot yet - only processEvents()
    # inside _shutdown_threads should deliver it.
    worker.finished.connect(
        lambda new, rb, w=worker: controller._on_downloaded(new, rb, w),
        updater.Qt.ConnectionType.QueuedConnection,
    )
    worker.finished.emit(str(new_path), str(old_path))

    controller._shutdown_threads()

    assert old_path.read_bytes() == b"old"
    assert controller._relaunch_process is None
    assert not new_path.exists(), (
        "queued finished signal was never delivered - _on_downloaded did not "
        "run, so the swap was neither confirmed nor rolled back"
    )


def test_cancellation_after_rollback_copy_aborts_before_move(tmp_path, monkeypatch):
    import shutil

    installed = tmp_path / "install"
    cache = tmp_path / "cache"
    installed.mkdir()
    cache.mkdir()
    old, new = installed / "Cove.AppImage", cache / "Cove.AppImage"
    old.write_bytes(b"working version")
    new.write_bytes(b"replacement")
    monkeypatch.setenv("APPIMAGE", str(old))
    cancelled = threading.Event()
    copy2 = shutil.copy2

    def cancel_after_rollback_copy(source, dest):
        result = copy2(source, dest)
        cancelled.set()
        return result

    def failing_move(source, dest):
        raise AssertionError("move must not run once cancelled")

    monkeypatch.setattr(updater.shutil, "copy2", cancel_after_rollback_copy)
    monkeypatch.setattr(updater.shutil, "move", failing_move)
    import pytest
    with pytest.raises(RuntimeError, match="cancelled"):
        updater.swap_in_appimage(new, cancelled=cancelled.is_set)
    assert old.read_bytes() == b"working version"
    assert not list(installed.glob("*.part"))
    assert not list(installed.glob("*.cove-rollback"))


def test_ack_read_with_invalid_encoding_does_not_block_timeout(
    tmp_path: Path, monkeypatch,
) -> None:
    old_path = tmp_path / "Cove-1.0.AppImage"
    new_path = tmp_path / "Cove-2.0.AppImage"
    old_path.write_bytes(b"old")
    new_path.write_bytes(b"new")
    process = _Process()
    monkeypatch.setenv("APPIMAGE", str(new_path))
    monkeypatch.setattr(updater, "_startup_ack_path", lambda token: tmp_path / token)
    monkeypatch.setattr(updater, "relaunch", lambda path, token: process)
    controller = _controller()
    controller._on_downloaded(
        str(new_path), str(old_path), SimpleNamespace(_cancelled=False)
    )
    token = controller._relaunch_token
    assert token is not None
    (tmp_path / token).write_bytes(b"\xff\xfe not valid ascii")
    controller._relaunch_deadline = 0.0

    with patch.object(updater.QMessageBox, "warning"):
        controller._poll_relaunch()

    assert old_path.read_bytes() == b"old"
    assert not new_path.exists()


def test_cancel_blocks_until_swap_commit_decision_completes() -> None:
    """cancel() must not be able to set _cancelled between a worker's
    post-swap check and its finished.emit(): the two are mutually exclusive
    via the same lock, closing the TOCTOU where a worker could observe
    _cancelled=False, get paused, and emit success after cancel() runs."""
    worker = updater.DownloadWorker(
        "https://github.com/owner/repo/Cove.AppImage",
        Path("/tmp/cove-updater-test-unused"), "owner/repo", "Cove.AppImage",
    )
    worker._commit_lock.acquire()
    cancel_returned = threading.Event()

    def call_cancel() -> None:
        worker.cancel()
        cancel_returned.set()

    t = threading.Thread(target=call_cancel)
    t.start()
    try:
        assert not cancel_returned.wait(0.2), (
            "cancel() must block while the worker holds the commit lock"
        )
        assert worker._cancelled is False
    finally:
        worker._commit_lock.release()
    assert cancel_returned.wait(1)
    assert worker._cancelled is True
    t.join()


def test_shutdown_suppresses_queued_update_prompt_and_new_checks() -> None:
    controller = _controller()
    controller._shutdown_threads()

    assert controller._shutting_down is True
    with patch.object(updater.UpdateController, "_prompt") as prompt:
        controller._on_update_available(
            updater.UpdateInfo("2.0.0", "https://example/release")
        )
        prompt.assert_not_called()

    controller.check()
    assert controller._thread is None


def test_shutdown_suppresses_queued_download_failure_dialog() -> None:
    controller = _controller()
    controller._shutdown_threads()

    with patch.object(updater.QMessageBox, "warning") as warning:
        controller._on_download_failed("connection reset")
        warning.assert_not_called()


def test_shutdown_suppresses_queued_relaunch_timer_tick(tmp_path, monkeypatch) -> None:
    old_path = tmp_path / "Cove-1.0.AppImage"
    new_path = tmp_path / "Cove-2.0.AppImage"
    old_path.write_bytes(b"old")
    new_path.write_bytes(b"new")
    process = _Process()
    monkeypatch.setenv("APPIMAGE", str(new_path))
    monkeypatch.setattr(updater, "_startup_ack_path", lambda token: tmp_path / token)
    monkeypatch.setattr(updater, "relaunch", lambda path, token: process)
    controller = _controller()
    controller._on_downloaded(
        str(new_path), str(old_path), SimpleNamespace(_cancelled=False)
    )
    controller._shutting_down = True
    # Force the timeout branch so an unguarded _poll_relaunch would
    # definitely act (show a dialog, clear state) instead of harmlessly
    # falling through.
    controller._relaunch_deadline = 0.0

    with patch.object(updater.QMessageBox, "warning") as warning:
        # A queued timer tick flushed by shutdown's event-processing pass
        # must not race _shutdown_threads' own ack check or show a dialog.
        controller._poll_relaunch()
        warning.assert_not_called()
    assert controller._relaunch_process is not None, (
        "_shutdown_threads, not a stray timer tick, must own this decision"
    )


def test_cancellation_during_staging_preserves_installed_binary(tmp_path, monkeypatch):
    import shutil

    installed = tmp_path / "install"
    cache = tmp_path / "cache"
    installed.mkdir()
    cache.mkdir()
    old, new = installed / "Cove.AppImage", cache / "Cove.AppImage"
    old.write_bytes(b"working version")
    new.write_bytes(b"replacement")
    monkeypatch.setenv("APPIMAGE", str(old))
    cancelled = threading.Event()
    move = shutil.move

    def cancel_after_copy(source, dest):
        result = move(source, dest)
        cancelled.set()
        return result

    monkeypatch.setattr(updater.shutil, "move", cancel_after_copy)
    import pytest
    with pytest.raises(RuntimeError, match="cancelled"):
        updater.swap_in_appimage(new, cancelled=cancelled.is_set)
    assert old.read_bytes() == b"working version"
    assert not list(installed.glob("*.part"))
    assert not list(installed.glob("*.cove-rollback"))

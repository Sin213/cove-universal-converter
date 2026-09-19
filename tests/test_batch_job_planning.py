"""Exercise preflight and real worker output across queue state changes."""
import os
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PIL import Image
from PySide6.QtWidgets import QApplication

from cove_converter.ui.main_window import MainWindow
from cove_converter.ui.file_row import unique_path


@pytest.fixture
def window(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(MainWindow, "_warm_hwaccel", lambda self: None)
    monkeypatch.setattr("cove_converter.updater.UpdateController.check", lambda self: None)
    win = MainWindow()
    win._settings.max_concurrent = 2
    yield win
    for row in win._rows:
        if row.worker is not None:
            row.worker.cancel()
            assert row.worker.wait(5000)
    app.processEvents()
    win.close()


def add_image(window, path, color="red"):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (8, 8), color).save(path)
    window._add_files([path])
    row = window._rows[-1]
    window._on_target_changed(row, ".png")
    return row


def drain(window):
    deadline = time.monotonic() + 5
    while window._pending_rows or window._active_rows:
        QApplication.processEvents()
        assert time.monotonic() < deadline, "batch did not finish"
        time.sleep(0.005)


@pytest.mark.parametrize("separate_folders", [False, True])
def test_colliding_outputs_both_survive(window, tmp_path, monkeypatch, separate_folders):
    first = add_image(window, tmp_path / "a" / "same.jpg", "red")
    second = add_image(window, tmp_path / ("b" if separate_folders else "a") / "same.webp", "blue")
    window._output_dir = tmp_path / "output"
    monkeypatch.setattr(window, "_ask_overwrite", lambda conflicts: pytest.fail("no existing output"))
    window._convert_all()
    drain(window)
    assert first.status == second.status == "Done"
    assert first.completed_output != second.completed_output
    with Image.open(first.completed_output) as a, Image.open(second.completed_output) as b:
        assert a.getpixel((0, 0))[0] > 240
        assert b.getpixel((0, 0))[2] > 240


def test_renaming_reserves_later_natural_destinations(window, tmp_path, monkeypatch):
    first = add_image(window, tmp_path / "same.jpg")
    second = add_image(window, tmp_path / "same (1).jpg")
    (tmp_path / "same.png").write_bytes(b"existing")
    monkeypatch.setattr(window, "_ask_overwrite", lambda conflicts: "rename")
    monkeypatch.setattr(window, "_pump_queue", lambda: None)
    window._convert_all()
    assert first.job.output_path.name == "same (2).png"
    assert second.job.output_path.name == "same (1).png"


def test_per_row_jobs_reserve_pending_destinations(window, tmp_path, monkeypatch):
    first = add_image(window, tmp_path / "same.jpg")
    second = add_image(window, tmp_path / "same.webp")
    monkeypatch.setattr(window, "_pump_queue", lambda: None)
    window._convert_one(first)
    window._convert_one(second)
    assert first.job.output_path != second.job.output_path


def test_queued_destination_and_settings_are_captured(window, tmp_path, monkeypatch):
    row = add_image(window, tmp_path / "source.jpg")
    approved = tmp_path / "approved"
    later = tmp_path / "later"
    later.mkdir()
    sentinel = later / "source.png"
    sentinel.write_bytes(b"keep me")
    window._output_dir = approved
    window._settings.jpeg_quality = 91
    with monkeypatch.context() as pause:
        pause.setattr(window, "_pump_queue", lambda: None)
        window._convert_one(row)
    window._output_dir = later
    window._settings.jpeg_quality = 12
    row.enhance_pdf = True
    window._pump_queue()
    drain(window)
    assert row.completed_output == approved / "source.png"
    assert sentinel.read_bytes() == b"keep me"
    assert row.worker.settings.jpeg_quality == 91
    assert row.worker.settings.enhance_scanned_pdf is False


def test_clear_all_allows_another_batch(window, tmp_path, monkeypatch):
    add_image(window, tmp_path / "source.jpg")
    with monkeypatch.context() as pause:
        pause.setattr(window, "_pump_queue", lambda: None)
        window._convert_all()
        assert not window.convert_btn.isEnabled()
        window._clear()
    row = add_image(window, tmp_path / "new.jpg")
    assert window.convert_btn.isEnabled()
    window.convert_btn.click()
    drain(window)
    assert row.status == "Done"


def test_job_output_path_is_resolved_against_symlinked_parent(window, tmp_path, monkeypatch):
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    alt_dir = tmp_path / "alt"
    alt_dir.mkdir()
    link_dir = tmp_path / "out_link"
    link_dir.symlink_to(real_dir)
    row = add_image(window, tmp_path / "source.jpg")
    window._output_dir = link_dir
    with monkeypatch.context() as pause:
        pause.setattr(window, "_pump_queue", lambda: None)
        window._convert_one(row)
    # The symlink is retargeted after the job was captured; the frozen job
    # must still point at the destination that was actually reserved
    # (under ``real_dir``), not wherever ``link_dir`` now resolves to.
    link_dir.unlink()
    link_dir.symlink_to(alt_dir)
    assert row.job.output_path == (real_dir / "source.png").resolve()
    assert row.job.output_path.parent == real_dir.resolve()


def test_job_output_path_preserves_leaf_symlink_name(window, tmp_path, monkeypatch):
    elsewhere = tmp_path / "elsewhere.bin"
    elsewhere.write_bytes(b"other file's real content")
    row = add_image(window, tmp_path / "source.jpg")
    window._output_dir = tmp_path
    leaf_link = tmp_path / "source.png"
    leaf_link.symlink_to(elsewhere)
    with monkeypatch.context() as pause:
        pause.setattr(window, "_pump_queue", lambda: None)
        pause.setattr(window, "_ask_overwrite", lambda conflicts: "overwrite")
        window._convert_one(row)
    # The leaf name must stay literal (``source.png``), not follow the
    # symlink to ``elsewhere.bin`` - otherwise the worker would write the
    # wrong suffix/location and silently adopt an unrelated file.
    assert row.job.output_path.name == "source.png"
    assert row.job.output_path == tmp_path.resolve() / "source.png"


def test_job_input_path_preserves_leaf_symlink_suffix(window, tmp_path, monkeypatch):
    payload = tmp_path / "payload.bin"
    payload.write_bytes(b"not really a jpg")
    source_link = tmp_path / "source.jpg"
    source_link.symlink_to(payload)
    window._add_files([source_link])
    row = window._rows[-1]
    window._on_target_changed(row, ".png")
    with monkeypatch.context() as pause:
        pause.setattr(window, "_pump_queue", lambda: None)
        window._convert_one(row)
    # The leaf name/suffix must stay literal so routing and worker suffix
    # inference still see ``.jpg``, not the symlink target's ``.bin``.
    assert row.job.input_path.name == "source.jpg"


def test_missing_job_counts_toward_batch_skipped(window, tmp_path):
    row = add_image(window, tmp_path / "source.jpg")
    window._batch_total = 1
    window._start_row(row)
    assert window._batch_skipped == 1
    assert row.status == "Unsupported"


def test_unique_path_normalizes_reserved_aliases(tmp_path):
    output = tmp_path / "out.png"
    alias = tmp_path / "sub" / ".." / "out.png"
    assert unique_path(output, {alias}) == tmp_path / "out (1).png"

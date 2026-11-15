"""Real queue integration: target fan-out, partial results and frozen jobs."""
import hashlib
import time

from PIL import Image
import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication

from cove_converter.ui.main_window import MainWindow
from cove_converter.ui.theme import unregister_theme_listener
from tests.test_batch_job_planning import add_image, drain


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
    unregister_theme_listener(win._on_theme_changed)
    win.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def test_multi_outputs_sources_and_casefold_collisions(window, tmp_path, monkeypatch):
    first = add_image(window, tmp_path / "same.png")
    second = add_image(window, tmp_path / "SAME.jpg", "blue")
    before = [hashlib.sha256(r.path.read_bytes()).digest() for r in (first, second)]
    window._output_dir = tmp_path / "output"
    window._output_dir.mkdir()
    existing = window._output_dir / "same.WEBP"
    existing.write_bytes(b"keep")
    monkeypatch.setattr(window, "_ask_overwrite", lambda conflicts: "rename")
    window._set_row_targets(first, (".jpg", ".webp", ".pdf"))
    window._set_row_targets(second, (".png", ".webp", ".pdf"))
    window._convert_all()
    drain(window)
    outputs = [p for r in (first, second) for p in r.completed_outputs]
    assert first.status == second.status == "Done"
    assert len(outputs) == len({str(p).casefold() for p in outputs}) == 6
    assert existing.read_bytes() == b"keep"
    assert [hashlib.sha256(r.path.read_bytes()).digest() for r in (first, second)] == before
    assert not list(window._output_dir.glob(".*cove*"))


def test_target_failure_keeps_other_outputs_and_reports_partial(window, tmp_path, monkeypatch):
    from cove_converter.engines.pillow import PillowWorker
    original = PillowWorker._convert
    def fail_one(worker):
        if worker.output_path.suffix == ".webp":
            raise ValueError("injected webp failure")
        original(worker)
    monkeypatch.setattr(PillowWorker, "_convert", fail_one)
    row = add_image(window, tmp_path / "source.png")
    window._set_row_targets(row, (".jpg", ".webp", ".bmp"))
    window._convert_one(row)
    drain(window)
    assert row.status == "Partial"
    assert {p.suffix for p in row.completed_outputs} == {".jpg", ".bmp"}
    assert "injected webp failure" in row.error_log
    assert "partial" in window.status_msg.text().lower()
    assert window._last_output_file() in row.completed_outputs


def test_multi_jobs_freeze_all_destinations_quality_and_reservations(window, tmp_path, monkeypatch):
    row = add_image(window, tmp_path / "same.jpg")
    other = add_image(window, tmp_path / "same.webp")
    window._set_row_targets(row, (".png", ".webp"))
    window._settings.jpeg_quality = 76
    with monkeypatch.context() as pause:
        pause.setattr(window, "_pump_queue", lambda: None)
        window._convert_one(row)
        window._convert_one(other)
    paths = [job.output_path for job in (*row.jobs, *other.jobs)]
    assert len(paths) == len(set(paths))
    window._settings.jpeg_quality = 1
    window._output_dir = tmp_path / "wrong"
    window._pump_queue()
    drain(window)
    assert all(p.exists() for p in paths)
    assert row.worker.settings.jpeg_quality == 76
    assert not (tmp_path / "wrong").exists()


def test_unsupported_target_rejected_before_any_output(window, tmp_path):
    row = add_image(window, tmp_path / "source.jpg")
    row.extra_targets = (".mp3",)
    window._convert_one(row)
    assert row.status == "Unsupported"
    assert not (tmp_path / "source.png").exists()


def test_preset_skips_reported_targets_and_keeps_unrelated_row(window, tmp_path):
    from cove_converter.settings import ConversionPreset, ConversionSettings
    image = add_image(window, tmp_path / "source.jpg")
    text = tmp_path / "source.txt"
    text.write_text("hello")
    window._add_files([text])
    document = window._rows[-1]
    old = document.target_ext
    preset = ConversionPreset((".png", ".webp"), ConversionSettings(jpeg_quality=72))
    window._apply_preset(preset)
    assert image.selected_targets == (".png", ".webp")
    assert image.preset_settings.jpeg_quality == 72
    assert document.target_ext == old
    assert "skipped" in window.status_msg.text().lower()


def test_cancel_does_not_start_later_targets(window, tmp_path, monkeypatch):
    from cove_converter.engines.pillow import PillowWorker
    original = PillowWorker._convert
    def slow(worker):
        for _ in range(100):
            if worker._cancel:
                return
            time.sleep(.002)
        original(worker)
    monkeypatch.setattr(PillowWorker, "_convert", slow)
    row = add_image(window, tmp_path / "source.jpg")
    window._set_row_targets(row, (".png", ".webp"))
    window._convert_one(row)
    row.worker.cancel()
    drain(window)
    assert row.status == "Cancelled"
    assert not (tmp_path / "source.png").exists()
    assert not (tmp_path / "source.webp").exists()
    assert "cancelled" in window.status_msg.text().lower()


def test_all_targets_fail_reports_failure(window, tmp_path):
    path = tmp_path / "broken.png"
    path.write_bytes(b"invalid")
    window._add_files([path])
    row = window._rows[-1]
    window._set_row_targets(row, (".jpg", ".webp"))
    window._convert_all()
    drain(window)
    assert row.status.startswith("Failed")
    assert not row.completed_outputs
    assert "failed" in window.status_msg.text()


def test_cancel_after_first_output_keeps_it_and_reports_partial(window, tmp_path, monkeypatch):
    from cove_converter.engines.pillow import PillowWorker
    original = PillowWorker._convert
    def cancel_second(worker):
        if worker.output_path.suffix == ".webp":
            worker.cancel()
            return
        original(worker)
    monkeypatch.setattr(PillowWorker, "_convert", cancel_second)
    row = add_image(window, tmp_path / "source.png")
    window._set_row_targets(row, (".jpg", ".webp", ".bmp"))
    window._convert_one(row)
    drain(window)
    assert row.status == "Partial"
    assert [p.suffix for p in row.completed_outputs] == [".jpg"]
    assert row.completed_outputs[0].exists()
    assert not (tmp_path / "source.bmp").exists()
    assert "cancelled" in row.error_log.lower()
    assert "partial" in window.status_msg.text()


def test_multi_output_obeys_worker_concurrency_cap(window, tmp_path, monkeypatch):
    import threading
    from cove_converter.engines.pillow import PillowWorker
    lock = threading.Lock()
    active = maximum = 0
    original = PillowWorker._convert
    def observed(worker):
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
        try:
            time.sleep(.02)
            original(worker)
        finally:
            with lock:
                active -= 1
    monkeypatch.setattr(PillowWorker, "_convert", observed)
    window._settings.max_concurrent = 2
    for i in range(4):
        row = add_image(window, tmp_path / f"source-{i}.png")
        window._set_row_targets(row, (".jpg", ".webp"))
    window._convert_all()
    drain(window)
    assert maximum == 2
    assert all(len(row.completed_outputs) == 2 for row in window._rows)


def test_reapplying_preset_with_new_quality_reopens_done_row(window, tmp_path):
    from cove_converter.settings import ConversionPreset, ConversionSettings
    row = add_image(window, tmp_path / "source.jpg")
    window._convert_one(row)
    drain(window)
    assert row.status == "Done"
    window._apply_preset(ConversionPreset((".png",), ConversionSettings(jpeg_quality=61)))
    assert row.status == "Pending"
    assert row.preset_settings.jpeg_quality == 61


@pytest.mark.parametrize("phase", ["scan", "rename"])
def test_unreadable_destination_fails_only_affected_row(window, tmp_path, monkeypatch, phase):
    from pathlib import Path
    denied = tmp_path / "denied"
    readable = tmp_path / "readable"
    first = add_image(window, denied / "first.jpg")
    second = add_image(window, readable / "second.jpg")
    existing = denied / "first.png"
    if phase == "rename":
        existing.write_bytes(b"existing output")
        monkeypatch.setattr(window, "_ask_overwrite", lambda conflicts: "rename")
    original = Path.iterdir
    inspections = 0
    def reject_denied(path):
        nonlocal inspections
        if path == denied:
            inspections += 1
            if phase == "scan" or inspections > 1:
                raise PermissionError("Permission denied: destination inspection")
        return original(path)
    monkeypatch.setattr(Path, "iterdir", reject_denied)
    window._convert_all()
    drain(window)
    assert first.status.startswith("Failed")
    assert "destination" in first.error_log.lower()
    assert "permission" in first.error_log.lower()
    if phase == "rename":
        assert existing.read_bytes() == b"existing output"
    else:
        assert not existing.exists()
    assert second.status == "Done"
    assert second.completed_output == readable / "second.png"
    assert "failed" in window.status_msg.text()


def _change_quality_via_dialog(window, monkeypatch, jpeg=44, webp=62):
    from cove_converter.ui.quality_dialog import QualityDialog
    def accept(dialog):
        dialog.enable_check.setChecked(True)
        dialog.jpeg.set_value(jpeg)
        dialog.webp.set_value(webp)
        dialog.accept()
        return dialog.result()
    monkeypatch.setattr(QualityDialog, "exec", accept)
    window._show_quality_dialog()


@pytest.mark.parametrize("scope", ["row", "all", "batch"])
@pytest.mark.parametrize("targets", [(".jpg",), (".jpg", ".webp")])
@pytest.mark.parametrize("had_preset", [False, True])
def test_manual_output_dialog_uses_later_quality(window, tmp_path, monkeypatch, scope, targets, had_preset):
    from PySide6.QtCore import QSettings
    from cove_converter import settings
    from cove_converter.settings import ConversionPreset, ConversionSettings
    from cove_converter.ui.outputs_dialog import OutputsDialog
    monkeypatch.setattr(settings, "QSettings", lambda *args: QSettings(
        str(tmp_path / "quality.ini"), QSettings.Format.IniFormat,
    ))
    rows = [add_image(window, tmp_path / f"source-{i}.png") for i in range(2)]
    affected = rows[:1] if scope == "row" else rows
    window._settings = ConversionSettings(use_custom_quality=True, jpeg_quality=93, webp_quality=94)
    if had_preset:
        window._apply_preset(ConversionPreset(targets, ConversionSettings(
            use_custom_quality=True, jpeg_quality=73, webp_quality=76,
        )), rows)
    def accept(dialog):
        for target, check in dialog.checks.items():
            check.setChecked(target in targets)
        dialog.apply_all.setChecked(scope == "all")
        dialog.apply_button.click()
        return dialog.result()
    monkeypatch.setattr(OutputsDialog, "exec", accept)
    window._show_outputs_dialog(None if scope == "batch" else rows[0])
    _change_quality_via_dialog(window, monkeypatch)
    for row in affected:
        window._convert_one(row)
    drain(window)
    for row in affected:
        assert row.status == "Done"
        assert row.selected_targets == targets
        assert all(job.settings.effective_jpeg_quality() == 44 for job in row.jobs)
        assert all(job.settings.effective_webp_quality() == 62 for job in row.jobs)
        assert row.preset_settings is None
    if scope == "row" and had_preset:
        assert rows[1].preset_settings.jpeg_quality == 73


@pytest.mark.parametrize("scope", ["row", "all", "batch"])
def test_explicit_saved_preset_dialog_keeps_preset_quality(window, tmp_path, monkeypatch, scope):
    from PySide6.QtCore import QSettings
    from cove_converter import settings
    from cove_converter.settings import ConversionSettings, PresetStore
    from cove_converter.ui.outputs_dialog import OutputsDialog
    monkeypatch.setattr(settings, "QSettings", lambda *args: QSettings(
        str(tmp_path / "quality.ini"), QSettings.Format.IniFormat,
    ))
    targets = (".jpg", ".webp")
    PresetStore().save("Web", targets, ConversionSettings(
        use_custom_quality=True, jpeg_quality=73, webp_quality=76,
    ))
    rows = [add_image(window, tmp_path / f"source-{i}.png") for i in range(2)]
    affected = rows[:1] if scope == "row" else rows
    def accept(dialog):
        dialog.apply_all.setChecked(scope == "all")
        dialog.names.setCurrentText("Web")
        dialog._apply_preset()
        return dialog.result()
    monkeypatch.setattr(OutputsDialog, "exec", accept)
    window._show_outputs_dialog(None if scope == "batch" else rows[0])
    _change_quality_via_dialog(window, monkeypatch)
    for row in affected:
        window._convert_one(row)
    drain(window)
    for row in affected:
        assert row.status == "Done"
        assert row.selected_targets == targets
        assert all(job.settings.effective_jpeg_quality() == 73 for job in row.jobs)
        assert all(job.settings.effective_webp_quality() == 76 for job in row.jobs)
    assert window._settings.effective_jpeg_quality() == 44

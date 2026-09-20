import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from unittest.mock import Mock, patch

from cove_converter import __main__ as startup


def test_setup_logging_is_idempotent_for_relative_log_dir(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = logging.getLogger()
    original_handlers = tuple(root.handlers)
    original_level = root.level
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(startup, "_log_dir", lambda: Path("cache"))

    try:
        first_path = startup._setup_logging()
        second_path = startup._setup_logging()
        expected = (tmp_path / "cache" / "cove-converter.log").resolve()
        matching_handlers = [
            handler
            for handler in root.handlers
            if isinstance(handler, RotatingFileHandler)
            and Path(handler.baseFilename) == expected
        ]

        assert first_path == expected
        assert second_path == expected
        assert len(matching_handlers) == 1
    finally:
        for handler in tuple(root.handlers):
            if handler not in original_handlers:
                root.removeHandler(handler)
                handler.close()
        root.setLevel(original_level)


def test_main_acknowledges_update_after_window_is_shown(tmp_path: Path) -> None:
    call_order: list[str] = []
    app = Mock()
    app.exec.side_effect = lambda: call_order.append("exec") or 0
    window = Mock()

    def record_single_shot(delay, callback) -> None:
        call_order.append("single_shot")

    with (
        patch.object(startup, "_setup_logging"),
        patch.object(startup, "QApplication", return_value=app),
        patch.object(startup, "MainWindow", return_value=window),
        patch.object(startup, "resource_path", return_value=tmp_path / "missing"),
        patch.object(startup, "apply_global_theme"),
        patch.object(
            startup.QTimer, "singleShot", side_effect=record_single_shot,
        ) as single_shot,
    ):
        result = startup.main()

    assert result == 0
    window.show.assert_called_once_with()
    single_shot.assert_called_once_with(0, startup.acknowledge_updated_startup)
    # The acknowledgement callback must be scheduled before the event loop
    # starts - scheduling it after app.exec() returns would mean it never
    # fires while the loop is servicing the shown window.
    assert call_order == ["single_shot", "exec"]

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

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

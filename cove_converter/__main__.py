import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from cove_converter.binaries import resource_path
from cove_converter.ui.main_window import MainWindow
from cove_converter.ui.theme import apply_global_theme


def _log_dir() -> Path:
    """Resolve the per-user cache dir we write the log to.

    Honours ``XDG_CACHE_HOME`` on Linux (so packaged installs land in the
    standard place) and falls back to ``~/.cache``. The directory is created
    lazily — failing to create it must not abort app startup, so we swallow
    any OSError and fall back to a temp dir."""
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "cove-universal-converter"


def _setup_logging() -> Path | None:
    """Wire stderr + rotating file handlers for the worker logger.

    PyInstaller ``--windowed`` builds detach stderr from any visible terminal,
    so a packaged AppImage user never sees the worker traceback even though
    the worker emits it. Writing to a known on-disk location means the failure
    is always recoverable: 'send me ~/.cache/cove-universal-converter/cove-converter.log'.

    Returns the resolved log file path on success (so the GUI can surface it
    in error UI later), or None if file logging couldn't be set up."""
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    # Stream handler: useful in dev / when launched from a terminal.
    if not any(isinstance(h, logging.StreamHandler) for h in root.handlers):
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        root.addHandler(sh)

    log_path: Path | None = None
    try:
        log_dir = _log_dir()
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "cove-converter.log"
        # Cap each file at 1 MB; keep 3 rotations. A failing conversion produces
        # ~2 KB of traceback so this comfortably holds many runs.
        fh = RotatingFileHandler(log_path, maxBytes=1_000_000, backupCount=3,
                                 encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)
        logging.getLogger("cove_converter").info("log file: %s", log_path)
    except OSError as exc:
        logging.getLogger("cove_converter").warning(
            "could not open log file: %s", exc,
        )
    return log_path


def main() -> int:
    # Conversion-worker tracebacks are routed through ``cove_converter.worker``;
    # we need both stderr and a rotating file on disk so a packaged
    # ``--windowed`` build still surfaces failures when the user double-clicks
    # the AppImage (no terminal attached).
    _setup_logging()

    app = QApplication(sys.argv)
    app.setApplicationName("Cove Universal Converter")
    apply_global_theme(app)

    icon_file = resource_path("cove_icon.png")
    if icon_file.is_file():
        app.setWindowIcon(QIcon(str(icon_file)))

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

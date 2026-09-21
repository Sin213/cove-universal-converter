"""Top-level launcher for PyInstaller bundles and packaged smoke checks."""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path


def _bundle_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))


def _install_bundled_version() -> str:
    from cove_converter.version import validate_version

    version_file = _bundle_root() / "cove-build-version.txt"
    if not version_file.is_file():
        raise RuntimeError(f"packaged build version is missing: {version_file}")
    version = validate_version(version_file.read_text(encoding="utf-8"))

    # The updater imports this public package value, so install the version
    # embedded by the build before importing the GUI entry point.
    import cove_converter

    cove_converter.__version__ = version
    return version


def _run_smoke(version: str, expected_version: str | None) -> int:
    if expected_version and version != expected_version:
        print(
            f"packaged version mismatch: expected {expected_version}, got {version}",
            file=sys.stderr,
        )
        return 1

    # Exercise the actual GUI startup and event loop as well as converters.
    # This catches missing Qt platform plugins and GUI imports in bundles.
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from cove_converter.ui.main_window import MainWindow
    from cove_converter.ui.theme import apply_global_theme

    app = QApplication.instance() or QApplication([])
    apply_global_theme(app)
    window = MainWindow()
    window.show()
    QTimer.singleShot(0, window.close)
    app.exec()

    from scripts.smoke_conversions import FAIL, SKIP, Route, run_smoke

    if getattr(sys, "frozen", False):
        suffix = ".exe" if sys.platform == "win32" else ""
        for name in ("ffmpeg", "pandoc"):
            binary = _bundle_root() / (name + suffix)
            if not binary.is_file() or (sys.platform != "win32" and not os.access(binary, os.X_OK)):
                raise RuntimeError(f"Packaged binary is missing or not executable: {binary}")
        # The smoke harness's sample generators invoke commands by name.
        # Exercise the packaged tools even if the build host has its own.
        os.environ["PATH"] = str(_bundle_root()) + os.pathsep + os.environ.get("PATH", "")

    routes = [
        Route(".png", ".jpg", "Pillow"),
        Route(".json", ".yaml", "Data"),
        Route(".zip", ".tar", "Archive"),
        Route(".srt", ".vtt", "Subtitle"),
        Route(".csv", ".xlsx", "Spreadsheet"),
        Route(".mp4", ".mp3", "FFmpeg"),
        Route(".md", ".docx", "Pandoc"),
        Route(".html", ".pdf", "Pdf"),
    ]
    with tempfile.TemporaryDirectory(prefix="cove-packaged-smoke-") as temp_dir:
        report = run_smoke(routes, work_dir=Path(temp_dir), quiet=True)
    counts = report.counts()
    failures = counts[FAIL] + counts[SKIP]
    print(f"Cove {version} packaged smoke: {len(routes) - failures}/{len(routes)} passed")
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    version = _install_bundled_version()
    if args and args[0] == "--smoke-test":
        parser = argparse.ArgumentParser(description="Validate the packaged application")
        parser.add_argument("--smoke-test", action="store_true")
        parser.add_argument("--expect-version")
        parsed = parser.parse_args(args)
        return _run_smoke(version, parsed.expect_version)

    from cove_converter.__main__ import main as application_main

    return application_main()


if __name__ == "__main__":
    raise SystemExit(main())

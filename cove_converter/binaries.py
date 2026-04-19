"""Platform-aware resolution of bundled ffmpeg/pandoc binaries.

Resolution order:
1. PyInstaller bundle root (``sys._MEIPASS/<name>``) — where ``--add-binary``
   lands ffmpeg / pandoc for packaged Setup.exe / Portable.exe / AppImage / .deb.
2. Legacy repo-relative ``bin/<platform>/<name>`` (dev runs with pre-placed
   binaries).
3. System ``PATH`` via ``shutil.which`` (dev runs with system-installed tools).
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path


def _platform_dir() -> str:
    if sys.platform.startswith("win"):
        return "win"
    return "linux"


def _exe(name: str) -> str:
    return f"{name}.exe" if sys.platform.startswith("win") else name


def _bundle_root() -> Path:
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return Path(__file__).resolve().parent.parent


def resource_path(relative: str) -> Path:
    """Resolve a bundled resource (icons, etc.) both in dev and PyInstaller builds."""
    return _bundle_root() / relative


def resolve(name: str) -> str:
    """Return an absolute path (or bare name) usable by ``subprocess``."""
    exe = _exe(name)
    root = _bundle_root()

    candidates = [
        root / exe,                             # PyInstaller bundle root
        root / "bin" / _platform_dir() / exe,   # legacy dev layout
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)

    found = shutil.which(exe)
    if found:
        return found

    raise FileNotFoundError(
        f"Could not find {exe}. Install it system-wide or rebuild the app so it "
        f"gets bundled."
    )


FFMPEG = "ffmpeg"
PANDOC = "pandoc"

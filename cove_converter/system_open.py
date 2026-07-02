"""Open files/folders/URLs externally without leaking AppImage env.

The AppImage runtime exports LD_LIBRARY_PATH pointing at the bundle's
libraries. QDesktopServices.openUrl spawns xdg-open with the current
environment, so the launched app (file manager, video player, browser)
inherits it, loads the bundle's outdated libraries, and crashes on
startup with errors like `liblzma.so.5: version XZ_5.4 not found`.
Inside an AppImage we spawn xdg-open ourselves with a scrubbed env.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices


def child_env() -> dict | None:
    """Scrubbed env for spawning external programs from inside an AppImage.

    Returns None when not running from an AppImage (inherit unchanged).
    """
    if not (os.environ.get("APPDIR") or os.environ.get("APPIMAGE")):
        return None
    env = os.environ.copy()
    for key in ("LD_LIBRARY_PATH", "LD_PRELOAD", "PYTHONHOME", "PYTHONPATH",
                "QT_PLUGIN_PATH", "QML2_IMPORT_PATH"):
        env.pop(key, None)
    return env


def _spawn_xdg_open(target: str) -> bool:
    env = child_env()
    if env is None or not sys.platform.startswith("linux"):
        return False
    if not shutil.which("xdg-open"):
        return False
    try:
        subprocess.Popen(["xdg-open", target], env=env)
        return True
    except Exception:  # noqa: BLE001
        return False


def open_local(path: str) -> None:
    """Open a local file or folder with the OS default handler."""
    if _spawn_xdg_open(path):
        return
    QDesktopServices.openUrl(QUrl.fromLocalFile(path))


def open_url(url: str) -> None:
    """Open a URL in the default browser."""
    if _spawn_xdg_open(url):
        return
    QDesktopServices.openUrl(QUrl(url))

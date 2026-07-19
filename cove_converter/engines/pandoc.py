from __future__ import annotations

import subprocess
import sys
import tempfile
import time

from cove_converter.binaries import PANDOC, resolve
from cove_converter.engines.base import BaseConverterWorker

# Generous ceiling: pandoc on any sane document finishes in seconds; a hang
# here is a stuck resource fetch or pathological input, not real work.
_PANDOC_TIMEOUT_S = 600


def _no_window_kwargs() -> dict:
    if sys.platform.startswith("win"):
        return {"creationflags": 0x08000000}
    return {}


class PandocWorker(BaseConverterWorker):
    """Pandoc has no usable progress stream — emit coarse milestones."""

    def _convert(self) -> None:
        self.progress.emit(5)
        cmd = [
            resolve(PANDOC),
            str(self.input_path),
            "-o", str(self.output_path),
        ]
        self.progress.emit(20)
        # stderr goes to a temp file (not a pipe) so a warning-heavy run
        # can't fill the pipe buffer and deadlock against the poll loop.
        with tempfile.TemporaryFile() as err:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=err,
                **_no_window_kwargs(),
            )
            # Poll instead of blocking so Cancel takes effect promptly and
            # a wedged pandoc can't hang the worker forever.
            deadline = time.monotonic() + _PANDOC_TIMEOUT_S
            while proc.poll() is None:
                if self._cancel or time.monotonic() > deadline:
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()
                    if self._cancel:
                        return
                    raise RuntimeError(
                        f"pandoc timed out after {_PANDOC_TIMEOUT_S}s"
                    )
                time.sleep(0.2)
            err.seek(0)
            stderr = err.read().decode("utf-8", errors="replace")
        if proc.returncode != 0:
            raise RuntimeError(stderr.strip() or f"pandoc exited {proc.returncode}")

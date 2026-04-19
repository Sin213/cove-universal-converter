from __future__ import annotations

import subprocess
import sys

from cove_converter.binaries import PANDOC, resolve
from cove_converter.engines.base import BaseConverterWorker


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
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            **_no_window_kwargs(),
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or f"pandoc exited {result.returncode}")

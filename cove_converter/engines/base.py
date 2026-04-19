from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal

from cove_converter.settings import ConversionSettings, default_settings


class BaseConverterWorker(QThread):
    progress = Signal(int)          # 0..100
    status   = Signal(str)          # "Processing" / "Done" / "Failed: …"
    finished_ok = Signal(Path)      # output path on success
    failed = Signal(str)            # error message

    def __init__(
        self,
        input_path: Path,
        output_path: Path,
        settings: ConversionSettings | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.input_path = Path(input_path)
        self.output_path = Path(output_path)
        self.settings = settings or default_settings()
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:  # noqa: D401 - QThread entry point
        try:
            self.status.emit("Processing")
            self.output_path.parent.mkdir(parents=True, exist_ok=True)
            self._convert()
            if self._cancel:
                self.status.emit("Cancelled")
                return
            self.progress.emit(100)
            self.status.emit("Done")
            self.finished_ok.emit(self.output_path)
        except Exception as exc:
            self.status.emit(f"Failed: {exc}")
            self.failed.emit(str(exc))

    def _convert(self) -> None:
        raise NotImplementedError

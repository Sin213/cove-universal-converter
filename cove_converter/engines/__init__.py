from cove_converter.engines.archives import ArchiveWorker
from cove_converter.engines.base import BaseConverterWorker
from cove_converter.engines.data import DataWorker
from cove_converter.engines.ffmpeg import FFmpegWorker
from cove_converter.engines.pandoc import PandocWorker
from cove_converter.engines.pdf import PdfWorker
from cove_converter.engines.pillow import PillowWorker
from cove_converter.engines.spreadsheets import SpreadsheetWorker
from cove_converter.engines.subtitles import SubtitleWorker

WORKER_REGISTRY: dict[str, type[BaseConverterWorker]] = {
    "FFmpeg":      FFmpegWorker,
    "Pillow":      PillowWorker,
    "Pandoc":      PandocWorker,
    "Pdf":         PdfWorker,
    "Subtitle":    SubtitleWorker,
    "Spreadsheet": SpreadsheetWorker,
    "Archive":     ArchiveWorker,
    "Data":        DataWorker,
}


def worker_for(engine: str) -> type[BaseConverterWorker]:
    return WORKER_REGISTRY[engine]


__all__ = [
    "ArchiveWorker",
    "BaseConverterWorker",
    "DataWorker",
    "FFmpegWorker",
    "PandocWorker",
    "PdfWorker",
    "PillowWorker",
    "SpreadsheetWorker",
    "SubtitleWorker",
    "WORKER_REGISTRY",
    "worker_for",
]

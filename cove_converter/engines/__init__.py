from cove_converter.engines.base import BaseConverterWorker
from cove_converter.engines.ffmpeg import FFmpegWorker
from cove_converter.engines.pandoc import PandocWorker
from cove_converter.engines.pdf import PdfWorker
from cove_converter.engines.pillow import PillowWorker

WORKER_REGISTRY: dict[str, type[BaseConverterWorker]] = {
    "FFmpeg": FFmpegWorker,
    "Pillow": PillowWorker,
    "Pandoc": PandocWorker,
    "Pdf":    PdfWorker,
}


def worker_for(engine: str) -> type[BaseConverterWorker]:
    return WORKER_REGISTRY[engine]


__all__ = [
    "BaseConverterWorker",
    "FFmpegWorker",
    "PandocWorker",
    "PdfWorker",
    "PillowWorker",
    "WORKER_REGISTRY",
    "worker_for",
]

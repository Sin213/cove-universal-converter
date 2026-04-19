"""Format → engine routing table.

Keeping this as a flat dict (rather than scattered across engines) means the UI
can populate the "Convert To" dropdown without importing any worker classes.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FormatInfo:
    engine: str
    targets: tuple[str, ...]


# ---- Images (Pillow, + pillow-heif for HEIC) -------------------------------
_IMG_COMMON = (".png", ".jpg", ".webp", ".bmp", ".tiff")

# ---- Audio / Video (FFmpeg) ------------------------------------------------
_AUDIO_TARGETS = (".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac", ".opus")
_VIDEO_TARGETS = (".mp4", ".mkv", ".webm", ".mov", ".avi")
_VIDEO_TO_ANY  = _VIDEO_TARGETS + (".gif",) + _AUDIO_TARGETS

# ---- Docs (Pandoc for non-PDF, PdfEngine for anything touching .pdf) -------
_DOC_TARGETS   = (".pdf", ".docx", ".md", ".html", ".epub", ".txt", ".rtf", ".odt")


SUPPORTED_FORMATS: dict[str, FormatInfo] = {
    # ---- Images ----
    ".png":  FormatInfo("Pillow", (".jpg", ".webp", ".bmp", ".tiff", ".ico")),
    ".jpg":  FormatInfo("Pillow", (".png", ".webp", ".bmp", ".tiff")),
    ".jpeg": FormatInfo("Pillow", (".png", ".webp", ".bmp", ".tiff")),
    ".webp": FormatInfo("Pillow", (".jpg", ".png", ".bmp", ".tiff")),
    ".bmp":  FormatInfo("Pillow", (".jpg", ".png", ".webp", ".tiff")),
    ".tiff": FormatInfo("Pillow", (".jpg", ".png", ".webp", ".bmp")),
    ".tif":  FormatInfo("Pillow", (".jpg", ".png", ".webp", ".bmp")),
    ".ico":  FormatInfo("Pillow", (".png", ".jpg")),
    ".heic": FormatInfo("Pillow", _IMG_COMMON),
    ".heif": FormatInfo("Pillow", _IMG_COMMON),

    # ---- Video (FFmpeg) ----
    ".mp4":  FormatInfo("FFmpeg", _VIDEO_TO_ANY),
    ".mkv":  FormatInfo("FFmpeg", _VIDEO_TO_ANY),
    ".webm": FormatInfo("FFmpeg", _VIDEO_TO_ANY),
    ".mov":  FormatInfo("FFmpeg", _VIDEO_TO_ANY),
    ".avi":  FormatInfo("FFmpeg", _VIDEO_TO_ANY),
    ".flv":  FormatInfo("FFmpeg", _VIDEO_TO_ANY),
    ".wmv":  FormatInfo("FFmpeg", _VIDEO_TO_ANY),
    ".m4v":  FormatInfo("FFmpeg", _VIDEO_TO_ANY),
    ".mpg":  FormatInfo("FFmpeg", _VIDEO_TO_ANY),
    ".mpeg": FormatInfo("FFmpeg", _VIDEO_TO_ANY),
    ".3gp":  FormatInfo("FFmpeg", _VIDEO_TO_ANY),
    ".ts":   FormatInfo("FFmpeg", _VIDEO_TO_ANY),
    ".gif":  FormatInfo("FFmpeg", (".mp4", ".webm", ".mkv")),

    # ---- Audio (FFmpeg) ----
    ".mp3":  FormatInfo("FFmpeg", _AUDIO_TARGETS),
    ".wav":  FormatInfo("FFmpeg", _AUDIO_TARGETS),
    ".flac": FormatInfo("FFmpeg", _AUDIO_TARGETS),
    ".ogg":  FormatInfo("FFmpeg", _AUDIO_TARGETS),
    ".m4a":  FormatInfo("FFmpeg", _AUDIO_TARGETS),
    ".aac":  FormatInfo("FFmpeg", _AUDIO_TARGETS),
    ".opus": FormatInfo("FFmpeg", _AUDIO_TARGETS),
    ".wma":  FormatInfo("FFmpeg", _AUDIO_TARGETS),
    ".aiff": FormatInfo("FFmpeg", _AUDIO_TARGETS),

    # ---- Documents ----
    # PdfEngine handles anything with .pdf on either side; Pandoc does the rest.
    ".pdf":  FormatInfo("Pdf",    (".txt", ".md", ".html")),
    ".docx": FormatInfo("Pandoc", _DOC_TARGETS),
    ".odt":  FormatInfo("Pandoc", _DOC_TARGETS),
    ".rtf":  FormatInfo("Pandoc", _DOC_TARGETS),
    ".epub": FormatInfo("Pandoc", _DOC_TARGETS),
    ".md":   FormatInfo("Pandoc", _DOC_TARGETS),
    ".html": FormatInfo("Pandoc", _DOC_TARGETS),
    ".htm":  FormatInfo("Pandoc", _DOC_TARGETS),
    ".txt":  FormatInfo("Pandoc", _DOC_TARGETS),
    ".tex":  FormatInfo("Pandoc", _DOC_TARGETS),
}


def info_for(extension: str) -> FormatInfo | None:
    return SUPPORTED_FORMATS.get(extension.lower())


def targets_for(extension: str) -> tuple[str, ...]:
    info = info_for(extension)
    return info.targets if info else ()


def engine_for(ext_in: str, ext_out: str) -> str | None:
    """Pick the right engine considering both endpoints (PDF overrides Pandoc)."""
    if ext_in.lower() == ".pdf" or ext_out.lower() == ".pdf":
        return "Pdf"
    info = info_for(ext_in)
    return info.engine if info else None


# ---- Display grouping (for the "Supported formats" dialog) -----------------
# Ordered so the UI renders Video → Audio → Images → Documents.
FORMAT_CATEGORIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Video",     (".mp4", ".mkv", ".webm", ".mov", ".avi", ".flv", ".wmv",
                   ".m4v", ".mpg", ".mpeg", ".3gp", ".ts", ".gif")),
    ("Audio",     (".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac", ".opus",
                   ".wma", ".aiff")),
    ("Images",    (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif",
                   ".ico", ".heic", ".heif")),
    ("Documents", (".pdf", ".docx", ".odt", ".rtf", ".epub", ".md",
                   ".html", ".htm", ".txt", ".tex")),
)

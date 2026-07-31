"""Format → engine routing table.

Keeping this as a flat dict (rather than scattered across engines) means the UI
can populate the "Convert To" dropdown without importing any worker classes.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

# Compound extensions whose ``Path.suffix`` doesn't carry enough information
# to route. Keep longer/more-specific spellings ahead of their fallbacks.
_COMPOUND_SUFFIXES: tuple[str, ...] = (".tar.bz2", ".tar.xz", ".tar.gz")


@dataclass(frozen=True)
class FormatInfo:
    engine: str
    targets: tuple[str, ...]


# ---- Images (Pillow, + pillow-heif for HEIC/HEIF) --------------------------
_IMAGE_INPUTS = (
    ".png", ".jpg", ".jpeg", ".jpe", ".jfif", ".webp", ".bmp", ".tiff",
    ".tif", ".ico", ".heic", ".heif", ".avif", ".jp2", ".j2k", ".jpx",
    ".tga", ".pcx", ".ppm", ".pgm", ".pbm", ".dds", ".icns",
)
_IMAGE_TARGETS = (
    ".png", ".jpg", ".webp", ".bmp", ".tiff", ".ico", ".heic", ".heif",
    ".avif", ".jp2", ".tga", ".pcx", ".ppm", ".pgm", ".pbm", ".dds",
    ".icns", ".pdf",
)

# ---- Audio / Video (FFmpeg) ------------------------------------------------
_AUDIO_TARGETS = (
    ".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac", ".opus", ".ac3",
    ".mp2", ".spx", ".caf", ".au", ".wv", ".voc", ".w64", ".mka", ".m4b",
    ".oga", ".aif", ".tta", ".amr", ".weba",
)
_AUDIO_INPUTS = _AUDIO_TARGETS + (".wma", ".aiff")
_VIDEO_BIDIRECTIONAL = (
    ".mp4", ".mkv", ".webm", ".mov", ".avi", ".mxf", ".rm", ".swf", ".vob",
    ".asf", ".ogv", ".m2ts", ".mts", ".f4v",
)
# Raw/write-only container formats: valid encode targets, never routed inputs.
_VIDEO_TARGETS_ONLY = (".y4m", ".ivf")
_VIDEO_TARGETS = _VIDEO_BIDIRECTIONAL + _VIDEO_TARGETS_ONLY
_VIDEO_TO_ANY = _VIDEO_TARGETS + (".gif",) + _AUDIO_TARGETS
_VIDEO_INPUTS = _VIDEO_BIDIRECTIONAL + (
    ".flv", ".wmv", ".m4v", ".mpg", ".mpeg", ".3gp", ".ts", ".gif", ".dv",
)

# ---- Docs (Pandoc for non-PDF, PdfEngine for anything touching .pdf) -------
_DOC_INPUTS = (
    ".docx", ".odt", ".rtf", ".epub", ".md", ".html", ".htm", ".txt", ".tex",
    ".rst", ".org", ".textile", ".typst", ".ipynb", ".fb2", ".opml", ".muse",
    ".man", ".native", ".mediawiki", ".wiki", ".dokuwiki", ".jira", ".docbook",
)
_DOC_TARGETS = (
    ".pdf", ".docx", ".md", ".html", ".epub", ".txt", ".rtf", ".odt", ".tex",
    ".adoc", ".tei", ".icml", ".pptx",
)

_SUBTITLE_FORMATS = (".srt", ".vtt", ".ass", ".ssa", ".lrc", ".sbv")
_SHEET_FORMATS = (".csv", ".tsv", ".xlsx")
_ARCHIVE_FORMATS = (
    ".zip", ".tar", ".tgz", ".tar.gz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz",
)
_COMIC_FORMATS = (".cbz", ".cbt")
_DATA_FORMATS = (".json", ".yaml", ".yml", ".ndjson", ".jsonl", ".plist")


SUPPORTED_FORMATS: dict[str, FormatInfo] = {
    extension: FormatInfo(
        "Pillow",
        tuple(target for target in _IMAGE_TARGETS if target != extension),
    )
    for extension in _IMAGE_INPUTS
}
SUPPORTED_FORMATS.update(
    {
        extension: FormatInfo("FFmpeg", _VIDEO_TO_ANY)
        for extension in _VIDEO_INPUTS
        if extension != ".gif"
    }
)
SUPPORTED_FORMATS[".gif"] = FormatInfo("FFmpeg", _VIDEO_TARGETS)
SUPPORTED_FORMATS.update(
    {extension: FormatInfo("FFmpeg", _AUDIO_TARGETS) for extension in _AUDIO_INPUTS}
)

# PdfEngine handles anything with .pdf on either side; Pandoc does the rest.
# PDF stays first so PDF inputs default to the smart-PDF path.
SUPPORTED_FORMATS[".pdf"] = FormatInfo(
    "Pdf",
    (".pdf", ".cbz", ".docx", ".md", ".html", ".epub", ".txt", ".rtf", ".odt"),
)
SUPPORTED_FORMATS.update(
    {extension: FormatInfo("Pandoc", _DOC_TARGETS) for extension in _DOC_INPUTS}
)
SUPPORTED_FORMATS.update(
    {
        extension: FormatInfo(
            "Subtitle",
            tuple(target for target in _SUBTITLE_FORMATS if target != extension),
        )
        for extension in _SUBTITLE_FORMATS
    }
)
SUPPORTED_FORMATS.update(
    {
        extension: FormatInfo(
            "Spreadsheet",
            tuple(target for target in _SHEET_FORMATS if target != extension),
        )
        for extension in _SHEET_FORMATS
    }
)
SUPPORTED_FORMATS.update(
    {
        extension: FormatInfo(
            "Archive",
            tuple(
                target
                for target in (*_ARCHIVE_FORMATS, *_COMIC_FORMATS)
                if target != extension
            ),
        )
        for extension in _ARCHIVE_FORMATS
    }
)
SUPPORTED_FORMATS.update(
    {
        extension: FormatInfo(
            "Archive",
            (
                ".pdf",
                *(
                    target
                    for target in (*_ARCHIVE_FORMATS, *_COMIC_FORMATS)
                    if target != extension
                ),
            ),
        )
        for extension in _COMIC_FORMATS
    }
)
SUPPORTED_FORMATS.update(
    {
        extension: FormatInfo(
            "Data",
            tuple(target for target in _DATA_FORMATS if target != extension),
        )
        for extension in _DATA_FORMATS
    }
)


def info_for(extension: str) -> FormatInfo | None:
    return SUPPORTED_FORMATS.get(extension.lower())


def targets_for(extension: str) -> tuple[str, ...]:
    info = info_for(extension)
    return info.targets if info else ()


def common_targets(extensions: Iterable[str]) -> tuple[str, ...]:
    """Intersection of ``targets_for(ext)`` across ``extensions``.

    Order is taken from the first input's ``targets_for`` so the dropdown
    is deterministic instead of arbitrary set-iteration order.
    Returns ``()`` for empty input or when the intersection is empty
    (e.g. mixing image + video).
    """
    exts = list(extensions)
    if not exts:
        return ()
    first = targets_for(exts[0])
    if not first:
        return ()
    common = set(first)
    for ext in exts[1:]:
        common &= set(targets_for(ext))
        if not common:
            return ()
    return tuple(t for t in first if t in common)


def engine_for(ext_in: str, ext_out: str) -> str | None:
    """Pick the right engine considering both endpoints (PDF overrides Pandoc)."""
    info = info_for(ext_in)
    if info is None or ext_out.lower() not in info.targets:
        return None
    if ext_in.lower() == ".pdf" or ext_out.lower() == ".pdf":
        return "Pdf"
    return info.engine


def effective_suffix(path: Path) -> str:
    """Return the routing-relevant extension for ``path``.

    Honours compound suffixes such as ``.tar.gz`` — ``Path.suffix`` alone
    returns ``.gz``, which would either misroute the file or drop it on the
    floor entirely. Falls back to ``path.suffix.lower()`` for everything
    else, so existing single-suffix call sites keep working unchanged.
    """
    name = path.name.lower()
    for compound in _COMPOUND_SUFFIXES:
        if name.endswith(compound):
            return compound
    return path.suffix.lower()


def effective_stem(path: Path) -> str:
    """Return ``path.stem`` adjusted for compound suffixes.

    For ``foo.tar.gz`` this yields ``foo`` (not ``foo.tar``) so output-path
    construction can append a fresh target extension without producing
    weird names like ``foo.tar.zip``.
    """
    ext = effective_suffix(path)
    if ext in _COMPOUND_SUFFIXES:
        # A file literally named ``.tar.gz`` has an empty stem; without the
        # fallback the output would be a hidden file named just ``.zip``.
        return path.name[: -len(ext)] or "output"
    return path.stem


# ---- Display grouping (for the "Supported formats" dialog) -----------------
# Ordered so the UI renders Video → Audio → Images → Documents.
FORMAT_CATEGORIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Video", _VIDEO_INPUTS),
    ("Audio", _AUDIO_INPUTS),
    ("Images", _IMAGE_INPUTS),
    ("Documents", (".pdf", *_DOC_INPUTS)),
    ("Comics", _COMIC_FORMATS),
    ("Subtitles", _SUBTITLE_FORMATS),
    ("Spreadsheets", _SHEET_FORMATS),
    ("Archives", _ARCHIVE_FORMATS),
    ("Data", _DATA_FORMATS),
)

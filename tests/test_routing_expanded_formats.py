from itertools import permutations
from pathlib import Path

import pytest

from cove_converter.routing import (
    effective_stem,
    effective_suffix,
    engine_for,
    info_for,
    targets_for,
)


COMPOUND_ARCHIVES = (
    (".tar.bz2", ".tbz2"),
    (".tar.xz", ".txz"),
)

BIDIRECTIONAL_DOCS = (
    ".docx",
    ".odt",
    ".rtf",
    ".epub",
    ".md",
    ".html",
    ".txt",
    ".tex",
)

OUTPUT_ONLY_DOCS = (
    ".adoc",
    ".tei",
    ".icml",
    ".pptx",
)

VIDEO_INPUT_ONLY = (
    ".flv",
    ".wmv",
    ".m4v",
    ".mpg",
    ".mpeg",
    ".3gp",
    ".ts",
    ".dv",
)

VIDEO_BIDIRECTIONAL_CONTAINERS = (
    ".mxf",
    ".rm",
    ".vob",
    ".asf",
    ".ogv",
    ".m2ts",
    ".mts",
    ".f4v",
    ".swf",
)

VIDEO_OUTPUT_ONLY = (
    ".y4m",
    ".ivf",
)

SUBTITLE_FORMATS = (
    ".srt",
    ".vtt",
    ".ass",
    ".ssa",
    ".lrc",
    ".sbv",
)


@pytest.mark.parametrize(("suffix", "alias"), COMPOUND_ARCHIVES)
def test_compound_archive_suffixes_and_aliases_route(
    suffix: str,
    alias: str,
) -> None:
    path = Path(f"bundle{suffix.upper()}")

    assert effective_suffix(path) == suffix
    assert effective_stem(path) == "bundle"
    assert engine_for(suffix, ".zip") == "Archive"
    assert engine_for(".zip", suffix) == "Archive"
    assert engine_for(alias, suffix) == "Archive"


@pytest.mark.parametrize(
    ("source", "target"),
    tuple(permutations(BIDIRECTIONAL_DOCS, 2)),
)
def test_bidirectional_document_routes_use_pandoc(
    source: str,
    target: str,
) -> None:
    assert engine_for(source, target) == "Pandoc"


@pytest.mark.parametrize("source", BIDIRECTIONAL_DOCS)
def test_document_to_pdf_routes_use_pdf_engine(source: str) -> None:
    assert engine_for(source, ".pdf") == "Pdf"


@pytest.mark.parametrize("target", OUTPUT_ONLY_DOCS)
def test_output_only_document_formats_are_targets_not_inputs(target: str) -> None:
    assert info_for(target) is None
    assert engine_for(".md", target) == "Pandoc"
    assert engine_for(".pdf", target) is None
    assert engine_for(target, ".md") is None


def test_pdf_targets_match_worker_capabilities() -> None:
    assert targets_for(".pdf") == (
        ".pdf",
        ".cbz",
        ".docx",
        ".md",
        ".html",
        ".epub",
        ".txt",
        ".rtf",
        ".odt",
    )


@pytest.mark.parametrize("source", VIDEO_INPUT_ONLY)
def test_input_only_video_routes_to_video_and_audio(source: str) -> None:
    info = info_for(source)

    assert info is not None
    assert info.engine == "FFmpeg"
    assert engine_for(source, ".mp4") == "FFmpeg"
    assert engine_for(source, ".mp3") == "FFmpeg"
    assert engine_for(".mp4", source) is None
    assert engine_for(source, source) is None


@pytest.mark.parametrize("source", VIDEO_BIDIRECTIONAL_CONTAINERS)
def test_expanded_video_containers_are_bidirectional_targets(
    source: str,
) -> None:
    info = info_for(source)

    assert info is not None
    assert info.engine == "FFmpeg"
    assert engine_for(source, ".mp4") == "FFmpeg"
    assert engine_for(".mp4", source) == "FFmpeg"


@pytest.mark.parametrize("target", VIDEO_OUTPUT_ONLY)
def test_raw_video_formats_are_targets_not_inputs(target: str) -> None:
    assert info_for(target) is None
    assert engine_for(".mp4", target) == "FFmpeg"
    assert engine_for(target, ".mp4") is None


@pytest.mark.parametrize(
    ("source", "target", "expected_engine"),
    (
        (".cbz", ".pdf", "Pdf"),
        (".cbt", ".pdf", "Pdf"),
        (".pdf", ".cbz", "Pdf"),
        (".zip", ".cbz", "Archive"),
        (".tar.bz2", ".cbt", "Archive"),
        (".cbz", ".zip", "Archive"),
        (".cbz", ".cbt", "Archive"),
    ),
)
def test_comic_pdf_and_archive_routes_use_expected_engine(
    source: str,
    target: str,
    expected_engine: str,
) -> None:
    assert engine_for(source, target) == expected_engine


@pytest.mark.parametrize(
    ("source", "target"),
    tuple(permutations(SUBTITLE_FORMATS, 2)),
)
def test_subtitle_formats_route_pairwise(source: str, target: str) -> None:
    assert engine_for(source, target) == "Subtitle"


@pytest.mark.parametrize("extension", SUBTITLE_FORMATS)
def test_subtitle_formats_do_not_advertise_identity_routes(
    extension: str,
) -> None:
    assert engine_for(extension, extension) is None


@pytest.mark.parametrize(
    ("source", "target", "expected_engine"),
    (
        (".jfif", ".png", "Pillow"),
        (".j2k", ".jpg", "Pillow"),
        (".icns", ".webp", "Pillow"),
        (".avif", ".pdf", "Pdf"),
        (".ndjson", ".plist", "Data"),
        (".plist", ".json", "Data"),
        (".tsv", ".csv", "Spreadsheet"),
        (".tsv", ".xlsx", "Spreadsheet"),
        (".csv", ".tsv", "Spreadsheet"),
    ),
)
def test_representative_image_data_and_tsv_routes(
    source: str,
    target: str,
    expected_engine: str,
) -> None:
    assert engine_for(source, target) == expected_engine

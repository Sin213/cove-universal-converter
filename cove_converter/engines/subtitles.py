"""Subtitle worker — converts between SubRip (.srt) and WebVTT (.vtt).

These two account for the vast majority of subtitle workflows: SRT for
broadcast/legacy/Netflix/YouTube, VTT for HTML5/WebVTT browsers and modern
streaming pipelines. The semantic difference is small enough to handle with
text-level rewriting — no third-party dep needed.

Conversion rules:
- SRT timestamp:  00:00:01,234 --> 00:00:04,567
- VTT timestamp:  00:00:01.234 --> 00:00:04.567
- VTT files start with the literal `WEBVTT` line plus a blank line.
- SRT cue indices are optional in VTT and we drop them on .srt -> .vtt; on
  the way back we synthesise sequential indices.
"""
from __future__ import annotations

import re
from pathlib import Path

from cove_converter.engines.base import BaseConverterWorker


_TS_SRT = re.compile(
    r"(\d{2}:\d{2}:\d{2}),(\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}),(\d{3})",
)
_TS_VTT = re.compile(
    r"(\d{2}:\d{2}:\d{2})\.(\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2})\.(\d{3})",
)
# Full VTT timing line including any trailing cue settings (align:, line:,
# position:, size:, vertical:, region:). SRT does not support cue settings,
# so we drop everything after the end timestamp on .vtt -> .srt.
#
# WebVTT permits both `HH:MM:SS.mmm` and the hourless `MM:SS.mmm` forms; SRT
# requires the full `HH:MM:SS,mmm` form, so hourless timestamps are padded
# with `00:` in the substitution below.
_VTT_TS = r"((?:\d{2}:)?\d{2}:\d{2})\.(\d{3})"
_TS_VTT_LINE = re.compile(
    rf"{_VTT_TS}\s*-->\s*{_VTT_TS}[^\n]*",
)


def _vtt_to_srt_ts(main: str) -> str:
    """Pad WebVTT's hourless `MM:SS` form to SRT's required `HH:MM:SS`."""
    return main if main.count(":") == 2 else f"00:{main}"


def _read_text(path: Path) -> str:
    # Subtitle files are typically UTF-8 but legacy Windows-1252 is common.
    # `errors='replace'` is preferable to crashing on a stray byte.
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _srt_to_vtt(text: str) -> str:
    # Normalize line endings, then convert ',' → '.' in timestamps and
    # strip the optional cue-index lines.
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    text = _TS_SRT.sub(r"\1.\2 --> \3.\4", text)

    cleaned_blocks: list[str] = []
    for block in text.split("\n\n"):
        lines = block.split("\n")
        # Drop a leading numeric-only "1" / "2" / … cue-index line.
        if lines and lines[0].strip().isdigit():
            lines = lines[1:]
        if lines:
            cleaned_blocks.append("\n".join(lines))

    return "WEBVTT\n\n" + "\n\n".join(cleaned_blocks) + "\n"


def _vtt_to_srt(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()

    # Drop the WEBVTT header (and any optional metadata block before the
    # first blank line that follows it).
    if text.upper().startswith("WEBVTT"):
        # Cut to the first blank-line break so STYLE/NOTE/REGION blocks
        # and the WEBVTT preamble all fall away.
        first_break = text.find("\n\n")
        text = "" if first_break == -1 else text[first_break + 2 :]

    # `.` → `,` in timestamps, pad hourless `MM:SS.mmm` to `HH:MM:SS,mmm`,
    # and drop any trailing VTT cue settings (align:start, line:90%,
    # position:50%, etc.) — SRT does not support them.
    def _rewrite(match: re.Match) -> str:
        start_main, start_ms, end_main, end_ms = match.group(1, 2, 3, 4)
        return (
            f"{_vtt_to_srt_ts(start_main)},{start_ms} --> "
            f"{_vtt_to_srt_ts(end_main)},{end_ms}"
        )

    text = _TS_VTT_LINE.sub(_rewrite, text)

    out_blocks: list[str] = []
    index = 1
    for raw_block in text.split("\n\n"):
        lines = [line for line in raw_block.split("\n") if line.strip()]
        if not lines:
            continue
        # Skip VTT-only blocks (NOTE / STYLE / REGION). Per the WebVTT spec
        # these keywords identify a metadata block only when the first line
        # is the bare keyword or the keyword followed by whitespace — a cue
        # identifier like ``NOTE1`` or ``STYLE_A`` is a valid cue, not
        # metadata, so it must not be dropped.
        first = lines[0].strip()
        first_token = first.split(None, 1)[0] if first else ""
        if first_token.upper() in ("NOTE", "STYLE", "REGION"):
            continue
        # Skip the optional cue identifier (a non-timestamp line before
        # the timestamp line).
        if "-->" not in lines[0] and len(lines) > 1 and "-->" in lines[1]:
            lines = lines[1:]
        if "-->" not in lines[0]:
            continue
        out_blocks.append(f"{index}\n" + "\n".join(lines))
        index += 1

    return "\n\n".join(out_blocks) + "\n"


class SubtitleWorker(BaseConverterWorker):
    def _convert(self) -> None:
        in_ext = self.input_path.suffix.lower()
        out_ext = self.output_path.suffix.lower()
        self.progress.emit(20)

        text = _read_text(self.input_path)
        self.progress.emit(50)

        if in_ext == ".srt" and out_ext == ".vtt":
            converted = _srt_to_vtt(text)
        elif in_ext == ".vtt" and out_ext == ".srt":
            converted = _vtt_to_srt(text)
        else:
            raise RuntimeError(f"SubtitleWorker cannot convert {in_ext} → {out_ext}")

        self.progress.emit(85)
        self.output_path.write_text(converted, encoding="utf-8")

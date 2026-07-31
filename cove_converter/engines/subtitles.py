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
import subprocess
import sys
import tempfile
from pathlib import Path

from cove_converter.binaries import FFMPEG, resolve
from cove_converter.engines.base import BaseConverterWorker


_SRT_TS = r"(\d{2,}:\d{2}:\d{2}),(\d{3})"
_TS_SRT_LINE = re.compile(
    rf"^{_SRT_TS}\s*-->\s*{_SRT_TS}([^\r\n]*)$",
    re.MULTILINE,
)
# Full VTT timing line including any trailing cue settings (align:, line:,
# position:, size:, vertical:, region:). SRT does not support cue settings,
# so we drop everything after the end timestamp on .vtt -> .srt.
#
# WebVTT permits both `HH:MM:SS.mmm` and the hourless `MM:SS.mmm` forms; SRT
# requires the full `HH:MM:SS,mmm` form, so hourless timestamps are padded
# with `00:` in the substitution below.
_VTT_TS = r"((?:\d{2,}:)?\d{2}:\d{2})\.(\d{3})"
_TS_VTT_LINE = re.compile(
    rf"^{_VTT_TS}\s*-->\s*{_VTT_TS}[^\r\n]*$",
    re.MULTILINE,
)
_SBV_TIMING_LINE = re.compile(
    r"^(?P<start_h>\d+):(?P<start_m>\d{2}):(?P<start_s>\d{2})"
    r"\.(?P<start_ms>\d{3}),(?P<end_h>\d+):(?P<end_m>\d{2}):"
    r"(?P<end_s>\d{2})\.(?P<end_ms>\d{3})$"
)
_MANUAL_FORMATS = frozenset({".srt", ".vtt", ".sbv"})
_FFMPEG_MUXERS = {
    ".srt": "srt",
    ".vtt": "webvtt",
    ".ass": "ass",
    ".ssa": "ass",
    ".lrc": "lrc",
}


def _vtt_to_srt_ts(main: str) -> str:
    """Pad WebVTT's hourless `MM:SS` form to SRT's required `HH:MM:SS`."""
    return main if main.count(":") == 2 else f"00:{main}"


def _read_text(path: Path) -> str:
    # Subtitle files are typically UTF-8 but legacy Windows-1252 is common.
    # `errors='replace'` is preferable to crashing on a stray byte.
    raw = path.read_bytes()
    # Check UTF-32 before UTF-16 because little-endian UTF-32 shares UTF-16's
    # first two BOM bytes.
    if raw.startswith((b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff")):
        try:
            return raw.decode("utf-32")
        except UnicodeDecodeError:
            pass
    # UTF-16 SRTs are common from Windows tools.
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return raw.decode("utf-16")
        except UnicodeDecodeError:
            pass
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
    cleaned_blocks: list[str] = []
    for block in text.split("\n\n"):
        lines = block.split("\n")
        # Drop a leading numeric-only "1" / "2" / … cue-index line.
        if lines and lines[0].strip().isdigit():
            lines = lines[1:]
        if lines and _TS_SRT_LINE.fullmatch(lines[0]):
            lines[0] = _TS_SRT_LINE.sub(
                r"\1.\2 --> \3.\4\5",
                lines[0],
                count=1,
            )
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
        if (
            not _TS_VTT_LINE.fullmatch(lines[0])
            and len(lines) > 1
            and _TS_VTT_LINE.fullmatch(lines[1])
        ):
            lines = lines[1:]
        if not _TS_VTT_LINE.fullmatch(lines[0]):
            continue
        lines[0] = _TS_VTT_LINE.sub(_rewrite, lines[0], count=1)
        out_blocks.append(f"{index}\n" + "\n".join(lines))
        index += 1

    return "\n\n".join(out_blocks) + "\n"


def _sbv_to_srt(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    out_blocks: list[str] = []
    for cue_number, raw_block in enumerate(text.split("\n\n"), start=1):
        lines = raw_block.split("\n")
        if not lines:
            raise RuntimeError(f"Invalid SBV cue {cue_number}: missing timing")
        match = _SBV_TIMING_LINE.fullmatch(lines[0].strip())
        if match is None:
            raise RuntimeError(
                f"Invalid SBV timing in cue {cue_number}: {lines[0]!r}"
            )
        start = (
            f"{int(match['start_h']):02d}:{match['start_m']}:{match['start_s']},"
            f"{match['start_ms']}"
        )
        end = (
            f"{int(match['end_h']):02d}:{match['end_m']}:{match['end_s']},"
            f"{match['end_ms']}"
        )
        out_blocks.append(
            f"{len(out_blocks) + 1}\n{start} --> {end}\n" + "\n".join(lines[1:])
        )
    return "\n\n".join(out_blocks) + "\n"


def _srt_to_sbv(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    out_blocks: list[str] = []
    for cue_number, raw_block in enumerate(text.split("\n\n"), start=1):
        lines = raw_block.split("\n")
        if lines and lines[0].strip().isdigit():
            lines = lines[1:]
        if not lines:
            raise RuntimeError(f"Invalid SRT cue {cue_number}: missing timing")
        match = _TS_SRT_LINE.fullmatch(lines[0])
        if match is None:
            raise RuntimeError(
                f"Invalid SRT timing in cue {cue_number}: {lines[0]!r}"
            )
        timing = (
            f"{match.group(1)}.{match.group(2)},"
            f"{match.group(3)}.{match.group(4)}"
        )
        out_blocks.append(timing + "\n" + "\n".join(lines[1:]))
    return "\n\n".join(out_blocks) + "\n"


def _manual_convert(text: str, in_ext: str, out_ext: str) -> str:
    if in_ext == ".srt":
        srt = text
    elif in_ext == ".vtt":
        srt = _vtt_to_srt(text)
    elif in_ext == ".sbv":
        srt = _sbv_to_srt(text)
    else:
        raise RuntimeError(f"Unsupported manual subtitle input: {in_ext}")

    if out_ext == ".srt":
        return srt
    if out_ext == ".vtt":
        return _srt_to_vtt(srt)
    if out_ext == ".sbv":
        return _srt_to_sbv(srt)
    raise RuntimeError(f"Unsupported manual subtitle output: {out_ext}")


def _no_window_kwargs() -> dict:
    if sys.platform.startswith("win"):
        return {"creationflags": 0x08000000}  # CREATE_NO_WINDOW
    return {}


class SubtitleWorker(BaseConverterWorker):
    def _run_ffmpeg(self, source: Path, target: Path, out_ext: str) -> None:
        muxer = _FFMPEG_MUXERS[out_ext]
        proc = subprocess.Popen(
            [
                resolve(FFMPEG),
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(source),
                "-f",
                muxer,
                str(target),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            **_no_window_kwargs(),
        )
        stderr = ""
        while True:
            try:
                _, stderr = proc.communicate(timeout=0.1)
                break
            except subprocess.TimeoutExpired:
                if not self._cancel:
                    continue
                proc.terminate()
                _, stderr = proc.communicate()
                return
        if proc.returncode != 0:
            detail = stderr.strip()
            message = f"ffmpeg subtitle conversion failed with code {proc.returncode}"
            if detail:
                message += f": {detail[-500:]}"
            raise RuntimeError(message)

    def _convert(self) -> None:
        in_ext = self.input_path.suffix.lower()
        out_ext = self.output_path.suffix.lower()
        self.progress.emit(20)

        if in_ext in _MANUAL_FORMATS and out_ext in _MANUAL_FORMATS:
            converted = _manual_convert(_read_text(self.input_path), in_ext, out_ext)
            self.progress.emit(85)
            self.output_path.write_text(converted, encoding="utf-8")
            return

        self.progress.emit(50)
        if in_ext == ".sbv":
            with tempfile.TemporaryDirectory(prefix="cove-subtitles-") as temp_dir:
                source = Path(temp_dir) / "source.srt"
                source.write_text(
                    _sbv_to_srt(_read_text(self.input_path)),
                    encoding="utf-8",
                )
                self._run_ffmpeg(source, self.output_path, out_ext)
        elif out_ext == ".sbv":
            with tempfile.TemporaryDirectory(prefix="cove-subtitles-") as temp_dir:
                target = Path(temp_dir) / "target.srt"
                self._run_ffmpeg(self.input_path, target, ".srt")
                if self._cancel:
                    return
                self.output_path.write_text(
                    _srt_to_sbv(_read_text(target)),
                    encoding="utf-8",
                )
        elif out_ext in _FFMPEG_MUXERS:
            self._run_ffmpeg(self.input_path, self.output_path, out_ext)
        else:
            raise RuntimeError(f"SubtitleWorker cannot convert {in_ext} → {out_ext}")
        self.progress.emit(85)

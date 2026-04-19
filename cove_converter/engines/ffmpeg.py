from __future__ import annotations

import re
import subprocess
import sys

from cove_converter.binaries import FFMPEG, resolve
from cove_converter.engines.base import BaseConverterWorker

_DURATION_RE = re.compile(r"Duration:\s+(\d+):(\d+):(\d+\.\d+)")
_TIME_RE     = re.compile(r"time=(\d+):(\d+):(\d+\.\d+)")

_AUDIO_ONLY_EXTS = {
    ".mp3", ".wav", ".flac", ".ogg", ".m4a",
    ".aac", ".opus", ".wma", ".aiff",
}

_AUDIO_CODEC: dict[str, str] = {
    ".mp3":  "libmp3lame",
    ".wav":  "pcm_s16le",
    ".flac": "flac",
    ".ogg":  "libvorbis",
    ".m4a":  "aac",
    ".aac":  "aac",
    ".opus": "libopus",
    ".wma":  "wmav2",
    ".aiff": "pcm_s16be",
}

_VIDEO_CODEC: dict[str, str] = {
    ".webm": "libvpx-vp9",
    ".mkv":  "libx264",
    ".mp4":  "libx264",
    ".mov":  "libx264",
    ".avi":  "mpeg4",
    ".flv":  "libx264",
    ".wmv":  "wmv2",
    ".m4v":  "libx264",
    ".mpg":  "mpeg2video",
    ".mpeg": "mpeg2video",
    ".3gp":  "libx264",
    ".ts":   "libx264",
}

_LOSSLESS_AUDIO = {"pcm_s16le", "pcm_s16be", "flac"}


def _hhmmss_to_seconds(h: str, m: str, s: str) -> float:
    return int(h) * 3600 + int(m) * 60 + float(s)


def _no_window_kwargs() -> dict:
    if sys.platform.startswith("win"):
        return {"creationflags": 0x08000000}  # CREATE_NO_WINDOW
    return {}


class FFmpegWorker(BaseConverterWorker):
    """ffmpeg worker.

    Builds codec args from the output extension and the user's quality settings,
    then drives a progress bar off ffmpeg's own ``time=`` vs ``Duration:`` output.
    """

    def _build_cmd(self) -> list[str]:
        s = self.settings
        out_ext = self.output_path.suffix.lower()
        cmd = [resolve(FFMPEG), "-y", "-i", str(self.input_path)]

        if out_ext == ".gif":
            # Palette-less but decent default for GIFs from video.
            cmd += ["-vf", "fps=15,scale=480:-1:flags=lanczos", str(self.output_path)]
            return cmd

        abr = s.effective_audio_bitrate()

        if out_ext in _AUDIO_ONLY_EXTS:
            codec = _AUDIO_CODEC.get(out_ext, "aac")
            cmd += ["-vn", "-c:a", codec]
            if codec not in _LOSSLESS_AUDIO:
                cmd += ["-b:a", f"{abr}k"]
            cmd += [str(self.output_path)]
            return cmd

        # Video output — pair a sensible audio codec with the container.
        vcodec = _VIDEO_CODEC.get(out_ext, "libx264")
        acodec = "libopus" if out_ext == ".webm" else "aac"
        crf = s.effective_video_crf()
        preset = s.effective_video_preset()
        cmd += ["-c:v", vcodec]
        if vcodec in ("libx264", "libx265"):
            cmd += ["-crf", str(crf), "-preset", preset]
        elif vcodec == "libvpx-vp9":
            cmd += ["-crf", str(crf), "-b:v", "0"]
        cmd += ["-c:a", acodec, "-b:a", f"{abr}k"]
        cmd += [str(self.output_path)]
        return cmd

    def _convert(self) -> None:
        cmd = self._build_cmd()
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            **_no_window_kwargs(),
        )
        total_seconds: float | None = None

        assert proc.stderr is not None
        for line in proc.stderr:
            if self._cancel:
                proc.terminate()
                break
            if total_seconds is None:
                m = _DURATION_RE.search(line)
                if m:
                    total_seconds = _hhmmss_to_seconds(*m.groups())
            t = _TIME_RE.search(line)
            if t and total_seconds:
                elapsed = _hhmmss_to_seconds(*t.groups())
                pct = max(0, min(99, int(elapsed / total_seconds * 100)))
                self.progress.emit(pct)

        rc = proc.wait()
        if rc != 0 and not self._cancel:
            raise RuntimeError(f"ffmpeg exited with code {rc}")

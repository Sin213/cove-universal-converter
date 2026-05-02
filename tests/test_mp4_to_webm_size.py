"""Regression: default MP4 -> WebM must not grossly inflate the source.

A previous default (libvpx-vp9 CRF 32, deadline=best implicit) produced WebM
files 1.5-5x the size of typical MP4 inputs. The fix shipped a size-aware
balanced default (CRF 36, deadline good, cpu-used 4, opus 96k). This test
guards that policy: if a future change reverts toward a near-lossless default,
the ratio assertion fails loudly with the actual sizes printed.

The test uses a generated representative MP4 (lavfi testsrc2 + sine, h264 +
aac, 720p) so it stays self-contained. Also runs the path through the real
``FFmpegWorker._convert`` so any regression in the command builder shows up
here too.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from cove_converter.engines.ffmpeg import FFmpegWorker  # noqa: E402
from cove_converter.settings import default_settings  # noqa: E402


# Generated MP4 is highly compressible flat-ish content; even small inflation
# would be a real regression. 1.25x leaves room for container overhead on
# very short clips without masking real bloat.
MAX_RATIO = 1.25


def _have_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


def _make_h264_sample(dest: Path, *, seconds: float = 3.0) -> None:
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-t", str(seconds),
        "-i", "testsrc2=size=1280x720:rate=30",
        "-f", "lavfi", "-t", str(seconds),
        "-i", "sine=frequency=440:sample_rate=44100",
        "-ac", "2", "-c:v", "libx264", "-crf", "23", "-preset", "veryfast",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-shortest",
        str(dest),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"ffmpeg exited {proc.returncode}")


def _run_ffmpeg_worker(in_path: Path, out_path: Path) -> list[str]:
    cls = FFmpegWorker
    w = cls.__new__(cls)
    w.input_path = in_path
    w.output_path = out_path
    w._final_output_path = out_path
    w._owned_temp_path = None
    w.settings = default_settings()
    w._cancel = False
    w.progress = mock.Mock()
    w.status = mock.Mock()
    w.finished_ok = mock.Mock()
    w.failed = mock.Mock()
    cmd = w._build_cmd()
    w._convert()
    return cmd


@unittest.skipUnless(_have_ffmpeg(), "ffmpeg not on PATH")
class Mp4ToWebmDefaultSize(unittest.TestCase):
    def test_default_does_not_grossly_inflate_mp4(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cove-mp4-webm-") as td:
            work = Path(td)
            src = work / "sample.mp4"
            dst = work / "sample.webm"
            _make_h264_sample(src)

            in_size = src.stat().st_size
            self.assertGreater(in_size, 0, "sample MP4 was empty")

            cmd = _run_ffmpeg_worker(src, dst)

            self.assertTrue(dst.exists(), f"WebM output missing: {dst}")
            out_size = dst.stat().st_size
            self.assertGreater(out_size, 0, "WebM output empty")

            ratio = out_size / in_size
            print(
                f"\nMP4->WebM default sizing:"
                f"\n  cmd:   {' '.join(cmd)}"
                f"\n  in:    {in_size} bytes ({in_size/1024:.1f} KiB)"
                f"\n  out:   {out_size} bytes ({out_size/1024:.1f} KiB)"
                f"\n  ratio: {ratio:.3f}"
            )
            self.assertLessEqual(
                ratio, MAX_RATIO,
                f"WebM bloated source: ratio {ratio:.3f} > {MAX_RATIO}",
            )

    def test_default_command_uses_size_aware_policy(self) -> None:
        """Pin the default flags so silent regressions in _build_cmd fail."""
        cls = FFmpegWorker
        w = cls.__new__(cls)
        w.input_path = Path("/tmp/x.mp4")
        w.output_path = Path("/tmp/x.webm")
        w._final_output_path = w.output_path
        w._owned_temp_path = None
        w.settings = default_settings()
        w._cancel = False
        w.progress = mock.Mock()
        w.status = mock.Mock()
        w.finished_ok = mock.Mock()
        w.failed = mock.Mock()
        cmd = w._build_cmd()
        # Codec
        self.assertIn("libvpx-vp9", cmd)
        self.assertIn("libopus", cmd)
        # CRF must be size-aware (>= 34); old default 32 caused 1.5x bloat.
        crf_idx = cmd.index("-crf")
        self.assertGreaterEqual(int(cmd[crf_idx + 1]), 34,
                                f"VP9 default CRF too aggressive on quality: {cmd[crf_idx+1]}")
        # Encode-time guards.
        self.assertIn("-deadline", cmd)
        self.assertIn("good", cmd)
        self.assertIn("-cpu-used", cmd)
        # Audio bitrate cap for default path (no 320k near-lossless).
        ab_idx = cmd.index("-b:a")
        ab_kbps = int(cmd[ab_idx + 1].rstrip("k"))
        self.assertLessEqual(ab_kbps, 128,
                             f"Opus default bitrate too high: {cmd[ab_idx+1]}")
        # yuv420p forced for compatibility.
        self.assertIn("yuv420p", cmd)


if __name__ == "__main__":
    unittest.main()

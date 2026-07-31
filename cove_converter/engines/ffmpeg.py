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
    ".aac", ".opus", ".wma", ".aiff", ".aif",
    ".ac3", ".mp2", ".spx", ".caf", ".au",
    ".wv", ".voc", ".w64", ".mka", ".m4b",
    ".oga", ".tta", ".amr", ".weba",
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
    ".aif":  "pcm_s16be",
    ".ac3":  "ac3",
    ".mp2":  "mp2",
    ".spx":  "libspeex",
    ".caf":  "pcm_s16le",
    ".au":   "pcm_s16be",
    ".wv":   "wavpack",
    ".voc":  "pcm_s16le",
    ".w64":  "pcm_s16le",
    ".mka":  "libopus",
    ".m4b":  "aac",
    ".oga":  "libvorbis",
    ".tta":  "tta",
    ".amr":  "libopencore_amrnb",
    ".weba": "libopus",
}

_AUDIO_MUXER: dict[str, str] = {
    # ffmpeg does not infer the WebM muxer from the de-facto .weba suffix.
    ".weba": "webm",
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
    ".mxf":  "mpeg2video",
    ".rm":   "rv10",
    ".swf":  "flv1",
    ".vob":  "mpeg2video",
    ".asf":  "msmpeg4v3",
    ".ogv":  "libtheora",
    ".m2ts": "mpeg2video",
    ".mts":  "mpeg2video",
    ".f4v":  "libx264",
    ".y4m":  "rawvideo",
    ".ivf":  "libvpx-vp9",
}

_VIDEO_AUDIO_CODEC: dict[str, str] = {
    ".webm": "libopus",
    ".mxf":  "pcm_s16le",
    ".rm":   "ac3",
    ".swf":  "libmp3lame",
    ".vob":  "mp2",
    ".asf":  "wmav2",
    ".ogv":  "libvorbis",
    ".m2ts": "mp2",
    ".mts":  "mp2",
}

_VIDEO_ONLY_EXTS = {".y4m", ".ivf"}

# Software H.264/H.265/AV1 encoders and their (NVENC, AMF) equivalents.
_HW_EQUIV: dict[str, tuple[str, str]] = {
    "libx264": ("h264_nvenc", "h264_amf"),
    "libx265": ("hevc_nvenc", "hevc_amf"),
    "libaom-av1": ("av1_nvenc", "av1_amf"),
}

# Hardware encoders reachable from static mappings or selectable codec paths.
_HW_OUTPUT_CODECS = {
    codec
    for codec in (*_VIDEO_CODEC.values(), "libaom-av1")
    if codec in _HW_EQUIV
}
NVENC_ENCODERS: tuple[str, ...] = tuple(
    sorted({_HW_EQUIV[c][0] for c in _HW_OUTPUT_CODECS}))
AMF_ENCODERS: tuple[str, ...] = tuple(
    sorted({_HW_EQUIV[c][1] for c in _HW_OUTPUT_CODECS}))

# yuv420p + even dimensions. yuv420p needs even dims; ceil (not trunc) so a
# 1-pixel axis rounds up to 2 instead of collapsing to 0. Hardware encoders
# need even dims too, so this applies to every video branch.
_EVEN_SCALE_ARGS = ["-pix_fmt", "yuv420p", "-vf", "scale=ceil(iw/2)*2:ceil(ih/2)*2"]


def hw_encode_args(encoder: str, crf: int) -> list[str]:
    """Vendor-specific encode options for a hardware (NVENC/AMF) encoder.

    Shared by ``_build_cmd`` and the hwaccel detection probe so detection
    validates the exact option set production will emit — not just that the
    encoder name exists and runs with defaults. A build/driver that exposes the
    encoder but rejects one of these options fails the probe and falls back to
    CPU instead of failing the real job.
    """
    if encoder.endswith("_nvenc"):
        return ["-c:v", encoder, "-preset", "p5", "-tune", "hq",
                "-rc", "vbr", "-cq", str(crf), "-b:v", "0"]
    if encoder.endswith("_amf"):
        # AMF CQP has no single -qp knob; it exposes per-frame-type quantizers.
        return ["-c:v", encoder, "-quality", "balanced",
                "-usage", "transcoding", "-rc", "cqp",
                "-qp_i", str(crf), "-qp_p", str(crf), "-qp_b", str(crf)]
    return ["-c:v", encoder]


_LOSSLESS_AUDIO = {"pcm_s16le", "pcm_s16be", "flac", "wavpack", "tta", "alac"}


def _audio_encode_args(codec: str, bitrate_kbps: int) -> list[str]:
    args = ["-c:a", codec]
    if codec in _LOSSLESS_AUDIO:
        return args

    if codec == "libopencore_amrnb":
        # AMR-NB is fixed to 8 kHz mono and accepts only a small set of bitrates.
        return [*args, "-ar", "8000", "-ac", "1", "-b:a", "12.2k"]
    if codec == "libopus":
        bitrate_kbps = min(bitrate_kbps, 256)
    elif codec == "libvorbis":
        # Vorbis cannot encode the low sample rates used by formats such as
        # AMR-NB, and libvorbis rejects very high rates for mono input.
        args += ["-ar", "44100"]
        bitrate_kbps = min(bitrate_kbps, 192)
    elif codec == "libspeex":
        args += ["-ar", "32000"]
        bitrate_kbps = min(bitrate_kbps, 44)

    return [*args, "-b:a", f"{bitrate_kbps}k"]


# WebM defaults. VP9's CRF scale runs hotter than x264's: the near-lossless
# x264 default (CRF 17) translates to roughly VP9 CRF 24 and bloats typical
# web-source MP4s by 5-10x. CRF 32 still inflates 1080p sources (~1.5x on an
# AV1-encoded MP4 in our smoke). Use a size-aware balanced default and let the
# user opt into custom quality with the sliders for higher fidelity. Opus is
# transparent well below 128 kbps for typical content, so default lower too.
_WEBM_DEFAULT_VP9_CRF   = 36
_WEBM_DEFAULT_OPUS_KBPS = 96
_WEBM_DEFAULT_CPU_USED  = "4"


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
        # Imported lazily: hwaccel imports _no_window_kwargs from this module,
        # so a top-level import here would be circular.
        from cove_converter.engines import hwaccel

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
            if out_ext == ".m4a" and getattr(s, "m4a_codec", "aac") == "alac":
                codec = "alac"
            cmd += ["-vn", *_audio_encode_args(codec, abr)]
            muxer = _AUDIO_MUXER.get(out_ext)
            if muxer:
                cmd += ["-f", muxer]
            cmd += [str(self.output_path)]
            return cmd

        # Video output — pair a sensible audio codec with the container.
        vcodec = _VIDEO_CODEC.get(out_ext, "libx264")
        if (
            out_ext in {".mp4", ".mkv"}
            and getattr(s, "video_codec", "h264") == "av1"
        ):
            vcodec = "libaom-av1"
        acodec = _VIDEO_AUDIO_CODEC.get(out_ext, "aac")
        preset = s.effective_video_preset()

        # Offload a mapped codec when the user's preference allows it and a
        # live probe confirms it works. Unmapped codecs stay on CPU.
        nv, amf = _HW_EQUIV.get(vcodec, ("", ""))
        pref = s.encoder_pref
        use_nvenc = bool(
            nv and pref in ("auto", "nvenc") and hwaccel.nvenc_available(nv)
        )
        use_amf = bool(
            amf and pref in ("auto", "amf")
            and hwaccel.amf_available(amf) and not use_nvenc
        )
        crf = s.effective_video_crf()

        if use_nvenc:
            cmd += hw_encode_args(nv, crf) + _EVEN_SCALE_ARGS
        elif use_amf:
            cmd += hw_encode_args(amf, crf) + _EVEN_SCALE_ARGS
        elif vcodec in ("libx264", "libx265"):
            cmd += ["-c:v", vcodec, "-crf", str(crf), "-preset", preset]
            # RGB sources (GIF, ProRes 4444, screen recordings) would
            # otherwise encode as yuv444p, which common players can't decode.
            cmd += _EVEN_SCALE_ARGS
        elif vcodec == "libvpx-vp9":
            vp9_crf = s.video_crf if s.use_custom_quality else _WEBM_DEFAULT_VP9_CRF
            cmd += ["-c:v", vcodec, "-crf", str(vp9_crf), "-b:v", "0",
                    "-row-mt", "1", *_EVEN_SCALE_ARGS]
            if not s.use_custom_quality:
                # Default path: keep encode time sane and avoid the
                # near-lossless "best" deadline that bloats output.
                cmd += ["-deadline", "good", "-cpu-used", _WEBM_DEFAULT_CPU_USED]
        elif vcodec == "libaom-av1":
            cmd += ["-c:v", vcodec, "-crf", str(crf), "-b:v", "0",
                    *_EVEN_SCALE_ARGS]
        elif vcodec == "rawvideo":
            cmd += ["-c:v", vcodec, *_EVEN_SCALE_ARGS]
        else:
            # qscale encoders (mpeg4, wmv2, mpeg2video) ignore -crf; without
            # a quality flag they fall back to an uncontrolled default
            # bitrate. Map the CRF setting (0-51) onto qscale 2-31.
            qv = max(2, min(31, round(s.effective_video_crf() / 3)))
            cmd += ["-c:v", vcodec, "-q:v", str(qv), *_EVEN_SCALE_ARGS]
        if out_ext in _VIDEO_ONLY_EXTS:
            cmd += ["-an"]
        elif acodec == "libopus" and not s.use_custom_quality:
            cmd += _audio_encode_args(acodec, _WEBM_DEFAULT_OPUS_KBPS)
        else:
            cmd += _audio_encode_args(acodec, abr)
        if out_ext == ".mxf":
            # MXF requires 48 kHz audio; ffmpeg rejects the common 44.1 kHz input.
            cmd += ["-ar", "48000"]
        cmd += [str(self.output_path)]
        return cmd

    def _convert(self) -> None:
        cmd = self._build_cmd()
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            **_no_window_kwargs(),
        )
        total_seconds: float | None = None

        stderr = proc.stderr
        if stderr is None:
            proc.terminate()
            proc.wait()
            raise RuntimeError("ffmpeg did not provide a stderr stream")

        for line in stderr:
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

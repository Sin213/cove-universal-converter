"""Runtime detection of NVIDIA (NVENC) and AMD (AMF) hardware video encoders.

ffmpeg may be compiled with ``*_nvenc`` / ``*_amf`` encoders yet still fail at
runtime when the GPU, driver, or vendor runtime is absent. So detection is a
two-step probe: confirm the encoder is listed by ``-encoders``, then run a tiny
one-frame null test-encode and check the exit code. The verdict is cached per
encoder for the process lifetime so the modal quality dialog reads it instantly.

Everything degrades to CPU: any probe failure (missing binary, unsupported
encoder, driver error) returns False and never raises into a conversion job.
"""
from __future__ import annotations

import os
import subprocess
import threading

from cove_converter.binaries import FFMPEG, resolve
from cove_converter.engines.ffmpeg import (
    _EVEN_SCALE_ARGS,
    AMF_ENCODERS,
    NVENC_ENCODERS,
    _no_window_kwargs,
    hw_encode_args,
)

# Representative CRF for the test-encode. Any valid value works; the point is
# to exercise the vendor rate-control options, not a specific quality.
_PROBE_CRF = 23

_NVENC_LOCK = threading.Lock()
_AMF_LOCK = threading.Lock()
_nvenc_cache: dict[str, bool] = {}
_amf_cache: dict[str, bool] = {}


def _encoder_listed(encoder: str) -> bool:
    """True if ffmpeg reports ``encoder`` in its ``-encoders`` table."""
    try:
        proc = subprocess.run(
            [resolve(FFMPEG), "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            **_no_window_kwargs(),
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return encoder in (proc.stdout or "")


def _test_encode(encoder: str) -> bool:
    """Run a short null encode with the *production* options; True on exit 0.

    Uses the exact vendor option set ``_build_cmd`` emits (via
    ``hw_encode_args`` + ``_EVEN_SCALE_ARGS``) so a build/driver that exposes
    the encoder but rejects one of those options is correctly detected as
    unavailable and falls back to CPU.
    """
    devnull = "NUL" if os.name == "nt" else "/dev/null"
    encode_args = hw_encode_args(encoder, _PROBE_CRF) + _EVEN_SCALE_ARGS
    try:
        proc = subprocess.run(
            [
                resolve(FFMPEG), "-hide_banner", "-y",
                "-f", "lavfi", "-i", "color=c=black:s=64x64:d=0.3",
                *encode_args, "-f", "null", devnull,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            **_no_window_kwargs(),
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0


def _probe(encoder: str) -> bool:
    return _encoder_listed(encoder) and _test_encode(encoder)


def _cached_probe(cache: dict[str, bool], lock: threading.Lock, encoder: str) -> bool:
    """Return a cached verdict, running the probe OUTSIDE the lock on a miss.

    The lock only guards dict reads/writes, never the subprocess probe, so a
    slow or hanging probe on one thread can't block another (e.g. the UI thread
    reading the cache while the startup warm-cache thread is still probing). A
    concurrent double-probe is harmless: the result is idempotent and the first
    stored verdict wins via ``setdefault``.
    """
    with lock:
        cached = cache.get(encoder)
    if cached is not None:
        return cached
    result = _probe(encoder)
    with lock:
        return cache.setdefault(encoder, result)


def nvenc_available(encoder: str = "hevc_nvenc") -> bool:
    """Cached verdict for a specific NVENC encoder (probes on a cache miss)."""
    return _cached_probe(_nvenc_cache, _NVENC_LOCK, encoder)


def amf_available(encoder: str = "hevc_amf") -> bool:
    """Cached verdict for a specific AMF encoder (probes on a cache miss)."""
    return _cached_probe(_amf_cache, _AMF_LOCK, encoder)


def any_nvenc_available() -> bool:
    """True if any NVENC encoder used by a real output works (may probe)."""
    return any(nvenc_available(e) for e in NVENC_ENCODERS)


def any_amf_available() -> bool:
    """True if any AMF encoder used by a real output works (may probe)."""
    return any(amf_available(e) for e in AMF_ENCODERS)


def _cached_verdict(
    cache: dict[str, bool], lock: threading.Lock, *encoders: str
) -> bool | None:
    """Cache-only vendor verdict without ever running a probe.

    Returns True if some encoder is known-available, False only once every
    encoder has been probed and all failed, and None while any probe is still
    outstanding (unknown). Distinguishing None from False lets the UI grey out
    an as-yet-unknown vendor without discarding a saved preference for it.
    """
    with lock:
        vals = [cache.get(e) for e in encoders]
    if any(v is True for v in vals):
        return True
    if all(v is False for v in vals):
        return False
    return None


def nvenc_verdict() -> bool | None:
    """Cache-only tri-state verdict for NVENC (True / False / None-unknown)."""
    return _cached_verdict(_nvenc_cache, _NVENC_LOCK, *NVENC_ENCODERS)


def amf_verdict() -> bool | None:
    """Cache-only tri-state verdict for AMF (True / False / None-unknown)."""
    return _cached_verdict(_amf_cache, _AMF_LOCK, *AMF_ENCODERS)


def warm_cache() -> None:
    """Prime every used-encoder probe so a startup thread absorbs the latency.

    Warms each encoder explicitly (no short-circuit) so the conversion path
    never triggers a late first probe on the encoder it actually selects.
    """
    for encoder in NVENC_ENCODERS:
        nvenc_available(encoder)
    for encoder in AMF_ENCODERS:
        amf_available(encoder)

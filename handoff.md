# Handoff: NVENC + AMF hardware video encoding

## Goal
Port GPU (NVIDIA NVENC / AMD AMF) hardware video encoding to
cove-universal-converter. On machines with a supported GPU, H.264/H.265 video
conversions offload to the hardware encoder with automatic CPU fallback and a
user-facing Encoder choice. The converter is CRF-quality-only, so only the
quality (not bitrate/two-pass) half of the original cove-compressor feature
applies.

## Scope of change (staged files only)
- `cove_converter/engines/hwaccel.py` (new): runtime NVENC/AMF detection.
  Two-step probe (encoder listed in `-encoders`, then a one-frame null
  test-encode returns rc 0), cached per encoder behind locks. Every failure
  path returns False and never raises.
- `cove_converter/engines/ffmpeg.py`: `_HW_EQUIV` map (libx264->h264_*,
  libx265->hevc_*). New GPU branches in `_build_cmd`. NVENC:
  `-preset p5 -tune hq -rc vbr -cq <crf> -b:v 0`. AMF:
  `-quality balanced -usage transcoding -rc cqp -qp <crf>`. Both keep
  `-pix_fmt yuv420p` and the even-dimension scale filter. NVENC preferred on
  `auto` when both present; forcing an unavailable vendor falls through to CPU.
  VP9/mpeg4/wmv2/mpeg2video CPU paths unchanged (each branch now carries its
  own `-c:v`). hwaccel imported lazily inside `_build_cmd` to avoid a circular
  import.
- `cove_converter/settings.py`: `encoder_pref` field (auto/cpu/nvenc/amf),
  persisted in `save()`, read + validated in `load_settings()` (unknown value
  falls back to auto). `ENCODER_KEYS/OPTIONS/KEY_MAP/LABEL_MAP` for the UI.
- `cove_converter/ui/quality_dialog.py`: "Video encoder" combo, outside the
  customize-toggle group. Unavailable GPU vendors greyed via cached
  `hwaccel.any_*_available()`; a saved-but-now-unavailable pref resets to
  Automatic. `result_settings()` includes `encoder_pref`.
- `cove_converter/ui/main_window.py`: daemon thread on init calls
  `hwaccel.warm_cache()` so the modal dialog reads cached verdicts.
- `README.md`: documents the Encoder option.
- `tests/test_hwaccel.py` (new): detection graceful failure, arg matrix
  (nvenc/amf/auto/cpu prefs, VP9/AVI ignore GPU), CPU fallback when probes
  False, settings round-trip incl. unknown-value fallback.

## Verification
- `.venv/bin/python -m pytest tests/ -q` -> 198 passed, 20 subtests.
- Live probe on this sandbox: `any_nvenc_available()` / `any_amf_available()`
  both return False. Encoders ARE listed by ffmpeg, but the null test-encode
  fails (ffmpeg rc 234, "Could not open encoder" - no GPU passthrough in the
  sandbox). This is the correct, honest verdict: detection degrades to CPU
  cleanly, validating the safe-fallback path.

## Notes
- Fixed NVENC p5 / AMF balanced dial is a deliberate simplification vs the
  original per-preset ladder (converter presets are x264-specific).
- No push / no PR / no commit per instructions.

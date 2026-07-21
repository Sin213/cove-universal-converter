## What's Changed

GPU-accelerated video encoding.

### New
- Hardware video encoding for H.264 outputs (MP4, MKV, MOV, FLV, M4V, 3GP, TS) via NVIDIA NVENC and AMD AMF. On a supported GPU, video conversions offload to the hardware encoder for a large speed-up.
- New "Video encoder" quality setting: Automatic, CPU, NVIDIA (NVENC), or AMD (AMF). Automatic prefers NVENC when both GPUs are present.
- Unavailable GPU vendors are greyed out in the dialog. A forced-but-missing GPU always falls back to CPU and never fails the job.

### How it works
- Runtime GPU detection probes each encoder with a short null test-encode using the exact options the real conversion emits, so a driver or build that exposes an encoder but rejects an option is correctly treated as unavailable and falls back to CPU.
- Probes are cached and warmed on a background thread at startup, so the settings dialog never blocks the UI.
- VP9 and legacy codecs (mpeg4, wmv2, mpeg2video) stay CPU-only.
- Your existing quality (CRF) choice carries straight over to the GPU encoders.

### Thanks
- Thank you to Flametossed for the NVENC and AMF hardware-encoding work this port is based on.

Each release artifact has a matching `.sha256` file for verification.

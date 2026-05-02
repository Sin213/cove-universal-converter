**Cove Universal Converter** v2.0.2 — second pass on the WebM size fix from v2.0.1.

Still 100% offline, still privacy-first.

## Highlights

- **Default MP4 → WebM no longer inflates typical sources.** v2.0.1 cut the worst-case bloat down from ~10x to ~1.5x by switching the default off the near-lossless x264 CRF passthrough. v2.0.2 finishes the job by shipping a size-aware default rather than VP9's "balanced" CRF, which the smoke test still showed inflating a 20.7 MiB MP4 to 31.3 MiB. The new default produces:
  - typical web h.264 720p source (1.04 MiB) → **0.90 MiB WebM** (ratio **0.87**)
  - already-compact AV1-in-MP4 1080p source (20.7 MiB) → **25.05 MiB WebM** (ratio **1.21**, down from 1.51 in v2.0.1; a perfect-equivalence VP9 transcode of an AV1 source is intrinsically larger because VP9 is the less efficient codec — but the encoder no longer wastes bytes on top of that)
- **What changed in the FFmpeg command.** All defaults; custom-quality opt-in is untouched.
  - VP9 CRF: `32` → **`36`** (still well above visually lossy thresholds; pairs with `-b:v 0` for true CRF mode).
  - Encode tuning: added **`-deadline good -cpu-used 4`**. The libvpx default `deadline best, cpu-used 0` was producing larger output *and* taking ~2x longer. On the 20.7 MiB sample, encode time dropped from **130s → 70s**.
  - Opus audio: `128 kbps` → **`96 kbps`** (transparent for speech and most music; matches what every major WebM publisher ships).
- **Custom-quality sliders are still authoritative.** If you opted into custom quality, your CRF, preset, and audio-bitrate choices are passed through unchanged. The size-aware tuning only applies to the out-of-the-box default path.
- **New regression test** (`tests/test_mp4_to_webm_size.py`) generates a representative MP4 and asserts WebM output ≤ 1.25× input. CI fails loudly if a future change re-introduces the bloat.

## What's still imperfect

- **AV1 → VP9 will always inflate at equivalent visual quality.** AV1 is a more efficient codec than VP9 at low bitrates. If you transcode an AV1-encoded `.mp4` (common on newer phones, YouTube downloads, and screen recorders) to `.webm` with default settings, expect ~1.2× growth. Drop the WebM CRF in custom-quality mode if you need to push further; the limit is the codec, not the wrapper.
- **`.3gp` → `.ogg` and `.3gp` → `.opus`** still fail in the smoke matrix (libvorbis/libopus reject the AMR-NB 8 kHz mono input at the worker's audio bitrate). Pre-existing, unrelated to the WebM change. Tracked separately.

## Downloads

| Platform | File | Notes |
|---|---|---|
| Linux (any distro with `libfuse2`) | `Cove-Universal-Converter-2.0.2-x86_64.AppImage` | Single executable, `chmod +x` and run. |
| Debian / Ubuntu / Mint / Pop!_OS | `cove-universal-converter_2.0.2_amd64.deb` | Installs system-wide with a menu entry. |
| Windows 10 / 11 | `cove-universal-converter-2.0.2-Setup.exe` | Installer with Start Menu shortcut + uninstaller. |
| Windows 10 / 11 (no install) | `cove-universal-converter-2.0.2-Portable.exe` | Single file — run it from anywhere, no install. |

Each binary has a matching `.sha256` sidecar on the release page.

## Verifying downloads

```bash
sha256sum -c Cove-Universal-Converter-2.0.2-x86_64.AppImage.sha256
sha256sum -c cove-universal-converter_2.0.2_amd64.deb.sha256
```

On Windows (PowerShell):

```powershell
Get-FileHash .\cove-universal-converter-2.0.2-Setup.exe -Algorithm SHA256
```

…and compare against the contents of the matching `.sha256` file.

## Acknowledgements

Thanks again to **Duck** for re-running the conversion against `golden.mp4` and catching that v2.0.1 only got us halfway there.

## Notes

- Built and tested on Arch Linux and Windows 11 with Python 3.12 and PySide6 6.11.
- Windows `.exe` files are still **unsigned**; SmartScreen may warn on first launch — click **More info → Run anyway**.
- See the [README](https://github.com/Sin213/cove-universal-converter#readme) for full usage docs.

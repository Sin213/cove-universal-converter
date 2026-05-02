**Cove Universal Converter** v2.0.1 — point release fixing default WebM output bloat.

Still 100% offline, still privacy-first.

## Highlights

- **Sane WebM defaults (no more 10x bloat)** — converting an MP4 to WebM with default settings could produce a file 5–10x larger than the source (e.g. a 5.5 MB MP4 → 54 MB WebM). VP9's CRF scale runs hotter than x264's, and the previous near-lossless x264 default (CRF 17) was being passed straight through to `libvpx-vp9`, where it asked the encoder to preserve every macroblock detail of the source. Default WebM output now uses:
  - `libvpx-vp9 -crf 32 -b:v 0` — VP9's recommended balanced quality.
  - `libopus -b:a 128k` — Opus is transparent at this bitrate; the old 320 kbps default just added bytes for no audible gain.
  - `-row-mt 1` for multithreaded VP9 encoding (substantially faster on multi-core hosts).
  - `-pix_fmt yuv420p` for broad player/codec compatibility (also unblocks `.3gp` → `.webm`, which previously failed outright).
- **Custom-quality sliders are unchanged** — if you opted into custom quality in the settings dialog, your chosen CRF and audio bitrate are still applied verbatim. Only the default (out-of-the-box) WebM path was tuned.

## Downloads

| Platform | File | Notes |
|---|---|---|
| Linux (any distro with `libfuse2`) | `Cove-Universal-Converter-2.0.1-x86_64.AppImage` | Single executable, `chmod +x` and run. |
| Debian / Ubuntu / Mint / Pop!_OS | `cove-universal-converter_2.0.1_amd64.deb` | Installs system-wide with a menu entry. |
| Windows 10 / 11 | `cove-universal-converter-2.0.1-Setup.exe` | Installer with Start Menu shortcut + uninstaller. |
| Windows 10 / 11 (no install) | `cove-universal-converter-2.0.1-Portable.exe` | Single file — run it from anywhere, no install. |

Each binary has a matching `.sha256` sidecar on the release page.

## Verifying downloads

```bash
sha256sum -c Cove-Universal-Converter-2.0.1-x86_64.AppImage.sha256
sha256sum -c cove-universal-converter_2.0.1_amd64.deb.sha256
```

On Windows (PowerShell):

```powershell
Get-FileHash .\cove-universal-converter-2.0.1-Setup.exe -Algorithm SHA256
```

…and compare against the contents of the matching `.sha256` file.

## Acknowledgements

Thanks to **Duck** for catching the WebM size-inflation regression and reporting it.

## Notes

- Built and tested on Arch Linux and Windows 11 with Python 3.12 and PySide6 6.11.
- Windows `.exe` files are still **unsigned**; SmartScreen may warn on first launch — click **More info → Run anyway**.
- See the [README](https://github.com/Sin213/cove-universal-converter#readme) for full usage docs.

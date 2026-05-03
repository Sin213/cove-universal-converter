**Cove Universal Converter** v2.0.3 — image-to-PDF, scanned-PDF enhancement, and hardened cross-filesystem finalization.

Still 100% offline, still privacy-first.

## Highlights

- **Image → PDF.** New conversion route turns `.png`, `.jpg`, `.jpeg`, and `.webp` inputs into a one-page PDF that preserves the source pixel dimensions exactly. No server round-trip, no resampling, no metadata stripped from the image.
- **Enhance scanned PDF (opt-in).** A conservative, default-off pipeline tuned for faded office scans: page rasterization at 200 DPI, mild auto-contrast, background whitening above 230, gentle text-contrast lift, unsharp mask, JPEG repack at quality 88. Tuned to preserve mid-greys and thin diagram lines rather than aggressively destroying them — turn it on per-conversion when you actually have a faded scan, not by default.
- **Hardened temp-output finalization.** The worker's atomic-write path is significantly more robust on external mounts (NTFS-3G, exFAT under `/run/media/...`, USB drives, network shares):
  - **Writability probe.** Sibling temp files are now actively probed with `open(..., "r+b")` after creation. If the mount silently returns a read-only file (mount-enforced `fmask`/`umask` ignoring `os.chmod`), the worker falls back to a system-temp output instead of failing mid-conversion with `PermissionError` from PIL/ffmpeg/pandoc.
  - **EXDEV cross-filesystem staging.** When the system-temp fallback is used and the final destination lives on a different filesystem (`os.replace` returns `EXDEV`), the worker now stages into a hidden sibling of the destination via `mkstemp`, copies through the **mkstemp file descriptor** (not by reopening the staging path), `flush` + `fsync`, then `os.replace` for an atomic intra-filesystem swap. Reopening the staging path for write would have re-tripped the original mount failure mode — this fix closes that hole.
  - **Pre-existing destination is never partially overwritten.** A mid-copy or mid-replace failure on the EXDEV path leaves any existing `final` file byte-for-byte unchanged. No more risk of data loss when conversion fails halfway through writing over an old output.
- **Read-only source images convert cleanly.** Regression covered: a `0o444` `.jpeg` or `.png` from an external mount no longer poisons the worker's `0o600` temp file with the source's mode before save.

## Tests

- `tests/test_pdf_enhance.py` — image-to-PDF + scanned-PDF enhancement coverage (402 LOC).
- `tests/test_image_to_pdf_readonly.py` — read-only source image regression.
- `tests/test_worker_temp_writability.py` — sibling-temp writability fallback, EXDEV finalization (success path, copy-failure leaves final untouched, **and a dedicated regression proving the staging path is never reopened for write**).

## Downloads

| Platform | File | Notes |
|---|---|---|
| Linux (any distro with `libfuse2`) | `Cove-Universal-Converter-2.0.3-x86_64.AppImage` | Single executable, `chmod +x` and run. |
| Debian / Ubuntu / Mint / Pop!_OS | `cove-universal-converter_2.0.3_amd64.deb` | Installs system-wide with a menu entry. |
| Windows 10 / 11 | `cove-universal-converter-2.0.3-Setup.exe` | Installer with Start Menu shortcut + uninstaller. |
| Windows 10 / 11 (no install) | `cove-universal-converter-2.0.3-Portable.exe` | Single file — run it from anywhere, no install. |

Each binary ships with a matching `.sha256` sidecar on the release page.

## Verifying downloads

```bash
sha256sum -c Cove-Universal-Converter-2.0.3-x86_64.AppImage.sha256
sha256sum -c cove-universal-converter_2.0.3_amd64.deb.sha256
```

On Windows (PowerShell):

```powershell
Get-FileHash .\cove-universal-converter-2.0.3-Setup.exe -Algorithm SHA256
```

…and compare against the contents of the matching `.sha256` file.

## Notes

- Built and tested on Arch Linux and Windows 11 with Python 3.12 and PySide6 6.11.
- Windows `.exe` files are still **unsigned**; SmartScreen may warn on first launch — click **More info → Run anyway**.
- See the [README](https://github.com/Sin213/cove-universal-converter#readme) for full usage docs.

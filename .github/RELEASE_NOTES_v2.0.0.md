**Cove Universal Converter** v2.0.0 — broader format coverage, safer file handling, and signed checksums for every published binary.

Still 100% offline, still privacy-first.

## Highlights

- **New conversion engines** — alongside the existing Video / Audio / Image / Document workers, this release adds:
  - **Subtitles** — SubRip (`.srt`) ↔ WebVTT (`.vtt`) text-level conversion, no third-party dep.
  - **Data formats** — JSON ↔ YAML round-trip via `yaml.safe_load` / `yaml.safe_dump`.
  - **Spreadsheets** — CSV ↔ XLSX via `openpyxl` (active sheet, plain-data round-trip).
  - **Archives** — ZIP ↔ TAR ↔ TAR.GZ (`.tgz`) extract-and-repack.
- **Safer archive handling** — bounded extraction caps the worst case for malformed or malicious archives:
  - Per-archive member count, total uncompressed bytes, and per-entry size limits.
  - Compression-ratio sanity check to refuse obvious zip / tar bombs.
  - Path-traversal and absolute-path entries are rejected up front.
  - Symlink / hardlink targets must resolve back inside the extraction root.
  - Block / character / FIFO / socket members are refused outright.
  - Tar extraction uses `filter='data'` on Python 3.12+ and falls back to a manual safe-extract on 3.11.
- **Atomic output writes** — every worker now writes to a unique sibling temp file (`tempfile.mkstemp`, O_CREAT | O_EXCL) and `os.replace`s into place at the end of the run. A cancelled or failed conversion never leaves a half-written file at the destination, and a successful one swaps in the result atomically. POSIX file modes are restored to match what a normal create would have produced.
- **Release-asset checksums** — every shipped binary now publishes a matching `<asset>.sha256` sidecar:
  - `Cove-Universal-Converter-2.0.0-x86_64.AppImage.sha256`
  - `cove-universal-converter_2.0.0_amd64.deb.sha256`
  - Standard `sha256sum` output format. Verify with `sha256sum -c <file>.sha256`.
- **Packaging / release fixes**:
  - Linux CI installs `libcairo2-dev` so the `pycairo` wheel source build succeeds.
  - The release workflow uploads sidecar `.sha256` files alongside the AppImage and `.deb`, and attaches them to the GitHub Release.

## Downloads

| Platform | File | Notes |
|---|---|---|
| Linux (any distro with `libfuse2`) | `Cove-Universal-Converter-2.0.0-x86_64.AppImage` | Single executable, `chmod +x` and run. |
| Debian / Ubuntu / Mint / Pop!_OS | `cove-universal-converter_2.0.0_amd64.deb` | Installs system-wide with a menu entry. |
| Windows 10 / 11 | `cove-universal-converter-2.0.0-Setup.exe` | Installer with Start Menu shortcut + uninstaller. |
| Windows 10 / 11 (no install) | `cove-universal-converter-2.0.0-Portable.exe` | Single file — run it from anywhere, no install. |

Each binary has a matching `.sha256` sidecar on the release page.

## Verifying downloads

```bash
sha256sum -c Cove-Universal-Converter-2.0.0-x86_64.AppImage.sha256
sha256sum -c cove-universal-converter_2.0.0_amd64.deb.sha256
```

On Windows (PowerShell):

```powershell
Get-FileHash .\cove-universal-converter-2.0.0-Setup.exe -Algorithm SHA256
```

…and compare against the contents of the matching `.sha256` file.

## Notes

- Built and tested on Arch Linux and Windows 11 with Python 3.12 and PySide6 6.11.
- Windows `.exe` files are still **unsigned**; SmartScreen may warn on first launch — click **More info → Run anyway**.
- See the [README](https://github.com/Sin213/cove-universal-converter#readme) for full usage docs.

**Cove Universal Converter** v2.1.1 — fixes document and media conversions failing on Windows when filenames or content contain non-ASCII characters.

Still 100% offline, still privacy-first.

## Fixed

- **Windows: EPUB/DOCX/MD/HTML → PDF conversions fail on non-ASCII content.** On Windows, Python's `subprocess` defaults to the system locale encoding (typically `cp1252`) when reading process output as text. Pandoc outputs UTF-8, so any non-ASCII characters in the source file — em-dashes, smart quotes, accented names, CJK text — caused a `UnicodeDecodeError` and a silent "Failed" status in the UI. All subprocess calls in the Pandoc, PDF, and FFmpeg engines now explicitly request UTF-8 decoding.

## Downloads

| Platform | File | Notes |
|---|---|---|
| Linux (any distro with `libfuse2`) | `Cove-Universal-Converter-2.1.1-x86_64.AppImage` | Single executable, `chmod +x` and run. |
| Debian / Ubuntu / Mint / Pop!_OS | `cove-universal-converter_2.1.1_amd64.deb` | Installs system-wide with a menu entry. |
| Windows 10 / 11 | `cove-universal-converter-2.1.1-Setup.exe` | Installer with Start Menu shortcut + uninstaller. |
| Windows 10 / 11 (no install) | `cove-universal-converter-2.1.1-Portable.exe` | Single file — run it from anywhere, no install. |

Each binary ships with a matching `.sha256` sidecar on the release page.

## Verifying downloads

```bash
sha256sum -c Cove-Universal-Converter-2.1.1-x86_64.AppImage.sha256
sha256sum -c cove-universal-converter_2.1.1_amd64.deb.sha256
```

On Windows (PowerShell):

```powershell
Get-FileHash .\cove-universal-converter-2.1.1-Setup.exe -Algorithm SHA256
```

...and compare against the contents of the matching `.sha256` file.

## Notes

- Built and tested on Arch Linux and Windows 11 with Python 3.12 and PySide6 6.11.
- Windows `.exe` files are still **unsigned**; SmartScreen may warn on first launch — click **More info → Run anyway**.
- See the [README](https://github.com/Sin213/cove-universal-converter#readme) for full usage docs.

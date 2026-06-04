**Cove Universal Converter** v2.1.2 — fixes document and media conversions failing on Windows.

Still 100% offline, still privacy-first.

## Fixed

- **Windows: EPUB/DOCX/MD/HTML → PDF conversions crash on non-ASCII content.** Python's `subprocess` defaults to the system locale encoding (typically `cp1252`) on Windows. Pandoc outputs UTF-8, so any non-ASCII characters in the source — em-dashes, smart quotes, accented names, CJK text — caused a `UnicodeDecodeError` and a "Failed" status. All subprocess calls now explicitly request UTF-8 decoding.

- **Windows: PDF rendering fails with `No module named 'reportlab.graphics.barcode.code128'`.** The Windows build script (`build.ps1`) only imported the top-level `reportlab` and `xhtml2pdf` packages into the frozen executable, missing critical submodules that xhtml2pdf needs at runtime. The build now uses `--collect-all` for `reportlab`, `xhtml2pdf`, `html5lib`, and `svglib` — matching what the Linux build already did.

## Downloads

| Platform | File | Notes |
|---|---|---|
| Linux (any distro with `libfuse2`) | `Cove-Universal-Converter-2.1.2-x86_64.AppImage` | Single executable, `chmod +x` and run. |
| Debian / Ubuntu / Mint / Pop!_OS | `cove-universal-converter_2.1.2_amd64.deb` | Installs system-wide with a menu entry. |
| Windows 10 / 11 | `cove-universal-converter-2.1.2-Setup.exe` | Installer with Start Menu shortcut + uninstaller. |
| Windows 10 / 11 (no install) | `cove-universal-converter-2.1.2-Portable.exe` | Single file — run it from anywhere, no install. |

Each binary ships with a matching `.sha256` sidecar on the release page.

## Verifying downloads

```bash
sha256sum -c Cove-Universal-Converter-2.1.2-x86_64.AppImage.sha256
sha256sum -c cove-universal-converter_2.1.2_amd64.deb.sha256
```

On Windows (PowerShell):

```powershell
Get-FileHash .\cove-universal-converter-2.1.2-Setup.exe -Algorithm SHA256
```

...and compare against the contents of the matching `.sha256` file.

## Notes

- Built and tested on Arch Linux and Windows 11 with Python 3.12 and PySide6 6.11.
- Windows `.exe` files are still **unsigned**; SmartScreen may warn on first launch — click **More info → Run anyway**.
- See the [README](https://github.com/Sin213/cove-universal-converter#readme) for full usage docs.

**Cove Universal Converter** v2.1.0 — new format: PDF → CBZ (comic book archive).

Still 100% offline, still privacy-first.

## New

- **PDF → CBZ conversion.** Drop a PDF and select `.cbz` as the target — every page is rendered to PNG at 150 DPI and packed into a CBZ archive. Works with any comic reader (YACReader, MComix, Panels, CDisplayEx, etc.) and is great for archiving scanned documents as page-image bundles.
- **Comics format category** added to the Supported Formats dialog.

## Downloads

| Platform | File | Notes |
|---|---|---|
| Linux (any distro with `libfuse2`) | `Cove-Universal-Converter-2.1.0-x86_64.AppImage` | Single executable, `chmod +x` and run. |
| Debian / Ubuntu / Mint / Pop!_OS | `cove-universal-converter_2.1.0_amd64.deb` | Installs system-wide with a menu entry. |
| Windows 10 / 11 | `cove-universal-converter-2.1.0-Setup.exe` | Installer with Start Menu shortcut + uninstaller. |
| Windows 10 / 11 (no install) | `cove-universal-converter-2.1.0-Portable.exe` | Single file — run it from anywhere, no install. |

Each binary ships with a matching `.sha256` sidecar on the release page.

## Verifying downloads

```bash
sha256sum -c Cove-Universal-Converter-2.1.0-x86_64.AppImage.sha256
sha256sum -c cove-universal-converter_2.1.0_amd64.deb.sha256
```

On Windows (PowerShell):

```powershell
Get-FileHash .\cove-universal-converter-2.1.0-Setup.exe -Algorithm SHA256
```

…and compare against the contents of the matching `.sha256` file.

## Notes

- Built and tested on Arch Linux and Windows 11 with Python 3.12 and PySide6 6.11.
- Windows `.exe` files are still **unsigned**; SmartScreen may warn on first launch — click **More info → Run anyway**.
- See the [README](https://github.com/Sin213/cove-universal-converter#readme) for full usage docs.

## Thanks

Thanks to **Whooshy** for the suggestion.

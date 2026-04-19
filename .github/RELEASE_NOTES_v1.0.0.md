First public release of **Cove Universal Converter** — an offline, privacy-first desktop app that batch-converts files between **40+ formats** across video, audio, images, and documents. One app replaces half a dozen online converters. Nothing leaves your machine.

## Highlights

- **Drag, drop, click, or drop a folder** — the whole window accepts files, folders recurse automatically, and the central zone opens a file picker on click.
- **40+ formats** across four categories. Click the ⓘ button inside the drop zone to see the full list grouped by Video / Audio / Images / Documents.
- **Near-lossless by default** — videos encode at x264 CRF 17 (visually indistinguishable from source), audio at 320 kbps, images at 95% JPEG/WebP. No sneaky compression.
- **Opt-in quality controls** — tick "Customize quality settings" in the ⚙ dialog to trade quality for smaller files (CRF slider, encoder preset, audio bitrate, JPEG/WebP sliders).
- **Save to any folder** — leave blank to write next to the source, or pick a global output directory.
- **Safe by design** — before a batch starts, any output files that already exist trigger a confirmation dialog with Overwrite / Rename duplicates / Cancel.
- **Right-click a row** to remove it (or press Delete). Batch queue runs 3 conversions in parallel by default (configurable).
- **PDF support** — convert to and from PDF via `pypdf` (input) and `xhtml2pdf` (output). Pure Python, no LaTeX required.
- **Real-time progress** parsed from ffmpeg's own output, with row tints for processing / done / failed states.

## Downloads

| Platform | File | Notes |
|---|---|---|
| Linux (any distro with `libfuse2`) | `Cove-Universal-Converter-1.0.0-x86_64.AppImage` | Single executable, just `chmod +x` and run. |
| Debian / Ubuntu / Mint / Pop!_OS | `cove-universal-converter_1.0.0_amd64.deb` | Installs system-wide with a menu entry. |
| Windows 10 / 11 | `cove-universal-converter-1.0.0-Setup.exe` | Installer with Start Menu shortcut + uninstaller. |
| Windows 10 / 11 (no install) | `cove-universal-converter-1.0.0-Portable.exe` | Single file — run it from anywhere, no install. |

### Linux — AppImage

```bash
chmod +x Cove-Universal-Converter-1.0.0-x86_64.AppImage
./Cove-Universal-Converter-1.0.0-x86_64.AppImage
```

If you hit a FUSE error, install `fuse2`:
- Arch: `sudo pacman -S fuse2`
- Debian / Ubuntu: `sudo apt install libfuse2`
- Fedora: `sudo dnf install fuse`

### Linux — .deb

```bash
sudo apt install ./cove-universal-converter_1.0.0_amd64.deb
```

You'll then find **Cove Universal Converter** in your applications menu.

### Windows — Setup.exe

Double-click, follow the wizard, pick whether you want a desktop shortcut. Uninstall anytime from Settings → Apps.

### Windows — Portable.exe

No installation. Double-click to run. Put it on a USB stick if you want.

> Both Windows .exe files are **unsigned**, so SmartScreen may warn you on first launch — click **More info → Run anyway**.

## What's bundled

Both the AppImage / .deb and the Windows builds ship with:
- **ffmpeg** — for all audio and video conversions
- **pandoc** — for document conversions (docx, epub, md, html, etc.)
- **Pillow** + **pillow-heif** — for images, including HEIC / HEIF
- **pypdf** + **xhtml2pdf** — for PDF input and output

You don't need to install anything else. Fully offline.

## Supported formats

| Category  | Formats                                                                            |
| --------- | ---------------------------------------------------------------------------------- |
| Video     | mp4, mkv, webm, mov, avi, flv, wmv, m4v, mpg, mpeg, 3gp, ts, gif                   |
| Audio     | mp3, wav, flac, ogg, m4a, aac, opus, wma, aiff                                     |
| Images    | png, jpg, jpeg, webp, bmp, tiff, tif, ico, heic, heif                              |
| Documents | pdf, docx, odt, rtf, epub, md, html, htm, txt, tex                                 |

## Notes

- All four artifacts are ~120–200 MB each because they bundle the Qt runtime, Python, ffmpeg, and pandoc. The Python source is under 1 MB.
- Built and tested on Arch Linux and Windows 11 with Python 3.12 and PySide6 6.11.
- The same codebase powers both the Linux and Windows builds — one repo, two native applications.

See the [README](https://github.com/Sin213/cove-universal-converter#readme) for full usage docs.

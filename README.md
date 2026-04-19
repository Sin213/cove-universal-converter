# Cove Universal Converter

An offline, privacy-first batch file converter. Drop in video, audio, images,
or documents and convert between 40+ formats — no files leave your machine.

One codebase, one repository, two native builds: a Windows `.exe` and a Linux
binary. Everything below assumes you're starting from a fresh clone:

```
git clone <your-repo-url>
cd cove-universal-converter
```

---

## What it can do

| Category  | Supported extensions                                                               |
| --------- | ---------------------------------------------------------------------------------- |
| Video     | mp4, mkv, webm, mov, avi, flv, wmv, m4v, mpg, mpeg, 3gp, ts, gif                   |
| Audio     | mp3, wav, flac, ogg, m4a, aac, opus, wma, aiff                                     |
| Images    | png, jpg, jpeg, webp, bmp, tiff, tif, ico, heic, heif                              |
| Documents | pdf, docx, odt, rtf, epub, md, html, htm, txt, tex                                 |

Features:

- Drag-and-drop, click-to-browse, or drop a whole folder (recurses automatically).
- Per-file target dropdown, or use the "Save to" field to batch-write to one folder.
- Near-lossless quality by default (CRF 17, preset slow, 320 kbps audio, 95%
  JPEG/WebP). An opt-in "Customize quality settings" checkbox exposes sliders
  if you'd rather trade quality for smaller files.
- Real-time progress bars parsed from FFmpeg's output.
- Overwrite confirmation with optional auto-rename to `file (1).ext`, `file (2).ext`, …
- Right-click a row (or press Delete) to remove it from the queue.

---

## Running from source (Linux)

You need Python 3.11 or newer. On Arch:

```bash
sudo pacman -S python ffmpeg pandoc
```

Set up a virtual environment and install the Python dependencies:

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Launch the app:

```bash
.venv/bin/python -m cove_converter
```

That's it. FFmpeg and Pandoc are resolved from your system `PATH` when the app
isn't running as a packaged build.

---

## Running from source (Windows)

You need Python 3.11+ from [python.org](https://www.python.org/downloads/).
During installation, tick **"Add Python to PATH"**.

Install FFmpeg and Pandoc:

- **FFmpeg**: download a release from [gyan.dev](https://www.gyan.dev/ffmpeg/builds/),
  unzip it, and add the `bin\` folder to your `PATH`, **or** drop `ffmpeg.exe`
  into `bin\win\` inside this repo.
- **Pandoc**: grab the installer from [pandoc.org](https://pandoc.org/installing.html)
  and run it — the installer adds it to `PATH` automatically.

Then in PowerShell from the repo root:

```powershell
py -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m cove_converter
```

---

## Building release artifacts

PyInstaller can't cross-compile, so Linux artifacts have to be built on Linux
and Windows artifacts on Windows. Each platform has its own build script that
downloads ffmpeg / pandoc automatically and produces the final files.

### Linux — AppImage + .deb

```bash
bash scripts/build-release.sh
# Output in release/:
#   Cove-Universal-Converter-1.0.0-x86_64.AppImage
#   cove-universal-converter_1.0.0_amd64.deb
```

Override the version with `VERSION=1.2.0 bash scripts/build-release.sh`.

### Windows — Setup.exe + Portable.exe

Requires [Inno Setup 6](https://jrsoftware.org/isdl.php) to be installed
(bundled on GitHub Actions' `windows-latest`).

```powershell
.\build.ps1 -Version 1.0.0
# Output in release\:
#   cove-universal-converter-1.0.0-Setup.exe
#   cove-universal-converter-1.0.0-Portable.exe
```

### Automated release via GitHub Actions

Push a tag matching `v*` (e.g. `v1.0.0`) and
`.github/workflows/release.yml` runs the matrix:

- `build-linux` produces the AppImage + .deb on `ubuntu-latest`.
- `build-windows` produces Setup.exe + Portable.exe on `windows-latest`.

Both jobs attach their artifacts to the GitHub Release created for the tag,
using the body from `.github/RELEASE_NOTES_v<version>.md`.

---

## Project layout

```
cove-universal-converter/
├── cove_converter/
│   ├── __main__.py          # entry point (python -m cove_converter)
│   ├── binaries.py          # resolves ffmpeg/pandoc per-OS
│   ├── routing.py           # SUPPORTED_FORMATS table
│   ├── settings.py          # ConversionSettings dataclass
│   ├── engines/             # one worker per backend
│   │   ├── base.py          # BaseConverterWorker(QThread)
│   │   ├── ffmpeg.py        # video + audio
│   │   ├── pillow.py        # images (+ pillow-heif for HEIC)
│   │   ├── pandoc.py        # document formats
│   │   └── pdf.py           # any conversion touching .pdf
│   └── ui/                  # PySide6 widgets and dialogs
├── bin/
│   ├── linux/               # drop ffmpeg + pandoc here for local Linux builds
│   └── win/                 # drop ffmpeg.exe + pandoc.exe here for Windows
├── cove_converter.spec      # PyInstaller spec (branches on sys.platform)
├── .github/workflows/       # cross-platform CI
├── requirements.txt
└── pyproject.toml
```

---

## Troubleshooting

**"Could not find ffmpeg" on launch**
System has neither a PATH install nor a bundled binary. Install ffmpeg via
your package manager, or drop the binary into `bin/linux/` or `bin\win\`.

**HEIC files won't open**
Make sure `pillow-heif` was installed (`pip install -r requirements.txt`).
Some ancient HEIC files from older iPhones use HEVC Range Extensions and
still fail — convert them with another tool first.

**PDF output looks plain**
We render PDFs via xhtml2pdf (pure Python, no LaTeX dependency). That trades
some typographical polish for a zero-friction cross-platform install. If you
want LaTeX-quality PDFs, install a TeX distribution and switch the PDF engine.

**Windows console window flashes during conversion**
Shouldn't happen — we pass `CREATE_NO_WINDOW` to every subprocess. If you see
one, please open an issue with your Python and PySide6 versions.

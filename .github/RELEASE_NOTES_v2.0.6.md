**Cove Universal Converter** v2.0.6 — patch release: fix EPUB → PDF conversions failing silently and add an in-app conversion log panel.

Still 100% offline, still privacy-first.

## Fix

- **EPUB → PDF (and other Pandoc-routed PDF targets) no longer fail with a bare "Failed".** On certain Windows builds and frozen-exe configurations, Pandoc's stdout was being captured as `None`, which then tripped a raw `TypeError` deep inside `_strip_inline_css` — the UI rendered that as just `Failed` with no actionable detail. v2.0.6 hardens the Pandoc → HTML path:
  - `_pandoc_to_html` now passes `-o -` explicitly so Pandoc is forced to emit the rendered HTML to stdout, and validates the captured output is non-empty before returning.
  - `_strip_inline_css` defensively rejects a `None` HTML payload with a user-readable `RuntimeError` ("Pandoc produced no HTML output for PDF rendering") instead of crashing on `re.sub`.
  - Removed an unused `tempfile.NamedTemporaryFile` stub from the EPUB branch — Pandoc reads the real input directly.

## New

- **Conversion log panel.** A collapsible bottom panel surfaces per-file failure details right inside the app. When a row enters a Failed state, the worker's full traceback is captured and routed into the log view so users can see *why* a conversion failed without digging through terminal logs or rotated log files. The panel themes with the rest of the UI (monospace, dim text, click-to-expand header, clear button).
- **Failed signal carries a traceback.** The shared `BaseConverterWorker.failed` signal now emits `(short_message, full_traceback)` so the UI can show a one-line status *and* the underlying detail.
- **Per-row `error_log` field.** `FileRow` carries the captured failure log, so the log panel can render it on-demand instead of holding it in transient widget state.

## Tests

- `tests/test_pdf_pandoc_html.py` — covers the Pandoc → HTML contract: `-o -` is passed, empty/None stdout raises a readable `RuntimeError`, and `_strip_inline_css` rejects `None` defensively.
- `tests/test_failure_log_capture.py` — verifies the `failed` signal emits `(message, traceback)` and that `FileRow.error_log` is populated on failure.
- `tests/test_stale_log_clearing.py` — regression cover for the log panel: starting a new conversion clears stale logs from the previous run, the clear button works, and successful rows don't pollute the panel.

## Downloads

| Platform | File | Notes |
|---|---|---|
| Linux (any distro with `libfuse2`) | `Cove-Universal-Converter-2.0.6-x86_64.AppImage` | Single executable, `chmod +x` and run. |
| Debian / Ubuntu / Mint / Pop!_OS | `cove-universal-converter_2.0.6_amd64.deb` | Installs system-wide with a menu entry. |
| Windows 10 / 11 | `cove-universal-converter-2.0.6-Setup.exe` | Installer with Start Menu shortcut + uninstaller. |
| Windows 10 / 11 (no install) | `cove-universal-converter-2.0.6-Portable.exe` | Single file — run it from anywhere, no install. |

Each binary ships with a matching `.sha256` sidecar on the release page.

## Verifying downloads

```bash
sha256sum -c Cove-Universal-Converter-2.0.6-x86_64.AppImage.sha256
sha256sum -c cove-universal-converter_2.0.6_amd64.deb.sha256
```

On Windows (PowerShell):

```powershell
Get-FileHash .\cove-universal-converter-2.0.6-Setup.exe -Algorithm SHA256
```

…and compare against the contents of the matching `.sha256` file.

## Notes

- Built and tested on Arch Linux and Windows 11 with Python 3.12 and PySide6 6.11.
- Windows `.exe` files are still **unsigned**; SmartScreen may warn on first launch — click **More info → Run anyway**.
- See the [README](https://github.com/Sin213/cove-universal-converter#readme) for full usage docs.

## Thanks

Thanks to **Nikoto** for pointing out the bug.

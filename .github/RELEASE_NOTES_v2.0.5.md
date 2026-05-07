**Cove Universal Converter** v2.0.5 — patch release: fix batch JavaScript-PDF conversion crash.

Still 100% offline, still privacy-first.

## Fix

- **Batch conversion of JavaScript / smart PDFs no longer crashes.** v2.0.4's smart-PDF flatten path drove pypdfium2 from each `PdfWorker` thread independently. With the default batch concurrency of 3, multiple worker threads called PDFium's native API at the same time — pypdfium2 releases the GIL during native calls, so they really did execute in parallel. PDFium's process-global state is not thread-safe, which surfaced two ways:
  - Visible: `Failed to load page` / `Data format error` raised mid-flatten, every JS-PDF in the batch failing.
  - Worse: intermittent native crashes that bypassed Python's exception handling and took the whole process down, leaving empty `.cove-part-*.pdf` temp files behind in the destination folder (the worker died before its cleanup ran).

  v2.0.5 introduces a module-level lock around the entire `flatten_pdf` body so concurrent batch workers cannot race PDFium. Single-file conversions hit the lock once with no contention — no behavior change. The fix is contained to the JS-PDF flatten path; the byte-copy fast path, scan-enhance, image-to-PDF, and PDF→text routes are untouched.

## Tests

- `tests/test_pdf_flatten.py` adds **2 regression tests**:
  - `test_flatten_concurrent_batch_does_not_race_pdfium` — runs `flatten_pdf` from four threads on JS-marker PDFs simultaneously and asserts all four succeed. Reliably reproduced the original crash before the fix and reliably passes after.
  - `test_flatten_failure_in_one_thread_does_not_break_others` — proves a single bad PDF in a concurrent run raises cleanly in its own thread without corrupting PDFium state for the surviving threads.

Full suite: **170 passed**, 20 subtests passed.

## Downloads

| Platform | File | Notes |
|---|---|---|
| Linux (any distro with `libfuse2`) | `Cove-Universal-Converter-2.0.5-x86_64.AppImage` | Single executable, `chmod +x` and run. |
| Debian / Ubuntu / Mint / Pop!_OS | `cove-universal-converter_2.0.5_amd64.deb` | Installs system-wide with a menu entry. |
| Windows 10 / 11 | `cove-universal-converter-2.0.5-Setup.exe` | Installer with Start Menu shortcut + uninstaller. |
| Windows 10 / 11 (no install) | `cove-universal-converter-2.0.5-Portable.exe` | Single file — run it from anywhere, no install. |

Each binary ships with a matching `.sha256` sidecar on the release page.

## Verifying downloads

```bash
sha256sum -c Cove-Universal-Converter-2.0.5-x86_64.AppImage.sha256
sha256sum -c cove-universal-converter_2.0.5_amd64.deb.sha256
```

On Windows (PowerShell):

```powershell
Get-FileHash .\cove-universal-converter-2.0.5-Setup.exe -Algorithm SHA256
```

…and compare against the contents of the matching `.sha256` file.

## Notes

- Built and tested on Arch Linux and Windows 11 with Python 3.12 and PySide6 6.11.
- Windows `.exe` files are still **unsigned**; SmartScreen may warn on first launch — click **More info → Run anyway**.
- See the [README](https://github.com/Sin213/cove-universal-converter#readme) for full usage docs.

## Thanks

Thanks to **Drago** for pointing out the batch JS-PDF crash.

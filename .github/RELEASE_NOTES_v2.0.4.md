**Cove Universal Converter** v2.0.4 — Smart-PDF flattening: turn JavaScript / dynamic / form PDFs into static rendered PDFs.

Still 100% offline, still privacy-first.

## Highlights

- **Smart-PDF → static-PDF flattening.** PDFs with `/JavaScript` or `/JS` action dictionaries (filled AcroForm character sheets, dynamic legal forms, calculator-style PDFs) used to render with blank or partial pages through Cove's regular PDF pipeline because the JS-driven content was never executed. v2.0.4 adds a real per-page rasteriser:
  - Detection is a bounded-memory streaming byte scan over the whole file (1 MiB chunks with marker-length carry-over) — markers in indirect objects or compressed object streams in the body of the file are detected, not just those in the catalog.
  - Each page is rendered through PDFium (via `pypdfium2` — already a project dependency, no new third-party packages) at 250 DPI in full RGB. The bitmaps are assembled into a single multi-page PDF via PIL's `save_all` with the original page count, original page dimensions, and the visible content baked in.
  - **`PdfDocument.init_forms()` is bootstrapped before any page handle is taken**, per pypdfium2's documented contract — without this, `page.render(may_draw_forms=True)` silently skips form widgets, decorative form-layer graphics, and stored AcroForm field values. XFA loader warnings are captured via `warnings.catch_warnings(record=True)` and routed to the dedicated logger at INFO; AcroForm rendering keeps working even when XFA fails.
  - **Output validation** runs unconditionally before flatten returns: file exists, size ≥ 4 KiB × page count, valid PDF, page count equals input. On any validation failure, the bad output is unlinked and a `RuntimeError` is raised — never a "successful" blank PDF.
  - **Cancellation cleanup** is consistent at every checkpoint: pre-render, post-render, and post-assembly. A late-cancel after `save_all` has already written `dst` no longer leaves a complete-but-unwanted PDF on disk.
  - **Loud, recoverable diagnostics.** `cove_converter.pdf_flatten` is its own logger; every failure path (open, init-forms, page load, render, bitmap write, assembly, validation) emits a dedicated ERROR record with the underlying cause before raising. The `RuntimeError` message itself carries the actionable detail, so the GUI status cell shows real reason text instead of a generic "Failed".

- **PDF → PDF is the new default target for PDF inputs.** The "Convert to" dropdown now lists `.pdf` first; newly added PDF rows default to `.pdf` (the smart-PDF flatten path). The doc targets — `.docx`, `.odt`, `.rtf`, `.epub`, `.md`, `.html`, `.txt` — remain available but are no longer the primary path. PDF → other formats keep using `pypdf`'s form-aware text extraction; rasterising would destroy the text layer, so flatten is intentionally restricted to PDF → PDF.

- **No more "output would overwrite source" rejection on the default flow.** When PDF → PDF is selected with no separate output directory, `FileRow.resolve_output` now produces a `stem (1).pdf` path so the source-overwrite guard does not reject the convert before the worker runs. Non-PDF targets and explicit-output-directory cases are unchanged.

- **Batch combo cleanup.** The "Apply format to all" toolbar control is now placeholder-driven: the full label always fits (width sized from font metrics), the dropdown lists only the actual format choices (the redundant "Apply format to all…" item is gone), and the combo snaps back to the placeholder after each apply so re-selecting the same format still re-applies to every row.

## Honest limitations

PDFium does **not** execute Acrobat-specific JavaScript at render time. Stored AcroForm field values render normally — type, save in Acrobat, then convert in Cove and the values are baked into the output. Values that exist *only* while Adobe Acrobat is open running calculation scripts will not appear in the flattened output. The flatten function logs an INFO line acknowledging this on every successful run; this is a deliberate trade-off, not a regression.

## Tests

- `tests/test_pdf_flatten.py` — **29 tests** covering:
  - byte-scan detection (head/tail/middle/chunk-boundary cases),
  - rasteriser correctness (page count preserved, A4 size preserved, output is non-blank, colour is preserved),
  - the `init_forms()`-before-page-handles ordering contract,
  - output validation (page-count-mismatch trips, size-floor trips, bad output removed),
  - cancellation at every checkpoint (pre-render, mid-render, post-assembly),
  - failure-path diagnostics (every `RuntimeError` raise emits a `cove_converter.pdf_flatten` ERROR record),
  - `warnings.catch_warnings` capture of pypdfium2 XFA loader warnings,
  - routing (PDF→PDF goes through flatten, PDF→txt does not, plain PDFs skip flatten entirely),
  - `FileRow.resolve_output` source-collision avoidance.

Full suite: 153 passed.

## Downloads

| Platform | File | Notes |
|---|---|---|
| Linux (any distro with `libfuse2`) | `Cove-Universal-Converter-2.0.4-x86_64.AppImage` | Single executable, `chmod +x` and run. |
| Debian / Ubuntu / Mint / Pop!_OS | `cove-universal-converter_2.0.4_amd64.deb` | Installs system-wide with a menu entry. |
| Windows 10 / 11 | `cove-universal-converter-2.0.4-Setup.exe` | Installer with Start Menu shortcut + uninstaller. |
| Windows 10 / 11 (no install) | `cove-universal-converter-2.0.4-Portable.exe` | Single file — run it from anywhere, no install. |

Each binary ships with a matching `.sha256` sidecar on the release page.

## Verifying downloads

```bash
sha256sum -c Cove-Universal-Converter-2.0.4-x86_64.AppImage.sha256
sha256sum -c cove-universal-converter_2.0.4_amd64.deb.sha256
```

On Windows (PowerShell):

```powershell
Get-FileHash .\cove-universal-converter-2.0.4-Setup.exe -Algorithm SHA256
```

…and compare against the contents of the matching `.sha256` file.

## Notes

- Built and tested on Arch Linux and Windows 11 with Python 3.12 and PySide6 6.11.
- Windows `.exe` files are still **unsigned**; SmartScreen may warn on first launch — click **More info → Run anyway**.
- Smart-PDF flattening uses `pypdfium2` (PDFium under the hood). The same renderer powered the Enhance Scanned PDF feature in v2.0.3, so no new runtime dependency is introduced.
- See the [README](https://github.com/Sin213/cove-universal-converter#readme) for full usage docs.

## Thanks

Thanks to **YourExcellency** and **Drago** for the suggestions that shaped this release.

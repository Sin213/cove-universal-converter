# Handoff: Fix 48 audited bugs (bug.md triage pass)

## Problem
Full-repo audit (2026-07-19) produced 52 findings; triage validated 48
(rejected H3-as-stated, M10, M16; H5's pdf half). This pass fixes every
accepted finding except H2 (update signature verification - needs a
signing key + release-pipeline infrastructure, deferred; checksum sidecar
verification hardened instead via L8/M3 fixes).

## Changes
- `cove_converter/updater.py`
  - H1: progress-dialog cancel now connects with `Qt.DirectConnection`
    (worker's event loop is blocked in run(); queued cancel never arrived).
    Cancel is re-checked before swap; cancelled downloads no longer
    install/relaunch. "cancelled" failure closes silently.
  - M1: `swap_in_appimage` no longer unlinks the old AppImage; controller
    removes it only after `relaunch()` succeeds, and rolls back (drop new,
    restore APPIMAGE env) if relaunch throws. Same-name assets preserve
    the old bytes in a `.cove-rollback` sibling before the in-place
    replace (restored via `os.replace` on relaunch failure, deleted on
    success) - Codex round 1. Post-swap cancellation now rolls the swap
    back too, so a cancelled update never takes effect - Codex round 2.
    The finished slot receives its worker bound into the connection, so
    the cancel check cannot race `_on_download_thread_done` clearing
    `self._download_worker` - Codex round 4.
  - M2: controller hooks `aboutToQuit` -> cancel/quit/wait(10s) on both
    check and download threads.
  - M3: `asset_name` from the release JSON validated (no separators, no
    dot-dot) before path join.
  - L7: version parser handles arbitrary component counts; trailing-zero
    normalisation; suffix policy documented.
  - L8: swap re-hashes the staged `.part` against the verified digest
    right before the final rename.
  - L9: `.part` (and any same-name rollback copy) unlinked on any swap
    failure; the staging move itself is inside the cleanup-protected
    block - Codex round 3.
  - L10: `UpdateCheckWorker.run` wrapped; malformed payload emits
    `failed` instead of wedging `self._thread` forever.
  - L11: win-portable detection via `portable.marker`/`cove-app-data`
    markers before the path-substring heuristic.
  - L12: download AND swap both run in the worker thread; GUI thread only
    relaunches.
- `cove_converter/engines/pillow.py` - H5: mode normalisation for
  non-JPEG targets from a measured Pillow-12 unsavable-mode matrix
  (LA/PA/CMYK/I;16/I -> bmp, PA/CMYK -> png/ico); alpha composited onto
  white, others converted to RGB.
- `cove_converter/engines/spreadsheets.py` - H6: CSV read via bytes +
  fallback chain (utf-8-sig/utf-8/cp1252/latin-1); L13: CSV written as
  utf-8-sig (Excel BOM); L14: field-size limit raised via halving loop
  (`sys.maxsize` overflows the C long on Windows - Codex round 2).
- `cove_converter/engines/subtitles.py` - M6: UTF-16 BOM sniff before
  the fallback chain (latin-1 no longer "succeeds" on UTF-16 garbage).
- `cove_converter/engines/data.py` - H4: merge-key (`<<:`) overrides
  legal again; collision detection now runs only across explicit keys
  (verified identical precedence to SafeLoader incl. multi-source
  merges); L16: UTF-16 BOM sniff in `_read_text`; L17: sets serialised
  sorted for deterministic JSON.
- `cove_converter/engines/ffmpeg.py` - M7: libx264/x265 branch forces
  `-pix_fmt yuv420p` + even-dimension scale (GIF/RGB -> mp4 was
  yuv444p, unplayable in common players; verified via ffprobe; ceil
  variant so 1-pixel axes round up to 2 instead of 0 - Codex round 4);
  M8:
  qscale encoders (mpeg4/wmv2/mpeg2video) get `-q:v` derived from CRF;
  L15: stderr decode `errors="replace"`.
- `cove_converter/engines/pandoc.py` - M9: Popen + 0.2s poll loop
  honouring cancel, 600s timeout, stderr to temp file (no pipe deadlock).
- `cove_converter/engines/pdf.py` - M4: `timeout=600` on both pandoc
  subprocess calls; L19: `_init_forms_quietly()` after both
  `PdfDocument(...)` sites (enhance, CBZ) per pypdfium2 contract.
- `cove_converter/engines/pdf_flatten.py` - L18: `/JS`//`/JavaScript`
  markers must be delimiter-terminated (regex; `/JSON`//`/JScript` no
  longer false-positive; EOF counts as delimiter; chunk carry widened by
  1 byte for the lookahead); M5: assembly switched from eager
  `append_images` list (1 fd per page; PIL materialises the list, so a
  lazy iterable cannot help) to per-page `append=True` - verified 60
  pages under `RLIMIT_NOFILE=40`.
- `requirements.txt` / `pyproject.toml` - Pillow pinned `>=12.3`:
  append-mode PDF writer raises "trailer loop found" past ~4 pages on
  12.2 (reproduced in repo venv; fixed upstream in 12.3). This is also
  the real fix for audit H3 (enhance path) - the bug was
  Pillow-version-dependent. Repo `.venv` upgraded 12.2.0 -> 12.3.0.
- `cove_converter/routing.py` - L1: Comics/.cbz removed from
  FORMAT_CATEGORIES (input-format dialog; .cbz is output-only); L20:
  `.tar.gz` added to .zip/.tar targets (worker + resolve_output already
  supported it); L6: empty compound-suffix stem falls back to "output".
- `cove_converter/binaries.py` - L2: bundled-binary candidates require
  the execute bit (non-Windows); L3: darwin platform dir.
- `cove_converter/portable.py` - L4: non-frozen runs anchor to the
  package dir, not CWD-resolved argv[0].
- `cove_converter/__main__.py` - L5: exact-type StreamHandler guard +
  idempotent file-handler add.
- `cove_converter/settings.py` - M17: `_stored_int()` falls back to
  defaults on corrupt values and clamps ranges (crf 0-51, quality 1-100,
  concurrency 1-16, bitrate 32-512).
- `cove_converter/ui/main_window.py`
  - H7: duplicate `resizeEvent` merged (size grip + toast); the grip was
    stuck at (0,0) because the toast-only override won.
  - H8: `closeEvent` cancels all workers (incl. retired) and waits up to
    5s each; if any worker outlives the bounded wait the close is
    refused (`event.ignore()`) and completed automatically once the
    stragglers finish, so teardown can never destroy a live QThread -
    Codex round 3.
  - H9: `_retire_worker`/`_reap_dead_worker` + `self._dead_workers` keep
    cancelled workers referenced until their QThread finishes
    (row removal / Clear no longer lets GC destroy a live QThread).
  - M12: `_clear()` resets all four batch counters.
  - M13: retargeting a terminal-state row resets it to Pending (progress,
    completed/override outputs, error log) so it can reconvert.
  - M14: target changes on Queued/Processing rows are refused (combo
    snaps back); `completed_output` now recorded from the worker's
    `finished_ok(Path)` signal (previously unconnected) with recompute
    as fallback only.
  - M15: `_add_files` skips already-queued source paths.
  - L21: Delete/Backspace shortcuts scoped WidgetWithChildrenShortcut.
  - L22: 8s status-clear timer only clears its own message.
  - L23: Formats/Quality/log dialogs `deleteLater()` after exec.
  - L24: pixmap cache key includes devicePixelRatio.
  - L25: `_on_target_changed` only called inside the combo-has-ext guard
    in `_apply_batch_format`.
  - L26: `override_output` cleared at the start of every attempt
    (`_convert_all` loop + `_convert_one`).
  - B6: `unique_path` RuntimeError caught in both rename branches ->
    per-row preflight failure instead of crashing the click handler.
- `build.ps1` - B1: versioned gyan.dev URL (8.1.2) + SHA-256, pandoc
  3.1.13 SHA-256, `Assert-Sha256` before each Expand-Archive.
- `scripts/build-release.sh` - B3: FFMPEG_VERSION override without
  matching FFMPEG_URL/SHA256 now aborts; URL is env-overridable; B4:
  appimagetool hash-pinned (continuous tag is mutable); the pin covers
  cached and downloaded copies alike, PATH fallback gated behind
  `APPIMAGETOOL_ALLOW_SYSTEM=1` - Codex round 2.
- `scripts/smoke_conversions.py` - B5: no-op conditional removed.
- Tests updated for intentional behavior changes:
  `tests/test_updater_swap.py` (keep-old contract + new mismatch test),
  `tests/test_xlsx_to_csv.py` (read utf-8-sig),
  `tests/test_pdf_flatten.py` (delimiter-terminated marker fixtures;
  page-count-validation simulation drops `append` instead of
  `append_images`).

## Not fixed (deliberate)
- H2 (signed updates): requires generating/managing a signing key and
  changing the release pipeline; out of code-only scope. Sidecar
  checksum path hardened instead (L8, M3, L9, L10).
- M4's `--embed-resources` retained: dropping it would break legitimate
  local-image embedding in doc->PDF; timeout added. Flagged as a
  product decision.
- M5 page-count cap not added (fd bound fixed; an arbitrary cap would
  reject legitimate large documents).

## Verification
- `python -m compileall cove_converter scripts` - ok
- `.venv/bin/python -m pytest tests/ -q` - 188 passed (baseline 187;
  +1 new swap-checksum test), 0 failed
- Runtime probes (all pass): flatten 60 pages @ RLIMIT_NOFILE=40; JS
  marker truth table (/JS yes, /JSON no, /JScript no, EOF yes); LA/I;16/
  CMYK -> bmp + CMYK -> png via PillowWorker; cp1252 CSV + 200KB field ->
  xlsx; xlsx -> csv BOM present; UTF-16 SRT/YAML decode; YAML merge
  override == SafeLoader semantics; GIF(101x75) -> mp4 ffprobe shows
  yuv420p 100x74; AVI cmd carries `-q:v 6`; version tuple ordering.

## Scope
Only the audited findings above, their regression-pinning test updates,
and the Pillow>=12.3 pin. No UI redesign, no packaging restructure, no
release artifacts.

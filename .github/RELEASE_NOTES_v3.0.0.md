# Cove Universal Converter 3.0.0 — Better Batch Conversion

- Convert one source into several selected formats. Use the per-file **+**
  button or **Outputs / Presets** for batch selection. Single-output conversion
  remains the default; **Apply format to all** remains available.
- Save, apply and delete local named presets containing formats and quality
  settings. Presets persist through the existing QSettings store, independently
  of legacy quality keys. Names are sanitized, with 80 characters per name and
  32 presets maximum. Unsupported targets/busy files are skipped and reported.
- Reserve every target destination before starting, including case-insensitive
  and same-stem collisions. Never replace a queued source. Existing overwrite
  confirmation and duplicate renaming remain available.
- Run targets through existing conversion workers and the batch concurrency cap.
  Keep successful outputs if another fails or remaining work is cancelled;
  report partial rows separately from complete success, failure and cancellation.
  Completed paths are available in row tooltips and the context menu.
- Add SVG input to the supported-formats dialog and smoke matrix. PNG/WebP
  preserve alpha; JPG/PDF flatten onto white. Raster output uses 96 DPI.

## SVG restrictions

SVG parsing and rendering run in a fresh spawned process. Each target has a
15-second processing deadline including startup. Cancellation/timeouts terminate
the child, escalate to kill if needed, and clean its temporary output before
returning. Input limits are 2 MiB, 10,000 elements and depth 64. Output is limited
to 8,192 pixels per dimension and 16 million pixels total.

Attribute values are limited to 32,768 characters and 4,096 numeric entries.
Cumulative attribute complexity is limited to 250,000 units (characters plus
numeric entries, conservatively charging ancestor attributes at every descendant)
to prevent inherited-list amplification before rendering. Spawned renderers
request 512 MiB address-space/data limits on POSIX, best-effort where supported;
these memory limits are unavailable on Windows. Memory exhaustion produces a
clean conversion error. Default SVG namespaces are preserved so clip paths and
gradients defined in `defs` render correctly.

Only a self-contained UTF-8 vector subset is accepted. DTDs/entities, scripts,
event handlers, foreign objects, linked/embedded images, `use`, style elements,
CSS imports/escapes, and external or filesystem references are rejected before
rendering. Local paint/clip `url(#id)` references and safe inline styles work.
Fonts are restricted to built-in Helvetica/Times/Courier substitutes, avoiding
SVG-directed font-file reads and fontconfig subprocesses. No input-directed
network or local resource fetching is allowed. Process isolation is not an OS
security sandbox.

svglib/ReportLab is not a browser renderer: filters, masks, animation and other
unlisted elements are rejected; supported gradients, clipping and text may
render differently. No SVG output is offered.

## Packaging compatibility

Runtime/package versions are 3.0.0. Artifact names, updater behavior and existing
dependency pins are preserved. CI and packaged smoke routes now cover all four
SVG targets; the frozen launcher dispatches multiprocessing children before GUI
startup. Linux/Windows artifacts must still be built and validated on their own
platforms before release.

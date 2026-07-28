## What's Changed

This release fixes conversion correctness, resource cleanup, user interface edge cases, archive portability, and updater security.

### Routing and output naming

- Reject unsupported source and target format pairs before conversion.
- Preserve compound extensions such as `.tar.gz` when resolving filename collisions.
- Preserve extension casing in numbered output filenames.

### Audio and video

- Cap Opus bitrate at 256 kbps.
- Cap Vorbis bitrate at 192 kbps and force its supported 44.1 kHz sample rate.
- Scale odd-sized WebM and legacy video output to even dimensions.
- Avoid leaked FFmpeg processes when stderr capture is unavailable.
- Detect hardware encoders only after a successful probe with an exact encoder match, preventing false GPU acceleration selection.

### Images and PDFs

- Apply EXIF orientation before image conversion.
- Composite paletted or transparent images onto white before BMP export.
- Close converted images, PDF pages, bitmaps, buffers, and replacement images on both success and failure.
- Prevent long-running or failed PDF conversions from leaking resources or retaining file locks.

### Structured data and spreadsheets

- Detect UTF-32 before UTF-16 in JSON, YAML, CSV, and subtitle inputs.
- Support BOM-encoded UTF-16 CSV input.
- Reject nonstandard or non-finite JSON numbers such as `NaN`, `Infinity`, and overflowed exponents.
- Sanitize control characters and edge apostrophes from generated Excel sheet names, including after truncation.
- Prevent formula-injection checks from being bypassed with tabs, newlines, carriage returns, form feeds, or vertical tabs.
- Lock and restore the process-wide CSV field-size setting, preventing concurrent conversion races and persistent global mutation.
- Always close spreadsheet workbooks and YAML loaders.

### Subtitles

- Rewrite only complete timestamp lines, preventing dialogue containing timestamp-like text or `-->` from being corrupted.
- Correctly parse SRT and VTT timestamps longer than 99 hours.
- Require a complete following timing line before treating VTT text as a cue identifier.
- Preserve correct cue-setting removal while avoiding payload misclassification.

### Settings, startup, and desktop integration

- Parse persisted string booleans correctly, so `"false"` no longer enables custom quality.
- Fall back safely when persisted integer settings overflow.
- Prevent duplicate rotating log handlers when the same log directory is expressed through relative and resolved paths.
- Resolve `xdg-open` against the sanitized child environment `PATH`.
- Return a controlled failure when no opener executable exists.
- Use a true height-for-width format-chip layout, preventing clipping and horizontal overflow in narrow dialogs.
- Include display pixel ratio in SVG icon cache keys, preventing blurry or incorrectly sized icons across display scales.
- Guard unexpected Qt combo-box models, missing items, and missing application instances from edge-case crashes.
- Correct desktop menu categorization with valid `Utility`, `FileTools`, and `Qt` categories.

### Updater security and resilience

- Strictly validate repository identifiers before constructing GitHub requests.
- Restrict API, asset, redirect, and final download URLs to trusted HTTPS GitHub hosts and approved ports.
- Reject URLs containing credentials or control characters.
- Validate every redirect hop and close responses whose final destination is untrusted.
- Ignore untrusted API-provided release-page URLs and construct trusted GitHub release URLs locally.
- Disable direct update assets when their URLs fail validation.
- Preserve query strings when deriving `.sha256` sidecar URLs.
- Bound release metadata responses to 2 MiB and checksum responses to 1 MiB.
- Handle malformed release payload types, asset entries, tags, and fields without crashing.

### Archives and packaging

- Apply Windows-specific archive filename rules only on actual Win32 systems.
- Avoid `pipefail` build failures caused by executable discovery pipelines when multiple matches exist.
- Run FFmpeg command-construction tests without requiring a host FFmpeg install, preventing clean release runners from failing before packaging.

Each release artifact has a matching `.sha256` file for verification.

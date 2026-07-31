## What's Changed

This release is a broad format-coverage expansion across every conversion
engine, plus routing fixes and two new output-codec choices.

### New conversions

**Video**

- `.mxf`, `.rm`, `.swf`, `.vob`, `.asf`, `.ogv`, `.m2ts`, `.mts`, `.f4v` are
  now full read/write video containers, joining the existing MP4, MKV,
  WebM, MOV, and AVI.
- `.y4m` and `.ivf` are new write-only targets (raw YUV4MPEG2 and IVF/VP9
  elementary streams).

**Audio**

- `.ac3`, `.mp2`, `.spx`, `.caf`, `.au`, `.wv`, `.voc`, `.w64`, `.mka`,
  `.m4b`, `.oga`, `.aif`, `.tta`, `.amr`, and `.weba` join the existing
  audio targets.

**Images**

- `.jpe`, `.jfif`, `.avif`, `.jp2`, `.j2k`, `.jpx`, `.tga`, `.pcx`, `.ppm`,
  `.pgm`, `.pbm`, `.dds`, and `.icns` are now supported inputs and outputs.

**Documents**

- New Pandoc input formats: `.rst`, `.org`, `.textile`, `.typst`, `.ipynb`,
  `.fb2`, `.opml`, `.muse`, `.man`, `.native`, `.mediawiki`, `.wiki`,
  `.dokuwiki`, `.jira`, `.docbook`.
- New Pandoc output formats: `.adoc`, `.tei`, `.icml`, `.pptx`.

**Comics**

- CBZ and CBT can now convert to PDF, ZIP, or TAR.

**Subtitles**

- `.ass`, `.ssa`, `.lrc`, and `.sbv` join SRT and VTT, with full pairwise
  conversion between all six formats.

**Spreadsheets**

- `.tsv` joins CSV and XLSX with full pairwise conversion.

**Archives**

- `.tar.bz2`, `.tbz2`, `.tar.xz`, and `.txz` join ZIP, TAR, and TGZ.

**Structured data**

- `.ndjson`, `.jsonl`, and `.plist` join JSON and YAML.

**New output-codec choices**

- MP4/MKV video output can now target H.264 or AV1.
- M4A audio output can now target AAC or ALAC.

### Routing and correctness fixes

- Fixed video output routing so the new FFmpeg encode profiles for
  `.mxf`, `.rm`, `.swf`, `.vob`, `.asf`, `.ogv`, `.m2ts`, `.mts`, and `.f4v`
  are reachable as conversion targets, not just implemented in the engine.
- `.y4m` and `.ivf` are correctly routed as write-only targets, never
  offered as source inputs.
- Added a target-dropdown warning tooltip when converting ASS/SSA
  subtitles to SRT, since styling, karaoke, and positioning do not survive
  the format change.

Each release artifact has a matching `.sha256` file for verification.

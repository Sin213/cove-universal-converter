"""Bounded-memory text input with BOM and legacy spreadsheet encoding support."""
from __future__ import annotations

import codecs
from pathlib import Path
from typing import TextIO


def open_text(path: Path, *, legacy_fallback: bool = False) -> TextIO:
    """Open text without buffering the file; validate legacy encodings in chunks.

    CSV's fallback must be decided before emitting rows, since UTF-8 can fail
    near EOF. A bounded validation pass preserves the existing CP1252/Latin-1
    fallback without holding both the original bytes and decoded text in RAM.
    """
    with path.open("rb") as raw:
        prefix = raw.read(4)
        if prefix.startswith((codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE)):
            encoding = "utf-32"
        elif prefix.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
            encoding = "utf-16"
        elif not legacy_fallback:
            encoding = "utf-8-sig"
        else:
            decoders = {
                name: codecs.getincrementaldecoder(name)()
                for name in ("utf-8-sig", "cp1252")
            }
            raw.seek(0)
            while decoders:
                chunk = raw.read(64 * 1024)
                for name, decoder in list(decoders.items()):
                    try:
                        decoder.decode(chunk, final=not chunk)
                    except UnicodeDecodeError:
                        del decoders[name]
                if not chunk:
                    break
            encoding = next(iter(decoders), "latin-1")
    return path.open("r", encoding=encoding, newline="")

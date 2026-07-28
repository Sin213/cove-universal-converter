from __future__ import annotations

from PIL import Image, ImageOps

try:
    import pillow_heif  # type: ignore[import-untyped]
    pillow_heif.register_heif_opener()
except Exception:
    pass

from cove_converter.engines.base import BaseConverterWorker

_JPEG_EXTS = {".jpg", ".jpeg"}
_FORMAT_ALIASES = {".jpg": "JPEG", ".jpeg": "JPEG", ".tif": "TIFF"}

# Source modes each non-JPEG target's saver rejects (measured on Pillow 12;
# e.g. "cannot write mode LA as BMP"). WEBP and TIFF accept everything the
# openers here produce. JPEG is handled separately because it also needs
# P/RGBA flattened onto white.
_UNSAVABLE_MODES = {
    ".bmp": {"P", "LA", "PA", "RGBA", "CMYK", "I;16", "I"},
    ".png": {"PA", "CMYK"},
    ".ico": {"PA", "CMYK"},
}


def _flatten_to_white(img: Image.Image) -> Image.Image:
    """Composite an image with alpha onto a white RGB background."""
    background = Image.new("RGB", img.size, (255, 255, 255))
    try:
        with img.convert("RGBA") as rgba:
            alpha = rgba.getchannel("A")
            try:
                background.paste(rgba, mask=alpha)
            finally:
                alpha.close()
    except Exception:
        background.close()
        raise
    return background


class PillowWorker(BaseConverterWorker):
    def _convert(self) -> None:
        self.progress.emit(10)
        with Image.open(self.input_path) as source:
            img = ImageOps.exif_transpose(source)
            try:
                target = self.output_path.suffix.lower()
                replacement: Image.Image | None = None
                if target in _JPEG_EXTS and img.mode in ("RGBA", "LA", "P", "PA"):
                    # JPEG has no alpha; composite onto white so transparency
                    # does not go black.
                    replacement = _flatten_to_white(img)
                elif target in _JPEG_EXTS and img.mode != "RGB":
                    replacement = img.convert("RGB")
                elif img.mode in _UNSAVABLE_MODES.get(target, ()):
                    # The target's saver can't take this mode; normalise to
                    # RGB, compositing alpha onto white rather than dropping it.
                    if "A" in img.mode or "transparency" in img.info:
                        replacement = _flatten_to_white(img)
                    else:
                        replacement = img.convert("RGB")

                if replacement is not None:
                    if img is not source:
                        img.close()
                    img = replacement
                self.progress.emit(60)

                save_kwargs: dict = {}
                fmt = _FORMAT_ALIASES.get(target)
                if fmt:
                    save_kwargs["format"] = fmt
                if target in _JPEG_EXTS:
                    save_kwargs["quality"] = self.settings.effective_jpeg_quality()
                    save_kwargs["optimize"] = True
                elif target == ".webp":
                    save_kwargs["quality"] = self.settings.effective_webp_quality()
                img.save(self.output_path, **save_kwargs)
            finally:
                if img is not source:
                    img.close()

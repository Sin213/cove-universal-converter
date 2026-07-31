from __future__ import annotations

from PIL import Image, ImageOps

try:
    import pillow_heif  # type: ignore[import-untyped]
    pillow_heif.register_heif_opener()
except Exception:
    pass

from cove_converter.engines.base import BaseConverterWorker

_JPEG_EXTS = {".jpg", ".jpeg", ".jpe", ".jfif"}
_FORMAT_ALIASES = {
    ".jpg": "JPEG",
    ".jpeg": "JPEG",
    ".jpe": "JPEG",
    ".jfif": "JPEG",
    ".tif": "TIFF",
    ".jp2": "JPEG2000",
    ".j2k": "JPEG2000",
    ".jpx": "JPEG2000",
}
_SEQUENCE_TARGETS = {".tif", ".tiff", ".webp", ".avif"}

# Source modes each non-JPEG target's saver rejects (measured on Pillow 12;
# e.g. "cannot write mode LA as BMP"). WEBP and TIFF accept everything the
# openers here produce. JPEG is handled separately because it also needs
# P/RGBA flattened onto white.
_UNSAVABLE_MODES = {
    ".bmp": {"P", "LA", "PA", "RGBA", "CMYK", "I;16", "I"},
    ".png": {"PA", "CMYK"},
    ".ico": {"PA", "CMYK"},
    ".pcx": {"LA", "PA", "RGBA", "CMYK", "I;16", "I", "F"},
    ".tga": {"PA", "CMYK", "I;16", "I", "F"},
    ".jp2": {"P", "PA"},
    ".j2k": {"P", "PA"},
    ".jpx": {"P", "PA"},
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


def _prepare_frame(frame: Image.Image, target: str) -> Image.Image:
    img = ImageOps.exif_transpose(frame)
    replacement: Image.Image | None = None
    if target == ".pgm" and img.mode != "L":
        replacement = img.convert("L")
    elif target == ".pbm" and img.mode != "1":
        replacement = img.convert("1")
    elif target in _JPEG_EXTS and img.mode in ("RGBA", "LA", "P", "PA"):
        # JPEG has no alpha; composite onto white so transparency does not go
        # black.
        replacement = _flatten_to_white(img)
    elif target in _JPEG_EXTS and img.mode != "RGB":
        replacement = img.convert("RGB")
    elif img.mode in _UNSAVABLE_MODES.get(target, ()):
        # The target's saver can't take this mode; normalise to RGB,
        # compositing alpha onto white rather than dropping it.
        if "A" in img.mode or "transparency" in img.info:
            replacement = _flatten_to_white(img)
        else:
            replacement = img.convert("RGB")

    if replacement is not None:
        img.close()
        return replacement
    return img


class PillowWorker(BaseConverterWorker):
    def _convert(self) -> None:
        self.progress.emit(10)
        with Image.open(self.input_path) as source:
            target = self.output_path.suffix.lower()
            frame_count = (
                getattr(source, "n_frames", 1)
                if target in _SEQUENCE_TARGETS
                else 1
            )
            loop = source.info.get("loop")
            frames: list[Image.Image] = []
            durations: list[int] = []
            try:
                for index in range(frame_count):
                    source.seek(index)
                    duration = source.info.get("duration")
                    if duration is not None:
                        durations.append(int(duration))
                    frames.append(_prepare_frame(source, target))
                self.progress.emit(60)

                save_kwargs: dict[str, object] = {}
                fmt = _FORMAT_ALIASES.get(target)
                if fmt:
                    save_kwargs["format"] = fmt
                if target in _JPEG_EXTS:
                    save_kwargs["quality"] = self.settings.effective_jpeg_quality()
                    save_kwargs["optimize"] = True
                elif target == ".webp":
                    save_kwargs["quality"] = self.settings.effective_webp_quality()
                elif target == ".avif":
                    save_kwargs["quality"] = self.settings.effective_jpeg_quality()

                if frame_count > 1:
                    save_kwargs["save_all"] = True
                    save_kwargs["append_images"] = frames[1:]
                    if (
                        target in {".webp", ".avif"}
                        and len(durations) == frame_count
                    ):
                        save_kwargs["duration"] = durations
                    if target in {".webp", ".avif"} and loop is not None:
                        save_kwargs["loop"] = loop

                frames[0].save(self.output_path, **save_kwargs)
            finally:
                for frame in frames:
                    frame.close()

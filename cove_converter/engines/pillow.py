from __future__ import annotations

from PIL import Image

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except Exception:
    pass

from cove_converter.engines.base import BaseConverterWorker

_JPEG_EXTS = {".jpg", ".jpeg"}
_FORMAT_ALIASES = {".jpg": "JPEG", ".jpeg": "JPEG", ".tif": "TIFF"}


class PillowWorker(BaseConverterWorker):
    def _convert(self) -> None:
        self.progress.emit(10)
        with Image.open(self.input_path) as img:
            target = self.output_path.suffix.lower()
            if target in _JPEG_EXTS and img.mode in ("RGBA", "LA", "P"):
                # JPEG has no alpha; composite onto white so transparency doesn't go black.
                background = Image.new("RGB", img.size, (255, 255, 255))
                rgba = img.convert("RGBA")
                background.paste(rgba, mask=rgba.split()[-1])
                img = background
            elif target in _JPEG_EXTS and img.mode != "RGB":
                img = img.convert("RGB")
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

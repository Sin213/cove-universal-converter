"""Fresh QSettings round trips and defensive preset loading."""
import json

import pytest
from PySide6.QtCore import QSettings

from cove_converter import settings


@pytest.fixture
def store(tmp_path, monkeypatch):
    path = str(tmp_path / "settings.ini")
    monkeypatch.setattr(settings, "QSettings", lambda *args: QSettings(path, QSettings.Format.IniFormat))
    return lambda: QSettings(path, QSettings.Format.IniFormat)


def test_preset_save_restart_apply_delete_and_old_quality(store):
    from cove_converter.settings import PresetStore
    qs = store()
    qs.setValue("quality/jpeg_quality", 81)
    qs.sync()
    assert settings.load_settings().jpeg_quality == 81
    presets = PresetStore()
    presets.save("  Web images\n ", (".jpg", ".webp"), settings.ConversionSettings(jpeg_quality=73))
    restored = PresetStore().load()
    assert list(restored) == ["Web images"]
    preset = restored["Web images"]
    assert preset.targets == (".jpg", ".webp")
    assert preset.settings.jpeg_quality == 73
    assert preset.compatible_targets(".png") == ((".jpg", ".webp"), ())
    assert preset.compatible_targets(".txt") == ((), (".jpg", ".webp"))
    presets.delete("Web images")
    assert not PresetStore().load()


@pytest.mark.parametrize("raw", ["broken", "[]", '{"version":99}', '{"version":1,"presets":[null,{}, {"name": [], "targets": []}]}'])
def test_corrupt_presets_safe(store, raw):
    store().setValue("presets/data", raw)
    assert not settings.PresetStore().load()


def test_names_limits_targets_and_quality_are_validated(store):
    presets = settings.PresetStore()
    with pytest.raises(ValueError):
        presets.save("\x00\n", (".png",), settings.ConversionSettings())
    with pytest.raises(ValueError):
        presets.save("x" * 81, (".png",), settings.ConversionSettings())
    with pytest.raises(ValueError):
        presets.save("Bad", (".unknown",), settings.ConversionSettings())
    for i in range(32):
        presets.save(str(i), (".png",), settings.ConversionSettings())
    with pytest.raises(ValueError):
        presets.save("Too many", (".png",), settings.ConversionSettings())
    presets.save("0", (".webp",), settings.ConversionSettings())
    assert len(presets.load()) == 32
    store().setValue("presets/data", json.dumps({"version": 1, "presets": [
        {"name": "Old", "targets": [".jpg", ".unknown"], "quality": {"jpeg_quality": "bad", "video_preset": "bad", "use_custom_quality": "false"}}
    ]}))
    loaded = presets.load()["Old"]
    assert loaded.targets == (".jpg",)
    assert loaded.settings.jpeg_quality == 92
    assert loaded.settings.video_preset == "medium"
    assert loaded.settings.use_custom_quality is False

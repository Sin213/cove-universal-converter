"""Data-format worker — converts JSON ↔ YAML.

These are the two formats anyone configuring software / shipping API payloads
deals with daily. Both encode the same structural primitives (dict, list,
str, int, float, bool, null), so the round-trip is faithful for normal data.

We use ``yaml.safe_load`` / ``yaml.safe_dump`` to avoid loading arbitrary
Python objects from untrusted YAML.
"""
from __future__ import annotations

import datetime as _dt
import json
import math
from pathlib import Path

from cove_converter.engines.base import BaseConverterWorker


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


class YamlKeyCollisionError(RuntimeError):
    """Raised when distinct YAML mapping keys collapse to the same JSON
    string key during normalisation. JSON object keys must be strings, so
    YAML keys like ``1`` (int) and ``"1"`` (str) — or ``True`` and ``"True"``
    — would otherwise overwrite each other silently and lose data."""


class YamlNonFiniteFloatError(RuntimeError):
    """Raised when YAML contains ``.nan``, ``.inf``, or ``-.inf``. JSON has
    no representation for non-finite floats, and emitting ``NaN`` / ``Infinity``
    would produce output that strict JSON parsers reject. We refuse rather
    than silently coerce to a different value."""


class JsonDuplicateKeyError(RuntimeError):
    """Raised when the same JSON object contains the same key more than once.
    ``json.loads`` silently keeps only the last value, which would lose data
    on the way to YAML."""


def _json_loads_no_duplicate_keys(text: str):
    """Parse JSON, rejecting any object that repeats a key. ``object_pairs_hook``
    sees the raw key/value pairs (including duplicates) before ``dict`` would
    collapse them — so detection is recursive for nested objects."""

    def _no_dupes(pairs):
        seen: set[str] = set()
        for k, _ in pairs:
            if k in seen:
                raise JsonDuplicateKeyError(
                    f"JSON object has duplicate key {k!r}; refusing to "
                    "silently drop one value"
                )
            seen.add(k)
        return dict(pairs)

    return json.loads(text, object_pairs_hook=_no_dupes)


def _json_key(value) -> str:
    """Render a YAML mapping key as the JSON object key it would become.
    Booleans are spelled JSON-style (``true`` / ``false``) and ``None`` as
    ``null`` so distinct YAML keys map to distinct JSON strings whenever
    possible. Everything else falls back to ``str()``."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, (_dt.datetime, _dt.date, _dt.time)):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _json_safe(value):
    """Recursively normalise PyYAML safe-loaded values into JSON-serialisable
    primitives. ``yaml.safe_load`` happily produces ``datetime.date`` /
    ``datetime.datetime`` for unquoted timestamps, which ``json.dumps`` cannot
    handle. ISO-8601 strings round-trip cleanly through both formats.

    Mapping keys are normalised to JSON strings. If two distinct YAML keys
    collapse to the same JSON string (e.g. the integer ``1`` and the string
    ``"1"``), a ``YamlKeyCollisionError`` is raised rather than silently
    overwriting one of the values."""
    if isinstance(value, dict):
        out: dict[str, object] = {}
        seen: dict[str, object] = {}
        for k, v in value.items():
            jk = _json_key(k)
            if jk in seen and seen[jk] != k:
                raise YamlKeyCollisionError(
                    f"YAML keys {seen[jk]!r} and {k!r} both map to JSON key "
                    f"{jk!r}; refusing to silently drop one value"
                )
            seen[jk] = k
            out[jk] = _json_safe(v)
        return out
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(v) for v in value]
    if isinstance(value, (_dt.datetime, _dt.date, _dt.time)):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, float) and not math.isfinite(value):
        raise YamlNonFiniteFloatError(
            f"YAML value {value!r} is not representable in JSON "
            "(NaN/Infinity/-Infinity have no valid JSON form)"
        )
    return value


def _json_to_yaml(input_path: Path, output_path: Path) -> None:
    import yaml

    data = _json_loads_no_duplicate_keys(_read_text(input_path))
    with output_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(
            data, f,
            sort_keys=False, allow_unicode=True, default_flow_style=False,
        )


def _build_collision_loader():
    """Subclass of ``yaml.SafeLoader`` that rejects mapping-key collisions
    at the node-construction stage. PyYAML's default safe loader builds a
    plain ``dict`` and so silently overwrites:

    * exact duplicate keys (``foo: a\\nfoo: b``)
    * Python-equal keys with distinct YAML scalar tags (``1`` and ``true``,
      since ``True == 1`` and ``hash(True) == hash(1)``)
    * keys that only collide after JSON string-key normalisation
      (``1`` and ``"1"``)

    Catching them here, before ``dict.__setitem__`` collapses them, is the
    only way to refuse the data instead of silently dropping a value."""
    import yaml

    class _CollisionDetectingLoader(yaml.SafeLoader):
        pass

    def _construct_mapping_strict(loader, node):
        if not isinstance(node, yaml.MappingNode):
            raise yaml.constructor.ConstructorError(
                None, None,
                f"expected a mapping node, but found {node.id}",
                node.start_mark,
            )
        # Resolve YAML merge keys (`<<: *anchor`) the same way SafeLoader
        # does — otherwise we'd reject perfectly valid merged mappings.
        loader.flatten_mapping(node)
        data: dict = {}
        yield data
        seen_python: list = []
        seen_json: dict[str, object] = {}
        for key_node, value_node in node.value:
            key = loader.construct_object(key_node, deep=True)
            for prev in seen_python:
                try:
                    same = prev == key
                except Exception:
                    same = False
                if same:
                    raise YamlKeyCollisionError(
                        f"YAML mapping has duplicate/equivalent keys: "
                        f"{prev!r} and {key!r}"
                    )
            jk = _json_key(key)
            if jk in seen_json:
                raise YamlKeyCollisionError(
                    f"YAML keys {seen_json[jk]!r} and {key!r} both map to "
                    f"JSON key {jk!r}; refusing to silently drop one value"
                )
            seen_python.append(key)
            seen_json[jk] = key
            value = loader.construct_object(value_node, deep=True)
            data[key] = value

    _CollisionDetectingLoader.add_constructor(
        yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
        _construct_mapping_strict,
    )
    return _CollisionDetectingLoader


def _yaml_to_json(input_path: Path, output_path: Path) -> None:
    import yaml

    loader_cls = _build_collision_loader()
    # `yaml.load` with a SafeLoader subclass is safe — it inherits
    # SafeConstructor's restricted tag set.
    data = _json_safe(yaml.load(_read_text(input_path), Loader=loader_cls))
    output_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


class DataWorker(BaseConverterWorker):
    def _convert(self) -> None:
        in_ext = self.input_path.suffix.lower()
        out_ext = self.output_path.suffix.lower()
        self.progress.emit(20)

        if in_ext == ".json" and out_ext in (".yaml", ".yml"):
            _json_to_yaml(self.input_path, self.output_path)
        elif in_ext in (".yaml", ".yml") and out_ext == ".json":
            _yaml_to_json(self.input_path, self.output_path)
        elif in_ext in (".yaml", ".yml") and out_ext in (".yaml", ".yml"):
            # Reformatting between .yaml and .yml is a no-op other than ext.
            self.output_path.write_text(_read_text(self.input_path), encoding="utf-8")
        else:
            raise RuntimeError(f"DataWorker cannot convert {in_ext} → {out_ext}")

        self.progress.emit(90)

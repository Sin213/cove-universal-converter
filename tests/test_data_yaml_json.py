"""Regression test for YAML→JSON safe-loaded native types (Codex review #2)."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from cove_converter.engines import data  # noqa: E402


class YamlToJson(unittest.TestCase):
    def test_unquoted_date_round_trips_as_string(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            yml = tdp / "in.yaml"
            out = tdp / "out.json"
            yml.write_text("date: 2026-05-02\nname: cove\n", encoding="utf-8")
            data._yaml_to_json(yml, out)
            payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(payload["name"], "cove")
            self.assertEqual(payload["date"], "2026-05-02")

    def test_unquoted_datetime_round_trips_as_iso_string(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            yml = tdp / "in.yaml"
            out = tdp / "out.json"
            yml.write_text("when: 2026-05-02T13:45:00\n", encoding="utf-8")
            data._yaml_to_json(yml, out)
            payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertTrue(payload["when"].startswith("2026-05-02T13:45:00"))

    def test_nested_dates_normalised(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            yml = tdp / "in.yaml"
            out = tdp / "out.json"
            yml.write_text(
                "events:\n  - date: 2026-01-01\n    label: kickoff\n  - date: 2026-12-31\n",
                encoding="utf-8",
            )
            data._yaml_to_json(yml, out)
            payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(payload["events"][0]["date"], "2026-01-01")
            self.assertEqual(payload["events"][1]["date"], "2026-12-31")

    def test_primitives_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            yml = tdp / "in.yaml"
            out = tdp / "out.json"
            yml.write_text(
                "n: 42\nf: 3.14\nb: true\ns: hello\nnull_v: null\nlist: [1, 2, 3]\n",
                encoding="utf-8",
            )
            data._yaml_to_json(yml, out)
            payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(payload["n"], 42)
            self.assertEqual(payload["f"], 3.14)
            self.assertIs(payload["b"], True)
            self.assertEqual(payload["s"], "hello")
            self.assertIsNone(payload["null_v"])
            self.assertEqual(payload["list"], [1, 2, 3])


class YamlKeyCollisions(unittest.TestCase):
    """Distinct YAML keys must not silently collapse to one JSON key."""

    def test_int_and_string_one_collide(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            yml = tdp / "in.yaml"
            out = tdp / "out.json"
            # `1` is parsed as int, `"1"` as str — both stringify to "1".
            yml.write_text("1: alpha\n\"1\": beta\n", encoding="utf-8")
            with self.assertRaises(data.YamlKeyCollisionError):
                data._yaml_to_json(yml, out)

    def test_nested_collision_also_fails(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            yml = tdp / "in.yaml"
            out = tdp / "out.json"
            yml.write_text(
                "outer:\n  1: alpha\n  \"1\": beta\n",
                encoding="utf-8",
            )
            with self.assertRaises(data.YamlKeyCollisionError):
                data._yaml_to_json(yml, out)

    def test_non_colliding_yaml_still_converts(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            yml = tdp / "in.yaml"
            out = tdp / "out.json"
            yml.write_text("1: alpha\n2: beta\n", encoding="utf-8")
            data._yaml_to_json(yml, out)
            payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(payload, {"1": "alpha", "2": "beta"})

    def test_int_and_bool_keys_collide(self) -> None:
        # `1` (int) and `true` (bool) compare equal as Python dict keys —
        # PyYAML's default loader silently overwrites one. Detection has
        # to happen at the YAML node stage, not after dict construction.
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            yml = tdp / "in.yaml"
            out = tdp / "out.json"
            yml.write_text("1: alpha\ntrue: beta\n", encoding="utf-8")
            with self.assertRaises(data.YamlKeyCollisionError):
                data._yaml_to_json(yml, out)

    def test_exact_duplicate_keys_collide(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            yml = tdp / "in.yaml"
            out = tdp / "out.json"
            yml.write_text("foo: alpha\nfoo: beta\n", encoding="utf-8")
            with self.assertRaises(data.YamlKeyCollisionError):
                data._yaml_to_json(yml, out)

    def test_nested_int_bool_collision_also_fails(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            yml = tdp / "in.yaml"
            out = tdp / "out.json"
            yml.write_text(
                "outer:\n  1: alpha\n  true: beta\n",
                encoding="utf-8",
            )
            with self.assertRaises(data.YamlKeyCollisionError):
                data._yaml_to_json(yml, out)


class YamlNonFiniteFloats(unittest.TestCase):
    """YAML ``.nan`` / ``.inf`` / ``-.inf`` must not produce invalid JSON."""

    def test_nan_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            yml = tdp / "in.yaml"
            out = tdp / "out.json"
            yml.write_text("v: .nan\n", encoding="utf-8")
            with self.assertRaises(data.YamlNonFiniteFloatError):
                data._yaml_to_json(yml, out)

    def test_positive_infinity_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            yml = tdp / "in.yaml"
            out = tdp / "out.json"
            yml.write_text("v: .inf\n", encoding="utf-8")
            with self.assertRaises(data.YamlNonFiniteFloatError):
                data._yaml_to_json(yml, out)

    def test_negative_infinity_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            yml = tdp / "in.yaml"
            out = tdp / "out.json"
            yml.write_text("v: -.inf\n", encoding="utf-8")
            with self.assertRaises(data.YamlNonFiniteFloatError):
                data._yaml_to_json(yml, out)

    def test_nested_nan_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            yml = tdp / "in.yaml"
            out = tdp / "out.json"
            yml.write_text(
                "outer:\n  values:\n    - 1.0\n    - .nan\n",
                encoding="utf-8",
            )
            with self.assertRaises(data.YamlNonFiniteFloatError):
                data._yaml_to_json(yml, out)

    def test_finite_floats_still_convert(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            yml = tdp / "in.yaml"
            out = tdp / "out.json"
            yml.write_text("a: 0.0\nb: -1.5\nc: 1.0e+6\n", encoding="utf-8")
            data._yaml_to_json(yml, out)
            payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(payload["a"], 0.0)
            self.assertEqual(payload["b"], -1.5)
            self.assertEqual(payload["c"], 1e6)


class JsonDuplicateKeys(unittest.TestCase):
    """Duplicate JSON object keys must not silently drop values when going to YAML."""

    def test_top_level_duplicate_key_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            j = tdp / "in.json"
            out = tdp / "out.yaml"
            j.write_text('{"a": 1, "a": 2}', encoding="utf-8")
            with self.assertRaises(data.JsonDuplicateKeyError):
                data._json_to_yaml(j, out)

    def test_nested_duplicate_key_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            j = tdp / "in.json"
            out = tdp / "out.yaml"
            j.write_text('{"outer": {"a": 1, "a": 2}}', encoding="utf-8")
            with self.assertRaises(data.JsonDuplicateKeyError):
                data._json_to_yaml(j, out)

    def test_valid_json_still_converts(self) -> None:
        import yaml

        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            j = tdp / "in.json"
            out = tdp / "out.yaml"
            j.write_text(
                '{"a": 1, "b": [1, 2, 3], "c": {"nested": true}}',
                encoding="utf-8",
            )
            data._json_to_yaml(j, out)
            payload = yaml.safe_load(out.read_text(encoding="utf-8"))
            self.assertEqual(payload, {"a": 1, "b": [1, 2, 3], "c": {"nested": True}})


if __name__ == "__main__":
    unittest.main()

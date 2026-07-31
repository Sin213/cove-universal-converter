from __future__ import annotations

import datetime as dt
import json
import os
import plistlib
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from cove_converter.engines import data


class NdjsonTests(unittest.TestCase):
    def test_load_ignores_blank_lines_and_preserves_unicode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "records.ndjson"
            path.write_text(
                '{"name":"Café"}\n\n  \n{"name":"東京","count":2}\n',
                encoding="utf-8",
            )

            self.assertEqual(
                data._load_data(path, ".ndjson"),
                [{"name": "Café"}, {"name": "東京", "count": 2}],
            )

    def test_write_jsonl_is_compact_and_round_trips(self) -> None:
        records = [{"name": "Café", "active": True}, [1, 2, 3]]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "records.jsonl"
            data._write_data(records, path, ".jsonl")

            self.assertEqual(
                path.read_text(encoding="utf-8"),
                '{"name":"Café","active":true}\n[1,2,3]\n',
            )
            self.assertEqual(data._load_data(path, ".jsonl"), records)

    def test_write_requires_top_level_sequence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "records.ndjson"
            with self.assertRaises(data.NdjsonTopLevelError):
                data._write_data({"record": 1}, path, ".ndjson")

    def test_invalid_records_report_their_line(self) -> None:
        invalid_records = (
            '{"broken":',
            '{"duplicate":1,"duplicate":2}',
            '{"value":NaN}',
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "records.ndjson"
            for invalid in invalid_records:
                with self.subTest(invalid=invalid):
                    path.write_text(
                        f'{{"valid":true}}\n{invalid}\n',
                        encoding="utf-8",
                    )
                    with self.assertRaisesRegex(data.NdjsonSyntaxError, "line 2"):
                        data._load_data(path, ".ndjson")


class PlistTests(unittest.TestCase):
    def test_xml_plist_round_trip_for_json_safe_values(self) -> None:
        value = {
            "name": "Café",
            "enabled": True,
            "count": 3,
            "ratio": 1.5,
            "items": ["東京", {"nested": False}],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "document.plist"
            data._write_data(value, path, ".plist")

            self.assertTrue(path.read_bytes().startswith(b"<?xml"))
            self.assertEqual(data._load_data(path, ".plist"), value)

    def test_json_null_is_rejected_for_plist_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "document.plist"
            with self.assertRaises(data.PlistUnsupportedValueError):
                data._write_data({"missing": None}, path, ".plist")

    def test_plist_only_types_are_rejected_on_load(self) -> None:
        values = (
            {"payload": b"\x00\x01"},
            {"created": dt.datetime(2026, 7, 30, 12, 0)},
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "document.plist"
            for value in values:
                with self.subTest(value=value):
                    path.write_bytes(plistlib.dumps(value))
                    with self.assertRaises(data.PlistUnsupportedValueError):
                        data._load_data(path, ".plist")

    def test_worker_converts_jsonl_to_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "records.jsonl"
            output = root / "records.json"
            source.write_text('{"id":1}\n{"id":2}\n', encoding="utf-8")

            data.DataWorker(source, output)._convert()

            self.assertEqual(
                json.loads(output.read_text(encoding="utf-8")),
                [{"id": 1}, {"id": 2}],
            )


if __name__ == "__main__":
    unittest.main()

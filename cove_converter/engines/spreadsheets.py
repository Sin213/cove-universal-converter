"""Spreadsheet worker — converts CSV ↔ XLSX.

These two cover the bulk of real-world spreadsheet handoffs: CSV from data
exports / databases / APIs, XLSX from Excel / Google Sheets / LibreOffice.
We use ``openpyxl`` for XLSX I/O and the stdlib ``csv`` module for CSV.

The XLSX side picks the active sheet and dumps every row's values; formulae,
formatting, and merged cells are intentionally not preserved (the goal is a
plain-data round-trip, not a faithful workbook clone)."""
from __future__ import annotations

import csv
import re
from pathlib import Path

from cove_converter.engines.base import BaseConverterWorker


# Excel forbids these characters in sheet titles (and also caps length at 31).
_INVALID_SHEET_CHARS = re.compile(r"[\[\]:*?/\\]")

# Leading characters that spreadsheet apps treat as formula triggers. Cells
# beginning with any of these must be written as explicit strings so a
# malicious CSV can't smuggle a formula into the resulting XLSX.
_FORMULA_TRIGGERS = ("=", "+", "-", "@")


def _sanitize_sheet_title(stem: str) -> str:
    """Build a valid Excel worksheet title from a filename stem.

    Replaces characters Excel rejects (``[``, ``]``, ``:``, ``*``, ``?``,
    ``/``, ``\\``) with ``_``, enforces the 31-character cap, and falls back
    to ``Sheet1`` if nothing usable remains."""
    cleaned = _INVALID_SHEET_CHARS.sub("_", stem)[:31]
    return cleaned or "Sheet1"


def _csv_to_xlsx(input_path: Path, output_path: Path) -> None:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = _sanitize_sheet_title(input_path.stem)

    with input_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        for row_idx, row in enumerate(reader, start=1):
            for col_idx, value in enumerate(row, start=1):
                cell = ws.cell(row=row_idx, column=col_idx, value=value)
                # CSV gives us only strings. openpyxl auto-converts any
                # value starting with "=" into a formula cell; the other
                # trigger chars stay as strings but spreadsheet apps still
                # treat them as formula entry points. Pin data_type to "s"
                # so the XLSX cell is unambiguously text.
                if (
                    isinstance(value, str)
                    and value
                    and value[0] in _FORMULA_TRIGGERS
                ):
                    cell.data_type = "s"

    wb.save(str(output_path))


def _csv_escape_formula(value):
    # CSV has no cell-type distinction: any field beginning with one of the
    # formula-trigger characters is interpreted as an active formula by
    # Excel/LibreOffice on open. Prefix a single apostrophe so spreadsheet
    # apps treat the value as literal text. Non-string and non-dangerous
    # values pass through unchanged.
    if isinstance(value, str) and value and value[0] in _FORMULA_TRIGGERS:
        return "'" + value
    return value


def _xlsx_to_csv(input_path: Path, output_path: Path) -> None:
    from openpyxl import load_workbook

    # ``data_only=True`` returns cached formula results; cells whose formulas
    # have never been evaluated by Excel/LibreOffice come back as ``None``.
    # Load a second view with ``data_only=False`` so we can fall back to the
    # raw formula text instead of silently emitting an empty cell.
    wb_values = load_workbook(filename=str(input_path), read_only=True, data_only=True)
    wb_formulas = load_workbook(filename=str(input_path), read_only=True, data_only=False)
    try:
        ws_values = wb_values.active
        ws_formulas = wb_formulas.active

        with output_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            for value_row, formula_row in zip(
                ws_values.iter_rows(values_only=True),
                ws_formulas.iter_rows(values_only=True),
            ):
                out_row = []
                for value_cell, formula_cell in zip(value_row, formula_row):
                    if value_cell is not None:
                        out_row.append(_csv_escape_formula(value_cell))
                    elif isinstance(formula_cell, str) and formula_cell.startswith("="):
                        # Uncached formula — preserve the formula text so the
                        # data isn't silently dropped, but neutralize the
                        # leading `=` so the resulting CSV can't trigger
                        # formula execution when reopened.
                        out_row.append(_csv_escape_formula(formula_cell))
                    else:
                        out_row.append("")
                writer.writerow(out_row)
    finally:
        wb_values.close()
        wb_formulas.close()


class SpreadsheetWorker(BaseConverterWorker):
    def _convert(self) -> None:
        in_ext = self.input_path.suffix.lower()
        out_ext = self.output_path.suffix.lower()
        self.progress.emit(15)

        if in_ext == ".csv" and out_ext == ".xlsx":
            _csv_to_xlsx(self.input_path, self.output_path)
        elif in_ext == ".xlsx" and out_ext == ".csv":
            _xlsx_to_csv(self.input_path, self.output_path)
        else:
            raise RuntimeError(
                f"SpreadsheetWorker cannot convert {in_ext} → {out_ext}",
            )

        self.progress.emit(90)

"""Regression tests for stale-log clearing on retry / preflight failure.

Codex flagged that ``row.error_log`` was previously cleared only inside
``_start_row``. Preflight rejections (unsupported target, would-overwrite-source)
short-circuit *before* that clearing, so a re-attempt that landed in a
preflight branch would surface the prior worker traceback via "View log".

These tests pin down the contract:
  * ``_record_preflight_failure`` overwrites stale ``error_log`` with
    the *current* preflight reason.
  * ``_convert_one`` clears ``error_log`` before any preflight branch
    can return, so a successful retry that proceeds to ``_start_row``
    starts with a clean slate.
  * Successful completion (``_on_worker_finished`` with status "Done")
    drops any prior ``error_log``.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from PySide6.QtWidgets import QApplication

from cove_converter.ui.file_row import FileRow
from cove_converter.ui.main_window import MainWindow


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


@pytest.fixture()
def main_window(qapp):
    win = MainWindow()
    yield win
    win.close()


def _add_failed_row(
    win: MainWindow,
    tmp_path: Path,
    *,
    src_name: str = "source.png",
    target_ext: str,
) -> FileRow:
    src = tmp_path / src_name
    src.write_bytes(b"\x00")  # contents irrelevant for these tests
    row = FileRow(path=src, target_ext=target_ext)
    row.status = "Failed: legacy worker error"
    row.error_log = "stale traceback from a prior attempt\nTraceback (most recent call last):\n..."
    win._rows.append(row)
    return row


def test_record_preflight_failure_overwrites_stale_log(main_window, tmp_path):
    row = _add_failed_row(main_window, tmp_path, target_ext=".jpg")
    main_window._record_preflight_failure(
        len(main_window._rows) - 1,
        "Unsupported",
        "Unsupported: no engine available to convert .png → .xyz",
    )
    assert row.error_log is not None
    assert "stale traceback" not in row.error_log
    assert "no engine available" in row.error_log


def test_convert_one_clears_log_before_preflight_unsupported(main_window, tmp_path):
    # Source extension with no registered engine — preflight rejects it.
    row = _add_failed_row(
        main_window, tmp_path, src_name="legacy.bogus", target_ext=".png"
    )
    main_window._convert_one(row)
    # The stale traceback must be gone, replaced by the current reason.
    assert row.error_log is not None
    assert "stale traceback" not in row.error_log
    assert "no engine available" in row.error_log


def test_convert_one_unsupported_overwrites_with_current_reason(
    main_window, tmp_path,
):
    # Even when the prior log was a long worker traceback, the current
    # preflight reason is what View Log should surface for this attempt.
    row = _add_failed_row(
        main_window, tmp_path, src_name="legacy.bogus", target_ext=".png"
    )
    row.error_log = (
        "old worker error\n\nTraceback (most recent call last):\n"
        "  File \"engines/pdf.py\", line 1, in _convert\nKaboom\n"
    )
    main_window._convert_one(row)
    assert row.error_log is not None
    assert "Kaboom" not in row.error_log
    assert "Unsupported" in row.error_log


def test_finished_done_clears_prior_error_log(main_window, tmp_path):
    row = _add_failed_row(main_window, tmp_path, target_ext=".jpg")
    # Simulate a successful retry: status flips to Done, finished handler runs.
    row.status = "Done"
    main_window._on_worker_finished(row)
    assert row.error_log is None

"""Verify that ``BaseConverterWorker.failed`` carries the full traceback
so the UI can preserve it on the row and surface it via "View log".

This guards the contract used by ``MainWindow._on_worker_failed`` —
without the traceback the failed conversion would only show "Failed: …"
text, which is exactly the regression we're fixing.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from PySide6.QtWidgets import QApplication

from cove_converter.engines.base import BaseConverterWorker


@pytest.fixture(scope="module")
def qapp():
    # Other tests in the suite (e.g. dialog round-trip tests) need a
    # full ``QApplication`` to construct widgets. Once a process
    # creates a ``QCoreApplication`` it cannot upgrade to a
    # ``QApplication``, so we always reuse / create the GUI variant
    # here to stay compatible with the rest of the suite.
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


class _ExplodingWorker(BaseConverterWorker):
    def _convert(self) -> None:
        raise RuntimeError("Pandoc produced no HTML output for PDF rendering")


def _drain(qapp, predicate, *, timeout_ms: int = 2000) -> None:
    """Spin the Qt event loop until ``predicate()`` is true or we time out."""
    import time
    deadline = time.monotonic() + timeout_ms / 1000.0
    while not predicate() and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)


def test_failed_signal_emits_message_and_traceback(qapp, tmp_path: Path) -> None:
    src = tmp_path / "in.epub"
    src.write_bytes(b"not a real epub")
    dst = tmp_path / "out.pdf"

    worker = _ExplodingWorker(src, dst)

    captured: dict[str, str] = {}

    def on_failed(message: str, tb: str) -> None:
        captured["message"] = message
        captured["tb"] = tb

    worker.failed.connect(on_failed)
    worker.start()
    _drain(qapp, lambda: bool(captured))
    worker.wait(2000)

    assert captured, "failed signal was never emitted"
    assert "no HTML output" in captured["message"]
    # Traceback must contain the engine frame and the original exception
    # message — that's what the UI shows in the View log dialog.
    assert "RuntimeError" in captured["tb"]
    assert "no HTML output" in captured["tb"]
    assert "_convert" in captured["tb"]

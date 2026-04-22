from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import (
    QAction,
    QBrush,
    QColor,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
    QIcon,
    QKeySequence,
    QShortcut,
)
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from cove_converter import __version__, updater
from cove_converter.binaries import resource_path
from cove_converter.engines import worker_for
from cove_converter.routing import SUPPORTED_FORMATS, engine_for, info_for, targets_for
from cove_converter.settings import ConversionSettings, default_settings
from cove_converter.ui.drop_zone import DropZone
from cove_converter.ui.file_row import FileRow, unique_path
from cove_converter.ui.formats_dialog import FormatsDialog
from cove_converter.ui.quality_dialog import QualityDialog

_DARK_QSS = """
QMainWindow, QWidget { background: #1f1f1f; color: #e6e6e6; }
QPushButton { background: #3a7bd5; color: white; border: none; padding: 8px 16px; border-radius: 6px; }
QPushButton:disabled { background: #555; color: #aaa; }
QPushButton:hover:!disabled { background: #2f63a8; }
QPushButton#secondary { background: #3a3a3a; color: #e6e6e6; }
QPushButton#secondary:hover { background: #4a4a4a; }
QTableWidget { background: #262626; gridline-color: #3a3a3a; border: 1px solid #3a3a3a; }
QHeaderView::section { background: #2f2f2f; color: #ddd; padding: 6px; border: none; }
QComboBox { background: #2f2f2f; color: #e6e6e6; border: 1px solid #444; padding: 4px; border-radius: 4px; }
QProgressBar { border: 1px solid #444; border-radius: 4px; background: #2a2a2a; text-align: center; color: #ddd; }
QProgressBar::chunk { background: #3a7bd5; border-radius: 4px; }
QLineEdit { background: #2a2a2a; color: #e6e6e6; border: 1px solid #444; border-radius: 4px; padding: 6px 8px; }
QLineEdit:focus { border-color: #3a7bd5; }
QLabel#saveLabel, QLabel#bulkLabel { color: #bfbfbf; }
QToolButton#clearDest, QToolButton#gearButton {
    color: #9a9a9a;
    background: transparent;
    border: none;
    font-size: 16px;
    padding: 0 6px;
}
QToolButton#gearButton { font-size: 18px; }
QToolButton#clearDest:hover, QToolButton#gearButton:hover { color: #ffffff; }
QStatusBar { background: #171717; color: #c8c8c8; }
"""

_COL_NAME, _COL_TARGET, _COL_PROGRESS, _COL_STATUS = range(4)

# Subtle row tints that read well against the #262626 table background.
_TINT_PROCESSING = QColor("#1f3556")
_TINT_DONE       = QColor("#1f4021")
_TINT_FAILED     = QColor("#4a1f1f")
_TINT_NONE: QColor | None = None


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"Cove Universal Converter v{__version__}")
        self.resize(960, 640)
        self.setStyleSheet(_DARK_QSS)

        icon_file = resource_path("cove_icon.png")
        if icon_file.is_file():
            self.setWindowIcon(QIcon(str(icon_file)))

        self.setAcceptDrops(True)

        self._rows: list[FileRow] = []
        self._output_dir: Path | None = None
        self._settings: ConversionSettings = default_settings()

        # Batch / queue state
        self._pending_indices: list[int] = []
        self._active_indices: set[int] = set()
        self._batch_done = 0
        self._batch_failed = 0
        self._batch_total = 0

        # --- Layout ---
        central = QWidget(self)
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self.drop_zone = DropZone()
        self.drop_zone.clicked.connect(self._browse_files)
        self.drop_zone.info_requested.connect(self._show_formats_dialog)
        layout.addWidget(self.drop_zone)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["File", "Convert to", "Progress", "Status"])
        self.table.horizontalHeader().setSectionResizeMode(_COL_NAME, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(_COL_TARGET, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(_COL_PROGRESS, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(_COL_STATUS, QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self.table, stretch=1)

        delete_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Delete), self.table)
        delete_shortcut.activated.connect(self._remove_selected_rows)
        backspace_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Backspace), self.table)
        backspace_shortcut.activated.connect(self._remove_selected_rows)

        self._build_save_row(layout)
        self._build_action_row(layout)

        self.statusBar()  # create the implicit status bar

        self._updater = updater.UpdateController(
            parent=self,
            current_version=__version__,
            repo="Sin213/cove-universal-converter",
            app_display_name="Cove Universal Converter",
            cache_subdir="cove-universal-converter",
        )
        QTimer.singleShot(4000, self._updater.check)

    # =========================================================
    # Layout builders
    # =========================================================

    def _build_save_row(self, layout: QVBoxLayout) -> None:
        row = QHBoxLayout()
        row.setSpacing(8)
        save_label = QLabel("Save to:")
        save_label.setObjectName("saveLabel")
        row.addWidget(save_label)

        self.dest_edit = QLineEdit()
        self.dest_edit.setReadOnly(True)
        self.dest_edit.setPlaceholderText("Same folder as source file")
        row.addWidget(self.dest_edit, stretch=1)

        self.dest_clear_btn = QToolButton()
        self.dest_clear_btn.setObjectName("clearDest")
        self.dest_clear_btn.setText("✕")
        self.dest_clear_btn.setToolTip("Reset — save next to each source file")
        self.dest_clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.dest_clear_btn.setVisible(False)
        self.dest_clear_btn.clicked.connect(self._clear_output_dir)
        row.addWidget(self.dest_clear_btn)

        self.dest_browse_btn = QPushButton("Browse…")
        self.dest_browse_btn.setObjectName("secondary")
        self.dest_browse_btn.clicked.connect(self._browse_output_dir)
        row.addWidget(self.dest_browse_btn)

        layout.addLayout(row)

    def _build_action_row(self, layout: QVBoxLayout) -> None:
        row = QHBoxLayout()

        self.gear_btn = QToolButton()
        self.gear_btn.setObjectName("gearButton")
        self.gear_btn.setText("⚙")
        self.gear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.gear_btn.setToolTip("Quality settings")
        self.gear_btn.clicked.connect(self._show_quality_dialog)
        row.addWidget(self.gear_btn)

        row.addStretch(1)

        self.clear_btn = QPushButton("Clear")
        self.clear_btn.setObjectName("secondary")
        self.clear_btn.clicked.connect(self._clear)
        row.addWidget(self.clear_btn)

        self.convert_btn = QPushButton("Batch Convert All")
        self.convert_btn.clicked.connect(self._convert_all)
        row.addWidget(self.convert_btn)

        layout.addLayout(row)

    # =========================================================
    # Drag / drop / browse
    # =========================================================

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.drop_zone.set_drag_active(True)
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        self.drop_zone.set_drag_active(False)
        event.accept()

    def dropEvent(self, event: QDropEvent) -> None:
        self.drop_zone.set_drag_active(False)
        paths: list[Path] = []
        for url in event.mimeData().urls():
            if not url.isLocalFile():
                continue
            p = Path(url.toLocalFile())
            if p.is_dir():
                paths.extend(self._walk_folder(p))
            elif p.is_file():
                paths.append(p)
        if paths:
            self._add_files(paths)
            event.acceptProposedAction()

    def _walk_folder(self, folder: Path) -> list[Path]:
        collected: list[Path] = []
        supported = set(SUPPORTED_FORMATS.keys())
        for p in folder.rglob("*"):
            if p.is_file() and p.suffix.lower() in supported:
                collected.append(p)
        return sorted(collected)

    def _browse_files(self) -> None:
        exts = sorted(SUPPORTED_FORMATS.keys())
        pattern = " ".join(f"*{e}" for e in exts)
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Select files to convert",
            str(Path.home()),
            f"Supported files ({pattern});;All files (*.*)",
        )
        if paths:
            self._add_files([Path(p) for p in paths])

    def _show_formats_dialog(self) -> None:
        FormatsDialog(self).exec()

    def _show_quality_dialog(self) -> None:
        dialog = QualityDialog(self._settings, self)
        if dialog.exec():
            self._settings = dialog.result_settings()

    def _browse_output_dir(self) -> None:
        start = str(self._output_dir) if self._output_dir else str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, "Choose output folder", start)
        if folder:
            self._output_dir = Path(folder)
            self.dest_edit.setText(str(self._output_dir))
            self.dest_clear_btn.setVisible(True)

    def _clear_output_dir(self) -> None:
        self._output_dir = None
        self.dest_edit.clear()
        self.dest_clear_btn.setVisible(False)

    # =========================================================
    # Row management
    # =========================================================

    def _add_files(self, paths: list[Path]) -> None:
        for path in paths:
            info = info_for(path.suffix)
            if info is None:
                continue
            row = FileRow(path=path, target_ext=info.targets[0])
            self._rows.append(row)
            self._append_table_row(row)

    def _append_table_row(self, row: FileRow) -> None:
        r = self.table.rowCount()
        self.table.insertRow(r)

        name_item = QTableWidgetItem(row.path.name)
        name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        name_item.setToolTip(str(row.path))
        self.table.setItem(r, _COL_NAME, name_item)

        combo = QComboBox()
        for ext in targets_for(row.path.suffix):
            combo.addItem(ext)
        combo.currentTextChanged.connect(lambda ext, rr=row: setattr(rr, "target_ext", ext))
        self.table.setCellWidget(r, _COL_TARGET, combo)

        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(0)
        self.table.setCellWidget(r, _COL_PROGRESS, bar)

        status_item = QTableWidgetItem(row.status)
        status_item.setFlags(status_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.table.setItem(r, _COL_STATUS, status_item)

    def _clear(self) -> None:
        for row in self._rows:
            if row.worker is not None:
                row.worker.cancel()
        self._rows.clear()
        self.table.setRowCount(0)
        self._pending_indices.clear()
        self._active_indices.clear()

    def _show_context_menu(self, pos: QPoint) -> None:
        index = self.table.indexAt(pos)
        if not index.isValid():
            return
        if not self.table.selectionModel().isSelected(index):
            self.table.clearSelection()
            self.table.selectRow(index.row())

        menu = QMenu(self)
        count = len(self.table.selectionModel().selectedRows())
        label = "Remove" if count <= 1 else f"Remove {count} items"
        remove_action = QAction(label, menu)
        remove_action.triggered.connect(self._remove_selected_rows)
        menu.addAction(remove_action)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _remove_selected_rows(self) -> None:
        rows = sorted({idx.row() for idx in self.table.selectionModel().selectedRows()}, reverse=True)
        for r in rows:
            if 0 <= r < len(self._rows):
                row = self._rows[r]
                if row.worker is not None and row.worker.isRunning():
                    row.worker.cancel()
                self._rows.pop(r)
                self.table.removeRow(r)

    # =========================================================
    # Conversion / queue
    # =========================================================

    def _convert_all(self) -> None:
        # Figure out which rows are eligible to (re)run.
        eligible: list[int] = []
        resolved: list[tuple[int, Path]] = []
        for i, row in enumerate(self._rows):
            if row.status in ("Done", "Processing"):
                continue
            if engine_for(row.path.suffix, row.target_ext) is None:
                self._set_status(i, "Unsupported")
                continue
            out = row.resolve_output(self._output_dir)
            if out.resolve() == row.path.resolve():
                self._set_status(i, "Failed: output would overwrite source")
                continue
            eligible.append(i)
            resolved.append((i, out))

        if not eligible:
            self.statusBar().showMessage("Nothing to convert.", 4000)
            return

        # Overwrite-confirmation step.
        conflicts = [(i, out) for i, out in resolved if out.exists()]
        if conflicts:
            choice = self._ask_overwrite(conflicts)
            if choice == "cancel":
                return
            if choice == "rename":
                reserved: set[Path] = set()
                for i, out in conflicts:
                    candidate = unique_path(out, reserved)
                    self._rows[i].override_output = candidate
                    reserved.add(candidate)

        self.convert_btn.setEnabled(False)
        self._batch_total = len(eligible)
        self._batch_done = 0
        self._batch_failed = 0
        self._pending_indices = list(eligible)
        self.statusBar().showMessage(f"Converting {self._batch_total}…")
        self._pump_queue()

    def _ask_overwrite(self, conflicts: list[tuple[int, Path]]) -> str:
        """Return 'overwrite', 'rename', or 'cancel'."""
        preview = "\n".join(f"• {p.name}" for _, p in conflicts[:8])
        if len(conflicts) > 8:
            preview += f"\n… and {len(conflicts) - 8} more"
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Files already exist")
        box.setText(f"{len(conflicts)} output file(s) already exist:")
        box.setInformativeText(preview)
        overwrite_btn = box.addButton("Overwrite", QMessageBox.ButtonRole.DestructiveRole)
        rename_btn    = box.addButton("Rename duplicates", QMessageBox.ButtonRole.ActionRole)
        cancel_btn    = box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(rename_btn)
        box.exec()
        clicked = box.clickedButton()
        if clicked is overwrite_btn:
            return "overwrite"
        if clicked is rename_btn:
            return "rename"
        return "cancel"

    def _pump_queue(self) -> None:
        while (
            self._pending_indices
            and len(self._active_indices) < max(1, self._settings.max_concurrent)
        ):
            index = self._pending_indices.pop(0)
            self._start_row(index)

        if not self._pending_indices and not self._active_indices and self._batch_total > 0:
            self._announce_batch_done()

    def _start_row(self, index: int) -> None:
        row = self._rows[index]
        engine = engine_for(row.path.suffix, row.target_ext)
        if engine is None:
            self._set_status(index, "Unsupported")
            return

        output_path = row.resolve_output(self._output_dir)

        worker_cls = worker_for(engine)
        worker = worker_cls(row.path, output_path, self._settings)
        row.worker = worker

        worker.progress.connect(lambda pct, i=index: self._set_progress(i, pct))
        worker.status.connect(lambda text, i=index: self._set_status(i, text))
        worker.finished.connect(lambda i=index: self._on_worker_finished(i))
        self._active_indices.add(index)
        worker.start()

    def _on_worker_finished(self, index: int) -> None:
        self._active_indices.discard(index)
        if 0 <= index < len(self._rows):
            status = self._rows[index].status
            if status == "Done":
                self._batch_done += 1
            elif status.startswith("Failed"):
                self._batch_failed += 1
        self._pump_queue()

    def _announce_batch_done(self) -> None:
        total = self._batch_total
        done = self._batch_done
        failed = self._batch_failed
        if failed:
            msg = f"✓ {done} of {total} done · ✗ {failed} failed"
        else:
            msg = f"✓ All {total} conversions complete"
        self.statusBar().showMessage(msg, 8000)
        self.convert_btn.setEnabled(True)
        self._batch_total = 0

    # =========================================================
    # Row status / tinting
    # =========================================================

    def _set_progress(self, index: int, pct: int) -> None:
        bar = self.table.cellWidget(index, _COL_PROGRESS)
        if isinstance(bar, QProgressBar):
            bar.setValue(pct)
        if 0 <= index < len(self._rows):
            self._rows[index].progress = pct

    def _set_status(self, index: int, text: str) -> None:
        if not (0 <= index < self.table.rowCount()):
            return

        display = text
        tint: QColor | None = None
        if text == "Done":
            display = "✓ Done"
            tint = _TINT_DONE
        elif text == "Processing":
            tint = _TINT_PROCESSING
        elif text.startswith("Failed") or text == "Unsupported":
            display = "✗ " + text
            tint = _TINT_FAILED
        elif text == "Cancelled":
            tint = _TINT_NONE

        item = self.table.item(index, _COL_STATUS)
        if item is not None:
            item.setText(display)

        self._apply_row_tint(index, tint)

        if 0 <= index < len(self._rows):
            self._rows[index].status = text

    def _apply_row_tint(self, index: int, color: QColor | None) -> None:
        for col in range(self.table.columnCount()):
            item = self.table.item(index, col)
            if item is None:
                continue
            if color is None:
                item.setData(Qt.ItemDataRole.BackgroundRole, None)
            else:
                item.setBackground(QBrush(color))

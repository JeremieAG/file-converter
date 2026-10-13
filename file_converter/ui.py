"""Fenêtre principale."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Iterable

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QDragEnterEvent, QDropEvent, QCloseEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .core import FORMATS, M4A, M4A_REENCODE_KBPS, MP3, MP3_QUALITIES, ConversionOptions
from .worker import ConversionWorker

MEDIA_FILTER = (
    "Fichiers audio/vidéo (*.mp4 *.m4v *.mkv *.mov *.avi *.webm *.wmv *.flv *.mpg *.mpeg *.ts *.3gp "
    "*.mp3 *.m4a *.aac *.wav *.flac *.ogg *.opus *.wma *.aif *.aiff *.alac);;"
    "Tous les fichiers (*)"
)

COLUMN_FILE, COLUMN_STATUS, COLUMN_PROGRESS = range(3)

SUCCESS_COLOR = QColor("#2e7d32")
ERROR_COLOR = QColor("#c62828")


class State(Enum):
    PENDING = "En attente"
    RUNNING = "Conversion…"
    DONE = "Terminé"
    FAILED = "Erreur"
    CANCELLED = "Annulé"


@dataclass
class FileEntry:
    path: Path
    state: State = State.PENDING


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("File Converter")
        self.setAcceptDrops(True)
        self.resize(860, 540)

        self._entries: list[FileEntry] = []
        self._worker: ConversionWorker | None = None
        self._close_when_stopped = False

        self._build_ui()
        self._on_format_changed()
        self._update_controls()

    # ----------------------------------------------------------------- construction

    def _build_ui(self) -> None:
        self.add_button = QPushButton("Ajouter des fichiers…")
        self.add_button.clicked.connect(self._choose_files)
        self.remove_button = QPushButton("Retirer la sélection")
        self.remove_button.clicked.connect(self._remove_selected)
        self.clear_button = QPushButton("Vider la liste")
        self.clear_button.clicked.connect(self._clear)

        file_buttons = QHBoxLayout()
        file_buttons.addWidget(self.add_button)
        file_buttons.addWidget(self.remove_button)
        file_buttons.addWidget(self.clear_button)
        file_buttons.addStretch()

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Fichier", "Statut", "Progression"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(COLUMN_FILE, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(COLUMN_STATUS, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(COLUMN_PROGRESS, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(COLUMN_PROGRESS, 160)
        self.table.itemSelectionChanged.connect(self._update_controls)

        drop_hint = QLabel(
            "Glissez-déposez vos fichiers vidéo ou audio ici\n"
            "ou cliquez sur « Ajouter des fichiers… »"
        )
        drop_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        drop_hint.setStyleSheet("QLabel { border: 2px dashed palette(mid); border-radius: 8px; color: palette(mid); }")

        self.file_stack = QStackedWidget()
        self.file_stack.addWidget(drop_hint)
        self.file_stack.addWidget(self.table)

        self.format_combo = QComboBox()
        for fmt in FORMATS:
            self.format_combo.addItem(fmt.label, fmt)
        self.format_combo.currentIndexChanged.connect(self._on_format_changed)

        self.quality_combo = QComboBox()
        for quality in MP3_QUALITIES:
            self.quality_combo.addItem(quality.label, quality)

        self.format_hint = QLabel()
        self.format_hint.setWordWrap(True)
        self.format_hint.setStyleSheet("color: palette(mid);")

        self.same_dir_check = QCheckBox("Même dossier que le fichier source")
        self.same_dir_check.setChecked(True)
        self.same_dir_check.toggled.connect(self._update_controls)
        self.output_dir_edit = QLineEdit()
        self.output_dir_edit.setReadOnly(True)
        self.output_dir_edit.setPlaceholderText("Aucun dossier choisi")
        self.browse_button = QPushButton("Parcourir…")
        self.browse_button.clicked.connect(self._choose_output_dir)

        output_dir_row = QHBoxLayout()
        output_dir_row.addWidget(self.output_dir_edit)
        output_dir_row.addWidget(self.browse_button)

        options_form = QFormLayout()
        options_form.addRow("Format de sortie :", self.format_combo)
        options_form.addRow("Qualité MP3 :", self.quality_combo)
        options_form.addRow("", self.format_hint)
        options_form.addRow("Dossier de sortie :", self.same_dir_check)
        options_form.addRow("", output_dir_row)
        options_box = QGroupBox("Options")
        options_box.setLayout(options_form)

        self.summary_label = QLabel()
        self.convert_button = QPushButton("Convertir")
        self.convert_button.setDefault(True)
        self.convert_button.clicked.connect(self._start_conversion)
        self.cancel_button = QPushButton("Annuler")
        self.cancel_button.clicked.connect(self._cancel_conversion)

        action_row = QHBoxLayout()
        action_row.addWidget(self.summary_label, 1)
        action_row.addWidget(self.cancel_button)
        action_row.addWidget(self.convert_button)

        layout = QVBoxLayout()
        layout.addLayout(file_buttons)
        layout.addWidget(self.file_stack, 1)
        layout.addWidget(options_box)
        layout.addLayout(action_row)
        central = QWidget()
        central.setLayout(layout)
        self.setCentralWidget(central)

    # ----------------------------------------------------------------- liste de fichiers

    def add_files(self, paths: Iterable[Path]) -> None:
        if self._is_running():
            return
        known = {entry.path for entry in self._entries}
        skipped_dirs = 0
        for path in paths:
            path = Path(path).resolve()
            if path.is_dir():
                skipped_dirs += 1
                continue
            if path in known:
                continue
            known.add(path)
            self._entries.append(FileEntry(path))
            self._append_row(path)
        if skipped_dirs:
            self.statusBar().showMessage(
                f"{skipped_dirs} dossier(s) ignoré(s) : déposez directement les fichiers.", 5000
            )
        self._update_controls()

    def _append_row(self, path: Path) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        name_item = QTableWidgetItem(path.name)
        name_item.setToolTip(str(path))
        self.table.setItem(row, COLUMN_FILE, name_item)
        self.table.setItem(row, COLUMN_STATUS, QTableWidgetItem(State.PENDING.value))
        progress = QProgressBar()
        progress.setRange(0, 100)
        progress.setValue(0)
        self.table.setCellWidget(row, COLUMN_PROGRESS, progress)

    def _choose_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Choisir des fichiers", "", MEDIA_FILTER)
        self.add_files(Path(p) for p in paths)

    def _remove_selected(self) -> None:
        rows = sorted({index.row() for index in self.table.selectionModel().selectedRows()}, reverse=True)
        for row in rows:
            self.table.removeRow(row)
            del self._entries[row]
        self._update_controls()

    def _clear(self) -> None:
        self.table.setRowCount(0)
        self._entries.clear()
        self.summary_label.clear()
        self._update_controls()

    # ----------------------------------------------------------------- glisser-déposer

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if not self._is_running() and any(url.isLocalFile() for url in event.mimeData().urls()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        self.dragEnterEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        self.add_files(Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile())
        event.acceptProposedAction()

    # ----------------------------------------------------------------- options

    def _on_format_changed(self) -> None:
        fmt = self.format_combo.currentData()
        if fmt == M4A:
            hint = (
                "Si l'audio source est déjà en AAC, il est copié sans réencodage (rapide, sans perte). "
                f"Sinon, il est encodé en AAC {M4A_REENCODE_KBPS} kbit/s."
            )
        elif fmt == MP3:
            hint = "CBR : débit constant. VBR : débit variable, meilleur rapport qualité/taille."
        else:
            hint = "Format sans perte : fichiers volumineux, qualité identique à la source décodée."
        self.format_hint.setText(hint)
        self._update_controls()

    def _choose_output_dir(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Dossier de sortie", self.output_dir_edit.text())
        if directory:
            self.output_dir_edit.setText(str(Path(directory)))
            self.same_dir_check.setChecked(False)

    def _output_dir(self) -> Path | None:
        if self.same_dir_check.isChecked():
            return None
        text = self.output_dir_edit.text()
        return Path(text) if text else None

    # ----------------------------------------------------------------- conversion

    def _is_running(self) -> bool:
        return self._worker is not None

    def _start_conversion(self) -> None:
        if self._is_running():
            return
        output_dir = self._output_dir()
        if not self.same_dir_check.isChecked():
            if output_dir is None:
                QMessageBox.warning(self, "Dossier de sortie", "Choisissez un dossier de sortie.")
                return
            if not output_dir.is_dir():
                QMessageBox.warning(self, "Dossier de sortie", f"Le dossier « {output_dir} » n'existe pas.")
                return

        jobs = [(row, entry.path) for row, entry in enumerate(self._entries) if entry.state != State.DONE]
        if not jobs:
            self.statusBar().showMessage("Tous les fichiers de la liste sont déjà convertis.", 5000)
            return

        options = ConversionOptions(
            format=self.format_combo.currentData(),
            mp3_quality=self.quality_combo.currentData(),
            output_dir=output_dir,
        )
        for row, _ in jobs:
            self._set_state(row, State.PENDING)
            self._set_progress(row, 0)

        worker = ConversionWorker(jobs, options, self)
        worker.file_started.connect(self._on_file_started)
        worker.file_progress.connect(self._set_progress)
        worker.file_succeeded.connect(self._on_file_succeeded)
        worker.file_failed.connect(self._on_file_failed)
        worker.file_cancelled.connect(self._on_file_cancelled)
        worker.finished.connect(self._on_worker_finished)
        self._worker = worker
        self.summary_label.setText(f"Conversion de {len(jobs)} fichier(s)…")
        self._update_controls()
        worker.start()

    def _cancel_conversion(self) -> None:
        if self._worker is not None:
            self.cancel_button.setEnabled(False)
            self.summary_label.setText("Annulation…")
            self._worker.cancel()

    def _on_file_started(self, row: int) -> None:
        self._set_state(row, State.RUNNING)
        self.table.scrollToItem(self.table.item(row, COLUMN_FILE))

    def _on_file_succeeded(self, row: int, output: str, stream_copied: bool) -> None:
        detail = f"→ {Path(output).name}"
        if stream_copied:
            detail += " (copie sans réencodage)"
        self._set_state(row, State.DONE, detail, tooltip=output)
        self._set_progress(row, 100)

    def _on_file_failed(self, row: int, message: str) -> None:
        self._set_state(row, State.FAILED, message, tooltip=message)
        self._set_progress(row, 0)

    def _on_file_cancelled(self, row: int) -> None:
        self._set_state(row, State.CANCELLED)
        self._set_progress(row, 0)

    def _on_worker_finished(self) -> None:
        if self._worker is not None:
            self._worker.deleteLater()
        self._worker = None
        counts = {state: sum(1 for e in self._entries if e.state == state) for state in State}
        parts = [f"{counts[State.DONE]} terminé(s)"]
        if counts[State.FAILED]:
            parts.append(f"{counts[State.FAILED]} en erreur")
        if counts[State.CANCELLED]:
            parts.append(f"{counts[State.CANCELLED]} annulé(s)")
        self.summary_label.setText(", ".join(parts) + ".")
        self._update_controls()
        if self._close_when_stopped:
            self.close()

    def _set_state(self, row: int, state: State, detail: str = "", tooltip: str = "") -> None:
        self._entries[row].state = state
        separator = " : " if state == State.FAILED else " "
        item = self.table.item(row, COLUMN_STATUS)
        item.setText(state.value + separator + detail if detail else state.value)
        item.setToolTip(tooltip)
        color = {State.DONE: SUCCESS_COLOR, State.FAILED: ERROR_COLOR}.get(state)
        item.setForeground(QBrush(color) if color else QBrush())

    def _set_progress(self, row: int, percent: int) -> None:
        bar: QProgressBar = self.table.cellWidget(row, COLUMN_PROGRESS)
        # Un pourcentage n'a pas de sens pour un fichier en erreur ou annulé.
        bar.setTextVisible(self._entries[row].state not in (State.FAILED, State.CANCELLED))
        if percent < 0:  # durée inconnue : barre indéterminée
            bar.setRange(0, 0)
        else:
            bar.setRange(0, 100)
            bar.setValue(percent)

    # ----------------------------------------------------------------- état des contrôles

    def _update_controls(self) -> None:
        running = self._is_running()
        has_files = bool(self._entries)
        self.file_stack.setCurrentWidget(self.table if has_files else self.file_stack.widget(0))
        self.add_button.setEnabled(not running)
        self.remove_button.setEnabled(not running and bool(self.table.selectionModel().selectedRows()))
        self.clear_button.setEnabled(not running and has_files)
        self.format_combo.setEnabled(not running)
        self.quality_combo.setEnabled(not running and self.format_combo.currentData() == MP3)
        self.same_dir_check.setEnabled(not running)
        custom_dir = not self.same_dir_check.isChecked()
        self.output_dir_edit.setEnabled(not running and custom_dir)
        self.browse_button.setEnabled(not running)
        self.convert_button.setEnabled(not running and has_files)
        self.cancel_button.setEnabled(running)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._worker is None:
            event.accept()
            return
        if not self._close_when_stopped:
            answer = QMessageBox.question(
                self,
                "Conversion en cours",
                "Une conversion est en cours. L'annuler et quitter ?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self._close_when_stopped = True
            self._cancel_conversion()
        # La fenêtre se fermera dans _on_worker_finished, une fois ffmpeg arrêté
        # et les fichiers partiels supprimés.
        event.ignore()

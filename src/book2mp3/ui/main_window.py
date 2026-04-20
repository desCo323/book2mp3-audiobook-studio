from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QProgressBar,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from book2mp3.config import AppPaths
from book2mp3.models import JobState
from book2mp3.pipeline.jobs import JobManager
from book2mp3.tts.piper import PiperBackend
from book2mp3.ui.worker import JobWorker
from book2mp3.utils.logging_utils import get_logger


class MainWindow(QMainWindow):
    def __init__(self, paths: AppPaths) -> None:
        super().__init__()
        self.paths = paths
        self.manager = JobManager(paths)
        self.worker: JobWorker | None = None
        self.current_job_id: str | None = None
        self.logger = get_logger("ui")

        self.setWindowTitle("book2mp3")
        self.resize(1280, 760)
        self._build_ui()
        self.refresh_voice_list()
        self.manager.recover_interrupted_jobs()
        self.refresh_jobs()
        self.maybe_start_next_job()

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)

        outer = QHBoxLayout(root)
        splitter = QSplitter(Qt.Horizontal)
        outer.addWidget(splitter)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel("Jobs"))
        self.jobs_list = QListWidget()
        self.jobs_list.itemSelectionChanged.connect(self.on_job_selected)
        left_layout.addWidget(self.jobs_list)
        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(self.refresh_jobs)
        left_layout.addWidget(refresh_button)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)

        form = QFormLayout()
        self.source_edit = QLineEdit()
        browse_button = QPushButton("Browse")
        browse_button.clicked.connect(self.select_source_file)
        source_row = QHBoxLayout()
        source_row.addWidget(self.source_edit)
        source_row.addWidget(browse_button)
        form.addRow("Source file", self._wrap(source_row))

        self.voice_combo = QComboBox()
        form.addRow("Voice", self.voice_combo)

        self.output_mode_combo = QComboBox()
        self.output_mode_combo.addItems(["segments", "single_file"])
        form.addRow("Output mode", self.output_mode_combo)

        self.max_chars_spin = QSpinBox()
        self.max_chars_spin.setRange(80, 1200)
        self.max_chars_spin.setValue(260)
        form.addRow("Max chars per chunk", self.max_chars_spin)

        self.priority_spin = QSpinBox()
        self.priority_spin.setRange(1, 100)
        self.priority_spin.setValue(50)
        form.addRow("Priority", self.priority_spin)

        self.keep_wav_checkbox = QCheckBox("Keep intermediate WAV files")
        form.addRow("", self.keep_wav_checkbox)

        right_layout.addLayout(form)

        buttons = QHBoxLayout()
        create_button = QPushButton("Create job")
        create_button.clicked.connect(self.create_job)
        buttons.addWidget(create_button)
        self.start_button = QPushButton("Start / Resume")
        self.start_button.clicked.connect(self.start_selected_job)
        buttons.addWidget(self.start_button)
        self.queue_button = QPushButton("Queue selected")
        self.queue_button.clicked.connect(self.queue_selected_job)
        buttons.addWidget(self.queue_button)
        self.stop_button = QPushButton("Stop")
        self.stop_button.clicked.connect(self.stop_current_job)
        buttons.addWidget(self.stop_button)
        self.priority_button = QPushButton("Apply priority")
        self.priority_button.clicked.connect(self.apply_priority_to_selected)
        buttons.addWidget(self.priority_button)
        voices_button = QPushButton("Reload voices")
        voices_button.clicked.connect(self.refresh_voice_list)
        buttons.addWidget(voices_button)
        right_layout.addLayout(buttons)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        right_layout.addWidget(self.progress_bar)

        self.status_label = QLabel("Idle")
        right_layout.addWidget(self.status_label)

        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        right_layout.addWidget(self.details)

        splitter.addWidget(right)
        splitter.setSizes([340, 940])

    def _wrap(self, layout: QHBoxLayout) -> QWidget:
        widget = QWidget()
        widget.setLayout(layout)
        return widget

    def refresh_voice_list(self) -> None:
        backend = PiperBackend(self.paths.runtime, self.paths.voices)
        voices = backend.installed_voices()
        self.voice_combo.clear()
        self.voice_combo.addItems(voices)
        self.logger.info("Loaded %s installed voices", len(voices))
        if not voices:
            self.status_label.setText(
                "No voices found. Run scripts/bootstrap_runtime.py or add voice files to voices/."
            )

    def refresh_jobs(self) -> None:
        self.jobs_list.clear()
        jobs = self.manager.list_jobs()
        self.logger.info("Refreshing jobs list with %s jobs", len(jobs))
        for job in jobs:
            label = (
                f"P{job.priority:02d} | {job.title} [{job.status}] "
                f"{job.completed_chunks}/{job.total_chunks}"
            )
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, job.job_id)
            self.jobs_list.addItem(item)

    def select_source_file(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Select source file",
            str(self.paths.root),
            "Books (*.txt *.pdf *.epub)",
        )
        if filename:
            self.source_edit.setText(filename)
            self.logger.info("Selected source file %s", filename)

    def create_job(self) -> None:
        source = Path(self.source_edit.text().strip())
        if not source.exists():
            QMessageBox.warning(self, "Missing file", "Select an existing TXT, PDF or EPUB file.")
            return
        voice_id = self.voice_combo.currentText().strip()
        if not voice_id:
            QMessageBox.warning(self, "Missing voice", "Install or select a Piper voice first.")
            return
        job = self.manager.create_job(
            source_path=source,
            voice_id=voice_id,
            priority=self.priority_spin.value(),
            max_chars=self.max_chars_spin.value(),
            output_mode=self.output_mode_combo.currentText(),
            keep_wav=self.keep_wav_checkbox.isChecked(),
        )
        self.current_job_id = job.job_id
        self.logger.info("Created job %s", job.job_id)
        self.refresh_jobs()
        self.show_job(job)

    def on_job_selected(self) -> None:
        item = self.jobs_list.currentItem()
        if not item:
            return
        job_id = item.data(Qt.UserRole)
        self.current_job_id = job_id
        self.logger.info("Selected job %s", job_id)
        self.show_job(self.manager.load_state(job_id))

    def show_job(self, job: JobState) -> None:
        self.status_label.setText(
            f"{job.status} | priority {job.priority} | chunks {job.completed_chunks}/{job.total_chunks} | voice {job.voice_id}"
        )
        self.progress_bar.setValue(
            int((job.completed_chunks / job.total_chunks) * 100) if job.total_chunks else 0
        )
        self.details.setPlainText("\n".join(job.logs[-200:]))
        self.priority_spin.setValue(job.priority)
        self.logger.debug("Displayed job %s with status %s", job.job_id, job.status)

    def start_selected_job(self) -> None:
        if not self.current_job_id:
            QMessageBox.warning(self, "No job", "Create or select a job first.")
            return
        self.manager.enqueue_job(self.current_job_id)
        self.logger.info("Start/resume requested for job %s", self.current_job_id)
        self.refresh_jobs()
        self.maybe_start_next_job()

    def queue_selected_job(self) -> None:
        if not self.current_job_id:
            QMessageBox.warning(self, "No job", "Select a job first.")
            return
        job = self.manager.enqueue_job(self.current_job_id)
        self.logger.info("Queue requested for job %s", self.current_job_id)
        self.refresh_jobs()
        self.show_job(job)
        self.maybe_start_next_job()

    def apply_priority_to_selected(self) -> None:
        if not self.current_job_id:
            QMessageBox.warning(self, "No job", "Select a job first.")
            return
        job = self.manager.update_priority(self.current_job_id, self.priority_spin.value())
        self.logger.info("Priority update requested for job %s", self.current_job_id)
        self.refresh_jobs()
        self.show_job(job)
        self.maybe_start_next_job()

    def maybe_start_next_job(self) -> None:
        if self.worker and self.worker.isRunning():
            return
        next_job = self.manager.next_queued_job()
        if not next_job:
            return
        self.current_job_id = next_job.job_id
        self.logger.info("Starting next queued job %s", next_job.job_id)
        self.worker = JobWorker(self.manager, next_job)
        self.worker.progress_changed.connect(self.on_progress_changed)
        self.worker.job_finished.connect(self.on_job_finished)
        self.worker.job_failed.connect(self.on_job_failed)
        self.worker.start()
        self.status_label.setText(f"running | {next_job.title}")

    def stop_current_job(self) -> None:
        if self.worker and self.worker.isRunning():
            self.worker.request_stop()
            self.status_label.setText("Stop requested")
            self.logger.warning("Stop requested for current running job")

    def on_progress_changed(self, current: int, total: int, message: str) -> None:
        self.progress_bar.setValue(int((current / total) * 100) if total else 0)
        self.status_label.setText(message)
        self.logger.debug("Progress update: %s/%s %s", current, total, message)

    def on_job_finished(self, state: JobState) -> None:
        self.refresh_jobs()
        self.show_job(state)
        self.logger.info("Job finished callback for %s with status %s", state.job_id, state.status)
        self.maybe_start_next_job()

    def on_job_failed(self, message: str) -> None:
        self.refresh_jobs()
        self.details.appendPlainText(message)
        self.status_label.setText("failed")
        self.logger.error("Job failed callback with traceback")
        self.maybe_start_next_job()

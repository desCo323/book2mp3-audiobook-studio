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
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from book2mp3.config import AppPaths
from book2mp3.models import JobState
from book2mp3.pipeline.jobs import JobManager
from book2mp3.preview_sessions import list_preview_sessions
from book2mp3.presets import QUALITY_PRESETS, get_preset
from book2mp3.tts.piper import PiperBackend
from book2mp3.ui.find_best_setting_dialog import FindBestSettingDialog
from book2mp3.ui.voice_lab_dialog import VoiceLabDialog
from book2mp3.ui.worker import JobWorker
from book2mp3.utils.logging_utils import get_logger
from book2mp3.voice_lab import list_voice_profiles

PREFERRED_VOICE_ORDER = [
    "de_DE-eva_k-x_low",
    "de_DE-kerstin-low",
    "de_DE-ramona-low",
    "en_US-amy-medium",
    "en_US-kathleen-low",
    "en_GB-alba-medium",
    "en_GB-cori-medium",
    "fr_FR-siwis-low",
]

BETA_STYLE = "background-color: #fff1cc; border: 1px solid #d18b00; color: #6b4b00;"
BETA_LABEL_STYLE = "color: #9a5c00; font-weight: bold;"


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
        tabs = QTabWidget()
        right_layout.addWidget(tabs)

        create_tab = QWidget()
        create_layout = QVBoxLayout(create_tab)

        help_label = QLabel(
            "Schnellstart:\n"
            "1. Quelle waehlen.\n"
            "2. Stimme und Preset waehlen.\n"
            "3. Job erzeugen.\n"
            "4. Mehrere Jobs koennen nacheinander in der Queue liegen.\n\n"
            "Tipp: Mit 'Find Best Setting' erzeugst du zuerst kurze Vergleichs-MP3s, "
            "bevor du das ganze Buch konvertierst."
        )
        help_label.setWordWrap(True)
        create_layout.addWidget(help_label)

        beta_legend = QLabel(
            "Orange markiert: vorbereitet oder beta, aber noch nicht komplett produktionsreif. "
            "Aktuell betrifft das XTTS und Custom-Voice-Funktionen."
        )
        beta_legend.setWordWrap(True)
        beta_legend.setStyleSheet(BETA_STYLE)
        create_layout.addWidget(beta_legend)

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

        self.backend_combo = QComboBox()
        self.backend_combo.addItems(["piper", "xtts"])
        self.backend_combo.currentIndexChanged.connect(self.on_backend_changed)
        form.addRow("Backend", self.backend_combo)

        self.backend_notice = QLabel(
            "XTTS ist noch beta. Der Standardpfad fuer sofort nutzbare Buchkonvertierung ist Piper."
        )
        self.backend_notice.setWordWrap(True)
        self.backend_notice.setStyleSheet(BETA_LABEL_STYLE)
        form.addRow("XTTS-Hinweis", self.backend_notice)

        self.voice_profile_combo = QComboBox()
        form.addRow("Voice profile", self.voice_profile_combo)

        self.preset_combo = QComboBox()
        for preset in QUALITY_PRESETS:
            self.preset_combo.addItem(f"{preset.label} ({preset.preset_id})", preset.preset_id)
        self.preset_combo.currentIndexChanged.connect(self.on_preset_changed)
        form.addRow("Qualitaets-Preset", self.preset_combo)

        self.preset_description = QLabel("")
        self.preset_description.setWordWrap(True)
        form.addRow("Preset-Info", self.preset_description)

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

        create_layout.addLayout(form)

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
        find_best_button = QPushButton("Find Best Setting")
        find_best_button.clicked.connect(self.open_find_best_setting)
        buttons.addWidget(find_best_button)
        self.voice_lab_button = QPushButton("Voice Lab (beta)")
        self.voice_lab_button.setStyleSheet(BETA_STYLE)
        self.voice_lab_button.clicked.connect(self.open_voice_lab)
        buttons.addWidget(self.voice_lab_button)
        create_layout.addLayout(buttons)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        create_layout.addWidget(self.progress_bar)

        self.status_label = QLabel("Idle")
        create_layout.addWidget(self.status_label)

        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        create_layout.addWidget(self.details)

        tabs.addTab(create_tab, "Jobs")

        queue_tab = QWidget()
        queue_layout = QVBoxLayout(queue_tab)
        queue_help = QLabel(
            "Die Queue ist persistent. Hohe Prioritaet wird zuerst abgearbeitet.\n"
            "Find-Best-Setting-Sessions tauchen hier ebenfalls auf, damit du spaeter "
            "wieder zu deinen Vergleichstests zurueckkehren kannst."
        )
        queue_help.setWordWrap(True)
        queue_layout.addWidget(queue_help)
        self.queue_details = QPlainTextEdit()
        self.queue_details.setReadOnly(True)
        self.queue_details.setPlaceholderText(
            "Hier steht die eigentliche Verarbeitungswarteschlange der Jobs."
        )
        queue_layout.addWidget(self.queue_details)
        self.preview_sessions_summary = QPlainTextEdit()
        self.preview_sessions_summary.setReadOnly(True)
        self.preview_sessions_summary.setPlaceholderText(
            "Hier stehen gespeicherte Preview-Sessions samt Anzahl der Tests und gewaehltem Favoriten."
        )
        queue_layout.addWidget(self.preview_sessions_summary)
        tabs.addTab(queue_tab, "Queue")

        splitter.addWidget(right)
        splitter.setSizes([340, 940])
        self.on_preset_changed()
        self.on_backend_changed()

    def _wrap(self, layout: QHBoxLayout) -> QWidget:
        widget = QWidget()
        widget.setLayout(layout)
        return widget

    def refresh_voice_list(self) -> None:
        backend = PiperBackend(self.paths.runtime, self.paths.voices)
        voices = backend.installed_voices()
        self.voice_combo.clear()
        if voices:
            self.voice_combo.addItems(voices)
        else:
            self.voice_combo.addItem("No voices found")
        self.refresh_voice_profiles()
        self.logger.info("Loaded %s installed voices", len(voices))
        for voice_id in PREFERRED_VOICE_ORDER:
            index = self.voice_combo.findText(voice_id)
            if index >= 0:
                self.voice_combo.setCurrentIndex(index)
                break
        if not voices:
            self.status_label.setText(
                f"No voices found. Checked voices in {self.paths.voices}. "
                "Run scripts/bootstrap_runtime.py or add voice files to voices/."
            )

    def refresh_voice_profiles(self) -> None:
        self.voice_profile_combo.clear()
        profiles = list_voice_profiles(self.paths.voice_profiles)
        if profiles:
            for profile in profiles:
                self.voice_profile_combo.addItem(
                    f"{profile.display_name} ({profile.target_language})",
                    profile.profile_id,
                )
        else:
            self.voice_profile_combo.addItem("No voice profiles found", "")

    def on_backend_changed(self) -> None:
        is_piper = self.backend_combo.currentText() == "piper"
        self.voice_combo.setEnabled(is_piper)
        self.voice_profile_combo.setEnabled(not is_piper)
        if is_piper:
            self.backend_combo.setStyleSheet("")
            self.voice_profile_combo.setStyleSheet("")
            self.backend_notice.hide()
        else:
            self.backend_combo.setStyleSheet(BETA_STYLE)
            self.voice_profile_combo.setStyleSheet(BETA_STYLE)
            self.backend_notice.show()

    def refresh_jobs(self) -> None:
        self.jobs_list.clear()
        jobs = self.manager.list_jobs()
        self.logger.info("Refreshing jobs list with %s jobs", len(jobs))
        queue_lines = []
        for job in jobs:
            label = (
                f"P{job.priority:02d} | {job.title} [{job.status}] "
                f"{job.completed_chunks}/{job.total_chunks}"
            )
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, job.job_id)
            self.jobs_list.addItem(item)
            queue_lines.append(
                f"P{job.priority:02d} | {job.status:9s} | {job.title} | preset={job.preset_id} | voice={job.voice_id}"
            )
        self.queue_details.setPlainText("\n".join(queue_lines) or "Keine Jobs in der Queue.")
        preview_lines = []
        for session in list_preview_sessions(self.paths):
            best = session.selected_case_index if session.selected_case_index is not None else "-"
            preview_lines.append(
                f"Preview {session.session_id} | tests={len(session.tests)} | best={best} | source={Path(session.source_file).name}"
            )
        self.preview_sessions_summary.setPlainText(
            "\n".join(preview_lines) or "Keine Find-Best-Setting-Sessions vorhanden."
        )

    def on_preset_changed(self) -> None:
        preset_id = self.preset_combo.currentData()
        preset = get_preset(preset_id)
        self.max_chars_spin.setValue(preset.max_chars)
        self.output_mode_combo.setCurrentText(preset.output_mode)
        self.keep_wav_checkbox.setChecked(preset.keep_wav)
        self.preset_description.setText(
            f"{preset.description} Satzpause: {preset.sentence_silence:.2f}s, Länge: {preset.length_scale:.2f}."
        )

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
        backend = self.backend_combo.currentText().strip()
        voice_profile_id = self.voice_profile_combo.currentData() or ""
        if backend == "piper":
            if not voice_id:
                QMessageBox.warning(self, "Missing voice", "Install or select a Piper voice first.")
                return
        else:
            if not voice_profile_id:
                QMessageBox.warning(
                    self,
                    "Missing voice profile",
                    "Create or select a Voice-Lab profile for XTTS first.",
                )
                return
        job = self.manager.create_job(
            source_path=source,
            voice_id=voice_id,
            voice_profile_id=voice_profile_id,
            preset_id=self.preset_combo.currentData(),
            priority=self.priority_spin.value(),
            max_chars=self.max_chars_spin.value(),
            output_mode=self.output_mode_combo.currentText(),
            keep_wav=self.keep_wav_checkbox.isChecked(),
            sentence_silence=get_preset(self.preset_combo.currentData()).sentence_silence,
            length_scale=get_preset(self.preset_combo.currentData()).length_scale,
            backend=backend,
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
            f"{job.status} | backend {job.backend} | priority {job.priority} | preset {job.preset_id} | chunks {job.completed_chunks}/{job.total_chunks} | voice {job.voice_id or job.voice_profile_id}"
        )
        self.progress_bar.setValue(
            int((job.completed_chunks / job.total_chunks) * 100) if job.total_chunks else 0
        )
        self.details.setPlainText("\n".join(job.logs[-200:]))
        self.priority_spin.setValue(job.priority)
        preset_index = self.preset_combo.findData(job.preset_id)
        if preset_index >= 0:
            self.preset_combo.setCurrentIndex(preset_index)
        backend_index = self.backend_combo.findText(job.backend)
        if backend_index >= 0:
            self.backend_combo.setCurrentIndex(backend_index)
        profile_index = self.voice_profile_combo.findData(job.voice_profile_id)
        if profile_index >= 0:
            self.voice_profile_combo.setCurrentIndex(profile_index)
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

    def open_voice_lab(self) -> None:
        dialog = VoiceLabDialog(self.paths, self)
        dialog.exec()

    def open_find_best_setting(self) -> None:
        dialog = FindBestSettingDialog(self.paths, self.manager, self)
        dialog.exec()
        self.refresh_jobs()

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

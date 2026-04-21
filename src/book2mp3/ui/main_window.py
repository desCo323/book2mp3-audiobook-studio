from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
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

from book2mp3.app_settings import AppSettings, load_app_settings, reset_workspace_state, save_app_settings
from book2mp3.config import AppPaths
from book2mp3.models import JobState
from book2mp3.pipeline.jobs import JobManager
from book2mp3.preview_sessions import list_preview_sessions, update_preview_job_status
from book2mp3.presets import QUALITY_PRESETS, get_preset
from book2mp3.tts.piper import PiperBackend
from book2mp3.tts.xtts import XttsBackend
from book2mp3.ui.find_best_setting_dialog import FindBestSettingDialog
from book2mp3.ui.voice_lab_dialog import VoiceLabDialog
from book2mp3.ui.worker import JobWorker
from book2mp3.utils.logging_utils import configure_logging, get_logger
from book2mp3.voice_catalog import (
    filter_voice_ids,
    format_voice_label,
    language_choices,
    voice_filter_empty_message,
    voice_language_code,
)
from book2mp3.xtts_speakers import auto_import_xtts_speakers, install_starter_xtts_profiles
from book2mp3.voice_lab import list_voice_profiles, load_voice_profile

BETA_STYLE = "background-color: #fff1cc; border: 1px solid #d18b00; color: #6b4b00;"
BETA_LABEL_STYLE = "color: #9a5c00; font-weight: bold;"


class MainWindow(QMainWindow):
    def __init__(self, paths: AppPaths) -> None:
        super().__init__()
        self.paths = paths
        self.app_settings = load_app_settings(paths.app_settings_file)
        self.manager = JobManager(paths)
        self.worker: JobWorker | None = None
        self.current_job_id: str | None = None
        self.logger = get_logger("ui")
        self.installed_voice_ids: list[str] = []
        self.xtts_backend = XttsBackend(paths.runtime, logger=self.logger)
        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_output)

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
        queue_button_row = QHBoxLayout()
        move_top_button = QPushButton("Ganz hoch")
        move_top_button.clicked.connect(lambda: self.move_selected_job("top"))
        queue_button_row.addWidget(move_top_button)
        move_up_button = QPushButton("Hoch")
        move_up_button.clicked.connect(lambda: self.move_selected_job("up"))
        queue_button_row.addWidget(move_up_button)
        move_down_button = QPushButton("Runter")
        move_down_button.clicked.connect(lambda: self.move_selected_job("down"))
        queue_button_row.addWidget(move_down_button)
        delete_button = QPushButton("Loeschen")
        delete_button.clicked.connect(self.delete_selected_job)
        queue_button_row.addWidget(delete_button)
        left_layout.addLayout(queue_button_row)
        refresh_button = QPushButton("Queue neu laden")
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
            "1. Buch waehlen.\n"
            "2. Stimme, Qualitaets-Preset und Ausgabeart festlegen.\n"
            "3. Job erzeugen.\n"
            "4. Links kannst du Jobs in der Queue verschieben oder loeschen.\n\n"
            "Tipp: 'Find Best Setting' ist der Live-Test fuer Stimme, Preset und Dateiausgabe."
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
        browse_button = QPushButton("Buch waehlen")
        browse_button.clicked.connect(self.select_source_file)
        source_row = QHBoxLayout()
        source_row.addWidget(self.source_edit)
        source_row.addWidget(browse_button)
        form.addRow("Quelle", self._wrap(source_row))

        self.voice_combo = QComboBox()
        form.addRow("Piper-Stimme", self.voice_combo)
        self.voice_language_combo = QComboBox()
        self.voice_language_combo.currentIndexChanged.connect(self.rebuild_voice_combo)
        form.addRow("Sprache", self.voice_language_combo)
        voice_filter_row = QHBoxLayout()
        self.voice_female_only_checkbox = QCheckBox("nur Frauenstimmen")
        self.voice_female_only_checkbox.toggled.connect(self.rebuild_voice_combo)
        voice_filter_row.addWidget(self.voice_female_only_checkbox)
        self.voice_high_only_checkbox = QCheckBox("nur high")
        self.voice_high_only_checkbox.toggled.connect(self.rebuild_voice_combo)
        voice_filter_row.addWidget(self.voice_high_only_checkbox)
        form.addRow("Piper-Filter", self._wrap(voice_filter_row))

        self.backend_combo = QComboBox()
        self.backend_combo.addItems(["piper", "xtts"])
        self.backend_combo.currentIndexChanged.connect(self.on_backend_changed)
        form.addRow("Backend", self.backend_combo)

        self.backend_notice = QLabel(
            "XTTS ist der natuerlichere Pfad, wenn gute Sprecherprofile vorhanden sind. "
            "Piper bleibt der einfache Offline-Fallback."
        )
        self.backend_notice.setWordWrap(True)
        self.backend_notice.setStyleSheet(BETA_LABEL_STYLE)
        form.addRow("XTTS-Hinweis", self.backend_notice)

        self.backend_summary = QLabel("")
        self.backend_summary.setWordWrap(True)
        form.addRow("Backend-Status", self.backend_summary)

        self.voice_profile_combo = QComboBox()
        self.voice_profile_combo.currentIndexChanged.connect(self.refresh_selected_voice_profile)
        form.addRow("XTTS-Profil", self.voice_profile_combo)
        self.voice_profile_hint = QLabel("")
        self.voice_profile_hint.setWordWrap(True)
        form.addRow("XTTS-Profile", self.voice_profile_hint)
        self.xtts_scan_hint = QLabel("")
        self.xtts_scan_hint.setWordWrap(True)
        form.addRow("XTTS-Suche", self.xtts_scan_hint)
        self.voice_profile_details = QLabel("")
        self.voice_profile_details.setWordWrap(True)
        form.addRow("Profil-Info", self.voice_profile_details)
        xtts_profile_row = QHBoxLayout()
        xtts_preview_button = QPushButton("XTTS-Referenz hoeren")
        xtts_preview_button.clicked.connect(self.preview_xtts_reference)
        xtts_profile_row.addWidget(xtts_preview_button)
        xtts_open_button = QPushButton("Profilordner oeffnen")
        xtts_open_button.clicked.connect(self.open_xtts_profile_folder)
        xtts_profile_row.addWidget(xtts_open_button)
        form.addRow("", self._wrap(xtts_profile_row))

        self.preset_combo = QComboBox()
        for preset in QUALITY_PRESETS:
            self.preset_combo.addItem(f"{preset.label} ({preset.preset_id})", preset.preset_id)
        self.preset_combo.currentIndexChanged.connect(self.on_preset_changed)
        form.addRow("Qualitaets-Preset", self.preset_combo)

        self.preset_description = QLabel("")
        self.preset_description.setWordWrap(True)
        form.addRow("Preset-Info", self.preset_description)

        self.output_mode_combo = QComboBox()
        self.output_mode_combo.addItem("Eine grosse Enddatei", "single_file")
        self.output_mode_combo.addItem("Enddateien alle X Minuten", "timed_parts")
        self.output_mode_combo.addItem("Nur kleine Teil-MP3s behalten", "segments")
        form.addRow("Finale Ausgabe", self.output_mode_combo)

        self.target_part_minutes_spin = QSpinBox()
        self.target_part_minutes_spin.setRange(1, 180)
        self.target_part_minutes_spin.setValue(15)
        self.target_part_minutes_spin.setSuffix(" min")
        form.addRow("Laenge pro Enddatei", self.target_part_minutes_spin)

        self.max_chars_spin = QSpinBox()
        self.max_chars_spin.setRange(80, 1200)
        self.max_chars_spin.setValue(260)
        form.addRow("Max Zeichen pro Chunk", self.max_chars_spin)

        self.priority_spin = QSpinBox()
        self.priority_spin.setRange(1, 100)
        self.priority_spin.setValue(50)
        form.addRow("Prioritaet", self.priority_spin)

        self.keep_wav_checkbox = QCheckBox("Zwischen-WAV-Dateien behalten")
        form.addRow("Debug-Dateien", self.keep_wav_checkbox)

        self.debug_logging_checkbox = QCheckBox("Sehr detailiertes Debug-Logging")
        self.debug_logging_checkbox.setChecked(self.app_settings.debug_logging)
        self.debug_logging_checkbox.toggled.connect(self.toggle_debug_logging)
        form.addRow("Logging", self.debug_logging_checkbox)

        create_layout.addLayout(form)

        buttons = QHBoxLayout()
        create_button = QPushButton("Job erzeugen")
        create_button.clicked.connect(self.create_job)
        buttons.addWidget(create_button)
        self.start_button = QPushButton("Start / Resume")
        self.start_button.clicked.connect(self.start_selected_job)
        buttons.addWidget(self.start_button)
        self.queue_button = QPushButton("In Queue")
        self.queue_button.clicked.connect(self.queue_selected_job)
        buttons.addWidget(self.queue_button)
        self.stop_button = QPushButton("Stop")
        self.stop_button.clicked.connect(self.stop_current_job)
        buttons.addWidget(self.stop_button)
        self.priority_button = QPushButton("Prioritaet anwenden")
        self.priority_button.clicked.connect(self.apply_priority_to_selected)
        buttons.addWidget(self.priority_button)
        voices_button = QPushButton("Stimmen neu laden")
        voices_button.clicked.connect(self.refresh_voice_list)
        buttons.addWidget(voices_button)
        find_best_button = QPushButton("Find Best Setting")
        find_best_button.clicked.connect(self.open_find_best_setting)
        buttons.addWidget(find_best_button)
        self.voice_lab_button = QPushButton("Voice Lab (beta)")
        self.voice_lab_button.setStyleSheet(BETA_STYLE)
        self.voice_lab_button.clicked.connect(self.open_voice_lab)
        buttons.addWidget(self.voice_lab_button)
        xtts_import_button = QPushButton("XTTS-Sprecher")
        xtts_import_button.setStyleSheet(BETA_STYLE)
        xtts_import_button.clicked.connect(self.import_or_open_xtts)
        buttons.addWidget(xtts_import_button)
        xtts_starter_button = QPushButton("XTTS-Starter")
        xtts_starter_button.setStyleSheet(BETA_STYLE)
        xtts_starter_button.clicked.connect(self.install_xtts_starters)
        buttons.addWidget(xtts_starter_button)
        reset_button = QPushButton("Standard-Einstellungen / Reset")
        reset_button.clicked.connect(self.reset_application_state)
        buttons.addWidget(reset_button)
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
            "Links kannst du Jobs hoch, runter oder ganz nach oben schieben und bei Bedarf loeschen.\n"
            "Voice-Tuning-Sessions tauchen hier ebenfalls auf, damit du spaeter "
            "zu deinen gespeicherten Stellen und Preview-Renders zurueckkehren kannst."
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
            "Hier stehen gespeicherte Voice-Tuning-Sessions mit letzter Preview und gespeichertem Setting."
        )
        queue_layout.addWidget(self.preview_sessions_summary)
        tabs.addTab(queue_tab, "Queue")

        splitter.addWidget(right)
        splitter.setSizes([340, 940])
        self.apply_default_controls()
        self.on_preset_changed()
        self.on_backend_changed()

    def _wrap(self, layout: QHBoxLayout) -> QWidget:
        widget = QWidget()
        widget.setLayout(layout)
        return widget

    def refresh_voice_list(self) -> None:
        backend = PiperBackend(self.paths.runtime, self.paths.voices)
        self.installed_voice_ids = backend.installed_voices()
        self.voice_language_combo.blockSignals(True)
        self.voice_language_combo.clear()
        for code, label in language_choices(self.installed_voice_ids):
            self.voice_language_combo.addItem(label, code)
        self.voice_language_combo.blockSignals(False)
        self.rebuild_voice_combo()
        self.refresh_voice_profiles()
        self.logger.info("Loaded %s installed voices", len(self.installed_voice_ids))
        self.update_backend_summary()
        if not self.installed_voice_ids:
            self.status_label.setText(
                f"No voices found. Checked voices in {self.paths.voices}. "
                "Run scripts/bootstrap_runtime.py or add voice files to voices/."
            )

    def rebuild_voice_combo(self) -> None:
        selected_voice_id = self.voice_combo.currentData() or self.voice_combo.currentText().strip()
        language_code = self.voice_language_combo.currentData() or ""
        visible_voices = filter_voice_ids(
            self.installed_voice_ids,
            language_code,
            female_only=self.voice_female_only_checkbox.isChecked(),
            high_only=self.voice_high_only_checkbox.isChecked(),
        )
        self.voice_combo.clear()
        if visible_voices:
            for voice_id in visible_voices:
                self.voice_combo.addItem(format_voice_label(voice_id), voice_id)
            selected_index = self.voice_combo.findData(selected_voice_id)
            self.voice_combo.setCurrentIndex(selected_index if selected_index >= 0 else 0)
        else:
            self.voice_combo.addItem(
                voice_filter_empty_message(
                    language_code,
                    female_only=self.voice_female_only_checkbox.isChecked(),
                    high_only=self.voice_high_only_checkbox.isChecked(),
                ),
                "",
            )

    def refresh_voice_profiles(self) -> None:
        self.voice_profile_combo.clear()
        profiles = list_voice_profiles(self.paths.voice_profiles)
        if profiles:
            for profile in profiles:
                self.voice_profile_combo.addItem(
                    f"{profile.target_language} | {profile.display_name}",
                    profile.profile_id,
                )
            self.voice_profile_hint.setText(
                f"{len(profiles)} XTTS-Profile verfuegbar. Gute Resultate haengen von den Referenzsamples ab."
            )
            self.xtts_scan_hint.setText("XTTS-Profile vorhanden. Du kannst direkt mit XTTS arbeiten.")
        else:
            self.voice_profile_combo.addItem("No voice profiles found", "")
            self.voice_profile_hint.setText(
                "Keine XTTS-Profile vorhanden. Importiere einen xtts-webui speakers-Ordner oder erstelle ein Voice-Lab-Profil."
            )
            self.xtts_scan_hint.setText(
                "Nutze 'XTTS-Sprecher' fuer Auto-Import alter WebUI-Ordner oder 'XTTS-Starter' fuer sofort nutzbare Beispielsprecher."
            )
            self.voice_profile_details.setText("Noch kein XTTS-Profil ausgewaehlt.")
        self.refresh_selected_voice_profile()
        self.update_backend_summary()

    def refresh_selected_voice_profile(self) -> None:
        profile_id = self.voice_profile_combo.currentData() or ""
        if not profile_id:
            self.voice_profile_details.setText("Noch kein XTTS-Profil ausgewaehlt.")
            return
        try:
            profile = load_voice_profile(self.paths.voice_profiles, profile_id)
        except FileNotFoundError:
            self.voice_profile_details.setText("XTTS-Profil konnte nicht geladen werden.")
            return
        sample_count = len(profile.samples)
        first_sample = Path(profile.samples[0]).name if profile.samples else "-"
        warnings = "; ".join(profile.validation_warnings[:2]) if profile.validation_warnings else "keine"
        self.voice_profile_details.setText(
            f"{profile.display_name} | Sprache {profile.target_language} | Samples {sample_count} | "
            f"erstes Sample {first_sample} | Warnungen {warnings}"
        )

    def on_backend_changed(self) -> None:
        is_piper = self.backend_combo.currentText() == "piper"
        self.voice_combo.setEnabled(is_piper)
        self.voice_language_combo.setEnabled(is_piper)
        self.voice_profile_combo.setEnabled(not is_piper)
        if is_piper:
            self.backend_combo.setStyleSheet("")
            self.voice_profile_combo.setStyleSheet("")
            self.backend_notice.hide()
            if self.preset_combo.currentData() == "premium_natural":
                fallback_index = self.preset_combo.findData("natural")
                if fallback_index >= 0:
                    self.preset_combo.setCurrentIndex(fallback_index)
        else:
            if not self.xtts_backend.is_available():
                QMessageBox.warning(
                    self,
                    "XTTS runtime fehlt",
                    self.xtts_backend.availability_reason(),
                )
                fallback_index = self.backend_combo.findText("piper")
                if fallback_index >= 0:
                    self.backend_combo.setCurrentIndex(fallback_index)
                return
            self.backend_combo.setStyleSheet(BETA_STYLE)
            self.voice_profile_combo.setStyleSheet(BETA_STYLE)
            self.backend_notice.show()
            if self.preset_combo.currentData() in {"fast_cpu", "balanced", "natural"}:
                xtts_index = self.preset_combo.findData("premium_natural")
                if xtts_index >= 0:
                    self.preset_combo.setCurrentIndex(xtts_index)
        self.update_backend_summary()

    def update_backend_summary(self) -> None:
        profile_count = max(0, self.voice_profile_combo.count() - (1 if self.voice_profile_combo.itemData(0) == "" else 0))
        if self.backend_combo.currentText() == "xtts":
            if not self.xtts_backend.is_available():
                self.backend_summary.setText(f"XTTS nicht bereit. {self.xtts_backend.availability_reason()}")
                return
            self.backend_summary.setText(
                f"XTTS: {profile_count} Sprecherprofile verfuegbar. "
                "Empfohlen: Preset 'Premium Natuerlich' und ein gutes WebUI-/Voice-Lab-Profil."
            )
        else:
            self.backend_summary.setText(
                f"Piper: {len(self.installed_voice_ids)} Offline-Stimmen verfuegbar. "
                "Empfohlen fuer schnelle lokale Verarbeitung ohne XTTS-Runtime."
            )

    def apply_default_controls(self) -> None:
        preset_index = self.preset_combo.findData(self.app_settings.default_preset_id)
        if preset_index >= 0:
            self.preset_combo.setCurrentIndex(preset_index)
        mode_index = self.output_mode_combo.findData(self.app_settings.default_output_mode)
        if mode_index >= 0:
            self.output_mode_combo.setCurrentIndex(mode_index)
        self.target_part_minutes_spin.setValue(self.app_settings.default_target_part_minutes)
        self.keep_wav_checkbox.setChecked(self.app_settings.default_keep_wav)
        self.max_chars_spin.setValue(self.app_settings.default_max_chars)
        self.priority_spin.setValue(self.app_settings.default_priority)

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
                f"P{job.priority:02d} | {job.status:9s} | {job.title} | preset={job.preset_id} | "
                f"output={job.output_mode} | ziel={job.target_part_minutes}m | voice={job.voice_id or job.voice_profile_id}"
            )
        self.queue_details.setPlainText("\n".join(queue_lines) or "Keine Jobs in der Queue.")
        preview_lines = []
        for session in list_preview_sessions(self.paths):
            preview_lines.append(
                f"Tuning {session.session_id} | backend={session.backend} | "
                f"voice={session.voice_id or session.voice_profile_id or '-'} | "
                f"preview={session.last_preview_status} | setting={session.saved_setting_id or '-'} | "
                f"source={Path(session.source_file).name}"
            )
        self.preview_sessions_summary.setPlainText(
            "\n".join(preview_lines) or "Keine Find-Best-Setting-Sessions vorhanden."
        )

    def on_preset_changed(self) -> None:
        preset_id = self.preset_combo.currentData()
        preset = get_preset(preset_id)
        self.max_chars_spin.setValue(preset.max_chars)
        output_mode_index = self.output_mode_combo.findData(preset.output_mode)
        if output_mode_index >= 0:
            self.output_mode_combo.setCurrentIndex(output_mode_index)
        self.target_part_minutes_spin.setValue(preset.target_part_minutes)
        self.keep_wav_checkbox.setChecked(preset.keep_wav)
        if self.backend_combo.currentText() == "xtts":
            self.preset_description.setText(
                f"{preset.description} XTTS nutzt vor allem Chunk-Laenge und Sprechtempo. "
                f"Enddateien: {preset.output_mode}, Ziel {preset.target_part_minutes} min."
            )
        else:
            self.preset_description.setText(
                f"{preset.description} Satzpause: {preset.sentence_silence:.2f}s, Laenge: {preset.length_scale:.2f}, "
                f"Enddateien: {preset.output_mode}, Ziel {preset.target_part_minutes} min."
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
        voice_id = self.voice_combo.currentData() or self.voice_combo.currentText().strip()
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
            if not self.xtts_backend.is_available():
                QMessageBox.warning(
                    self,
                    "XTTS runtime fehlt",
                    self.xtts_backend.availability_reason(),
                )
                return
        job = self.manager.create_job(
            source_path=source,
            voice_id=voice_id,
            voice_profile_id=voice_profile_id,
            preset_id=self.preset_combo.currentData(),
            priority=self.priority_spin.value(),
            max_chars=self.max_chars_spin.value(),
            output_mode=self.output_mode_combo.currentData(),
            target_part_minutes=self.target_part_minutes_spin.value(),
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
            f"{job.status} | backend {job.backend} | priority {job.priority} | preset {job.preset_id} | "
            f"output {job.output_mode} | ziel {job.target_part_minutes}m | chunks {job.completed_chunks}/{job.total_chunks} | "
            f"voice {job.voice_id or job.voice_profile_id}"
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
        if job.voice_id:
            language_index = self.voice_language_combo.findData(voice_language_code(job.voice_id))
            if language_index >= 0:
                self.voice_language_combo.setCurrentIndex(language_index)
        voice_index = self.voice_combo.findData(job.voice_id)
        if voice_index >= 0:
            self.voice_combo.setCurrentIndex(voice_index)
        output_mode_index = self.output_mode_combo.findData(job.output_mode)
        if output_mode_index >= 0:
            self.output_mode_combo.setCurrentIndex(output_mode_index)
        self.target_part_minutes_spin.setValue(job.target_part_minutes)
        self.keep_wav_checkbox.setChecked(job.keep_wav)
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

    def move_selected_job(self, direction: str) -> None:
        if not self.current_job_id:
            QMessageBox.warning(self, "Kein Job", "Bitte zuerst einen Job auswaehlen.")
            return
        job = self.manager.move_job(self.current_job_id, direction)
        if not job:
            return
        self.refresh_jobs()
        self.show_job(job)
        self.maybe_start_next_job()

    def delete_selected_job(self) -> None:
        if not self.current_job_id:
            QMessageBox.warning(self, "Kein Job", "Bitte zuerst einen Job auswaehlen.")
            return
        job_id = self.current_job_id
        job = self.manager.load_state(job_id)
        if job.status == "running":
            QMessageBox.warning(self, "Job laeuft", "Einen laufenden Job bitte erst stoppen, bevor du ihn loeschst.")
            return
        answer = QMessageBox.question(
            self,
            "Job loeschen",
            "Soll der ausgewaehlte Job inklusive Arbeitsdateien wirklich geloescht werden?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.manager.delete_job(job_id)
        self.current_job_id = None
        self.refresh_jobs()
        self.status_label.setText("Job geloescht.")

    def toggle_debug_logging(self, checked: bool) -> None:
        self.app_settings.debug_logging = checked
        save_app_settings(self.paths.app_settings_file, self.app_settings)
        configure_logging(self.paths.logs, debug_enabled=checked)
        self.status_label.setText(
            "Debug-Logging aktiv. Jeder Schritt wird sehr detailiert protokolliert."
            if checked
            else "Debug-Logging reduziert. Nur wichtigere Infos und Fehler werden protokolliert."
        )

    def reset_application_state(self) -> None:
        if self.worker and self.worker.isRunning():
            QMessageBox.warning(self, "Job laeuft", "Bitte zuerst den aktuellen Job stoppen, bevor du alles zuruecksetzt.")
            return
        answer = QMessageBox.question(
            self,
            "Alles zuruecksetzen",
            "Soll die App auf Start zurueckgesetzt werden? Dabei werden Jobs, Voice-Settings, Vorschau-Sessions, Logs und Voice-Profile geloescht.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        default_settings = AppSettings()
        save_app_settings(self.paths.app_settings_file, default_settings)
        self.app_settings = default_settings
        reset_workspace_state(self.paths.workspace)
        configure_logging(self.paths.logs, debug_enabled=self.app_settings.debug_logging, force_reset=True)
        self.manager = JobManager(self.paths)
        self.current_job_id = None
        self.debug_logging_checkbox.setChecked(self.app_settings.debug_logging)
        self.source_edit.clear()
        self.apply_default_controls()
        self.details.clear()
        self.queue_details.clear()
        self.preview_sessions_summary.clear()
        self.status_label.setText("App auf Standard zurueckgesetzt.")
        self.refresh_voice_profiles()
        self.refresh_jobs()

    def open_voice_lab(self) -> None:
        dialog = VoiceLabDialog(self.paths, self)
        dialog.exec()
        self.refresh_voice_profiles()

    def import_or_open_xtts(self) -> None:
        source_root, manifests = auto_import_xtts_speakers(self.paths, fallback_language="de")
        self.refresh_voice_profiles()
        if manifests:
            self.status_label.setText(f"XTTS-Sprecher importiert: {len(manifests)} aus {source_root}")
            self.xtts_scan_hint.setText(f"Gefunden und importiert aus: {source_root}")
            backend_index = self.backend_combo.findText("xtts")
            if backend_index >= 0:
                self.backend_combo.setCurrentIndex(backend_index)
            return
        starter_manifests = install_starter_xtts_profiles(self.paths)
        self.refresh_voice_profiles()
        if starter_manifests:
            self.status_label.setText(f"XTTS-Starter installiert: {len(starter_manifests)} Profile")
            self.xtts_scan_hint.setText("Keine Altinstallation gefunden. XTTS-Starterprofile wurden stattdessen installiert.")
            backend_index = self.backend_combo.findText("xtts")
            if backend_index >= 0:
                self.backend_combo.setCurrentIndex(backend_index)
            return
        self.xtts_scan_hint.setText(
            "Kein befuellter XTTS speakers-Ordner gefunden und keine Starterprofile installiert. Oeffne Voice Lab fuer Details und manuelle Auswahl."
        )
        self.open_voice_lab()

    def install_xtts_starters(self) -> None:
        manifests = install_starter_xtts_profiles(self.paths)
        self.refresh_voice_profiles()
        if manifests:
            self.status_label.setText(f"XTTS-Starter installiert: {len(manifests)}")
            self.xtts_scan_hint.setText("XTTS-Starterprofile sind jetzt verfuegbar.")
            backend_index = self.backend_combo.findText("xtts")
            if backend_index >= 0:
                self.backend_combo.setCurrentIndex(backend_index)
            return
        self.status_label.setText("XTTS-Starter waren bereits installiert.")
        self.xtts_scan_hint.setText("XTTS-Starterprofile sind bereits vorhanden.")

    def preview_xtts_reference(self) -> None:
        profile_id = self.voice_profile_combo.currentData() or ""
        if not profile_id:
            QMessageBox.warning(self, "Kein XTTS-Profil", "Bitte zuerst ein XTTS-Profil auswaehlen.")
            return
        profile = load_voice_profile(self.paths.voice_profiles, profile_id)
        if not profile.samples:
            QMessageBox.warning(self, "Keine Samples", "Dieses XTTS-Profil hat keine Referenzsamples.")
            return
        sample_path = Path(profile.samples[0])
        if not sample_path.exists():
            QMessageBox.warning(self, "Sample fehlt", f"Referenzsample nicht gefunden: {sample_path}")
            return
        self.player.setSource(QUrl.fromLocalFile(str(sample_path)))
        self.player.play()
        self.status_label.setText(f"Spiele XTTS-Referenzsample: {sample_path.name}")

    def open_xtts_profile_folder(self) -> None:
        profile_id = self.voice_profile_combo.currentData() or ""
        if not profile_id:
            QMessageBox.warning(self, "Kein XTTS-Profil", "Bitte zuerst ein XTTS-Profil auswaehlen.")
            return
        profile_dir = self.paths.voice_profiles / profile_id
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(profile_dir)))

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
        update_preview_job_status(
            self.paths,
            state.job_id,
            state.status,
            state.final_output_file if Path(state.final_output_file).exists() else None,
        )
        self.refresh_jobs()
        self.show_job(state)
        self.logger.info("Job finished callback for %s with status %s", state.job_id, state.status)
        self.maybe_start_next_job()

    def on_job_failed(self, message: str) -> None:
        if self.current_job_id:
            update_preview_job_status(self.paths, self.current_job_id, "failed")
        self.refresh_jobs()
        self.details.appendPlainText(message)
        self.status_label.setText("failed")
        self.logger.error("Job failed callback with traceback")
        self.maybe_start_next_job()

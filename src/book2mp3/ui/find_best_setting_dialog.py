from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from book2mp3.config import AppPaths
from book2mp3.pipeline.jobs import JobManager
from book2mp3.preview_sessions import (
    attach_preview_job,
    create_preview_session,
    refresh_preview_excerpt,
    link_saved_setting,
    list_preview_sessions,
)
from book2mp3.presets import get_preset
from book2mp3.tts.piper import PiperBackend
from book2mp3.utils.logging_utils import get_logger
from book2mp3.voice_settings import list_voice_settings, load_voice_setting, save_voice_setting


class FindBestSettingDialog(QDialog):
    def __init__(self, paths: AppPaths, manager: JobManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.paths = paths
        self.manager = manager
        self.logger = get_logger("find_best_setting")
        self.current_source: Path | None = None
        self.current_session_id: str | None = None
        self.installed_voices: list[str] = []

        self.setWindowTitle("Voice Tuning")
        self.resize(1100, 760)
        self._build_ui()
        self.refresh_voice_list()
        self.refresh_saved_settings()
        self.refresh_sessions()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        intro = QLabel(
            "Waehle ein Buch, lass eine zufaellige Stelle ziehen und tune Stimme und Vorleseparameter "
            "direkt an dieser Stelle. Mit 'Neue Stelle' bekommst du sofort einen anderen Ausschnitt."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        howto = QLabel(
            "So benutzt du diesen Modus:\n"
            "1. Buchquelle waehlen.\n"
            "2. Session erzeugen.\n"
            "3. Mit Stimme, Chunk-Laenge, Satzpause und Sprechtempo experimentieren.\n"
            "4. Preview rendern.\n"
            "5. Gutes Ergebnis als Voice-Setting speichern.\n\n"
            "Empfohlene Startwerte:\n"
            "- Roman natuerlich: 240-280 Zeichen, Satzpause 0.24-0.32s, Laenge 1.02-1.08\n"
            "- Standard ausgewogen: 200-240 Zeichen, Satzpause 0.18-0.24s, Laenge 0.98-1.03\n"
            "- Schnell fuer CPU: 150-190 Zeichen, Satzpause 0.10-0.16s, Laenge 0.92-0.98"
        )
        howto.setWordWrap(True)
        layout.addWidget(howto)

        controls = QHBoxLayout()
        self.source_label = QLabel("Keine Quelle gewaehlt")
        controls.addWidget(self.source_label)
        choose_source = QPushButton("Quelle waehlen")
        choose_source.clicked.connect(self.select_source)
        controls.addWidget(choose_source)
        create_session = QPushButton("Session erzeugen")
        create_session.clicked.connect(self.create_session)
        controls.addWidget(create_session)
        new_excerpt = QPushButton("Neue Stelle")
        new_excerpt.clicked.connect(self.new_excerpt)
        controls.addWidget(new_excerpt)
        render_preview = QPushButton("Preview rendern")
        render_preview.clicked.connect(self.render_preview)
        controls.addWidget(render_preview)
        save_setting = QPushButton("Als Voice-Setting speichern")
        save_setting.clicked.connect(self.save_setting)
        controls.addWidget(save_setting)
        layout.addLayout(controls)

        rows = QHBoxLayout()
        self.sessions_list = QListWidget()
        self.sessions_list.itemSelectionChanged.connect(self.on_session_selected)
        rows.addWidget(self.sessions_list)

        center = QVBoxLayout()
        form = QFormLayout()
        self.voice_combo = QComboBox()
        form.addRow("Stimme", self.voice_combo)
        self.preset_combo = QComboBox()
        for preset_id in ["fast_cpu", "balanced", "natural"]:
            preset = get_preset(preset_id)
            self.preset_combo.addItem(preset.label, preset.preset_id)
        self.preset_combo.currentIndexChanged.connect(self.apply_preset_hint)
        form.addRow("Preset-Hilfe", self.preset_combo)

        self.max_chars_spin = QSpinBox()
        self.max_chars_spin.setRange(100, 450)
        self.max_chars_spin.setSingleStep(10)
        self.max_chars_spin.setValue(220)
        self.max_chars_spin.valueChanged.connect(self.update_helper_text)
        form.addRow("Max chars per chunk", self.max_chars_spin)

        self.sentence_slider = QSlider(Qt.Horizontal)
        self.sentence_slider.setRange(5, 60)
        self.sentence_slider.setValue(20)
        self.sentence_slider.valueChanged.connect(self.update_helper_text)
        form.addRow("Satzpause", self.sentence_slider)
        self.sentence_label = QLabel("0.20s")
        form.addRow("", self.sentence_label)

        self.length_slider = QSlider(Qt.Horizontal)
        self.length_slider.setRange(85, 120)
        self.length_slider.setValue(100)
        self.length_slider.valueChanged.connect(self.update_helper_text)
        form.addRow("Sprechlaenge", self.length_slider)
        self.length_label = QLabel("1.00")
        form.addRow("", self.length_label)

        self.setting_name = QLineEdit()
        self.setting_name.setPlaceholderText("z. B. Roman warm langsam")
        form.addRow("Setting-Name", self.setting_name)

        self.saved_settings_combo = QComboBox()
        form.addRow("Gespeicherte Settings", self.saved_settings_combo)
        load_setting = QPushButton("Setting laden")
        load_setting.clicked.connect(self.load_setting)
        form.addRow("", load_setting)

        center.addLayout(form)
        self.helper_label = QLabel("")
        self.helper_label.setWordWrap(True)
        center.addWidget(self.helper_label)

        self.excerpt_view = QPlainTextEdit()
        self.excerpt_view.setReadOnly(True)
        self.excerpt_view.setPlaceholderText("Hier erscheint die zufaellige Buchstelle.")
        center.addWidget(self.excerpt_view)
        rows.addLayout(center)
        layout.addLayout(rows)

        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setPlaceholderText(
            "Hier siehst du Session-, Preview- und Setting-Details."
        )
        layout.addWidget(self.details)
        self.apply_preset_hint()

    def refresh_voice_list(self) -> None:
        self.installed_voices = PiperBackend(self.paths.runtime, self.paths.voices).installed_voices()
        self.voice_combo.clear()
        for voice_id in self.installed_voices:
            self.voice_combo.addItem(voice_id, voice_id)

    def refresh_saved_settings(self) -> None:
        self.saved_settings_combo.clear()
        for setting in list_voice_settings(self.paths.voice_settings):
            self.saved_settings_combo.addItem(setting.display_name, setting.setting_id)

    def select_source(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Buchquelle fuer Voice-Tuning auswaehlen",
            str(self.paths.root),
            "Books (*.txt *.pdf *.epub)",
        )
        if filename:
            self.current_source = Path(filename)
            self.source_label.setText(filename)

    def refresh_sessions(self) -> None:
        self.sessions_list.clear()
        for session in list_preview_sessions(self.paths):
            item = QListWidgetItem(f"{session.title} [{session.session_id}]")
            item.setData(32, session.session_id)
            self.sessions_list.addItem(item)

    def create_session(self) -> None:
        if not self.current_source or not self.current_source.exists():
            QMessageBox.warning(self, "Keine Quelle", "Bitte zuerst eine Buchquelle auswaehlen.")
            return
        if not self.installed_voices:
            QMessageBox.warning(
                self,
                "Keine Stimmen",
                f"Es wurden keine Piper-Stimmen gefunden.\nGepruefter Ordner: {self.paths.voices}",
            )
            return
        session = create_preview_session(self.paths, self.current_source)
        self.logger.info("Created preview session %s", session.session_id)
        self.refresh_sessions()
        self.current_session_id = session.session_id
        self.show_session(session.session_id)

    def on_session_selected(self) -> None:
        item = self.sessions_list.currentItem()
        if not item:
            return
        session_id = item.data(32)
        self.current_session_id = session_id
        self.show_session(session_id)

    def show_session(self, session_id: str) -> None:
        sessions = {session.session_id: session for session in list_preview_sessions(self.paths)}
        session = sessions[session_id]
        self.excerpt_view.setPlainText(session.preview_excerpt)
        voice_index = self.voice_combo.findData(session.voice_id)
        if voice_index >= 0:
            self.voice_combo.setCurrentIndex(voice_index)
        preset_index = self.preset_combo.findData(session.preset_hint)
        if preset_index >= 0:
            self.preset_combo.setCurrentIndex(preset_index)
        self.details.setPlainText(
            json.dumps(asdict(session), indent=2, ensure_ascii=False)
        )

    def new_excerpt(self) -> None:
        if not self.current_session_id:
            QMessageBox.warning(self, "Keine Session", "Bitte zuerst eine Session erzeugen oder auswaehlen.")
            return
        session = refresh_preview_excerpt(self.paths, self.current_session_id)
        self.show_session(session.session_id)

    def apply_preset_hint(self) -> None:
        preset = get_preset(self.preset_combo.currentData())
        self.max_chars_spin.setValue(preset.max_chars)
        self.sentence_slider.setValue(int(round(preset.sentence_silence * 100)))
        self.length_slider.setValue(int(round(preset.length_scale * 100)))
        self.update_helper_text()

    def update_helper_text(self) -> None:
        sentence_silence = self.sentence_slider.value() / 100
        length_scale = self.length_slider.value() / 100
        max_chars = self.max_chars_spin.value()
        self.sentence_label.setText(f"{sentence_silence:.2f}s")
        self.length_label.setText(f"{length_scale:.2f}")
        if max_chars >= 240 and sentence_silence >= 0.24 and length_scale >= 1.02:
            hint = "Empfehlung: gut fuer ruhige, natuerliche Romanstimmen."
        elif max_chars <= 190 and sentence_silence <= 0.16 and length_scale <= 0.98:
            hint = "Empfehlung: gut fuer schnelle CPU-Previews und kuerzere Sachtexte."
        else:
            hint = "Empfehlung: guter Allround-Bereich fuer die meisten Hoerbuecher."
        self.helper_label.setText(
            f"{hint}\nAktuell: {max_chars} Zeichen, {sentence_silence:.2f}s Satzpause, {length_scale:.2f} Laenge."
        )

    def render_preview(self) -> None:
        if not self.current_session_id:
            QMessageBox.warning(self, "Keine Session", "Bitte zuerst eine Session erzeugen oder auswaehlen.")
            return
        voice_id = self.voice_combo.currentData() or self.voice_combo.currentText().strip()
        if not voice_id:
            QMessageBox.warning(self, "Keine Stimme", "Bitte eine Stimme auswaehlen.")
            return
        sessions = {session.session_id: session for session in list_preview_sessions(self.paths)}
        session = sessions[self.current_session_id]
        preset_hint = self.preset_combo.currentData()
        job = self.manager.create_job(
            source_path=Path(session.preview_source_file),
            voice_id=voice_id,
            voice_profile_id="",
            preset_id=preset_hint,
            priority=98,
            max_chars=self.max_chars_spin.value(),
            output_mode="single_file",
            keep_wav=False,
            sentence_silence=self.sentence_slider.value() / 100,
            length_scale=self.length_slider.value() / 100,
        )
        session = attach_preview_job(
            self.paths,
            session.session_id,
            voice_id,
            preset_hint,
            job.job_id,
            job.final_output_file,
            "queued",
        )
        self.show_session(session.session_id)
        parent = self.parent()
        if parent and hasattr(parent, "refresh_jobs"):
            parent.refresh_jobs()
        if parent and hasattr(parent, "maybe_start_next_job"):
            parent.maybe_start_next_job()
        QMessageBox.information(
            self,
            "Preview gestartet",
            "Die Preview wurde in die Queue gelegt und wird direkt verarbeitet.",
        )

    def save_setting(self) -> None:
        voice_id = self.voice_combo.currentData() or self.voice_combo.currentText().strip()
        if not voice_id:
            QMessageBox.warning(self, "Keine Stimme", "Bitte zuerst eine Stimme auswaehlen.")
            return
        display_name = self.setting_name.text().strip() or f"{voice_id}_{self.preset_combo.currentData()}"
        setting = save_voice_setting(
            self.paths.voice_settings,
            display_name=display_name,
            voice_id=voice_id,
            preset_hint=self.preset_combo.currentData(),
            max_chars=self.max_chars_spin.value(),
            sentence_silence=self.sentence_slider.value() / 100,
            length_scale=self.length_slider.value() / 100,
            notes="Gespeichert aus Voice Tuning",
        )
        self.refresh_saved_settings()
        if self.current_session_id:
            link_saved_setting(self.paths, self.current_session_id, setting.setting_id)
            self.show_session(self.current_session_id)
        QMessageBox.information(self, "Setting gespeichert", f"Voice-Setting '{setting.display_name}' gespeichert.")

    def load_setting(self) -> None:
        setting_id = self.saved_settings_combo.currentData()
        if not setting_id:
            QMessageBox.warning(self, "Kein Setting", "Bitte ein gespeichertes Voice-Setting auswaehlen.")
            return
        setting = load_voice_setting(self.paths.voice_settings, setting_id)
        voice_index = self.voice_combo.findData(setting.voice_id)
        if voice_index >= 0:
            self.voice_combo.setCurrentIndex(voice_index)
        preset_index = self.preset_combo.findData(setting.preset_hint)
        if preset_index >= 0:
            self.preset_combo.setCurrentIndex(preset_index)
        self.max_chars_spin.setValue(setting.max_chars)
        self.sentence_slider.setValue(int(round(setting.sentence_silence * 100)))
        self.length_slider.setValue(int(round(setting.length_scale * 100)))
        self.setting_name.setText(setting.display_name)
        self.update_helper_text()

from __future__ import annotations

import json
import traceback
import uuid
from pathlib import Path

from PySide6.QtCore import QThread, Qt, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
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
from book2mp3.pipeline.audio import concat_mp3_files, wav_to_mp3
from book2mp3.pipeline.chunking import split_text
from book2mp3.preview_sessions import (
    attach_preview_job,
    create_preview_session,
    link_saved_setting,
    list_preview_sessions,
    refresh_preview_excerpt,
    update_preview_selection,
)
from book2mp3.tts.piper import PiperBackend
from book2mp3.tts.xtts import XttsBackend
from book2mp3.ui.voice_lab_dialog import VoiceLabDialog
from book2mp3.utils.logging_utils import get_logger
from book2mp3.voice_catalog import (
    filter_voice_ids,
    format_voice_label,
    language_choices,
    voice_language_code,
)
from book2mp3.voice_lab import list_voice_profiles, load_voice_profile
from book2mp3.voice_settings import list_voice_settings, save_voice_setting


class LivePreviewWorker(QThread):
    preview_finished = Signal(str, str)
    preview_failed = Signal(str)

    def __init__(
        self,
        paths: AppPaths,
        session_id: str,
        backend: str,
        voice_id: str,
        voice_profile_id: str,
        max_chars: int,
        sentence_silence: float,
        length_scale: float,
    ) -> None:
        super().__init__()
        self.paths = paths
        self.session_id = session_id
        self.backend = backend
        self.voice_id = voice_id
        self.voice_profile_id = voice_profile_id
        self.max_chars = max_chars
        self.sentence_silence = sentence_silence
        self.length_scale = length_scale
        self.logger = get_logger("live_preview")

    def run(self) -> None:
        try:
            session = {item.session_id: item for item in list_preview_sessions(self.paths)}[self.session_id]
            preview_root = self.paths.preview_sessions / self.session_id / "live_preview"
            wav_root = preview_root / "wav"
            mp3_root = preview_root / "mp3"
            wav_root.mkdir(parents=True, exist_ok=True)
            mp3_root.mkdir(parents=True, exist_ok=True)

            text = Path(session.preview_source_file).read_text(encoding="utf-8")
            chunks = split_text(text, self.max_chars)
            piper_backend = PiperBackend(self.paths.runtime, self.paths.voices, logger=self.logger)
            xtts_backend = XttsBackend(self.paths.runtime, logger=self.logger)
            mp3_files: list[Path] = []

            for index, chunk in enumerate(chunks, start=1):
                wav_path = wav_root / f"{index:03d}.wav"
                mp3_path = mp3_root / f"{index:03d}.mp3"
                if self.backend == "piper":
                    piper_backend.synthesize_to_wav(
                        chunk,
                        self.voice_id,
                        wav_path,
                        sentence_silence=self.sentence_silence,
                        length_scale=self.length_scale,
                    )
                else:
                    profile = load_voice_profile(self.paths.voice_profiles, self.voice_profile_id)
                    xtts_backend.synthesize_to_wav(
                        chunk,
                        profile,
                        wav_path,
                        length_scale=self.length_scale,
                    )
                wav_to_mp3(wav_path, mp3_path, logger=self.logger)
                mp3_files.append(mp3_path)

            final_mp3 = preview_root / "preview.mp3"
            concat_mp3_files(mp3_files, final_mp3, logger=self.logger)
            preview_job_id = f"live_{uuid.uuid4().hex[:10]}"
            attach_preview_job(
                self.paths,
                self.session_id,
                self.backend,
                self.voice_id,
                self.voice_profile_id,
                "live_tuning",
                preview_job_id,
                str(final_mp3),
                "completed",
            )
            self.preview_finished.emit(self.session_id, str(final_mp3))
        except Exception:
            self.logger.exception("Live preview render failed")
            self.preview_failed.emit(traceback.format_exc())


class FindBestSettingDialog(QDialog):
    def __init__(self, paths: AppPaths, manager: object, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.paths = paths
        self.logger = get_logger("find_best_setting")
        self.current_source: Path | None = None
        self.current_session_id: str | None = None
        self.installed_voices: list[str] = []
        self.preview_worker: LivePreviewWorker | None = None
        self.xtts_backend = XttsBackend(paths.runtime, logger=self.logger)

        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_output)

        self.setWindowTitle("Voice Tuning")
        self.resize(1040, 780)
        self._build_ui()
        self.refresh_voice_list()
        self.refresh_voice_profiles()
        self.restore_last_session()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        intro = QLabel(
            "Einfach ausprobieren: Buch waehlen, zufaellige Stelle hoeren, Backend waehlen, Regler anpassen "
            "und sofort pruefen wie es klingt. XTTS nutzt importierte Sprecherprofile und klingt oft natuerlicher."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        source_row = QHBoxLayout()
        self.source_label = QLabel("Keine Quelle gewaehlt")
        self.source_label.setWordWrap(True)
        source_row.addWidget(self.source_label)
        source_button = QPushButton("Buch waehlen")
        source_button.clicked.connect(self.select_source)
        source_row.addWidget(source_button)
        new_excerpt_button = QPushButton("Neue Stelle")
        new_excerpt_button.clicked.connect(self.new_excerpt)
        source_row.addWidget(new_excerpt_button)
        import_xtts_button = QPushButton("XTTS-Sprecher importieren")
        import_xtts_button.clicked.connect(self.open_voice_lab)
        source_row.addWidget(import_xtts_button)
        layout.addLayout(source_row)

        form = QFormLayout()
        self.backend_combo = QComboBox()
        self.backend_combo.addItems(["piper", "xtts"])
        self.backend_combo.currentIndexChanged.connect(self.on_backend_changed)
        form.addRow("Backend", self.backend_combo)

        self.voice_combo = QComboBox()
        form.addRow("Piper-Stimme", self.voice_combo)
        self.voice_language_combo = QComboBox()
        self.voice_language_combo.currentIndexChanged.connect(self.rebuild_voice_combo)
        form.addRow("Piper-Sprache", self.voice_language_combo)

        self.voice_profile_combo = QComboBox()
        self.voice_profile_combo.currentIndexChanged.connect(self.refresh_selected_voice_profile)
        form.addRow("XTTS-Profil", self.voice_profile_combo)
        self.voice_profile_details = QLabel("")
        self.voice_profile_details.setWordWrap(True)
        form.addRow("Profil-Info", self.voice_profile_details)
        xtts_profile_row = QHBoxLayout()
        preview_reference_button = QPushButton("Referenzsample hoeren")
        preview_reference_button.clicked.connect(self.preview_xtts_reference)
        xtts_profile_row.addWidget(preview_reference_button)
        open_profile_button = QPushButton("Profilordner oeffnen")
        open_profile_button.clicked.connect(self.open_xtts_profile_folder)
        xtts_profile_row.addWidget(open_profile_button)
        form.addRow("", self._wrap(xtts_profile_row))

        self.assistant_combo = QComboBox()
        self.assistant_combo.addItem("Roman / Story", "novel")
        self.assistant_combo.addItem("Sachbuch / Klar", "nonfiction")
        self.assistant_combo.addItem("Kinderbuch / Warm", "children")
        self.assistant_combo.addItem("Schnell / CPU", "cpu")
        form.addRow("Schnellhilfe", self.assistant_combo)
        assistant_button = QPushButton("Optimale Startwerte")
        assistant_button.clicked.connect(self.apply_assistant_profile)
        form.addRow("", assistant_button)

        self.max_chars_spin = QSpinBox()
        self.max_chars_spin.setRange(100, 450)
        self.max_chars_spin.setSingleStep(10)
        self.max_chars_spin.setValue(220)
        self.max_chars_spin.valueChanged.connect(self.update_helper_text)
        form.addRow("Chunk-Laenge", self.max_chars_spin)

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
        form.addRow("Tempo / Laenge", self.length_slider)
        self.length_label = QLabel("1.00")
        form.addRow("", self.length_label)

        self.setting_name = QLineEdit()
        self.setting_name.setPlaceholderText("z. B. Roman warm langsam")
        form.addRow("Voice-Setting Name", self.setting_name)
        layout.addLayout(form)

        self.helper_label = QLabel("")
        self.helper_label.setWordWrap(True)
        layout.addWidget(self.helper_label)

        self.excerpt_view = QPlainTextEdit()
        self.excerpt_view.setReadOnly(True)
        self.excerpt_view.setPlaceholderText("Hier erscheint automatisch eine zufaellige Stelle aus dem Buch.")
        layout.addWidget(self.excerpt_view)

        button_row = QHBoxLayout()
        self.play_now_button = QPushButton("Play Preview jetzt")
        self.play_now_button.clicked.connect(self.render_and_play_preview)
        button_row.addWidget(self.play_now_button)
        play_last_button = QPushButton("Letzte Preview abspielen")
        play_last_button.clicked.connect(self.play_last_preview)
        button_row.addWidget(play_last_button)
        stop_button = QPushButton("Stop")
        stop_button.clicked.connect(self.stop_playback)
        button_row.addWidget(stop_button)
        save_setting_button = QPushButton("Voice-Setting speichern")
        save_setting_button.clicked.connect(self.save_setting)
        button_row.addWidget(save_setting_button)
        load_last_button = QPushButton("Letztes Setting laden")
        load_last_button.clicked.connect(self.load_latest_setting)
        button_row.addWidget(load_last_button)
        layout.addLayout(button_row)

        self.status_label = QLabel("Noch keine Preview gerendert.")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setPlaceholderText("Hier stehen kurze Tuning-Infos zur aktuellen Stelle.")
        layout.addWidget(self.details)

        self.apply_assistant_profile()
        self.on_backend_changed()

    def refresh_voice_list(self) -> None:
        self.installed_voices = PiperBackend(self.paths.runtime, self.paths.voices).installed_voices()
        self.voice_language_combo.blockSignals(True)
        self.voice_language_combo.clear()
        for code, label in language_choices(self.installed_voices):
            self.voice_language_combo.addItem(label, code)
        self.voice_language_combo.blockSignals(False)
        self.rebuild_voice_combo()

    def refresh_voice_profiles(self) -> None:
        selected_profile_id = self.voice_profile_combo.currentData() or ""
        profiles = list_voice_profiles(self.paths.voice_profiles)
        self.voice_profile_combo.clear()
        if profiles:
            for profile in profiles:
                self.voice_profile_combo.addItem(
                    f"{profile.target_language} | {profile.display_name}",
                    profile.profile_id,
                )
            selected_index = self.voice_profile_combo.findData(selected_profile_id)
            self.voice_profile_combo.setCurrentIndex(selected_index if selected_index >= 0 else 0)
        else:
            self.voice_profile_combo.addItem("Keine XTTS-Profile gefunden", "")
        self.refresh_selected_voice_profile()

    def refresh_selected_voice_profile(self) -> None:
        profile_id = self.voice_profile_combo.currentData() or ""
        if not profile_id:
            self.voice_profile_details.setText("Noch kein XTTS-Profil ausgewaehlt.")
            return
        profile = load_voice_profile(self.paths.voice_profiles, profile_id)
        sample_count = len(profile.samples)
        first_sample = Path(profile.samples[0]).name if profile.samples else "-"
        warnings = "; ".join(profile.validation_warnings[:2]) if profile.validation_warnings else "keine"
        self.voice_profile_details.setText(
            f"{profile.display_name} | Sprache {profile.target_language} | Samples {sample_count} | "
            f"erstes Sample {first_sample} | Warnungen {warnings}"
        )

    def rebuild_voice_combo(self) -> None:
        selected_voice_id = self.voice_combo.currentData() or self.voice_combo.currentText().strip()
        language_code = self.voice_language_combo.currentData() or ""
        visible_voices = filter_voice_ids(self.installed_voices, language_code)
        self.voice_combo.clear()
        for voice_id in visible_voices:
            self.voice_combo.addItem(format_voice_label(voice_id), voice_id)
        if visible_voices:
            selected_index = self.voice_combo.findData(selected_voice_id)
            self.voice_combo.setCurrentIndex(selected_index if selected_index >= 0 else 0)

    def on_backend_changed(self) -> None:
        is_piper = self.backend_combo.currentText() == "piper"
        self.voice_combo.setEnabled(is_piper)
        self.voice_language_combo.setEnabled(is_piper)
        self.voice_profile_combo.setEnabled(not is_piper)
        if is_piper:
            self.status_label.setText("Piper aktiv: schnell und offline, aber oft synthetischer.")
        else:
            if not self.xtts_backend.is_available():
                self.status_label.setText(f"XTTS nicht bereit: {self.xtts_backend.availability_reason()}")
            else:
                self.status_label.setText("XTTS aktiv: bessere Chance auf natuerlichen Klang mit guten Sprecherprofilen.")

    def restore_last_session(self) -> None:
        sessions = list_preview_sessions(self.paths)
        if sessions:
            self.current_session_id = sessions[0].session_id
            self.current_source = Path(sessions[0].source_file)
            self.source_label.setText(str(self.current_source))
            self.show_session(sessions[0].session_id)

    def select_source(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Buch fuer Voice-Tuning waehlen",
            str(self.paths.root),
            "Books (*.txt *.pdf *.epub)",
        )
        if not filename:
            return
        self.current_source = Path(filename)
        self.source_label.setText(filename)
        self.create_session()

    def create_session(self) -> None:
        if not self.current_source or not self.current_source.exists():
            QMessageBox.warning(self, "Keine Quelle", "Bitte zuerst ein Buch waehlen.")
            return
        if not self.installed_voices and not list_voice_profiles(self.paths.voice_profiles):
            QMessageBox.warning(
                self,
                "Keine Stimmen",
                "Es wurden weder Piper-Stimmen noch XTTS-Profile gefunden.",
            )
            return
        session = create_preview_session(self.paths, self.current_source)
        self.current_session_id = session.session_id
        self.show_session(session.session_id)

    def show_session(self, session_id: str) -> None:
        session = {item.session_id: item for item in list_preview_sessions(self.paths)}[session_id]
        self.current_session_id = session_id
        self.excerpt_view.setPlainText(session.preview_excerpt)

        backend_index = self.backend_combo.findText(session.backend)
        if backend_index >= 0:
            self.backend_combo.setCurrentIndex(backend_index)
        if session.voice_id:
            language_index = self.voice_language_combo.findData(voice_language_code(session.voice_id))
            if language_index >= 0:
                self.voice_language_combo.setCurrentIndex(language_index)
            voice_index = self.voice_combo.findData(session.voice_id)
            if voice_index >= 0:
                self.voice_combo.setCurrentIndex(voice_index)
        if session.voice_profile_id:
            profile_index = self.voice_profile_combo.findData(session.voice_profile_id)
            if profile_index >= 0:
                self.voice_profile_combo.setCurrentIndex(profile_index)

        info_lines = [
            f"Quelle: {Path(session.source_file).name}",
            f"Stelle ab Textposition: {session.excerpt_offset}",
            f"Backend: {session.backend}",
            f"Letzte Preview: {session.last_preview_status}",
        ]
        if session.voice_id:
            info_lines.append(f"Piper-Stimme: {session.voice_id}")
        if session.voice_profile_id:
            info_lines.append(f"XTTS-Profil: {session.voice_profile_id}")
        if session.last_preview_output:
            info_lines.append(f"Datei: {Path(session.last_preview_output).name}")
        if session.saved_setting_id:
            info_lines.append(f"Gespeichertes Setting: {session.saved_setting_id}")
        self.details.setPlainText("\n".join(info_lines))

    def new_excerpt(self) -> None:
        if not self.current_session_id:
            QMessageBox.warning(self, "Keine Session", "Bitte zuerst ein Buch waehlen.")
            return
        session = refresh_preview_excerpt(self.paths, self.current_session_id)
        self.show_session(session.session_id)

    def apply_assistant_profile(self) -> None:
        profile = self.assistant_combo.currentData()
        presets = {
            "novel": (260, 28, 105, "Gut fuer natuerliche Romanstimmen mit mehr Ruhe."),
            "nonfiction": (220, 20, 100, "Gut fuer klare, neutrale Sachbuchstimmen."),
            "children": (240, 30, 103, "Gut fuer warme, etwas ruhigere Kinderbuchstimmen."),
            "cpu": (170, 12, 95, "Gut fuer schnelle Vorschauen auf CPU-Systemen."),
        }
        max_chars, sentence_pause, length_scale, note = presets[profile]
        self.max_chars_spin.setValue(max_chars)
        self.sentence_slider.setValue(sentence_pause)
        self.length_slider.setValue(length_scale)
        self.update_helper_text()
        self.status_label.setText(f"Assistent aktiv: {note}")

    def update_helper_text(self) -> None:
        sentence_silence = self.sentence_slider.value() / 100
        length_scale = self.length_slider.value() / 100
        max_chars = self.max_chars_spin.value()
        self.sentence_label.setText(f"{sentence_silence:.2f}s")
        self.length_label.setText(f"{length_scale:.2f}")
        if self.backend_combo.currentText() == "xtts":
            hint = "XTTS: gute Referenzsamples sind wichtiger als die letzten Regler-Prozent."
        elif max_chars >= 240 and sentence_silence >= 0.24 and length_scale >= 1.02:
            hint = "Eher natuerlich und ruhiger."
        elif max_chars <= 190 and sentence_silence <= 0.16 and length_scale <= 0.98:
            hint = "Eher schnell und CPU-freundlich."
        else:
            hint = "Eher ausgewogen fuer die meisten Hoerbuecher."
        self.helper_label.setText(
            f"{hint}\nAktuell: {max_chars} Zeichen, {sentence_silence:.2f}s Satzpause, {length_scale:.2f} Laenge."
        )

    def render_and_play_preview(self) -> None:
        if not self.current_session_id:
            QMessageBox.warning(self, "Keine Session", "Bitte zuerst ein Buch waehlen.")
            return
        if self.preview_worker and self.preview_worker.isRunning():
            QMessageBox.warning(self, "Preview laeuft", "Bitte kurz warten, die aktuelle Preview wird noch erzeugt.")
            return

        backend = self.backend_combo.currentText().strip()
        voice_id = ""
        voice_profile_id = ""
        if backend == "piper":
            voice_id = self.voice_combo.currentData() or self.voice_combo.currentText().strip()
            if not voice_id:
                QMessageBox.warning(self, "Keine Stimme", "Bitte zuerst eine Stimme auswaehlen.")
                return
        else:
            voice_profile_id = self.voice_profile_combo.currentData() or ""
            if not voice_profile_id:
                QMessageBox.warning(
                    self,
                    "Kein XTTS-Profil",
                    "Bitte zuerst ein XTTS-Sprecherprofil waehlen oder importieren.",
                )
                return
            if not self.xtts_backend.is_available():
                QMessageBox.warning(
                    self,
                    "XTTS runtime fehlt",
                    self.xtts_backend.availability_reason(),
                )
                return

        self.status_label.setText("Preview wird direkt erzeugt...")
        self.play_now_button.setEnabled(False)
        update_preview_selection(
            self.paths,
            self.current_session_id,
            backend,
            voice_id,
            voice_profile_id,
        )
        self.preview_worker = LivePreviewWorker(
            self.paths,
            self.current_session_id,
            backend,
            voice_id,
            voice_profile_id,
            self.max_chars_spin.value(),
            self.sentence_slider.value() / 100,
            self.length_slider.value() / 100,
        )
        self.preview_worker.preview_finished.connect(self.on_preview_finished)
        self.preview_worker.preview_failed.connect(self.on_preview_failed)
        self.preview_worker.start()

    def on_preview_finished(self, session_id: str, output_mp3: str) -> None:
        self.play_now_button.setEnabled(True)
        self.show_session(session_id)
        self.player.setSource(QUrl.fromLocalFile(output_mp3))
        self.player.play()
        self.status_label.setText(f"Preview fertig und wird abgespielt: {Path(output_mp3).name}")

    def on_preview_failed(self, message: str) -> None:
        self.play_now_button.setEnabled(True)
        if self.current_session_id:
            attach_preview_job(
                self.paths,
                self.current_session_id,
                self.backend_combo.currentText().strip(),
                self.voice_combo.currentData() or self.voice_combo.currentText().strip(),
                self.voice_profile_combo.currentData() or "",
                "live_tuning",
                f"live_failed_{uuid.uuid4().hex[:10]}",
                "",
                "failed",
            )
        self.status_label.setText("Preview fehlgeschlagen.")
        self.details.setPlainText(message)
        QMessageBox.warning(self, "Preview fehlgeschlagen", "Die Preview konnte nicht erzeugt werden. Details stehen unten.")

    def play_last_preview(self) -> None:
        if not self.current_session_id:
            QMessageBox.warning(self, "Keine Session", "Bitte zuerst ein Buch waehlen.")
            return
        session = {item.session_id: item for item in list_preview_sessions(self.paths)}[self.current_session_id]
        preview_file = Path(session.last_preview_output) if session.last_preview_output else None
        if not preview_file or not preview_file.exists():
            QMessageBox.warning(self, "Keine Preview", "Es gibt noch keine fertige Preview-MP3.")
            return
        self.player.setSource(QUrl.fromLocalFile(str(preview_file)))
        self.player.play()
        self.status_label.setText(f"Spiele letzte Preview ab: {preview_file.name}")

    def preview_xtts_reference(self) -> None:
        profile_id = self.voice_profile_combo.currentData() or ""
        if not profile_id:
            QMessageBox.warning(self, "Kein XTTS-Profil", "Bitte zuerst ein XTTS-Profil waehlen.")
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
        self.status_label.setText(f"Spiele XTTS-Referenzsample ab: {sample_path.name}")

    def open_xtts_profile_folder(self) -> None:
        profile_id = self.voice_profile_combo.currentData() or ""
        if not profile_id:
            QMessageBox.warning(self, "Kein XTTS-Profil", "Bitte zuerst ein XTTS-Profil waehlen.")
            return
        from PySide6.QtGui import QDesktopServices

        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.paths.voice_profiles / profile_id)))

    def stop_playback(self) -> None:
        self.player.stop()
        self.status_label.setText("Wiedergabe gestoppt.")

    def save_setting(self) -> None:
        backend = self.backend_combo.currentText().strip()
        voice_id = self.voice_combo.currentData() or self.voice_combo.currentText().strip()
        voice_profile_id = self.voice_profile_combo.currentData() or ""
        if backend == "piper" and not voice_id:
            QMessageBox.warning(self, "Keine Stimme", "Bitte zuerst eine Stimme auswaehlen.")
            return
        if backend == "xtts" and not voice_profile_id:
            QMessageBox.warning(self, "Kein XTTS-Profil", "Bitte zuerst ein XTTS-Sprecherprofil waehlen.")
            return

        display_name = self.setting_name.text().strip() or f"{(voice_id or voice_profile_id)}_live"
        setting = save_voice_setting(
            self.paths.voice_settings,
            display_name=display_name,
            backend=backend,
            voice_id=voice_id,
            voice_profile_id=voice_profile_id,
            preset_hint="live_tuning",
            max_chars=self.max_chars_spin.value(),
            sentence_silence=self.sentence_slider.value() / 100,
            length_scale=self.length_slider.value() / 100,
            notes="Gespeichert aus Live Voice Tuning",
        )
        if self.current_session_id:
            update_preview_selection(
                self.paths,
                self.current_session_id,
                backend,
                voice_id,
                voice_profile_id,
            )
            link_saved_setting(self.paths, self.current_session_id, setting.setting_id)
            self.show_session(self.current_session_id)
        self.status_label.setText(f"Voice-Setting gespeichert: {setting.display_name}")

    def load_latest_setting(self) -> None:
        settings = list_voice_settings(self.paths.voice_settings)
        if not settings:
            QMessageBox.warning(self, "Keine Settings", "Es gibt noch kein gespeichertes Voice-Setting.")
            return
        setting = settings[0]
        backend_index = self.backend_combo.findText(setting.backend)
        if backend_index >= 0:
            self.backend_combo.setCurrentIndex(backend_index)
        if setting.voice_id:
            language_index = self.voice_language_combo.findData(voice_language_code(setting.voice_id))
            if language_index >= 0:
                self.voice_language_combo.setCurrentIndex(language_index)
            voice_index = self.voice_combo.findData(setting.voice_id)
            if voice_index >= 0:
                self.voice_combo.setCurrentIndex(voice_index)
        if setting.voice_profile_id:
            profile_index = self.voice_profile_combo.findData(setting.voice_profile_id)
            if profile_index >= 0:
                self.voice_profile_combo.setCurrentIndex(profile_index)
        self.max_chars_spin.setValue(setting.max_chars)
        self.sentence_slider.setValue(int(round(setting.sentence_silence * 100)))
        self.length_slider.setValue(int(round(setting.length_scale * 100)))
        self.setting_name.setText(setting.display_name)
        self.update_helper_text()
        self.status_label.setText(f"Letztes Voice-Setting geladen: {setting.display_name}")

    def open_voice_lab(self) -> None:
        dialog = VoiceLabDialog(self.paths, self)
        dialog.exec()
        self.refresh_voice_profiles()

    def _wrap(self, layout: QHBoxLayout) -> QWidget:
        widget = QWidget()
        widget.setLayout(layout)
        return widget

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from book2mp3.config import AppPaths
from book2mp3.utils.logging_utils import get_logger
from book2mp3.voice_lab import create_voice_profile


class VoiceLabDialog(QDialog):
    def __init__(self, paths: AppPaths, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.paths = paths
        self.logger = get_logger("voice_lab")
        self.sample_paths: list[Path] = []

        self.setWindowTitle("Voice Lab")
        self.resize(760, 560)
        self._build_ui()
        self.refresh_existing_profiles()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        intro = QLabel(
            "Lege hier neue Sprecherprofile fuer kuenftiges Voice Cloning an. "
            "Die erste Version speichert Referenzsamples, Metadaten und Validierungshinweise. "
            "XTTS nutzt diese Profile spaeter direkt fuer Voice Cloning."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        form = QFormLayout()
        self.name_edit = QLineEdit()
        form.addRow("Name", self.name_edit)
        self.language_combo = QComboBox()
        self.language_combo.addItems(["de", "en", "fr", "es", "it", "nl", "pl"])
        form.addRow("Zielsprache", self.language_combo)
        self.backend_combo = QComboBox()
        self.backend_combo.addItems(["xtts_v2", "custom_pipeline_planned"])
        form.addRow("Backend", self.backend_combo)
        layout.addLayout(form)

        sample_row = QHBoxLayout()
        add_samples_button = QPushButton("Samples hinzufuegen")
        add_samples_button.clicked.connect(self.add_samples)
        sample_row.addWidget(add_samples_button)
        clear_samples_button = QPushButton("Samples leeren")
        clear_samples_button.clicked.connect(self.clear_samples)
        sample_row.addWidget(clear_samples_button)
        layout.addLayout(sample_row)

        self.samples_list = QListWidget()
        layout.addWidget(self.samples_list)

        self.notes_edit = QPlainTextEdit()
        self.notes_edit.setPlaceholderText(
            "Notizen, Zielstimme, Aufnahmeumgebung, Stil, Besonderheiten."
        )
        layout.addWidget(self.notes_edit)

        action_row = QHBoxLayout()
        save_button = QPushButton("Profil speichern")
        save_button.clicked.connect(self.save_profile)
        action_row.addWidget(save_button)
        refresh_button = QPushButton("Profile neu laden")
        refresh_button.clicked.connect(self.refresh_existing_profiles)
        action_row.addWidget(refresh_button)
        layout.addLayout(action_row)

        self.profile_list = QListWidget()
        layout.addWidget(self.profile_list)

        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        layout.addWidget(self.details)

    def add_samples(self) -> None:
        filenames, _ = QFileDialog.getOpenFileNames(
            self,
            "Referenzsamples waehlen",
            str(self.paths.root),
            "Audio (*.wav *.mp3 *.flac *.ogg *.m4a *.aac)",
        )
        for filename in filenames:
            path = Path(filename)
            if path not in self.sample_paths:
                self.sample_paths.append(path)
                self.samples_list.addItem(str(path))

    def clear_samples(self) -> None:
        self.sample_paths.clear()
        self.samples_list.clear()

    def save_profile(self) -> None:
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Fehlender Name", "Bitte einen Profilnamen eintragen.")
            return
        if not self.sample_paths:
            QMessageBox.warning(self, "Keine Samples", "Bitte mindestens ein Referenzsample hinzufuegen.")
            return
        manifest = create_voice_profile(
            self.paths.voice_profiles,
            display_name=name,
            target_language=self.language_combo.currentText(),
            backend=self.backend_combo.currentText(),
            notes=self.notes_edit.toPlainText().strip(),
            sample_paths=self.sample_paths,
        )
        self.logger.info("Saved voice profile %s", manifest)
        self.refresh_existing_profiles()
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        self.details.setPlainText(json.dumps(payload, indent=2, ensure_ascii=False))
        QMessageBox.information(
            self,
            "Profil gespeichert",
            "Voice-Lab-Profil gespeichert. Der XTTS-Backend-Schritt kann darauf spaeter aufbauen.",
        )

    def refresh_existing_profiles(self) -> None:
        self.profile_list.clear()
        profiles = sorted(self.paths.voice_profiles.glob("*/profile.json"))
        for profile in profiles:
            self.profile_list.addItem(profile.parent.name)
        self.details.setPlainText(
            "Vorhandene Voice-Lab-Profile werden unter workspace/voice_profiles gespeichert."
        )

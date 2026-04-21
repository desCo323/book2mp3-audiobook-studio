from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
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
from book2mp3.xtts_speakers import (
    auto_import_xtts_speakers,
    describe_candidate_speaker_roots,
    import_xtts_webui_speakers,
    install_starter_xtts_profiles,
)
from book2mp3.utils.logging_utils import get_logger
from book2mp3.voice_lab import create_voice_profile, load_voice_profile

BETA_STYLE = "background-color: #fff1cc; border: 1px solid #d18b00; color: #6b4b00;"
BETA_LABEL_STYLE = "color: #9a5c00; font-weight: bold;"


class VoiceLabDialog(QDialog):
    def __init__(self, paths: AppPaths, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.paths = paths
        self.logger = get_logger("voice_lab")
        self.sample_paths: list[Path] = []
        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_output)

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
        intro.setStyleSheet(BETA_STYLE)
        layout.addWidget(intro)

        self.beta_notice = QLabel(
            "Orange markiert: vorbereitet, aber noch nicht vollstaendig produktionsreif. "
            "XTTS/Custom-Voice-Profile sind noch ein Beta-Pfad."
        )
        self.beta_notice.setWordWrap(True)
        self.beta_notice.setStyleSheet(BETA_LABEL_STYLE)
        layout.addWidget(self.beta_notice)

        form = QFormLayout()
        self.name_edit = QLineEdit()
        form.addRow("Name", self.name_edit)
        self.language_combo = QComboBox()
        self.language_combo.addItems(["de", "en", "fr", "es", "it", "nl", "pl"])
        form.addRow("Zielsprache", self.language_combo)
        self.backend_combo = QComboBox()
        self.backend_combo.addItems(["xtts_v2 (beta)", "custom_pipeline_planned (not available)"])
        self.backend_combo.setStyleSheet(BETA_STYLE)
        form.addRow("Backend", self.backend_combo)
        layout.addLayout(form)

        sample_row = QHBoxLayout()
        add_samples_button = QPushButton("Samples hinzufuegen")
        add_samples_button.clicked.connect(self.add_samples)
        sample_row.addWidget(add_samples_button)
        scan_button = QPushButton("Gefundene XTTS-Orte anzeigen")
        scan_button.clicked.connect(self.show_candidate_locations)
        sample_row.addWidget(scan_button)
        auto_import_button = QPushButton("XTTS-Sprecher automatisch suchen")
        auto_import_button.clicked.connect(self.auto_import_webui_speakers)
        sample_row.addWidget(auto_import_button)
        starter_button = QPushButton("Starter-XTTS-Sprecher laden")
        starter_button.clicked.connect(self.install_starter_profiles)
        sample_row.addWidget(starter_button)
        import_webui_button = QPushButton("XTTS-WebUI-Sprecher importieren")
        import_webui_button.clicked.connect(self.import_webui_speakers)
        sample_row.addWidget(import_webui_button)
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
        self.profile_list.itemSelectionChanged.connect(self.show_selected_profile)
        layout.addWidget(self.profile_list)

        profile_action_row = QHBoxLayout()
        preview_profile_button = QPushButton("Ausgewaehltes Sample hoeren")
        preview_profile_button.clicked.connect(self.preview_selected_profile_sample)
        profile_action_row.addWidget(preview_profile_button)
        open_profile_button = QPushButton("Profilordner oeffnen")
        open_profile_button.clicked.connect(self.open_selected_profile_folder)
        profile_action_row.addWidget(open_profile_button)
        layout.addLayout(profile_action_row)

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

    def import_webui_speakers(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self,
            "XTTS-WebUI speakers Ordner waehlen",
            str(self.paths.root),
        )
        if not folder:
            return
        manifests = import_xtts_webui_speakers(
            self.paths,
            Path(folder),
            fallback_language=self.language_combo.currentText(),
        )
        self.refresh_existing_profiles()
        self.details.setPlainText(
            json.dumps(
                {"imported_profiles": [manifest.parent.name for manifest in manifests], "source_folder": folder},
                indent=2,
                ensure_ascii=False,
            )
        )
        QMessageBox.information(
            self,
            "XTTS-Sprecher importiert",
            f"{len(manifests)} XTTS-Sprecherprofile aus dem WebUI-Ordner importiert.",
        )

    def auto_import_webui_speakers(self) -> None:
        source_root, manifests = auto_import_xtts_speakers(
            self.paths,
            fallback_language=self.language_combo.currentText(),
        )
        self.refresh_existing_profiles()
        if not source_root or not manifests:
            QMessageBox.warning(
                self,
                "Keine XTTS-Sprecher gefunden",
                "Es wurde kein befuellter speakers-Ordner gefunden. "
                "Gesucht wird jetzt auch in Home, Documents, Downloads sowie typischen xtts-webui-Ordnern unter /mnt und /media. "
                "Lege sonst einen XTTS-WebUI speakers-Ordner unter src/speakers, speakers/ oder xtts-webui/speakers ab.",
            )
            self.show_candidate_locations()
            return
        self.details.setPlainText(
            json.dumps(
                {
                    "imported_profiles": [manifest.parent.name for manifest in manifests],
                    "source_folder": str(source_root),
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        QMessageBox.information(
            self,
            "XTTS-Sprecher importiert",
            f"{len(manifests)} XTTS-Sprecherprofile automatisch aus {source_root} importiert.",
        )

    def show_candidate_locations(self) -> None:
        summaries = describe_candidate_speaker_roots(self.paths)
        if not summaries:
            self.details.setPlainText(
                "Keine XTTS-Kandidaten gefunden.\n"
                "Gesucht wurde in src/speakers, speakers/, xtts-webui/speakers sowie typischen Altinstallationen in Home, Documents, Downloads, /mnt und /media."
            )
            return
        self.details.setPlainText(json.dumps({"candidates": summaries}, indent=2, ensure_ascii=False))

    def install_starter_profiles(self) -> None:
        manifests = install_starter_xtts_profiles(self.paths)
        self.refresh_existing_profiles()
        if not manifests:
            QMessageBox.information(
                self,
                "Starter bereits vorhanden",
                "Die XTTS-Starterprofile sind bereits installiert.",
            )
            return
        self.details.setPlainText(
            json.dumps(
                {
                    "installed_starter_profiles": [manifest.parent.name for manifest in manifests],
                    "source": "https://github.com/daswer123/xtts-webui/tree/main/speakers",
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        QMessageBox.information(
            self,
            "Starter installiert",
            f"{len(manifests)} XTTS-Starterprofile wurden installiert.",
        )

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
            backend=self.backend_combo.currentText().split(" ", 1)[0],
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
            "Vorhandene Voice-Lab-Profile werden unter workspace/voice_profiles gespeichert.\n"
            "XTTS/Custom Voices sind im UI farblich als Beta markiert.\n"
            "Wenn noch keine Profile da sind, nutze 'XTTS-Sprecher automatisch suchen', 'Starter-XTTS-Sprecher laden' oder importiere einen WebUI speakers-Ordner."
        )
        if self.profile_list.count():
            self.profile_list.setCurrentRow(0)

    def show_selected_profile(self) -> None:
        item = self.profile_list.currentItem()
        if not item:
            return
        profile = load_voice_profile(self.paths.voice_profiles, item.text())
        payload = {
            "profile_id": profile.profile_id,
            "display_name": profile.display_name,
            "target_language": profile.target_language,
            "backend": profile.backend,
            "sample_count": len(profile.samples),
            "samples": profile.samples,
            "validation_warnings": profile.validation_warnings,
            "notes": profile.notes,
        }
        self.details.setPlainText(json.dumps(payload, indent=2, ensure_ascii=False))

    def preview_selected_profile_sample(self) -> None:
        item = self.profile_list.currentItem()
        if not item:
            QMessageBox.warning(self, "Kein Profil", "Bitte zuerst ein Voice-Profil auswaehlen.")
            return
        profile = load_voice_profile(self.paths.voice_profiles, item.text())
        if not profile.samples:
            QMessageBox.warning(self, "Keine Samples", "Dieses Profil hat keine Referenzsamples.")
            return
        sample_path = Path(profile.samples[0])
        if not sample_path.exists():
            QMessageBox.warning(self, "Sample fehlt", f"Referenzsample nicht gefunden: {sample_path}")
            return
        self.player.setSource(QUrl.fromLocalFile(str(sample_path)))
        self.player.play()

    def open_selected_profile_folder(self) -> None:
        item = self.profile_list.currentItem()
        if not item:
            QMessageBox.warning(self, "Kein Profil", "Bitte zuerst ein Voice-Profil auswaehlen.")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.paths.voice_profiles / item.text())))

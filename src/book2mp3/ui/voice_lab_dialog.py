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
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from book2mp3.config import AppPaths
from book2mp3.i18n import apply_text, resolve_ui_language, translate_widget_tree
from book2mp3.tts.xtts import XttsBackend
from book2mp3.ui.theme import apply_modern_window_style
from book2mp3.ui.xtts_setup_dialog import XttsSetupDialog
from book2mp3.xtts_speakers import (
    auto_import_xtts_speakers,
    describe_candidate_speaker_roots,
    import_xtts_webui_speakers,
    install_starter_xtts_profiles,
)
from book2mp3.utils.logging_utils import get_logger
from book2mp3.voice_lab import create_voice_profile, load_voice_profile
from book2mp3.xtts_setup import xtts_launcher_hint, xtts_license_hint

class VoiceLabDialog(QDialog):
    def __init__(self, paths: AppPaths, parent: QWidget | None = None, *, ui_language: str | None = None) -> None:
        super().__init__(parent)
        self.paths = paths
        self.logger = get_logger("voice_lab")
        self.ui_language = resolve_ui_language(ui_language)
        self.xtts_backend = XttsBackend(paths.runtime, logger=self.logger)
        self.sample_paths: list[Path] = []
        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_output)

        self.setWindowTitle(apply_text("XTTS-Profilstudio", self.ui_language))
        self.resize(980, 700)
        self.setMinimumSize(900, 660)
        self._build_ui()
        apply_modern_window_style(self)
        translate_widget_tree(self, self.ui_language)
        self.refresh_existing_profiles()

    def _build_ui(self) -> None:
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(8, 8, 8, 8)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer_layout.addWidget(scroll)

        page = QWidget()
        scroll.setWidget(page)
        layout = QVBoxLayout(page)

        intro = QLabel(
            "Hier verwaltest du XTTS-Sprecherprofile getrennt vom eigentlichen Auftragsdialog. "
            "Importiere vorhandene Sprecher, prüfe Referenzsamples und speichere saubere Profile für das Profilstudio."
        )
        intro.setWordWrap(True)
        intro.setProperty("role", "hint")
        layout.addWidget(intro)

        self.runtime_intro = QLabel("")
        self.runtime_intro.setWordWrap(True)
        self.runtime_intro.setProperty("role", "hint")
        layout.addWidget(self.runtime_intro)

        self.beta_notice = QLabel(
            "XTTS-Profile brauchen gute Referenzsamples. Prüfe deshalb jede neue Stimme zuerst im Profilstudio, "
            "bevor du daraus ein Produktionsprofil machst."
        )
        self.beta_notice.setWordWrap(True)
        self.beta_notice.setProperty("role", "warning")
        layout.addWidget(self.beta_notice)

        sections = QVBoxLayout()
        layout.addLayout(sections)

        edit_group = QGroupBox("Profil anlegen oder importieren")
        edit_layout = QVBoxLayout(edit_group)
        form = QFormLayout()
        self.name_edit = QLineEdit()
        form.addRow("Profilname", self.name_edit)
        self.language_combo = QComboBox()
        self.language_combo.addItems(["de", "en", "es", "pt", "fr", "it", "nl", "pl"])
        form.addRow("Zielsprache", self.language_combo)
        self.backend_combo = QComboBox()
        self.backend_combo.addItems(["xtts_v2"])
        form.addRow("Backend", self.backend_combo)
        edit_layout.addLayout(form)

        tool_grid = QGridLayout()
        runtime_button = QPushButton("XTTS jetzt einrichten")
        runtime_button.clicked.connect(self.open_xtts_setup_dialog)
        tool_grid.addWidget(runtime_button, 0, 0)
        add_samples_button = QPushButton("Samples hinzufuegen")
        add_samples_button.clicked.connect(self.add_samples)
        tool_grid.addWidget(add_samples_button, 0, 1)
        scan_button = QPushButton("Gefundene XTTS-Orte anzeigen")
        scan_button.clicked.connect(self.show_candidate_locations)
        tool_grid.addWidget(scan_button, 0, 2)
        auto_import_button = QPushButton("XTTS-Sprecher automatisch suchen")
        auto_import_button.clicked.connect(self.auto_import_webui_speakers)
        tool_grid.addWidget(auto_import_button, 1, 0)
        starter_button = QPushButton("Starter-XTTS-Sprecher laden")
        starter_button.clicked.connect(self.install_starter_profiles)
        tool_grid.addWidget(starter_button, 1, 1)
        import_webui_button = QPushButton("XTTS-WebUI-Sprecher importieren")
        import_webui_button.clicked.connect(self.import_webui_speakers)
        tool_grid.addWidget(import_webui_button, 1, 2)
        clear_samples_button = QPushButton("Samples leeren")
        clear_samples_button.clicked.connect(self.clear_samples)
        tool_grid.addWidget(clear_samples_button, 2, 0)
        edit_layout.addLayout(tool_grid)

        self.samples_list = QListWidget()
        self.samples_list.setMinimumHeight(100)
        edit_layout.addWidget(self.samples_list)

        self.notes_edit = QPlainTextEdit()
        self.notes_edit.setPlaceholderText(
            "Notizen, Zielstimme, Aufnahmeumgebung, Stil, Besonderheiten."
        )
        self.notes_edit.setMinimumHeight(90)
        edit_layout.addWidget(self.notes_edit)

        action_row = QHBoxLayout()
        save_button = QPushButton("Profil speichern")
        save_button.clicked.connect(self.save_profile)
        action_row.addWidget(save_button)
        refresh_button = QPushButton("Profile neu laden")
        refresh_button.clicked.connect(self.refresh_existing_profiles)
        action_row.addWidget(refresh_button)
        edit_layout.addLayout(action_row)

        list_group = QGroupBox("Vorhandene XTTS-Profile")
        list_layout = QVBoxLayout(list_group)
        self.profile_list = QListWidget()
        self.profile_list.itemSelectionChanged.connect(self.show_selected_profile)
        self.profile_list.setMinimumHeight(150)
        list_layout.addWidget(self.profile_list)

        profile_action_row = QHBoxLayout()
        preview_profile_button = QPushButton("Ausgewaehltes Sample hoeren")
        preview_profile_button.clicked.connect(self.preview_selected_profile_sample)
        profile_action_row.addWidget(preview_profile_button)
        open_profile_button = QPushButton("Profilordner oeffnen")
        open_profile_button.clicked.connect(self.open_selected_profile_folder)
        profile_action_row.addWidget(open_profile_button)
        list_layout.addLayout(profile_action_row)

        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setMinimumHeight(180)
        list_layout.addWidget(self.details)

        sections.addWidget(edit_group)
        sections.addWidget(list_group)
        layout.addStretch(1)

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
        self.refresh_runtime_hint()
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
            "XTTS-Profil gespeichert. Darauf kann jetzt im Profilstudio und in Produktionsprofilen aufgebaut werden.",
        )

    def refresh_existing_profiles(self) -> None:
        self.profile_list.clear()
        profiles = sorted(self.paths.voice_profiles.glob("*/profile.json"))
        for profile in profiles:
            self.profile_list.addItem(profile.parent.name)
        self.details.setPlainText(
            "Vorhandene XTTS-Profile werden unter workspace/voice_profiles gespeichert.\n"
            "Die Profile werden anschliessend im Profilstudio fuer Hörproben und Produktionsprofile verwendet.\n"
            "Wenn noch keine Profile da sind, nutze 'XTTS-Sprecher automatisch suchen', 'Starter-XTTS-Sprecher laden' oder importiere einen WebUI speakers-Ordner."
        )
        if self.profile_list.count():
            self.profile_list.setCurrentRow(0)
        self.refresh_runtime_hint()

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

    def open_xtts_setup_dialog(self) -> None:
        dialog = XttsSetupDialog(self.paths, self, ui_language=self.ui_language)
        dialog.exec()
        self.refresh_runtime_hint()
        self.refresh_existing_profiles()

    def refresh_runtime_hint(self) -> None:
        if self.xtts_backend.is_available():
            self.runtime_intro.setText(
                "XTTS-Runtime ist bereit. Prüfe jetzt Referenzsamples, importiere Sprecher und teste danach im Benchmark-Studio."
            )
            return
        self.runtime_intro.setText(
            f"Piper funktioniert sofort. XTTS ist optional und wird getrennt eingerichtet. "
            f"Schnellstart: {xtts_launcher_hint()}. {xtts_license_hint()}"
        )

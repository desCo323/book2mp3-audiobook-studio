from __future__ import annotations

import sys

from PySide6.QtCore import QProcess
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from book2mp3.config import AppPaths
from book2mp3.i18n import apply_text, resolve_ui_language, translate_widget_tree
from book2mp3.ui.theme import apply_modern_window_style
from book2mp3.xtts_setup import (
    xtts_launcher_hint,
    xtts_license_hint,
    xtts_setup_command,
    xtts_setup_command_text,
    xtts_setup_summary,
    xtts_setup_supported,
)


class XttsSetupDialog(QDialog):
    def __init__(self, paths: AppPaths, parent: QWidget | None = None, *, ui_language: str | None = None) -> None:
        super().__init__(parent)
        self.paths = paths
        self.ui_language = resolve_ui_language(ui_language)
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(self._append_output)
        self.process.finished.connect(self._on_finished)
        self.process.errorOccurred.connect(self._on_error)

        self.setWindowTitle(apply_text("XTTS optional einrichten", self.ui_language))
        self.resize(900, 640)
        self.setMinimumSize(820, 560)
        self._build_ui()
        apply_modern_window_style(self)
        translate_widget_tree(self, self.ui_language)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        hero = QLabel("XTTS optional einrichten")
        hero.setProperty("role", "hero")
        layout.addWidget(hero)

        intro = QLabel(
            f"{xtts_setup_summary(self.paths)} "
            "Die App bleibt währenddessen benutzbar, aber der XTTS-Setup selbst kann einige Minuten dauern."
        )
        intro.setWordWrap(True)
        intro.setProperty("role", "hint")
        layout.addWidget(intro)

        license_note = QLabel(xtts_license_hint())
        license_note.setWordWrap(True)
        license_note.setProperty("role", "warning")
        layout.addWidget(license_note)

        self.status_label = QLabel(
            f"Empfohlener Endnutzerpfad: {xtts_launcher_hint()} oder direkt aus diesem Dialog starten."
        )
        self.status_label.setWordWrap(True)
        self.status_label.setProperty("role", "muted")
        layout.addWidget(self.status_label)

        self.command_view = QPlainTextEdit()
        self.command_view.setReadOnly(True)
        if xtts_setup_supported(self.paths):
            self.command_view.setPlainText(xtts_setup_command_text(self.paths, python_executable=sys.executable))
        else:
            self.command_view.setPlainText("XTTS-Setup ist in dieser Laufzeit nicht vorbereitet.")
        self.command_view.setMinimumHeight(84)
        layout.addWidget(self.command_view)

        self.output_view = QPlainTextEdit()
        self.output_view.setReadOnly(True)
        self.output_view.setPlaceholderText(
            "Hier erscheinen der Download- und Installationsfortschritt der optionalen XTTS-Runtime."
        )
        layout.addWidget(self.output_view, 1)

        button_row = QHBoxLayout()
        self.start_button = QPushButton("XTTS jetzt einrichten")
        self.start_button.clicked.connect(self.start_install)
        button_row.addWidget(self.start_button)
        self.open_runtime_button = QPushButton("Runtime-Ordner öffnen")
        self.open_runtime_button.clicked.connect(self.open_runtime_folder)
        button_row.addWidget(self.open_runtime_button)
        self.close_button = QPushButton("Schließen")
        self.close_button.clicked.connect(self.close)
        button_row.addWidget(self.close_button)
        layout.addLayout(button_row)

        if not xtts_setup_supported(self.paths):
            self.start_button.setEnabled(False)
            self.status_label.setText("XTTS-Setup ist in dieser Laufzeit nicht vorbereitet.")

    def open_runtime_folder(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.paths.runtime)))

    def start_install(self) -> None:
        if self.process.state() != QProcess.ProcessState.NotRunning:
            return
        if not xtts_setup_supported(self.paths):
            QMessageBox.warning(self, "XTTS-Setup fehlt", "Die Installationsskripte sind in dieser Laufzeit nicht vorhanden.")
            return
        command = xtts_setup_command(self.paths, python_executable=sys.executable)
        self.output_view.clear()
        self.output_view.appendPlainText(f"Starte: {xtts_setup_command_text(self.paths, python_executable=sys.executable)}\n")
        self.start_button.setEnabled(False)
        self.close_button.setEnabled(False)
        self.status_label.setText("XTTS-Setup läuft. Downloads und Paketinstallation können einige Minuten dauern.")
        self.process.start(command[0], command[1:])

    def _append_output(self) -> None:
        chunk = bytes(self.process.readAllStandardOutput()).decode("utf-8", errors="replace")
        if not chunk:
            return
        self.output_view.moveCursor(QTextCursor.MoveOperation.End)
        self.output_view.insertPlainText(chunk)
        self.output_view.moveCursor(QTextCursor.MoveOperation.End)

    def _on_finished(self, exit_code: int, exit_status: QProcess.ExitStatus) -> None:
        self.start_button.setEnabled(True)
        self.close_button.setEnabled(True)
        if exit_status == QProcess.ExitStatus.NormalExit and exit_code == 0:
            self.status_label.setText(
                "XTTS-Runtime installiert. Als Nächstes kannst du Starterprofile laden oder direkt ein XTTS-Profil testen."
            )
            QMessageBox.information(
                self,
                "XTTS bereit",
                "Die optionale XTTS-Runtime wurde eingerichtet. Lade jetzt bei Bedarf Starterprofile oder öffne das XTTS-Profilstudio.",
            )
            return
        self.status_label.setText("XTTS-Setup ist fehlgeschlagen. Prüfe die Logausgabe und bleibe vorerst bei Piper.")
        QMessageBox.warning(
            self,
            "XTTS-Setup fehlgeschlagen",
            "Die optionale XTTS-Runtime konnte nicht eingerichtet werden. Details stehen im Logbereich dieses Dialogs.",
        )

    def _on_error(self, error: QProcess.ProcessError) -> None:
        self.output_view.appendPlainText(f"\nProzessfehler: {error}")

    def closeEvent(self, event) -> None:  # type: ignore[override]
        if self.process.state() != QProcess.ProcessState.NotRunning:
            answer = QMessageBox.question(
                self,
                "Setup läuft noch",
                "Der XTTS-Setup läuft noch. Soll er wirklich abgebrochen werden?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.process.kill()
            self.process.waitForFinished(3000)
        super().closeEvent(event)

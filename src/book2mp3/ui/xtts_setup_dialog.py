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

    def _text(self, de: str, en: str, es: str, pt: str) -> str:
        return {
            "de": de,
            "en": en,
            "es": es,
            "pt": pt,
        }.get(self.ui_language, en)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        hero = QLabel("XTTS optional einrichten")
        hero.setProperty("role", "hero")
        layout.addWidget(hero)

        intro = QLabel(
            f"{xtts_setup_summary(self.paths)} "
            + self._text(
                "Die App bleibt währenddessen benutzbar, aber der XTTS-Setup selbst kann einige Minuten dauern.",
                "The app remains usable while this runs, but the XTTS setup itself can take several minutes.",
                "La aplicación seguirá siendo utilizable mientras esto se ejecuta, pero la instalación de XTTS puede tardar varios minutos.",
                "O aplicativo continua utilizável durante esse processo, mas a instalação do XTTS pode levar vários minutos.",
            )
        )
        intro.setWordWrap(True)
        intro.setProperty("role", "hint")
        layout.addWidget(intro)

        license_note = QLabel(xtts_license_hint())
        license_note.setWordWrap(True)
        license_note.setProperty("role", "warning")
        layout.addWidget(license_note)

        self.status_label = QLabel(
            self._text(
                f"Empfohlener Endnutzerpfad: {xtts_launcher_hint()} oder direkt aus diesem Dialog starten.",
                f"Recommended end-user path: {xtts_launcher_hint()} or start it directly from this dialog.",
                f"Ruta recomendada para el usuario final: {xtts_launcher_hint()} o iniciarlo directamente desde este diálogo.",
                f"Caminho recomendado para o usuário final: {xtts_launcher_hint()} ou iniciá-lo diretamente neste diálogo.",
            )
        )
        self.status_label.setWordWrap(True)
        self.status_label.setProperty("role", "muted")
        layout.addWidget(self.status_label)

        self.command_view = QPlainTextEdit()
        self.command_view.setReadOnly(True)
        if xtts_setup_supported(self.paths):
            self.command_view.setPlainText(xtts_setup_command_text(self.paths, python_executable=sys.executable))
        else:
            self.command_view.setPlainText(
                self._text(
                    "XTTS-Setup ist in dieser Laufzeit nicht vorbereitet.",
                    "XTTS setup is not prepared in this runtime.",
                    "La instalación de XTTS no está preparada en este runtime.",
                    "A instalação do XTTS não está preparada neste runtime.",
                )
            )
        self.command_view.setMinimumHeight(84)
        layout.addWidget(self.command_view)

        self.output_view = QPlainTextEdit()
        self.output_view.setReadOnly(True)
        self.output_view.setPlaceholderText(
            self._text(
                "Hier erscheinen der Download- und Installationsfortschritt der optionalen XTTS-Runtime.",
                "Download and installation progress for the optional XTTS runtime appears here.",
                "Aquí aparecerá el progreso de descarga e instalación del runtime opcional de XTTS.",
                "Aqui aparecerá o progresso do download e da instalação do runtime opcional do XTTS.",
            )
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
            self.status_label.setText(
                self._text(
                    "XTTS-Setup ist in dieser Laufzeit nicht vorbereitet.",
                    "XTTS setup is not prepared in this runtime.",
                    "La instalación de XTTS no está preparada en este runtime.",
                    "A instalação do XTTS não está preparada neste runtime.",
                )
            )

    def open_runtime_folder(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.paths.runtime)))

    def start_install(self) -> None:
        if self.process.state() != QProcess.ProcessState.NotRunning:
            return
        if not xtts_setup_supported(self.paths):
            QMessageBox.warning(
                self,
                self._text("XTTS-Setup fehlt", "XTTS setup missing", "Falta la instalación de XTTS", "Falta a instalação do XTTS"),
                self._text(
                    "Die Installationsskripte sind in dieser Laufzeit nicht vorhanden.",
                    "The installation scripts are not present in this runtime.",
                    "Los scripts de instalación no están presentes en este runtime.",
                    "Os scripts de instalação não estão presentes neste runtime.",
                ),
            )
            return
        command = xtts_setup_command(self.paths, python_executable=sys.executable)
        self.output_view.clear()
        self.output_view.appendPlainText(
            self._text("Starte", "Starting", "Iniciando", "Iniciando")
            + f": {xtts_setup_command_text(self.paths, python_executable=sys.executable)}\n"
        )
        self.start_button.setEnabled(False)
        self.close_button.setEnabled(False)
        self.status_label.setText(
            self._text(
                "XTTS-Setup läuft. Downloads und Paketinstallation können einige Minuten dauern.",
                "XTTS setup is running. Downloads and package installation can take several minutes.",
                "La instalación de XTTS está en curso. Las descargas y la instalación de paquetes pueden tardar varios minutos.",
                "A instalação do XTTS está em andamento. Downloads e instalação de pacotes podem levar vários minutos.",
            )
        )
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
                self._text(
                    "XTTS-Runtime installiert. Als Nächstes kannst du Starterprofile laden oder direkt ein XTTS-Profil testen.",
                    "XTTS runtime installed. Next you can load starter profiles or test an XTTS profile directly.",
                    "Runtime XTTS instalado. Ahora puedes cargar perfiles iniciales o probar directamente un perfil XTTS.",
                    "Runtime XTTS instalado. Agora você pode carregar perfis iniciais ou testar diretamente um perfil XTTS.",
                )
            )
            QMessageBox.information(
                self,
                self._text("XTTS bereit", "XTTS ready", "XTTS listo", "XTTS pronto"),
                self._text(
                    "Die optionale XTTS-Runtime wurde eingerichtet. Lade jetzt bei Bedarf Starterprofile oder öffne das XTTS-Profilstudio.",
                    "The optional XTTS runtime is ready. You can now load starter profiles or open the XTTS profile studio.",
                    "El runtime opcional de XTTS está listo. Ahora puedes cargar perfiles iniciales o abrir el estudio de perfiles XTTS.",
                    "O runtime opcional do XTTS está pronto. Agora você pode carregar perfis iniciais ou abrir o estúdio de perfis XTTS.",
                ),
            )
            return
        self.status_label.setText(
            self._text(
                "XTTS-Setup ist fehlgeschlagen. Prüfe die Logausgabe und bleibe vorerst bei Piper.",
                "XTTS setup failed. Check the log output and stay with Piper for now.",
                "La instalación de XTTS ha fallado. Revisa el log y utiliza Piper por ahora.",
                "A instalação do XTTS falhou. Verifique o log e use Piper por enquanto.",
            )
        )
        QMessageBox.warning(
            self,
            self._text("XTTS-Setup fehlgeschlagen", "XTTS setup failed", "Falló la instalación de XTTS", "A instalação do XTTS falhou"),
            self._text(
                "Die optionale XTTS-Runtime konnte nicht eingerichtet werden. Details stehen im Logbereich dieses Dialogs.",
                "The optional XTTS runtime could not be installed. Details are shown in the log area of this dialog.",
                "No se pudo instalar el runtime opcional de XTTS. Los detalles se muestran en el área de log de este diálogo.",
                "Não foi possível instalar o runtime opcional do XTTS. Os detalhes aparecem na área de log deste diálogo.",
            ),
        )

    def _on_error(self, error: QProcess.ProcessError) -> None:
        self.output_view.appendPlainText(f"\n{self._text('Prozessfehler', 'Process error', 'Error del proceso', 'Erro do processo')}: {error}")

    def closeEvent(self, event) -> None:  # type: ignore[override]
        if self.process.state() != QProcess.ProcessState.NotRunning:
            answer = QMessageBox.question(
                self,
                self._text("Setup läuft noch", "Setup still running", "La instalación sigue en curso", "A instalação ainda está em andamento"),
                self._text(
                    "Der XTTS-Setup läuft noch. Soll er wirklich abgebrochen werden?",
                    "The XTTS setup is still running. Do you really want to abort it?",
                    "La instalación de XTTS sigue en curso. ¿Seguro que quieres cancelarla?",
                    "A instalação do XTTS ainda está em andamento. Deseja realmente cancelá-la?",
                ),
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.process.kill()
            self.process.waitForFinished(3000)
        super().closeEvent(event)

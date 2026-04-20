from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from book2mp3.config import AppPaths
from book2mp3.pipeline.jobs import JobManager
from book2mp3.preview_sessions import (
    choose_preview_case,
    create_preview_session,
    list_preview_sessions,
    record_preview_job_result,
)
from book2mp3.presets import get_preset
from book2mp3.tts.piper import PiperBackend
from book2mp3.utils.logging_utils import get_logger


class FindBestSettingDialog(QDialog):
    def __init__(self, paths: AppPaths, manager: JobManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.paths = paths
        self.manager = manager
        self.logger = get_logger("find_best_setting")
        self.current_source: Path | None = None
        self.current_session_id: str | None = None

        self.setWindowTitle("Find Best Setting")
        self.resize(980, 680)
        self._build_ui()
        self.refresh_sessions()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        intro = QLabel(
            "Erzeuge bis zu 10 sinnvolle Preview-Tests. "
            "Jeder Test erzeugt eine kurze Vergleichs-MP3. "
            "Die Session bleibt gespeichert, damit du spaeter wiederkommen und einen Favoriten waehlen kannst."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        howto = QLabel(
            "So benutzt du diese Funktion:\n"
            "1. Buchquelle waehlen.\n"
            "2. Preview-Session erzeugen.\n"
            "3. Tests in die Queue legen.\n"
            "4. Die erzeugten MP3s anhoeren.\n"
            "5. Spaeter wiederkommen und den besten Test als Favoriten speichern.\n\n"
            "Jeder Test kombiniert Stimme und Preset. "
            "Die Preview ist absichtlich kurz, damit du schnell vergleichen kannst, "
            "bevor du ein ganzes Buch renderst."
        )
        howto.setWordWrap(True)
        layout.addWidget(howto)

        controls = QHBoxLayout()
        self.source_label = QLabel("Keine Quelle gewaehlt")
        controls.addWidget(self.source_label)
        choose_source = QPushButton("Quelle waehlen")
        choose_source.clicked.connect(self.select_source)
        controls.addWidget(choose_source)
        create_session = QPushButton("Preview-Session erzeugen")
        create_session.clicked.connect(self.create_session)
        controls.addWidget(create_session)
        queue_tests = QPushButton("Tests in Queue legen")
        queue_tests.clicked.connect(self.queue_tests)
        controls.addWidget(queue_tests)
        choose_best = QPushButton("Ausgewaehlten Test als Favorit speichern")
        choose_best.clicked.connect(self.choose_best)
        controls.addWidget(choose_best)
        layout.addLayout(controls)

        rows = QHBoxLayout()
        self.sessions_list = QListWidget()
        self.sessions_list.itemSelectionChanged.connect(self.on_session_selected)
        rows.addWidget(self.sessions_list)
        self.tests_list = QListWidget()
        rows.addWidget(self.tests_list)
        layout.addLayout(rows)

        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setPlaceholderText(
            "Hier siehst du die Session-Details, die erzeugten Testobjekte, "
            "Job-IDs und spaeter den gespeicherten Favoriten."
        )
        layout.addWidget(self.details)

    def select_source(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Buchquelle fuer Preview auswaehlen",
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
        voices = PiperBackend(self.paths.runtime, self.paths.voices).installed_voices()
        session = create_preview_session(self.paths, self.current_source, voices)
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
        self.tests_list.clear()
        for test in session.tests:
            marker = " *BEST*" if session.selected_case_index == test.index else ""
            item = QListWidgetItem(
                f"{test.index:02d} | {test.status:8s} | {test.voice_id} | {test.preset_id}{marker}"
            )
            item.setData(32, test.index)
            self.tests_list.addItem(item)
        self.details.setPlainText(json.dumps({
            "session_id": session.session_id,
            "source_file": session.source_file,
            "preview_source_file": session.preview_source_file,
            "selected_case_index": session.selected_case_index,
            "tests": [test.__dict__ for test in session.tests],
        }, indent=2, ensure_ascii=False))

    def queue_tests(self) -> None:
        if not self.current_session_id:
            QMessageBox.warning(self, "Keine Session", "Bitte zuerst eine Preview-Session auswaehlen.")
            return
        sessions = {session.session_id: session for session in list_preview_sessions(self.paths)}
        session = sessions[self.current_session_id]
        preview_source = Path(session.preview_source_file)
        created = 0
        for test in session.tests:
            if test.job_id:
                continue
            preset = get_preset(test.preset_id)
            job = self.manager.create_job(
                source_path=preview_source,
                voice_id=test.voice_id,
                preset_id=preset.preset_id,
                priority=95,
                max_chars=preset.max_chars,
                output_mode="single_file",
                keep_wav=False,
                sentence_silence=preset.sentence_silence,
                length_scale=preset.length_scale,
            )
            record_preview_job_result(
                self.paths,
                session.session_id,
                test.index,
                job.job_id,
                job.final_output_file,
                "queued",
            )
            created += 1
        self.show_session(session.session_id)
        QMessageBox.information(self, "Tests erzeugt", f"{created} Preview-Tests wurden in die Queue gelegt.")

    def choose_best(self) -> None:
        if not self.current_session_id:
            QMessageBox.warning(self, "Keine Session", "Bitte zuerst eine Session auswaehlen.")
            return
        item = self.tests_list.currentItem()
        if not item:
            QMessageBox.warning(self, "Kein Test", "Bitte einen Test waehlen.")
            return
        case_index = item.data(32)
        session = choose_preview_case(self.paths, self.current_session_id, case_index)
        self.show_session(session.session_id)
        QMessageBox.information(
            self,
            "Favorit gespeichert",
            f"Test {case_index} wurde gespeichert. Du kannst spaeter darauf zurueckkommen.",
        )

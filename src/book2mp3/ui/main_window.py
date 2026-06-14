from __future__ import annotations

import json
import shutil
from collections import Counter
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFrame,
    QFileDialog,
    QFormLayout,
    QGroupBox,
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
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from book2mp3.app_settings import AppSettings, load_app_settings, reset_workspace_state, save_app_settings
from book2mp3.config import AppPaths
from book2mp3.i18n import (
    apply_text,
    preferred_content_language_code,
    resolve_ui_language,
    tr,
    translate_widget_tree,
    ui_language_choices,
)
from book2mp3.models import JobState
from book2mp3.pipeline.extract import DocumentStructure
from book2mp3.pipeline.jobs import JobManager
from book2mp3.piper_custom import default_config_for_model, import_custom_piper_model
from book2mp3.preview_sessions import list_preview_sessions, update_preview_job_status
from book2mp3.presets import QUALITY_PRESETS, get_preset
from book2mp3.service import Book2Mp3Service
from book2mp3.tts.piper import PiperBackend
from book2mp3.tts.xtts import XttsBackend
from book2mp3.ui.find_best_setting_dialog import FindBestSettingDialog
from book2mp3.ui.theme import apply_modern_window_style
from book2mp3.ui.voice_lab_dialog import VoiceLabDialog
from book2mp3.ui.worker import JobWorker
from book2mp3.ui.xtts_setup_dialog import XttsSetupDialog
from book2mp3.utils.logging_utils import configure_logging, get_logger
from book2mp3.voice_catalog import (
    core_language_label,
    filter_voice_ids,
    format_voice_label,
    language_choices,
    voice_filter_empty_message,
    voice_language_code,
)
from book2mp3.xtts_speakers import auto_import_xtts_speakers, install_starter_xtts_profiles
from book2mp3.voice_lab import list_voice_profiles, load_voice_profile
from book2mp3.voice_settings import (
    PROFILE_STATUS_APPROVED,
    PROFILE_STATUS_ARCHIVED,
    PROFILE_STATUS_DRAFT,
    PROFILE_STATUS_TESTED,
    list_voice_settings,
    load_voice_setting,
    profile_status_label,
    update_voice_setting_status,
)
from book2mp3.xtts_setup import xtts_launcher_hint, xtts_license_hint


class MainWindow(QMainWindow):
    def __init__(self, paths: AppPaths) -> None:
        super().__init__()
        self.paths = paths
        self.app_settings = load_app_settings(paths.app_settings_file)
        self.ui_language = resolve_ui_language(self.app_settings.ui_language)
        self.manager = JobManager(paths)
        self.service = Book2Mp3Service(paths)
        self.worker: JobWorker | None = None
        self.current_job_id: str | None = None
        self.cached_jobs: list[JobState] = []
        self.cached_active_jobs: list[JobState] = []
        self.logger = get_logger("ui")
        self.installed_voice_ids: list[str] = []
        self.selected_source_files: list[Path] = []
        self.pause_requested_job_id: str | None = None
        self.source_structures: dict[str, DocumentStructure] = {}
        self.source_structure = DocumentStructure(
            source_type="",
            chapter_count=0,
            chapter_titles=[],
            supports_chapter_files=False,
            summary="Noch keine Quelle gewählt.",
            analysis_status="idle",
        )
        self.job_output_mode_requested = "single_file"
        self.job_output_mode = "single_file"
        self._syncing_job_output_mode = False
        self.xtts_backend = XttsBackend(paths.runtime, logger=self.logger)
        self.xtts_backend.set_device_mode(self.app_settings.xtts_device_mode)
        self.xtts_probe_cache: dict[str, object] | None = None
        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_output)
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.handle_about_to_quit)

        self.setWindowTitle(apply_text("book2mp3 Hörbuch-Studio", self.ui_language))
        self.resize(1320, 760)
        self.setMinimumSize(1240, 720)
        self._build_ui()
        apply_modern_window_style(self)
        translate_widget_tree(self, self.ui_language)
        self.refresh_voice_list()
        self.refresh_saved_profiles()
        self.manager.recover_interrupted_jobs()
        self.refresh_jobs()
        self.refresh_diagnostics_summary()
        self.apply_cuda_first_preference()
        self.update_idle_status_from_queue()

    def _text(self, text: str) -> str:
        return apply_text(text, self.ui_language)

    def _tr(self, key: str, **kwargs) -> str:
        return tr(self.ui_language, key, **kwargs)

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)

        outer = QHBoxLayout(root)
        splitter = QSplitter(Qt.Horizontal)
        outer.addWidget(splitter)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        hero = QLabel("Aktive Aufträge")
        hero.setProperty("role", "hero")
        left_layout.addWidget(hero)
        sidebar_hint = QLabel(
            "Hier liegt die echte Produktionswarteschlange. "
            "Zum Anlegen eines neuen Hörbuchs nutzt du rechts ein gespeichertes Produktionsprofil."
        )
        sidebar_hint.setWordWrap(True)
        sidebar_hint.setProperty("role", "hint")
        left_layout.addWidget(sidebar_hint)
        self.queue_eta_header = QLabel("Noch keine Laufzeitdaten. Nach dem ersten erfolgreichen Buch erscheint hier eine erste Queue-Prognose.")
        self.queue_eta_header.setWordWrap(True)
        self.queue_eta_header.setProperty("role", "muted")
        left_layout.addWidget(self.queue_eta_header)
        self.job_list_overview_label = QLabel(
            "Noch keine aktiven Aufträge. Sobald eine Queue vorhanden ist, erscheinen hier Status, Restzeit und Prioritäten."
        )
        self.job_list_overview_label.setWordWrap(True)
        self.job_list_overview_label.setProperty("role", "hint")
        left_layout.addWidget(self.job_list_overview_label)
        filters_row = QHBoxLayout()
        self.job_search_edit = QLineEdit()
        self.job_search_edit.setPlaceholderText("Auftrag, Profil oder Buch suchen")
        self.job_search_edit.textChanged.connect(self.refresh_active_jobs_sidebar)
        filters_row.addWidget(self.job_search_edit, 1)
        self.job_status_filter_combo = QComboBox()
        self.job_status_filter_combo.addItem("Alle", "all")
        self.job_status_filter_combo.addItem("Läuft jetzt", "running")
        self.job_status_filter_combo.addItem("Wartet", "waiting")
        self.job_status_filter_combo.addItem("Aufmerksamkeit", "attention")
        self.job_status_filter_combo.addItem("Blockiert", "blocked")
        self.job_status_filter_combo.addItem("Fehler", "failed")
        self.job_status_filter_combo.currentIndexChanged.connect(self.refresh_active_jobs_sidebar)
        filters_row.addWidget(self.job_status_filter_combo)
        left_layout.addLayout(filters_row)
        self.job_list_filter_hint = QLabel("Liste zeigt alle aktiven Aufträge.")
        self.job_list_filter_hint.setWordWrap(True)
        self.job_list_filter_hint.setProperty("role", "muted")
        left_layout.addWidget(self.job_list_filter_hint)
        self.jobs_list = QListWidget()
        self.jobs_list.setMinimumWidth(340)
        self.jobs_list.setAlternatingRowColors(True)
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
        delete_button = QPushButton("Auftrag löschen")
        delete_button.clicked.connect(self.delete_selected_job)
        queue_button_row.addWidget(delete_button)
        left_layout.addLayout(queue_button_row)
        refresh_button = QPushButton("Warteschlange neu laden")
        refresh_button.clicked.connect(self.refresh_jobs)
        left_layout.addWidget(refresh_button)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        self.main_tabs = QTabWidget()
        tabs = self.main_tabs
        right_layout.addWidget(tabs)

        create_tab = QWidget()
        create_layout = self._make_scroll_tab(create_tab)
        intro = QLabel("1. Auftrag anlegen")
        intro.setProperty("role", "hero")
        create_layout.addWidget(intro)
        self.production_help_label = QLabel(
            "Für neue Hörbücher wählst du hier nur noch eine Buchquelle und ein gespeichertes Produktionsprofil. "
            "Stimmen testen, XTTS-Profile importieren und Feintuning liegen bewusst im separaten Profilstudio."
        )
        self.production_help_label.setWordWrap(True)
        self.production_help_label.setProperty("role", "hint")
        create_layout.addWidget(self.production_help_label)

        source_group = QGroupBox("Buchquelle")
        source_form = QFormLayout(source_group)
        self.source_edit = QLineEdit()
        self.source_edit.setReadOnly(True)
        self.source_edit.setPlaceholderText("Noch keine Quelldateien ausgewählt.")
        browse_button = QPushButton("Dateien wählen")
        browse_button.clicked.connect(self.select_source_files)
        clear_sources_button = QPushButton("Leeren")
        clear_sources_button.clicked.connect(self.clear_selected_source_files)
        source_row = QHBoxLayout()
        source_row.addWidget(self.source_edit)
        source_row.addWidget(browse_button)
        source_row.addWidget(clear_sources_button)
        source_form.addRow("Datei", self._wrap(source_row))
        self.source_count_label = QLabel("0 Quellen ausgewählt.")
        self.source_count_label.setWordWrap(True)
        self.source_count_label.setProperty("role", "muted")
        source_form.addRow("Auswahl", self.source_count_label)
        self.source_analysis_label = QLabel("Noch keine Quelle gewählt.")
        self.source_analysis_label.setWordWrap(True)
        self.source_analysis_label.setProperty("role", "muted")
        source_form.addRow("Kapitelerkennung", self.source_analysis_label)
        self.source_list = QListWidget()
        self.source_list.setMinimumHeight(150)
        source_form.addRow("Importübersicht", self.source_list)
        create_layout.addWidget(source_group)

        profile_group = QGroupBox("Produktionsprofil")
        profile_form = QFormLayout(profile_group)
        self.saved_profile_combo = QComboBox()
        self.saved_profile_combo.currentIndexChanged.connect(self.refresh_saved_profile_summary)
        profile_form.addRow("Gespeichertes Profil", self.saved_profile_combo)
        saved_profile_row = QHBoxLayout()
        refresh_saved_profiles_button = QPushButton("Profile neu laden")
        refresh_saved_profiles_button.clicked.connect(self.refresh_saved_profiles)
        saved_profile_row.addWidget(refresh_saved_profiles_button)
        open_test_lab_from_create = QPushButton("Zum Benchmark-Studio")
        open_test_lab_from_create.clicked.connect(lambda: self.show_benchmark_tab(focus_assistant=True))
        saved_profile_row.addWidget(open_test_lab_from_create)
        profile_form.addRow("", self._wrap(saved_profile_row))
        self.saved_profile_summary = QLabel("Noch kein Produktionsprofil gewählt.")
        self.saved_profile_summary.setWordWrap(True)
        self.saved_profile_summary.setProperty("role", "muted")
        profile_form.addRow("Profil-Info", self.saved_profile_summary)
        create_layout.addWidget(profile_group)

        metadata_group = QGroupBox("Metadaten & Tags")
        metadata_form = QFormLayout(metadata_group)
        self.meta_title_edit = QLineEdit()
        metadata_form.addRow("Titel", self.meta_title_edit)
        self.meta_author_edit = QLineEdit()
        metadata_form.addRow("Autor", self.meta_author_edit)
        self.meta_narrator_edit = QLineEdit()
        metadata_form.addRow("Sprecher", self.meta_narrator_edit)
        self.meta_genre_edit = QLineEdit("Audiobook")
        metadata_form.addRow("Genre", self.meta_genre_edit)
        self.meta_language_tag_edit = QLineEdit()
        metadata_form.addRow("Sprachtag", self.meta_language_tag_edit)
        self.meta_publisher_edit = QLineEdit()
        metadata_form.addRow("Verlag", self.meta_publisher_edit)
        self.meta_year_edit = QLineEdit()
        metadata_form.addRow("Jahr", self.meta_year_edit)
        self.meta_subject_edit = QLineEdit()
        metadata_form.addRow("Schlagwörter", self.meta_subject_edit)
        self.meta_isbn_edit = QLineEdit()
        metadata_form.addRow("ISBN", self.meta_isbn_edit)
        self.meta_comment_edit = QPlainTextEdit()
        self.meta_comment_edit.setPlaceholderText("Freier Kommentar oder Quelle für die finalen MP3-Tags.")
        self.meta_comment_edit.setMinimumHeight(76)
        metadata_form.addRow("Kommentar", self.meta_comment_edit)
        metadata_actions = QHBoxLayout()
        self.metadata_guess_button = QPushButton("Automatisch erkennen")
        self.metadata_guess_button.clicked.connect(self.populate_metadata_from_filename)
        metadata_actions.addWidget(self.metadata_guess_button)
        self.metadata_search_button = QPushButton("Online-Suche verfeinern")
        self.metadata_search_button.clicked.connect(self.search_metadata_online)
        metadata_actions.addWidget(self.metadata_search_button)
        self.metadata_apply_button = QPushButton("Ausgewählten Treffer übernehmen")
        self.metadata_apply_button.clicked.connect(self.apply_best_metadata_result)
        metadata_actions.addWidget(self.metadata_apply_button)
        metadata_form.addRow("", self._wrap(metadata_actions))
        self.metadata_status_label = QLabel("Noch keine Metadaten geladen.")
        self.metadata_status_label.setWordWrap(True)
        self.metadata_status_label.setProperty("role", "muted")
        metadata_form.addRow("Status", self.metadata_status_label)
        self.metadata_results_list = QListWidget()
        self.metadata_results_list.setMinimumHeight(120)
        metadata_form.addRow("Treffer", self.metadata_results_list)
        create_layout.addWidget(metadata_group)

        create_options_group = QGroupBox("Auftragsoptionen")
        create_options_form = QFormLayout(create_options_group)
        self.priority_spin = QSpinBox()
        self.priority_spin.setRange(1, 100)
        self.priority_spin.setValue(50)
        create_options_form.addRow("Priorität", self.priority_spin)
        self.job_output_mode_combo_hint = QLabel("Die finale Ausgabe kann pro Auftrag angepasst werden.")
        self.job_output_mode_combo_hint.setWordWrap(True)
        self.job_output_mode_combo_hint.setProperty("role", "muted")
        create_options_form.addRow("Ausgabe-Hinweis", self.job_output_mode_combo_hint)
        self.job_output_mode_group = QButtonGroup(self)
        output_modes_widget = QWidget()
        output_modes_layout = QVBoxLayout(output_modes_widget)
        output_modes_layout.setContentsMargins(0, 0, 0, 0)
        self.job_output_single_radio = QRadioButton("Eine große Enddatei")
        self.job_output_single_radio.toggled.connect(
            lambda checked: self.on_job_output_mode_radio_toggled("single_file", checked)
        )
        self.job_output_mode_group.addButton(self.job_output_single_radio)
        output_modes_layout.addWidget(self.job_output_single_radio)
        self.job_output_chapter_radio = QRadioButton("Eine Datei pro Kapitel")
        self.job_output_chapter_radio.toggled.connect(
            lambda checked: self.on_job_output_mode_radio_toggled("chapter_files", checked)
        )
        self.job_output_mode_group.addButton(self.job_output_chapter_radio)
        output_modes_layout.addWidget(self.job_output_chapter_radio)
        self.job_output_timed_radio = QRadioButton("Mehrere Dateien nach Zeit")
        self.job_output_timed_radio.toggled.connect(
            lambda checked: self.on_job_output_mode_radio_toggled("timed_parts", checked)
        )
        self.job_output_mode_group.addButton(self.job_output_timed_radio)
        output_modes_layout.addWidget(self.job_output_timed_radio)
        create_options_form.addRow("Finale Ausgabe", output_modes_widget)
        self.job_snapshot_label = QLabel(
            "Das Produktionsprofil bestimmt Backend, Stimme, Chunkgröße, Tempo und Ausgabeformat."
        )
        self.job_snapshot_label.setWordWrap(True)
        self.job_snapshot_label.setProperty("role", "muted")
        create_options_form.addRow("Wird verwendet", self.job_snapshot_label)
        create_layout.addWidget(create_options_group)

        create_buttons_card = QFrame()
        create_buttons_card.setProperty("card", "true")
        create_buttons_layout = QVBoxLayout(create_buttons_card)
        create_buttons_intro = QLabel(
            "Typischer Ablauf: Auftrag erzeugen, danach starten oder in die Warteschlange legen."
        )
        create_buttons_intro.setWordWrap(True)
        create_buttons_intro.setProperty("role", "muted")
        create_buttons_layout.addWidget(create_buttons_intro)
        create_buttons_row = QHBoxLayout()
        create_button = QPushButton("Aufträge aus Profil erzeugen")
        create_button.clicked.connect(self.create_job)
        create_buttons_row.addWidget(create_button)
        self.start_button = QPushButton("Ausgewählten Auftrag starten")
        self.start_button.clicked.connect(self.start_selected_job)
        create_buttons_row.addWidget(self.start_button)
        self.queue_button = QPushButton("Ausgewählten Auftrag einreihen")
        self.queue_button.clicked.connect(self.queue_selected_job)
        create_buttons_row.addWidget(self.queue_button)
        self.stop_button = QPushButton("Aktuellen Auftrag stoppen")
        self.stop_button.clicked.connect(self.stop_current_job)
        create_buttons_row.addWidget(self.stop_button)
        create_buttons_layout.addLayout(create_buttons_row)
        create_layout.addWidget(create_buttons_card)
        tabs.addTab(create_tab, "Auftrag")

        voices_tab = QWidget()
        voices_layout = self._make_scroll_tab(voices_tab)
        voices_intro = QLabel("2. Produktionsprofile")
        voices_intro.setProperty("role", "hero")
        voices_layout.addWidget(voices_intro)
        voices_help = QLabel(
            "Die eigentliche Auftragserstellung bleibt bewusst schlank. Hier verwaltest du Entwürfe, getestete und freigegebene Produktionsprofile "
            "und öffnest bei Bedarf das separate Profilstudio oder die XTTS-Profilverwaltung."
        )
        voices_help.setWordWrap(True)
        voices_help.setProperty("role", "hint")
        voices_layout.addWidget(voices_help)

        profile_library_group = QGroupBox("Gespeicherte Produktionsprofile")
        profile_library_layout = QVBoxLayout(profile_library_group)
        self.profile_library_list = QListWidget()
        self.profile_library_list.itemSelectionChanged.connect(self.on_profile_library_selected)
        profile_library_layout.addWidget(self.profile_library_list)
        profile_library_actions = QHBoxLayout()
        use_profile_button = QPushButton("Im Auftragsdialog verwenden")
        use_profile_button.clicked.connect(self.use_selected_profile_for_new_jobs)
        profile_library_actions.addWidget(use_profile_button)
        open_profile_studio_button = QPushButton("Zum Benchmark-Studio")
        open_profile_studio_button.clicked.connect(self.show_benchmark_tab)
        profile_library_actions.addWidget(open_profile_studio_button)
        profile_library_layout.addLayout(profile_library_actions)
        profile_status_actions = QHBoxLayout()
        approve_profile_button = QPushButton("Freigeben")
        approve_profile_button.clicked.connect(lambda: self.set_selected_profile_status(PROFILE_STATUS_APPROVED))
        profile_status_actions.addWidget(approve_profile_button)
        mark_tested_button = QPushButton("Als getestet markieren")
        mark_tested_button.clicked.connect(lambda: self.set_selected_profile_status(PROFILE_STATUS_TESTED))
        profile_status_actions.addWidget(mark_tested_button)
        archive_profile_button = QPushButton("Archivieren")
        archive_profile_button.clicked.connect(lambda: self.set_selected_profile_status(PROFILE_STATUS_ARCHIVED))
        profile_status_actions.addWidget(archive_profile_button)
        profile_library_layout.addLayout(profile_status_actions)
        self.profile_library_summary = QLabel("Noch kein Produktionsprofil gewählt.")
        self.profile_library_summary.setWordWrap(True)
        self.profile_library_summary.setProperty("role", "muted")
        profile_library_layout.addWidget(self.profile_library_summary)
        voices_layout.addWidget(profile_library_group)
        tabs.addTab(voices_tab, "Produktionsprofile")

        benchmark_tab = QWidget()
        benchmark_layout = self._make_scroll_tab(benchmark_tab)
        benchmark_title = QLabel("3. Benchmark-Studio")
        benchmark_title.setProperty("role", "hero")
        benchmark_layout.addWidget(benchmark_title)
        benchmark_help = QLabel(
            "Hier testest du Stimmen, Varianten und Geschwindigkeiten. "
            "Das eigentliche Produktionsprofil legst du erst nach Bewertung und Benchmark als freigegebenes Profil fest."
        )
        benchmark_help.setWordWrap(True)
        benchmark_help.setProperty("role", "hint")
        benchmark_layout.addWidget(benchmark_help)

        profile_runtime_group = QGroupBox("Studio-Überblick")
        profile_runtime_form = QFormLayout(profile_runtime_group)
        self.profile_runtime_summary = QLabel("")
        self.profile_runtime_summary.setWordWrap(True)
        profile_runtime_form.addRow("Überblick", self.profile_runtime_summary)
        self.profile_runtime_hint = QLabel("")
        self.profile_runtime_hint.setWordWrap(True)
        self.profile_runtime_hint.setProperty("role", "muted")
        profile_runtime_form.addRow("Hinweis", self.profile_runtime_hint)
        benchmark_layout.addWidget(profile_runtime_group)

        benchmark_tools_group = QGroupBox("Tests und Vergleich")
        benchmark_tools_layout = QVBoxLayout(benchmark_tools_group)
        benchmark_tools_intro = QLabel(
            "Öffne das Profilstudio für normale Hörproben oder den geführten Assistenten für eine neue Testreihe."
        )
        benchmark_tools_intro.setWordWrap(True)
        benchmark_tools_intro.setProperty("role", "muted")
        benchmark_tools_layout.addWidget(benchmark_tools_intro)
        lab_tools_card = QFrame()
        lab_tools_card.setProperty("card", "true")
        lab_tools_layout = QVBoxLayout(lab_tools_card)
        lab_tools_title = QLabel("Studio-Werkzeuge")
        lab_tools_title.setProperty("role", "hero")
        lab_tools_layout.addWidget(lab_tools_title)
        lab_tools_row = QHBoxLayout()
        find_best_button = QPushButton("Profilstudio")
        find_best_button.setToolTip("Öffnet das separate Profilstudio für Hörproben und Feintuning.")
        find_best_button.clicked.connect(self.open_find_best_setting)
        lab_tools_row.addWidget(find_best_button)
        voice_test_button = QPushButton("Profil-Assistent")
        voice_test_button.setToolTip("Öffnet direkt den geführten Profil-Assistenten.")
        voice_test_button.clicked.connect(lambda: self.open_find_best_setting(focus_assistant=True))
        lab_tools_row.addWidget(voice_test_button)
        import_piper_button = QPushButton("Custom-Piper importieren")
        import_piper_button.clicked.connect(self.import_custom_piper_voice)
        lab_tools_row.addWidget(import_piper_button)
        voices_button = QPushButton("Stimmen neu laden")
        voices_button.clicked.connect(self.refresh_voice_list)
        lab_tools_row.addWidget(voices_button)
        lab_tools_layout.addLayout(lab_tools_row)
        benchmark_tools_layout.addWidget(lab_tools_card)
        benchmark_layout.addWidget(benchmark_tools_group)
        self.benchmark_tab_index = tabs.addTab(benchmark_tab, "Benchmark-Studio")

        xtts_tab = QWidget()
        xtts_layout = self._make_scroll_tab(xtts_tab)
        xtts_title = QLabel("4. XTTS-Profile")
        xtts_title.setProperty("role", "hero")
        xtts_layout.addWidget(xtts_title)
        xtts_help = QLabel(
            "Hier verwaltest du nur XTTS-Runtime, Sprecherprofile und CUDA. "
            "Diese Schritte sind bewusst vom Benchmark-Studio und vom Produktionsdialog getrennt."
        )
        xtts_help.setWordWrap(True)
        xtts_help.setProperty("role", "hint")
        xtts_layout.addWidget(xtts_help)

        xtts_runtime_group = QGroupBox("XTTS-Runtime und Import")
        xtts_runtime_form = QFormLayout(xtts_runtime_group)
        self.xtts_setup_summary_label = QLabel("")
        self.xtts_setup_summary_label.setWordWrap(True)
        self.xtts_setup_summary_label.setProperty("role", "hint")
        xtts_runtime_form.addRow("Schnellstart", self.xtts_setup_summary_label)
        xtts_runtime_actions = QHBoxLayout()
        profile_runtime_refresh = QPushButton("Bestand neu laden")
        profile_runtime_refresh.clicked.connect(self.refresh_voice_list)
        xtts_runtime_actions.addWidget(profile_runtime_refresh)
        self.xtts_setup_button = QPushButton("XTTS jetzt einrichten")
        self.xtts_setup_button.clicked.connect(self.open_xtts_setup_dialog)
        xtts_runtime_actions.addWidget(self.xtts_setup_button)
        profile_runtime_probe = QPushButton("CUDA / XTTS prüfen")
        profile_runtime_probe.clicked.connect(self.show_xtts_runtime_probe)
        xtts_runtime_actions.addWidget(profile_runtime_probe)
        profile_runtime_xtts = QPushButton("XTTS-Profilstudio")
        profile_runtime_xtts.clicked.connect(self.open_voice_lab)
        xtts_runtime_actions.addWidget(profile_runtime_xtts)
        xtts_runtime_form.addRow("", self._wrap(xtts_runtime_actions))
        profile_import_actions = QHBoxLayout()
        xtts_import_button = QPushButton("XTTS-Profile suchen")
        xtts_import_button.clicked.connect(self.import_or_open_xtts)
        profile_import_actions.addWidget(xtts_import_button)
        xtts_starter_button = QPushButton("Starterprofile laden")
        xtts_starter_button.clicked.connect(self.install_xtts_starters)
        profile_import_actions.addWidget(xtts_starter_button)
        xtts_runtime_form.addRow("Import", self._wrap(profile_import_actions))
        xtts_layout.addWidget(xtts_runtime_group)

        backend_group = QGroupBox("Backend & Laufzeit")
        backend_form = QFormLayout(backend_group)
        self.backend_combo = QComboBox()
        self.backend_combo.addItems(["piper", "xtts"])
        self.backend_combo.currentIndexChanged.connect(self.on_backend_changed)
        backend_form.addRow("Backend", self.backend_combo)
        self.backend_notice = QLabel(
            "XTTS klingt natürlicher, braucht aber gute Sprecherprofile. Piper bleibt der robuste Offline-Standard."
        )
        self.backend_notice.setWordWrap(True)
        self.backend_notice.setProperty("role", "muted")
        backend_form.addRow("Einordnung", self.backend_notice)
        self.backend_summary = QLabel("")
        self.backend_summary.setWordWrap(True)
        backend_form.addRow("Status", self.backend_summary)
        self.xtts_device_combo = QComboBox()
        self.xtts_device_combo.addItem("CUDA bevorzugen", "cuda")
        self.xtts_device_combo.addItem("Automatisch", "auto")
        self.xtts_device_combo.addItem("CPU erzwingen", "cpu")
        self.xtts_device_combo.currentIndexChanged.connect(self.on_xtts_device_mode_changed)
        backend_form.addRow("XTTS-Gerät", self.xtts_device_combo)
        xtts_runtime_row = QHBoxLayout()
        xtts_probe_button = QPushButton("CUDA / XTTS prüfen")
        xtts_probe_button.clicked.connect(self.show_xtts_runtime_probe)
        xtts_runtime_row.addWidget(xtts_probe_button)
        backend_form.addRow("", self._wrap(xtts_runtime_row))
        self.xtts_runtime_hint = QLabel("")
        self.xtts_runtime_hint.setWordWrap(True)
        self.xtts_runtime_hint.setProperty("role", "muted")
        backend_form.addRow("Runtime", self.xtts_runtime_hint)
        voices_layout.addWidget(backend_group)

        piper_group = QGroupBox("Piper-Stimmen")
        piper_form = QFormLayout(piper_group)
        self.voice_combo = QComboBox()
        piper_form.addRow("Stimme", self.voice_combo)
        self.voice_language_combo = QComboBox()
        self.voice_language_combo.currentIndexChanged.connect(self.rebuild_voice_combo)
        piper_form.addRow("Sprache", self.voice_language_combo)
        voice_filter_row = QHBoxLayout()
        self.voice_female_only_checkbox = QCheckBox("nur Frauenstimmen")
        self.voice_female_only_checkbox.toggled.connect(self.rebuild_voice_combo)
        voice_filter_row.addWidget(self.voice_female_only_checkbox)
        self.voice_high_only_checkbox = QCheckBox("nur high")
        self.voice_high_only_checkbox.toggled.connect(self.rebuild_voice_combo)
        voice_filter_row.addWidget(self.voice_high_only_checkbox)
        piper_form.addRow("Filter", self._wrap(voice_filter_row))
        hidden_import_piper_button = QPushButton("Custom-Piper importieren")
        hidden_import_piper_button.clicked.connect(self.import_custom_piper_voice)
        piper_form.addRow("", hidden_import_piper_button)
        voices_layout.addWidget(piper_group)

        xtts_group = QGroupBox("XTTS-Profile")
        xtts_form = QFormLayout(xtts_group)
        self.voice_profile_combo = QComboBox()
        self.voice_profile_combo.currentIndexChanged.connect(self.refresh_selected_voice_profile)
        xtts_form.addRow("Profil", self.voice_profile_combo)
        self.voice_profile_hint = QLabel("")
        self.voice_profile_hint.setWordWrap(True)
        self.voice_profile_hint.setProperty("role", "muted")
        xtts_form.addRow("Verfügbare Profile", self.voice_profile_hint)
        self.xtts_scan_hint = QLabel("")
        self.xtts_scan_hint.setWordWrap(True)
        self.xtts_scan_hint.setProperty("role", "muted")
        xtts_form.addRow("Importstatus", self.xtts_scan_hint)
        self.voice_profile_details = QLabel("")
        self.voice_profile_details.setWordWrap(True)
        self.voice_profile_details.setProperty("role", "muted")
        xtts_form.addRow("Ausgewählt", self.voice_profile_details)
        xtts_profile_row = QHBoxLayout()
        xtts_preview_button = QPushButton("Referenz anhören")
        xtts_preview_button.clicked.connect(self.preview_xtts_reference)
        xtts_profile_row.addWidget(xtts_preview_button)
        xtts_open_button = QPushButton("Profilordner öffnen")
        xtts_open_button.clicked.connect(self.open_xtts_profile_folder)
        xtts_profile_row.addWidget(xtts_open_button)
        hidden_xtts_import_button = QPushButton("XTTS-Profile suchen")
        hidden_xtts_import_button.clicked.connect(self.import_or_open_xtts)
        xtts_profile_row.addWidget(hidden_xtts_import_button)
        hidden_xtts_starter_button = QPushButton("Starterprofile laden")
        hidden_xtts_starter_button.clicked.connect(self.install_xtts_starters)
        xtts_profile_row.addWidget(hidden_xtts_starter_button)
        xtts_form.addRow("", self._wrap(xtts_profile_row))
        xtts_layout.addWidget(xtts_group)

        profile_save_group = QGroupBox("Produktionsprofil vorbereiten")
        profile_save_form = QFormLayout(profile_save_group)
        self.preset_combo = QComboBox()
        for preset in QUALITY_PRESETS:
            self.preset_combo.addItem(preset.label, preset.preset_id)
        self.preset_combo.currentIndexChanged.connect(self.on_preset_changed)
        profile_save_form.addRow("Qualitäts-Preset", self.preset_combo)
        self.preset_description = QLabel("")
        self.preset_description.setWordWrap(True)
        self.preset_description.setProperty("role", "muted")
        profile_save_form.addRow("Preset-Info", self.preset_description)
        self.output_mode_combo = QComboBox()
        self.output_mode_combo.addItem("Eine große Enddatei", "single_file")
        self.output_mode_combo.addItem("Eine Enddatei pro Kapitel", "chapter_files")
        self.output_mode_combo.addItem("Mehrere Enddateien nach Zeit", "timed_parts")
        self.output_mode_combo.addItem("Nur Segmentdateien behalten", "segments")
        self.output_mode_combo.currentIndexChanged.connect(self.update_output_mode_controls)
        profile_save_form.addRow("Ausgabe", self.output_mode_combo)
        self.target_part_minutes_spin = QSpinBox()
        self.target_part_minutes_spin.setRange(1, 180)
        self.target_part_minutes_spin.setValue(15)
        self.target_part_minutes_spin.setSuffix(" min")
        profile_save_form.addRow("Teil-Länge", self.target_part_minutes_spin)
        self.max_chars_spin = QSpinBox()
        self.max_chars_spin.setRange(80, 1200)
        self.max_chars_spin.setValue(260)
        profile_save_form.addRow("Zeichen pro Chunk", self.max_chars_spin)
        self.keep_wav_checkbox = QCheckBox("Zwischen-WAV-Dateien behalten")
        profile_save_form.addRow("Debug-Dateien", self.keep_wav_checkbox)
        voices_layout.addWidget(profile_save_group)

        self.voice_lab_button = QPushButton("XTTS-Profilstudio")
        self.voice_lab_button.clicked.connect(self.open_voice_lab)
        xtts_profile_row.addWidget(self.voice_lab_button)
        backend_group.setVisible(False)
        piper_group.setVisible(False)
        profile_save_group.setVisible(False)
        self.xtts_profiles_tab_index = tabs.addTab(xtts_tab, "XTTS-Profile")

        jobs_tab = QWidget()
        jobs_layout = self._make_scroll_tab(jobs_tab)
        jobs_title = QLabel("5. Aufträge")
        jobs_title.setProperty("role", "hero")
        jobs_layout.addWidget(jobs_title)
        jobs_help = QLabel(
            "Hier bearbeitest du die echte Produktionswarteschlange: Status, Stufen, Kapitel, Artefakte und Logs."
        )
        jobs_help.setWordWrap(True)
        jobs_help.setProperty("role", "hint")
        jobs_layout.addWidget(jobs_help)

        state_group = QGroupBox("Aktueller Auftrag")
        state_layout = QVBoxLayout(state_group)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        state_layout.addWidget(self.progress_bar)
        self.status_label = QLabel("Bereit. Noch kein Auftrag läuft.")
        self.status_label.setWordWrap(True)
        state_layout.addWidget(self.status_label)
        self.job_runtime_summary = QLabel("Noch keine Laufzeit- oder ETA-Daten für den aktuellen Auftrag.")
        self.job_runtime_summary.setWordWrap(True)
        self.job_runtime_summary.setProperty("role", "muted")
        state_layout.addWidget(self.job_runtime_summary)
        playback_row = QHBoxLayout()
        self.play_job_button = QPushButton("▶ Start / Resume")
        self.play_job_button.clicked.connect(self.start_selected_job)
        playback_row.addWidget(self.play_job_button)
        self.pause_job_button = QPushButton("⏸ Pause")
        self.pause_job_button.clicked.connect(self.pause_selected_job)
        playback_row.addWidget(self.pause_job_button)
        self.stop_job_button = QPushButton("⏹ Stop")
        self.stop_job_button.clicked.connect(self.stop_current_job)
        playback_row.addWidget(self.stop_job_button)
        state_layout.addLayout(playback_row)
        job_actions_row = QHBoxLayout()
        open_job_folder_button = QPushButton("Jobordner öffnen")
        open_job_folder_button.clicked.connect(self.open_current_job_folder)
        job_actions_row.addWidget(open_job_folder_button)
        open_output_folder_button = QPushButton("Ausgabeordner öffnen")
        open_output_folder_button.clicked.connect(self.open_current_output_folder)
        job_actions_row.addWidget(open_output_folder_button)
        open_manifest_button = QPushButton("Manifest öffnen")
        open_manifest_button.clicked.connect(self.open_current_manifest_file)
        job_actions_row.addWidget(open_manifest_button)
        open_chapters_button = QPushButton("Kapiteldatei öffnen")
        open_chapters_button.clicked.connect(self.open_current_chapters_file)
        job_actions_row.addWidget(open_chapters_button)
        state_layout.addLayout(job_actions_row)
        self.job_summary = QPlainTextEdit()
        self.job_summary.setReadOnly(True)
        self.job_summary.setPlaceholderText(
            "Hier stehen Stufenstatus, Kapitel, Chunk-Zusammenfassung und wichtige Artefakte des gewählten Auftrags."
        )
        self.job_summary.setMinimumHeight(140)
        state_layout.addWidget(self.job_summary)
        detail_tabs = QTabWidget()
        stage_group = QGroupBox("Stufen")
        stage_layout = QVBoxLayout(stage_group)
        self.job_stage_list = QListWidget()
        stage_layout.addWidget(self.job_stage_list)
        detail_tabs.addTab(stage_group, "Stufen")
        chapter_group = QGroupBox("Kapitel")
        chapter_layout = QVBoxLayout(chapter_group)
        self.job_chapter_list = QListWidget()
        self.job_chapter_list.itemSelectionChanged.connect(self.refresh_job_selection_details)
        chapter_layout.addWidget(self.job_chapter_list)
        chapter_actions = QHBoxLayout()
        open_chapter_text_button = QPushButton("Kapiteltext öffnen")
        open_chapter_text_button.clicked.connect(self.open_selected_chapter_text)
        chapter_actions.addWidget(open_chapter_text_button)
        open_chapter_audio_button = QPushButton("Kapitelaudio öffnen")
        open_chapter_audio_button.clicked.connect(self.open_selected_chapter_audio)
        chapter_actions.addWidget(open_chapter_audio_button)
        retry_chapter_button = QPushButton("Kapitel erneut anstellen")
        retry_chapter_button.clicked.connect(self.retry_selected_chapter)
        chapter_actions.addWidget(retry_chapter_button)
        chapter_layout.addLayout(chapter_actions)
        detail_tabs.addTab(chapter_group, "Kapitel")
        chunk_group = QGroupBox("Chunks")
        chunk_layout = QVBoxLayout(chunk_group)
        self.job_chunk_list = QListWidget()
        self.job_chunk_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.job_chunk_list.itemSelectionChanged.connect(self.refresh_job_selection_details)
        chunk_layout.addWidget(self.job_chunk_list)
        chunk_actions = QHBoxLayout()
        open_chunk_text_button = QPushButton("Chunktext öffnen")
        open_chunk_text_button.clicked.connect(self.open_selected_chunk_text)
        chunk_actions.addWidget(open_chunk_text_button)
        open_chunk_audio_button = QPushButton("Chunkaudio öffnen")
        open_chunk_audio_button.clicked.connect(self.open_selected_chunk_audio)
        chunk_actions.addWidget(open_chunk_audio_button)
        chunk_layout.addLayout(chunk_actions)
        retry_actions = QHBoxLayout()
        retry_selected_button = QPushButton("Ausgewählte Chunks erneut anstellen")
        retry_selected_button.clicked.connect(self.retry_selected_chunks)
        retry_actions.addWidget(retry_selected_button)
        retry_failed_button = QPushButton("Fehlgeschlagene Chunks erneut anstellen")
        retry_failed_button.clicked.connect(self.retry_failed_chunks)
        retry_actions.addWidget(retry_failed_button)
        retry_all_button = QPushButton("Gesamten Auftrag erneut anstellen")
        retry_all_button.clicked.connect(self.retry_current_job)
        retry_actions.addWidget(retry_all_button)
        chunk_layout.addLayout(retry_actions)
        detail_tabs.addTab(chunk_group, "Chunks")
        selection_group = QGroupBox("Auswahldetails")
        selection_layout = QVBoxLayout(selection_group)
        self.job_selection_details = QPlainTextEdit()
        self.job_selection_details.setReadOnly(True)
        self.job_selection_details.setPlaceholderText("Hier erscheinen Details zum ausgewählten Kapitel oder Chunk.")
        self.job_selection_details.setMinimumHeight(120)
        selection_layout.addWidget(self.job_selection_details)
        detail_tabs.addTab(selection_group, "Auswahl")
        logs_group = QGroupBox("Job-Logs")
        logs_layout = QVBoxLayout(logs_group)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setPlaceholderText("Hier erscheinen die letzten Job-Logs und Statusmeldungen.")
        self.details.setMinimumHeight(180)
        logs_layout.addWidget(self.details)
        detail_tabs.addTab(logs_group, "Logs")
        state_layout.addWidget(detail_tabs)
        jobs_layout.addWidget(state_group)

        queue_group = QGroupBox("Queue & gespeicherte Vorschauen")
        queue_group_layout = QVBoxLayout(queue_group)
        self.queue_details = QPlainTextEdit()
        self.queue_details.setReadOnly(True)
        self.queue_details.setPlaceholderText("Hier steht die eigentliche Verarbeitungswarteschlange.")
        queue_group_layout.addWidget(self.queue_details)
        self.queue_runtime_summary = QLabel("Noch keine Queue-Prognose verfügbar.")
        self.queue_runtime_summary.setWordWrap(True)
        self.queue_runtime_summary.setProperty("role", "muted")
        queue_group_layout.addWidget(self.queue_runtime_summary)
        self.preview_sessions_summary = QPlainTextEdit()
        self.preview_sessions_summary.setReadOnly(True)
        self.preview_sessions_summary.setPlaceholderText(
            "Hier stehen gespeicherte Hörproben und zuletzt gerenderte Vorschauen."
        )
        queue_group_layout.addWidget(self.preview_sessions_summary)
        jobs_layout.addWidget(queue_group)

        queue_actions_group = QGroupBox("Auftragsaktionen")
        queue_actions_form = QFormLayout(queue_actions_group)
        queue_actions_row = QHBoxLayout()
        self.run_next_button = QPushButton("Nächsten Queue-Job starten")
        self.run_next_button.clicked.connect(self.start_next_queued_job)
        queue_actions_row.addWidget(self.run_next_button)
        self.priority_button = QPushButton("Priorität für Auswahl speichern")
        self.priority_button.clicked.connect(self.apply_priority_to_selected)
        queue_actions_row.addWidget(self.priority_button)
        queue_actions_form.addRow("", self._wrap(queue_actions_row))
        jobs_layout.addWidget(queue_actions_group)

        finished_tab = QWidget()
        finished_root_layout = self._make_scroll_tab(finished_tab)
        finished_title = QLabel("5. Fertige Bücher")
        finished_title.setProperty("role", "hero")
        finished_root_layout.addWidget(finished_title)
        finished_help = QLabel(
            "Hier öffnest du fertige Hörbücher, löschst abgeschlossene Projekte und ergänzt oder korrigierst die finalen Metadaten vor dem Weitergeben."
        )
        finished_help.setWordWrap(True)
        finished_help.setProperty("role", "hint")
        finished_root_layout.addWidget(finished_help)

        finished_group = QGroupBox("Fertige Hörbücher")
        finished_layout = QVBoxLayout(finished_group)
        self.finished_books_list = QListWidget()
        self.finished_books_list.setMinimumHeight(140)
        self.finished_books_list.itemSelectionChanged.connect(self.on_finished_book_selected)
        finished_layout.addWidget(self.finished_books_list)
        finished_actions = QHBoxLayout()
        open_finished_audio_button = QPushButton("Hörbuch öffnen")
        open_finished_audio_button.clicked.connect(self.open_selected_finished_audio)
        finished_actions.addWidget(open_finished_audio_button)
        download_finished_audio_button = QPushButton("Hörbuch herunterladen")
        download_finished_audio_button.clicked.connect(self.download_selected_finished_audio)
        finished_actions.addWidget(download_finished_audio_button)
        open_finished_folder_button = QPushButton("Ordner öffnen")
        open_finished_folder_button.clicked.connect(self.open_selected_finished_folder)
        finished_actions.addWidget(open_finished_folder_button)
        delete_finished_job_button = QPushButton("Projekt löschen")
        delete_finished_job_button.clicked.connect(self.delete_selected_finished_job)
        finished_actions.addWidget(delete_finished_job_button)
        finished_layout.addLayout(finished_actions)
        finished_meta_group = QGroupBox("Abschluss: Metadaten & Tags")
        finished_meta_form = QFormLayout(finished_meta_group)
        self.finished_meta_title_edit = QLineEdit()
        finished_meta_form.addRow("Titel", self.finished_meta_title_edit)
        self.finished_meta_author_edit = QLineEdit()
        finished_meta_form.addRow("Autor", self.finished_meta_author_edit)
        self.finished_meta_narrator_edit = QLineEdit()
        finished_meta_form.addRow("Sprecher", self.finished_meta_narrator_edit)
        self.finished_meta_genre_edit = QLineEdit()
        finished_meta_form.addRow("Genre", self.finished_meta_genre_edit)
        self.finished_meta_language_edit = QLineEdit()
        finished_meta_form.addRow("Sprachtag", self.finished_meta_language_edit)
        self.finished_meta_publisher_edit = QLineEdit()
        finished_meta_form.addRow("Verlag", self.finished_meta_publisher_edit)
        self.finished_meta_year_edit = QLineEdit()
        finished_meta_form.addRow("Jahr", self.finished_meta_year_edit)
        self.finished_meta_subject_edit = QLineEdit()
        finished_meta_form.addRow("Schlagwörter", self.finished_meta_subject_edit)
        self.finished_meta_isbn_edit = QLineEdit()
        finished_meta_form.addRow("ISBN", self.finished_meta_isbn_edit)
        self.finished_meta_comment_edit = QPlainTextEdit()
        self.finished_meta_comment_edit.setMinimumHeight(90)
        finished_meta_form.addRow("Kommentar", self.finished_meta_comment_edit)
        finished_meta_actions = QHBoxLayout()
        self.finished_metadata_guess_button = QPushButton("Automatisch erkennen")
        self.finished_metadata_guess_button.clicked.connect(self.populate_finished_metadata_from_filename)
        finished_meta_actions.addWidget(self.finished_metadata_guess_button)
        self.finished_metadata_search_button = QPushButton("Online-Suche verfeinern")
        self.finished_metadata_search_button.clicked.connect(self.search_finished_metadata_online)
        finished_meta_actions.addWidget(self.finished_metadata_search_button)
        self.finished_metadata_apply_button = QPushButton("Ausgewählten Treffer übernehmen")
        self.finished_metadata_apply_button.clicked.connect(self.apply_finished_metadata_result)
        finished_meta_actions.addWidget(self.finished_metadata_apply_button)
        self.finished_metadata_save_button = QPushButton("Tags speichern")
        self.finished_metadata_save_button.clicked.connect(self.save_finished_job_metadata)
        finished_meta_actions.addWidget(self.finished_metadata_save_button)
        finished_meta_form.addRow("", self._wrap(finished_meta_actions))
        self.finished_metadata_status_label = QLabel("Wähle unten ein fertiges Hörbuch, um Metadaten zu prüfen oder nachzutragen.")
        self.finished_metadata_status_label.setWordWrap(True)
        self.finished_metadata_status_label.setProperty("role", "muted")
        finished_meta_form.addRow("Status", self.finished_metadata_status_label)
        self.finished_metadata_results_list = QListWidget()
        self.finished_metadata_results_list.setMinimumHeight(100)
        finished_meta_form.addRow("Treffer", self.finished_metadata_results_list)
        finished_layout.addWidget(finished_meta_group)
        finished_root_layout.addWidget(finished_group)

        tabs.addTab(jobs_tab, "Aufträge")
        tabs.addTab(finished_tab, "Fertige Bücher")

        diagnostics_tab = QWidget()
        diagnostics_layout_root = self._make_scroll_tab(diagnostics_tab)
        diagnostics_title = QLabel("6. Diagnose")
        diagnostics_title.setProperty("role", "hero")
        diagnostics_layout_root.addWidget(diagnostics_title)
        diagnostics_help = QLabel(
            "Hier prüfst du Laufzeit, CUDA-/XTTS-Status, Arbeitsordner und Performance-Logging."
        )
        diagnostics_help.setWordWrap(True)
        diagnostics_help.setProperty("role", "hint")
        diagnostics_layout_root.addWidget(diagnostics_help)

        diagnostics_group = QGroupBox("Laufzeit- und Systemzustand")
        diagnostics_layout = QVBoxLayout(diagnostics_group)
        self.system_usage_label = QLabel("CPU -, RAM -, CUDA/GPU -")
        self.system_usage_label.setWordWrap(True)
        self.system_usage_label.setProperty("role", "muted")
        diagnostics_layout.addWidget(self.system_usage_label)
        self.diagnostics_summary = QPlainTextEdit()
        self.diagnostics_summary.setReadOnly(True)
        self.diagnostics_summary.setPlaceholderText(
            "Hier stehen Pfade, Runtime-Zustand, Profil-/Jobzahlen und Performance-Logging."
        )
        self.diagnostics_summary.setMinimumHeight(220)
        diagnostics_layout.addWidget(self.diagnostics_summary)
        diagnostics_row = QHBoxLayout()
        refresh_diagnostics_button = QPushButton("Diagnose aktualisieren")
        refresh_diagnostics_button.clicked.connect(self.refresh_diagnostics_summary_with_probe)
        diagnostics_row.addWidget(refresh_diagnostics_button)
        self.diagnostics_xtts_setup_button = QPushButton("XTTS optional einrichten")
        self.diagnostics_xtts_setup_button.clicked.connect(self.open_xtts_setup_dialog)
        diagnostics_row.addWidget(self.diagnostics_xtts_setup_button)
        open_workspace_button = QPushButton("Arbeitsbereich öffnen")
        open_workspace_button.clicked.connect(lambda: self.open_path(self.paths.workspace))
        diagnostics_row.addWidget(open_workspace_button)
        open_logs_button = QPushButton("Logs öffnen")
        open_logs_button.clicked.connect(lambda: self.open_path(self.paths.logs))
        diagnostics_row.addWidget(open_logs_button)
        open_root_button = QPushButton("Appordner öffnen")
        open_root_button.clicked.connect(lambda: self.open_path(self.paths.root))
        diagnostics_row.addWidget(open_root_button)
        diagnostics_layout.addLayout(diagnostics_row)
        diagnostics_layout_root.addWidget(diagnostics_group)

        tabs.addTab(diagnostics_tab, "Diagnose")

        settings_tab = QWidget()
        settings_layout = self._make_scroll_tab(settings_tab)
        settings_title = QLabel("7. Einstellungen")
        settings_title.setProperty("role", "hero")
        settings_layout.addWidget(settings_title)
        settings_help = QLabel(
            "Hier steuerst du Logging, App-Zustand und wichtige Arbeitsordner. Produktionsprofile und Jobs bleiben in ihren eigenen Bereichen."
        )
        settings_help.setWordWrap(True)
        settings_help.setProperty("role", "hint")
        settings_layout.addWidget(settings_help)

        maintenance_group = QGroupBox("App-Zustand und Logging")
        maintenance_form = QFormLayout(maintenance_group)
        self.ui_language_combo = QComboBox()
        for code, label in ui_language_choices(self.ui_language):
            self.ui_language_combo.addItem(label, code)
        self.ui_language_combo.currentIndexChanged.connect(self.on_ui_language_changed)
        maintenance_form.addRow(self._tr("settings.ui_language.label"), self.ui_language_combo)
        self.ui_language_hint = QLabel(self._tr("settings.ui_language.hint"))
        self.ui_language_hint.setWordWrap(True)
        self.ui_language_hint.setProperty("role", "muted")
        maintenance_form.addRow("", self.ui_language_hint)
        self.debug_logging_checkbox = QCheckBox("Sehr detailliertes Debug-Logging")
        self.debug_logging_checkbox.setChecked(self.app_settings.debug_logging)
        self.debug_logging_checkbox.toggled.connect(self.toggle_debug_logging)
        maintenance_form.addRow("Logging", self.debug_logging_checkbox)
        self.xtts_processing_mode_combo = QComboBox()
        self.xtts_processing_mode_combo.addItem("Automatisch entscheiden", "auto")
        self.xtts_processing_mode_combo.addItem("Immer seriell", "serial")
        self.xtts_processing_mode_combo.addItem("Parallel CPU-Postprozess bevorzugen", "parallel_cpu_postprocess")
        self.xtts_processing_mode_combo.currentIndexChanged.connect(self.on_xtts_processing_mode_changed)
        maintenance_form.addRow("XTTS-Verarbeitung", self.xtts_processing_mode_combo)
        self.xtts_processing_mode_hint = QLabel(
            "Automatisch lernt aus vergangenen Läufen. Seriell ist der konservative Pfad, "
            "Parallel nutzt bei CUDA freie CPU-Kapazität für MP3-Nachbearbeitung."
        )
        self.xtts_processing_mode_hint.setWordWrap(True)
        self.xtts_processing_mode_hint.setProperty("role", "muted")
        maintenance_form.addRow("Modus-Hinweis", self.xtts_processing_mode_hint)
        self.language_restart_hint = QLabel(self._tr("settings.ui_language.note"))
        self.language_restart_hint.setWordWrap(True)
        self.language_restart_hint.setProperty("role", "muted")
        maintenance_form.addRow("", self.language_restart_hint)
        maintenance_row = QHBoxLayout()
        reset_button = QPushButton("App-Zustand zurücksetzen")
        reset_button.clicked.connect(self.reset_application_state)
        maintenance_row.addWidget(reset_button)
        maintenance_form.addRow("", self._wrap(maintenance_row))
        settings_layout.addWidget(maintenance_group)

        files_group = QGroupBox("Arbeitsdateien")
        files_layout = QFormLayout(files_group)
        files_layout.addRow("App-Einstellungen", QLabel(str(self.paths.app_settings_file)))
        files_layout.addRow("Profilordner", QLabel(str(self.paths.voice_settings)))
        settings_files_row = QHBoxLayout()
        open_app_settings_button = QPushButton("App-Einstellungen öffnen")
        open_app_settings_button.clicked.connect(lambda: self.open_path(self.paths.app_settings_file))
        settings_files_row.addWidget(open_app_settings_button)
        open_profile_settings_button = QPushButton("Profilordner öffnen")
        open_profile_settings_button.clicked.connect(lambda: self.open_path(self.paths.voice_settings))
        settings_files_row.addWidget(open_profile_settings_button)
        open_preview_sessions_button = QPushButton("Profilstudio-Sessions öffnen")
        open_preview_sessions_button.clicked.connect(lambda: self.open_path(self.paths.preview_sessions))
        settings_files_row.addWidget(open_preview_sessions_button)
        files_layout.addRow("", self._wrap(settings_files_row))
        settings_layout.addWidget(files_group)

        tabs.addTab(settings_tab, "Einstellungen")

        splitter.addWidget(right)
        splitter.setSizes([300, 1020])
        self.apply_default_controls()
        self.on_preset_changed()
        self.on_backend_changed()

    def _wrap(self, layout: QHBoxLayout) -> QWidget:
        widget = QWidget()
        widget.setLayout(layout)
        return widget

    def show_benchmark_tab(self, focus_assistant: bool = False) -> None:
        self.main_tabs.setCurrentIndex(self.benchmark_tab_index)
        if focus_assistant:
            self.status_label.setText(
                "Benchmark-Studio geöffnet. Starte dort den Profil-Assistenten für eine neue Testreihe."
            )

    def _empty_source_structure(self, summary: str) -> DocumentStructure:
        return DocumentStructure(
            source_type="",
            chapter_count=0,
            chapter_titles=[],
            supports_chapter_files=False,
            summary=summary,
            analysis_status="idle",
        )

    def _source_structure_summary_text(self, structure: DocumentStructure) -> str:
        status_prefix = {
            "idle": self._tr("source.analysis.idle"),
            "supported": self._tr("source.analysis.supported", count=structure.chapter_count),
            "unsupported": self._tr("source.analysis.unsupported"),
            "error": self._tr("source.analysis.error"),
        }.get(structure.analysis_status, structure.summary)
        lines = [status_prefix, structure.summary]
        if structure.detection_method:
            detection_labels = {
                "pdf_outline": "Erkennungspfad: PDF-Lesezeichen / Inhaltsverzeichnis",
                "pdf_page_headings": "Erkennungspfad: PDF-Seitenanfänge / Überschriften",
                "epub_spine": "Erkennungspfad: EPUB-Spine / HTML-Kapitel",
                "flat_text": "Erkennungspfad: reine Textüberschriften",
                "error": "Erkennungspfad: Fehler",
            }
            lines.append(detection_labels.get(structure.detection_method, f"Erkennungspfad: {structure.detection_method}"))
        if structure.chapter_titles:
            preview = ", ".join(structure.chapter_titles[:3])
            if len(structure.chapter_titles) > 3:
                preview += ", …"
            lines.append(f"Erkannte Kapitel: {preview}")
        if structure.analysis_notes:
            lines.extend(structure.analysis_notes[:3])
        return "\n".join(lines)

    def refresh_source_analysis(self) -> None:
        self.source_structures = {}
        self.source_list.clear()
        if not self.selected_source_files:
            self.source_structure = self._empty_source_structure("Noch keine Quelle gewählt.")
            self.source_count_label.setText(self._tr("source.count.none"))
        else:
            self.source_analysis_label.setText({
                "de": "Kapitelanalyse läuft …",
                "en": "Chapter analysis running …",
                "es": "Analizando capítulos …",
                "pt": "Analisando capítulos …",
            }.get(self.ui_language, "Chapter analysis running …"))
            for source in self.selected_source_files:
                if not source.exists():
                    structure = self._empty_source_structure(
                        "Datei noch nicht gefunden. Die Kapitelerkennung startet, sobald der Pfad gültig ist."
                    )
                    structure.source_type = source.suffix.lower().lstrip(".")
                    structure.analysis_status = "error"
                    structure.error = f"Datei nicht gefunden: {source}"
                else:
                    structure = DocumentStructure(**self.service.analyze_source(source))
                self.source_structures[str(source)] = structure
            self.source_structure = self.source_structures.get(str(self.selected_source_files[0]), self._empty_source_structure("Noch keine Quelle gewählt."))
            supported_count = sum(1 for structure in self.source_structures.values() if structure.supports_chapter_files)
            total_count = len(self.selected_source_files)
            self.source_count_label.setText(self._tr("source.count", total=total_count, supported=supported_count))
            self.refresh_source_list()
            if total_count == 1:
                self.source_analysis_label.setText(self._source_structure_summary_text(self.source_structure))
            else:
                self.source_analysis_label.setText(
                    self._tr(
                        "source.analysis.multi",
                        total=total_count,
                        supported=supported_count,
                        fallback=total_count - supported_count,
                    )
                )
        if not self.selected_source_files:
            self.source_analysis_label.setText(self._source_structure_summary_text(self.source_structure))
        self.apply_job_output_mode_availability()

    def refresh_source_list(self) -> None:
        self.source_list.clear()
        requested_mode = self.job_output_mode_requested or "single_file"
        for source in self.selected_source_files:
            structure = self.source_structures.get(str(source), self._empty_source_structure("Noch keine Analyse verfügbar."))
            actual_mode = self._resolved_output_mode_for_structure(requested_mode, structure)
            chapter_text = (
                {
                    "de": f"Kapitel {structure.chapter_count}",
                    "en": f"chapters {structure.chapter_count}",
                    "es": f"capítulos {structure.chapter_count}",
                    "pt": f"capítulos {structure.chapter_count}",
                }.get(self.ui_language, f"chapters {structure.chapter_count}")
                if structure.supports_chapter_files
                else {
                    "de": "keine Kapiteldateien",
                    "en": "no chapter files",
                    "es": "sin archivos por capítulo",
                    "pt": "sem arquivos por capítulo",
                }.get(self.ui_language, "no chapter files")
            )
            item = QListWidgetItem(
                f"{source.name} | {source.suffix.lower().lstrip('.') or '-'} | {chapter_text} | "
                + {
                    "de": "Ausgabe",
                    "en": "output",
                    "es": "salida",
                    "pt": "saída",
                }.get(self.ui_language, "output")
                + f" {self._output_mode_label(actual_mode, self.target_part_minutes_spin.value())}"
            )
            item.setToolTip(f"{source}\n{self._source_structure_summary_text(structure)}")
            self.source_list.addItem(item)

    def set_selected_source_files(self, sources: list[Path]) -> None:
        unique_sources: list[Path] = []
        seen: set[Path] = set()
        for source in sources:
            normalized = source.expanduser().resolve()
            if normalized in seen:
                continue
            seen.add(normalized)
            unique_sources.append(normalized)
        self.selected_source_files = unique_sources
        if not unique_sources:
            summary = ""
        elif len(unique_sources) == 1:
            summary = str(unique_sources[0])
        else:
            summary = f"{len(unique_sources)} Dateien ausgewählt"
        self.source_edit.blockSignals(True)
        try:
            self.source_edit.setText(summary)
        finally:
            self.source_edit.blockSignals(False)
        self.refresh_source_analysis()
        self.refresh_metadata_ui()
        if len(unique_sources) == 1:
            self.populate_metadata_from_filename(auto_run=True)

    def clear_selected_source_files(self) -> None:
        self.set_selected_source_files([])

    def _active_metadata_source(self) -> Path | None:
        return self.selected_source_files[0] if self.selected_source_files else None

    def _apply_metadata_payload_to_create_fields(
        self,
        payload: dict[str, object],
        *,
        extended: dict[str, object] | None = None,
        overwrite_title: bool = True,
    ) -> None:
        title = str(payload.get("title") or "")
        if overwrite_title and title:
            self.meta_title_edit.setText(title)
        elif overwrite_title and not title and len(self.selected_source_files) == 1 and self.selected_source_files:
            self.meta_title_edit.setText(self.selected_source_files[0].stem)
        author = str(payload.get("author") or "")
        if author:
            self.meta_author_edit.setText(author)
        narrator = str(payload.get("narrator") or "")
        if narrator and not self.meta_narrator_edit.text().strip():
            self.meta_narrator_edit.setText(narrator)
        genre = str(payload.get("genre") or "")
        if genre:
            self.meta_genre_edit.setText(genre)
        language = str(payload.get("language") or "")
        if language:
            self.meta_language_tag_edit.setText(language)
        comment = str(payload.get("comment") or "")
        if comment and not self.meta_comment_edit.toPlainText().strip():
            self.meta_comment_edit.setPlainText(comment)
        extended = extended or {}
        publisher = str(extended.get("publisher") or payload.get("publisher") or "")
        if publisher:
            self.meta_publisher_edit.setText(publisher)
        year = str(extended.get("year") or payload.get("year") or "")
        if year and year != "0":
            self.meta_year_edit.setText(year)
        subjects = extended.get("subjects") or payload.get("subjects") or ""
        if isinstance(subjects, list):
            subjects_text = ", ".join(str(item) for item in subjects if item)
        else:
            subjects_text = str(subjects or "")
        if subjects_text:
            self.meta_subject_edit.setText(subjects_text)
        identifiers = extended.get("identifiers") or payload.get("identifiers") or []
        isbn = str(payload.get("isbn") or extended.get("isbn") or "")
        if not isbn and isinstance(identifiers, list):
            for identifier in identifiers:
                identifier_text = str(identifier or "").strip()
                if identifier_text:
                    isbn = identifier_text
                    break
        if isbn:
            self.meta_isbn_edit.setText(isbn)

    def _apply_metadata_payload_to_finished_fields(
        self,
        payload: dict[str, object],
        *,
        extended: dict[str, object] | None = None,
    ) -> None:
        title = str(payload.get("title") or "")
        if title:
            self.finished_meta_title_edit.setText(title)
        author = str(payload.get("author") or "")
        if author:
            self.finished_meta_author_edit.setText(author)
        narrator = str(payload.get("narrator") or "")
        if narrator and not self.finished_meta_narrator_edit.text().strip():
            self.finished_meta_narrator_edit.setText(narrator)
        genre = str(payload.get("genre") or "")
        if genre:
            self.finished_meta_genre_edit.setText(genre)
        language = str(payload.get("language") or "")
        if language:
            self.finished_meta_language_edit.setText(language)
        comment = str(payload.get("comment") or "")
        if comment and not self.finished_meta_comment_edit.toPlainText().strip():
            self.finished_meta_comment_edit.setPlainText(comment)
        extended = extended or {}
        publisher = str(extended.get("publisher") or payload.get("publisher") or "")
        if publisher:
            self.finished_meta_publisher_edit.setText(publisher)
        year = str(extended.get("year") or payload.get("year") or "")
        if year and year != "0":
            self.finished_meta_year_edit.setText(year)
        subjects = extended.get("subjects") or payload.get("subjects") or ""
        if isinstance(subjects, list):
            subjects_text = ", ".join(str(item) for item in subjects if item)
        else:
            subjects_text = str(subjects or "")
        if subjects_text:
            self.finished_meta_subject_edit.setText(subjects_text)
        identifiers = extended.get("identifiers") or payload.get("identifiers") or []
        isbn = str(payload.get("isbn") or extended.get("isbn") or "")
        if not isbn and isinstance(identifiers, list):
            for identifier in identifiers:
                identifier_text = str(identifier or "").strip()
                if identifier_text:
                    isbn = identifier_text
                    break
        if isbn:
            self.finished_meta_isbn_edit.setText(isbn)

    def _populate_metadata_results_list(self, target: QListWidget, suggestions: list[dict[str, object]]) -> None:
        target.clear()
        for entry in suggestions:
            year = f" ({entry.get('year')})" if entry.get("year") else ""
            author = str(entry.get("author") or "-")
            confidence = f"{float(entry.get('confidence') or 0.0):.2f}"
            source = str(entry.get("source") or "metadata")
            item = QListWidgetItem(f"{entry.get('title')}{year} | {author} | {source} | {confidence}")
            item.setData(Qt.UserRole, entry)
            item.setToolTip(json.dumps(entry, indent=2, ensure_ascii=False))
            target.addItem(item)
        if target.count():
            target.setCurrentRow(0)

    def _metadata_confidence_band(self, confidence: float) -> str:
        if confidence >= 0.80:
            return "high"
        if confidence >= 0.55:
            return "medium"
        return "low"

    def refresh_metadata_ui(self) -> None:
        source = self._active_metadata_source()
        single_source = len(self.selected_source_files) == 1 and source is not None
        self.meta_title_edit.setEnabled(single_source)
        self.metadata_search_button.setEnabled(single_source)
        self.metadata_apply_button.setEnabled(single_source)
        self.metadata_results_list.setEnabled(single_source)
        if not source:
            self.metadata_status_label.setText({
                "de": "Noch keine Quelle gewählt. Danach können Metadaten vorgeschlagen oder online gesucht werden.",
                "en": "No source selected yet. After that you can suggest metadata or search online.",
                "es": "Todavía no se ha seleccionado ninguna fuente. Después podrás sugerir metadatos o buscarlos en línea.",
                "pt": "Nenhuma fonte foi selecionada ainda. Depois disso você poderá sugerir metadados ou pesquisar online.",
            }.get(self.ui_language, "No source selected yet. After that you can suggest metadata or search online."))
            self.metadata_results_list.clear()
            return
        if not self.meta_language_tag_edit.text().strip():
            structure = self.source_structures.get(str(source))
            language_hint = preferred_content_language_code(self.ui_language).split("_", 1)[0]
            if structure and structure.source_type:
                self.meta_language_tag_edit.setText(language_hint)
        if single_source:
            self.metadata_status_label.setText({
                "de": f"Metadaten für {source.name}: Dateiname wurde analysiert. Optional kannst du zusätzlich bei Open Library suchen.",
                "en": f"Metadata for {source.name}: the file name has been analyzed. You can optionally search Open Library too.",
                "es": f"Metadatos para {source.name}: se analizó el nombre del archivo. También puedes buscar en Open Library.",
                "pt": f"Metadados para {source.name}: o nome do arquivo foi analisado. Você também pode pesquisar no Open Library.",
            }.get(self.ui_language, f"Metadata for {source.name}: the file name has been analyzed. You can optionally search Open Library too."))
        else:
            self.metadata_status_label.setText({
                "de": "Mehrere Quellen ausgewählt. Titel bleiben pro Datei individuell; gemeinsame Metadaten wie Autor, Sprecher, Genre und Kommentar gelten für alle Jobs.",
                "en": "Multiple sources selected. Titles stay individual per file; shared metadata like author, narrator, genre, and comment are applied to all jobs.",
                "es": "Se seleccionaron varias fuentes. Los títulos siguen siendo individuales por archivo; los metadatos comunes como autor, narrador, género y comentario se aplican a todos los trabajos.",
                "pt": "Várias fontes foram selecionadas. Os títulos permanecem individuais por arquivo; metadados compartilhados como autor, narrador, gênero e comentário são aplicados a todas as tarefas.",
            }.get(self.ui_language, "Multiple sources selected. Titles stay individual per file; shared metadata like author, narrator, genre, and comment are applied to all jobs."))
            self.metadata_results_list.clear()

    def populate_metadata_from_filename(self, auto_run: bool = False) -> None:
        source = self._active_metadata_source()
        if source is None:
            return
        try:
            suggestions = self.service.metadata_suggestions(source)
        except Exception as exc:
            self.metadata_status_label.setText(
                {
                    "de": f"Automatische Metadatenerkennung fehlgeschlagen: {exc}",
                    "en": f"Automatic metadata detection failed: {exc}",
                    "es": f"La detección automática de metadatos falló: {exc}",
                    "pt": f"A detecção automática de metadados falhou: {exc}",
                }.get(self.ui_language, f"Automatic metadata detection failed: {exc}")
            )
            return
        guessed = suggestions.get("guessed") or {}
        extended = suggestions.get("extended_book_metadata") or {}
        results = suggestions.get("results") or suggestions.get("candidates") or []
        if isinstance(results, list):
            self._populate_metadata_results_list(
                self.metadata_results_list,
                [entry for entry in results if isinstance(entry, dict)],
            )
        confidence = float(suggestions.get("confidence") or 0.0)
        title_source = str(suggestions.get("title_source") or "-")
        author_source = str(suggestions.get("author_source") or "-")
        confidence_band = self._metadata_confidence_band(confidence)
        should_apply = confidence_band in {"high", "medium"}
        if should_apply and isinstance(guessed, dict):
            self._apply_metadata_payload_to_create_fields(
                guessed,
                extended=extended if isinstance(extended, dict) else {},
                overwrite_title=len(self.selected_source_files) == 1,
            )
        if confidence_band == "high":
            message = {
                "de": "Metadaten automatisch übernommen",
                "en": "Metadata applied automatically",
                "es": "Metadatos aplicados automáticamente",
                "pt": "Metadados aplicados automaticamente",
            }.get(self.ui_language, "Metadata applied automatically")
        elif confidence_band == "medium":
            message = {
                "de": "Metadaten automatisch vorgeschlagen. Bitte kurz prüfen.",
                "en": "Metadata suggested automatically. Please review briefly.",
                "es": "Metadatos sugeridos automáticamente. Revísalos brevemente.",
                "pt": "Metadados sugeridos automaticamente. Revise rapidamente.",
            }.get(self.ui_language, "Metadata suggested automatically. Please review briefly.")
        else:
            message = {
                "de": "Automatik unsicher. Bitte Trefferliste prüfen und manuell übernehmen.",
                "en": "Automatic detection is unsure. Review the match list and apply one manually.",
                "es": "La detección automática es incierta. Revisa la lista y aplica un resultado manualmente.",
                "pt": "A detecção automática é incerta. Revise a lista e aplique um resultado manualmente.",
            }.get(self.ui_language, "Automatic detection is unsure. Review the match list and apply one manually.")
        self.metadata_status_label.setText(
            f"{message}. "
            + {
                "de": f"Konfidenz {confidence:.2f}, Titelquelle {title_source}, Autorquelle {author_source}.",
                "en": f"Confidence {confidence:.2f}, title source {title_source}, author source {author_source}.",
                "es": f"Confianza {confidence:.2f}, origen del título {title_source}, origen del autor {author_source}.",
                "pt": f"Confiança {confidence:.2f}, origem do título {title_source}, origem do autor {author_source}.",
            }.get(self.ui_language, f"Confidence {confidence:.2f}, title source {title_source}, author source {author_source}.")
        )

    def search_metadata_online(self) -> None:
        source = self._active_metadata_source()
        if source is None or len(self.selected_source_files) != 1:
            return
        query_title = self.meta_title_edit.text().strip()
        query_author = self.meta_author_edit.text().strip()
        try:
            suggestions = self.service.search_book_metadata(
                title=query_title,
                author=query_author,
                query=f"{query_title} {query_author}".strip(),
                limit=5,
            )
        except Exception as exc:
            self.metadata_status_label.setText(
                {
                    "de": f"Metadatensuche fehlgeschlagen: {exc}",
                    "en": f"Metadata search failed: {exc}",
                    "es": f"La búsqueda de metadatos falló: {exc}",
                    "pt": f"A busca de metadados falhou: {exc}",
                }.get(self.ui_language, f"Metadata search failed: {exc}")
            )
            return
        self._populate_metadata_results_list(self.metadata_results_list, suggestions)
        self.metadata_status_label.setText({
            "de": f"Online-Suche abgeschlossen: {len(suggestions)} Treffer.",
            "en": f"Online search finished: {len(suggestions)} result(s).",
            "es": f"Búsqueda online completada: {len(suggestions)} resultado(s).",
            "pt": f"Busca online concluída: {len(suggestions)} resultado(s).",
        }.get(self.ui_language, f"Online search finished: {len(suggestions)} result(s)."))

    def apply_best_metadata_result(self) -> None:
        item = self.metadata_results_list.currentItem()
        if item is None and self.metadata_results_list.count():
            item = self.metadata_results_list.item(0)
        if item is None:
            return
        entry = item.data(Qt.UserRole) or {}
        if isinstance(entry, dict):
            self._apply_metadata_payload_to_create_fields(entry, extended=entry, overwrite_title=self.meta_title_edit.isEnabled())
        self.metadata_status_label.setText({
            "de": "Metadaten aus dem ausgewählten Treffer übernommen.",
            "en": "Metadata from the selected result has been applied.",
            "es": "Se aplicaron los metadatos del resultado seleccionado.",
            "pt": "Os metadados do resultado selecionado foram aplicados.",
        }.get(self.ui_language, "Metadata from the selected result has been applied."))

    def _metadata_payload_for_source(self, source: Path) -> dict[str, str]:
        title = self.meta_title_edit.text().strip() if len(self.selected_source_files) == 1 else ""
        narrator = self.meta_narrator_edit.text().strip()
        year_text = self.meta_year_edit.text().strip()
        year_value = int(year_text) if year_text.isdigit() else 0
        payload = {
            "title": title,
            "album": title,
            "artist": narrator,
            "album_artist": narrator,
            "narrator": narrator,
            "author": self.meta_author_edit.text().strip(),
            "genre": self.meta_genre_edit.text().strip() or "Audiobook",
            "language": self.meta_language_tag_edit.text().strip() or preferred_content_language_code(self.ui_language).split("_", 1)[0],
            "publisher": self.meta_publisher_edit.text().strip(),
            "year": year_value,
            "subject": self.meta_subject_edit.text().strip(),
            "isbn": self.meta_isbn_edit.text().strip(),
            "description": self.meta_comment_edit.toPlainText().strip(),
            "comment": self.meta_comment_edit.toPlainText().strip(),
        }
        return {key: value for key, value in payload.items() if value}

    def _resolved_output_mode_for_structure(self, requested_mode: str, structure: DocumentStructure) -> str:
        actual_mode = requested_mode or "single_file"
        if actual_mode == "segments":
            actual_mode = "single_file"
        if actual_mode == "chapter_files" and not structure.supports_chapter_files:
            actual_mode = "single_file"
        return actual_mode

    def on_job_output_mode_radio_toggled(self, mode: str, checked: bool) -> None:
        if not checked or self._syncing_job_output_mode:
            return
        self.apply_job_output_mode_availability(preferred_mode=mode)

    def selected_job_output_mode(self) -> str:
        return self.job_output_mode or "single_file"

    def apply_job_output_mode_availability(self, *, preferred_mode: str | None = None) -> None:
        if preferred_mode:
            self.job_output_mode_requested = preferred_mode
        desired_mode = self.job_output_mode_requested or self.selected_job_output_mode() or "single_file"
        structures = list(self.source_structures.values()) if self.source_structures else ([self.source_structure] if self.source_structure.analysis_status != "idle" else [])
        total_sources = len(self.selected_source_files)
        supported_sources = sum(1 for structure in structures if structure.supports_chapter_files)
        if total_sources <= 1:
            chapter_available = supported_sources == 1
        else:
            chapter_available = supported_sources > 0
        self.job_output_chapter_radio.setEnabled(chapter_available)
        if total_sources <= 1:
            chapter_tooltip = (
                "Kapitel erkannt: diese Quelle kann als eine Datei pro Kapitel exportiert werden."
                if chapter_available
                else "Diese Quelle hat keine stabile Kapitelstruktur. Kapiteldateien bleiben deaktiviert."
            )
        else:
            chapter_tooltip = (
                f"{supported_sources}/{total_sources} Quellen unterstützen Kapiteldateien. "
                "Quellen ohne Kapitelstruktur fallen automatisch auf eine Enddatei zurück."
                if chapter_available
                else "Keine der ausgewählten Quellen hat eine stabile Kapitelstruktur."
            )
        self.job_output_chapter_radio.setToolTip(chapter_tooltip)
        actual_mode = desired_mode
        if actual_mode == "segments":
            actual_mode = "single_file"
        if actual_mode == "chapter_files" and not chapter_available:
            actual_mode = "single_file"
        self.job_output_mode = actual_mode
        radio_map = {
            "single_file": self.job_output_single_radio,
            "chapter_files": self.job_output_chapter_radio,
            "timed_parts": self.job_output_timed_radio,
        }
        self._syncing_job_output_mode = True
        try:
            target_radio = radio_map.get(actual_mode, self.job_output_single_radio)
            target_radio.setChecked(True)
        finally:
            self._syncing_job_output_mode = False

        hint_parts = []
        if chapter_available and total_sources > 1:
            hint_parts.append(self._tr("output.chapter.enabled.multi", supported=supported_sources, total=total_sources))
        elif chapter_available:
            hint_parts.append(self._tr("output.chapter.enabled.single"))
        else:
            hint_parts.append(self._tr("output.chapter.disabled"))
        setting_id = self.saved_profile_combo.currentData() or ""
        if setting_id:
            setting = load_voice_setting(self.paths.voice_settings, setting_id)
            profile_mode = self._output_mode_label(setting.output_mode, setting.target_part_minutes)
            active_mode = self._output_mode_label(self.job_output_mode, setting.target_part_minutes)
            if setting.output_mode == "chapter_files" and self.job_output_mode != "chapter_files":
                hint_parts.append(
                    self._tr("output.profile_fallback", profile_mode=profile_mode, active_mode=active_mode)
                )
            else:
                hint_parts.append(self._tr("output.active_mode", mode=active_mode))
        else:
            hint_parts.append(self._tr("output.choose_profile"))
        self.job_output_mode_combo_hint.setText(" ".join(hint_parts))
        self.refresh_source_list()

    def _make_scroll_tab(self, tab: QWidget) -> QVBoxLayout:
        outer_layout = QVBoxLayout(tab)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        outer_layout.addWidget(scroll)
        return layout

    def open_path(self, path: Path) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def refresh_diagnostics_summary(self, *, include_runtime_probe: bool = False) -> None:
        diagnostics = self.service.diagnostics(include_runtime_probe=include_runtime_probe)
        paths = diagnostics["paths"]
        xtts = diagnostics["xtts"]
        jobs = diagnostics["jobs"]
        profiles = diagnostics["profiles"]
        perf = diagnostics["performance_logging"]
        system_usage = diagnostics.get("system_usage", {})
        probe = xtts.get("probe")
        runtime_stats = diagnostics["runtime_statistics"]
        core_voice_counts = diagnostics["voices"].get("core_language_voice_counts", {})
        core_voice_summary = ", ".join(
            f"{core_language_label(prefix, ui_language=self.ui_language)} {core_voice_counts.get(prefix, 0)}"
            for prefix in ("de", "en", "es", "pt")
        )
        if probe:
            probe_text = (
                f"Probe: {'OK' if probe.get('ok') else 'Fehler'} | "
                f"CUDA={probe.get('cuda_available')} | Torch={probe.get('torch_version', '-')}"
            )
        else:
            probe_text = "Probe: nicht frisch ausgeführt"
        cpu_text = "-"
        if system_usage.get("cpu_percent") is not None:
            cpu_text = f"{system_usage['cpu_percent']:.0f}%"
        ram_text = "-"
        if system_usage.get("memory_percent") is not None:
            ram_text = f"{system_usage['memory_percent']:.0f}% ({system_usage.get('memory_used_gb', 0):.1f}/{system_usage.get('memory_total_gb', 0):.1f} GB)"
        gpu_entries = system_usage.get("gpus") or []
        if gpu_entries:
            top_gpu = gpu_entries[0]
            gpu_text = (
                f"{top_gpu.get('name', 'GPU')} {top_gpu.get('gpu_percent', 0):.0f}% | "
                f"VRAM {top_gpu.get('memory_used_mb', 0)/1024:.1f}/{top_gpu.get('memory_total_mb', 0)/1024:.1f} GB "
                f"({top_gpu.get('memory_percent', 0):.0f}%)"
            )
        else:
            gpu_text = "kein NVIDIA/CUDA-Telemetriepfad"
        self.system_usage_label.setText(f"CPU {cpu_text} | RAM {ram_text} | CUDA/GPU {gpu_text}")
        self.diagnostics_summary.setPlainText(
            "\n".join(
                [
                    f"Arbeitsbereich: {paths['workspace']['path']}",
                    f"Logs: {paths['logs']['path']}",
                    f"Voices: {paths['voices']['path']}",
                    f"XTTS-Profile: {paths['voice_profiles']['path']}",
                    "",
                    f"Jobs: {jobs['count']} | Status: {jobs['status_counts']}",
                    f"Profile: {profiles['count']} | Status: {profiles['status_counts']}",
                    f"Piper-Stimmen: {diagnostics['voices']['piper_voice_count']} | XTTS-Profile: {diagnostics['voices']['xtts_profile_count']}",
                    f"Kernsprachen Piper: {core_voice_summary}",
                    "",
                    f"XTTS verfügbar: {xtts['available']}",
                    f"XTTS Gerät gewählt: {xtts['selected_device_mode']} | empfohlen: {xtts['preferred_device_mode']}",
                    f"XTTS Verarbeitungsmodus: {diagnostics['app_settings'].get('xtts_processing_mode', 'auto')}",
                    f"XTTS Hinweis: {xtts['availability_reason']}",
                    f"XTTS Schnellstart: {xtts_launcher_hint()}",
                    probe_text,
                    f"Host CPU-Auslastung: {cpu_text}",
                    f"Host RAM-Auslastung: {ram_text}",
                    f"Host GPU/CUDA-Auslastung: {gpu_text}",
                    "",
                    f"Performance-Logging aktiv: {perf['enabled']}",
                    f"Performance-Logdatei: {perf['target_file'] or '-'}",
                    f"Performance-Run-ID: {perf['run_id'] or '-'}",
                    "",
                    f"App-Einstellungen: {diagnostics['app_settings']}",
                    "",
                    f"Runtime-Statistiken: {runtime_stats['entry_count']} Einträge | Stand {runtime_stats['updated_at'] or '-'}",
                    f"Durchschnitt gesamt: {runtime_stats['average_total_seconds']/60:.1f} min | Backends: {runtime_stats['backend_counts']} | Modi: {runtime_stats['mode_counts']}",
                ]
            )
        )
        self.update_xtts_setup_presentation()

    def refresh_diagnostics_summary_with_probe(self) -> None:
        self.refresh_diagnostics_summary(include_runtime_probe=True)

    def _current_job_state(self) -> JobState | None:
        if not self.current_job_id:
            return None
        try:
            return self.manager.load_state(self.current_job_id)
        except FileNotFoundError:
            return None

    def _job_output_dir(self, job: JobState) -> Path:
        return Path(job.final_output_file).parent

    def open_current_job_folder(self) -> None:
        job = self._current_job_state()
        if not job:
            QMessageBox.warning(self, "Kein Job", "Bitte zuerst einen Auftrag auswählen.")
            return
        self.open_path(job.job_dir(self.paths.jobs))

    def open_current_output_folder(self) -> None:
        job = self._current_job_state()
        if not job:
            QMessageBox.warning(self, "Kein Job", "Bitte zuerst einen Auftrag auswählen.")
            return
        self.open_path(self._job_output_dir(job))

    def open_current_manifest_file(self) -> None:
        job = self._current_job_state()
        if not job:
            QMessageBox.warning(self, "Kein Job", "Bitte zuerst einen Auftrag auswählen.")
            return
        manifest = Path(job.manifest_file)
        if not manifest.exists():
            QMessageBox.warning(self, "Manifest fehlt", "Für diesen Auftrag gibt es noch keine manifest.json.")
            return
        self.open_path(manifest)

    def open_current_chapters_file(self) -> None:
        job = self._current_job_state()
        if not job:
            QMessageBox.warning(self, "Kein Job", "Bitte zuerst einen Auftrag auswählen.")
            return
        chapters_file = Path(job.chapters_file)
        if not chapters_file.exists():
            QMessageBox.warning(self, "Kapiteldatei fehlt", "Für diesen Auftrag gibt es noch keine chapters.json.")
            return
        self.open_path(chapters_file)

    def open_selected_chapter_text(self) -> None:
        job = self._current_job_state()
        if not job:
            QMessageBox.warning(self, "Kein Job", "Bitte zuerst einen Auftrag auswählen.")
            return
        chapter = self._selected_chapter(job)
        if chapter is None:
            QMessageBox.warning(self, "Kein Kapitel", "Bitte zuerst ein Kapitel auswählen.")
            return
        chapter_text = Path(chapter.text_file)
        if not chapter_text.exists():
            QMessageBox.warning(self, "Kapiteltext fehlt", f"Datei nicht gefunden: {chapter_text}")
            return
        self.open_path(chapter_text)

    def open_selected_chapter_audio(self) -> None:
        job = self._current_job_state()
        if not job:
            QMessageBox.warning(self, "Kein Job", "Bitte zuerst einen Auftrag auswählen.")
            return
        chapter = self._selected_chapter(job)
        if chapter is None:
            QMessageBox.warning(self, "Kein Kapitel", "Bitte zuerst ein Kapitel auswählen.")
            return
        if not chapter.output_file:
            QMessageBox.warning(self, "Kein Audio", "Für dieses Kapitel gibt es noch keine fertige Audiodatei.")
            return
        chapter_audio = Path(chapter.output_file)
        if not chapter_audio.exists():
            QMessageBox.warning(self, "Kapitelaudio fehlt", f"Datei nicht gefunden: {chapter_audio}")
            return
        self.open_path(chapter_audio)

    def retry_selected_chapter(self) -> None:
        job = self._current_job_state()
        if not job:
            QMessageBox.warning(self, "Kein Job", "Bitte zuerst einen Auftrag auswählen.")
            return
        chapter = self._selected_chapter(job)
        if chapter is None:
            QMessageBox.warning(self, "Kein Kapitel", "Bitte zuerst ein Kapitel auswählen.")
            return
        chunk_indexes = list(range(chapter.chunk_start_index, chapter.chunk_end_index + 1))
        updated = self.manager.retry_job(job.job_id, chunk_indexes=chunk_indexes, reset_output=True)
        self.refresh_jobs()
        self.show_job(updated)
        self.status_label.setText(f"Kapitel {chapter.index} wurde mit Chunks {chunk_indexes} erneut angestellt.")

    def open_selected_chunk_text(self) -> None:
        job = self._current_job_state()
        if not job:
            QMessageBox.warning(self, "Kein Job", "Bitte zuerst einen Auftrag auswählen.")
            return
        selected = self._selected_chunk_indexes()
        if not selected:
            QMessageBox.warning(self, "Kein Chunk", "Bitte zuerst mindestens einen Chunk auswählen.")
            return
        chunk = next((entry for entry in job.chunks if entry.index == selected[0]), None)
        if chunk is None:
            QMessageBox.warning(self, "Chunk fehlt", "Der ausgewählte Chunk konnte nicht geladen werden.")
            return
        chunk_text = Path(chunk.text_file)
        if not chunk_text.exists():
            QMessageBox.warning(self, "Chunktext fehlt", f"Datei nicht gefunden: {chunk_text}")
            return
        self.open_path(chunk_text)

    def open_selected_chunk_audio(self) -> None:
        job = self._current_job_state()
        if not job:
            QMessageBox.warning(self, "Kein Job", "Bitte zuerst einen Auftrag auswählen.")
            return
        selected = self._selected_chunk_indexes()
        if not selected:
            QMessageBox.warning(self, "Kein Chunk", "Bitte zuerst mindestens einen Chunk auswählen.")
            return
        chunk = next((entry for entry in job.chunks if entry.index == selected[0]), None)
        if chunk is None:
            QMessageBox.warning(self, "Chunk fehlt", "Der ausgewählte Chunk konnte nicht geladen werden.")
            return
        for artifact in (chunk.mp3_file, chunk.wav_file):
            path = Path(artifact)
            if path.exists():
                self.open_path(path)
                return
        QMessageBox.warning(self, "Chunkaudio fehlt", "Für diesen Chunk gibt es noch keine Audiodatei.")

    def retry_selected_chunks(self) -> None:
        job = self._current_job_state()
        if not job:
            QMessageBox.warning(self, "Kein Job", "Bitte zuerst einen Auftrag auswählen.")
            return
        chunk_indexes = self._selected_chunk_indexes()
        if not chunk_indexes:
            QMessageBox.warning(self, "Keine Auswahl", "Bitte zuerst mindestens einen Chunk auswählen.")
            return
        updated = self.manager.retry_job(job.job_id, chunk_indexes=chunk_indexes, reset_output=True)
        self.refresh_jobs()
        self.show_job(updated)
        self.status_label.setText(f"Chunks {sorted(chunk_indexes)} wurden zurückgesetzt und wieder in die Queue gestellt.")

    def retry_failed_chunks(self) -> None:
        job = self._current_job_state()
        if not job:
            QMessageBox.warning(self, "Kein Job", "Bitte zuerst einen Auftrag auswählen.")
            return
        failed = [chunk.index for chunk in job.failed_chunks]
        if not failed:
            QMessageBox.information(self, "Keine Fehler", "Für diesen Auftrag gibt es aktuell keine fehlgeschlagenen Chunks.")
            return
        updated = self.manager.retry_job(job.job_id, chunk_indexes=failed, reset_output=True)
        self.refresh_jobs()
        self.show_job(updated)
        self.status_label.setText(f"Fehlgeschlagene Chunks erneut angestellt: {failed}")

    def retry_current_job(self) -> None:
        job = self._current_job_state()
        if not job:
            QMessageBox.warning(self, "Kein Job", "Bitte zuerst einen Auftrag auswählen.")
            return
        updated = self.manager.retry_job(job.job_id, reset_output=True)
        self.refresh_jobs()
        self.show_job(updated)
        self.status_label.setText("Auftrag vollständig zurückgesetzt und erneut in die Queue gestellt.")

    def build_job_summary(self, job: JobState) -> str:
        stage_lines = [
            f"- {stage['label']}: {stage['status']} | {stage['detail']}"
            for stage in job.stage_statuses()
        ]
        chapter_titles = ", ".join(chapter.title for chapter in job.chapters[:6]) or "-"
        if len(job.chapters) > 6:
            chapter_titles += ", …"
        outputs = "\n".join(job.final_output_files[:6]) or "-"
        if len(job.final_output_files) > 6:
            outputs += "\n…"
        failed_chunks = ", ".join(str(chunk.index) for chunk in job.failed_chunks) or "-"
        return "\n".join(
            [
                f"Job-ID: {job.job_id}",
                f"Titel: {job.title}",
                f"Status: {job.status}",
                f"Backend: {job.backend}",
                f"Produktionsprofil: {job.saved_profile_name or '-'} ({job.saved_profile_id or '-'})",
                f"Stimme/Profil: {job.voice_id or job.voice_profile_id or '-'}",
                f"Output-Modus: {job.output_mode} | Ziel-Minuten: {job.target_part_minutes}",
                f"Gerät/Verarbeitung: {job.device_mode} / {job.processing_mode}",
                f"Verarbeitungsgrund: {job.processing_mode_reason or '-'}",
                f"Blockgrund: {job.block_reason or '-'}",
                f"Letzte Fehlerkategorie: {job.last_failure_category or '-'}",
                f"Automatische Recovery-Versuche: {job.auto_recovery_attempts}",
                f"Textlänge: {job.source_characters} Zeichen",
                f"Schätzung: {self._format_duration_hm(job.estimated_total_seconds)} gesamt | Rest {self._format_duration_hm(job.estimated_remaining_seconds)} | Samples {job.estimated_from_samples} ({job.estimated_confidence})",
                f"Ist-Dauer: {self._format_duration_hm(job.actual_total_seconds)}",
                "",
                "Stufen:",
                *stage_lines,
                "",
                f"Kapitel: {len(job.chapters)} | Titel: {chapter_titles}",
                f"Chunks: {job.completed_chunks}/{job.total_chunks} fertig | Fehlgeschlagen: {failed_chunks}",
                "",
                f"Quelldatei: {job.source_file}",
                f"Extrakt: {job.extracted_file}",
                f"Manifest: {job.manifest_file}",
                f"Kapiteldatei: {job.chapters_file}",
                f"Fehlerbericht: {job.failure_report_file or '-'}",
                "Ausgaben:",
                outputs,
            ]
        )

    def _job_runtime_summary_text(self, job: JobState) -> str:
        estimate_text = (
            f"Schätzung ca. {self._format_duration_hm(job.estimated_total_seconds)}, Rest aktuell ca. {self._format_duration_hm(job.estimated_remaining_seconds)}."
            if job.estimated_total_seconds > 0
            else "Noch keine belastbare Schätzung für diesen Auftrag verfügbar."
        )
        actual_text = (
            f" Bisher gemessene Gesamtdauer: {self._format_duration_hm(job.actual_total_seconds)}."
            if job.actual_total_seconds > 0
            else ""
        )
        confidence_text = (
            f" Datenbasis: {job.estimated_from_samples} ähnlicher Lauf/Läufe ({job.estimated_confidence})."
            if job.estimated_from_samples > 0
            else ""
        )
        return (
            f"Verarbeitung: {job.processing_mode} auf {job.device_mode}. "
            f"{job.processing_mode_reason or 'Noch keine Modusbegründung.'} "
            f"{estimate_text}{confidence_text}{actual_text}"
        ).strip()

    def refresh_job_selection_details(self) -> None:
        job = self._current_job_state()
        if job is None:
            self.job_selection_details.clear()
            return
        chapter = self._selected_chapter(job)
        chunk_indexes = self._selected_chunk_indexes()
        lines: list[str] = []
        if chapter is not None:
            lines.extend(
                [
                    f"Kapitel {chapter.index}: {chapter.title}",
                    f"Textdatei: {chapter.text_file}",
                    f"Chunk-Bereich: {chapter.chunk_start_index}-{chapter.chunk_end_index}",
                    f"Audio: {chapter.output_file or '-'}",
                ]
            )
        if chunk_indexes:
            chunks = [chunk for chunk in job.chunks if chunk.index in chunk_indexes]
            lines.append("")
            lines.append(f"Ausgewählte Chunks: {', '.join(str(chunk.index) for chunk in chunks)}")
            for chunk in chunks[:5]:
                text_len = len(Path(chunk.text_file).read_text(encoding="utf-8")) if Path(chunk.text_file).exists() else 0
                lines.append(
                    f"- Chunk {chunk.index}: Status {chunk.status}, Kapitel {chunk.chapter_index}, {text_len} Zeichen, Fehler {chunk.error or '-'}"
                )
            if len(chunks) > 5:
                lines.append(f"- … und {len(chunks) - 5} weitere Chunks")
        if not lines:
            lines.append("Noch keine Kapitel- oder Chunk-Auswahl aktiv.")
        self.job_selection_details.setPlainText("\n".join(lines))

    def populate_job_detail_lists(self, job: JobState) -> None:
        self.job_stage_list.clear()
        for stage in job.stage_statuses():
            item = QListWidgetItem(f"{stage['label']}: {stage['status']} | {stage['detail']}")
            item.setToolTip(f"Stufe {stage['stage']}\nStatus: {stage['status']}\n{stage['detail']}")
            self.job_stage_list.addItem(item)

        self.job_chapter_list.clear()
        for chapter in job.chapters:
            output_name = Path(chapter.output_file).name if chapter.output_file else "-"
            item = QListWidgetItem(
                f"{chapter.index:03d} | {chapter.title} | Chunks {chapter.chunk_start_index}-{chapter.chunk_end_index} | Audio {output_name}"
            )
            item.setData(Qt.UserRole, chapter.index)
            item.setToolTip(
                f"Titel: {chapter.title}\nText: {chapter.text_file}\nOutput: {chapter.output_file or '-'}"
            )
            self.job_chapter_list.addItem(item)
        if not job.chapters:
            self.job_chapter_list.addItem("Noch keine Kapitelstruktur für diesen Auftrag.")

        self.job_chunk_list.clear()
        for chunk in job.chunks:
            audio_name = "-"
            for candidate in (chunk.mp3_file, chunk.wav_file):
                if candidate and Path(candidate).exists():
                    audio_name = Path(candidate).name
                    break
            item = QListWidgetItem(
                f"{chunk.index:05d} | {chunk.status:7s} | Kapitel {chunk.chapter_index} | {len(Path(chunk.text_file).read_text(encoding='utf-8')) if Path(chunk.text_file).exists() else 0} Zeichen | Audio {audio_name}"
            )
            item.setData(Qt.UserRole, chunk.index)
            item.setToolTip(
                f"Kapitel: {chunk.chapter_title or '-'}\nText: {chunk.text_file}\nMP3: {chunk.mp3_file}\nWAV: {chunk.wav_file}\nFehler: {chunk.error or '-'}"
            )
            self.job_chunk_list.addItem(item)
        if not job.chunks:
            self.job_chunk_list.addItem("Noch keine Chunks für diesen Auftrag.")

    def _selected_chunk_indexes(self) -> list[int]:
        indexes: list[int] = []
        for item in self.job_chunk_list.selectedItems():
            value = item.data(Qt.UserRole)
            if value:
                indexes.append(int(value))
        return indexes

    def _selected_chapter(self, job: JobState):
        item = self.job_chapter_list.currentItem()
        if not item:
            return None
        chapter_index = item.data(Qt.UserRole)
        if not chapter_index:
            return None
        for chapter in job.chapters:
            if chapter.index == int(chapter_index):
                return chapter
        return None

    def refresh_saved_profiles(self) -> None:
        selected_setting_id = self.saved_profile_combo.currentData() or ""
        self.saved_profile_combo.clear()
        settings = list_voice_settings(self.paths.voice_settings)
        approved_settings = [setting for setting in settings if setting.status == PROFILE_STATUS_APPROVED]
        if not approved_settings:
            self.saved_profile_combo.addItem("Noch kein freigegebenes Produktionsprofil", "")
            self.saved_profile_summary.setText(
                {
                    "de": "Im Auftragsdialog erscheinen nur freigegebene Produktionsprofile. Erstelle oder teste ein Profil im Profilstudio und gib es danach in der Profilbibliothek frei.",
                    "en": "Only approved production profiles appear in the job creator. Create or test a profile in the Profile Studio and approve it in the library afterwards.",
                    "es": "En el creador de trabajos solo aparecen perfiles de producción aprobados. Crea o prueba un perfil en el estudio y apruébalo después en la biblioteca.",
                    "pt": "Apenas perfis de produção aprovados aparecem no criador de tarefas. Crie ou teste um perfil no estúdio e aprove-o depois na biblioteca.",
                }.get(self.ui_language, "Only approved production profiles appear in the job creator. Create or test a profile in the Profile Studio and approve it in the library afterwards.")
            )
            self.job_snapshot_label.setText({
                "de": "Das Produktionsprofil bestimmt Backend, Stimme, Chunkgröße, Tempo und Ausgabeformat.",
                "en": "The production profile defines backend, voice, chunk size, speaking speed, and output mode.",
                "es": "El perfil de producción define backend, voz, tamaño de fragmento, velocidad y modo de salida.",
                "pt": "O perfil de produção define backend, voz, tamanho do bloco, velocidade de fala e modo de saída.",
            }.get(self.ui_language, "The production profile defines backend, voice, chunk size, speaking speed, and output mode."))
            self.apply_job_output_mode_availability(preferred_mode="single_file")
            self.refresh_profile_library()
            self.refresh_profile_hub_summary()
            return
        for setting in approved_settings:
            label = f"{setting.display_name} | {setting.backend} | {setting.preset_hint} | freigegeben"
            self.saved_profile_combo.addItem(label, setting.setting_id)
        selected_index = self.saved_profile_combo.findData(selected_setting_id)
        self.saved_profile_combo.setCurrentIndex(selected_index if selected_index >= 0 else 0)
        self.refresh_saved_profile_summary()
        self.refresh_profile_library()
        self.refresh_profile_hub_summary()

    def refresh_saved_profile_summary(self) -> None:
        setting_id = self.saved_profile_combo.currentData() or ""
        if not setting_id:
            self.saved_profile_summary.setText({
                "de": "Noch kein freigegebenes Produktionsprofil gewählt. Öffne die Profilbibliothek und gib ein getestetes Profil frei.",
                "en": "No approved production profile selected yet. Open the profile library and approve a tested profile.",
                "es": "Todavía no se ha seleccionado ningún perfil de producción aprobado. Abre la biblioteca y aprueba un perfil probado.",
                "pt": "Nenhum perfil de produção aprovado foi selecionado ainda. Abra a biblioteca e aprove um perfil testado.",
            }.get(self.ui_language, "No approved production profile selected yet. Open the profile library and approve a tested profile."))
            self.job_snapshot_label.setText({
                "de": "Das Produktionsprofil bestimmt Backend, Stimme, Chunkgröße, Tempo und Ausgabeformat.",
                "en": "The production profile defines backend, voice, chunk size, speaking speed, and output mode.",
                "es": "El perfil de producción define backend, voz, tamaño de fragmento, velocidad y modo de salida.",
                "pt": "O perfil de produção define backend, voz, tamanho do bloco, velocidade de fala e modo de saída.",
            }.get(self.ui_language, "The production profile defines backend, voice, chunk size, speaking speed, and output mode."))
            self.apply_job_output_mode_availability(preferred_mode="single_file")
            return
        setting = load_voice_setting(self.paths.voice_settings, setting_id)
        voice_label = setting.voice_profile_id or setting.voice_id or "-"
        mode_label = self._output_mode_label(setting.output_mode, setting.target_part_minutes)
        benchmark_text = (
            f" | Benchmark {setting.benchmark_average_ms/1000:.2f}s"
            if setting.benchmark_average_ms > 0
            else ""
        )
        self.saved_profile_summary.setText(
            f"{setting.display_name}\n"
            f"Status: {profile_status_label(setting.status, ui_language=self.ui_language)} | Backend: {setting.backend} | Stimme/Profil: {voice_label}\n"
            f"Preset: {setting.preset_hint} | Ausgabe: {mode_label}{benchmark_text}"
        )
        self.job_snapshot_label.setText(
            f"Chunkgröße {setting.max_chars}, Satzpause {setting.sentence_silence:.2f}s, "
            f"Tempo {setting.length_scale:.2f}, Standardausgabe {mode_label}, "
            f"freigegeben {setting.approved_at or '-'}, zuletzt aktualisiert {setting.updated_at}."
        )
        self.apply_job_output_mode_availability(preferred_mode=setting.output_mode)
        self.select_profile_in_library(setting_id)

    def refresh_profile_library(self) -> None:
        selected_setting_id = self.saved_profile_combo.currentData() or ""
        self.profile_library_list.clear()
        settings = list_voice_settings(self.paths.voice_settings)
        if not settings:
            self.profile_library_summary.setText({
                "de": "Noch keine Produktionsprofile vorhanden. Öffne das Profilstudio und speichere dort eine getestete Kombination.",
                "en": "No production profiles exist yet. Open the Profile Studio and save a tested combination there.",
                "es": "Todavía no existen perfiles de producción. Abre el estudio de perfiles y guarda allí una combinación probada.",
                "pt": "Ainda não existem perfis de produção. Abra o Estúdio de Perfis e salve lá uma combinação testada.",
            }.get(self.ui_language, "No production profiles exist yet. Open the Profile Studio and save a tested combination there."))
            return
        for setting in settings:
            label = (
                f"{profile_status_label(setting.status, ui_language=self.ui_language)} | {setting.display_name} | "
                f"{setting.backend} | {setting.preset_hint}"
            )
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, setting.setting_id)
            item.setToolTip(
                f"Status: {profile_status_label(setting.status, ui_language=self.ui_language)}\n"
                f"Backend: {setting.backend}\n"
                f"Ausgabe: {self._output_mode_label(setting.output_mode, setting.target_part_minutes)}"
            )
            self.profile_library_list.addItem(item)
        self.select_profile_in_library(selected_setting_id or settings[0].setting_id)

    def select_profile_in_library(self, setting_id: str) -> None:
        if not setting_id:
            return
        for index in range(self.profile_library_list.count()):
            item = self.profile_library_list.item(index)
            if item.data(Qt.UserRole) == setting_id:
                self.profile_library_list.setCurrentItem(item)
                return

    def on_profile_library_selected(self) -> None:
        item = self.profile_library_list.currentItem()
        if not item:
            self.profile_library_summary.setText(self._text("Noch kein Produktionsprofil gewählt."))
            return
        setting_id = item.data(Qt.UserRole)
        setting = load_voice_setting(self.paths.voice_settings, setting_id)
        runtime_label = "CUDA zuerst" if setting.backend == "xtts" else "direkt offline"
        benchmark_text = (
            f" | Benchmark {setting.benchmark_average_ms/1000:.2f}s"
            if setting.benchmark_average_ms > 0
            else ""
        )
        self.profile_library_summary.setText(
            f"{setting.display_name}\n"
            f"Status: {profile_status_label(setting.status, ui_language=self.ui_language)} | Backend: {setting.backend} | Stimme/Profil: {setting.voice_profile_id or setting.voice_id or '-'}\n"
            f"Preset: {setting.preset_hint} | Ausgabe: {self._output_mode_label(setting.output_mode, setting.target_part_minutes)}{benchmark_text}\n"
            f"Chunkgröße: {setting.max_chars} | Tempo: {setting.length_scale:.2f} | Modus: {runtime_label}\n"
            f"Freigegeben: {setting.approved_at or '-'} | Aktualisiert: {setting.updated_at}"
        )

    def use_selected_profile_for_new_jobs(self) -> None:
        item = self.profile_library_list.currentItem()
        if not item:
            QMessageBox.warning(self, "Kein Profil", "Bitte zuerst ein Produktionsprofil auswählen.")
            return
        setting_id = item.data(Qt.UserRole)
        setting = load_voice_setting(self.paths.voice_settings, setting_id)
        if setting.status != PROFILE_STATUS_APPROVED:
            QMessageBox.warning(
                self,
                "Profil noch nicht freigegeben",
                "Im Auftragsdialog sind nur freigegebene Produktionsprofile erlaubt. "
                "Markiere dieses Profil zuerst als freigegeben.",
            )
            return
        index = self.saved_profile_combo.findData(setting_id)
        if index >= 0:
            self.saved_profile_combo.setCurrentIndex(index)
            self.main_tabs.setCurrentIndex(0)
            self.status_label.setText("Produktionsprofil für neue Aufträge übernommen.")

    def set_selected_profile_status(self, status: str) -> None:
        item = self.profile_library_list.currentItem()
        if not item:
            QMessageBox.warning(self, "Kein Profil", "Bitte zuerst ein Produktionsprofil auswählen.")
            return
        setting_id = item.data(Qt.UserRole)
        updated = update_voice_setting_status(self.paths.voice_settings, setting_id, status)
        self.refresh_saved_profiles()
        self.select_profile_in_library(updated.setting_id)
        self.status_label.setText(
            f"Profilstatus aktualisiert: {updated.display_name} -> {profile_status_label(updated.status, ui_language=self.ui_language)}"
        )
        self.refresh_diagnostics_summary()

    def refresh_profile_hub_summary(self) -> None:
        saved_profile_count = max(0, self.saved_profile_combo.count() - (1 if self.saved_profile_combo.itemData(0) == "" else 0))
        all_profiles = list_voice_settings(self.paths.voice_settings)
        tested_count = sum(1 for setting in all_profiles if setting.status == PROFILE_STATUS_TESTED)
        draft_count = sum(1 for setting in all_profiles if setting.status == PROFILE_STATUS_DRAFT)
        archived_count = sum(1 for setting in all_profiles if setting.status == PROFILE_STATUS_ARCHIVED)
        xtts_profile_count = max(0, self.voice_profile_combo.count() - (1 if self.voice_profile_combo.itemData(0) == "" else 0))
        self.profile_runtime_summary.setText(
            {
                "de": f"{saved_profile_count} freigegebene Produktionsprofile, {tested_count} getestete, {draft_count} Entwürfe, {archived_count} archivierte, {len(self.installed_voice_ids)} Piper-Stimmen und {xtts_profile_count} XTTS-Profile verfügbar.",
                "en": f"{saved_profile_count} approved production profiles, {tested_count} tested, {draft_count} drafts, {archived_count} archived, {len(self.installed_voice_ids)} Piper voices and {xtts_profile_count} XTTS profiles available.",
                "es": f"{saved_profile_count} perfiles de producción aprobados, {tested_count} probados, {draft_count} borradores, {archived_count} archivados, {len(self.installed_voice_ids)} voces Piper y {xtts_profile_count} perfiles XTTS disponibles.",
                "pt": f"{saved_profile_count} perfis de produção aprovados, {tested_count} testados, {draft_count} rascunhos, {archived_count} arquivados, {len(self.installed_voice_ids)} vozes Piper e {xtts_profile_count} perfis XTTS disponíveis.",
            }.get(self.ui_language, f"{saved_profile_count} approved production profiles, {tested_count} tested, {draft_count} drafts, {archived_count} archived, {len(self.installed_voice_ids)} Piper voices and {xtts_profile_count} XTTS profiles available.")
        )
        self.profile_runtime_hint.setText(self.xtts_runtime_hint.text() or self.backend_summary.text())
        self.update_xtts_setup_presentation()

    def apply_cuda_first_preference(self) -> None:
        if not self.xtts_backend.is_available():
            return
        preferred_mode = self.xtts_backend.preferred_device_mode()
        cuda_index = self.xtts_device_combo.findData("cuda")
        auto_index = self.xtts_device_combo.findData("auto")
        if cuda_index >= 0:
            self.xtts_device_combo.setItemText(
                cuda_index,
                "CUDA bevorzugen (Standard)" if preferred_mode == "cuda" else "CUDA bevorzugen",
            )
        if auto_index >= 0:
            self.xtts_device_combo.setItemText(
                auto_index,
                "Automatisch (CPU / CUDA)" if preferred_mode == "cuda" else "Automatisch",
            )
        if preferred_mode == "cuda" and self.app_settings.xtts_device_mode in {"", "auto"}:
            self.app_settings.xtts_device_mode = "cuda"
            save_app_settings(self.paths.app_settings_file, self.app_settings)
            device_index = self.xtts_device_combo.findData("cuda")
            if device_index >= 0:
                self.xtts_device_combo.setCurrentIndex(device_index)
            self.xtts_backend.set_device_mode("cuda")

    def refresh_voice_list(self) -> None:
        backend = PiperBackend(self.paths.runtime, self.paths.voices)
        self.installed_voice_ids = backend.installed_voices()
        self.voice_language_combo.blockSignals(True)
        self.voice_language_combo.clear()
        for code, label in language_choices(self.installed_voice_ids, ui_language=self.ui_language):
            self.voice_language_combo.addItem(label, code)
        self.voice_language_combo.blockSignals(False)
        preferred_language = preferred_content_language_code(self.ui_language)
        preferred_index = self.voice_language_combo.findData(preferred_language)
        if preferred_index >= 0:
            self.voice_language_combo.setCurrentIndex(preferred_index)
        self.rebuild_voice_combo()
        self.refresh_voice_profiles()
        self.refresh_saved_profiles()
        self.logger.info("Loaded %s installed voices", len(self.installed_voice_ids))
        self.update_backend_summary()
        self.refresh_profile_hub_summary()
        self.refresh_diagnostics_summary()
        if not self.installed_voice_ids:
            self.status_label.setText(
                f"Keine Piper-Stimmen gefunden. Geprüft wurde {self.paths.voices}. "
                "Nutze bootstrap_runtime.py oder kopiere Stimmen nach voices/."
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
                self.voice_combo.addItem(format_voice_label(voice_id, ui_language=self.ui_language), voice_id)
            selected_index = self.voice_combo.findData(selected_voice_id)
            self.voice_combo.setCurrentIndex(selected_index if selected_index >= 0 else 0)
        else:
            self.voice_combo.addItem(
                voice_filter_empty_message(
                    language_code,
                    ui_language=self.ui_language,
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
            self.voice_profile_combo.addItem("Keine XTTS-Profile gefunden", "")
            self.voice_profile_hint.setText(
                "Keine XTTS-Profile vorhanden. Importiere einen xtts-webui speakers-Ordner oder erstelle ein XTTS-Profil im Profilstudio."
            )
            self.xtts_scan_hint.setText(
                "Nutze 'XTTS-Sprecher' fuer Auto-Import alter WebUI-Ordner oder 'XTTS-Starter' fuer sofort nutzbare Beispielsprecher."
            )
            self.voice_profile_details.setText("Noch kein XTTS-Profil ausgewaehlt.")
        self.refresh_selected_voice_profile()
        self.update_backend_summary()
        self.refresh_profile_hub_summary()
        self.update_xtts_setup_presentation()

    def probe_xtts_runtime(self, *, refresh: bool = False) -> dict[str, object] | None:
        if self.xtts_probe_cache is not None and not refresh:
            return self.xtts_probe_cache
        if not self.xtts_backend.is_available():
            self.xtts_probe_cache = None
            self.xtts_runtime_hint.setText(self.xtts_backend.availability_reason())
            return None
        try:
            self.xtts_probe_cache = self.xtts_backend.runtime_probe()
        except Exception as exc:
            self.xtts_probe_cache = {"ok": False, "error": str(exc)}
        probe = self.xtts_probe_cache
        if probe.get("ok"):
            if probe.get("cuda_available"):
                gpu_names = ", ".join(probe.get("gpu_names", [])) or "CUDA-GPU"
                self.xtts_runtime_hint.setText(
                    f"CUDA aktiv in XTTS-Runtime. Geraete: {gpu_names}. Torch {probe.get('torch_version', '-')}"
                )
            else:
                host = probe.get("host_nvidia_smi", {})
                host_hint = ""
                if isinstance(host, dict) and host.get("found") and host.get("gpus"):
                    host_hint = f" Host sieht NVIDIA: {', '.join(host.get('gpus', []))}."
                self.xtts_runtime_hint.setText(
                    f"XTTS-Runtime laeuft aktuell auf CPU. Torch {probe.get('torch_version', '-')}.{host_hint}"
                )
        else:
            self.xtts_runtime_hint.setText(f"XTTS-Probe fehlgeschlagen: {probe.get('error', 'unbekannt')}")
        self.refresh_profile_hub_summary()
        self.update_xtts_setup_presentation()
        return self.xtts_probe_cache

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
        self.xtts_device_combo.setEnabled(not is_piper)
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
            self.backend_combo.setStyleSheet("")
            self.voice_profile_combo.setStyleSheet("")
            self.backend_notice.show()
            self.xtts_backend.set_device_mode(self.xtts_device_combo.currentData() or "auto")
            if self.preset_combo.currentData() in {"fast_cpu", "balanced", "natural"}:
                xtts_index = self.preset_combo.findData("premium_natural")
                if xtts_index >= 0:
                    self.preset_combo.setCurrentIndex(xtts_index)
        self.update_backend_summary()

    def update_backend_summary(self) -> None:
        profile_count = max(0, self.voice_profile_combo.count() - (1 if self.voice_profile_combo.itemData(0) == "" else 0))
        if self.backend_combo.currentText() == "xtts":
            if not self.xtts_backend.is_available():
                self.backend_summary.setText(
                    {
                        "de": f"XTTS nicht bereit. {self.xtts_backend.availability_reason()}",
                        "en": f"XTTS not ready. {self.xtts_backend.availability_reason()}",
                        "es": f"XTTS no está listo. {self.xtts_backend.availability_reason()}",
                        "pt": f"XTTS não está pronto. {self.xtts_backend.availability_reason()}",
                    }.get(self.ui_language, f"XTTS not ready. {self.xtts_backend.availability_reason()}")
                )
                self.update_xtts_setup_presentation()
                return
            probe = self.probe_xtts_runtime()
            if probe and probe.get("ok"):
                actual_device = "CUDA" if probe.get("cuda_available") else "CPU"
                self.backend_summary.setText(
                    {
                        "de": f"XTTS: {profile_count} Sprecherprofile verfügbar. Gerätemodus {self.xtts_device_combo.currentData() or 'auto'}, aktuelle Runtime {actual_device}. Empfohlen: Preset 'Premium Natürlich' und ein gutes XTTS-Profil.",
                        "en": f"XTTS: {profile_count} speaker profiles available. Device mode {self.xtts_device_combo.currentData() or 'auto'}, current runtime {actual_device}. Recommended: preset 'Premium Natural' and a good XTTS profile.",
                        "es": f"XTTS: {profile_count} perfiles de voz disponibles. Modo de dispositivo {self.xtts_device_combo.currentData() or 'auto'}, runtime actual {actual_device}. Recomendado: preset 'Premium Natural' y un buen perfil XTTS.",
                        "pt": f"XTTS: {profile_count} perfis de voz disponíveis. Modo do dispositivo {self.xtts_device_combo.currentData() or 'auto'}, runtime atual {actual_device}. Recomendado: preset 'Premium Natural' e um bom perfil XTTS.",
                    }.get(self.ui_language, f"XTTS: {profile_count} speaker profiles available. Device mode {self.xtts_device_combo.currentData() or 'auto'}, current runtime {actual_device}. Recommended: preset 'Premium Natural' and a good XTTS profile.")
                )
                self.refresh_profile_hub_summary()
                self.update_xtts_setup_presentation()
                return
            self.backend_summary.setText(
                {
                    "de": f"XTTS: {profile_count} Sprecherprofile verfügbar. Empfohlen: Preset 'Premium Natürlich' und ein gutes XTTS-Profil.",
                    "en": f"XTTS: {profile_count} speaker profiles available. Recommended: preset 'Premium Natural' and a good XTTS profile.",
                    "es": f"XTTS: {profile_count} perfiles de voz disponibles. Recomendado: preset 'Premium Natural' y un buen perfil XTTS.",
                    "pt": f"XTTS: {profile_count} perfis de voz disponíveis. Recomendado: preset 'Premium Natural' e um bom perfil XTTS.",
                }.get(self.ui_language, f"XTTS: {profile_count} speaker profiles available. Recommended: preset 'Premium Natural' and a good XTTS profile.")
            )
        else:
            self.backend_summary.setText(
                {
                    "de": f"Piper: {len(self.installed_voice_ids)} Offline-Stimmen verfügbar. Empfohlen für schnelle lokale Verarbeitung ohne XTTS-Runtime.",
                    "en": f"Piper: {len(self.installed_voice_ids)} offline voices available. Recommended for fast local processing without XTTS runtime.",
                    "es": f"Piper: {len(self.installed_voice_ids)} voces offline disponibles. Recomendado para un procesamiento local rápido sin runtime XTTS.",
                    "pt": f"Piper: {len(self.installed_voice_ids)} vozes offline disponíveis. Recomendado para processamento local rápido sem runtime XTTS.",
                }.get(self.ui_language, f"Piper: {len(self.installed_voice_ids)} offline voices available. Recommended for fast local processing without XTTS runtime.")
            )
        self.refresh_profile_hub_summary()
        self.update_xtts_setup_presentation()

    def update_xtts_setup_presentation(self) -> None:
        profile_count = max(
            0,
            self.voice_profile_combo.count() - (1 if self.voice_profile_combo.itemData(0) == "" else 0),
        )
        if self.xtts_backend.is_available():
            setup_text = (
                {
                    "de": f"XTTS ist bereit. {profile_count} Sprecherprofile gefunden. Prüfe jetzt CUDA, lade bei Bedarf Starterprofile oder öffne direkt das XTTS-Profilstudio.",
                    "en": f"XTTS is ready. {profile_count} speaker profiles found. Check CUDA, install starter profiles if needed, or open the XTTS profile studio.",
                    "es": f"XTTS está listo. Se encontraron {profile_count} perfiles de voz. Comprueba CUDA, instala perfiles iniciales si hace falta o abre el estudio XTTS.",
                    "pt": f"XTTS está pronto. {profile_count} perfis de voz encontrados. Verifique o CUDA, instale perfis iniciais se necessário ou abra o estúdio XTTS.",
                }.get(self.ui_language, f"XTTS is ready. {profile_count} speaker profiles found. Check CUDA, install starter profiles if needed, or open the XTTS profile studio.")
            )
            button_text = self._text("XTTS optional einrichten")
        else:
            setup_text = (
                {
                    "de": f"Piper läuft sofort. XTTS ist optional und wird getrennt eingerichtet. Schnellstart: {xtts_launcher_hint()}. {xtts_license_hint()}",
                    "en": f"Piper works immediately. XTTS is optional and set up separately. Quick start: {xtts_launcher_hint()}. {xtts_license_hint()}",
                    "es": f"Piper funciona de inmediato. XTTS es opcional y se configura por separado. Inicio rápido: {xtts_launcher_hint()}. {xtts_license_hint()}",
                    "pt": f"O Piper funciona imediatamente. O XTTS é opcional e configurado separadamente. Início rápido: {xtts_launcher_hint()}. {xtts_license_hint()}",
                }.get(self.ui_language, f"Piper works immediately. XTTS is optional and set up separately. Quick start: {xtts_launcher_hint()}. {xtts_license_hint()}")
            )
            button_text = self._text("XTTS jetzt einrichten")
        self.xtts_setup_summary_label.setText(setup_text)
        self.xtts_setup_button.setText(button_text)
        self.diagnostics_xtts_setup_button.setText(button_text)

    def open_xtts_setup_dialog(self) -> None:
        dialog = XttsSetupDialog(self.paths, self, ui_language=self.ui_language)
        dialog.exec()
        self.xtts_probe_cache = None
        self.refresh_voice_profiles()
        self.refresh_diagnostics_summary()

    def apply_default_controls(self) -> None:
        language_index = self.ui_language_combo.findData(self.app_settings.ui_language)
        if language_index >= 0:
            self.ui_language_combo.setCurrentIndex(language_index)
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
        device_index = self.xtts_device_combo.findData(self.app_settings.xtts_device_mode)
        if device_index >= 0:
            self.xtts_device_combo.setCurrentIndex(device_index)
        processing_mode_index = self.xtts_processing_mode_combo.findData(self.app_settings.xtts_processing_mode)
        if processing_mode_index >= 0:
            self.xtts_processing_mode_combo.setCurrentIndex(processing_mode_index)
        self.update_output_mode_controls()
        self.apply_job_output_mode_availability(preferred_mode=self.app_settings.default_output_mode or "single_file")
        self.refresh_source_analysis()

    def on_ui_language_changed(self) -> None:
        selected = self.ui_language_combo.currentData() or "auto"
        if selected == self.app_settings.ui_language:
            return
        self.app_settings.ui_language = selected
        save_app_settings(self.paths.app_settings_file, self.app_settings)
        self.status_label.setText(self._tr("status.language_changed"))
        QMessageBox.information(
            self,
            self._tr("dialog.language_changed.title"),
            self._tr("dialog.language_changed.body"),
        )

    def _output_mode_label(self, output_mode: str, target_part_minutes: int) -> str:
        labels = {
            "de": {
                "single_file": "eine große Enddatei",
                "chapter_files": "eine Enddatei pro Kapitel",
                "timed_parts": f"Enddateien etwa alle {target_part_minutes} Minuten",
                "segments": "nur Segmentdateien",
            },
            "en": {
                "single_file": "one final file",
                "chapter_files": "one final file per chapter",
                "timed_parts": f"final files every ~{target_part_minutes} minutes",
                "segments": "segment files only",
            },
            "es": {
                "single_file": "un archivo final",
                "chapter_files": "un archivo final por capítulo",
                "timed_parts": f"archivos finales cada ~{target_part_minutes} minutos",
                "segments": "solo archivos de segmentos",
            },
            "pt": {
                "single_file": "um arquivo final",
                "chapter_files": "um arquivo final por capítulo",
                "timed_parts": f"arquivos finais a cada ~{target_part_minutes} minutos",
                "segments": "apenas arquivos de segmentos",
            },
        }
        return labels.get(self.ui_language, labels["en"]).get(output_mode, output_mode)

    def update_output_mode_controls(self) -> None:
        output_mode = self.output_mode_combo.currentData() or "single_file"
        self.target_part_minutes_spin.setEnabled(output_mode == "timed_parts")

    def _eta_short_label(self, seconds: float) -> str:
        if seconds <= 0:
            return self._tr("queue.eta.learning")
        return f"ETA {self._format_duration_hm(seconds)}"

    def _format_duration_hm(self, seconds: float) -> str:
        total_seconds = int(round(max(0.0, seconds)))
        hours, remainder = divmod(total_seconds, 3600)
        minutes, _ = divmod(remainder, 60)
        if hours <= 0:
            return {
                "de": f"{minutes} min",
                "en": f"{minutes} min",
                "es": f"{minutes} min",
                "pt": f"{minutes} min",
            }.get(self.ui_language, f"{minutes} min")
        return {
            "de": f"{hours} h {minutes:02d} min",
            "en": f"{hours} h {minutes:02d} min",
            "es": f"{hours} h {minutes:02d} min",
            "pt": f"{hours} h {minutes:02d} min",
        }.get(self.ui_language, f"{hours} h {minutes:02d} min")

    def _queue_eta_overview_text(self, jobs: list[JobState]) -> str:
        queued_jobs = [job for job in jobs if job.status in {"queued", "prepared", "running"}]
        if not queued_jobs:
            return {
                "de": "Keine aktiven oder wartenden Aufträge. Noch keine Restzeit in der Queue.",
                "en": "No active or queued jobs. No remaining queue time yet.",
                "es": "No hay trabajos activos o en cola. Aún no hay tiempo restante para la cola.",
                "pt": "Não há tarefas ativas ou na fila. Ainda não há tempo restante da fila.",
            }.get(self.ui_language, "No active or queued jobs. No remaining queue time yet.")
        known_jobs = [job for job in queued_jobs if job.estimated_remaining_seconds > 0]
        total_seconds = sum(max(0.0, job.estimated_remaining_seconds) for job in known_jobs)
        if not known_jobs:
            return {
                "de": f"{len(queued_jobs)} aktive oder wartende Aufträge. Die erste Gesamtprognose erscheint, sobald die ersten echten Laufzeitdaten vorliegen.",
                "en": f"{len(queued_jobs)} active or queued jobs. The first overall estimate appears as soon as the first real runtime data is available.",
                "es": f"{len(queued_jobs)} trabajos activos o en cola. La primera estimación global aparecerá en cuanto exista el primer dato real de ejecución.",
                "pt": f"{len(queued_jobs)} tarefas ativas ou na fila. A primeira estimativa geral aparecerá assim que existirem os primeiros dados reais de execução.",
            }.get(self.ui_language, f"{len(queued_jobs)} active or queued jobs. The first overall estimate appears as soon as the first real runtime data is available.")
        total_text = self._format_duration_hm(total_seconds)
        return {
            "de": f"{len(queued_jobs)} aktive oder wartende Aufträge | Gesamt-Restzeit ca. {total_text} | belastbare ETA für {len(known_jobs)}/{len(queued_jobs)} Jobs",
            "en": f"{len(queued_jobs)} active or queued jobs | total remaining time approx. {total_text} | reliable ETA for {len(known_jobs)}/{len(queued_jobs)} jobs",
            "es": f"{len(queued_jobs)} trabajos activos o en cola | tiempo restante total aprox. {total_text} | ETA fiable para {len(known_jobs)}/{len(queued_jobs)} trabajos",
            "pt": f"{len(queued_jobs)} tarefas ativas ou na fila | tempo restante total aprox. {total_text} | ETA confiável para {len(known_jobs)}/{len(queued_jobs)} tarefas",
        }.get(self.ui_language, f"{len(queued_jobs)} active or queued jobs | total remaining time approx. {total_text} | reliable ETA for {len(known_jobs)}/{len(queued_jobs)} jobs")

    def _job_status_display(self, status: str) -> str:
        labels = {
            "de": {
                "running": "Läuft",
                "queued": "Wartet",
                "prepared": "Bereit",
                "blocked": "Blockiert",
                "failed": "Fehler",
                "stopped": "Pausiert",
                "completed": "Fertig",
                "draft": "Entwurf",
            },
            "en": {
                "running": "Running",
                "queued": "Queued",
                "prepared": "Ready",
                "blocked": "Blocked",
                "failed": "Failed",
                "stopped": "Paused",
                "completed": "Done",
                "draft": "Draft",
            },
            "es": {
                "running": "En curso",
                "queued": "En cola",
                "prepared": "Listo",
                "blocked": "Bloqueado",
                "failed": "Error",
                "stopped": "Pausado",
                "completed": "Terminado",
                "draft": "Borrador",
            },
            "pt": {
                "running": "Em execução",
                "queued": "Na fila",
                "prepared": "Pronto",
                "blocked": "Bloqueado",
                "failed": "Falhou",
                "stopped": "Pausado",
                "completed": "Concluído",
                "draft": "Rascunho",
            },
        }
        return labels.get(self.ui_language, labels["en"]).get(status, status)

    def _job_status_priority(self, status: str) -> int:
        order = {
            "running": 0,
            "failed": 1,
            "blocked": 2,
            "stopped": 3,
            "prepared": 4,
            "queued": 5,
            "draft": 6,
            "completed": 7,
        }
        return order.get(status, 99)

    def _job_matches_filter(self, job: JobState, filter_key: str, needle: str) -> bool:
        if filter_key == "running" and job.status != "running":
            return False
        if filter_key == "waiting" and job.status not in {"queued", "prepared"}:
            return False
        if filter_key == "attention" and job.status not in {"failed", "blocked", "stopped"}:
            return False
        if filter_key == "blocked" and job.status != "blocked":
            return False
        if filter_key == "failed" and job.status != "failed":
            return False
        if not needle:
            return True
        haystack = " ".join(
            [
                job.title,
                job.saved_profile_name or "",
                job.backend,
                job.voice_id or "",
                job.voice_profile_id or "",
                Path(job.source_file).name if job.source_file else "",
            ]
        ).lower()
        return needle in haystack

    def _job_list_item_text(self, job: JobState) -> str:
        backend_text = f"{job.backend.upper()} · {job.device_mode.upper()} · P{job.priority:02d}"
        profile_text = job.saved_profile_name or (job.voice_profile_id or job.voice_id or "-")
        status_text = self._job_status_display(job.status)
        eta_seconds = job.estimated_remaining_seconds or job.estimated_total_seconds
        eta_text = self._eta_short_label(eta_seconds)
        progress_text = f"{job.completed_chunks}/{job.total_chunks} Chunks" if job.total_chunks else "Noch keine Chunks"
        if job.block_reason:
            progress_text += f" · {job.block_reason}"
        return (
            f"{job.title}\n"
            f"{status_text} · {progress_text} · {eta_text}\n"
            f"{backend_text} · {profile_text}"
        )

    def refresh_active_jobs_sidebar(self) -> None:
        self.jobs_list.clear()
        active_jobs = list(self.cached_active_jobs)
        filter_key = self.job_status_filter_combo.currentData() or "all"
        search_term = self.job_search_edit.text().strip().lower()
        visible_jobs = [
            job
            for job in sorted(
                active_jobs,
                key=lambda job: (
                    self._job_status_priority(job.status),
                    job.priority,
                    job.title.lower(),
                ),
            )
            if self._job_matches_filter(job, str(filter_key), search_term)
        ]
        counts = Counter(job.status for job in active_jobs)
        running_count = counts.get("running", 0)
        waiting_count = counts.get("queued", 0) + counts.get("prepared", 0)
        attention_count = counts.get("failed", 0) + counts.get("blocked", 0) + counts.get("stopped", 0)
        completed_eta_jobs = [job for job in active_jobs if job.estimated_remaining_seconds > 0]
        total_eta = sum(job.estimated_remaining_seconds for job in completed_eta_jobs)
        eta_text = self._format_duration_hm(total_eta) if completed_eta_jobs else self._tr("queue.eta.learning")
        self.job_list_overview_label.setText(
            {
                "de": f"Läuft {running_count} · Wartet {waiting_count} · Aufmerksamkeit {attention_count} · Sichtbar {len(visible_jobs)}/{len(active_jobs)} · Queue ca. {eta_text}",
                "en": f"Running {running_count} · Waiting {waiting_count} · Needs attention {attention_count} · Visible {len(visible_jobs)}/{len(active_jobs)} · Queue approx. {eta_text}",
                "es": f"En curso {running_count} · En espera {waiting_count} · Atención {attention_count} · Visible {len(visible_jobs)}/{len(active_jobs)} · Cola aprox. {eta_text}",
                "pt": f"Em execução {running_count} · Em espera {waiting_count} · Atenção {attention_count} · Visível {len(visible_jobs)}/{len(active_jobs)} · Fila aprox. {eta_text}",
            }.get(self.ui_language, f"Running {running_count} · Waiting {waiting_count} · Needs attention {attention_count} · Visible {len(visible_jobs)}/{len(active_jobs)} · Queue approx. {eta_text}")
        )
        self.job_list_filter_hint.setText(
            {
                "de": f"Filter: {self.job_status_filter_combo.currentText()} | Suche: {self.job_search_edit.text().strip() or 'keine'}",
                "en": f"Filter: {self.job_status_filter_combo.currentText()} | Search: {self.job_search_edit.text().strip() or 'none'}",
                "es": f"Filtro: {self.job_status_filter_combo.currentText()} | Búsqueda: {self.job_search_edit.text().strip() or 'ninguna'}",
                "pt": f"Filtro: {self.job_status_filter_combo.currentText()} | Pesquisa: {self.job_search_edit.text().strip() or 'nenhuma'}",
            }.get(self.ui_language, f"Filter: {self.job_status_filter_combo.currentText()} | Search: {self.job_search_edit.text().strip() or 'none'}")
        )
        for job in visible_jobs:
            item = QListWidgetItem(self._job_list_item_text(job))
            item.setData(Qt.UserRole, job.job_id)
            item.setToolTip(
                "\n".join(
                    [
                        f"Status: {self._job_status_display(job.status)}",
                        f"Profil: {job.saved_profile_name or '-'}",
                        f"Backend: {job.backend}",
                        f"Verarbeitung: {job.processing_mode} auf {job.device_mode}",
                        f"Schätzung gesamt: {self._format_duration_hm(job.estimated_total_seconds)}",
                        f"Restzeit: {self._format_duration_hm(job.estimated_remaining_seconds)}",
                        f"Datenbasis: {job.estimated_from_samples} Lauf/Läufe ({job.estimated_confidence})",
                        f"Quelle: {Path(job.source_file).name if job.source_file else '-'}",
                    ]
                )
            )
            self.jobs_list.addItem(item)
        if self.current_job_id:
            for row in range(self.jobs_list.count()):
                item = self.jobs_list.item(row)
                if item.data(Qt.UserRole) == self.current_job_id:
                    self.jobs_list.setCurrentRow(row)
                    break

    def refresh_jobs(self) -> None:
        jobs = self.manager.list_jobs()
        active_jobs = [job for job in jobs if job.status != "completed"]
        self.cached_jobs = list(jobs)
        self.cached_active_jobs = list(active_jobs)
        self.logger.info("Refreshing jobs list with %s jobs", len(jobs))
        queue_lines = []
        for job in sorted(
            active_jobs,
            key=lambda job: (
                self._job_status_priority(job.status),
                job.priority,
                job.title.lower(),
            ),
        ):
            queue_lines.append(
                f"P{job.priority:02d} | {self._job_status_display(job.status):11s} | {job.title} | preset={job.preset_id} | "
                f"output={job.output_mode} | ziel={job.target_part_minutes}m | "
                f"profil={job.saved_profile_name or '-'} | voice={job.voice_id or job.voice_profile_id} | "
                f"mode={job.processing_mode} | eta={self._format_duration_hm(job.estimated_remaining_seconds)}"
                + (f" | block={job.block_reason}" if job.block_reason else "")
            )
        self.refresh_active_jobs_sidebar()
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
            "\n".join(preview_lines) or "Keine gespeicherten Profilstudio-Sessions vorhanden."
        )
        queued_jobs = [job for job in active_jobs if job.status in {"queued", "prepared", "running"}]
        queued_eta_seconds = sum(max(0.0, job.estimated_remaining_seconds) for job in queued_jobs)
        processing_modes: dict[str, int] = {}
        for job in queued_jobs:
            processing_modes[job.processing_mode] = processing_modes.get(job.processing_mode, 0) + 1
        if queued_jobs:
            queued_eta_text = self._format_duration_hm(queued_eta_seconds)
            self.queue_runtime_summary.setText(
                {
                    "de": f"{len(queued_jobs)} aktive oder wartende Aufträge | kumulierte Restzeit ca. {queued_eta_text} | Modi {processing_modes}",
                    "en": f"{len(queued_jobs)} active or queued jobs | combined remaining time approx. {queued_eta_text} | modes {processing_modes}",
                    "es": f"{len(queued_jobs)} trabajos activos o en cola | tiempo restante combinado aprox. {queued_eta_text} | modos {processing_modes}",
                    "pt": f"{len(queued_jobs)} tarefas ativas ou na fila | tempo restante combinado aprox. {queued_eta_text} | modos {processing_modes}",
                }.get(self.ui_language, f"{len(queued_jobs)} active or queued jobs | combined remaining time approx. {queued_eta_text} | modes {processing_modes}")
            )
        else:
            self.queue_runtime_summary.setText(
                {
                    "de": "Keine aktiven oder wartenden Aufträge. Noch keine Restzeit in der Queue.",
                    "en": "No active or queued jobs. No remaining queue time yet.",
                    "es": "No hay trabajos activos o en cola. Aún no hay tiempo restante de cola.",
                    "pt": "Não há tarefas ativas ou na fila. Ainda não existe tempo restante da fila.",
                }.get(self.ui_language, "No active or queued jobs. No remaining queue time yet.")
            )
        self.queue_eta_header.setText(self._queue_eta_overview_text(active_jobs))
        self.refresh_finished_books_list(jobs)
        self.refresh_diagnostics_summary()
        self.update_idle_status_from_queue(active_jobs)

    def refresh_finished_books_list(self, jobs: list[JobState]) -> None:
        self.finished_books_list.clear()
        completed_jobs = [job for job in jobs if job.status == "completed" and job.final_output_files]
        for job in completed_jobs:
            author = job.audiobook_metadata.author or "-"
            duration = f"{job.actual_total_seconds/60:.1f} min" if job.actual_total_seconds > 0 else self._eta_short_label(job.estimated_total_seconds)
            file_word = {
                "de": "Datei(en)",
                "en": "file(s)",
                "es": "archivo(s)",
                "pt": "arquivo(s)",
            }.get(self.ui_language, "file(s)")
            item = QListWidgetItem(f"{job.audiobook_metadata.title} | {author} | {len(job.final_output_files)} {file_word} | {duration}")
            item.setData(Qt.UserRole, job.job_id)
            item.setToolTip(
                "\n".join(
                    [
                        f"{self._text('Titel')}: {job.audiobook_metadata.title}",
                        f"{self._text('Autor')}: {job.audiobook_metadata.author or '-'}",
                        f"{self._text('Sprecher')}: {job.audiobook_metadata.narrator or '-'}",
                        f"{self._text('Ausgabe')}: {self._job_output_dir(job)}",
                    ]
                )
            )
            self.finished_books_list.addItem(item)
        if self.current_job_id:
            for row in range(self.finished_books_list.count()):
                item = self.finished_books_list.item(row)
                if item.data(Qt.UserRole) == self.current_job_id:
                    self.finished_books_list.setCurrentRow(row)
                    break

    def _selected_finished_job(self) -> JobState | None:
        item = self.finished_books_list.currentItem()
        if item is None:
            return None
        job_id = item.data(Qt.UserRole)
        if not job_id:
            return None
        return self.manager.load_state(job_id)

    def _finished_metadata_needs_enrichment(self, job: JobState) -> bool:
        title = job.audiobook_metadata.title.strip()
        author = job.audiobook_metadata.author.strip()
        genre = job.audiobook_metadata.genre.strip()
        language = job.audiobook_metadata.language.strip()
        source_stem = Path(job.source_file).stem.strip()
        return (
            not title
            or not author
            or not genre
            or not language
            or title == source_stem
        )

    def on_finished_book_selected(self) -> None:
        job = self._selected_finished_job()
        if job is None:
            self.refresh_finished_metadata_editor(None)
            return
        self.current_job_id = job.job_id
        self.jobs_list.clearSelection()
        self.show_job(job)
        self.refresh_finished_metadata_editor(job)
        self.populate_finished_metadata_from_filename(auto_run=True)

    def refresh_finished_metadata_editor(self, job: JobState | None) -> None:
        fields = (
            self.finished_meta_title_edit,
            self.finished_meta_author_edit,
            self.finished_meta_narrator_edit,
            self.finished_meta_genre_edit,
            self.finished_meta_language_edit,
            self.finished_meta_publisher_edit,
            self.finished_meta_year_edit,
            self.finished_meta_subject_edit,
            self.finished_meta_isbn_edit,
        )
        for field in fields:
            field.setEnabled(job is not None)
        self.finished_meta_comment_edit.setEnabled(job is not None)
        self.finished_metadata_guess_button.setEnabled(job is not None)
        self.finished_metadata_search_button.setEnabled(job is not None)
        self.finished_metadata_apply_button.setEnabled(job is not None)
        self.finished_metadata_save_button.setEnabled(job is not None)
        self.finished_metadata_results_list.setEnabled(job is not None)
        if job is None:
            for field in fields:
                field.clear()
            self.finished_meta_comment_edit.setPlainText("")
            self.finished_metadata_results_list.clear()
            self.finished_metadata_status_label.setText(
                {
                    "de": "Wähle unten ein fertiges Hörbuch, um Metadaten zu prüfen oder nachzutragen.",
                    "en": "Choose a finished audiobook below to review or update its metadata.",
                    "es": "Elige abajo un audiolibro terminado para revisar o actualizar sus metadatos.",
                    "pt": "Escolha abaixo um audiolivro concluído para revisar ou atualizar seus metadados.",
                }.get(self.ui_language, "Choose a finished audiobook below to review or update its metadata.")
            )
            return
        meta = job.audiobook_metadata
        self.finished_meta_title_edit.setText(meta.title)
        self.finished_meta_author_edit.setText(meta.author)
        self.finished_meta_narrator_edit.setText(meta.narrator)
        self.finished_meta_genre_edit.setText(meta.genre)
        self.finished_meta_language_edit.setText(meta.language)
        self.finished_meta_publisher_edit.setText(meta.publisher)
        self.finished_meta_year_edit.setText(str(meta.year or ""))
        self.finished_meta_subject_edit.setText(meta.subject)
        self.finished_meta_isbn_edit.setText(meta.isbn)
        self.finished_meta_comment_edit.setPlainText(meta.comment)
        self.finished_metadata_results_list.clear()
        self.finished_metadata_status_label.setText(
            {
                "de": f"Fertiges Hörbuch geladen. Änderungen werden direkt in die MP3-Tags und Manifeste geschrieben: {job.audiobook_metadata.title}",
                "en": f"Finished audiobook loaded. Changes are written directly into the MP3 tags and manifests: {job.audiobook_metadata.title}",
                "es": f"Audiolibro terminado cargado. Los cambios se escribirán directamente en las etiquetas MP3 y manifiestos: {job.audiobook_metadata.title}",
                "pt": f"Audiolivro concluído carregado. As alterações serão gravadas diretamente nas tags MP3 e nos manifestos: {job.audiobook_metadata.title}",
            }.get(self.ui_language, f"Finished audiobook loaded. Changes are written directly into the MP3 tags and manifests: {job.audiobook_metadata.title}")
        )

    def _finished_metadata_payload(self) -> dict[str, str]:
        title = self.finished_meta_title_edit.text().strip()
        narrator = self.finished_meta_narrator_edit.text().strip()
        year_text = self.finished_meta_year_edit.text().strip()
        year_value = int(year_text) if year_text.isdigit() else 0
        payload = {
            "title": title,
            "album": title,
            "artist": narrator,
            "album_artist": narrator,
            "narrator": narrator,
            "author": self.finished_meta_author_edit.text().strip(),
            "genre": self.finished_meta_genre_edit.text().strip() or "Audiobook",
            "language": self.finished_meta_language_edit.text().strip() or preferred_content_language_code(self.ui_language).split("_", 1)[0],
            "publisher": self.finished_meta_publisher_edit.text().strip(),
            "year": year_value,
            "subject": self.finished_meta_subject_edit.text().strip(),
            "isbn": self.finished_meta_isbn_edit.text().strip(),
            "description": self.finished_meta_comment_edit.toPlainText().strip(),
            "comment": self.finished_meta_comment_edit.toPlainText().strip(),
        }
        return {key: value for key, value in payload.items() if value}

    def populate_finished_metadata_from_filename(self, auto_run: bool = False) -> None:
        job = self._selected_finished_job()
        if job is None:
            return
        try:
            suggestions = self.service.metadata_suggestions(Path(job.source_file))
        except Exception as exc:
            self.finished_metadata_status_label.setText(
                {
                    "de": f"Automatische Metadatenerkennung für das fertige Hörbuch fehlgeschlagen: {exc}",
                    "en": f"Automatic metadata detection for the finished audiobook failed: {exc}",
                    "es": f"La detección automática de metadatos para el audiolibro terminado falló: {exc}",
                    "pt": f"A detecção automática de metadados para o audiolivro concluído falhou: {exc}",
                }.get(self.ui_language, f"Automatic metadata detection for the finished audiobook failed: {exc}")
            )
            return
        guessed = suggestions.get("guessed") or {}
        extended = suggestions.get("extended_book_metadata") or {}
        results = suggestions.get("results") or suggestions.get("candidates") or []
        if isinstance(results, list):
            self._populate_metadata_results_list(
                self.finished_metadata_results_list,
                [entry for entry in results if isinstance(entry, dict)],
            )
        confidence = float(suggestions.get("confidence") or 0.0)
        title_source = str(suggestions.get("title_source") or "-")
        author_source = str(suggestions.get("author_source") or "-")
        confidence_band = self._metadata_confidence_band(confidence)
        metadata_needs_enrichment = self._finished_metadata_needs_enrichment(job)
        should_apply = metadata_needs_enrichment and confidence_band in {"high", "medium"}
        if should_apply and isinstance(guessed, dict):
            self._apply_metadata_payload_to_finished_fields(
                guessed,
                extended=extended if isinstance(extended, dict) else {},
            )
        if confidence_band == "high":
            prefix = {
                "de": "Fertiges Hörbuch automatisch erkannt und übernommen.",
                "en": "Finished audiobook metadata detected and applied automatically.",
                "es": "Los metadatos del audiolibro terminado se detectaron y aplicaron automáticamente.",
                "pt": "Os metadados do audiolivro concluído foram detectados e aplicados automaticamente.",
            }.get(self.ui_language, "Finished audiobook metadata detected and applied automatically.")
        elif confidence_band == "medium":
            prefix = {
                "de": "Fertiges Hörbuch automatisch analysiert. Bitte kurz prüfen.",
                "en": "Finished audiobook analyzed automatically. Please review briefly.",
                "es": "Audiolibro terminado analizado automáticamente. Revísalo brevemente.",
                "pt": "Audiolivro concluído analisado automaticamente. Revise rapidamente.",
            }.get(self.ui_language, "Finished audiobook analyzed automatically. Please review briefly.")
        else:
            prefix = {
                "de": "Automatik unsicher. Bitte Trefferliste prüfen und Metadaten manuell übernehmen.",
                "en": "Automatic detection is unsure. Review the match list and apply metadata manually.",
                "es": "La detección automática es incierta. Revisa la lista y aplica los metadatos manualmente.",
                "pt": "A detecção automática é incerta. Revise a lista e aplique os metadados manualmente.",
            }.get(self.ui_language, "Automatic detection is unsure. Review the match list and apply metadata manually.")
        self.finished_metadata_status_label.setText(
            f"{prefix} "
            + {
                "de": f"Konfidenz {confidence:.2f}, Titelquelle {title_source}, Autorquelle {author_source}.",
                "en": f"Confidence {confidence:.2f}, title source {title_source}, author source {author_source}.",
                "es": f"Confianza {confidence:.2f}, origen del título {title_source}, origen del autor {author_source}.",
                "pt": f"Confiança {confidence:.2f}, origem do título {title_source}, origem do autor {author_source}.",
            }.get(
                self.ui_language,
                f"Confidence {confidence:.2f}, title source {title_source}, author source {author_source}.",
            )
        )

    def search_finished_metadata_online(self) -> None:
        job = self._selected_finished_job()
        if job is None:
            return
        try:
            suggestions = self.service.search_book_metadata(
                title=self.finished_meta_title_edit.text().strip(),
                author=self.finished_meta_author_edit.text().strip(),
                query=f"{self.finished_meta_title_edit.text().strip()} {self.finished_meta_author_edit.text().strip()}".strip(),
                limit=5,
            )
        except Exception as exc:
            self.finished_metadata_status_label.setText(
                {
                    "de": f"Metadatensuche für das fertige Hörbuch fehlgeschlagen: {exc}",
                    "en": f"Metadata search for the finished audiobook failed: {exc}",
                    "es": f"La búsqueda de metadatos para el audiolibro terminado falló: {exc}",
                    "pt": f"A busca de metadados para o audiolivro concluído falhou: {exc}",
                }.get(self.ui_language, f"Metadata search for the finished audiobook failed: {exc}")
            )
            return
        self._populate_metadata_results_list(self.finished_metadata_results_list, suggestions)
        self.finished_metadata_status_label.setText(
            {
                "de": f"Online-Suche für das fertige Hörbuch abgeschlossen: {len(suggestions)} Treffer.",
                "en": f"Online search for the finished audiobook finished: {len(suggestions)} result(s).",
                "es": f"La búsqueda online para el audiolibro terminado finalizó: {len(suggestions)} resultado(s).",
                "pt": f"A busca online para o audiolivro concluído terminou: {len(suggestions)} resultado(s).",
            }.get(self.ui_language, f"Online search for the finished audiobook finished: {len(suggestions)} result(s).")
        )

    def apply_finished_metadata_result(self) -> None:
        item = self.finished_metadata_results_list.currentItem()
        if item is None and self.finished_metadata_results_list.count():
            item = self.finished_metadata_results_list.item(0)
        if item is None:
            return
        entry = item.data(Qt.UserRole) or {}
        if isinstance(entry, dict):
            self._apply_metadata_payload_to_finished_fields(entry, extended=entry)
        self.finished_metadata_status_label.setText(
            {
                "de": "Die ausgewählten Metadaten wurden auf das fertige Hörbuch übertragen. Speichere jetzt die Tags, um die Enddateien zu aktualisieren.",
                "en": "The selected metadata has been copied to the finished audiobook. Save the tags now to update the final files.",
                "es": "Los metadatos seleccionados se copiaron al audiolibro terminado. Guarda ahora las etiquetas para actualizar los archivos finales.",
                "pt": "Os metadados selecionados foram copiados para o audiolivro concluído. Agora salve as tags para atualizar os arquivos finais.",
            }.get(self.ui_language, "The selected metadata has been copied to the finished audiobook. Save the tags now to update the final files.")
        )

    def save_finished_job_metadata(self) -> None:
        job = self._selected_finished_job()
        if job is None:
            return
        updated = self.service.update_job_metadata(
            job.job_id,
            audiobook_metadata=self._finished_metadata_payload(),
            reapply_outputs=True,
        )
        updated_state = self.manager.load_state(job.job_id)
        self.refresh_jobs()
        self.refresh_finished_metadata_editor(updated_state)
        self.show_job(updated_state)
        self.status_label.setText(
            {
                "de": f"Metadaten und MP3-Tags für '{updated_state.audiobook_metadata.title}' wurden aktualisiert.",
                "en": f"Metadata and MP3 tags for '{updated_state.audiobook_metadata.title}' were updated.",
                "es": f"Se actualizaron los metadatos y las etiquetas MP3 de '{updated_state.audiobook_metadata.title}'.",
                "pt": f"Os metadados e as tags MP3 de '{updated_state.audiobook_metadata.title}' foram atualizados.",
            }.get(self.ui_language, f"Metadata and MP3 tags for '{updated_state.audiobook_metadata.title}' were updated.")
        )

    def open_selected_finished_audio(self) -> None:
        job = self._selected_finished_job()
        if not job or not job.final_output_files:
            return
        self.open_path(Path(job.final_output_files[0]))

    def _suggest_finished_download_name(self, job: JobState, source_path: Path) -> str:
        title = (job.audiobook_metadata.title or job.title or source_path.stem).strip()
        author = (job.audiobook_metadata.author or "").strip()
        label = f"{author} - {title}" if author else title
        safe = "".join(character if character not in '<>:"/\\|?*' else "_" for character in label).strip()
        return safe or source_path.name

    def download_selected_finished_audio(self) -> None:
        job = self._selected_finished_job()
        if not job or not job.final_output_files:
            return
        output_paths = [Path(path) for path in job.final_output_files if Path(path).exists()]
        if not output_paths:
            self.status_label.setText(
                {
                    "de": "Keine fertigen Ausgabedateien gefunden.",
                    "en": "No finished output files were found.",
                    "es": "No se encontraron archivos finales.",
                    "pt": "Nenhum arquivo final foi encontrado.",
                }.get(self.ui_language, "No finished output files were found.")
            )
            return
        if len(output_paths) == 1:
            source_path = output_paths[0]
            suggested_name = self._suggest_finished_download_name(job, source_path)
            target_path, _ = QFileDialog.getSaveFileName(
                self,
                self._text("Hörbuch herunterladen"),
                str(Path.home() / f"{suggested_name}{source_path.suffix}"),
                "MP3-Dateien (*.mp3);;Alle Dateien (*)",
            )
            if not target_path:
                return
            shutil.copy2(source_path, Path(target_path))
            self.status_label.setText(
                {
                    "de": f"Fertiges Hörbuch gespeichert: {target_path}",
                    "en": f"Finished audiobook saved: {target_path}",
                    "es": f"Audiolibro terminado guardado: {target_path}",
                    "pt": f"Audiolivro concluído salvo: {target_path}",
                }.get(self.ui_language, f"Finished audiobook saved: {target_path}")
            )
            return
        target_dir = QFileDialog.getExistingDirectory(
            self,
            self._text("Hörbuch herunterladen"),
            str(Path.home()),
        )
        if not target_dir:
            return
        export_dir = Path(target_dir) / self._suggest_finished_download_name(job, output_paths[0])
        export_dir.mkdir(parents=True, exist_ok=True)
        for source_path in output_paths:
            shutil.copy2(source_path, export_dir / source_path.name)
        if job.manifest_file and Path(job.manifest_file).exists():
            shutil.copy2(Path(job.manifest_file), export_dir / Path(job.manifest_file).name)
        if job.chapters_file and Path(job.chapters_file).exists():
            shutil.copy2(Path(job.chapters_file), export_dir / Path(job.chapters_file).name)
        self.status_label.setText(
            {
                "de": f"Fertige Hörbuchdateien exportiert nach: {export_dir}",
                "en": f"Finished audiobook files exported to: {export_dir}",
                "es": f"Archivos del audiolibro exportados a: {export_dir}",
                "pt": f"Arquivos do audiolivro exportados para: {export_dir}",
            }.get(self.ui_language, f"Finished audiobook files exported to: {export_dir}")
        )

    def open_selected_finished_folder(self) -> None:
        job = self._selected_finished_job()
        if not job:
            return
        self.open_path(self._job_output_dir(job))

    def delete_selected_finished_job(self) -> None:
        job = self._selected_finished_job()
        if not job:
            return
        answer = QMessageBox.question(
            self,
            self._text("Loeschen"),
            {
                "de": f"Soll das fertige Hörbuchprojekt '{job.audiobook_metadata.title}' inklusive Arbeitsordner wirklich gelöscht werden?",
                "en": f"Do you really want to delete the finished audiobook project '{job.audiobook_metadata.title}' including its working folder?",
                "es": f"¿De verdad quieres eliminar el proyecto de audiolibro terminado '{job.audiobook_metadata.title}' junto con su carpeta de trabajo?",
                "pt": f"Tem certeza de que deseja excluir o projeto de audiolivro concluído '{job.audiobook_metadata.title}' junto com a pasta de trabalho?",
            }.get(self.ui_language, f"Do you really want to delete the finished audiobook project '{job.audiobook_metadata.title}' including its working folder?"),
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        if self.current_job_id == job.job_id:
            self.current_job_id = None
        self.manager.delete_job(job.job_id)
        self.refresh_jobs()

    def on_preset_changed(self) -> None:
        preset_id = self.preset_combo.currentData()
        preset = get_preset(preset_id)
        self.max_chars_spin.setValue(preset.max_chars)
        output_mode_index = self.output_mode_combo.findData(preset.output_mode)
        if output_mode_index >= 0:
            self.output_mode_combo.setCurrentIndex(output_mode_index)
        self.target_part_minutes_spin.setValue(preset.target_part_minutes)
        self.keep_wav_checkbox.setChecked(preset.keep_wav)
        output_label = self._output_mode_label(preset.output_mode, preset.target_part_minutes)
        if self.backend_combo.currentText() == "xtts":
            self.preset_description.setText(
                f"{preset.description} XTTS nutzt vor allem Chunk-Laenge und Sprechtempo. "
                f"Enddateien: {output_label}."
            )
        else:
            self.preset_description.setText(
                f"{preset.description} Satzpause: {preset.sentence_silence:.2f}s, Laenge: {preset.length_scale:.2f}, "
                f"Enddateien: {output_label}."
            )

    def select_source_files(self) -> None:
        dialog_title = {
            "de": "Quelldateien auswählen",
            "en": "Choose source files",
            "es": "Elegir archivos fuente",
            "pt": "Escolher arquivos de origem",
        }.get(self.ui_language, "Choose source files")
        file_filter = {
            "de": "Unterstützte Quellen (*.txt *.pdf *.epub);;Textdateien (*.txt);;PDF-Dateien (*.pdf);;EPUB-Dateien (*.epub);;Alle Dateien (*)",
            "en": "Supported sources (*.txt *.pdf *.epub);;Text files (*.txt);;PDF files (*.pdf);;EPUB files (*.epub);;All files (*)",
            "es": "Fuentes compatibles (*.txt *.pdf *.epub);;Archivos de texto (*.txt);;Archivos PDF (*.pdf);;Archivos EPUB (*.epub);;Todos los archivos (*)",
            "pt": "Fontes compatíveis (*.txt *.pdf *.epub);;Arquivos de texto (*.txt);;Arquivos PDF (*.pdf);;Arquivos EPUB (*.epub);;Todos os arquivos (*)",
        }.get(self.ui_language, "Supported sources (*.txt *.pdf *.epub);;Text files (*.txt);;PDF files (*.pdf);;EPUB files (*.epub);;All files (*)")
        filenames, _ = QFileDialog.getOpenFileNames(
            self,
            dialog_title,
            str(self.paths.root),
            file_filter,
        )
        if filenames:
            self.set_selected_source_files([Path(filename) for filename in filenames])
            self.logger.info("Selected source files %s", filenames)

    def create_job(self) -> None:
        if not self.selected_source_files:
            QMessageBox.warning(
                self,
                self._text("Quelle fehlt"),
                {
                    "de": "Bitte mindestens eine vorhandene TXT-, PDF- oder EPUB-Datei wählen.",
                    "en": "Please choose at least one existing TXT, PDF, or EPUB file.",
                    "es": "Elige al menos un archivo TXT, PDF o EPUB existente.",
                    "pt": "Escolha pelo menos um arquivo TXT, PDF ou EPUB existente.",
                }.get(self.ui_language, "Please choose at least one existing TXT, PDF, or EPUB file."),
            )
            return
        setting_id = self.saved_profile_combo.currentData() or ""
        if not setting_id:
            QMessageBox.warning(
                self,
                self._text("Kein Produktionsprofil"),
                {
                    "de": "Im Auftragsdialog kann nur mit einem freigegebenen Produktionsprofil gearbeitet werden. Bitte öffne zuerst die Profilbibliothek und gib dort ein getestetes Profil frei.",
                    "en": "The job creator only works with approved production profiles. Please open the profile library first and approve a tested profile there.",
                    "es": "El creador de trabajos solo funciona con perfiles de producción aprobados. Primero abre la biblioteca de perfiles y aprueba allí un perfil probado.",
                    "pt": "O criador de tarefas só funciona com perfis de produção aprovados. Primeiro abra a biblioteca de perfis e aprove lá um perfil testado.",
                }.get(self.ui_language, "The job creator only works with approved production profiles. Please open the profile library first and approve a tested profile there."),
            )
            return
        setting = load_voice_setting(self.paths.voice_settings, setting_id)
        if setting.status != PROFILE_STATUS_APPROVED:
            QMessageBox.warning(
                self,
                self._text("Profil nicht freigegeben"),
                {
                    "de": "Dieses Produktionsprofil ist noch nicht freigegeben. Bitte gib es zuerst in der Profilbibliothek frei.",
                    "en": "This production profile is not approved yet. Please approve it first in the profile library.",
                    "es": "Este perfil de producción todavía no está aprobado. Apruébalo primero en la biblioteca de perfiles.",
                    "pt": "Este perfil de produção ainda não está aprovado. Aprove-o primeiro na biblioteca de perfis.",
                }.get(self.ui_language, "This production profile is not approved yet. Please approve it first in the profile library."),
            )
            return
        backend = setting.backend.strip().lower()
        voice_id = setting.voice_id
        voice_profile_id = setting.voice_profile_id
        if backend == "xtts" and not self.xtts_backend.is_available():
            QMessageBox.warning(self, "XTTS runtime fehlt", self.xtts_backend.availability_reason())
            return
        jobs = self.service.create_jobs(
            source_paths=self.selected_source_files,
            saved_profile_id=setting.setting_id,
            backend=backend,
            voice_id=voice_id,
            voice_profile_id=voice_profile_id,
            preset_id=setting.preset_hint,
            priority=self.priority_spin.value(),
            max_chars=setting.max_chars,
            output_mode=self.selected_job_output_mode(),
            target_part_minutes=setting.target_part_minutes,
            keep_wav=False,
            sentence_silence=setting.sentence_silence,
            length_scale=setting.length_scale,
            audiobook_metadata=self._metadata_payload_for_source(self.selected_source_files[0]),
        )
        if not jobs:
            QMessageBox.warning(
                self,
                self._text("Keine Jobs erzeugt"),
                {
                    "de": "Aus der Auswahl konnten keine Aufträge erstellt werden.",
                    "en": "No jobs could be created from the current selection.",
                    "es": "No se pudieron crear trabajos a partir de la selección actual.",
                    "pt": "Nenhuma tarefa pôde ser criada a partir da seleção atual.",
                }.get(self.ui_language, "No jobs could be created from the current selection."),
            )
            return
        self.current_job_id = str(jobs[0]["job_id"])
        self.logger.info("Created %s job(s) from selected sources", len(jobs))
        self.refresh_jobs()
        self.show_job(self.manager.load_state(self.current_job_id))
        self.status_label.setText(
            {
                "de": f"{len(jobs)} Auftrag/Aufträge aus Produktionsprofil erstellt: {setting.display_name}",
                "en": f"{len(jobs)} job(s) created from production profile: {setting.display_name}",
                "es": f"Se crearon {len(jobs)} trabajo(s) desde el perfil de producción: {setting.display_name}",
                "pt": f"Foram criadas {len(jobs)} tarefa(s) a partir do perfil de produção: {setting.display_name}",
            }.get(self.ui_language, f"{len(jobs)} job(s) created from production profile: {setting.display_name}")
        )

    def on_job_selected(self) -> None:
        item = self.jobs_list.currentItem()
        if not item:
            return
        job_id = item.data(Qt.UserRole)
        self.current_job_id = job_id
        self.finished_books_list.clearSelection()
        self.refresh_finished_metadata_editor(None)
        self.logger.info("Selected job %s", job_id)
        self.show_job(self.manager.load_state(job_id))

    def show_job(self, job: JobState) -> None:
        self.status_label.setText(
            f"{job.status} | backend {job.backend} | profil {job.saved_profile_name or '-'} | priority {job.priority} | preset {job.preset_id} | "
            f"output {job.output_mode} | ziel {job.target_part_minutes}m | chunks {job.completed_chunks}/{job.total_chunks} | "
            f"voice {job.voice_id or job.voice_profile_id}"
            + (f" | block {job.block_reason}" if job.block_reason else "")
        )
        self.progress_bar.setValue(
            int((job.completed_chunks / job.total_chunks) * 100) if job.total_chunks else 0
        )
        self.job_summary.setPlainText(self.build_job_summary(job))
        self.job_runtime_summary.setText(self._job_runtime_summary_text(job))
        self.populate_job_detail_lists(job)
        self.refresh_job_selection_details()
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
        profile_index = self.saved_profile_combo.findData(job.saved_profile_id)
        if profile_index >= 0:
            self.saved_profile_combo.setCurrentIndex(profile_index)
        self.target_part_minutes_spin.setValue(job.target_part_minutes)
        self.keep_wav_checkbox.setChecked(job.keep_wav)
        self.update_job_transport_buttons(job)
        self.update_output_mode_controls()
        self.refresh_diagnostics_summary()
        self.logger.debug("Displayed job %s with status %s", job.job_id, job.status)

    def update_job_transport_buttons(self, job: JobState | None) -> None:
        has_job = job is not None
        is_running = bool(self.worker and self.worker.isRunning() and job and job.job_id == self.current_job_id)
        can_resume = bool(job and job.status in {"queued", "prepared", "stopped", "failed", "blocked"})
        self.play_job_button.setEnabled(has_job and can_resume)
        self.pause_job_button.setEnabled(is_running)
        self.stop_job_button.setEnabled(is_running)

    def start_selected_job(self) -> None:
        if not self.current_job_id:
            QMessageBox.warning(self, "Kein Auftrag", "Bitte zuerst einen Auftrag erstellen oder auswählen.")
            return
        self.pause_requested_job_id = None
        self.manager.enqueue_job(self.current_job_id)
        self.logger.info("Start/resume requested for job %s", self.current_job_id)
        self.refresh_jobs()
        self.maybe_start_next_job()

    def pause_selected_job(self) -> None:
        if not self.current_job_id or not self.worker or not self.worker.isRunning():
            return
        self.pause_requested_job_id = self.current_job_id
        self.worker.request_stop()
        self.status_label.setText(
            {
                "de": "Pause angefordert. Der Auftrag stoppt nach dem aktuellen Chunk/Batch und bleibt danach in der Queue.",
                "en": "Pause requested. The job will stop after the current chunk/batch and then stay in the queue.",
                "es": "Pausa solicitada. El trabajo se detendrá después del fragmento/lote actual y permanecerá en la cola.",
                "pt": "Pausa solicitada. A tarefa será interrompida após o bloco/lote atual e permanecerá na fila.",
            }.get(self.ui_language, "Pause requested. The job will stop after the current chunk/batch and then stay in the queue.")
        )
        self.logger.warning("Pause requested for current running job %s", self.current_job_id)

    def queue_selected_job(self) -> None:
        if not self.current_job_id:
            QMessageBox.warning(self, "Kein Auftrag", "Bitte zuerst einen Auftrag auswählen.")
            return
        job = self.manager.enqueue_job(self.current_job_id)
        self.logger.info("Queue requested for job %s", self.current_job_id)
        self.refresh_jobs()
        self.show_job(job)
        self.maybe_start_next_job()

    def apply_priority_to_selected(self) -> None:
        if not self.current_job_id:
            QMessageBox.warning(self, "Kein Auftrag", "Bitte zuerst einen Auftrag auswählen.")
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
        self.job_summary.clear()
        self.job_stage_list.clear()
        self.job_chapter_list.clear()
        self.job_chunk_list.clear()
        self.job_selection_details.clear()
        self.details.clear()
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
        self.refresh_diagnostics_summary()

    def on_xtts_processing_mode_changed(self) -> None:
        processing_mode = self.xtts_processing_mode_combo.currentData() or "auto"
        self.app_settings.xtts_processing_mode = processing_mode
        save_app_settings(self.paths.app_settings_file, self.app_settings)
        mode_labels = {
            "auto": "XTTS-Verarbeitung lernt jetzt automatisch aus vergangenen Läufen.",
            "serial": "XTTS-Verarbeitung wurde auf seriell festgesetzt.",
            "parallel_cpu_postprocess": "XTTS-Verarbeitung bevorzugt jetzt parallelen CPU-Postprozess.",
        }
        self.status_label.setText(mode_labels.get(processing_mode, "XTTS-Verarbeitungsmodus aktualisiert."))
        self.refresh_diagnostics_summary()

    def on_xtts_device_mode_changed(self) -> None:
        device_mode = self.xtts_device_combo.currentData() or "auto"
        self.app_settings.xtts_device_mode = device_mode
        save_app_settings(self.paths.app_settings_file, self.app_settings)
        self.xtts_backend.set_device_mode(device_mode)
        self.xtts_probe_cache = None
        self.update_backend_summary()
        self.refresh_diagnostics_summary()

    def show_xtts_runtime_probe(self) -> None:
        probe = self.probe_xtts_runtime(refresh=True)
        if not probe:
            QMessageBox.warning(self, "XTTS runtime fehlt", self.xtts_backend.availability_reason())
            return
        if probe.get("ok"):
            actual = "CUDA" if probe.get("cuda_available") else "CPU"
            gpu_names = probe.get("gpu_names", [])
            host = probe.get("host_nvidia_smi", {})
            host_text = ", ".join(host.get("gpus", [])) if isinstance(host, dict) else ""
            message = (
                f"XTTS Runtime OK\n\n"
                f"Gewuenschter Modus: {self.xtts_device_combo.currentData() or 'auto'}\n"
                f"Aktueller Modus: {actual}\n"
                f"Torch: {probe.get('torch_version', '-')}\n"
                f"CUDA verfuegbar: {probe.get('cuda_available')}\n"
                f"GPU(s): {', '.join(gpu_names) or '-'}\n"
                f"Host NVIDIA: {host_text or '-'}"
            )
            QMessageBox.information(self, "XTTS Probe", message)
        else:
            QMessageBox.warning(self, "XTTS Probe", f"XTTS-Probe fehlgeschlagen:\n{probe.get('error', 'unbekannt')}")
        self.refresh_diagnostics_summary()

    def reset_application_state(self) -> None:
        if self.worker and self.worker.isRunning():
            QMessageBox.warning(self, "Job laeuft", "Bitte zuerst den aktuellen Job stoppen, bevor du alles zuruecksetzt.")
            return
        answer = QMessageBox.question(
            self,
            "Alles zuruecksetzen",
            "Soll die App auf Start zurueckgesetzt werden? Dabei werden Jobs, Produktionsprofile, Vorschau-Sessions, Logs und Voice-Profile geloescht.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        default_settings = AppSettings()
        save_app_settings(self.paths.app_settings_file, default_settings)
        self.app_settings = default_settings
        reset_workspace_state(self.paths.workspace)
        configure_logging(self.paths.logs, debug_enabled=self.app_settings.debug_logging, force_reset=True)
        self.manager = JobManager(self.paths)
        self.service = Book2Mp3Service(self.paths)
        self.current_job_id = None
        self.selected_source_files = []
        self.source_structures = {}
        self.xtts_backend.set_device_mode(self.app_settings.xtts_device_mode)
        self.xtts_probe_cache = None
        self.debug_logging_checkbox.setChecked(self.app_settings.debug_logging)
        processing_mode_index = self.xtts_processing_mode_combo.findData(self.app_settings.xtts_processing_mode)
        if processing_mode_index >= 0:
            self.xtts_processing_mode_combo.setCurrentIndex(processing_mode_index)
        self.clear_selected_source_files()
        self.apply_default_controls()
        self.job_summary.clear()
        self.job_stage_list.clear()
        self.job_chapter_list.clear()
        self.job_chunk_list.clear()
        self.job_selection_details.clear()
        self.details.clear()
        self.queue_details.clear()
        self.preview_sessions_summary.clear()
        self.diagnostics_summary.clear()
        self.status_label.setText("App auf Standard zurueckgesetzt.")
        self.refresh_voice_profiles()
        self.refresh_jobs()
        self.refresh_diagnostics_summary()

    def open_voice_lab(self) -> None:
        dialog = VoiceLabDialog(self.paths, self, ui_language=self.ui_language)
        dialog.exec()
        self.refresh_voice_profiles()
        self.refresh_diagnostics_summary()

    def import_or_open_xtts(self) -> None:
        source_root, manifests = auto_import_xtts_speakers(self.paths, fallback_language="de")
        self.refresh_voice_profiles()
        if manifests:
            self.status_label.setText(f"XTTS-Sprecher importiert: {len(manifests)} aus {source_root}")
            self.xtts_scan_hint.setText(f"Gefunden und importiert aus: {source_root}")
            backend_index = self.backend_combo.findText("xtts")
            if backend_index >= 0:
                self.backend_combo.setCurrentIndex(backend_index)
            self.refresh_diagnostics_summary()
            return
        starter_manifests = install_starter_xtts_profiles(self.paths)
        self.refresh_voice_profiles()
        if starter_manifests:
            self.status_label.setText(f"XTTS-Starter installiert: {len(starter_manifests)} Profile")
            self.xtts_scan_hint.setText("Keine Altinstallation gefunden. XTTS-Starterprofile wurden stattdessen installiert.")
            backend_index = self.backend_combo.findText("xtts")
            if backend_index >= 0:
                self.backend_combo.setCurrentIndex(backend_index)
            self.refresh_diagnostics_summary()
            return
        self.xtts_scan_hint.setText(
            "Kein befuellter XTTS speakers-Ordner gefunden und keine Starterprofile installiert. Oeffne Voice Lab fuer Details und manuelle Auswahl."
        )
        self.open_voice_lab()
        self.refresh_diagnostics_summary()

    def install_xtts_starters(self) -> None:
        manifests = install_starter_xtts_profiles(self.paths)
        self.refresh_voice_profiles()
        if manifests:
            self.status_label.setText(f"XTTS-Starter installiert: {len(manifests)}")
            self.xtts_scan_hint.setText("XTTS-Starterprofile sind jetzt verfuegbar.")
            backend_index = self.backend_combo.findText("xtts")
            if backend_index >= 0:
                self.backend_combo.setCurrentIndex(backend_index)
            self.refresh_diagnostics_summary()
            return
        self.status_label.setText("XTTS-Starter waren bereits installiert.")
        self.xtts_scan_hint.setText("XTTS-Starterprofile sind bereits vorhanden.")
        self.refresh_diagnostics_summary()

    def import_custom_piper_voice(self) -> None:
        model_filename, _ = QFileDialog.getOpenFileName(
            self,
            "Piper ONNX-Modell waehlen",
            str(self.paths.root),
            "Piper model (*.onnx)",
        )
        if not model_filename:
            return
        model_path = Path(model_filename)
        try:
            config_path = default_config_for_model(model_path)
        except FileNotFoundError:
            config_filename, _ = QFileDialog.getOpenFileName(
                self,
                "Piper JSON-Konfiguration waehlen",
                str(model_path.parent),
                "Piper config (*.json)",
            )
            if not config_filename:
                QMessageBox.warning(
                    self,
                    "Config fehlt",
                    "Ein Piper-Modell braucht die passende .onnx.json-Datei.",
                )
                return
            config_path = Path(config_filename)
        imported = import_custom_piper_model(self.paths.voices, model_path, config_path)
        self.refresh_voice_list()
        voice_index = self.voice_combo.findData(imported.voice_id)
        if voice_index >= 0:
            self.voice_combo.setCurrentIndex(voice_index)
        self.status_label.setText(f"Custom-Piper-Stimme importiert: {imported.voice_id}")
        QMessageBox.information(
            self,
            "Piper importiert",
            f"Custom-Piper-Stimme installiert:\n{imported.voice_id}\n\n{imported.model_path}",
        )
        self.refresh_diagnostics_summary()

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

    def open_find_best_setting(self, focus_assistant: bool = False) -> None:
        dialog = FindBestSettingDialog(self.paths, self.manager, self, focus_assistant=focus_assistant, ui_language=self.ui_language)
        dialog.exec()
        self.refresh_saved_profiles()
        self.refresh_jobs()
        self.refresh_diagnostics_summary()

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
        self.worker.finished.connect(self.cleanup_worker)
        self.worker.start()
        self.status_label.setText(f"running | {next_job.title}")

    def start_next_queued_job(self) -> None:
        next_job = self.manager.next_queued_job()
        if not next_job:
            QMessageBox.information(self, "Queue leer", "Es wartet gerade kein ausführbarer Auftrag in der Queue.")
            return
        self.current_job_id = next_job.job_id
        self.maybe_start_next_job()

    def stop_current_job(self) -> None:
        if self.worker and self.worker.isRunning():
            self.pause_requested_job_id = None
            self.worker.request_stop()
            self.status_label.setText("Stop requested")
            self.logger.warning("Stop requested for current running job")

    def update_idle_status_from_queue(self, jobs: list[JobState] | None = None) -> None:
        if self.worker and self.worker.isRunning():
            return
        known_jobs = jobs if jobs is not None else self.manager.list_jobs()
        queued_count = sum(1 for job in known_jobs if job.status in {"queued", "prepared"})
        blocked_count = sum(1 for job in known_jobs if job.status == "blocked")
        if queued_count:
            self.status_label.setText(self._tr("status.ready.queue", count=queued_count))
        elif blocked_count:
            self.status_label.setText(self._tr("status.ready.blocked", count=blocked_count))
        elif not self.current_job_id:
            self.status_label.setText(self._tr("status.ready.no_job"))

    def on_progress_changed(self, current: int, total: int, message: str) -> None:
        self.progress_bar.setValue(int((current / total) * 100) if total else 0)
        eta_text = ""
        if self.current_job_id:
            try:
                state = self.manager.load_state(self.current_job_id)
            except FileNotFoundError:
                state = None
            if state and state.estimated_remaining_seconds > 0:
                eta_text = f" | Rest ca. {state.estimated_remaining_seconds/60:.1f} min"
        self.status_label.setText(f"{message}{eta_text}")
        self.logger.debug("Progress update: %s/%s %s", current, total, message)

    def on_job_finished(self, state: JobState) -> None:
        skip_autostart = False
        if self.pause_requested_job_id and state.job_id == self.pause_requested_job_id and state.status == "stopped":
            state = self.manager.enqueue_job(state.job_id)
            skip_autostart = True
            self.pause_requested_job_id = None
        update_preview_job_status(
            self.paths,
            state.job_id,
            state.status,
            state.final_output_file if Path(state.final_output_file).exists() else None,
        )
        self.refresh_jobs()
        self.show_job(state)
        self.logger.info("Job finished callback for %s with status %s", state.job_id, state.status)
        if not skip_autostart:
            self.maybe_start_next_job()

    def on_job_failed(self, message: str) -> None:
        if self.current_job_id:
            update_preview_job_status(self.paths, self.current_job_id, "failed")
        self.refresh_jobs()
        self.details.appendPlainText(message)
        self.status_label.setText("failed")
        self.logger.error("Job failed callback with traceback")
        self.maybe_start_next_job()

    def cleanup_worker(self) -> None:
        worker = self.sender()
        if worker is self.worker:
            self.worker = None
        if worker is not None and hasattr(worker, "deleteLater"):
            worker.deleteLater()

    def handle_about_to_quit(self) -> None:
        if self.worker and self.worker.isRunning():
            self.logger.warning("Stopping running worker during app shutdown")
            self.worker.request_stop()
            self.worker.wait()

    def closeEvent(self, event) -> None:
        if self.worker and self.worker.isRunning():
            answer = QMessageBox.question(
                self,
                "Auftrag läuft noch",
                "Gerade wird noch ein Auftrag verarbeitet. Soll er sauber gestoppt und die App dann geschlossen werden?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.worker.request_stop()
            self.worker.wait()
        super().closeEvent(event)

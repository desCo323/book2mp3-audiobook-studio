from __future__ import annotations

from dataclasses import replace
import json
import re
import traceback
import uuid
from pathlib import Path
import time

from PySide6.QtCore import QThread, QTimer, Qt, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QRadioButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    QListWidget,
    QListWidgetItem,
)

from book2mp3.config import AppPaths
from book2mp3.app_settings import load_app_settings, save_app_settings
from book2mp3.i18n import apply_text, preferred_content_language_code, resolve_ui_language, translate_widget_tree
from book2mp3.metadata_extractor import build_author_pronunciation_rules, guess_metadata_from_filename
from book2mp3.pipeline.audio import concat_audio_files_to_mp3, concat_mp3_files, trim_wav_silence_in_place, wav_to_mp3
from book2mp3.pipeline.chunking import split_text
from book2mp3.pipeline.extract import DocumentStructure, analyze_document_structure
from book2mp3.preview_sessions import (
    attach_preview_job,
    create_preview_session,
    link_saved_setting,
    list_preview_sessions,
    refresh_preview_excerpt,
    update_preview_excerpt_text,
    update_preview_selection,
)
from book2mp3.tts.piper import PiperBackend
from book2mp3.tts.pronunciation import (
    apply_pronunciation_rules,
    suggest_explicit_pronunciation_candidates,
    suggest_pronunciation_candidates,
)
from book2mp3.tts.xtts import XttsBackend
from book2mp3.presets import QUALITY_PRESETS, get_preset
from book2mp3.ui.voice_lab_dialog import VoiceLabDialog
from book2mp3.ui.async_tasks import AsyncTaskRunner
from book2mp3.ui.theme import apply_modern_window_style
from book2mp3.utils.logging_utils import get_logger
from book2mp3.utils.perf_logging import perf_event, perf_scope
from book2mp3.voice_catalog import (
    filter_voice_ids,
    format_voice_label,
    language_choices,
    voice_filter_empty_message,
    voice_language_code,
)
from book2mp3.voice_lab import list_voice_profiles, load_voice_profile
from book2mp3.voice_settings import (
    PROFILE_STATUS_APPROVED,
    PROFILE_STATUS_ARCHIVED,
    PROFILE_STATUS_TESTED,
    list_voice_settings,
    load_voice_setting,
    profile_status_label,
    save_voice_setting,
    update_voice_setting_status,
)
from book2mp3.voice_test_assistant import (
    VoiceTestRun,
    VoiceTestCandidate,
    add_candidate_to_run,
    average_render_duration_ms,
    create_chunk_tuning_round,
    create_benchmark_run,
    create_refinement_round,
    create_voice_test_run,
    load_voice_test_run,
    record_benchmark_result,
    update_candidate_feedback,
)
from book2mp3.xtts_options import (
    default_xtts_inference,
    normalize_pronunciation_rules,
    normalize_xtts_quality_mode,
    safe_xtts_chunk_chars,
)


_XTTS_PREVIEW_HARD_LIMIT = 2400
_XTTS_DIALOG_TRANSLATION = str.maketrans(
    {
        "«": "",
        "»": "",
        "„": "",
        "“": "",
        "”": "",
        "‚": "",
        "‘": "",
        "’": "'",
    }
)


def _normalize_xtts_dialog_text(text: str) -> str:
    normalized = str(text or "").translate(_XTTS_DIALOG_TRANSLATION)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    normalized = re.sub(r"^\s*[\"']+\s*", "", normalized)
    normalized = re.sub(r"\s*[\"']+\s*$", "", normalized)
    return normalized


def _xtts_preview_sentences(text: str) -> list[str]:
    normalized = _normalize_xtts_dialog_text(text)
    if not normalized:
        return []
    return [
        match.group(0).strip()
        for match in re.finditer(r"[^.!?]+[.!?]+[\"']*|[^.!?]+$", normalized)
        if match.group(0).strip()
    ]


def _paragraph_preview_text(text: str, hard_limit: int = _XTTS_PREVIEW_HARD_LIMIT) -> str:
    normalized = _normalize_xtts_dialog_text(text)
    if len(normalized) <= hard_limit:
        return normalized

    paragraphs = []
    for paragraph in re.split(r"\n\s*\n+", str(text or "")):
        normalized_paragraph = _normalize_xtts_dialog_text(paragraph)
        if normalized_paragraph:
            paragraphs.append(normalized_paragraph)
    chosen: list[str] = []
    total = 0
    for paragraph in paragraphs:
        extra = len(paragraph) + (2 if chosen else 0)
        if chosen and total + extra > hard_limit:
            break
        if extra > hard_limit and not chosen:
            break
        chosen.append(paragraph)
        total += extra
    if chosen:
        return "\n\n".join(chosen).strip()

    sentences = _xtts_preview_sentences(normalized)
    chosen: list[str] = []
    total = 0
    for sentence in sentences:
        extra = len(sentence) + (1 if chosen else 0)
        if chosen and total + extra > hard_limit:
            break
        chosen.append(sentence)
        total += extra
    if chosen:
        return " ".join(chosen).strip()
    return normalized[:hard_limit].strip()


def _assistant_language_label(code: str, ui_language: str = "en") -> str:
    mappings = {
        "de": {
            "de": "Deutsch",
            "de_de": "Deutsch",
            "en": "Englisch",
            "en_us": "Englisch (US)",
            "en_gb": "Englisch (UK)",
            "fr": "Französisch",
            "it": "Italienisch",
            "es": "Spanisch",
            "pt": "Portugiesisch",
            "sv": "Schwedisch",
        },
        "en": {
            "de": "German",
            "de_de": "German",
            "en": "English",
            "en_us": "English (US)",
            "en_gb": "English (UK)",
            "fr": "French",
            "it": "Italian",
            "es": "Spanish",
            "pt": "Portuguese",
            "sv": "Swedish",
        },
        "es": {
            "de": "Alemán",
            "de_de": "Alemán",
            "en": "Inglés",
            "en_us": "Inglés (US)",
            "en_gb": "Inglés (UK)",
            "fr": "Francés",
            "it": "Italiano",
            "es": "Español",
            "pt": "Portugués",
            "sv": "Sueco",
        },
        "pt": {
            "de": "Alemão",
            "de_de": "Alemão",
            "en": "Inglês",
            "en_us": "Inglês (US)",
            "en_gb": "Inglês (UK)",
            "fr": "Francês",
            "it": "Italiano",
            "es": "Espanhol",
            "pt": "Português",
            "sv": "Sueco",
        },
    }
    normalized = code.lower()
    return mappings.get(ui_language, mappings["en"]).get(normalized, code)


class LivePreviewWorker(QThread):
    preview_finished = Signal(str, str, float)
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
        xtts_device_mode: str,
        xtts_quality_mode: str,
        xtts_inference: dict[str, object],
        pronunciation_rules: list[dict[str, object]],
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
        self.xtts_device_mode = xtts_device_mode
        self.xtts_quality_mode = xtts_quality_mode
        self.xtts_inference = dict(xtts_inference)
        self.pronunciation_rules = list(pronunciation_rules)
        self.logger = get_logger("live_preview")

    def run(self) -> None:
        try:
            render_started = time.perf_counter()
            session = {item.session_id: item for item in list_preview_sessions(self.paths)}[self.session_id]
            preview_root = self.paths.preview_sessions / self.session_id / "live_preview"
            wav_root = preview_root / "wav"
            mp3_root = preview_root / "mp3"
            wav_root.mkdir(parents=True, exist_ok=True)
            mp3_root.mkdir(parents=True, exist_ok=True)

            text = Path(session.preview_source_file).read_text(encoding="utf-8")
            preview_text = text
            chunks = split_text(text, self.max_chars)
            piper_backend = PiperBackend(self.paths.runtime, self.paths.voices, logger=self.logger)
            xtts_backend = XttsBackend(self.paths.runtime, logger=self.logger, device_mode=self.xtts_device_mode)
            mp3_files: list[Path] = []
            final_preview = preview_root / "preview.mp3"

            with perf_scope(
                "preview.render",
                category="preview",
                backend=self.backend,
                session_id=self.session_id,
                source_chars=len(text),
                max_chars=self.max_chars,
            ):
                if self.backend == "piper":
                    self.logger.info(
                        "Live preview start backend=%s source_chars=%s chunk_count=%s max_chars=%s",
                        self.backend,
                        len(text),
                        len(chunks),
                        self.max_chars,
                    )
                    for index, chunk in enumerate(chunks, start=1):
                        wav_path = wav_root / f"{index:03d}.wav"
                        mp3_path = mp3_root / f"{index:03d}.mp3"
                        piper_backend.synthesize_to_wav(
                            chunk,
                            self.voice_id,
                            wav_path,
                            sentence_silence=self.sentence_silence,
                            length_scale=self.length_scale,
                        )
                        wav_to_mp3(wav_path, mp3_path, logger=self.logger)
                        mp3_files.append(mp3_path)
                    concat_mp3_files(mp3_files, final_preview, logger=self.logger)
                else:
                    profile = load_voice_profile(self.paths.voice_profiles, self.voice_profile_id)
                    preview_text = _paragraph_preview_text(text)
                    spoken_preview = apply_pronunciation_rules(preview_text, self.pronunciation_rules)
                    spoken_text = _normalize_xtts_dialog_text(spoken_preview.spoken_text)
                    xtts_max_chars = safe_xtts_chunk_chars(self.max_chars, profile.target_language)
                    xtts_chunks = split_text(spoken_text, xtts_max_chars)
                    if not xtts_chunks:
                        raise RuntimeError("XTTS preview text is empty after normalization")
                    preview_profile = replace(profile, samples=profile.samples[:1] or profile.samples)
                    wav_paths = [wav_root / f"{index:03d}.wav" for index in range(1, len(xtts_chunks) + 1)]
                    final_preview = preview_root / "preview.mp3"
                    self.logger.info(
                        "Live preview start backend=%s source_chars=%s preview_chars=%s spoken_chars=%s chunk_count=%s max_chars=%s requested_max_chars=%s profile_samples=%s device_mode=%s quality_mode=%s pronunciation_rules=%s",
                        self.backend,
                        len(text),
                        len(preview_text),
                        len(spoken_text),
                        len(xtts_chunks),
                        xtts_max_chars,
                        self.max_chars,
                        len(preview_profile.samples),
                        self.xtts_device_mode,
                        self.xtts_quality_mode,
                        len(self.pronunciation_rules),
                    )
                    xtts_backend.synthesize_many_to_wavs(
                        xtts_chunks,
                        preview_profile,
                        wav_paths,
                        length_scale=self.length_scale,
                        enable_text_splitting=bool(self.xtts_inference.get("enable_text_splitting", False)),
                        inference_options=self.xtts_inference,
                    )
                    for wav_path in wav_paths:
                        trim_wav_silence_in_place(wav_path, logger=self.logger)
                    concat_audio_files_to_mp3(wav_paths, final_preview, logger=self.logger)
            perf_event(
                "preview.render.complete",
                category="preview",
                backend=self.backend,
                session_id=self.session_id,
                rendered_chars=len(preview_text),
                duration_ms=round((time.perf_counter() - render_started) * 1000, 3),
                output_file=final_preview,
            )
            preview_job_id = f"live_{uuid.uuid4().hex[:10]}"
            attach_preview_job(
                self.paths,
                self.session_id,
                self.backend,
                self.voice_id,
                self.voice_profile_id,
                "live_tuning",
                preview_job_id,
                str(final_preview),
                "completed",
            )
            self.preview_finished.emit(
                self.session_id,
                str(final_preview),
                round((time.perf_counter() - render_started) * 1000, 3),
            )
        except Exception:
            self.logger.exception("Live preview render failed")
            self.preview_failed.emit(traceback.format_exc())


class XttsWarmupWorker(QThread):
    warmup_finished = Signal(str, float)
    warmup_failed = Signal(str, str)

    def __init__(self, paths: AppPaths, voice_profile_id: str, xtts_device_mode: str) -> None:
        super().__init__()
        self.paths = paths
        self.voice_profile_id = voice_profile_id
        self.xtts_device_mode = xtts_device_mode
        self.logger = get_logger("xtts_warmup")

    def run(self) -> None:
        started = time.perf_counter()
        try:
            profile = load_voice_profile(self.paths.voice_profiles, self.voice_profile_id)
            backend = XttsBackend(self.paths.runtime, logger=self.logger, device_mode=self.xtts_device_mode)
            backend.warmup_profile(profile, speaker_sample_limit=1)
            self.warmup_finished.emit(self.voice_profile_id, round((time.perf_counter() - started) * 1000, 3))
        except Exception:
            self.logger.exception("XTTS warmup failed")
            self.warmup_failed.emit(self.voice_profile_id, traceback.format_exc())


class FindBestSettingDialog(QDialog):
    def __init__(
        self,
        paths: AppPaths,
        manager: object,
        parent: QWidget | None = None,
        *,
        focus_assistant: bool = False,
        focus_lexicon: bool = False,
        lexicon_seed_terms: list[str] | None = None,
        initial_source_path: Path | None = None,
        ui_language: str | None = None,
    ) -> None:
        super().__init__(parent)
        self.paths = paths
        self.logger = get_logger("find_best_setting")
        self.app_settings = load_app_settings(paths.app_settings_file)
        self.ui_language = resolve_ui_language(ui_language or self.app_settings.ui_language)
        self.focus_assistant = focus_assistant
        self.focus_lexicon = focus_lexicon
        self.lexicon_seed_terms = [
            " ".join(str(item or "").split()).strip()
            for item in (lexicon_seed_terms or [])
            if str(item or "").strip()
        ]
        self.initial_source_path = Path(initial_source_path) if initial_source_path else None
        self.current_source: Path | None = None
        self.current_session_id: str | None = None
        self._async_request_id = 0
        self._active_source_analysis_request_id = 0
        self._source_analysis_runner: AsyncTaskRunner | None = None
        self._active_create_session_request_id = 0
        self._create_session_runner: AsyncTaskRunner | None = None
        self._active_new_excerpt_request_id = 0
        self._new_excerpt_runner: AsyncTaskRunner | None = None
        self.installed_voices: list[str] = []
        self.source_structure = DocumentStructure(
            source_type="",
            chapter_count=0,
            chapter_titles=[],
            supports_chapter_files=False,
            summary="Noch keine Quelle gewählt.",
            analysis_status="idle",
        )
        self.output_mode_requested = "single_file"
        self._syncing_output_mode_radios = False
        self.preview_worker: LivePreviewWorker | None = None
        self.xtts_warmup_worker: XttsWarmupWorker | None = None
        self.last_xtts_warmup_key = ""
        self.current_xtts_warmup_key = ""
        self.voice_test_run: VoiceTestRun | None = None
        self.active_assistant_candidate_id = ""
        self.current_saved_setting_id = ""
        self.pending_benchmark_candidate_ids: list[str] = []
        self.play_preview_after_render = True
        self._xtts_inference_override: dict[str, object] = {}
        self._xtts_inference_override_key = ""
        self._pending_close = False
        self._shutdown_wait_attempts = 0
        self._voice_lab_dialog: VoiceLabDialog | None = None
        self.xtts_backend = XttsBackend(paths.runtime, logger=self.logger, device_mode=self.app_settings.xtts_device_mode)

        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_output)
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.handle_about_to_quit)

        self.setWindowTitle(apply_text("Profilstudio & Hörproben", self.ui_language))
        self.resize(1160, 740)
        self.setMinimumSize(1060, 680)
        self._build_ui()
        apply_modern_window_style(self)
        translate_widget_tree(self, self.ui_language)
        self.refresh_voice_list()
        self.refresh_voice_profiles()
        self.apply_cuda_first_preference()
        self.refresh_saved_settings()
        self.restore_last_session()
        if self.initial_source_path and self.initial_source_path.exists():
            self.current_source = self.initial_source_path
            self.source_label.setText(str(self.current_source))
            self.refresh_source_analysis()
            self.refresh_pronunciation_suggestions()
        if self.focus_assistant:
            assistant_mode_index = self.test_mode_combo.findData("assistant")
            if assistant_mode_index >= 0:
                self.test_mode_combo.setCurrentIndex(assistant_mode_index)
            self.studio_tabs.setCurrentWidget(self.test_page)
            self.test_assistant_button.setFocus(Qt.FocusReason.OtherFocusReason)
        elif self.focus_lexicon:
            self.studio_tabs.setCurrentWidget(self.backend_page)
            self.backend_tabs.setCurrentIndex(1)
            self.xtts_pronunciation_table.setFocus(Qt.FocusReason.OtherFocusReason)

    def _text(self, text: str) -> str:
        return apply_text(text, self.ui_language)

    def _next_async_request_id(self) -> int:
        self._async_request_id += 1
        return self._async_request_id

    def _connect_async_runner(
        self,
        runner: AsyncTaskRunner,
        on_success,
        on_failure,
    ) -> None:
        runner.success.connect(on_success)
        runner.failure.connect(on_failure)
        runner.finished.connect(lambda: self._cleanup_async_runner(runner))
        runner.start()

    def _cleanup_async_runner(self, runner: object) -> None:
        if self._source_analysis_runner is runner:
            self._source_analysis_runner = None
        if self._create_session_runner is runner:
            self._create_session_runner = None
        if self._new_excerpt_runner is runner:
            self._new_excerpt_runner = None
        if hasattr(runner, "deleteLater"):
            runner.deleteLater()

    def _focus_existing_dialog(self, dialog: QDialog | None) -> bool:
        if dialog is None:
            return False
        if dialog.isVisible():
            dialog.activateWindow()
            dialog.raise_()
            return True
        return False

    def _build_ui(self) -> None:
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(8, 8, 8, 8)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer_layout.addWidget(scroll)

        page = QWidget()
        scroll.setWidget(page)
        layout = QVBoxLayout(page)

        intro = QLabel(
            "Das Profilstudio ist bewusst vom eigentlichen Auftragsdialog getrennt. "
            "Hier testest du Stimmen, XTTS-Profile, Presets und Varianten. "
            "Wenn etwas gut klingt, speicherst du es als Produktionsprofil für echte Hörbuchaufträge."
        )
        intro.setWordWrap(True)
        intro.setProperty("role", "hint")
        layout.addWidget(intro)

        workflow_group = QGroupBox("Studio-Ablauf")
        workflow_layout = QVBoxLayout(workflow_group)
        self.workflow_label = QLabel("")
        self.workflow_label.setWordWrap(True)
        self.workflow_label.setProperty("role", "muted")
        workflow_layout.addWidget(self.workflow_label)
        workflow_buttons = QHBoxLayout()
        self.workflow_back_button = QPushButton("Zurück")
        self.workflow_back_button.clicked.connect(self.go_to_previous_studio_step)
        workflow_buttons.addWidget(self.workflow_back_button)
        self.workflow_next_button = QPushButton("Weiter")
        self.workflow_next_button.clicked.connect(self.go_to_next_studio_step)
        workflow_buttons.addWidget(self.workflow_next_button)
        workflow_layout.addLayout(workflow_buttons)
        layout.addWidget(workflow_group)

        self.studio_tabs = QTabWidget()
        self.studio_tabs.currentChanged.connect(self.on_studio_tab_changed)
        layout.addWidget(self.studio_tabs)

        self.source_page = QWidget()
        source_page_layout = QVBoxLayout(self.source_page)
        session_group = QGroupBox("Quelle und aktueller Ausschnitt")
        session_layout = QVBoxLayout(session_group)
        source_row = QHBoxLayout()
        self.source_label = QLabel("Keine Quelle gewaehlt")
        self.source_label.setWordWrap(True)
        source_row.addWidget(self.source_label, 1)
        source_button = QPushButton("Buch waehlen")
        source_button.clicked.connect(self.select_source)
        source_row.addWidget(source_button)
        new_excerpt_button = QPushButton("Neue Stelle")
        new_excerpt_button.clicked.connect(self.new_excerpt)
        source_row.addWidget(new_excerpt_button)
        session_layout.addLayout(source_row)
        self.source_analysis_label = QLabel("Noch keine Quelle gewählt.")
        self.source_analysis_label.setWordWrap(True)
        self.source_analysis_label.setProperty("role", "muted")
        session_layout.addWidget(self.source_analysis_label)
        self.excerpt_view = QPlainTextEdit()
        self.excerpt_view.setReadOnly(True)
        self.excerpt_view.setPlaceholderText("Hier erscheint automatisch eine zufaellige Stelle aus dem Buch.")
        self.excerpt_view.setMinimumHeight(140)
        session_layout.addWidget(self.excerpt_view)
        source_page_layout.addWidget(session_group)
        source_page_hint = QLabel(
            "Direkt nach der Dateiauswahl wird geprüft, ob eine belastbare Kapitelstruktur vorhanden ist. "
            "Erst dann kann später 'eine Datei pro Kapitel' aktiviert werden."
        )
        source_page_hint.setWordWrap(True)
        source_page_hint.setProperty("role", "muted")
        source_page_layout.addWidget(source_page_hint)
        source_page_layout.addStretch(1)
        self.studio_tabs.addTab(self.source_page, "Quelle")

        self.backend_page = QWidget()
        backend_page_layout = QVBoxLayout(self.backend_page)
        backend_intro = QLabel(
            "Backend und Stimmenverwaltung sind getrennt. Wähle Piper oder XTTS und bearbeite nur die dafür passenden Felder."
        )
        backend_intro.setWordWrap(True)
        backend_intro.setProperty("role", "hint")
        backend_page_layout.addWidget(backend_intro)

        self.backend_combo = QComboBox()
        self.backend_combo.addItems(["piper", "xtts"])
        self.backend_combo.currentIndexChanged.connect(self.on_backend_changed)
        self.backend_tabs = QTabWidget()
        self.backend_tabs.currentChanged.connect(self.on_backend_tab_changed)
        backend_page_layout.addWidget(self.backend_tabs)

        piper_page = QWidget()
        piper_page_layout = QVBoxLayout(piper_page)
        piper_group = QGroupBox("Piper testen")
        piper_form = QFormLayout(piper_group)
        self.voice_combo = QComboBox()
        piper_form.addRow("Piper-Stimme", self.voice_combo)
        self.voice_language_combo = QComboBox()
        self.voice_language_combo.currentIndexChanged.connect(self.rebuild_voice_combo)
        piper_form.addRow("Piper-Sprache", self.voice_language_combo)
        voice_filter_row = QHBoxLayout()
        self.voice_female_only_checkbox = QCheckBox("nur Frauenstimmen")
        self.voice_female_only_checkbox.toggled.connect(self.rebuild_voice_combo)
        voice_filter_row.addWidget(self.voice_female_only_checkbox)
        self.voice_high_only_checkbox = QCheckBox("nur high")
        self.voice_high_only_checkbox.toggled.connect(self.rebuild_voice_combo)
        voice_filter_row.addWidget(self.voice_high_only_checkbox)
        piper_form.addRow("Piper-Filter", self._wrap(voice_filter_row))
        piper_tools_row = QHBoxLayout()
        reload_piper_button = QPushButton("Piper-Stimmen neu laden")
        reload_piper_button.clicked.connect(self.refresh_voice_list)
        piper_tools_row.addWidget(reload_piper_button)
        import_piper_button = QPushButton("Custom-Piper importieren")
        import_piper_button.clicked.connect(self.parent().import_custom_piper_voice if hasattr(self.parent(), "import_custom_piper_voice") else self.refresh_voice_list)
        piper_tools_row.addWidget(import_piper_button)
        piper_form.addRow("", self._wrap(piper_tools_row))
        piper_page_layout.addWidget(piper_group)
        piper_page_layout.addStretch(1)
        self.backend_tabs.addTab(piper_page, "Piper")

        xtts_page = QWidget()
        xtts_page_layout = QVBoxLayout(xtts_page)
        xtts_group = QGroupBox("XTTS testen & Aussprache-Lexikon")
        xtts_form = QFormLayout(xtts_group)
        self.voice_profile_combo = QComboBox()
        self.voice_profile_combo.currentIndexChanged.connect(self.refresh_selected_voice_profile)
        xtts_form.addRow("XTTS-Profil", self.voice_profile_combo)

        self.xtts_device_combo = QComboBox()
        self.xtts_device_combo.addItem("CUDA bevorzugen", "cuda")
        self.xtts_device_combo.addItem("Auto", "auto")
        self.xtts_device_combo.addItem("CPU erzwingen", "cpu")
        device_index = self.xtts_device_combo.findData(self.app_settings.xtts_device_mode)
        self.xtts_device_combo.setCurrentIndex(device_index if device_index >= 0 else 0)
        self.xtts_device_combo.currentIndexChanged.connect(self.on_xtts_device_mode_changed)
        xtts_form.addRow("XTTS-Geraet", self.xtts_device_combo)

        self.xtts_quality_mode_combo = QComboBox()
        self.xtts_quality_mode_combo.addItem("Schnell", "fast")
        self.xtts_quality_mode_combo.addItem("Bessere Qualität", "quality")
        self.xtts_quality_mode_combo.addItem("Max Qualität", "max_quality")
        self.xtts_quality_mode_combo.currentIndexChanged.connect(self.update_helper_text)
        xtts_form.addRow("XTTS-Qualitätsmodus", self.xtts_quality_mode_combo)

        self.voice_profile_details = QLabel("")
        self.voice_profile_details.setWordWrap(True)
        self.voice_profile_details.setProperty("role", "muted")
        xtts_form.addRow("Profil-Info", self.voice_profile_details)
        xtts_profile_row = QHBoxLayout()
        preview_reference_button = QPushButton("Referenzsample hoeren")
        preview_reference_button.clicked.connect(self.preview_xtts_reference)
        xtts_profile_row.addWidget(preview_reference_button)
        open_profile_button = QPushButton("Profilordner oeffnen")
        open_profile_button.clicked.connect(self.open_xtts_profile_folder)
        xtts_profile_row.addWidget(open_profile_button)
        xtts_profile_button = QPushButton("XTTS-Profilstudio")
        xtts_profile_button.clicked.connect(self.open_voice_lab)
        xtts_profile_row.addWidget(xtts_profile_button)
        xtts_form.addRow("", self._wrap(xtts_profile_row))
        xtts_import_row = QHBoxLayout()
        xtts_manage_button = QPushButton("XTTS-Profile verwalten")
        xtts_manage_button.clicked.connect(self.open_voice_lab)
        xtts_import_row.addWidget(xtts_manage_button)
        xtts_reload_button = QPushButton("XTTS-Bestand neu laden")
        xtts_reload_button.clicked.connect(self.refresh_voice_profiles)
        xtts_import_row.addWidget(xtts_reload_button)
        xtts_form.addRow("Werkzeuge", self._wrap(xtts_import_row))
        self.xtts_pronunciation_hint = QLabel(
            "Hier pflegst du das Aussprache-Lexikon für Eigennamen und schwierige Begriffe. "
            "XTTS nutzt nur eine gesprochene Arbeitskopie, Originaltext und Metadaten bleiben unverändert."
        )
        self.xtts_pronunciation_hint.setWordWrap(True)
        self.xtts_pronunciation_hint.setProperty("role", "muted")
        xtts_form.addRow("Aussprache-Lexikon", self.xtts_pronunciation_hint)
        self.xtts_pronunciation_table = QTableWidget(0, 3)
        self.xtts_pronunciation_table.setHorizontalHeaderLabels(["Aktiv", "Original", "Gesprochen als"])
        self.xtts_pronunciation_table.verticalHeader().setVisible(False)
        self.xtts_pronunciation_table.setMinimumHeight(170)
        xtts_form.addRow("", self.xtts_pronunciation_table)
        xtts_rule_buttons = QHBoxLayout()
        add_rule_button = QPushButton("Regel hinzufügen")
        add_rule_button.clicked.connect(self.add_pronunciation_rule)
        xtts_rule_buttons.addWidget(add_rule_button)
        remove_rule_button = QPushButton("Regel entfernen")
        remove_rule_button.clicked.connect(self.remove_selected_pronunciation_rule)
        xtts_rule_buttons.addWidget(remove_rule_button)
        add_suggestion_button = QPushButton("Vorschlag übernehmen")
        add_suggestion_button.clicked.connect(self.add_selected_pronunciation_suggestion)
        xtts_rule_buttons.addWidget(add_suggestion_button)
        refresh_suggestions_button = QPushButton("Vorschläge neu prüfen")
        refresh_suggestions_button.clicked.connect(self.refresh_pronunciation_suggestions)
        xtts_rule_buttons.addWidget(refresh_suggestions_button)
        xtts_form.addRow("", self._wrap(xtts_rule_buttons))
        self.xtts_pronunciation_suggestions = QListWidget()
        self.xtts_pronunciation_suggestions.setMinimumHeight(120)
        xtts_form.addRow("Lexikon-Vorschläge", self.xtts_pronunciation_suggestions)
        xtts_page_layout.addWidget(xtts_group)
        xtts_page_layout.addStretch(1)
        self.backend_tabs.addTab(xtts_page, "XTTS")
        self.studio_tabs.addTab(self.backend_page, "Backend & Stimme")

        self.tuning_page = QWidget()
        tuning_page_layout = QVBoxLayout(self.tuning_page)
        tuning_intro = QLabel(
            "Hier legst du für die aktuelle Testvariante Preset, Chunkgröße, Tempo und Ausgabeziel fest. "
            "Die Kapiteloption wird automatisch gesperrt, wenn die Quelle keine Kapitelstruktur hergibt."
        )
        tuning_intro.setWordWrap(True)
        tuning_intro.setProperty("role", "hint")
        tuning_page_layout.addWidget(tuning_intro)

        tuning_group = QGroupBox("Tuning und Ausgabe")
        tuning_layout = QVBoxLayout(tuning_group)
        tuning_form = QFormLayout()
        self.assistant_combo = QComboBox()
        self.assistant_combo.addItem("Roman / Story", "novel")
        self.assistant_combo.addItem("Sachbuch / Klar", "nonfiction")
        self.assistant_combo.addItem("Kinderbuch / Warm", "children")
        self.assistant_combo.addItem("Schnell / CPU", "cpu")
        self.preset_combo = QComboBox()
        for preset in QUALITY_PRESETS:
            self.preset_combo.addItem(preset.label, preset.preset_id)
        self.preset_combo.currentIndexChanged.connect(self.on_preset_changed)
        tuning_form.addRow("Qualitaets-Preset", self.preset_combo)

        self.output_mode_combo = QComboBox()
        self.output_mode_combo.addItem("Eine grosse Enddatei", "single_file")
        self.output_mode_combo.addItem("Eine Enddatei pro Kapitel", "chapter_files")
        self.output_mode_combo.addItem("Enddateien alle X Minuten", "timed_parts")
        self.output_mode_combo.addItem("Nur kleine Teil-MP3s behalten", "segments")
        self.output_mode_combo.currentIndexChanged.connect(self.update_helper_text)
        self.output_mode_combo.currentIndexChanged.connect(self.sync_output_mode_radios_from_combo)
        self.output_mode_combo.hide()
        self.output_mode_group = QButtonGroup(self)
        output_modes_widget = QWidget()
        output_modes_layout = QVBoxLayout(output_modes_widget)
        output_modes_layout.setContentsMargins(0, 0, 0, 0)
        self.output_mode_single_radio = QRadioButton("Eine grosse Enddatei")
        self.output_mode_single_radio.toggled.connect(
            lambda checked: self.on_output_mode_radio_toggled("single_file", checked)
        )
        self.output_mode_group.addButton(self.output_mode_single_radio)
        output_modes_layout.addWidget(self.output_mode_single_radio)
        self.output_mode_chapter_radio = QRadioButton("Eine Datei pro Kapitel")
        self.output_mode_chapter_radio.toggled.connect(
            lambda checked: self.on_output_mode_radio_toggled("chapter_files", checked)
        )
        self.output_mode_group.addButton(self.output_mode_chapter_radio)
        output_modes_layout.addWidget(self.output_mode_chapter_radio)
        self.output_mode_timed_radio = QRadioButton("Mehrere Dateien nach Zeit")
        self.output_mode_timed_radio.toggled.connect(
            lambda checked: self.on_output_mode_radio_toggled("timed_parts", checked)
        )
        self.output_mode_group.addButton(self.output_mode_timed_radio)
        output_modes_layout.addWidget(self.output_mode_timed_radio)
        self.output_mode_segments_radio = QRadioButton("Nur Teil-MP3s behalten")
        self.output_mode_segments_radio.toggled.connect(
            lambda checked: self.on_output_mode_radio_toggled("segments", checked)
        )
        self.output_mode_group.addButton(self.output_mode_segments_radio)
        output_modes_layout.addWidget(self.output_mode_segments_radio)
        tuning_form.addRow("Finale Ausgabe", output_modes_widget)

        self.target_part_minutes_spin = QSpinBox()
        self.target_part_minutes_spin.setRange(1, 180)
        self.target_part_minutes_spin.setValue(15)
        self.target_part_minutes_spin.setSuffix(" min")
        self.target_part_minutes_spin.valueChanged.connect(self.update_helper_text)
        tuning_form.addRow("Laenge pro Enddatei", self.target_part_minutes_spin)

        self.max_chars_spin = QSpinBox()
        self.max_chars_spin.setRange(100, 450)
        self.max_chars_spin.setSingleStep(10)
        self.max_chars_spin.setValue(220)
        self.max_chars_spin.valueChanged.connect(self.update_helper_text)
        tuning_form.addRow("Max Zeichen pro Chunk", self.max_chars_spin)

        self.sentence_slider = QSlider(Qt.Horizontal)
        self.sentence_slider.setRange(5, 60)
        self.sentence_slider.setValue(20)
        self.sentence_slider.valueChanged.connect(self.update_helper_text)
        tuning_form.addRow("Satzpause", self.sentence_slider)
        self.sentence_label = QLabel("0.20s")
        tuning_form.addRow("", self.sentence_label)

        self.length_slider = QSlider(Qt.Horizontal)
        self.length_slider.setRange(85, 120)
        self.length_slider.setValue(100)
        self.length_slider.valueChanged.connect(self.update_helper_text)
        tuning_form.addRow("Tempo / Laenge", self.length_slider)
        self.length_label = QLabel("1.00")
        tuning_form.addRow("", self.length_label)
        tuning_layout.addLayout(tuning_form)
        tuning_page_layout.addWidget(tuning_group)

        self.helper_label = QLabel("")
        self.helper_label.setWordWrap(True)
        self.helper_label.setProperty("role", "muted")
        tuning_page_layout.addWidget(self.helper_label)
        tuning_page_layout.addStretch(1)
        self.studio_tabs.addTab(self.tuning_page, "Tuning")

        self.test_page = QWidget()
        test_page_layout = QVBoxLayout(self.test_page)
        test_intro = QLabel(
            "Hier arbeitest du entweder geführt mit dem Profil-Assistenten oder manuell mit einer Benchmark-Reihe. "
            "Beide Modi bleiben bewusst getrennt, damit die Testlogik nicht mit zu vielen gleichzeitigen Optionen überladen wird."
        )
        test_intro.setWordWrap(True)
        test_intro.setProperty("role", "hint")
        test_page_layout.addWidget(test_intro)
        test_mode_group = QGroupBox("Arbeitsmodus")
        test_mode_layout = QFormLayout(test_mode_group)
        self.test_mode_combo = QComboBox()
        self.test_mode_combo.addItem("Geführter Assistent", "assistant")
        self.test_mode_combo.addItem("Manuelle Benchmark-Reihe", "benchmark")
        self.test_mode_combo.currentIndexChanged.connect(self.on_test_mode_changed)
        test_mode_layout.addRow("Modus", self.test_mode_combo)
        self.test_mode_hint_label = QLabel("")
        self.test_mode_hint_label.setWordWrap(True)
        self.test_mode_hint_label.setProperty("role", "muted")
        test_mode_layout.addRow("Hinweis", self.test_mode_hint_label)
        test_page_layout.addWidget(test_mode_group)

        self.test_mode_stack = QStackedWidget()
        test_page_layout.addWidget(self.test_mode_stack)

        assistant_page = QWidget()
        assistant_page_layout = QVBoxLayout(assistant_page)
        assistant_group = QGroupBox("Geführter Profil-Assistent")
        assistant_layout = QVBoxLayout(assistant_group)
        assistant_form = QFormLayout()
        assistant_form.addRow("Schnellhilfe", self.assistant_combo)
        self.assistant_language_combo = QComboBox()
        assistant_form.addRow("Testsprache", self.assistant_language_combo)
        self.assistant_gender_combo = QComboBox()
        self.assistant_gender_combo.addItem("egal", "any")
        self.assistant_gender_combo.addItem("weiblich", "female")
        self.assistant_gender_combo.addItem("maennlich", "male")
        assistant_form.addRow("Stimmwunsch", self.assistant_gender_combo)
        assistant_button_row = QHBoxLayout()
        assistant_button = QPushButton("Optimale Startwerte")
        assistant_button.clicked.connect(self.apply_assistant_profile)
        assistant_button_row.addWidget(assistant_button)
        self.test_assistant_button = QPushButton("Profil-Assistent starten")
        self.test_assistant_button.clicked.connect(self.start_voice_test_assistant)
        assistant_button_row.addWidget(self.test_assistant_button)
        assistant_form.addRow("", self._wrap(assistant_button_row))
        assistant_layout.addLayout(assistant_form)
        assistant_page_layout.addWidget(assistant_group)
        assistant_page_layout.addStretch(1)
        self.test_mode_stack.addWidget(assistant_page)

        benchmark_page = QWidget()
        benchmark_page_layout = QVBoxLayout(benchmark_page)
        benchmark_group = QGroupBox("Manuelle Benchmark-Reihe")
        benchmark_layout = QVBoxLayout(benchmark_group)
        benchmark_form = QFormLayout()
        self.benchmark_language_combo = QComboBox()
        benchmark_form.addRow("Testsprache", self.benchmark_language_combo)
        self.benchmark_gender_combo = QComboBox()
        self.benchmark_gender_combo.addItem("egal", "any")
        self.benchmark_gender_combo.addItem("weiblich", "female")
        self.benchmark_gender_combo.addItem("maennlich", "male")
        benchmark_form.addRow("Stimmwunsch", self.benchmark_gender_combo)
        benchmark_layout.addLayout(benchmark_form)
        benchmark_setup_row = QHBoxLayout()
        self.start_benchmark_button = QPushButton("Leere Benchmark-Reihe anlegen")
        self.start_benchmark_button.clicked.connect(self.start_benchmark_test_run)
        benchmark_setup_row.addWidget(self.start_benchmark_button)
        self.add_current_candidate_button = QPushButton("Aktuelle Einstellungen hinzufügen")
        self.add_current_candidate_button.clicked.connect(self.add_current_settings_to_test_run)
        benchmark_setup_row.addWidget(self.add_current_candidate_button)
        benchmark_layout.addLayout(benchmark_setup_row)
        benchmark_page_layout.addWidget(benchmark_group)
        benchmark_page_layout.addStretch(1)
        self.test_mode_stack.addWidget(benchmark_page)

        candidate_group = QGroupBox("Kandidaten und Bewertung")
        candidate_layout = QVBoxLayout(candidate_group)
        candidate_form = QFormLayout()
        self.assistant_candidate_combo = QComboBox()
        self.assistant_candidate_combo.currentIndexChanged.connect(self.on_assistant_candidate_changed)
        candidate_form.addRow("Kandidat", self.assistant_candidate_combo)
        candidate_action_row_top = QHBoxLayout()
        self.assistant_load_button = QPushButton("Kandidat laden")
        self.assistant_load_button.clicked.connect(self.load_selected_assistant_candidate)
        candidate_action_row_top.addWidget(self.assistant_load_button)
        self.assistant_render_button = QPushButton("Kandidat rendern")
        self.assistant_render_button.clicked.connect(self.render_selected_assistant_candidate)
        candidate_action_row_top.addWidget(self.assistant_render_button)
        candidate_form.addRow("", self._wrap(candidate_action_row_top))
        candidate_action_row_mid = QHBoxLayout()
        self.assistant_benchmark_all_button = QPushButton("Alle Kandidaten benchmarken")
        self.assistant_benchmark_all_button.clicked.connect(self.benchmark_all_candidates)
        candidate_action_row_mid.addWidget(self.assistant_benchmark_all_button)
        self.assistant_refine_button = QPushButton("Beste Variante verfeinern")
        self.assistant_refine_button.clicked.connect(self.refine_voice_test_assistant)
        candidate_action_row_mid.addWidget(self.assistant_refine_button)
        candidate_form.addRow("", self._wrap(candidate_action_row_mid))
        candidate_action_row_bottom = QHBoxLayout()
        self.assistant_chunk_tuning_button = QPushButton("2. Schritt: Chunk-Tuning")
        self.assistant_chunk_tuning_button.clicked.connect(self.start_chunk_tuning_round)
        candidate_action_row_bottom.addWidget(self.assistant_chunk_tuning_button)
        self.assistant_save_rating_button = QPushButton("Bewertung speichern")
        self.assistant_save_rating_button.clicked.connect(self.save_assistant_rating)
        candidate_action_row_bottom.addWidget(self.assistant_save_rating_button)
        candidate_form.addRow("", self._wrap(candidate_action_row_bottom))
        self.assistant_rating_spin = QSpinBox()
        self.assistant_rating_spin.setRange(0, 5)
        self.assistant_rating_spin.setValue(0)
        candidate_form.addRow("Qualitätswert 0-5", self.assistant_rating_spin)
        self.assistant_note = QLineEdit()
        self.assistant_note.setPlaceholderText("z. B. natürlich, zu dumpf, gute Geschwindigkeit")
        candidate_form.addRow("Bewertungsnotiz", self.assistant_note)
        candidate_layout.addLayout(candidate_form)
        self.assistant_status_label = QLabel("Noch keine Testreihe gestartet.")
        self.assistant_status_label.setWordWrap(True)
        self.assistant_status_label.setProperty("role", "muted")
        candidate_layout.addWidget(self.assistant_status_label)
        test_page_layout.addWidget(candidate_group)
        test_page_layout.addStretch(1)
        self.studio_tabs.addTab(self.test_page, "Testreihe")

        self.production_page = QWidget()
        production_page_layout = QVBoxLayout(self.production_page)
        production_intro = QLabel(
            "Erst wenn eine Variante gut klingt und in der Testreihe überzeugt, wird sie hier als Produktionsprofil gespeichert oder freigegeben."
        )
        production_intro.setWordWrap(True)
        production_intro.setProperty("role", "hint")
        production_page_layout.addWidget(production_intro)

        production_group = QGroupBox("Produktionsprofil")
        production_layout = QVBoxLayout(production_group)
        production_form = QFormLayout()
        self.setting_name = QLineEdit()
        self.setting_name.setPlaceholderText("z. B. Roman warm natürlich")
        production_form.addRow("Name fuer Produktionsprofil", self.setting_name)
        self.saved_settings_combo = QComboBox()
        self.saved_settings_combo.currentIndexChanged.connect(self.on_saved_setting_changed)
        production_form.addRow("Gespeicherte Produktionsprofile", self.saved_settings_combo)
        production_layout.addLayout(production_form)

        self.saved_settings_status_label = QLabel("Noch kein Produktionsprofil geladen.")
        self.saved_settings_status_label.setWordWrap(True)
        self.saved_settings_status_label.setProperty("role", "muted")
        production_layout.addWidget(self.saved_settings_status_label)

        save_button_row = QHBoxLayout()
        save_setting_button = QPushButton("Produktionsprofil aktualisieren")
        save_setting_button.clicked.connect(self.save_setting)
        save_button_row.addWidget(save_setting_button)
        save_new_setting_button = QPushButton("Als neues Profil speichern")
        save_new_setting_button.clicked.connect(self.save_setting_as_new)
        save_button_row.addWidget(save_new_setting_button)
        production_layout.addLayout(save_button_row)
        profile_status_row = QHBoxLayout()
        approve_setting_button = QPushButton("Als Produktionsprofil freigeben")
        approve_setting_button.clicked.connect(lambda: self.set_saved_setting_status(PROFILE_STATUS_APPROVED))
        profile_status_row.addWidget(approve_setting_button)
        mark_tested_button = QPushButton("Als getestet markieren")
        mark_tested_button.clicked.connect(lambda: self.set_saved_setting_status(PROFILE_STATUS_TESTED))
        profile_status_row.addWidget(mark_tested_button)
        archive_setting_button = QPushButton("Archivieren")
        archive_setting_button.clicked.connect(lambda: self.set_saved_setting_status(PROFILE_STATUS_ARCHIVED))
        profile_status_row.addWidget(archive_setting_button)
        production_layout.addLayout(profile_status_row)
        load_button_row = QHBoxLayout()
        load_last_button = QPushButton("Gewaehltes Profil laden")
        load_last_button.clicked.connect(self.load_selected_saved_setting)
        load_button_row.addWidget(load_last_button)
        production_layout.addLayout(load_button_row)
        production_page_layout.addWidget(production_group)
        production_page_layout.addStretch(1)
        self.studio_tabs.addTab(self.production_page, "Produktionsprofil")

        self.preview_page = QWidget()
        preview_page_layout = QVBoxLayout(self.preview_page)
        preview_group = QGroupBox("Preview und Ergebnis")
        preview_layout = QVBoxLayout(preview_group)
        preview_button_row_top = QHBoxLayout()
        self.play_now_button = QPushButton("Preview jetzt erzeugen")
        self.play_now_button.clicked.connect(self.render_and_play_preview)
        preview_button_row_top.addWidget(self.play_now_button)
        play_last_button = QPushButton("Letzte Preview abspielen")
        play_last_button.clicked.connect(self.play_last_preview)
        preview_button_row_top.addWidget(play_last_button)
        stop_button = QPushButton("Stop")
        stop_button.clicked.connect(self.stop_playback)
        preview_button_row_top.addWidget(stop_button)
        preview_layout.addLayout(preview_button_row_top)

        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setPlaceholderText("Hier stehen kurze Tuning-Infos zur aktuellen Stelle.")
        self.details.setMinimumHeight(150)
        preview_layout.addWidget(self.details)
        preview_page_layout.addWidget(preview_group)
        preview_page_layout.addStretch(1)
        self.studio_tabs.addTab(self.preview_page, "Preview")

        self.status_label = QLabel("Noch keine Preview gerendert.")
        self.status_label.setWordWrap(True)
        self.status_label.setProperty("role", "muted")
        layout.addWidget(self.status_label)

        layout.addStretch(1)
        self.apply_assistant_profile()
        self.on_backend_changed()
        self.on_test_mode_changed()
        self.update_workflow_navigation()

    def refresh_voice_list(self) -> None:
        self.installed_voices = PiperBackend(self.paths.runtime, self.paths.voices).installed_voices()
        self.voice_language_combo.blockSignals(True)
        self.voice_language_combo.clear()
        for code, label in language_choices(self.installed_voices, ui_language=self.ui_language):
            self.voice_language_combo.addItem(label, code)
        self.voice_language_combo.blockSignals(False)
        preferred_language = preferred_content_language_code(self.ui_language)
        preferred_index = self.voice_language_combo.findData(preferred_language)
        if preferred_index >= 0:
            self.voice_language_combo.setCurrentIndex(preferred_index)
        self.rebuild_voice_combo()
        self.refresh_assistant_language_choices()

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
        self.refresh_assistant_language_choices()

    def refresh_saved_settings(self) -> None:
        selected_setting_id = self.current_saved_setting_id or self.saved_settings_combo.currentData() or ""
        settings = list_voice_settings(self.paths.voice_settings)
        self.saved_settings_combo.blockSignals(True)
        self.saved_settings_combo.clear()
        if not settings:
            self.saved_settings_combo.addItem("Noch kein Produktionsprofil gespeichert", "")
            self.saved_settings_combo.blockSignals(False)
            self.current_saved_setting_id = ""
            self.saved_settings_status_label.setText(
                "Speichere hier ein erfolgreich getestetes Setup. Erst nach ausdruecklicher Freigabe erscheint es im Auftragsdialog."
            )
            return
        for setting in settings:
            self.saved_settings_combo.addItem(
                f"{profile_status_label(setting.status, ui_language=self.ui_language)} | {setting.display_name} | {setting.backend} | {setting.preset_hint}",
                setting.setting_id,
            )
        selected_index = self.saved_settings_combo.findData(selected_setting_id)
        self.saved_settings_combo.setCurrentIndex(selected_index if selected_index >= 0 else 0)
        self.saved_settings_combo.blockSignals(False)
        self.current_saved_setting_id = self.saved_settings_combo.currentData() or ""
        self.on_saved_setting_changed()

    def current_pronunciation_rules(self) -> list[dict[str, object]]:
        rules: list[dict[str, object]] = []
        for row in range(self.xtts_pronunciation_table.rowCount()):
            enabled_item = self.xtts_pronunciation_table.item(row, 0)
            match_item = self.xtts_pronunciation_table.item(row, 1)
            spoken_item = self.xtts_pronunciation_table.item(row, 2)
            rules.append(
                {
                    "enabled": enabled_item.checkState() == Qt.CheckState.Checked if enabled_item is not None else True,
                    "match": match_item.text().strip() if match_item is not None else "",
                    "spoken_as": spoken_item.text().strip() if spoken_item is not None else "",
                    "scope": "whole_phrase",
                }
            )
        return normalize_pronunciation_rules(rules)

    def set_pronunciation_rules(self, rules: list[dict[str, object]] | None) -> None:
        normalized = normalize_pronunciation_rules(rules)
        self.xtts_pronunciation_table.setRowCount(0)
        for rule in normalized:
            row = self.xtts_pronunciation_table.rowCount()
            self.xtts_pronunciation_table.insertRow(row)
            enabled_item = QTableWidgetItem("")
            enabled_item.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsUserCheckable
            )
            enabled_item.setCheckState(Qt.CheckState.Checked if rule.get("enabled", True) else Qt.CheckState.Unchecked)
            self.xtts_pronunciation_table.setItem(row, 0, enabled_item)
            self.xtts_pronunciation_table.setItem(row, 1, QTableWidgetItem(str(rule.get("match", ""))))
            self.xtts_pronunciation_table.setItem(row, 2, QTableWidgetItem(str(rule.get("spoken_as", ""))))
        self.refresh_pronunciation_suggestions()

    def add_pronunciation_rule(self, match: str = "", spoken_as: str = "") -> None:
        row = self.xtts_pronunciation_table.rowCount()
        self.xtts_pronunciation_table.insertRow(row)
        enabled_item = QTableWidgetItem("")
        enabled_item.setFlags(
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsUserCheckable
        )
        enabled_item.setCheckState(Qt.CheckState.Checked)
        self.xtts_pronunciation_table.setItem(row, 0, enabled_item)
        self.xtts_pronunciation_table.setItem(row, 1, QTableWidgetItem(match))
        self.xtts_pronunciation_table.setItem(row, 2, QTableWidgetItem(spoken_as or match))
        self.xtts_pronunciation_table.setCurrentCell(row, 2)

    def remove_selected_pronunciation_rule(self) -> None:
        row = self.xtts_pronunciation_table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Keine Regel", "Bitte zuerst eine Aussprache-Regel auswählen.")
            return
        self.xtts_pronunciation_table.removeRow(row)
        self.refresh_pronunciation_suggestions()

    def refresh_pronunciation_suggestions(self) -> None:
        existing_rules = self.current_pronunciation_rules()
        self._ensure_detected_author_rules(existing_rules)
        existing_rules = self.current_pronunciation_rules()
        text = self._pronunciation_suggestion_text()
        suggestions = suggest_explicit_pronunciation_candidates(
            self._pronunciation_seed_terms(),
            existing_rules=existing_rules,
            limit=8,
            reason="metadata_name",
        )
        suggestions.extend(
            suggest_pronunciation_candidates(
                text,
                existing_rules=existing_rules,
                limit=20,
            )
        )
        self.xtts_pronunciation_suggestions.clear()
        seen_matches: set[str] = set()
        for suggestion in suggestions:
            match = " ".join(str(suggestion.get("match", "") or "").split()).strip()
            if not match:
                continue
            folded = match.casefold()
            if folded in seen_matches:
                continue
            seen_matches.add(folded)
            label = f"{suggestion['match']} -> {suggestion['spoken_as']}"
            if suggestion["spoken_as"] == suggestion["match"]:
                label = suggestion["match"]
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, suggestion)
            self.xtts_pronunciation_suggestions.addItem(item)

    def _ensure_detected_author_rules(self, existing_rules: list[dict[str, object]] | None = None) -> None:
        current_matches = {
            str(rule.get("match", "") or "").strip().casefold()
            for rule in normalize_pronunciation_rules(existing_rules or self.current_pronunciation_rules())
        }
        author_rules = build_author_pronunciation_rules(authors=set(self._pronunciation_author_terms()))
        for rule in author_rules:
            match = str(rule.get("match", "") or "").strip()
            if not match or match.casefold() in current_matches:
                continue
            current_matches.add(match.casefold())
            self.add_pronunciation_rule(match, str(rule.get("spoken_as", "") or match))

    def _pronunciation_seed_terms(self) -> list[str]:
        terms: list[str] = list(self.lexicon_seed_terms)
        for author in self._pronunciation_author_terms():
            if author and author not in terms:
                terms.append(author)
        if self.current_source:
            try:
                guessed = guess_metadata_from_filename(self.current_source)
                title = " ".join(str(guessed.get("title", "") or "").split()).strip()
                if title and title not in terms:
                    terms.append(title)
            except Exception:
                pass
        return terms

    def _pronunciation_author_terms(self) -> list[str]:
        authors: list[str] = []
        for seed in self.lexicon_seed_terms:
            if seed and seed not in authors:
                authors.append(seed)
        if self.current_source:
            try:
                guessed = guess_metadata_from_filename(self.current_source)
                author = " ".join(str(guessed.get("author", "") or "").split()).strip()
                if author and author not in authors:
                    authors.append(author)
            except Exception:
                pass
        return authors

    def add_selected_pronunciation_suggestion(self) -> None:
        item = self.xtts_pronunciation_suggestions.currentItem()
        if item is None:
            QMessageBox.warning(self, "Kein Vorschlag", "Bitte zuerst einen Namensvorschlag auswählen.")
            return
        suggestion = item.data(Qt.ItemDataRole.UserRole) or {}
        self.add_pronunciation_rule(
            str(suggestion.get("match", "")),
            str(suggestion.get("spoken_as", "")),
        )
        self.refresh_pronunciation_suggestions()

    def _pronunciation_suggestion_text(self) -> str:
        text = self.excerpt_view.toPlainText().strip()
        if text:
            return text
        if self.current_session_id:
            try:
                session = {item.session_id: item for item in list_preview_sessions(self.paths)}[self.current_session_id]
                preview_source = Path(session.preview_source_file)
                if preview_source.exists():
                    return preview_source.read_text(encoding="utf-8")
            except Exception:
                return ""
        return ""

    def current_xtts_quality_mode(self) -> str:
        return normalize_xtts_quality_mode(self.xtts_quality_mode_combo.currentData() or "fast")

    def _current_xtts_inference_key(self, quality_mode: str | None = None) -> str:
        normalized_mode = normalize_xtts_quality_mode(quality_mode or self.current_xtts_quality_mode())
        return "::".join(
            [
                self.backend_combo.currentText().strip(),
                self.voice_profile_combo.currentData() or "",
                normalized_mode,
            ]
        )

    def _set_xtts_inference_override(self, inference_options: dict[str, object], quality_mode: str) -> None:
        if not inference_options:
            self._xtts_inference_override = {}
            self._xtts_inference_override_key = ""
            return
        normalized_mode = normalize_xtts_quality_mode(quality_mode or "fast")
        self._xtts_inference_override = dict(inference_options)
        self._xtts_inference_override_key = self._current_xtts_inference_key(normalized_mode)

    def current_xtts_inference(self) -> dict[str, object]:
        quality_mode = self.current_xtts_quality_mode()
        override_key = self._current_xtts_inference_key(quality_mode)
        if self._xtts_inference_override and self._xtts_inference_override_key == override_key:
            return dict(self._xtts_inference_override)
        return default_xtts_inference(quality_mode)

    def on_saved_setting_changed(self) -> None:
        setting_id = self.saved_settings_combo.currentData() or ""
        if not setting_id:
            self.current_saved_setting_id = ""
            self.saved_settings_status_label.setText(
                "Noch kein Produktionsprofil geladen. Speichere hier zuerst eine getestete Kombination."
            )
            return
        setting = load_voice_setting(self.paths.voice_settings, setting_id)
        self.current_saved_setting_id = setting.setting_id
        benchmark_text = (
            f" | Benchmark {setting.benchmark_average_ms/1000:.2f}s"
            if setting.benchmark_average_ms > 0
            else ""
        )
        self.saved_settings_status_label.setText(
            f"{setting.display_name} | Status {profile_status_label(setting.status, ui_language=self.ui_language)} | Backend {setting.backend} | "
            f"Ausgabe {setting.output_mode} | XTTS-Modus {setting.xtts_quality_mode} | Regeln {len(setting.pronunciation_rules)}"
            f"{benchmark_text} | freigegeben {setting.approved_at or '-'} | aktualisiert {setting.updated_at}"
        )

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
                "Automatisch (CPU / CUDA)" if preferred_mode == "cuda" else "Auto",
            )
        if preferred_mode == "cuda" and self.app_settings.xtts_device_mode in {"", "auto"}:
            self.app_settings.xtts_device_mode = "cuda"
            save_app_settings(self.paths.app_settings_file, self.app_settings)
            device_index = self.xtts_device_combo.findData("cuda")
            if device_index >= 0:
                self.xtts_device_combo.setCurrentIndex(device_index)
            self.xtts_backend.set_device_mode("cuda")

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
        self.maybe_start_xtts_warmup()

    def maybe_start_xtts_warmup(self) -> None:
        if self.backend_combo.currentText() != "xtts":
            return
        if self.studio_tabs.currentWidget() is not self.backend_page:
            return
        if self.backend_tabs.currentIndex() != 1:
            return
        profile_id = self.voice_profile_combo.currentData() or ""
        if not profile_id or not self.xtts_backend.is_available():
            return
        warmup_key = f"{profile_id}::{self.xtts_device_combo.currentData() or 'auto'}"
        if warmup_key == self.last_xtts_warmup_key:
            return
        if self.xtts_warmup_worker and self.xtts_warmup_worker.isRunning():
            if self.current_xtts_warmup_key == warmup_key:
                return
            return
        self.current_xtts_warmup_key = warmup_key
        self.xtts_warmup_worker = XttsWarmupWorker(
            self.paths,
            profile_id,
            self.xtts_device_combo.currentData() or "auto",
        )
        self.xtts_warmup_worker.warmup_finished.connect(self.on_xtts_warmup_finished)
        self.xtts_warmup_worker.warmup_failed.connect(self.on_xtts_warmup_failed)
        self.xtts_warmup_worker.finished.connect(self.cleanup_xtts_warmup_worker)
        self.status_label.setText("XTTS wird im Hintergrund vorgewaermt. Erste Preview wird dadurch spaeter deutlich kuerzer.")
        self.xtts_warmup_worker.start()

    def on_backend_tab_changed(self, index: int) -> None:
        backend = "piper" if index == 0 else "xtts"
        if self.backend_combo.currentText() == backend:
            if backend == "xtts":
                self.maybe_start_xtts_warmup()
            return
        backend_index = self.backend_combo.findText(backend)
        if backend_index >= 0:
            self.backend_combo.setCurrentIndex(backend_index)

    def _studio_step_labels(self) -> list[str]:
        return [self.studio_tabs.tabText(index) for index in range(self.studio_tabs.count())]

    def update_workflow_navigation(self) -> None:
        current_index = self.studio_tabs.currentIndex()
        steps = self._studio_step_labels()
        current_label = steps[current_index] if 0 <= current_index < len(steps) else "-"
        next_label = steps[current_index + 1] if current_index + 1 < len(steps) else "Fertig"
        run_hint = ""
        if self.voice_test_run is not None:
            workflow_labels = {
                "prepare": "Vorbereitung",
                "candidates": "Kandidaten sammeln",
                "benchmark": "Benchmark läuft",
                "refine": "Verfeinerung läuft",
                "chunk_tuning": "Chunk-Tuning läuft",
            }
            run_hint = f" Aktuelle Testreihe: {workflow_labels.get(self.voice_test_run.workflow_step, self.voice_test_run.workflow_step)}."
        self.workflow_label.setText(
            f"Schritt {current_index + 1} von {len(steps)}: {current_label}\n"
            f"Nächster Fokus: {next_label}. Im Benchmark-Studio bleibt immer nur der aktuell sinnvolle Teil im Vordergrund.{run_hint}"
        )
        self.workflow_back_button.setEnabled(current_index > 0)
        self.workflow_next_button.setEnabled(current_index < len(steps) - 1)

    def go_to_previous_studio_step(self) -> None:
        current_index = self.studio_tabs.currentIndex()
        if current_index > 0:
            self.studio_tabs.setCurrentIndex(current_index - 1)

    def go_to_next_studio_step(self) -> None:
        current_index = self.studio_tabs.currentIndex()
        if current_index < self.studio_tabs.count() - 1:
            self.studio_tabs.setCurrentIndex(current_index + 1)

    def on_studio_tab_changed(self, _index: int) -> None:
        self.update_workflow_navigation()
        if not hasattr(self, "backend_page") or not hasattr(self, "backend_tabs"):
            return
        if self.studio_tabs.currentWidget() is self.backend_page and self.backend_tabs.currentIndex() == 1:
            self.maybe_start_xtts_warmup()

    def on_test_mode_changed(self) -> None:
        mode = self.test_mode_combo.currentData() or "assistant"
        self.test_mode_stack.setCurrentIndex(0 if mode == "assistant" else 1)
        if mode == "assistant":
            self.test_mode_hint_label.setText(
                "Der Assistent erzeugt Kandidaten automatisch, sammelt deine Qualitätsbewertung und leitet danach in Verfeinerung und Chunk-Tuning über."
            )
        else:
            self.test_mode_hint_label.setText(
                "Die manuelle Benchmark-Reihe lässt dich eigene Kombinationen zusammenstellen und Geschwindigkeit sowie Qualität gezielt vergleichen."
            )

    def _requested_test_language(self) -> str:
        combo = self.assistant_language_combo if (self.test_mode_combo.currentData() or "assistant") == "assistant" else self.benchmark_language_combo
        return combo.currentData() or "de"

    def _requested_test_gender(self) -> str:
        combo = self.assistant_gender_combo if (self.test_mode_combo.currentData() or "assistant") == "assistant" else self.benchmark_gender_combo
        return combo.currentData() or "any"

    def refresh_assistant_language_choices(self) -> None:
        selected_assistant_code = self.assistant_language_combo.currentData() or preferred_content_language_code(self.ui_language).split("_", 1)[0]
        selected_benchmark_code = self.benchmark_language_combo.currentData() or selected_assistant_code
        preferred_code = preferred_content_language_code(self.ui_language).split("_", 1)[0]
        codes: dict[str, str] = {preferred_code: _assistant_language_label(preferred_code)}
        for code, label in language_choices(self.installed_voices, ui_language=self.ui_language):
            normalized = str(code).strip().lower()
            if normalized and normalized != "all":
                codes[normalized] = label
        for profile in list_voice_profiles(self.paths.voice_profiles):
            normalized = str(profile.target_language or "").strip().lower()
            if normalized:
                codes.setdefault(normalized, _assistant_language_label(normalized))
        for combo, selected_code in (
            (self.assistant_language_combo, selected_assistant_code),
            (self.benchmark_language_combo, selected_benchmark_code),
        ):
            combo.blockSignals(True)
            combo.clear()
            for code, label in sorted(codes.items(), key=lambda item: item[1]):
                combo.addItem(label, code)
            selected_index = combo.findData(selected_code)
            combo.setCurrentIndex(selected_index if selected_index >= 0 else 0)
            combo.blockSignals(False)

    def rebuild_voice_combo(self) -> None:
        selected_voice_id = self.voice_combo.currentData() or self.voice_combo.currentText().strip()
        language_code = self.voice_language_combo.currentData() or ""
        visible_voices = filter_voice_ids(
            self.installed_voices,
            language_code,
            female_only=self.voice_female_only_checkbox.isChecked(),
            high_only=self.voice_high_only_checkbox.isChecked(),
        )
        self.voice_combo.clear()
        for voice_id in visible_voices:
            self.voice_combo.addItem(format_voice_label(voice_id, ui_language=self.ui_language), voice_id)
        if visible_voices:
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

    def on_backend_changed(self) -> None:
        is_piper = self.backend_combo.currentText() == "piper"
        expected_tab_index = 0 if is_piper else 1
        if self.backend_tabs.currentIndex() != expected_tab_index:
            self.backend_tabs.blockSignals(True)
            self.backend_tabs.setCurrentIndex(expected_tab_index)
            self.backend_tabs.blockSignals(False)
        self.voice_combo.setEnabled(is_piper)
        self.voice_language_combo.setEnabled(is_piper)
        self.voice_profile_combo.setEnabled(not is_piper)
        self.xtts_device_combo.setEnabled(not is_piper)
        self.xtts_quality_mode_combo.setEnabled(not is_piper)
        self.xtts_pronunciation_table.setEnabled(not is_piper)
        self.xtts_pronunciation_suggestions.setEnabled(not is_piper)
        if is_piper:
            self.status_label.setText("Piper aktiv: schnell und offline, aber oft synthetischer.")
        else:
            self.xtts_backend.set_device_mode(self.xtts_device_combo.currentData() or "auto")
            if not self.xtts_backend.is_available():
                self.status_label.setText(f"XTTS nicht bereit: {self.xtts_backend.availability_reason()}")
            else:
                self.status_label.setText(
                    "XTTS aktiv: bessere Chance auf natuerlichen Klang mit guten Sprecherprofilen. "
                    f"Geraet: {self.xtts_device_combo.currentData() or 'auto'}."
                )
                self.maybe_start_xtts_warmup()

    def restore_last_session(self) -> None:
        sessions = list_preview_sessions(self.paths)
        if sessions:
            self.current_session_id = sessions[0].session_id
            self.current_source = Path(sessions[0].source_file)
            self.source_label.setText(str(self.current_source))
            self.show_session(sessions[0].session_id)
        else:
            self.refresh_source_analysis()

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
        self.source_analysis_label.setText("Sitzungserstellung läuft …")
        request_id = self._next_async_request_id()
        self._active_create_session_request_id = request_id
        source_path = self.current_source
        source_path_text = str(source_path)

        def _create_preview_session() -> str:
            return create_preview_session(self.paths, source_path).session_id

        self._create_session_runner = AsyncTaskRunner(request_id, _create_preview_session, parent=self)

        def on_success(rid: int, session_id: str) -> None:
            if rid != self._active_create_session_request_id:
                return
            if not self.current_source or str(self.current_source) != source_path_text:
                return
            self.show_session(session_id)

        def on_failure(rid: int, message: str) -> None:
            if rid != self._active_create_session_request_id:
                return
            if not self.current_source or str(self.current_source) != source_path_text:
                return
            self.source_analysis_label.setText(
                self._text("Sitzungserstellung fehlgeschlagen: ") + message.strip().splitlines()[-1]
            )

        self._connect_async_runner(self._create_session_runner, on_success, on_failure)

    def show_session(self, session_id: str) -> None:
        session = {item.session_id: item for item in list_preview_sessions(self.paths)}[session_id]
        self.current_session_id = session_id
        self.current_source = Path(session.source_file)
        self.source_label.setText(str(self.current_source))
        self.refresh_source_analysis()
        self.excerpt_view.setPlainText(session.preview_excerpt)
        self.refresh_pronunciation_suggestions()

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
        if session.saved_setting_id:
            self.current_saved_setting_id = session.saved_setting_id
            self.refresh_saved_settings()
        self.voice_test_run = load_voice_test_run(self.paths, session_id)
        self.refresh_voice_test_candidates()

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
            "idle": "Kapitelerkennung wartet auf eine Quelle.",
            "supported": f"Kapitel erkannt: {structure.chapter_count} Kapitel können getrennt exportiert werden.",
            "unsupported": "Keine nutzbare Kapitelstruktur erkannt. Kapiteldateien bleiben deaktiviert.",
            "error": "Kapitelanalyse fehlgeschlagen.",
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
        if not self.current_source:
            self.source_structure = self._empty_source_structure("Noch keine Quelle gewählt.")
            self.source_analysis_label.setText(self._source_structure_summary_text(self.source_structure))
            self.apply_requested_output_mode(self.output_mode_requested)
        elif not self.current_source.exists():
            self.source_structure = self._empty_source_structure(
                "Datei noch nicht gefunden. Die Kapitelerkennung startet, sobald die Quelle vorhanden ist."
            )
            self.source_analysis_label.setText(self._source_structure_summary_text(self.source_structure))
            self.apply_requested_output_mode(self.output_mode_requested)
        else:
            source_path = self.current_source
            source_path_text = str(source_path)
            self.source_analysis_label.setText("Kapitelanalyse läuft …")
            request_id = self._next_async_request_id()
            self._active_source_analysis_request_id = request_id

            def _analyze_source() -> tuple[str, DocumentStructure]:
                return source_path_text, analyze_document_structure(source_path)

            self._source_analysis_runner = AsyncTaskRunner(
                request_id,
                _analyze_source,
                parent=self,
            )

            def on_success(rid: int, payload: tuple[str, DocumentStructure]) -> None:
                if rid != self._active_source_analysis_request_id:
                    return
                cached_source, structure = payload
                if not self.current_source or str(self.current_source) != cached_source:
                    return
                self.source_structure = structure
                self.source_analysis_label.setText(self._source_structure_summary_text(self.source_structure))
                self.apply_requested_output_mode(self.output_mode_requested)

            def on_failure(rid: int, message: str) -> None:
                if rid != self._active_source_analysis_request_id:
                    return
                if not self.current_source or str(self.current_source) != source_path_text:
                    return
                self.source_structure = self._empty_source_structure("Kapitelerkennung fehlgeschlagen.")
                self.source_structure.analysis_status = "error"
                self.source_structure.error = message.strip().splitlines()[-1] if message else "Unbekannter Fehler"
                self.source_structure.summary = f"Kapitelerkennung fehlgeschlagen: {self.source_structure.error}"
                self.source_analysis_label.setText(self._source_structure_summary_text(self.source_structure))
                self.apply_requested_output_mode(self.output_mode_requested)

            self._connect_async_runner(self._source_analysis_runner, on_success, on_failure)

    def on_output_mode_radio_toggled(self, mode: str, checked: bool) -> None:
        if not checked or self._syncing_output_mode_radios:
            return
        self.apply_requested_output_mode(mode)

    def apply_requested_output_mode(self, mode: str) -> None:
        self.output_mode_requested = mode or "single_file"
        actual_mode = self.output_mode_requested
        if actual_mode == "chapter_files" and not self.source_structure.supports_chapter_files:
            actual_mode = "single_file"
        index = self.output_mode_combo.findData(actual_mode)
        if index >= 0:
            self.output_mode_combo.setCurrentIndex(index)
        else:
            self.sync_output_mode_radios_from_combo()
            self.update_helper_text()

    def sync_output_mode_radios_from_combo(self) -> None:
        chapter_available = self.source_structure.supports_chapter_files
        self.output_mode_chapter_radio.setEnabled(chapter_available)
        self.output_mode_chapter_radio.setToolTip(
            "Kapitel erkannt: pro Kapitel kann eine eigene Enddatei erzeugt werden."
            if chapter_available
            else "Diese Quelle hat keine stabile Kapitelstruktur. Kapiteldateien bleiben deaktiviert."
        )
        mode = self.output_mode_combo.currentData() or "single_file"
        radio_map = {
            "single_file": self.output_mode_single_radio,
            "chapter_files": self.output_mode_chapter_radio,
            "timed_parts": self.output_mode_timed_radio,
            "segments": self.output_mode_segments_radio,
        }
        self._syncing_output_mode_radios = True
        try:
            radio_map.get(mode, self.output_mode_single_radio).setChecked(True)
        finally:
            self._syncing_output_mode_radios = False

    def new_excerpt(self) -> None:
        if not self.current_session_id:
            QMessageBox.warning(self, "Keine Session", "Bitte zuerst ein Buch waehlen.")
            return
        request_id = self._next_async_request_id()
        self._active_new_excerpt_request_id = request_id
        session_id = self.current_session_id

        self.source_analysis_label.setText("Neuen Ausschnitt wird gesucht …")

        def _refresh_excerpt() -> str:
            return refresh_preview_excerpt(self.paths, session_id).session_id

        self._new_excerpt_runner = AsyncTaskRunner(request_id, _refresh_excerpt, parent=self)

        def on_success(rid: int, refreshed_session_id: str) -> None:
            if rid != self._active_new_excerpt_request_id:
                return
            if self.current_session_id != session_id:
                return
            self.show_session(refreshed_session_id)

        def on_failure(rid: int, message: str) -> None:
            if rid != self._active_new_excerpt_request_id:
                return
            self.source_analysis_label.setText(
                f"Ausschnittsaktualisierung fehlgeschlagen: {message.strip().splitlines()[-1] if message else 'Unbekannter Fehler'}"
            )

        self._connect_async_runner(self._new_excerpt_runner, on_success, on_failure)

    def refresh_voice_test_candidates(self) -> None:
        selected_candidate_id = self.assistant_candidate_combo.currentData() or self.active_assistant_candidate_id
        self.assistant_candidate_combo.clear()
        if not self.voice_test_run:
            self.assistant_candidate_combo.addItem("Noch keine Testreihe erstellt", "")
            self.assistant_status_label.setText("Noch keine Testreihe gestartet.")
            self.active_assistant_candidate_id = ""
            self.update_workflow_navigation()
            return
        preferred_mode = "assistant" if self.voice_test_run.mode == "assistant" else "benchmark"
        mode_index = self.test_mode_combo.findData(preferred_mode)
        if mode_index >= 0:
            self.test_mode_combo.setCurrentIndex(mode_index)
        if not self.voice_test_run.candidates:
            self.assistant_candidate_combo.addItem("Noch keine Kandidaten in der Reihe", "")
            mode_labels = {
                "assistant": "Profil-Assistent",
                "benchmark": "Benchmark-Reihe",
                "chunk_tuning": "Chunk-Tuning-Reihe",
            }
            self.assistant_status_label.setText(
                f"{mode_labels.get(self.voice_test_run.mode, self.voice_test_run.mode)} angelegt. "
                "Füge jetzt Kandidaten hinzu oder starte den Assistenten."
            )
            self.active_assistant_candidate_id = ""
            self.update_workflow_navigation()
            return
        for candidate in self.voice_test_run.candidates:
            rating_suffix = f" | Rating {candidate.rating}/5" if candidate.rating else ""
            avg_ms = average_render_duration_ms(candidate)
            if avg_ms:
                speed_suffix = (
                    f" | Ø {avg_ms/1000:.2f}s ({candidate.benchmark_runs}x)"
                    if candidate.benchmark_runs > 1
                    else f" | {avg_ms/1000:.2f}s"
                )
            else:
                speed_suffix = ""
            self.assistant_candidate_combo.addItem(
                f"{candidate.label}{rating_suffix}{speed_suffix}",
                candidate.candidate_id,
            )
        selected_index = self.assistant_candidate_combo.findData(selected_candidate_id)
        self.assistant_candidate_combo.setCurrentIndex(selected_index if selected_index >= 0 else 0)
        self.active_assistant_candidate_id = self.assistant_candidate_combo.currentData() or ""
        current = next(
            (candidate for candidate in self.voice_test_run.candidates if candidate.candidate_id == self.active_assistant_candidate_id),
            self.voice_test_run.candidates[0],
        )
        self.assistant_rating_spin.setValue(current.rating)
        self.assistant_note.setText(current.rating_note)
        mode_labels = {
            "assistant": "Assistent",
            "benchmark": "Benchmark",
            "chunk_tuning": "Chunk-Tuning",
        }
        ranked = [candidate for candidate in self.voice_test_run.candidates if average_render_duration_ms(candidate) > 0]
        fastest = min(ranked, key=average_render_duration_ms) if ranked else None
        best_rated = max(self.voice_test_run.candidates, key=lambda item: item.rating, default=None)
        summary_parts = [
            f"{mode_labels.get(self.voice_test_run.mode, self.voice_test_run.mode)} aktiv",
            f"{len(self.voice_test_run.candidates)} Kandidaten",
            f"Runde {self.voice_test_run.refinement_round + 1}",
        ]
        if fastest:
            summary_parts.append(f"schnellster {fastest.label} mit {average_render_duration_ms(fastest)/1000:.2f}s")
        if best_rated and best_rated.rating > 0:
            summary_parts.append(f"beste Bewertung {best_rated.label} mit {best_rated.rating}/5")
        self.assistant_status_label.setText(
            " | ".join(summary_parts)
        )
        self.update_workflow_navigation()

    def _selected_assistant_candidate(self):
        if not self.voice_test_run:
            return None
        candidate_id = self.assistant_candidate_combo.currentData() or ""
        for candidate in self.voice_test_run.candidates:
            if candidate.candidate_id == candidate_id:
                return candidate
        return None

    def on_assistant_candidate_changed(self) -> None:
        candidate = self._selected_assistant_candidate()
        if candidate is None:
            return
        self.active_assistant_candidate_id = candidate.candidate_id
        self.assistant_rating_spin.setValue(candidate.rating)
        self.assistant_note.setText(candidate.rating_note)

    def _ensure_test_session(self) -> bool:
        if self.current_session_id:
            return True
        if self.current_source and self.current_source.exists():
            self.create_session()
            return self.current_session_id is not None
        QMessageBox.warning(self, "Keine Quelle", "Bitte zuerst ein Buch waehlen.")
        return False

    def _current_candidate_from_controls(self) -> VoiceTestCandidate | None:
        backend = self.backend_combo.currentText().strip()
        voice_id = self.voice_combo.currentData() or self.voice_combo.currentText().strip()
        voice_profile_id = self.voice_profile_combo.currentData() or ""
        if backend == "piper" and not voice_id:
            QMessageBox.warning(self, "Keine Stimme", "Bitte zuerst eine Piper-Stimme auswaehlen.")
            return None
        if backend == "xtts" and not voice_profile_id:
            QMessageBox.warning(self, "Kein XTTS-Profil", "Bitte zuerst ein XTTS-Profil auswaehlen.")
            return None
        language_code = (
            self.voice_language_combo.currentData()
            if backend == "piper"
            else (load_voice_profile(self.paths.voice_profiles, voice_profile_id).target_language if voice_profile_id else "")
        ) or "de"
        gender_hint = self._requested_test_gender()
        label = self.setting_name.text().strip() or (
            f"{backend.upper()} | {voice_profile_id or voice_id} | {self.max_chars_spin.value()} Zeichen | "
            f"{self.sentence_slider.value()/100:.2f}s | {self.length_slider.value()/100:.2f}"
        )
        return VoiceTestCandidate(
            candidate_id="",
            label=label,
            backend=backend,
            language_code=str(language_code),
            gender_hint=str(gender_hint),
            voice_id=voice_id if backend == "piper" else "",
            voice_profile_id=voice_profile_id if backend == "xtts" else "",
            preset_id=self.preset_combo.currentData(),
            max_chars=self.max_chars_spin.value(),
            output_mode=self.output_mode_combo.currentData(),
            target_part_minutes=self.target_part_minutes_spin.value(),
            sentence_silence=self.sentence_slider.value() / 100,
            length_scale=self.length_slider.value() / 100,
            xtts_quality_mode=self.current_xtts_quality_mode() if backend == "xtts" else "fast",
            xtts_inference=self.current_xtts_inference() if backend == "xtts" else default_xtts_inference("fast"),
            pronunciation_rules=self.current_pronunciation_rules() if backend == "xtts" else [],
            notes="Manuell aus aktuellen Studio-Einstellungen hinzugefügt",
        )

    def start_voice_test_assistant(self) -> None:
        if not self._ensure_test_session():
            return
        assistant_mode_index = self.test_mode_combo.findData("assistant")
        if assistant_mode_index >= 0:
            self.test_mode_combo.setCurrentIndex(assistant_mode_index)
        self.pending_benchmark_candidate_ids = []
        self.play_preview_after_render = True
        session = {item.session_id: item for item in list_preview_sessions(self.paths)}[self.current_session_id]
        self.voice_test_run = create_voice_test_run(
            self.paths,
            session_id=self.current_session_id,
            title=session.title,
            requested_language=self._requested_test_language(),
            requested_gender=self._requested_test_gender(),
            requested_style=self.assistant_combo.currentData() or "nonfiction",
        )
        self.refresh_voice_test_candidates()
        self.load_selected_assistant_candidate()
        self.studio_tabs.setCurrentWidget(self.test_page)
        self.status_label.setText("Profil-Assistent vorbereitet. Kandidat laden oder direkt rendern.")

    def start_benchmark_test_run(self) -> None:
        if not self._ensure_test_session():
            return
        benchmark_mode_index = self.test_mode_combo.findData("benchmark")
        if benchmark_mode_index >= 0:
            self.test_mode_combo.setCurrentIndex(benchmark_mode_index)
        self.pending_benchmark_candidate_ids = []
        self.play_preview_after_render = True
        session = {item.session_id: item for item in list_preview_sessions(self.paths)}[self.current_session_id]
        self.voice_test_run = create_benchmark_run(
            self.paths,
            session_id=self.current_session_id,
            title=session.title,
            requested_language=self._requested_test_language(),
            requested_gender=self._requested_test_gender(),
            requested_style=self.assistant_combo.currentData() or "nonfiction",
        )
        self.refresh_voice_test_candidates()
        self.studio_tabs.setCurrentWidget(self.test_page)
        self.status_label.setText(
            "Leere Benchmark-Reihe angelegt. Füge jetzt aktuelle Einstellungen als Kandidaten hinzu."
        )

    def add_current_settings_to_test_run(self) -> None:
        if not self._ensure_test_session():
            return
        if self.voice_test_run is None:
            self.start_benchmark_test_run()
        if self.voice_test_run is None:
            return
        candidate = self._current_candidate_from_controls()
        if candidate is None:
            return
        self.voice_test_run = add_candidate_to_run(self.paths, self.voice_test_run, candidate)
        self.refresh_voice_test_candidates()
        candidate_index = self.assistant_candidate_combo.findData(self.voice_test_run.candidates[-1].candidate_id)
        if candidate_index >= 0:
            self.assistant_candidate_combo.setCurrentIndex(candidate_index)
        self.studio_tabs.setCurrentWidget(self.test_page)
        self.status_label.setText(f"Kandidat zur Testreihe hinzugefügt: {candidate.label}")

    def load_selected_assistant_candidate(self) -> None:
        candidate = self._selected_assistant_candidate()
        if candidate is None:
            QMessageBox.warning(self, "Kein Kandidat", "Bitte zuerst eine Testreihe erzeugen.")
            return
        self.active_assistant_candidate_id = candidate.candidate_id
        backend_index = self.backend_combo.findText(candidate.backend)
        if backend_index >= 0:
            self.backend_combo.setCurrentIndex(backend_index)
        if candidate.voice_id:
            language_index = self.voice_language_combo.findData(voice_language_code(candidate.voice_id))
            if language_index >= 0:
                self.voice_language_combo.setCurrentIndex(language_index)
            voice_index = self.voice_combo.findData(candidate.voice_id)
            if voice_index >= 0:
                self.voice_combo.setCurrentIndex(voice_index)
        if candidate.voice_profile_id:
            profile_index = self.voice_profile_combo.findData(candidate.voice_profile_id)
            if profile_index >= 0:
                self.voice_profile_combo.setCurrentIndex(profile_index)
        preset_index = self.preset_combo.findData(candidate.preset_id)
        if preset_index >= 0:
            self.preset_combo.setCurrentIndex(preset_index)
        self.apply_requested_output_mode(candidate.output_mode)
        self.max_chars_spin.setValue(candidate.max_chars)
        self.target_part_minutes_spin.setValue(candidate.target_part_minutes)
        self.sentence_slider.setValue(int(round(candidate.sentence_silence * 100)))
        self.length_slider.setValue(int(round(candidate.length_scale * 100)))
        quality_index = self.xtts_quality_mode_combo.findData(candidate.xtts_quality_mode or "fast")
        self.xtts_quality_mode_combo.setCurrentIndex(quality_index if quality_index >= 0 else 0)
        self._set_xtts_inference_override(candidate.xtts_inference, candidate.xtts_quality_mode or "fast")
        self.set_pronunciation_rules(candidate.pronunciation_rules)
        self.assistant_rating_spin.setValue(candidate.rating)
        self.assistant_note.setText(candidate.rating_note)
        self.setting_name.setText(candidate.label)
        self.update_helper_text()
        self.status_label.setText(f"Test-Kandidat geladen: {candidate.label}")

    def render_selected_assistant_candidate(self) -> None:
        candidate = self._selected_assistant_candidate()
        if candidate is None:
            QMessageBox.warning(self, "Kein Kandidat", "Bitte zuerst eine Testreihe erzeugen.")
            return
        self.play_preview_after_render = True
        self.load_selected_assistant_candidate()
        self.render_and_play_preview()

    def benchmark_all_candidates(self) -> None:
        if self.voice_test_run is None or not self.voice_test_run.candidates:
            QMessageBox.warning(self, "Keine Testreihe", "Bitte zuerst eine Testreihe mit Kandidaten erzeugen.")
            return
        if self.preview_worker and self.preview_worker.isRunning():
            QMessageBox.warning(self, "Preview läuft", "Bitte warte, bis die aktuelle Preview beendet ist.")
            return
        self.pending_benchmark_candidate_ids = [
            candidate.candidate_id for candidate in self.voice_test_run.candidates if candidate.candidate_id
        ]
        self.play_preview_after_render = False
        self.status_label.setText(
            f"Benchmark startet mit {len(self.pending_benchmark_candidate_ids)} Kandidaten. Wiedergabe bleibt dabei stumm."
        )
        self._run_next_benchmark_candidate()

    def _run_next_benchmark_candidate(self) -> None:
        if not self.pending_benchmark_candidate_ids:
            self.play_preview_after_render = True
            self.status_label.setText("Benchmark-Reihe abgeschlossen. Zeiten und Bewertungen wurden gespeichert.")
            return
        candidate_id = self.pending_benchmark_candidate_ids.pop(0)
        index = self.assistant_candidate_combo.findData(candidate_id)
        if index >= 0:
            self.assistant_candidate_combo.setCurrentIndex(index)
        self.load_selected_assistant_candidate()
        self.render_and_play_preview()

    def save_assistant_rating(self) -> None:
        candidate = self._selected_assistant_candidate()
        if candidate is None or self.voice_test_run is None:
            QMessageBox.warning(self, "Kein Kandidat", "Bitte zuerst eine Testreihe erzeugen.")
            return
        self.voice_test_run = update_candidate_feedback(
            self.paths,
            self.voice_test_run,
            candidate.candidate_id,
            rating=self.assistant_rating_spin.value(),
            rating_note=self.assistant_note.text().strip(),
        )
        self.refresh_voice_test_candidates()
        self.status_label.setText(f"Bewertung gespeichert: {candidate.label}")

    def refine_voice_test_assistant(self) -> None:
        if self.voice_test_run is None:
            QMessageBox.warning(self, "Keine Testreihe", "Bitte zuerst den Profil-Assistenten starten.")
            return
        self.voice_test_run = create_refinement_round(self.paths, self.voice_test_run)
        self.refresh_voice_test_candidates()
        self.load_selected_assistant_candidate()
        self.studio_tabs.setCurrentWidget(self.test_page)
        self.status_label.setText("Verfeinerungsrunde erstellt.")

    def start_chunk_tuning_round(self) -> None:
        if self.voice_test_run is None:
            QMessageBox.warning(self, "Keine Testreihe", "Bitte zuerst eine Testreihe und Qualitätsbewertungen anlegen.")
            return
        self.pending_benchmark_candidate_ids = []
        self.play_preview_after_render = True
        self.voice_test_run = create_chunk_tuning_round(self.paths, self.voice_test_run)
        if not self.voice_test_run.candidates:
            QMessageBox.warning(
                self,
                "Keine Basisvariante",
                "Für den zweiten Schritt braucht es zuerst mindestens eine bewertete Qualitätsvariante.",
            )
            return
        self.refresh_voice_test_candidates()
        self.load_selected_assistant_candidate()
        self.studio_tabs.setCurrentWidget(self.test_page)
        self.status_label.setText(
            "2. Schritt aktiv: Chunk-Tuning-Reihe aus der bestbewerteten Variante erstellt."
        )

    def apply_assistant_profile(self) -> None:
        profile = self.assistant_combo.currentData()
        presets = {
            "novel": (260, 28, 105, "single_file", 20, "natural", "Gut fuer natuerliche Romanstimmen mit mehr Ruhe."),
            "nonfiction": (220, 20, 100, "chapter_files", 15, "balanced", "Gut fuer klare, neutrale Sachbuchstimmen mit Kapiteldateien."),
            "children": (240, 30, 103, "timed_parts", 10, "natural", "Gut fuer warme, etwas ruhigere Kinderbuchstimmen."),
            "cpu": (170, 12, 95, "segments", 10, "fast_cpu", "Gut fuer schnelle Vorschauen auf CPU-Systemen."),
        }
        max_chars, sentence_pause, length_scale, output_mode, part_minutes, preset_id, note = presets[profile]
        self.max_chars_spin.setValue(max_chars)
        self.sentence_slider.setValue(sentence_pause)
        self.length_slider.setValue(length_scale)
        preset_index = self.preset_combo.findData(preset_id)
        if preset_index >= 0:
            self.preset_combo.setCurrentIndex(preset_index)
        self.apply_requested_output_mode(output_mode)
        self.target_part_minutes_spin.setValue(part_minutes)
        self.update_helper_text()
        self.status_label.setText(f"Assistent aktiv: {note}")

    def on_preset_changed(self) -> None:
        preset = get_preset(self.preset_combo.currentData())
        self.max_chars_spin.setValue(preset.max_chars)
        self.apply_requested_output_mode(preset.output_mode)
        self.target_part_minutes_spin.setValue(preset.target_part_minutes)
        self.sentence_slider.setValue(int(round(preset.sentence_silence * 100)))
        self.length_slider.setValue(int(round(preset.length_scale * 100)))
        self.update_helper_text()

    def update_helper_text(self) -> None:
        sentence_silence = self.sentence_slider.value() / 100
        length_scale = self.length_slider.value() / 100
        max_chars = self.max_chars_spin.value()
        output_mode = self.output_mode_combo.currentData() or "single_file"
        target_part_minutes = self.target_part_minutes_spin.value()
        self.target_part_minutes_spin.setEnabled(output_mode == "timed_parts")
        self.sentence_label.setText(f"{sentence_silence:.2f}s")
        self.length_label.setText(f"{length_scale:.2f}")
        if self.backend_combo.currentText() == "xtts":
            quality_mode = self.current_xtts_quality_mode()
            xtts_effective_chars = safe_xtts_chunk_chars(max_chars, "de")
            hint = (
                "XTTS: gute Referenzsamples sind wichtiger als die letzten Regler-Prozent. "
                f"Geraet: {self.xtts_device_combo.currentData() or 'auto'} | Qualitätsmodus: {quality_mode} | "
                f"Aussprache-Regeln: {len(self.current_pronunciation_rules())}. "
                f"Deutsch wird intern sicher auf {xtts_effective_chars} Zeichen begrenzt."
            )
        elif max_chars >= 240 and sentence_silence >= 0.24 and length_scale >= 1.02:
            hint = "Eher natuerlich und ruhiger."
        elif max_chars <= 190 and sentence_silence <= 0.16 and length_scale <= 0.98:
            hint = "Eher schnell und CPU-freundlich."
        else:
            hint = "Eher ausgewogen fuer die meisten Hoerbuecher."
        output_hint = {
            "single_file": "eine grosse Enddatei",
            "chapter_files": "eine Enddatei pro Kapitel",
            "timed_parts": f"Enddateien etwa alle {target_part_minutes} Minuten",
            "segments": "nur kleine Teil-MP3s",
        }.get(output_mode, output_mode)
        chapter_hint = (
            " Kapiteldateien sind für diese Quelle verfügbar."
            if self.source_structure.supports_chapter_files
            else " Kapiteldateien sind für diese Quelle deaktiviert."
        )
        self.helper_label.setText(
            f"{hint}\nAktuell: {max_chars} Zeichen, {sentence_silence:.2f}s Satzpause, "
            f"{length_scale:.2f} Laenge, Ausgabe: {output_hint}.{chapter_hint}"
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

        current_excerpt = self.excerpt_view.toPlainText().strip()
        if current_excerpt:
            update_preview_excerpt_text(self.paths, self.current_session_id, current_excerpt)

        self.status_label.setText(
            "Preview wird direkt erzeugt. XTTS rendert den aktuellen Absatz in mehreren sauberen Chunks. "
            "Bitte den Dialog waehrenddessen nicht schliessen."
        )
        self.play_now_button.setEnabled(False)
        self.studio_tabs.setCurrentWidget(self.preview_page)
        self.active_assistant_candidate_id = self.assistant_candidate_combo.currentData() or self.active_assistant_candidate_id
        perf_event(
            "preview.start_requested",
            category="preview",
            backend=backend,
            session_id=self.current_session_id,
            voice_id=voice_id,
            voice_profile_id=voice_profile_id,
            max_chars=self.max_chars_spin.value(),
            xtts_quality_mode=self.current_xtts_quality_mode() if backend == "xtts" else "",
            pronunciation_rule_count=len(self.current_pronunciation_rules()) if backend == "xtts" else 0,
        )
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
            self.xtts_device_combo.currentData() or "auto",
            self.current_xtts_quality_mode(),
            self.current_xtts_inference(),
            self.current_pronunciation_rules(),
        )
        self.preview_worker.preview_finished.connect(self.on_preview_finished)
        self.preview_worker.preview_failed.connect(self.on_preview_failed)
        self.preview_worker.finished.connect(self.cleanup_preview_worker)
        self.preview_worker.start()

    def on_xtts_device_mode_changed(self) -> None:
        device_mode = self.xtts_device_combo.currentData() or "auto"
        self.app_settings.xtts_device_mode = device_mode
        save_app_settings(self.paths.app_settings_file, self.app_settings)
        self.xtts_backend.set_device_mode(device_mode)
        self.last_xtts_warmup_key = ""
        self.update_helper_text()
        self.maybe_start_xtts_warmup()

    def on_preview_finished(self, session_id: str, output_file: str, duration_ms: float) -> None:
        self.play_now_button.setEnabled(True)
        self.show_session(session_id)
        if self.voice_test_run and self.active_assistant_candidate_id:
            self.voice_test_run = record_benchmark_result(
                self.paths,
                self.voice_test_run,
                self.active_assistant_candidate_id,
                preview_file=output_file,
                render_duration_ms=duration_ms,
            )
            self.refresh_voice_test_candidates()
        if self.play_preview_after_render:
            self.player.setSource(QUrl.fromLocalFile(output_file))
            self.player.play()
        if self.play_preview_after_render:
            self.status_label.setText(
                f"Preview fertig und wird abgespielt: {Path(output_file).name} | {duration_ms/1000:.2f}s"
            )
        else:
            self.status_label.setText(
                f"Benchmark-Preview fertig: {Path(output_file).name} | {duration_ms/1000:.2f}s"
            )
        if self.pending_benchmark_candidate_ids:
            self.status_label.setText(
                f"Benchmark-Kandidat fertig: {Path(output_file).name} | {duration_ms/1000:.2f}s. Nächster Kandidat folgt."
            )
            self._run_next_benchmark_candidate()
            return
        if not self.play_preview_after_render:
            self.play_preview_after_render = True
            self.status_label.setText(
                f"Benchmark fertig: {Path(output_file).name} | {duration_ms/1000:.2f}s"
            )

    def on_preview_failed(self, message: str) -> None:
        self.play_now_button.setEnabled(True)
        self.pending_benchmark_candidate_ids = []
        self.play_preview_after_render = True
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

    def on_xtts_warmup_finished(self, profile_id: str, duration_ms: float) -> None:
        current_profile_id = self.voice_profile_combo.currentData() or ""
        if self.current_xtts_warmup_key:
            self.last_xtts_warmup_key = self.current_xtts_warmup_key
        if current_profile_id == profile_id and self.backend_combo.currentText() == "xtts":
            self.status_label.setText(
                f"XTTS bereit: Profil {profile_id} vorgewaermt in {duration_ms/1000:.2f}s. "
                "Die naechste Preview spart den Modellstart."
            )

    def on_xtts_warmup_failed(self, profile_id: str, message: str) -> None:
        current_profile_id = self.voice_profile_combo.currentData() or ""
        if current_profile_id == profile_id and self.backend_combo.currentText() == "xtts":
            self.logger.warning("XTTS warmup failed for %s", profile_id)
            self.details.setPlainText(message)
            self.status_label.setText("XTTS-Warmup fehlgeschlagen. Preview funktioniert weiter, aber der erste Start kann laenger dauern.")

    def cleanup_preview_worker(self) -> None:
        worker = self.sender()
        if worker is self.preview_worker:
            self.preview_worker = None
        if worker is not None and hasattr(worker, "deleteLater"):
            worker.deleteLater()

    def cleanup_xtts_warmup_worker(self) -> None:
        worker = self.sender()
        if worker is self.xtts_warmup_worker:
            self.xtts_warmup_worker = None
            self.current_xtts_warmup_key = ""
        if worker is not None and hasattr(worker, "deleteLater"):
            worker.deleteLater()

    def _wait_for_preview_workers(self, on_idle: callable | None = None) -> None:
        if self.preview_worker and self.preview_worker.isRunning():
            self._shutdown_wait_attempts += 1
            if self._shutdown_wait_attempts > 120:
                self.logger.warning("Preview worker shutdown timeout while closing dialog.")
            else:
                self.status_label.setText("Preview läuft noch. Warte auf sauberen Abschluss...")
                QTimer.singleShot(120, lambda: self._wait_for_preview_workers(on_idle))
                return
        if self.xtts_warmup_worker and self.xtts_warmup_worker.isRunning():
            self._shutdown_wait_attempts += 1
            if self._shutdown_wait_attempts > 120:
                self.logger.warning("XTTS warmup worker shutdown timeout while closing dialog.")
            else:
                self.status_label.setText("XTTS wird noch vorgewaermt. Warte auf sauberen Abschluss...")
                QTimer.singleShot(120, lambda: self._wait_for_preview_workers(on_idle))
                return
        self._shutdown_wait_attempts = 0
        self._pending_close = False
        if on_idle is not None:
            on_idle()

    def _shutdown_preview_workers(self, on_idle: callable | None = None) -> None:
        self._wait_for_preview_workers(on_idle)

    def handle_about_to_quit(self) -> None:
        self._shutdown_preview_workers()

    def _finalize_reject(self) -> None:
        super().reject()

    def reject(self) -> None:
        if self.preview_worker and self.preview_worker.isRunning():
            self.status_label.setText(
                "Preview laeuft noch. Bitte kurz warten, bis sie fertig ist."
            )
            QMessageBox.information(
                self,
                "Preview laeuft",
                "Die Preview wird noch erzeugt. Bitte kurz warten, bis sie fertig ist.",
            )
            return
        if self.xtts_warmup_worker and self.xtts_warmup_worker.isRunning():
            self.status_label.setText("XTTS wird noch vorgewaermt. Bitte kurz warten.")
            self._shutdown_preview_workers(self._finalize_reject)
            return
        super().reject()

    def closeEvent(self, event) -> None:
        if self._pending_close:
            super().closeEvent(event)
            return
        if self.preview_worker and self.preview_worker.isRunning():
            self.status_label.setText(
                "Preview laeuft noch. Bitte kurz warten, bis sie fertig ist."
            )
            QMessageBox.information(
                self,
                "Preview laeuft",
                "Die Preview wird noch erzeugt. Bitte kurz warten, bis sie fertig ist.",
            )
            event.ignore()
            self._pending_close = True
            self._shutdown_preview_workers(lambda: self.close())
            return
        if self.xtts_warmup_worker and self.xtts_warmup_worker.isRunning():
            self.status_label.setText("XTTS wird noch vorgewaermt. Warte auf sauberen Abschluss...")
            event.ignore()
            self._pending_close = True
            self._shutdown_preview_workers(lambda: self.close())
            return
        super().closeEvent(event)

    def play_last_preview(self) -> None:
        if not self.current_session_id:
            QMessageBox.warning(self, "Keine Session", "Bitte zuerst ein Buch waehlen.")
            return
        session = {item.session_id: item for item in list_preview_sessions(self.paths)}[self.current_session_id]
        preview_file = Path(session.last_preview_output) if session.last_preview_output else None
        if not preview_file or not preview_file.exists():
            QMessageBox.warning(self, "Keine Preview", "Es gibt noch keine fertige Preview-Datei.")
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

    def _selected_candidate_for_profile_save(self) -> VoiceTestCandidate | None:
        candidate = self._selected_assistant_candidate()
        if candidate is None:
            return None
        backend = self.backend_combo.currentText().strip()
        voice_id = self.voice_combo.currentData() or self.voice_combo.currentText().strip()
        voice_profile_id = self.voice_profile_combo.currentData() or ""
        if candidate.backend != backend:
            return None
        if candidate.voice_id != voice_id:
            return None
        if candidate.voice_profile_id != voice_profile_id:
            return None
        return candidate

    def set_saved_setting_status(self, status: str) -> None:
        setting_id = self.saved_settings_combo.currentData() or ""
        if not setting_id:
            QMessageBox.warning(self, "Kein Profil", "Bitte zuerst ein gespeichertes Produktionsprofil auswählen.")
            return
        updated = update_voice_setting_status(self.paths.voice_settings, setting_id, status)
        self.current_saved_setting_id = updated.setting_id
        self.refresh_saved_settings()
        self.saved_settings_combo.setCurrentIndex(self.saved_settings_combo.findData(updated.setting_id))
        self.status_label.setText(
            f"Produktionsprofilstatus aktualisiert: {updated.display_name} -> {profile_status_label(updated.status, ui_language=self.ui_language)}"
        )

    def save_setting(self, *, as_new: bool = False) -> None:
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
        current_excerpt = self.excerpt_view.toPlainText().strip()
        selected_candidate = self._selected_candidate_for_profile_save()
        benchmark_average_ms = average_render_duration_ms(selected_candidate) if selected_candidate is not None else 0.0
        last_benchmark_ms = selected_candidate.render_duration_ms if selected_candidate is not None else 0.0
        last_benchmark_at = selected_candidate.last_rendered_at if selected_candidate is not None else ""
        setting = save_voice_setting(
            self.paths.voice_settings,
            display_name=display_name,
            backend=backend,
            voice_id=voice_id,
            voice_profile_id=voice_profile_id,
            preset_hint=self.preset_combo.currentData(),
            max_chars=self.max_chars_spin.value(),
            output_mode=self.output_mode_combo.currentData(),
            target_part_minutes=self.target_part_minutes_spin.value(),
            sentence_silence=self.sentence_slider.value() / 100,
            length_scale=self.length_slider.value() / 100,
            notes="Gespeichert aus Profilstudio & Hörproben",
            status=PROFILE_STATUS_TESTED,
            benchmark_average_ms=benchmark_average_ms,
            last_benchmark_ms=last_benchmark_ms,
            last_benchmark_at=last_benchmark_at,
            source_session_id=self.current_session_id or "",
            source_run_id=self.voice_test_run.run_id if self.voice_test_run is not None else "",
            source_candidate_id=selected_candidate.candidate_id if selected_candidate is not None else "",
            xtts_quality_mode=self.current_xtts_quality_mode() if backend == "xtts" else "fast",
            xtts_inference=self.current_xtts_inference() if backend == "xtts" else default_xtts_inference("fast"),
            pronunciation_rules=self.current_pronunciation_rules() if backend == "xtts" else [],
            setting_id=None if as_new else self.current_saved_setting_id or None,
            ensure_unique_name=as_new,
        )
        self.current_saved_setting_id = setting.setting_id
        self.refresh_saved_settings()
        if self.current_session_id:
            if current_excerpt:
                update_preview_excerpt_text(self.paths, self.current_session_id, current_excerpt)
            update_preview_selection(
                self.paths,
                self.current_session_id,
                backend,
                voice_id,
                voice_profile_id,
            )
            link_saved_setting(self.paths, self.current_session_id, setting.setting_id)
            self.show_session(self.current_session_id)
        action_text = "neu gespeichert" if as_new else "aktualisiert"
        self.status_label.setText(
            f"Produktionsprofil {action_text}: {setting.display_name}. Status jetzt: {profile_status_label(setting.status, ui_language=self.ui_language)}."
        )

    def save_setting_as_new(self) -> None:
        self.save_setting(as_new=True)

    def load_selected_saved_setting(self) -> None:
        setting_id = self.saved_settings_combo.currentData() or ""
        if not setting_id:
            QMessageBox.warning(self, "Keine Profile", "Es gibt noch kein gespeichertes Produktionsprofil.")
            return
        setting = load_voice_setting(self.paths.voice_settings, setting_id)
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
        preset_index = self.preset_combo.findData(setting.preset_hint)
        if preset_index >= 0:
            self.preset_combo.setCurrentIndex(preset_index)
        self.apply_requested_output_mode(setting.output_mode)
        self.target_part_minutes_spin.setValue(setting.target_part_minutes)
        self.sentence_slider.setValue(int(round(setting.sentence_silence * 100)))
        self.length_slider.setValue(int(round(setting.length_scale * 100)))
        quality_index = self.xtts_quality_mode_combo.findData(setting.xtts_quality_mode)
        self.xtts_quality_mode_combo.setCurrentIndex(quality_index if quality_index >= 0 else 0)
        self._set_xtts_inference_override(setting.xtts_inference, setting.xtts_quality_mode)
        self.set_pronunciation_rules(setting.pronunciation_rules)
        self.setting_name.setText(setting.display_name)
        self.current_saved_setting_id = setting.setting_id
        self.update_helper_text()
        self.status_label.setText(
            f"Produktionsprofil geladen: {setting.display_name} ({profile_status_label(setting.status, ui_language=self.ui_language)})"
        )

    def open_voice_lab(self) -> None:
        if self._focus_existing_dialog(self._voice_lab_dialog):
            return
        if self._voice_lab_dialog is None:
            dialog = VoiceLabDialog(self.paths, self, ui_language=self.ui_language)
            dialog.finished.connect(lambda _result: setattr(self, "_voice_lab_dialog", None))
            self._voice_lab_dialog = dialog
        else:
            dialog = self._voice_lab_dialog
        dialog.exec()
        self.refresh_voice_profiles()

    def _wrap(self, layout: QHBoxLayout) -> QWidget:
        widget = QWidget()
        widget.setLayout(layout)
        return widget

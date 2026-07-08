from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
import wave
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox

from book2mp3.config import AppPaths
from book2mp3.preview_sessions import list_preview_sessions
from book2mp3.tts.xtts import XttsBackend
from book2mp3.ui.find_best_setting_dialog import FindBestSettingDialog
from book2mp3.ui.main_window import MainWindow
from book2mp3.voice_lab import create_voice_profile
from book2mp3.xtts_options import XTTS_SAFE_CHUNK_CHARS


ROOT = Path("/home/codex/repo/book2mp3")
APP_SRC_ROOT = ROOT / "src"


def runtime_fixture_root() -> Path:
    candidate = APP_SRC_ROOT / "runtime"
    return candidate if candidate.exists() else ROOT / "runtime"


def ensure_runtime_fixture(app_root: Path) -> None:
    runtime_target = runtime_fixture_root()
    runtime_link = app_root / "runtime"
    if runtime_link.exists():
        return
    runtime_link.symlink_to(runtime_target, target_is_directory=True)


def create_dummy_wav(path: Path, seconds: int = 4) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes(b"\x00\x00" * 16000 * seconds)


def synthesize_dummy_wav(
    self: XttsBackend,
    text: str,
    profile,
    wav_path: Path,
    length_scale: float = 1.0,
    enable_text_splitting: bool = False,
    inference_options: dict[str, object] | None = None,
) -> None:
    del self, text, profile, length_scale, enable_text_splitting, inference_options
    create_dummy_wav(wav_path, seconds=2)


CAPTURED_XTTS_TEXTS: list[str] = []


def synthesize_dummy_wavs(
    self: XttsBackend,
    texts: list[str],
    profile,
    wav_paths: list[Path],
    length_scale: float = 1.0,
    enable_text_splitting: bool = False,
    inference_options: dict[str, object] | None = None,
) -> None:
    del self, profile, length_scale, enable_text_splitting, inference_options
    CAPTURED_XTTS_TEXTS.clear()
    CAPTURED_XTTS_TEXTS.extend(texts)
    for wav_path in wav_paths:
        create_dummy_wav(wav_path, seconds=2)


def warmup_noop(self: XttsBackend, profile, *, speaker_sample_limit: int = 1) -> None:
    del self, profile, speaker_sample_limit


def pump_events_until(app: QApplication, predicate, timeout_seconds: float) -> bool:
    deadline = time.time() + timeout_seconds
    while not predicate() and time.time() < deadline:
        app.processEvents()
        time.sleep(0.05)
    app.processEvents()
    return bool(predicate())


def main() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    with tempfile.TemporaryDirectory(prefix="book2mp3-smoke-xtts-ui-") as tmp_dir:
        app_root = Path(tmp_dir) / "src"
        app_root.mkdir(parents=True, exist_ok=True)
        ensure_runtime_fixture(app_root)
        shutil.copytree(ROOT / "voices", app_root / "voices", dirs_exist_ok=True)
        paths = AppPaths.from_project_root(app_root)
        paths.ensure()

        sample = app_root / "xtts_sample.wav"
        create_dummy_wav(sample)
        manifest = create_voice_profile(
            paths.voice_profiles,
            display_name="XTTS UI Smoke",
            target_language="de",
            backend="xtts_v2",
            notes="XTTS UI Smoke",
            sample_paths=[sample],
        )
        profile_id = manifest.parent.name

        original = XttsBackend.synthesize_to_wav
        original_many = XttsBackend.synthesize_many_to_wavs
        original_warmup = XttsBackend.warmup_profile
        XttsBackend.synthesize_to_wav = synthesize_dummy_wav
        XttsBackend.synthesize_many_to_wavs = synthesize_dummy_wavs
        XttsBackend.warmup_profile = warmup_noop
        try:
            app = QApplication([])
            QMessageBox.information = staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Ok)
            QMessageBox.warning = staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Ok)
            window = MainWindow(paths)
            window.maybe_start_next_job = lambda: None

            dialog = FindBestSettingDialog(paths, window.manager, window)
            dialog.current_source = ROOT / "test.epub"
            dialog.create_session()
            if not pump_events_until(app, lambda: bool(dialog.current_session_id), 20):
                raise AssertionError("Preview session was not created")

            backend_index = dialog.backend_combo.findText("xtts")
            if backend_index < 0:
                raise AssertionError("XTTS backend option not found")
            dialog.backend_combo.setCurrentIndex(backend_index)
            app.processEvents()
            if dialog.backend_combo.currentText() != "xtts":
                raise AssertionError(f"Expected xtts backend, got {dialog.backend_combo.currentText()}")
            dialog.refresh_voice_profiles()
            profile_index = dialog.voice_profile_combo.findData(profile_id)
            if profile_index < 0:
                raise AssertionError(f"Expected XTTS profile {profile_id} in combo")
            dialog.voice_profile_combo.setCurrentIndex(profile_index)

            session = {item.session_id: item for item in list_preview_sessions(paths)}[dialog.current_session_id]
            dialogue_excerpt = (
                "« »Wirst du uns überhaupt nicht vermissen?« Talwyn sackte ein wenig in sich zusammen. "
                "»Darum geht es nicht, und das weißt du auch.« »Ich weiß nur, dass wir gemeinsam am stärksten sind.« "
                "»Und ich weiß nur, dass wir in den letzten fünf Jahren nur stagniert haben. "
                "Wir haben unsere Fähigkeiten nicht weiterentwickelt.« »Unsere Fähigkeiten oder unsere Macht?« "
                "»Beides.« »Was ist los, Schwester? Willst du Drachenkönigin und Südlandkönigin werden?« "
                "»Nein. Ich will diese Blutlinie auch noch für die nächsten Jahrtausende blühen und gedeihen sehen.«"
            )
            Path(session.preview_source_file).write_text(dialogue_excerpt, encoding="utf-8")
            dialog.excerpt_view.setPlainText(dialogue_excerpt)
            dialog.max_chars_spin.setValue(450)

            dialog.setting_name.setText("XTTS Smoke UI Voice")
            dialog.save_setting()
            dialog.render_and_play_preview()

            if not pump_events_until(
                app,
                lambda: dialog.preview_worker is None or not dialog.preview_worker.isRunning(),
                60,
            ):
                raise AssertionError("XTTS live preview worker did not finish in time")

            updated_session = {item.session_id: item for item in list_preview_sessions(paths)}[dialog.current_session_id]
            preview_output = Path(updated_session.last_preview_output) if updated_session.last_preview_output else None
            if not preview_output or not preview_output.exists():
                raise AssertionError(f"Expected XTTS preview output, got: {updated_session.last_preview_output}")
            if preview_output.suffix.lower() != ".mp3":
                raise AssertionError(f"Expected concatenated MP3 preview, got: {preview_output}")
            if len(CAPTURED_XTTS_TEXTS) < 2:
                raise AssertionError(f"Expected multi-chunk XTTS preview, got {CAPTURED_XTTS_TEXTS}")
            oversized_chunks = [item for item in CAPTURED_XTTS_TEXTS if len(item) > XTTS_SAFE_CHUNK_CHARS]
            if oversized_chunks:
                raise AssertionError(f"Expected XTTS-safe preview chunks, got: {oversized_chunks}")
            joined_preview = " ".join(CAPTURED_XTTS_TEXTS)
            if "«" in joined_preview or "»" in joined_preview:
                raise AssertionError(f"Expected guillemets to be removed before XTTS, got: {joined_preview!r}")
            if "Drachenkönigin" not in joined_preview:
                raise AssertionError(f"Expected later paragraph text in preview, got: {joined_preview!r}")

            summary = {
                "backend": updated_session.backend,
                "voice_profile_id": updated_session.voice_profile_id,
                "preview_status": updated_session.last_preview_status,
                "preview_output": str(preview_output),
                "xtts_chunk_count": len(CAPTURED_XTTS_TEXTS),
            }
            print(json.dumps(summary, indent=2))
            window.close()
            dialog.close()
            app.quit()
        finally:
            XttsBackend.synthesize_to_wav = original
            XttsBackend.synthesize_many_to_wavs = original_many
            XttsBackend.warmup_profile = original_warmup
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

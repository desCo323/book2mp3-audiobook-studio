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


def synthesize_dummy_wav(self: XttsBackend, text: str, profile, wav_path: Path, length_scale: float = 1.0) -> None:
    del self, text, profile, length_scale
    create_dummy_wav(wav_path, seconds=2)


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
        XttsBackend.synthesize_to_wav = synthesize_dummy_wav
        try:
            app = QApplication([])
            QMessageBox.information = staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Ok)
            QMessageBox.warning = staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Ok)
            window = MainWindow(paths)
            window.maybe_start_next_job = lambda: None

            dialog = FindBestSettingDialog(paths, window.manager, window)
            dialog.current_source = ROOT / "test.epub"
            dialog.create_session()
            if not dialog.current_session_id:
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
            Path(session.preview_source_file).write_text(session.preview_excerpt[:220], encoding="utf-8")

            dialog.setting_name.setText("XTTS Smoke UI Voice")
            dialog.save_setting()
            dialog.render_and_play_preview()

            deadline = time.time() + 60
            while dialog.preview_worker and dialog.preview_worker.isRunning() and time.time() < deadline:
                app.processEvents()
                time.sleep(0.1)

            if dialog.preview_worker and dialog.preview_worker.isRunning():
                raise AssertionError("XTTS live preview worker did not finish in time")

            updated_session = {item.session_id: item for item in list_preview_sessions(paths)}[dialog.current_session_id]
            preview_output = Path(updated_session.last_preview_output) if updated_session.last_preview_output else None
            if not preview_output or not preview_output.exists():
                raise AssertionError(f"Expected XTTS preview MP3, got: {updated_session.last_preview_output}")

            summary = {
                "backend": updated_session.backend,
                "voice_profile_id": updated_session.voice_profile_id,
                "preview_status": updated_session.last_preview_status,
                "preview_output": str(preview_output),
            }
            print(json.dumps(summary, indent=2))
            window.close()
            dialog.close()
            app.quit()
        finally:
            XttsBackend.synthesize_to_wav = original
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

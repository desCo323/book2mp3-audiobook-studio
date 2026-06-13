from __future__ import annotations

import json
import os
import shutil
import tempfile
import wave
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox

from book2mp3.config import AppPaths
from book2mp3.ui.main_window import MainWindow
from book2mp3.voice_lab import create_voice_profile
from book2mp3.voice_settings import PROFILE_STATUS_APPROVED, save_voice_setting


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


def main() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    with tempfile.TemporaryDirectory(prefix="book2mp3-smoke-xtts-main-") as tmp_dir:
        app_root = Path(tmp_dir) / "src"
        app_root.mkdir(parents=True, exist_ok=True)
        ensure_runtime_fixture(app_root)
        shutil.copytree(ROOT / "voices", app_root / "voices", dirs_exist_ok=True)
        paths = AppPaths.from_project_root(app_root)
        paths.ensure()

        sample = app_root / "xtts_main_sample.wav"
        create_dummy_wav(sample)
        manifest = create_voice_profile(
            paths.voice_profiles,
            display_name="XTTS Main Smoke",
            target_language="de",
            backend="xtts_v2",
            notes="XTTS Main Window Smoke",
            sample_paths=[sample],
        )
        profile_id = manifest.parent.name

        app = QApplication([])
        QMessageBox.information = staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Ok)
        QMessageBox.warning = staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Ok)

        window = MainWindow(paths)
        window.source_edit.setText(str(ROOT / "test.epub"))
        window.refresh_voice_profiles()
        approved_profile = save_voice_setting(
            paths.voice_settings,
            display_name="XTTS Main Approved",
            backend="xtts",
            voice_id="",
            voice_profile_id=profile_id,
            preset_hint="premium_natural",
            max_chars=260,
            output_mode="single_file",
            target_part_minutes=15,
            sentence_silence=0.22,
            length_scale=1.0,
            status=PROFILE_STATUS_APPROVED,
            notes="Automatisch freigegeben für XTTS Main Window Smoke",
        )
        window.refresh_saved_profiles()
        approved_index = window.saved_profile_combo.findData(approved_profile.setting_id)
        if approved_index < 0:
            raise AssertionError(f"Approved XTTS profile not selectable in job dialog: {approved_profile.setting_id}")
        window.saved_profile_combo.setCurrentIndex(approved_index)

        window.create_job()
        if not window.current_job_id:
            raise AssertionError("Expected XTTS job to be created")
        state = window.manager.load_state(window.current_job_id)
        summary = {
            "job_id": state.job_id,
            "backend": state.backend,
            "saved_profile_id": state.saved_profile_id,
            "voice_profile_id": state.voice_profile_id,
            "preset_id": state.preset_id,
            "output_mode": state.output_mode,
        }
        assert state.backend == "xtts"
        assert state.saved_profile_id == approved_profile.setting_id
        assert state.voice_profile_id == profile_id
        assert state.preset_id == "premium_natural"
        print(json.dumps(summary, indent=2))
        window.close()
        app.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

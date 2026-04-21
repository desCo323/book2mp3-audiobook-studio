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


ROOT = Path("/home/codex/repo/book2mp3")


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
        shutil.copytree(ROOT / "runtime", app_root / "runtime", dirs_exist_ok=True)
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
        backend_index = window.backend_combo.findText("xtts")
        if backend_index < 0:
            raise AssertionError("XTTS backend option not found")
        window.backend_combo.setCurrentIndex(backend_index)
        profile_index = window.voice_profile_combo.findData(profile_id)
        if profile_index < 0:
            raise AssertionError(f"Expected XTTS profile {profile_id} in combo")
        window.voice_profile_combo.setCurrentIndex(profile_index)

        if window.preset_combo.currentData() != "premium_natural":
            raise AssertionError(f"Expected XTTS preset premium_natural, got {window.preset_combo.currentData()}")

        window.create_job()
        if not window.current_job_id:
            raise AssertionError("Expected XTTS job to be created")
        state = window.manager.load_state(window.current_job_id)
        summary = {
            "job_id": state.job_id,
            "backend": state.backend,
            "voice_profile_id": state.voice_profile_id,
            "preset_id": state.preset_id,
            "output_mode": state.output_mode,
        }
        assert state.backend == "xtts"
        assert state.voice_profile_id == profile_id
        assert state.preset_id == "premium_natural"
        print(json.dumps(summary, indent=2))
        window.close()
        app.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

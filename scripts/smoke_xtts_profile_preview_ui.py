from __future__ import annotations

import json
import os
import shutil
import tempfile
import wave
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox

from book2mp3.config import AppPaths
from book2mp3.ui.find_best_setting_dialog import FindBestSettingDialog
from book2mp3.ui.main_window import MainWindow
from book2mp3.ui.voice_lab_dialog import VoiceLabDialog
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


def create_dummy_wav(path: Path, seconds: int = 3) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes(b"\x00\x00" * 16000 * seconds)


def main() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    with tempfile.TemporaryDirectory(prefix="book2mp3-smoke-xtts-profile-ui-") as tmp_dir:
        app_root = Path(tmp_dir) / "src"
        app_root.mkdir(parents=True, exist_ok=True)
        ensure_runtime_fixture(app_root)
        shutil.copytree(ROOT / "voices", app_root / "voices", dirs_exist_ok=True)
        paths = AppPaths.from_project_root(app_root)
        paths.ensure()

        sample = app_root / "xtts_preview_sample.wav"
        create_dummy_wav(sample)
        manifest = create_voice_profile(
            paths.voice_profiles,
            display_name="XTTS Preview Smoke",
            target_language="de",
            backend="xtts_v2",
            notes="XTTS Profile Preview Smoke",
            sample_paths=[sample],
        )
        profile_id = manifest.parent.name

        app = QApplication([])
        QMessageBox.information = staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Ok)
        QMessageBox.warning = staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Ok)

        window = MainWindow(paths)
        window.refresh_voice_profiles()
        profile_index = window.voice_profile_combo.findData(profile_id)
        if profile_index < 0:
            raise AssertionError(f"Expected XTTS profile {profile_id} in main window combo")
        window.voice_profile_combo.setCurrentIndex(profile_index)
        window.preview_xtts_reference()
        main_source = window.player.source().toLocalFile()
        if not main_source.endswith("xtts_preview_sample.wav"):
            raise AssertionError(f"Expected main window preview source to be the sample, got {main_source}")
        if "XTTS Preview Smoke" not in window.voice_profile_details.text():
            raise AssertionError(f"Missing profile details text: {window.voice_profile_details.text()}")

        dialog = FindBestSettingDialog(paths, window.manager, window)
        dialog.refresh_voice_profiles()
        profile_index = dialog.voice_profile_combo.findData(profile_id)
        if profile_index < 0:
            raise AssertionError(f"Expected XTTS profile {profile_id} in tuning dialog combo")
        backend_index = dialog.backend_combo.findText("xtts")
        dialog.backend_combo.setCurrentIndex(backend_index)
        dialog.voice_profile_combo.setCurrentIndex(profile_index)
        dialog.preview_xtts_reference()
        tuning_source = dialog.player.source().toLocalFile()
        if not tuning_source.endswith("xtts_preview_sample.wav"):
            raise AssertionError(f"Expected tuning preview source to be the sample, got {tuning_source}")

        voice_lab = VoiceLabDialog(paths, window)
        voice_lab.refresh_existing_profiles()
        voice_lab.profile_list.setCurrentRow(0)
        voice_lab.preview_selected_profile_sample()
        lab_source = voice_lab.player.source().toLocalFile()
        if not lab_source.endswith(".wav"):
            raise AssertionError(f"Expected voice lab sample preview source, got {lab_source}")

        print(
            json.dumps(
                {
                    "profile_id": profile_id,
                    "main_window_source": main_source,
                    "tuning_source": tuning_source,
                    "voice_lab_source": lab_source,
                },
                indent=2,
            )
        )
        voice_lab.close()
        dialog.close()
        window.close()
        app.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

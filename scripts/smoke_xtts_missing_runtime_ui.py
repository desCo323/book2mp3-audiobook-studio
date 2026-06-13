from __future__ import annotations

import json
import os
import tempfile
import wave
import struct
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox

from book2mp3.config import AppPaths
from book2mp3.preview_sessions import create_preview_session
from book2mp3.ui.find_best_setting_dialog import FindBestSettingDialog
from book2mp3.ui.main_window import MainWindow
from book2mp3.voice_lab import create_voice_profile


ROOT = Path("/home/codex/repo/book2mp3")


def _write_test_wav(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(22050)
        frames = [int(0.15 * 32767 * (1 if (i // 80) % 2 == 0 else -1)) for i in range(22050 // 2)]
        handle.writeframes(b"".join(struct.pack("<h", frame) for frame in frames))


def main() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    warnings: list[str] = []

    def remember_warning(_parent, title, message, *args, **kwargs):
        warnings.append(f"{title}: {message}")
        return QMessageBox.StandardButton.Ok

    with tempfile.TemporaryDirectory(prefix="book2mp3-smoke-xtts-missing-") as tmp_dir:
        app_root = Path(tmp_dir) / "src"
        paths = AppPaths.from_project_root(app_root)
        paths.ensure()

        source = app_root / "sample.txt"
        source.write_text("Das ist ein kurzer Text fuer den XTTS-Fehlerpfad.", encoding="utf-8")
        sample = app_root / "speaker.wav"
        _write_test_wav(sample)
        create_voice_profile(
            paths.voice_profiles,
            display_name="Missing Runtime Smoke",
            target_language="de",
            backend="xtts_v2",
            notes="smoke",
            sample_paths=[sample],
        )
        create_preview_session(paths, source)

        app = QApplication([])
        QMessageBox.warning = staticmethod(remember_warning)
        QMessageBox.information = staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Ok)

        window = MainWindow(paths)
        xtts_index = window.backend_combo.findText("xtts")
        if xtts_index >= 0:
            window.backend_combo.setCurrentIndex(xtts_index)
        if "XTTS runtime fehlt" not in "\n".join(warnings):
            raise AssertionError(f"Expected XTTS runtime warning in main window, got: {warnings}")

        dialog = FindBestSettingDialog(paths, window.manager, window)
        dialog.current_source = source
        dialog.create_session()
        profile_index = dialog.voice_profile_combo.findData("missing_runtime_smoke")
        if profile_index >= 0:
            dialog.voice_profile_combo.setCurrentIndex(profile_index)
        xtts_index = dialog.backend_combo.findText("xtts")
        if xtts_index >= 0:
            dialog.backend_combo.setCurrentIndex(xtts_index)
        dialog.render_and_play_preview()
        if dialog.preview_worker is not None:
            raise AssertionError("Preview worker should not start when XTTS runtime is missing")

        print(json.dumps({"warnings": warnings}, indent=2, ensure_ascii=False))
        dialog.close()
        window.close()
        app.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

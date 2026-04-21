from __future__ import annotations

import os
import shutil
import tempfile
import time
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox

from book2mp3.config import AppPaths
from book2mp3.ui.find_best_setting_dialog import FindBestSettingDialog, LivePreviewWorker
from book2mp3.ui.main_window import MainWindow
from book2mp3.voice_lab import create_voice_profile


ROOT = Path("/home/codex/repo/book2mp3")
APP_SRC_ROOT = ROOT / "src"


def ensure_runtime_fixture(app_root: Path) -> None:
    runtime_target = APP_SRC_ROOT / "runtime"
    runtime_link = app_root / "runtime"
    if not runtime_link.exists():
        runtime_link.symlink_to(runtime_target, target_is_directory=True)
    voices_target = ROOT / "voices"
    voices_link = app_root / "voices"
    if not voices_link.exists():
        voices_link.symlink_to(voices_target, target_is_directory=True)


class SlowPreviewWorker(LivePreviewWorker):
    def run(self) -> None:
        time.sleep(2.0)
        self.preview_finished.emit(self.session_id, "")


def main() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    with tempfile.TemporaryDirectory(prefix="book2mp3-smoke-preview-close-") as tmp_dir:
        app_root = Path(tmp_dir) / "src"
        app_root.mkdir(parents=True, exist_ok=True)
        ensure_runtime_fixture(app_root)
        paths = AppPaths.from_project_root(app_root)
        paths.ensure()

        sample = ROOT / "workspace" / "tmp_first_chunk.wav"
        create_voice_profile(
            paths.voice_profiles,
            display_name="XTTS Close Guard",
            target_language="de",
            backend="xtts_v2",
            notes="close guard",
            sample_paths=[sample],
        )

        app = QApplication([])
        QMessageBox.information = staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Ok)
        QMessageBox.warning = staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Ok)
        window = MainWindow(paths)
        window.maybe_start_next_job = lambda: None

        dialog = FindBestSettingDialog(paths, window.manager, window)
        dialog.show()
        app.processEvents()
        dialog.current_source = ROOT / "test.epub"
        dialog.create_session()
        if not dialog.current_session_id:
            raise AssertionError("Preview session was not created")

        dialog.preview_worker = SlowPreviewWorker(
            paths,
            dialog.current_session_id,
            "xtts",
            "",
            dialog.voice_profile_combo.currentData() or "",
            200,
            0.2,
            1.0,
        )
        dialog.preview_worker.preview_finished.connect(dialog.on_preview_finished)
        dialog.preview_worker.preview_failed.connect(dialog.on_preview_failed)
        dialog.preview_worker.finished.connect(dialog.cleanup_preview_worker)
        dialog.preview_worker.start()

        dialog.close()
        app.processEvents()
        if not dialog.isVisible() and dialog.preview_worker is not None:
            raise AssertionError("Dialog closed while preview worker was still running")

        deadline = time.time() + 10
        while dialog.preview_worker and time.time() < deadline:
            app.processEvents()
            time.sleep(0.1)

        if dialog.preview_worker is not None:
            raise AssertionError("Preview worker did not clean up after finishing")

        dialog.close()
        app.processEvents()
        print({"ok": True, "dialog_closed_after_preview": not dialog.isVisible()})
        window.close()
        app.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

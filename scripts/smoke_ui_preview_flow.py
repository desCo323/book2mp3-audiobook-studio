from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox

from book2mp3.config import AppPaths
from book2mp3.preview_sessions import list_preview_sessions
from book2mp3.ui.find_best_setting_dialog import FindBestSettingDialog
from book2mp3.ui.main_window import MainWindow


ROOT = Path("/home/codex/repo/book2mp3")


def main() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    with tempfile.TemporaryDirectory(prefix="book2mp3-smoke-ui-") as tmp_dir:
        app_root = Path(tmp_dir) / "src"
        app_root.mkdir(parents=True, exist_ok=True)
        shutil.copytree(ROOT / "runtime", app_root / "runtime", dirs_exist_ok=True)
        shutil.copytree(ROOT / "voices", app_root / "voices", dirs_exist_ok=True)
        paths = AppPaths.from_project_root(app_root)
        paths.ensure()

        app = QApplication([])
        QMessageBox.information = staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Ok)
        QMessageBox.warning = staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Ok)
        window = MainWindow(paths)
        window.refresh_voice_list()
        window.maybe_start_next_job = lambda: None

        voice_items = [window.voice_combo.itemText(i) for i in range(window.voice_combo.count())]
        if not voice_items or voice_items[0] == "No voices found":
            raise AssertionError(f"Expected installed voices, got: {voice_items}")

        dialog = FindBestSettingDialog(paths, window.manager, window)
        dialog.current_source = ROOT / "test.epub"
        dialog.create_session()
        if not dialog.current_session_id:
            raise AssertionError("Preview session was not created")

        dialog.assistant_combo.setCurrentIndex(0)
        dialog.apply_assistant_profile()
        session = {item.session_id: item for item in list_preview_sessions(paths)}[dialog.current_session_id]
        if not session.preview_excerpt:
            raise AssertionError("Preview session contains no excerpt")
        Path(session.preview_source_file).write_text(session.preview_excerpt[:280], encoding="utf-8")

        dialog.setting_name.setText("Smoke UI Voice")
        dialog.save_setting()
        dialog.render_and_play_preview()
        deadline = time.time() + 120
        while dialog.preview_worker and dialog.preview_worker.isRunning() and time.time() < deadline:
            app.processEvents()
            time.sleep(0.1)

        if dialog.preview_worker and dialog.preview_worker.isRunning():
            raise AssertionError("Live preview worker did not finish in time")

        updated_session = {item.session_id: item for item in list_preview_sessions(paths)}[dialog.current_session_id]
        preview_output = Path(updated_session.last_preview_output) if updated_session.last_preview_output else None
        if not preview_output or not preview_output.exists():
            raise AssertionError(f"Expected preview MP3, got session output: {updated_session.last_preview_output}")

        summary = {
            "voice_count": len(voice_items),
            "first_voice": voice_items[0],
            "selected_voice": window.voice_combo.currentData() or window.voice_combo.currentText(),
            "preview_session_id": session.session_id,
            "excerpt_length": len(session.preview_excerpt),
            "assistant_profile": dialog.assistant_combo.currentData(),
            "preview_status": updated_session.last_preview_status,
            "preview_output": str(preview_output),
        }
        print(json.dumps(summary, indent=2))
        window.close()
        dialog.close()
        app.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

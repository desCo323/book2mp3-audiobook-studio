from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox

from book2mp3.config import AppPaths
from book2mp3.ui.find_best_setting_dialog import FindBestSettingDialog
from book2mp3.ui.main_window import MainWindow
from book2mp3.voice_settings import PROFILE_STATUS_APPROVED, save_voice_setting


ROOT = Path("/home/codex/repo/book2mp3")


def ensure_fixture_link(app_root: Path, name: str) -> None:
    target = ROOT / name
    link = app_root / name
    if link.exists():
        return
    link.symlink_to(target, target_is_directory=True)


SOURCE_TEXT = """Kapitel 1
Die erste Werkhalle am Fluss war seit Jahren leer, aber jeden Freitag brannte dort eine einzige Lampe.

Kapitel 2
Als Lea den Schalter suchte, fand sie stattdessen eine Kiste mit alten Einsatzplänen der Maschinen.

Kapitel 3
Am Ende stellte sich heraus, dass der Nachtwächter die Halle offen hielt, damit niemand die Geschichten vergaß."""


def main() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    with tempfile.TemporaryDirectory(prefix="book2mp3-smoke-workflow-") as tmp_dir:
        app_root = Path(tmp_dir) / "src"
        app_root.mkdir(parents=True, exist_ok=True)
        ensure_fixture_link(app_root, "runtime")
        ensure_fixture_link(app_root, "voices")
        paths = AppPaths.from_project_root(app_root)
        paths.ensure()

        app = QApplication([])
        QMessageBox.information = staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Ok)
        QMessageBox.warning = staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Ok)
        QMessageBox.question = staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Yes)

        source = app_root / "workflow_story.txt"
        source.write_text(SOURCE_TEXT, encoding="utf-8")

        window = MainWindow(paths)
        window.maybe_start_next_job = lambda: None
        voice_id = window.voice_combo.itemData(0)
        if not voice_id:
            raise AssertionError("Expected at least one Piper voice for workflow smoke")

        approved_profile = save_voice_setting(
            paths.voice_settings,
            display_name="Workflow Smoke Profil",
            backend="piper",
            voice_id=voice_id,
            voice_profile_id="",
            preset_hint="balanced",
            max_chars=180,
            output_mode="chapter_files",
            target_part_minutes=15,
            sentence_silence=0.2,
            length_scale=1.0,
            status=PROFILE_STATUS_APPROVED,
            notes="UI workflow smoke profile",
        )
        window.refresh_saved_profiles()
        profile_index = window.saved_profile_combo.findData(approved_profile.setting_id)
        if profile_index < 0:
            raise AssertionError("Approved smoke profile missing from create-job combo")
        window.saved_profile_combo.setCurrentIndex(profile_index)
        window.source_edit.setText(str(source))
        window.create_job()
        state = window.manager.prepare_job(window.manager.load_state(window.current_job_id))
        window.show_job(state)
        if window.job_stage_list.count() < 3:
            raise AssertionError("Expected populated stage list for prepared job")
        if window.job_chapter_list.count() < 3:
            raise AssertionError("Expected populated chapter list for chaptered source")
        if window.job_chunk_list.count() < 3:
            raise AssertionError("Expected populated chunk list for prepared job")
        for index in range(min(2, window.job_chunk_list.count())):
            window.job_chunk_list.item(index).setSelected(True)
        window.retry_selected_chunks()
        retried_state = window.manager.load_state(state.job_id)
        if retried_state.status != "queued":
            raise AssertionError(f"Retry should requeue job, got {retried_state.status}")

        dialog = FindBestSettingDialog(paths, window.manager, window)
        dialog.current_source = source
        dialog.create_session()
        if dialog.test_mode_combo.currentData() != "assistant":
            raise AssertionError("Studio should default to guided assistant mode")
        if "Schritt" not in dialog.workflow_label.text():
            raise AssertionError("Workflow header did not render")
        dialog.start_voice_test_assistant()
        if dialog.voice_test_run is None or not dialog.voice_test_run.candidates:
            raise AssertionError("Assistant should create candidates")
        benchmark_index = dialog.test_mode_combo.findData("benchmark")
        dialog.test_mode_combo.setCurrentIndex(benchmark_index)
        dialog.start_benchmark_test_run()
        dialog.add_current_settings_to_test_run()
        if dialog.voice_test_run is None or not dialog.voice_test_run.candidates:
            raise AssertionError("Manual benchmark mode should accept current settings as candidates")
        if dialog.test_mode_stack.currentIndex() != 1:
            raise AssertionError("Benchmark mode should show benchmark page in the stack")

        print(
            json.dumps(
                {
                    "job_id": retried_state.job_id,
                    "chapter_count": len(retried_state.chapters),
                    "chunk_count": len(retried_state.chunks),
                    "studio_workflow_label": dialog.workflow_label.text(),
                    "assistant_candidates": len(dialog.voice_test_run.candidates),
                    "test_mode": dialog.test_mode_combo.currentData(),
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        dialog.close()
        window.close()
        app.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

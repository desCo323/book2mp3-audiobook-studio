from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox

from book2mp3.config import AppPaths
from book2mp3.service import Book2Mp3Service
from book2mp3.ui.find_best_setting_dialog import FindBestSettingDialog
from book2mp3.ui.main_window import MainWindow
from book2mp3.voice_settings import (
    PROFILE_STATUS_APPROVED,
    PROFILE_STATUS_TESTED,
    load_voice_setting,
)


ROOT = Path("/home/codex/repo/book2mp3")


def ensure_fixture_link(app_root: Path, name: str) -> None:
    target = ROOT / name
    link = app_root / name
    if link.exists():
        return
    link.symlink_to(target, target_is_directory=True)


def main() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    with tempfile.TemporaryDirectory(prefix="book2mp3-smoke-profile-") as tmp_dir:
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

        window = MainWindow(paths)
        window.maybe_start_next_job = lambda: None
        if window.xtts_backend.preferred_device_mode() == "cuda" and window.xtts_device_combo.currentData() != "cuda":
            raise AssertionError(f"Expected CUDA-first runtime selection, got {window.xtts_device_combo.currentData()!r}")
        tab_titles = [window.main_tabs.tabText(index) for index in range(window.main_tabs.count())]
        expected_tabs = {
            "Auftrag",
            "Produktionsprofile",
            "Benchmark-Studio",
            "XTTS-Profile",
            "Aufträge",
            "Diagnose",
            "Einstellungen",
        }
        if set(tab_titles) != expected_tabs:
            raise AssertionError(f"Unexpected main tabs: {tab_titles}")
        if "Arbeitsbereich:" not in window.diagnostics_summary.toPlainText():
            raise AssertionError("Diagnostics summary did not render in the main window")

        dialog = FindBestSettingDialog(paths, window.manager, window)
        studio_tabs = [dialog.studio_tabs.tabText(index) for index in range(dialog.studio_tabs.count())]
        expected_studio_tabs = {"Quelle", "Backend & Stimme", "Tuning", "Testreihe", "Produktionsprofil", "Preview"}
        if set(studio_tabs) != expected_studio_tabs:
            raise AssertionError(f"Unexpected profile studio tabs: {studio_tabs}")
        dialog.setting_name.setText("Studio Smoke Profil")
        dialog.save_setting_as_new()

        saved_id = dialog.current_saved_setting_id
        if not saved_id:
            raise AssertionError("Profile studio did not save a profile")
        saved = load_voice_setting(paths.voice_settings, saved_id)
        if saved.status != PROFILE_STATUS_TESTED:
            raise AssertionError(f"Expected tested profile after save, got {saved.status}")

        profile_index = dialog.saved_settings_combo.findData(saved_id)
        dialog.saved_settings_combo.setCurrentIndex(profile_index)
        dialog.set_saved_setting_status(PROFILE_STATUS_APPROVED)
        approved = load_voice_setting(paths.voice_settings, saved_id)
        if approved.status != PROFILE_STATUS_APPROVED:
            raise AssertionError(f"Expected approved profile after release, got {approved.status}")

        window.refresh_saved_profiles()
        if window.saved_profile_combo.findData(saved_id) < 0:
            raise AssertionError("Approved profile did not appear in job creation combo")

        source = app_root / "approved_profile_source.txt"
        source.write_text(("Dies ist ein Freigabe-Test. " * 40).strip(), encoding="utf-8")
        window.source_edit.setText(str(source))
        if window.job_output_chapter_radio.isEnabled():
            raise AssertionError("Chapter output should stay disabled for a flat text without detected chapter headings")
        window.saved_profile_combo.setCurrentIndex(window.saved_profile_combo.findData(saved_id))
        window.create_job()
        if not window.current_job_id:
            raise AssertionError("Main window did not create a job from approved profile")
        job = window.manager.load_state(window.current_job_id)
        if job.saved_profile_id != saved_id:
            raise AssertionError(f"Job did not keep approved profile id: {job.saved_profile_id}")
        if job.output_mode == "chapter_files":
            raise AssertionError("Job should not keep chapter_files when the selected source has no detected chapters")
        window.show_job(job)
        if "Stufen:" not in window.job_summary.toPlainText():
            raise AssertionError("Job summary did not include stage information")

        profiles = Book2Mp3Service(paths).list_saved_profiles()
        profile_payload = {entry["setting_id"]: entry for entry in profiles}
        if profile_payload[saved_id]["status"] != PROFILE_STATUS_APPROVED:
            raise AssertionError(f"Service profile status mismatch: {profile_payload[saved_id]}")

        print(
            json.dumps(
                {
                    "saved_profile_id": saved_id,
                    "saved_profile_status": approved.status,
                    "approved_profile_visible_in_job_dialog": window.saved_profile_combo.findData(saved_id) >= 0,
                    "chapter_output_enabled": window.job_output_chapter_radio.isEnabled(),
                    "job_id": job.job_id,
                    "job_profile_id": job.saved_profile_id,
                    "job_output_mode": job.output_mode,
                    "xtts_device_default": window.xtts_device_combo.currentData(),
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

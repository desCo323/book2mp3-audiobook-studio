from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox

from book2mp3.config import AppPaths
from book2mp3.pipeline.jobs import JobManager
from book2mp3.runtime_stats import record_runtime_stat
from book2mp3.ui.main_window import MainWindow
from book2mp3.voice_settings import PROFILE_STATUS_APPROVED, save_voice_setting


ROOT = Path("/home/codex/repo/book2mp3")


def ensure_fixture_link(app_root: Path, name: str) -> None:
    target = ROOT / name
    link = app_root / name
    if link.exists():
        return
    link.symlink_to(target, target_is_directory=True)


def main() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    with tempfile.TemporaryDirectory(prefix="book2mp3-smoke-bulk-") as tmp_dir:
        app_root = Path(tmp_dir) / "src"
        app_root.mkdir(parents=True, exist_ok=True)
        ensure_fixture_link(app_root, "runtime")
        ensure_fixture_link(app_root, "voices")
        paths = AppPaths.from_project_root(app_root)
        paths.ensure()

        record_runtime_stat(
            paths.runtime_stats_file,
            {
                "recorded_at": "2026-06-13T12:00:00+00:00",
                "job_id": "hist-001",
                "title": "Historischer Lauf",
                "backend": "piper",
                "saved_profile_id": "demo-profile",
                "voice_id": "de_DE-eva_k-x_low",
                "voice_profile_id": "",
                "device_mode": "cpu",
                "processing_mode": "serial",
                "output_mode": "single_file",
                "source_characters": 1200,
                "chunk_count": 6,
                "chapter_count": 1,
                "total_duration_seconds": 36.0,
                "synthesis_duration_seconds": 31.0,
                "assembly_duration_seconds": 5.0,
                "estimated_total_seconds": 36.0,
            },
        )

        profile = save_voice_setting(
            paths.voice_settings,
            display_name="Bulk Import Profil",
            backend="piper",
            voice_id="de_DE-eva_k-x_low",
            voice_profile_id="",
            preset_hint="balanced",
            max_chars=220,
            output_mode="chapter_files",
            target_part_minutes=15,
            sentence_silence=0.22,
            length_scale=1.0,
            status=PROFILE_STATUS_APPROVED,
            notes="Freigegeben für Bulk-Import-Smoke",
        )

        app = QApplication([])
        QMessageBox.information = staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Ok)
        QMessageBox.warning = staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Ok)
        QMessageBox.question = staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Yes)

        flat_source = app_root / "bulk_flat.txt"
        flat_source.write_text(("Dies ist ein Fließtext ohne Überschriften. " * 80).strip(), encoding="utf-8")
        chapter_source = app_root / "bulk_chapters.txt"
        chapter_source.write_text(
            "\n\n".join(
                [
                    "Kapitel 1\n" + ("Der Morgen war kühl. " * 30).strip(),
                    "Kapitel 2\n" + ("Die Werkstatt roch nach Holz. " * 30).strip(),
                    "Kapitel 3\n" + ("Abends wurde es still. " * 30).strip(),
                ]
            ),
            encoding="utf-8",
        )

        window = MainWindow(paths)
        window.maybe_start_next_job = lambda: None
        if window.xtts_processing_mode_combo.currentData() != "auto":
            raise AssertionError(f"Expected auto processing mode by default, got {window.xtts_processing_mode_combo.currentData()!r}")
        window.saved_profile_combo.setCurrentIndex(window.saved_profile_combo.findData(profile.setting_id))
        window.set_selected_source_files([flat_source, chapter_source])
        if window.source_list.count() != 2:
            raise AssertionError(f"Expected 2 source rows, got {window.source_list.count()}")
        if not window.job_output_chapter_radio.isEnabled():
            raise AssertionError("Chapter output should stay available when at least one selected source supports chapters.")
        window.job_output_chapter_radio.setChecked(True)
        window.create_job()

        jobs = JobManager(paths).list_jobs()
        if len(jobs) != 2:
            raise AssertionError(f"Expected 2 jobs after bulk import, got {len(jobs)}")
        by_name = {job.source_name: job for job in jobs}
        if by_name["bulk_flat.txt"].output_mode != "single_file":
            raise AssertionError(f"Flat text should fall back to single_file, got {by_name['bulk_flat.txt'].output_mode}")
        if by_name["bulk_chapters.txt"].output_mode != "chapter_files":
            raise AssertionError(f"Chapter text should keep chapter_files, got {by_name['bulk_chapters.txt'].output_mode}")
        if by_name["bulk_flat.txt"].estimated_total_seconds <= 0:
            raise AssertionError("Historical runtime estimate was not attached to queued job.")
        if "kumulierte Restzeit" not in window.queue_runtime_summary.text():
            raise AssertionError(f"Missing queue runtime summary text: {window.queue_runtime_summary.text()}")
        if "Gesamt-Restzeit" not in window.queue_eta_header.text():
            raise AssertionError(f"Missing queue ETA header text: {window.queue_eta_header.text()}")
        if window.jobs_list.count() < 1 or "ETA ca." not in window.jobs_list.item(0).text():
            raise AssertionError("Job list items do not show ETA text.")
        if "Runtime-Statistiken:" not in window.diagnostics_summary.toPlainText():
            raise AssertionError("Diagnostics summary did not include runtime statistics")

        print(
            json.dumps(
                {
                    "jobs_created": len(jobs),
                    "flat_output_mode": by_name["bulk_flat.txt"].output_mode,
                    "chapter_output_mode": by_name["bulk_chapters.txt"].output_mode,
                    "estimated_total_seconds": by_name["bulk_flat.txt"].estimated_total_seconds,
                    "source_list_rows": window.source_list.count(),
                    "queue_eta_header": window.queue_eta_header.text(),
                    "queue_runtime_summary": window.queue_runtime_summary.text(),
                    "first_job_label": window.jobs_list.item(0).text() if window.jobs_list.count() else "",
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        window.close()
        app.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

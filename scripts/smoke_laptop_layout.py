from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from PySide6.QtWidgets import QApplication

from book2mp3.config import AppPaths
from book2mp3.ui.find_best_setting_dialog import FindBestSettingDialog
from book2mp3.ui.main_window import MainWindow
from book2mp3.ui.voice_lab_dialog import VoiceLabDialog


ROOT = Path("/home/codex/repo/book2mp3")


def ensure_fixture_link(app_root: Path, name: str) -> None:
    target = ROOT / name
    link = app_root / name
    if link.exists():
        return
    link.symlink_to(target, target_is_directory=True)


def assert_widget_visible(widget, label: str) -> None:
    if widget.width() <= 0 or widget.height() <= 0:
        raise AssertionError(f"{label} is not visible: {widget.size()}")


def main() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    with tempfile.TemporaryDirectory(prefix="book2mp3-smoke-laptop-") as tmp_dir:
        app_root = Path(tmp_dir) / "src"
        app_root.mkdir(parents=True, exist_ok=True)
        ensure_fixture_link(app_root, "runtime")
        ensure_fixture_link(app_root, "voices")
        paths = AppPaths.from_project_root(app_root)
        paths.ensure()

        app = QApplication([])

        main_window = MainWindow(paths)
        main_window.resize(1366, 768)
        main_window.show()
        app.processEvents()
        assert main_window.width() <= 1366
        assert main_window.height() <= 768
        assert_widget_visible(main_window.jobs_list, "jobs_list")
        assert_widget_visible(main_window.source_list, "source_list")
        assert_widget_visible(main_window.job_chunk_list, "job_chunk_list")
        assert_widget_visible(main_window.xtts_processing_mode_combo, "xtts_processing_mode_combo")
        if main_window.job_chunk_list.parentWidget() is None:
            raise AssertionError("Chunk list lost its parent in the compact layout")

        benchmark_dialog = FindBestSettingDialog(paths, main_window.manager, main_window)
        benchmark_dialog.resize(1366, 768)
        benchmark_dialog.show()
        app.processEvents()
        assert benchmark_dialog.width() <= 1366
        assert benchmark_dialog.height() <= 768
        assert_widget_visible(benchmark_dialog.studio_tabs, "studio_tabs")
        assert_widget_visible(benchmark_dialog.details, "benchmark_details")

        voice_lab_dialog = VoiceLabDialog(paths, main_window)
        voice_lab_dialog.resize(1366, 768)
        voice_lab_dialog.show()
        app.processEvents()
        assert voice_lab_dialog.width() <= 1366
        assert voice_lab_dialog.height() <= 768
        assert_widget_visible(voice_lab_dialog.samples_list, "samples_list")
        assert_widget_visible(voice_lab_dialog.profile_list, "profile_list")
        assert_widget_visible(voice_lab_dialog.details, "voice_lab_details")

        print(
            json.dumps(
                {
                    "main_window": [main_window.width(), main_window.height()],
                    "benchmark_dialog": [benchmark_dialog.width(), benchmark_dialog.height()],
                    "voice_lab_dialog": [voice_lab_dialog.width(), voice_lab_dialog.height()],
                    "job_detail_layout": "tabbed",
                },
                indent=2,
            )
        )

        voice_lab_dialog.close()
        benchmark_dialog.close()
        main_window.close()
        app.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox

from book2mp3.app_settings import AppSettings, save_app_settings
from book2mp3.config import AppPaths
from book2mp3.service import Book2Mp3Service
from book2mp3.ui.main_window import MainWindow


ROOT = Path("/home/codex/repo/book2mp3")
ASYNC_RUNNER_ATTRS = (
    "_source_analysis_runner",
    "_metadata_runner",
    "_metadata_save_runner",
    "_metadata_search_runner",
    "_finished_metadata_runner",
    "_finished_metadata_search_runner",
    "_finished_metadata_save_runner",
    "_finished_metadata_redetect_runner",
    "_delete_job_runner",
    "_delete_finished_job_runner",
    "_diagnostics_runner",
)


def wait_for(app: QApplication, predicate, *, timeout_seconds: float = 10.0) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.05)
    app.processEvents()
    return predicate()


def window_async_idle(window: MainWindow) -> bool:
    return all(getattr(window, attr, None) is None for attr in ASYNC_RUNNER_ATTRS)


def ensure_fixture_link(app_root: Path, name: str) -> None:
    target = ROOT / name
    link = app_root / name
    if link.exists():
        return
    link.symlink_to(target, target_is_directory=True)


def main() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    with tempfile.TemporaryDirectory(prefix="book2mp3-smoke-i18n-meta-", dir="/home/codex") as tmp_dir:
        app_root = Path(tmp_dir) / "src"
        app_root.mkdir(parents=True, exist_ok=True)
        ensure_fixture_link(app_root, "runtime")
        ensure_fixture_link(app_root, "voices")
        paths = AppPaths.from_project_root(app_root)
        paths.ensure()
        save_app_settings(paths.app_settings_file, AppSettings(ui_language="en"))

        app = QApplication([])
        QMessageBox.information = staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Ok)
        QMessageBox.warning = staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Ok)
        QMessageBox.question = staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Yes)

        source = app_root / "Jane Austen - Pride and Prejudice.txt"
        source.write_text(("It is a truth universally acknowledged. " * 40).strip(), encoding="utf-8")

        service = Book2Mp3Service(paths)
        created = service.create_job(
            source_path=source,
            backend="piper",
            voice_id="en_US-lessac-medium",
            preset_id="balanced",
        )
        finished = service.run_job(str(created["job_id"]))

        window = MainWindow(paths)
        window.set_selected_source_files([source])
        window.refresh_jobs()
        wait_for(app, lambda: bool(window.meta_title_edit.text().strip()), timeout_seconds=10.0)

        if window.windowTitle() != "book2mp3 Audiobook Studio":
            raise AssertionError(f"Unexpected English window title: {window.windowTitle()!r}")
        if window.meta_title_edit.text() != "Pride and Prejudice":
            raise AssertionError(f"Metadata title guess failed: {window.meta_title_edit.text()!r}")
        if window.meta_author_edit.text() != "Jane Austen":
            raise AssertionError(f"Metadata author guess failed: {window.meta_author_edit.text()!r}")
        if window.jobs_list.count() != 0:
            raise AssertionError(f"Completed jobs must not stay in active jobs list: {window.jobs_list.count()}")
        if window.finished_books_list.count() < 1:
            raise AssertionError("Finished books overview stayed empty")
        if not any(window.main_tabs.tabText(index) == "Finished books" for index in range(window.main_tabs.count())):
            raise AssertionError("Finished books tab missing in English UI")

        first_item = window.finished_books_list.item(0)
        if "Pride and Prejudice" not in first_item.text():
            raise AssertionError(f"Finished books overview did not show metadata title: {first_item.text()!r}")
        window.finished_books_list.setCurrentRow(0)
        wait_for(app, lambda: bool(window.finished_meta_title_edit.text().strip()), timeout_seconds=5.0)
        if window.finished_meta_title_edit.text() != "Pride and Prejudice":
            raise AssertionError(f"Finished metadata editor did not load title: {window.finished_meta_title_edit.text()!r}")
        if window.finished_meta_author_edit.text() != "Jane Austen":
            raise AssertionError(f"Finished metadata editor did not load author: {window.finished_meta_author_edit.text()!r}")
        if not window.finished_metadata_redetect_button.isEnabled():
            raise AssertionError("Finished metadata re-detect button is not enabled for the selected finished book")
        if not window.finished_metadata_redetect_all_button.isEnabled():
            raise AssertionError("Finished metadata re-detect-all button is not enabled with finished books present")
        wait_for(app, lambda: window.finished_metadata_results_list.count() >= 1, timeout_seconds=10.0)
        if window.finished_metadata_results_list.count() < 1:
            raise AssertionError("Finished metadata suggestions list stayed empty")
        window.finished_meta_comment_edit.setPlainText("Test comment for final MP3 tags")
        window.save_finished_job_metadata()
        wait_for(
            app,
            lambda: service.manager.load_state(str(created["job_id"])).audiobook_metadata.comment
            == "Test comment for final MP3 tags",
            timeout_seconds=10.0,
        )
        refreshed = service.manager.load_state(str(created["job_id"]))
        if refreshed.audiobook_metadata.comment != "Test comment for final MP3 tags":
            raise AssertionError(
                f"Finished metadata save failed: {refreshed.audiobook_metadata.comment!r}"
            )

        print(
            json.dumps(
                {
                    "ui_language": window.ui_language,
                    "window_title": window.windowTitle(),
                    "metadata_title": window.meta_title_edit.text(),
                    "metadata_author": window.meta_author_edit.text(),
                    "active_jobs_count": window.jobs_list.count(),
                    "finished_books_count": window.finished_books_list.count(),
                    "finished_metadata_comment": refreshed.audiobook_metadata.comment,
                    "finished_job_status": finished["status"],
                },
                indent=2,
                ensure_ascii=False,
            )
        )

        wait_for(app, lambda: window_async_idle(window), timeout_seconds=10.0)
        window.close()
        app.processEvents()
        app.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

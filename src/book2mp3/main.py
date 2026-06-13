from __future__ import annotations

import os
import sys
from pathlib import Path
import time

from book2mp3.app_settings import load_app_settings
from PySide6.QtWidgets import QApplication

from book2mp3.config import AppPaths
from book2mp3.ui.main_window import MainWindow
from book2mp3.utils.logging_utils import configure_logging, get_logger
from book2mp3.utils.perf_logging import perf_event, perf_scope


def project_root() -> Path:
    configured_root = os.environ.get("BOOK2MP3_APP_ROOT", "").strip()
    if configured_root:
        return Path(configured_root).resolve()
    return Path(__file__).resolve().parents[2]


def main() -> int:
    with perf_scope("app_main", category="startup"):
        paths = AppPaths.from_project_root(project_root())
        with perf_scope("paths.ensure", category="startup", workspace=paths.workspace):
            repaired_paths = paths.ensure()
        with perf_scope("app_settings.load", category="startup", path=paths.app_settings_file):
            app_settings = load_app_settings(paths.app_settings_file)
        with perf_scope("logging.configure", category="startup", log_dir=paths.logs):
            configure_logging(paths.logs, debug_enabled=app_settings.debug_logging)
        logger = get_logger("main")
        launcher_started_ns = os.environ.get("BOOK2MP3_LAUNCHER_STARTED_AT_NS", "").strip()
        if launcher_started_ns.isdigit():
            perf_event(
                "launcher_to_main_gap",
                category="startup",
                duration_ms=round((time.time_ns() - int(launcher_started_ns)) / 1_000_000, 3),
            )
        for repaired_path in repaired_paths:
            logger.warning("Replaced unwritable workspace path with a fresh writable one: %s", repaired_path)
        logger.info("Starting book2mp3 application")
        with perf_scope("qt_application.create", category="startup"):
            app = QApplication(sys.argv)
        with perf_scope("main_window.create", category="startup"):
            window = MainWindow(paths)
        with perf_scope("main_window.show", category="startup"):
            window.show()
        perf_event("qt_event_loop.exec", category="startup")
        return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

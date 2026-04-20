from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from book2mp3.config import AppPaths
from book2mp3.ui.main_window import MainWindow
from book2mp3.utils.logging_utils import configure_logging, get_logger


def project_root() -> Path:
    configured_root = os.environ.get("BOOK2MP3_APP_ROOT", "").strip()
    if configured_root:
        return Path(configured_root).resolve()
    return Path(__file__).resolve().parents[2]


def main() -> int:
    paths = AppPaths.from_project_root(project_root())
    paths.ensure()
    configure_logging(paths.logs)
    logger = get_logger("main")
    logger.info("Starting book2mp3 application")
    app = QApplication(sys.argv)
    window = MainWindow(paths)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

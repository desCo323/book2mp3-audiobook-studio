from __future__ import annotations

import logging
from pathlib import Path


LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"


def configure_logging(log_dir: Path, debug_enabled: bool = True, force_reset: bool = False) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger("book2mp3")
    level = logging.DEBUG if debug_enabled else logging.INFO
    root.setLevel(level)
    if root.handlers and force_reset:
        for handler in list(root.handlers):
            handler.close()
            root.removeHandler(handler)
    if root.handlers:
        for handler in root.handlers:
            if isinstance(handler, logging.FileHandler):
                handler.setLevel(level)
            else:
                handler.setLevel(logging.INFO if debug_enabled else logging.WARNING)
        return root

    formatter = logging.Formatter(LOG_FORMAT)

    file_handler = logging.FileHandler(log_dir / "app.log", encoding="utf-8")
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO if debug_enabled else logging.WARNING)
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)

    root.debug("Application logging initialized")
    return root


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"book2mp3.{name}")


def attach_job_file_logger(job_id: str, job_dir: Path, debug_enabled: bool = True) -> logging.Logger:
    logger = logging.getLogger(f"book2mp3.job.{job_id}")
    logger.setLevel(logging.DEBUG if debug_enabled else logging.INFO)
    target = str(job_dir / "job.log")
    if not any(
        isinstance(handler, logging.FileHandler) and getattr(handler, "baseFilename", "") == target
        for handler in logger.handlers
    ):
        formatter = logging.Formatter(LOG_FORMAT)
        handler = logging.FileHandler(target, encoding="utf-8")
        handler.setLevel(logging.DEBUG if debug_enabled else logging.INFO)
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    else:
        for handler in logger.handlers:
            if isinstance(handler, logging.FileHandler):
                handler.setLevel(logging.DEBUG if debug_enabled else logging.INFO)
    return logger

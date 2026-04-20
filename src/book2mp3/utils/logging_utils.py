from __future__ import annotations

import logging
from pathlib import Path


LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"


def configure_logging(log_dir: Path) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger("book2mp3")
    if root.handlers:
        return root
    root.setLevel(logging.DEBUG)

    formatter = logging.Formatter(LOG_FORMAT)

    file_handler = logging.FileHandler(log_dir / "app.log", encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)

    root.debug("Application logging initialized")
    return root


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"book2mp3.{name}")


def attach_job_file_logger(job_id: str, job_dir: Path) -> logging.Logger:
    logger = logging.getLogger(f"book2mp3.job.{job_id}")
    logger.setLevel(logging.DEBUG)
    target = str(job_dir / "job.log")
    if not any(
        isinstance(handler, logging.FileHandler) and getattr(handler, "baseFilename", "") == target
        for handler in logger.handlers
    ):
        formatter = logging.Formatter(LOG_FORMAT)
        handler = logging.FileHandler(target, encoding="utf-8")
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    return logger

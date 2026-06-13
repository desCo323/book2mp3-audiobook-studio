from __future__ import annotations

import logging
import os
from pathlib import Path
import sys
import tempfile


LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"


def _build_file_handler(
    target: Path,
    level: int,
    formatter: logging.Formatter,
    fallback_name: str | None = None,
) -> tuple[logging.FileHandler | None, Path | None]:
    fallback_path = Path(tempfile.gettempdir()) / "book2mp3-logs" / (fallback_name or target.name)
    candidates = [target, fallback_path]
    for candidate in candidates:
        try:
            candidate.parent.mkdir(parents=True, exist_ok=True)
            handler = logging.FileHandler(candidate, encoding="utf-8")
            handler.setLevel(level)
            handler.setFormatter(formatter)
            return handler, candidate
        except PermissionError:
            if candidate == target and target.exists():
                try:
                    target.unlink()
                    handler = logging.FileHandler(target, encoding="utf-8")
                    handler.setLevel(level)
                    handler.setFormatter(formatter)
                    return handler, target
                except OSError:
                    pass
        except OSError:
            continue
    return None, None


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

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO if debug_enabled else logging.WARNING)
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)

    file_handler, file_path = _build_file_handler(log_dir / "app.log", level, formatter)
    if file_handler is not None:
        root.addHandler(file_handler)
    else:
        sys.stderr.write(
            "book2mp3: file logging unavailable, continuing with console-only logging\n"
        )

    root.debug("Application logging initialized")
    if file_path is not None and file_path != log_dir / "app.log":
        root.warning("Primary app log was not writable, using fallback log file %s", file_path)
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
        file_handler, file_path = _build_file_handler(
            Path(target),
            logging.DEBUG if debug_enabled else logging.INFO,
            formatter,
            fallback_name=f"job-{job_id}.log",
        )
        if file_handler is not None:
            logger.addHandler(file_handler)
            if file_path is not None and str(file_path) != target:
                logger.warning("Primary job log was not writable, using fallback log file %s", file_path)
        else:
            logger.warning("Job file logging unavailable for %s", job_id)
    else:
        for handler in logger.handlers:
            if isinstance(handler, logging.FileHandler):
                handler.setLevel(logging.DEBUG if debug_enabled else logging.INFO)
    return logger

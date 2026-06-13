from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
from typing import Any


def _timestamp_token() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")


def _is_writable_directory(path: Path) -> bool:
    return os.access(path, os.W_OK | os.X_OK)


def _is_writable_file(path: Path) -> bool:
    return os.access(path, os.W_OK)


def _quarantine_path(path: Path, reason: str, logger: logging.Logger | None = None) -> Path:
    suffix_base = f"{path.name}.{reason}-{_timestamp_token()}"
    candidate = path.with_name(suffix_base)
    counter = 1
    while candidate.exists():
        candidate = path.with_name(f"{suffix_base}-{counter}")
        counter += 1
    path.rename(candidate)
    if logger is not None:
        logger.warning("Workspace path quarantined: %s -> %s", path, candidate)
    return candidate


def ensure_writable_directory(path: Path, logger: logging.Logger | None = None) -> Path:
    if path.exists():
        if not path.is_dir():
            _quarantine_path(path, "invalid", logger=logger)
            path.mkdir(parents=True, exist_ok=True)
            return path
        if not _is_writable_directory(path):
            _quarantine_path(path, "readonly", logger=logger)
            path.mkdir(parents=True, exist_ok=True)
        return path
    parent = path.parent
    if parent != path:
        ensure_writable_directory(parent, logger=logger)
    path.mkdir(parents=True, exist_ok=True)
    return path


def prepare_writable_file(path: Path, logger: logging.Logger | None = None) -> Path:
    ensure_writable_directory(path.parent, logger=logger)
    if path.exists():
        if path.is_dir():
            _quarantine_path(path, "invalid", logger=logger)
        elif not _is_writable_file(path):
            _quarantine_path(path, "readonly", logger=logger)
    return path


def safe_write_text(
    path: Path,
    data: str,
    *,
    encoding: str = "utf-8",
    logger: logging.Logger | None = None,
) -> Path:
    try:
        prepare_writable_file(path, logger=logger)
        path.write_text(data, encoding=encoding)
        return path
    except OSError:
        prepare_writable_file(path, logger=logger)
        path.write_text(data, encoding=encoding)
        return path


def safe_write_json(
    path: Path,
    payload: dict[str, Any],
    *,
    logger: logging.Logger | None = None,
) -> Path:
    return safe_write_text(
        path,
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
        logger=logger,
    )

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
import itertools
import json
import os
from pathlib import Path
import sys
import threading
import tempfile
import time


_WRITE_LOCK = threading.Lock()
_SPAN_COUNTER = itertools.count(1)
_TARGET_CACHE: Path | None = None
_WRITE_DISABLED = False
_FALLBACK_WARNED = False
_DISABLED_WARNED = False


def _env_enabled() -> bool:
    value = os.environ.get("BOOK2MP3_PERF_LOG", "").strip().lower()
    return value not in {"", "0", "false", "no", "off"}


def is_perf_logging_enabled() -> bool:
    return _env_enabled()


def current_run_id() -> str:
    return os.environ.get("BOOK2MP3_PERF_RUN_ID", "").strip()


def perf_log_target_hint() -> Path | None:
    return _default_log_path()


def _default_log_path() -> Path | None:
    configured = os.environ.get("BOOK2MP3_PERF_LOG_FILE", "").strip()
    if configured:
        return Path(configured)
    app_root = os.environ.get("BOOK2MP3_APP_ROOT", "").strip()
    if app_root:
        return Path(app_root) / "workspace" / "logs" / "performance.jsonl"
    return None


def _fallback_log_path(primary: Path | None) -> Path:
    if primary is not None:
        stem = primary.stem
        suffix = primary.suffix or ".jsonl"
    else:
        stem = "performance"
        suffix = ".jsonl"
    run_id = current_run_id() or f"pid-{os.getpid()}"
    filename = f"{stem}-{run_id}{suffix}"
    return Path(tempfile.gettempdir()) / "book2mp3-logs" / filename


def _json_safe(value: object) -> object:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return str(value)


def _timestamp_token() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")


def _quarantine_unwritable_file(target: Path) -> bool:
    suffix_base = f"{target.name}.readonly-{_timestamp_token()}"
    candidate = target.with_name(suffix_base)
    counter = 1
    while candidate.exists():
        candidate = target.with_name(f"{suffix_base}-{counter}")
        counter += 1
    try:
        target.rename(candidate)
        return True
    except OSError:
        try:
            target.unlink()
            return True
        except OSError:
            return False


def _probe_writable_path(target: Path) -> bool:
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8"):
            pass
        return True
    except PermissionError:
        if target.exists() and _quarantine_unwritable_file(target):
            try:
                with target.open("a", encoding="utf-8"):
                    pass
                return True
            except OSError:
                return False
        return False
    except OSError:
        return False


def _warn_once(message: str, flag_name: str) -> None:
    global _FALLBACK_WARNED, _DISABLED_WARNED
    if flag_name == "fallback":
        if _FALLBACK_WARNED:
            return
        _FALLBACK_WARNED = True
    elif flag_name == "disabled":
        if _DISABLED_WARNED:
            return
        _DISABLED_WARNED = True
    sys.stderr.write(f"book2mp3: {message}\n")


def _resolve_target() -> Path | None:
    global _TARGET_CACHE, _WRITE_DISABLED
    if _WRITE_DISABLED:
        return None
    if _TARGET_CACHE is not None and _probe_writable_path(_TARGET_CACHE):
        return _TARGET_CACHE

    primary = _default_log_path()
    candidates: list[Path] = []
    if primary is not None:
        candidates.append(primary)
    candidates.append(_fallback_log_path(primary))

    for index, candidate in enumerate(candidates):
        if _probe_writable_path(candidate):
            _TARGET_CACHE = candidate
            if index > 0:
                _warn_once(
                    f"performance logging primary target unavailable, using fallback file {candidate}",
                    "fallback",
                )
            return candidate

    _WRITE_DISABLED = True
    _warn_once("performance logging unavailable, continuing without performance log file", "disabled")
    return None


def _write_record(record: dict[str, object]) -> None:
    if not is_perf_logging_enabled():
        return
    target = _resolve_target()
    if target is None:
        return
    line = json.dumps(record, ensure_ascii=False, sort_keys=True)
    with _WRITE_LOCK:
        try:
            with target.open("a", encoding="utf-8") as handle:
                handle.write(line)
                handle.write("\n")
        except OSError:
            global _TARGET_CACHE
            _TARGET_CACHE = None
            retry_target = _resolve_target()
            if retry_target is None:
                return
            try:
                with retry_target.open("a", encoding="utf-8") as handle:
                    handle.write(line)
                    handle.write("\n")
            except OSError:
                return


def perf_event(name: str, *, category: str = "app", **fields: object) -> None:
    if not is_perf_logging_enabled():
        return
    record = {
        "type": "event",
        "name": name,
        "category": category,
        "wall_time_utc": datetime.now(timezone.utc).isoformat(),
        "time_ns": time.perf_counter_ns(),
        "pid": os.getpid(),
        "thread_id": threading.get_ident(),
        "thread_name": threading.current_thread().name,
        "run_id": current_run_id(),
        "app_root": os.environ.get("BOOK2MP3_APP_ROOT", "").strip(),
        "fields": _json_safe(fields),
    }
    _write_record(record)


@contextmanager
def perf_scope(name: str, *, category: str = "app", **fields: object) -> Iterator[None]:
    if not is_perf_logging_enabled():
        yield
        return
    span_id = f"{os.getpid()}-{next(_SPAN_COUNTER)}"
    started_wall = datetime.now(timezone.utc).isoformat()
    started_ns = time.perf_counter_ns()
    perf_event(
        name,
        category=category,
        phase="start",
        span_id=span_id,
        started_wall=started_wall,
        **fields,
    )
    status = "ok"
    error_message = ""
    try:
        yield
    except Exception as exc:
        status = "error"
        error_message = str(exc)
        raise
    finally:
        finished_ns = time.perf_counter_ns()
        duration_ms = round((finished_ns - started_ns) / 1_000_000, 3)
        perf_event(
            name,
            category=category,
            phase="end",
            span_id=span_id,
            started_wall=started_wall,
            duration_ms=duration_ms,
            status=status,
            error=error_message,
            **fields,
        )

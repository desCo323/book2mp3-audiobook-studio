from __future__ import annotations

import json
import logging
import random
import shutil
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

from book2mp3.config import AppPaths
from book2mp3.models import utc_now
from book2mp3.pipeline.extract import extract_text
from book2mp3.utils.workspace_files import ensure_writable_directory, safe_write_json, safe_write_text


LOGGER = logging.getLogger("book2mp3.preview_sessions")


@dataclass
class PreviewSession:
    session_id: str
    title: str
    source_file: str
    extracted_file: str
    preview_source_file: str
    preview_excerpt: str
    excerpt_offset: int
    created_at: str
    updated_at: str
    backend: str = "piper"
    voice_id: str = ""
    voice_profile_id: str = ""
    preset_hint: str = "balanced"
    last_preview_job_id: str = ""
    last_preview_output: str = ""
    last_preview_status: str = "idle"
    saved_setting_id: str = ""


def _migrate_payload(payload: dict[str, object]) -> dict[str, object]:
    data = dict(payload)
    preview_excerpt = str(data.get("preview_excerpt", "") or "")
    preview_source_file = str(data.get("preview_source_file", "") or "")
    if not preview_excerpt and preview_source_file and Path(preview_source_file).exists():
        try:
            preview_excerpt = Path(preview_source_file).read_text(encoding="utf-8")
        except OSError:
            preview_excerpt = ""

    tests = data.get("tests", [])
    if not data.get("voice_id") and isinstance(tests, list) and tests:
        first = tests[0]
        if isinstance(first, dict):
            data["voice_id"] = first.get("voice_id", "")
            data["preset_hint"] = first.get("preset_id", data.get("preset_hint", "balanced"))
    if not data.get("last_preview_job_id") and isinstance(tests, list):
        completed = next(
            (
                item for item in tests
                if isinstance(item, dict) and item.get("job_id")
            ),
            None,
        )
        if completed:
            data["last_preview_job_id"] = completed.get("job_id", "")
            data["last_preview_output"] = completed.get("output_mp3", "")
            data["last_preview_status"] = completed.get("status", "idle")

    allowed = {
        "session_id": str(data.get("session_id", "")),
        "title": str(data.get("title", "")),
        "source_file": str(data.get("source_file", "")),
        "extracted_file": str(data.get("extracted_file", "")),
        "preview_source_file": preview_source_file,
        "preview_excerpt": preview_excerpt,
        "excerpt_offset": int(data.get("excerpt_offset", 0) or 0),
        "created_at": str(data.get("created_at", utc_now())),
        "updated_at": str(data.get("updated_at", data.get("created_at", utc_now()))),
        "backend": str(data.get("backend", "piper") or "piper"),
        "voice_id": str(data.get("voice_id", "") or ""),
        "voice_profile_id": str(data.get("voice_profile_id", "") or ""),
        "preset_hint": str(data.get("preset_hint", "balanced") or "balanced"),
        "last_preview_job_id": str(data.get("last_preview_job_id", "") or ""),
        "last_preview_output": str(data.get("last_preview_output", "") or ""),
        "last_preview_status": str(data.get("last_preview_status", "idle") or "idle"),
        "saved_setting_id": str(data.get("saved_setting_id", "") or ""),
    }
    return allowed


def _session_path(paths: AppPaths, session_id: str) -> Path:
    return paths.preview_sessions / session_id / "session.json"


def _load_session(paths: AppPaths, session_id: str) -> PreviewSession:
    payload = json.loads(_session_path(paths, session_id).read_text(encoding="utf-8"))
    migrated = _migrate_payload(payload)
    return PreviewSession(**migrated)


def _save_session(paths: AppPaths, session: PreviewSession) -> None:
    session_dir = paths.preview_sessions / session.session_id
    ensure_writable_directory(session_dir, logger=LOGGER)
    session.updated_at = utc_now()
    safe_write_json(_session_path(paths, session.session_id), asdict(session), logger=LOGGER)


def list_preview_sessions(paths: AppPaths) -> list[PreviewSession]:
    sessions: list[PreviewSession] = []
    for session_file in sorted(paths.preview_sessions.glob("*/session.json")):
        sessions.append(_load_session(paths, session_file.parent.name))
    return sorted(sessions, key=lambda item: item.updated_at, reverse=True)


def _sentence_windows(text: str, excerpt_chars: int) -> list[tuple[int, str]]:
    normalized = " ".join(text.split())
    if len(normalized) <= excerpt_chars:
        return [(0, normalized)]

    boundaries: list[int] = [0]
    for index, char in enumerate(normalized):
        if char in ".!?;:" and index + 1 < len(normalized):
            boundaries.append(index + 1)
    boundaries.append(len(normalized))
    boundaries = sorted(set(boundaries))

    windows: list[tuple[int, str]] = []
    for start in boundaries:
        if start >= len(normalized):
            continue
        end = min(len(normalized), start + excerpt_chars + 250)
        snippet = normalized[start:end].strip()
        if len(snippet) < min(350, excerpt_chars // 2):
            continue
        cut = len(snippet)
        for marker in [". ", "! ", "? ", "; ", ": "]:
            pos = snippet.rfind(marker, 0, min(len(snippet), excerpt_chars + 180))
            if pos > 280:
                cut = pos + 1
                break
        windows.append((start, snippet[:cut].strip()))
    return windows or [(0, normalized[:excerpt_chars].strip())]


def pick_random_excerpt(text: str, excerpt_chars: int = 1150, seed: int | None = None) -> tuple[int, str]:
    windows = _sentence_windows(text, excerpt_chars)
    rng = random.Random(seed)
    return rng.choice(windows)


def create_preview_session(paths: AppPaths, source_path: Path) -> PreviewSession:
    session_id = uuid.uuid4().hex[:12]
    session_dir = paths.preview_sessions / session_id
    ensure_writable_directory(session_dir, logger=LOGGER)

    source_copy = session_dir / "input" / source_path.name
    ensure_writable_directory(source_copy.parent, logger=LOGGER)
    shutil.copy2(source_path, source_copy)

    extracted = extract_text(source_copy)
    extracted_file = session_dir / "extracted.txt"
    safe_write_text(extracted_file, extracted, logger=LOGGER)

    offset, excerpt = pick_random_excerpt(extracted)
    preview_source = session_dir / "preview_source.txt"
    safe_write_text(preview_source, excerpt, logger=LOGGER)

    session = PreviewSession(
        session_id=session_id,
        title=f"{source_path.stem}_voice_tuning",
        source_file=str(source_copy),
        extracted_file=str(extracted_file),
        preview_source_file=str(preview_source),
        preview_excerpt=excerpt,
        excerpt_offset=offset,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    _save_session(paths, session)
    return session


def refresh_preview_excerpt(paths: AppPaths, session_id: str) -> PreviewSession:
    session = _load_session(paths, session_id)
    text = Path(session.extracted_file).read_text(encoding="utf-8")
    offset, excerpt = pick_random_excerpt(text)
    safe_write_text(Path(session.preview_source_file), excerpt, logger=LOGGER)
    session.preview_excerpt = excerpt
    session.excerpt_offset = offset
    session.last_preview_job_id = ""
    session.last_preview_output = ""
    session.last_preview_status = "idle"
    _save_session(paths, session)
    return session


def update_preview_excerpt_text(paths: AppPaths, session_id: str, excerpt: str) -> PreviewSession:
    session = _load_session(paths, session_id)
    normalized_excerpt = str(excerpt or "").strip()
    safe_write_text(Path(session.preview_source_file), normalized_excerpt, logger=LOGGER)
    session.preview_excerpt = normalized_excerpt
    session.last_preview_job_id = ""
    session.last_preview_output = ""
    session.last_preview_status = "idle"
    _save_session(paths, session)
    return session


def attach_preview_job(
    paths: AppPaths,
    session_id: str,
    backend: str,
    voice_id: str,
    voice_profile_id: str,
    preset_hint: str,
    job_id: str,
    output_mp3: str,
    status: str,
) -> PreviewSession:
    session = _load_session(paths, session_id)
    session.backend = backend
    session.voice_id = voice_id
    session.voice_profile_id = voice_profile_id
    session.preset_hint = preset_hint
    session.last_preview_job_id = job_id
    session.last_preview_output = output_mp3
    session.last_preview_status = status
    _save_session(paths, session)
    return session


def update_preview_selection(
    paths: AppPaths,
    session_id: str,
    backend: str,
    voice_id: str,
    voice_profile_id: str,
) -> PreviewSession:
    session = _load_session(paths, session_id)
    session.backend = backend
    session.voice_id = voice_id
    session.voice_profile_id = voice_profile_id
    _save_session(paths, session)
    return session


def link_saved_setting(paths: AppPaths, session_id: str, setting_id: str) -> PreviewSession:
    session = _load_session(paths, session_id)
    session.saved_setting_id = setting_id
    _save_session(paths, session)
    return session


def update_preview_job_status(
    paths: AppPaths,
    job_id: str,
    status: str,
    output_mp3: str | None = None,
) -> PreviewSession | None:
    for session in list_preview_sessions(paths):
        if session.last_preview_job_id == job_id:
            session.last_preview_status = status
            if output_mp3:
                session.last_preview_output = output_mp3
            _save_session(paths, session)
            return session
    return None

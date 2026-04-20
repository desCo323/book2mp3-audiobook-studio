from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from book2mp3.config import AppPaths
from book2mp3.pipeline.extract import extract_text
from book2mp3.presets import QUALITY_PRESETS, get_preset

PREFERRED_PREVIEW_VOICES = [
    "de_DE-eva_k-x_low",
    "de_DE-kerstin-low",
    "de_DE-ramona-low",
    "en_US-amy-medium",
    "en_US-kathleen-low",
    "en_GB-alba-medium",
    "en_GB-cori-medium",
    "fr_FR-siwis-low",
]


@dataclass
class PreviewCase:
    index: int
    label: str
    voice_id: str
    preset_id: str
    job_id: str = ""
    status: str = "planned"
    output_mp3: str = ""


@dataclass
class PreviewSession:
    session_id: str
    title: str
    source_file: str
    preview_source_file: str
    selected_case_index: int | None
    created_at: str
    tests: list[PreviewCase] = field(default_factory=list)


def _session_path(paths: AppPaths, session_id: str) -> Path:
    return paths.preview_sessions / session_id / "session.json"


def _load_session(paths: AppPaths, session_id: str) -> PreviewSession:
    payload = json.loads(_session_path(paths, session_id).read_text(encoding="utf-8"))
    payload["tests"] = [PreviewCase(**item) for item in payload.get("tests", [])]
    return PreviewSession(**payload)


def _save_session(paths: AppPaths, session: PreviewSession) -> None:
    session_dir = paths.preview_sessions / session.session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    payload = asdict(session)
    (_session_path(paths, session.session_id)).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def list_preview_sessions(paths: AppPaths) -> list[PreviewSession]:
    sessions: list[PreviewSession] = []
    for session_file in sorted(paths.preview_sessions.glob("*/session.json")):
        sessions.append(_load_session(paths, session_file.parent.name))
    return sorted(sessions, key=lambda item: item.created_at, reverse=True)


def _build_preview_text(text: str, approx_chars: int = 1800) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= approx_chars:
        return normalized
    end = approx_chars
    for marker in [". ", "! ", "? ", "; ", ": "]:
        pos = normalized.rfind(marker, 0, approx_chars + 400)
        if pos > 900:
            end = pos + 1
            break
    return normalized[:end].strip()


def _rank_voices(installed_voices: list[str]) -> list[str]:
    ranked: list[str] = []
    seen: set[str] = set()
    for voice in PREFERRED_PREVIEW_VOICES + installed_voices:
        if voice in installed_voices and voice not in seen:
            ranked.append(voice)
            seen.add(voice)
    return ranked


def build_sensible_preview_cases(installed_voices: list[str], max_tests: int = 10) -> list[PreviewCase]:
    voices = _rank_voices(installed_voices)
    presets = [preset.preset_id for preset in QUALITY_PRESETS]
    selected: list[PreviewCase] = []

    preferred_voice_count = min(3, len(voices))
    index = 1
    for voice_id in voices[:preferred_voice_count]:
        for preset_id in presets:
            if len(selected) >= max_tests:
                return selected
            preset = get_preset(preset_id)
            selected.append(
                PreviewCase(
                    index=index,
                    label=f"Test {index}: {voice_id} + {preset.label}",
                    voice_id=voice_id,
                    preset_id=preset_id,
                )
            )
            index += 1

    for voice_id in voices[preferred_voice_count:]:
        if len(selected) >= max_tests:
            break
        preset = get_preset("balanced")
        selected.append(
            PreviewCase(
                index=index,
                label=f"Test {index}: {voice_id} + {preset.label}",
                voice_id=voice_id,
                preset_id="balanced",
            )
        )
        index += 1
    return selected


def create_preview_session(paths: AppPaths, source_path: Path, installed_voices: list[str]) -> PreviewSession:
    session_id = uuid.uuid4().hex[:12]
    session_dir = paths.preview_sessions / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    source_copy = session_dir / "input" / source_path.name
    source_copy.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, source_copy)

    extracted = extract_text(source_copy)
    preview_text = _build_preview_text(extracted)
    preview_source = session_dir / "preview_source.txt"
    preview_source.write_text(preview_text, encoding="utf-8")

    session = PreviewSession(
        session_id=session_id,
        title=f"{source_path.stem}_preview",
        source_file=str(source_copy),
        preview_source_file=str(preview_source),
        selected_case_index=None,
        created_at=source_copy.stat().st_mtime_ns.__str__(),
        tests=build_sensible_preview_cases(installed_voices),
    )
    _save_session(paths, session)
    return session


def record_preview_job_result(
    paths: AppPaths, session_id: str, case_index: int, job_id: str, output_mp3: str, status: str
) -> PreviewSession:
    session = _load_session(paths, session_id)
    for item in session.tests:
        if item.index == case_index:
            item.job_id = job_id
            item.output_mp3 = output_mp3
            item.status = status
            break
    _save_session(paths, session)
    return session


def choose_preview_case(paths: AppPaths, session_id: str, case_index: int) -> PreviewSession:
    session = _load_session(paths, session_id)
    session.selected_case_index = case_index
    _save_session(paths, session)
    return session

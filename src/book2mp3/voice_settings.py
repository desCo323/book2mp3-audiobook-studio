from __future__ import annotations

import json
from dataclasses import asdict, dataclass
import os
from pathlib import Path

from book2mp3.models import utc_now

PROFILE_STATUS_DRAFT = "draft"
PROFILE_STATUS_TESTED = "tested"
PROFILE_STATUS_APPROVED = "approved"
PROFILE_STATUS_ARCHIVED = "archived"
VALID_PROFILE_STATUSES = {
    PROFILE_STATUS_DRAFT,
    PROFILE_STATUS_TESTED,
    PROFILE_STATUS_APPROVED,
    PROFILE_STATUS_ARCHIVED,
}


def normalize_profile_status(status: str | None) -> str:
    normalized = (status or "").strip().lower()
    if normalized in VALID_PROFILE_STATUSES:
        return normalized
    return PROFILE_STATUS_DRAFT


def profile_status_label(status: str) -> str:
    return {
        PROFILE_STATUS_DRAFT: "Entwurf",
        PROFILE_STATUS_TESTED: "Getestet",
        PROFILE_STATUS_APPROVED: "Freigegeben",
        PROFILE_STATUS_ARCHIVED: "Archiviert",
    }.get(normalize_profile_status(status), "Entwurf")


@dataclass
class VoiceSetting:
    setting_id: str
    display_name: str
    backend: str
    voice_id: str
    voice_profile_id: str
    preset_hint: str
    max_chars: int
    output_mode: str
    target_part_minutes: int
    sentence_silence: float
    length_scale: float
    created_at: str
    updated_at: str
    notes: str = ""
    status: str = PROFILE_STATUS_DRAFT
    approved_at: str = ""
    benchmark_average_ms: float = 0.0
    last_benchmark_ms: float = 0.0
    last_benchmark_at: str = ""
    source_session_id: str = ""
    source_run_id: str = ""
    source_candidate_id: str = ""

    @property
    def is_approved(self) -> bool:
        return normalize_profile_status(self.status) == PROFILE_STATUS_APPROVED


def _settings_dir(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    return root


def _setting_path(root: Path, setting_id: str) -> Path:
    return _settings_dir(root) / f"{setting_id}.json"


def sanitize_setting_id(name: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "_" for ch in name.strip())
    cleaned = "_".join(part for part in cleaned.split("_") if part)
    return cleaned or "voice_setting"


def ensure_unique_setting_id(root: Path, display_name: str) -> str:
    base = sanitize_setting_id(display_name)
    candidate = base
    counter = 2
    while _setting_path(root, candidate).exists():
        candidate = f"{base}_{counter}"
        counter += 1
    return candidate


def save_voice_setting(
    root: Path,
    display_name: str,
    backend: str,
    voice_id: str,
    voice_profile_id: str,
    preset_hint: str,
    max_chars: int,
    output_mode: str,
    target_part_minutes: int,
    sentence_silence: float,
    length_scale: float,
    notes: str = "",
    status: str | None = None,
    approved_at: str | None = None,
    benchmark_average_ms: float | None = None,
    last_benchmark_ms: float | None = None,
    last_benchmark_at: str | None = None,
    source_session_id: str | None = None,
    source_run_id: str | None = None,
    source_candidate_id: str | None = None,
    *,
    setting_id: str | None = None,
    ensure_unique_name: bool = False,
) -> VoiceSetting:
    resolved_setting_id = setting_id or sanitize_setting_id(display_name)
    if ensure_unique_name and setting_id is None:
        resolved_setting_id = ensure_unique_setting_id(root, display_name)
    now = utc_now()
    existing = (
        load_voice_setting(root, resolved_setting_id)
        if _setting_path(root, resolved_setting_id).exists()
        else None
    )
    resolved_status = normalize_profile_status(status or (existing.status if existing else PROFILE_STATUS_TESTED))
    resolved_approved_at = approved_at if approved_at is not None else (existing.approved_at if existing else "")
    if resolved_status == PROFILE_STATUS_APPROVED and not resolved_approved_at:
        resolved_approved_at = now
    if resolved_status != PROFILE_STATUS_APPROVED and status is not None and approved_at is None:
        resolved_approved_at = ""
    setting = VoiceSetting(
        setting_id=resolved_setting_id,
        display_name=display_name,
        backend=backend,
        voice_id=voice_id,
        voice_profile_id=voice_profile_id,
        preset_hint=preset_hint,
        max_chars=max_chars,
        output_mode=output_mode,
        target_part_minutes=target_part_minutes,
        sentence_silence=sentence_silence,
        length_scale=length_scale,
        created_at=existing.created_at if existing else now,
        updated_at=now,
        notes=notes,
        status=resolved_status,
        approved_at=resolved_approved_at,
        benchmark_average_ms=(
            benchmark_average_ms
            if benchmark_average_ms is not None
            else (existing.benchmark_average_ms if existing else 0.0)
        ),
        last_benchmark_ms=(
            last_benchmark_ms
            if last_benchmark_ms is not None
            else (existing.last_benchmark_ms if existing else 0.0)
        ),
        last_benchmark_at=(
            last_benchmark_at
            if last_benchmark_at is not None
            else (existing.last_benchmark_at if existing else "")
        ),
        source_session_id=(
            source_session_id
            if source_session_id is not None
            else (existing.source_session_id if existing else "")
        ),
        source_run_id=(
            source_run_id
            if source_run_id is not None
            else (existing.source_run_id if existing else "")
        ),
        source_candidate_id=(
            source_candidate_id
            if source_candidate_id is not None
            else (existing.source_candidate_id if existing else "")
        ),
    )
    target = _setting_path(root, resolved_setting_id)
    payload = json.dumps(asdict(setting), indent=2, ensure_ascii=False)
    try:
        target.write_text(payload, encoding="utf-8")
    except PermissionError:
        if target.exists():
            try:
                target.unlink()
            except OSError:
                pass
        try:
            target.write_text(payload, encoding="utf-8")
        except OSError:
            fallback = target.with_name(f"{target.stem}-{os.getpid()}{target.suffix}")
            fallback.write_text(payload, encoding="utf-8")
    return setting


def list_voice_settings(root: Path) -> list[VoiceSetting]:
    settings: list[VoiceSetting] = []
    for path in sorted(_settings_dir(root).glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload.setdefault("backend", "piper")
        payload.setdefault("voice_profile_id", "")
        payload.setdefault("output_mode", "single_file")
        payload.setdefault("target_part_minutes", 15)
        payload.setdefault("status", PROFILE_STATUS_APPROVED)
        payload.setdefault("approved_at", payload.get("updated_at", ""))
        payload.setdefault("benchmark_average_ms", 0.0)
        payload.setdefault("last_benchmark_ms", 0.0)
        payload.setdefault("last_benchmark_at", "")
        payload.setdefault("source_session_id", "")
        payload.setdefault("source_run_id", "")
        payload.setdefault("source_candidate_id", "")
        payload["status"] = normalize_profile_status(payload.get("status"))
        settings.append(VoiceSetting(**payload))
    return sorted(settings, key=lambda item: item.updated_at, reverse=True)


def load_voice_setting(root: Path, setting_id: str) -> VoiceSetting:
    payload = json.loads(_setting_path(root, setting_id).read_text(encoding="utf-8"))
    payload.setdefault("backend", "piper")
    payload.setdefault("voice_profile_id", "")
    payload.setdefault("output_mode", "single_file")
    payload.setdefault("target_part_minutes", 15)
    payload.setdefault("status", PROFILE_STATUS_APPROVED)
    payload.setdefault("approved_at", payload.get("updated_at", ""))
    payload.setdefault("benchmark_average_ms", 0.0)
    payload.setdefault("last_benchmark_ms", 0.0)
    payload.setdefault("last_benchmark_at", "")
    payload.setdefault("source_session_id", "")
    payload.setdefault("source_run_id", "")
    payload.setdefault("source_candidate_id", "")
    payload["status"] = normalize_profile_status(payload.get("status"))
    return VoiceSetting(**payload)


def update_voice_setting_status(root: Path, setting_id: str, status: str) -> VoiceSetting:
    existing = load_voice_setting(root, setting_id)
    normalized_status = normalize_profile_status(status)
    return save_voice_setting(
        root,
        display_name=existing.display_name,
        backend=existing.backend,
        voice_id=existing.voice_id,
        voice_profile_id=existing.voice_profile_id,
        preset_hint=existing.preset_hint,
        max_chars=existing.max_chars,
        output_mode=existing.output_mode,
        target_part_minutes=existing.target_part_minutes,
        sentence_silence=existing.sentence_silence,
        length_scale=existing.length_scale,
        notes=existing.notes,
        status=normalized_status,
        approved_at=existing.approved_at if normalized_status == PROFILE_STATUS_APPROVED else "",
        benchmark_average_ms=existing.benchmark_average_ms,
        last_benchmark_ms=existing.last_benchmark_ms,
        last_benchmark_at=existing.last_benchmark_at,
        source_session_id=existing.source_session_id,
        source_run_id=existing.source_run_id,
        source_candidate_id=existing.source_candidate_id,
        setting_id=existing.setting_id,
    )

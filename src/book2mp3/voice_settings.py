from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
import os
from pathlib import Path
from typing import Any

from book2mp3.i18n import resolve_ui_language
from book2mp3.models import utc_now
from book2mp3.xtts_options import (
    default_xtts_inference,
    normalize_pronunciation_rules,
    normalize_xtts_inference,
    normalize_xtts_quality_mode,
)

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
DEFAULT_RAMONA_SETTING_ID = "xtts1"
DEFAULT_RAMONA_VOICE_PROFILE_ID = "xtts_deutsch_weiblich_warm"
STANDARD_XTTS_SETTING_ID = DEFAULT_RAMONA_SETTING_ID
STANDARD_XTTS_DISPLAY_NAME = "Standard XTTS"
STANDARD_XTTS_PRESET_HINT = "premium_natural"
STANDARD_XTTS_MAX_CHARS = 130
STANDARD_XTTS_LENGTH_SCALE = 0.96
_DEFAULT_RAMONA_LEXICON_AUTHORS = {
    "G. A. Aiken",
    "Thea Harrison",
    "J. K. Rowling",
    "Sara Kylie Morrighan",
}
_DEFAULT_RAMONA_FALLBACK_RULES = [
    {"match": "G. A. Aiken", "spoken_as": "G A Eyken", "scope": "whole_phrase", "enabled": True},
    {"match": "G.A. Aiken", "spoken_as": "G A Eyken", "scope": "whole_phrase", "enabled": True},
    {"match": "Aiken, G. A.", "spoken_as": "G A Eyken", "scope": "whole_phrase", "enabled": True},
    {"match": "Sara Kylie Morrighan", "spoken_as": "Sara Morrigan", "scope": "whole_phrase", "enabled": True},
    {"match": "Conall Víga-Feilan", "spoken_as": "Konnal Wiga Feilan", "scope": "whole_phrase", "enabled": True},
    {"match": "Conall", "spoken_as": "Konnal", "scope": "whole_phrase", "enabled": True},
    {"match": "Víga-Feilan", "spoken_as": "Wiga Feilan", "scope": "whole_phrase", "enabled": True},
    {"match": "Nikolai Vorislav", "spoken_as": "Nikolai Worislaw", "scope": "whole_phrase", "enabled": True},
    {"match": "Nik Vorislav", "spoken_as": "Nikolai Worislaw", "scope": "whole_phrase", "enabled": True},
    {"match": "Aleksei Vorislav", "spoken_as": "Aleksei Worislaw", "scope": "whole_phrase", "enabled": True},
    {"match": "Bannik Vorislav", "spoken_as": "Bannik Worislaw", "scope": "whole_phrase", "enabled": True},
    {"match": "Annwyl", "spoken_as": "Annwil", "scope": "whole_phrase", "enabled": True},
    {"match": "Fearghus", "spoken_as": "Fergus", "scope": "whole_phrase", "enabled": True},
    {"match": "Briec", "spoken_as": "Briek", "scope": "whole_phrase", "enabled": True},
    {"match": "Iseabail", "spoken_as": "Isabehl", "scope": "whole_phrase", "enabled": True},
    {"match": "Dragos Cuelebre", "spoken_as": "Dragos Kuelebre", "scope": "whole_phrase", "enabled": True},
    {"match": "Cuelebre", "spoken_as": "Kuelebre", "scope": "whole_phrase", "enabled": True},
    {"match": "Newt Scamander", "spoken_as": "Njut Skamander", "scope": "whole_phrase", "enabled": True},
    {"match": "Cormoran Strike", "spoken_as": "Kormoran Streik", "scope": "whole_phrase", "enabled": True},
]
_DEFAULT_RAMONA_EXTRA_RULES = [
    {"match": "VgDDK", "spoken_as": "Verteidigung gegen die dunklen Künste", "scope": "whole_phrase", "enabled": True},
    {"match": "Rowena Ravenclaw", "spoken_as": "Rowena Räwenklo", "scope": "whole_phrase", "enabled": True},
    {"match": "Godric Gryffindor", "spoken_as": "Godrik Griffindor", "scope": "whole_phrase", "enabled": True},
    {"match": "Helga Hufflepuff", "spoken_as": "Helga Huffelpaff", "scope": "whole_phrase", "enabled": True},
    {"match": "Salazar Slytherin", "spoken_as": "Salazar Slisserin", "scope": "whole_phrase", "enabled": True},
    {"match": "Ariani ä Iriel", "spoken_as": "Ariani eh Iriel", "scope": "whole_phrase", "enabled": True},
    {"match": "Amelia Gryffindor", "spoken_as": "Amelia Griffindor", "scope": "whole_phrase", "enabled": True},
    {"match": "Rei Ishii", "spoken_as": "Rei Ischii", "scope": "whole_phrase", "enabled": True},
    {"match": "Talwyn", "spoken_as": "Tallwin", "scope": "whole_phrase", "enabled": True},
    {"match": "Talan", "spoken_as": "Talan", "scope": "whole_phrase", "enabled": True},
    {"match": "Izzy", "spoken_as": "Issi", "scope": "whole_phrase", "enabled": True},
    {"match": "Rhi", "spoken_as": "Rie", "scope": "whole_phrase", "enabled": True},
    {"match": "Éibhear", "spoken_as": "Eiwer", "scope": "whole_phrase", "enabled": True},
    {"match": "Eibhear", "spoken_as": "Eiwer", "scope": "whole_phrase", "enabled": True},
]


def standard_xtts_inference() -> dict[str, Any]:
    return {
        "temperature": 0.82,
        "top_p": 0.96,
        "top_k": 80,
        "repetition_penalty": 4.0,
        "length_penalty": 1.0,
        "num_beams": 1,
        "do_sample": True,
        "enable_text_splitting": False,
        "gpt_cond_len": 30,
        "gpt_cond_chunk_len": 6,
        "max_ref_length": 45,
        "sound_norm_refs": True,
        "librosa_trim_db": None,
    }


def normalize_profile_status(status: str | None) -> str:
    normalized = (status or "").strip().lower()
    if normalized in VALID_PROFILE_STATUSES:
        return normalized
    return PROFILE_STATUS_DRAFT


def profile_status_label(status: str, *, ui_language: str = "en") -> str:
    normalized = normalize_profile_status(status)
    labels = {
        "de": {
            PROFILE_STATUS_DRAFT: "Entwurf",
            PROFILE_STATUS_TESTED: "Getestet",
            PROFILE_STATUS_APPROVED: "Freigegeben",
            PROFILE_STATUS_ARCHIVED: "Archiviert",
        },
        "en": {
            PROFILE_STATUS_DRAFT: "Draft",
            PROFILE_STATUS_TESTED: "Tested",
            PROFILE_STATUS_APPROVED: "Approved",
            PROFILE_STATUS_ARCHIVED: "Archived",
        },
        "es": {
            PROFILE_STATUS_DRAFT: "Borrador",
            PROFILE_STATUS_TESTED: "Probado",
            PROFILE_STATUS_APPROVED: "Aprobado",
            PROFILE_STATUS_ARCHIVED: "Archivado",
        },
        "pt": {
            PROFILE_STATUS_DRAFT: "Rascunho",
            PROFILE_STATUS_TESTED: "Testado",
            PROFILE_STATUS_APPROVED: "Aprovado",
            PROFILE_STATUS_ARCHIVED: "Arquivado",
        },
    }
    bundle = labels.get(resolve_ui_language(ui_language), labels["en"])
    return bundle.get(normalized, bundle[PROFILE_STATUS_DRAFT])


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
    xtts_quality_mode: str = "fast"
    xtts_inference: dict[str, Any] = field(default_factory=dict)
    pronunciation_rules: list[dict[str, Any]] = field(default_factory=list)

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
    xtts_quality_mode: str | None = None,
    xtts_inference: dict[str, Any] | None = None,
    pronunciation_rules: list[dict[str, Any]] | None = None,
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
    resolved_quality_mode = normalize_xtts_quality_mode(
        xtts_quality_mode if xtts_quality_mode is not None else (existing.xtts_quality_mode if existing else "fast")
    )
    resolved_inference = normalize_xtts_inference(
        xtts_inference if xtts_inference is not None else (existing.xtts_inference if existing else None),
        quality_mode=resolved_quality_mode,
    )
    resolved_pronunciation_rules = normalize_pronunciation_rules(
        pronunciation_rules if pronunciation_rules is not None else (existing.pronunciation_rules if existing else [])
    )
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
        xtts_quality_mode=resolved_quality_mode,
        xtts_inference=resolved_inference,
        pronunciation_rules=resolved_pronunciation_rules,
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
        payload.setdefault("xtts_quality_mode", "fast")
        payload.setdefault("xtts_inference", {})
        payload.setdefault("pronunciation_rules", [])
        payload["status"] = normalize_profile_status(payload.get("status"))
        payload["xtts_quality_mode"] = normalize_xtts_quality_mode(payload.get("xtts_quality_mode"))
        payload["xtts_inference"] = normalize_xtts_inference(
            payload.get("xtts_inference"),
            quality_mode=payload["xtts_quality_mode"],
        )
        payload["pronunciation_rules"] = normalize_pronunciation_rules(payload.get("pronunciation_rules"))
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
    payload.setdefault("xtts_quality_mode", "fast")
    payload.setdefault("xtts_inference", {})
    payload.setdefault("pronunciation_rules", [])
    payload["status"] = normalize_profile_status(payload.get("status"))
    payload["xtts_quality_mode"] = normalize_xtts_quality_mode(payload.get("xtts_quality_mode"))
    payload["xtts_inference"] = normalize_xtts_inference(
        payload.get("xtts_inference"),
        quality_mode=payload["xtts_quality_mode"],
    )
    payload["pronunciation_rules"] = normalize_pronunciation_rules(payload.get("pronunciation_rules"))
    return VoiceSetting(**payload)


def ensure_standard_xtts_setting(root: Path, voice_profiles_root: Path) -> VoiceSetting | None:
    """Create or migrate the approved Standard XTTS production profile."""
    if not (voice_profiles_root / DEFAULT_RAMONA_VOICE_PROFILE_ID / "profile.json").exists():
        return None
    target_inference = normalize_xtts_inference(standard_xtts_inference(), quality_mode="max_quality")
    target_rules = _default_ramona_pronunciation_rules()
    if _setting_path(root, STANDARD_XTTS_SETTING_ID).exists():
        existing = load_voice_setting(root, STANDARD_XTTS_SETTING_ID)
        if (
            existing.display_name == STANDARD_XTTS_DISPLAY_NAME
            and existing.backend == "xtts"
            and existing.voice_id == "de_DE-ramona-low"
            and existing.voice_profile_id == DEFAULT_RAMONA_VOICE_PROFILE_ID
            and existing.preset_hint == STANDARD_XTTS_PRESET_HINT
            and existing.max_chars == STANDARD_XTTS_MAX_CHARS
            and existing.output_mode == "chapter_files"
            and existing.target_part_minutes == 20
            and existing.sentence_silence == 0.24
            and existing.length_scale == STANDARD_XTTS_LENGTH_SCALE
            and existing.status == PROFILE_STATUS_APPROVED
            and existing.xtts_quality_mode == "max_quality"
            and existing.xtts_inference == target_inference
            and existing.pronunciation_rules == target_rules
        ):
            return existing
    return save_voice_setting(
        root,
        display_name=STANDARD_XTTS_DISPLAY_NAME,
        backend="xtts",
        voice_id="de_DE-ramona-low",
        voice_profile_id=DEFAULT_RAMONA_VOICE_PROFILE_ID,
        preset_hint=STANDARD_XTTS_PRESET_HINT,
        max_chars=STANDARD_XTTS_MAX_CHARS,
        output_mode="chapter_files",
        target_part_minutes=20,
        sentence_silence=0.24,
        length_scale=STANDARD_XTTS_LENGTH_SCALE,
        notes=(
            "Approved Standard XTTS profile with expressive server parameters, tighter dense-name chunks "
            "and automatic fantasy-name pronunciation rules."
        ),
        status=PROFILE_STATUS_APPROVED,
        approved_at=None,
        xtts_quality_mode="max_quality",
        xtts_inference=target_inference,
        pronunciation_rules=target_rules,
        setting_id=STANDARD_XTTS_SETTING_ID,
    )


def seed_default_voice_settings(root: Path, voice_profiles_root: Path) -> list[VoiceSetting]:
    """Ensure the approved Standard XTTS profile exists when the Ramona voice profile is present."""
    existed = _setting_path(root, STANDARD_XTTS_SETTING_ID).exists()
    setting = ensure_standard_xtts_setting(root, voice_profiles_root)
    if setting is None or existed:
        return []
    return [setting]


def _default_ramona_pronunciation_rules() -> list[dict[str, Any]]:
    try:
        from book2mp3.metadata_extractor.lexicon import build_pronunciation_rules

        rules = build_pronunciation_rules(authors=_DEFAULT_RAMONA_LEXICON_AUTHORS)
    except Exception:
        rules = _DEFAULT_RAMONA_FALLBACK_RULES
    rules = [*rules, *_DEFAULT_RAMONA_EXTRA_RULES]
    return normalize_pronunciation_rules(
        rule
        for rule in rules
        if str(rule.get("match", "")).casefold() != str(rule.get("spoken_as", "")).casefold()
    )


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
        xtts_quality_mode=existing.xtts_quality_mode,
        xtts_inference=existing.xtts_inference,
        pronunciation_rules=existing.pronunciation_rules,
        setting_id=existing.setting_id,
    )

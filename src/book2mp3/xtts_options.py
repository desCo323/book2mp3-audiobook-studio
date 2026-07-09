from __future__ import annotations

import re
from typing import Any, Iterable

XTTS_QUALITY_FAST = "fast"
XTTS_QUALITY_QUALITY = "quality"
XTTS_QUALITY_MAX = "max_quality"
XTTS_QUALITY_MODES = {
    XTTS_QUALITY_FAST,
    XTTS_QUALITY_QUALITY,
    XTTS_QUALITY_MAX,
}
XTTS_SAFE_CHUNK_CHARS = 220
_XTTS_LANGUAGE_CHAR_LIMITS = {
    "de": 253,
}
_XTTS_DIALOG_TRANSLATION = str.maketrans(
    {
        "«": "",
        "»": "",
        "„": "",
        "“": "",
        "”": "",
        "‚": "",
        "‘": "",
        "’": "'",
    }
)

_QUALITY_DEFAULTS: dict[str, dict[str, Any]] = {
    XTTS_QUALITY_FAST: {
        "temperature": 0.75,
        "top_p": 0.85,
        "top_k": 50,
        "repetition_penalty": 10.0,
        "length_penalty": 1.0,
        "num_beams": 1,
        "do_sample": True,
        "enable_text_splitting": False,
        "gpt_cond_len": 30,
        "gpt_cond_chunk_len": 4,
        "max_ref_length": 30,
        "sound_norm_refs": False,
        "librosa_trim_db": None,
    },
    XTTS_QUALITY_QUALITY: {
        "temperature": 0.65,
        "top_p": 0.85,
        "top_k": 50,
        "repetition_penalty": 5.0,
        "length_penalty": 1.0,
        "num_beams": 2,
        "do_sample": True,
        "enable_text_splitting": False,
        "gpt_cond_len": 30,
        "gpt_cond_chunk_len": 4,
        "max_ref_length": 30,
        "sound_norm_refs": False,
        "librosa_trim_db": None,
    },
    XTTS_QUALITY_MAX: {
        "temperature": 0.60,
        "top_p": 0.85,
        "top_k": 50,
        "repetition_penalty": 5.0,
        "length_penalty": 1.0,
        "num_beams": 2,
        "do_sample": True,
        "enable_text_splitting": False,
        "gpt_cond_len": 30,
        "gpt_cond_chunk_len": 4,
        "max_ref_length": 30,
        "sound_norm_refs": False,
        "librosa_trim_db": None,
    },
}


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() not in {"", "0", "false", "no", "off"}
    return bool(value)


def normalize_xtts_quality_mode(mode: str | None) -> str:
    normalized = str(mode or "").strip().lower()
    if normalized in XTTS_QUALITY_MODES:
        return normalized
    return XTTS_QUALITY_FAST


def default_xtts_inference(mode: str | None) -> dict[str, Any]:
    return dict(_QUALITY_DEFAULTS[normalize_xtts_quality_mode(mode)])


def safe_xtts_chunk_chars(requested: int, language_code: str | None = "de") -> int:
    """Clamp XTTS text chunks below the model's per-language warning limit."""
    try:
        value = int(requested)
    except (TypeError, ValueError):
        value = XTTS_SAFE_CHUNK_CHARS
    value = max(1, value)
    code = str(language_code or "de").strip().lower().replace("-", "_").split("_", 1)[0]
    hard_limit = _XTTS_LANGUAGE_CHAR_LIMITS.get(code, XTTS_SAFE_CHUNK_CHARS + 10)
    safe_limit = max(80, min(XTTS_SAFE_CHUNK_CHARS, hard_limit - 13))
    return min(value, safe_limit)


def normalize_xtts_dialog_text(text: str) -> str:
    """Normalize dialogue punctuation before sending text to XTTS."""
    normalized = str(text or "").translate(_XTTS_DIALOG_TRANSLATION)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    normalized = re.sub(r"^\s*[\"']+\s*", "", normalized)
    normalized = re.sub(r"\s*[\"']+\s*$", "", normalized)
    return normalized


def normalize_xtts_inference(
    payload: dict[str, Any] | None,
    *,
    quality_mode: str | None = None,
) -> dict[str, Any]:
    base = default_xtts_inference(quality_mode)
    if not payload:
        return base
    normalized = dict(base)
    float_keys = ("temperature", "top_p", "repetition_penalty", "length_penalty")
    int_keys = ("top_k", "num_beams", "gpt_cond_len", "gpt_cond_chunk_len", "max_ref_length")
    for key in float_keys:
        if key in payload and payload[key] is not None:
            try:
                normalized[key] = float(payload[key])
            except (TypeError, ValueError):
                continue
    for key in int_keys:
        if key in payload and payload[key] is not None:
            try:
                normalized[key] = int(payload[key])
            except (TypeError, ValueError):
                continue
    if "do_sample" in payload:
        normalized["do_sample"] = _coerce_bool(payload["do_sample"])
    if "enable_text_splitting" in payload:
        normalized["enable_text_splitting"] = _coerce_bool(payload["enable_text_splitting"])
    if "sound_norm_refs" in payload:
        normalized["sound_norm_refs"] = _coerce_bool(payload["sound_norm_refs"])
    if "librosa_trim_db" in payload:
        librosa_trim_db = payload["librosa_trim_db"]
        if librosa_trim_db is None or librosa_trim_db == "":
            normalized["librosa_trim_db"] = None
        else:
            try:
                normalized["librosa_trim_db"] = float(librosa_trim_db)
            except (TypeError, ValueError):
                normalized["librosa_trim_db"] = None
    normalized["num_beams"] = max(1, int(normalized["num_beams"]))
    normalized["top_k"] = max(0, int(normalized["top_k"]))
    normalized["temperature"] = max(0.01, float(normalized["temperature"]))
    normalized["top_p"] = min(1.0, max(0.01, float(normalized["top_p"])))
    normalized["repetition_penalty"] = max(0.1, float(normalized["repetition_penalty"]))
    normalized["length_penalty"] = max(0.1, float(normalized["length_penalty"]))
    normalized["gpt_cond_len"] = max(1, min(30, int(normalized["gpt_cond_len"])))
    normalized["gpt_cond_chunk_len"] = max(1, min(int(normalized["gpt_cond_len"]), int(normalized["gpt_cond_chunk_len"])))
    normalized["max_ref_length"] = max(1, min(60, int(normalized["max_ref_length"])))
    if normalized["librosa_trim_db"] is not None:
        normalized["librosa_trim_db"] = max(1.0, min(80.0, float(normalized["librosa_trim_db"])))
    return normalized


def normalize_pronunciation_rules(
    rules: Iterable[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    normalized_rules: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str]] = set()
    for raw_rule in rules or []:
        match = " ".join(str(raw_rule.get("match", "") or "").split()).strip()
        spoken_as = " ".join(str(raw_rule.get("spoken_as", "") or "").split()).strip()
        if not match:
            continue
        if not spoken_as:
            spoken_as = match
        scope = str(raw_rule.get("scope", "whole_phrase") or "whole_phrase").strip().lower() or "whole_phrase"
        if scope not in {"whole_phrase"}:
            scope = "whole_phrase"
        enabled = bool(raw_rule.get("enabled", True))
        key = (match.casefold(), spoken_as.casefold())
        if key in seen_keys:
            continue
        seen_keys.add(key)
        normalized_rules.append(
            {
                "match": match,
                "spoken_as": spoken_as,
                "scope": scope,
                "enabled": enabled,
            }
        )
    return normalized_rules

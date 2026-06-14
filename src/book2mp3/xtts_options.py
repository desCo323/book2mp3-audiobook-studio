from __future__ import annotations

from typing import Any, Iterable

XTTS_QUALITY_FAST = "fast"
XTTS_QUALITY_QUALITY = "quality"
XTTS_QUALITY_MAX = "max_quality"
XTTS_QUALITY_MODES = {
    XTTS_QUALITY_FAST,
    XTTS_QUALITY_QUALITY,
    XTTS_QUALITY_MAX,
}

_QUALITY_DEFAULTS: dict[str, dict[str, Any]] = {
    XTTS_QUALITY_FAST: {
        "temperature": 0.75,
        "top_p": 0.85,
        "top_k": 50,
        "repetition_penalty": 10.0,
        "num_beams": 1,
        "do_sample": True,
    },
    XTTS_QUALITY_QUALITY: {
        "temperature": 0.60,
        "top_p": 0.80,
        "top_k": 40,
        "repetition_penalty": 8.0,
        "num_beams": 2,
        "do_sample": True,
    },
    XTTS_QUALITY_MAX: {
        "temperature": 0.55,
        "top_p": 0.75,
        "top_k": 30,
        "repetition_penalty": 8.0,
        "num_beams": 3,
        "do_sample": True,
    },
}


def normalize_xtts_quality_mode(mode: str | None) -> str:
    normalized = str(mode or "").strip().lower()
    if normalized in XTTS_QUALITY_MODES:
        return normalized
    return XTTS_QUALITY_FAST


def default_xtts_inference(mode: str | None) -> dict[str, Any]:
    return dict(_QUALITY_DEFAULTS[normalize_xtts_quality_mode(mode)])


def normalize_xtts_inference(
    payload: dict[str, Any] | None,
    *,
    quality_mode: str | None = None,
) -> dict[str, Any]:
    base = default_xtts_inference(quality_mode)
    if not payload:
        return base
    normalized = dict(base)
    float_keys = ("temperature", "top_p", "repetition_penalty")
    int_keys = ("top_k", "num_beams")
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
        normalized["do_sample"] = bool(payload["do_sample"])
    normalized["num_beams"] = max(1, int(normalized["num_beams"]))
    normalized["top_k"] = max(0, int(normalized["top_k"]))
    normalized["temperature"] = max(0.01, float(normalized["temperature"]))
    normalized["top_p"] = min(1.0, max(0.01, float(normalized["top_p"])))
    normalized["repetition_penalty"] = max(0.1, float(normalized["repetition_penalty"]))
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

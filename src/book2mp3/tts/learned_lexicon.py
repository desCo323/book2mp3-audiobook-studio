from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any

from book2mp3.models import utc_now
from book2mp3.tts.pronunciation import suggest_document_name_markers
from book2mp3.tts.pronunciation import spoken_hint
from book2mp3.xtts_options import normalize_pronunciation_rules


LEARNED_LEXICON_DIR = "learned_lexicon"
LEARNED_LEXICON_FILE = "xtts_names.json"
LEARNED_LEXICON_VERSION = 1
AUTO_RULE_MIN_CONFIDENCE = 0.82


def learned_lexicon_path(workspace: Path) -> Path:
    return Path(workspace) / LEARNED_LEXICON_DIR / LEARNED_LEXICON_FILE


def empty_learned_lexicon(*, reason: str = "reset") -> dict[str, Any]:
    now = utc_now()
    return {
        "version": LEARNED_LEXICON_VERSION,
        "created_at": now,
        "updated_at": now,
        "entries": {},
        "test_runs": [],
        "notes": [
            {
                "created_at": now,
                "reason": reason,
                "text": (
                    "Learning lexicon reset. Curated global_book_lexicon.json is untouched; "
                    "this file stores observed XTTS name, phonetic, and prosody hints."
                ),
            }
        ],
    }


def reset_learned_lexicon(workspace: Path, *, reason: str = "manual_reset") -> dict[str, Any]:
    payload = empty_learned_lexicon(reason=reason)
    save_learned_lexicon(workspace, payload)
    return payload


def load_learned_lexicon(workspace: Path) -> dict[str, Any]:
    path = learned_lexicon_path(workspace)
    if not path.exists():
        return empty_learned_lexicon(reason="implicit_empty")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty_learned_lexicon(reason="unreadable_existing_file")
    if not isinstance(payload, dict):
        return empty_learned_lexicon(reason="invalid_existing_file")
    payload.setdefault("version", LEARNED_LEXICON_VERSION)
    payload.setdefault("created_at", utc_now())
    payload.setdefault("updated_at", utc_now())
    payload.setdefault("entries", {})
    payload.setdefault("test_runs", [])
    payload.setdefault("notes", [])
    if not isinstance(payload["entries"], dict):
        payload["entries"] = {}
    if not isinstance(payload["test_runs"], list):
        payload["test_runs"] = []
    if not isinstance(payload["notes"], list):
        payload["notes"] = []
    return payload


def save_learned_lexicon(workspace: Path, payload: dict[str, Any]) -> None:
    path = learned_lexicon_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload["updated_at"] = utc_now()
    tmp_path = path.with_name(f"{path.stem}.{path.suffix}.tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def learn_name_observations(
    workspace: Path,
    text: str,
    *,
    source_id: str,
    source_kind: str,
    language_code: str = "de",
    existing_rules: list[dict[str, Any]] | None = None,
    min_occurrences: int = 1,
) -> dict[str, Any]:
    payload = load_learned_lexicon(workspace)
    entries = payload.setdefault("entries", {})
    markers = suggest_document_name_markers(
        text,
        existing_rules=existing_rules,
        limit=240,
        min_occurrences=min_occurrences,
    )
    now = utc_now()
    changed = 0
    for marker in markers:
        name = " ".join(str(marker.get("match", "") or "").split()).strip()
        if not name:
            continue
        key = _entry_key(name, language_code)
        estimate = estimate_name_phonetics(
            name,
            language_code=language_code,
            spoken_as=str(marker.get("spoken_as", "") or ""),
            source_reason=str(marker.get("reason", "") or ""),
            changes_spoken_text=bool(marker.get("changes_spoken_text", False)),
        )
        entry = entries.get(key)
        if not isinstance(entry, dict):
            entry = {
                "name": name,
                "language": language_code,
                "created_at": now,
                "status": "trusted" if estimate["confidence"] >= AUTO_RULE_MIN_CONFIDENCE else "candidate",
                "occurrences_total": 0,
                "sources": [],
                "candidates": [],
            }
        entry["name"] = name
        entry["language"] = language_code
        entry["updated_at"] = now
        entry["occurrences_total"] = int(entry.get("occurrences_total", 0) or 0) + int(marker.get("occurrences", 0) or 0)
        entry["last_seen_at"] = now
        entry["best"] = _merge_best_estimate(entry.get("best"), estimate)
        entry["status"] = _updated_status(str(entry.get("status", "candidate")), entry["best"])
        entry.setdefault("sources", []).append(
            {
                "source_id": source_id,
                "source_kind": source_kind,
                "seen_at": now,
                "occurrences": int(marker.get("occurrences", 0) or 0),
                "reason": str(marker.get("reason", "") or ""),
            }
        )
        entry["sources"] = entry["sources"][-20:]
        _append_candidate(entry, estimate)
        entries[key] = entry
        changed += 1
    if changed:
        save_learned_lexicon(workspace, payload)
    return {
        "path": str(learned_lexicon_path(workspace)),
        "observed_markers": len(markers),
        "updated_entries": changed,
        "entry_count": len(entries),
    }


def learned_pronunciation_rules(
    workspace: Path,
    source_text: str | None = None,
    *,
    min_confidence: float = AUTO_RULE_MIN_CONFIDENCE,
) -> list[dict[str, Any]]:
    payload = load_learned_lexicon(workspace)
    rules: list[dict[str, Any]] = []
    for entry in payload.get("entries", {}).values():
        if not isinstance(entry, dict):
            continue
        best = entry.get("best")
        if not isinstance(best, dict):
            continue
        name = str(entry.get("name", "") or "").strip()
        spoken_as = str(best.get("spoken_as", "") or "").strip()
        if not name or not spoken_as or name.casefold() == spoken_as.casefold():
            continue
        confidence = float(best.get("confidence", 0.0) or 0.0)
        status = str(entry.get("status", "candidate") or "candidate")
        if status not in {"trusted", "approved"} and confidence < min_confidence:
            continue
        if source_text and not _contains_name(source_text, name):
            continue
        rules.append(
            {
                "match": name,
                "spoken_as": spoken_as,
                "scope": "whole_phrase",
                "enabled": True,
            }
        )
    return normalize_pronunciation_rules(rules)


def record_test_run_evaluation(
    workspace: Path,
    evaluation: dict[str, Any],
    *,
    source_id: str,
) -> dict[str, Any]:
    payload = load_learned_lexicon(workspace)
    test_runs = payload.setdefault("test_runs", [])
    test_runs.append(
        {
            "source_id": source_id,
            "recorded_at": utc_now(),
            "evaluation": evaluation,
        }
    )
    payload["test_runs"] = test_runs[-50:]
    save_learned_lexicon(workspace, payload)
    return {
        "path": str(learned_lexicon_path(workspace)),
        "test_run_count": len(payload["test_runs"]),
    }


def estimate_name_phonetics(
    name: str,
    *,
    language_code: str = "de",
    spoken_as: str = "",
    source_reason: str = "",
    changes_spoken_text: bool = False,
) -> dict[str, Any]:
    normalized_name = " ".join(str(name or "").split()).strip()
    spoken = " ".join(str(spoken_as or "").split()).strip() or spoken_hint(normalized_name)
    ipa, ipa_source = _estimate_ipa(spoken or normalized_name, language_code=language_code)
    confidence = _estimate_confidence(
        source_reason=source_reason,
        has_ipa=bool(ipa),
        changes_spoken_text=changes_spoken_text or spoken.casefold() != normalized_name.casefold(),
    )
    return {
        "spoken_as": spoken or normalized_name,
        "ipa": ipa,
        "ipa_source": ipa_source,
        "confidence": confidence,
        "source_reason": source_reason or "name_marker",
        "prosody": _prosody_hint(spoken or normalized_name, language_code=language_code),
    }


def _entry_key(name: str, language_code: str) -> str:
    return f"{language_code.strip().lower() or 'de'}:{name.casefold()}"


def _merge_best_estimate(previous: Any, estimate: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(previous, dict):
        return dict(estimate)
    previous_confidence = float(previous.get("confidence", 0.0) or 0.0)
    next_confidence = float(estimate.get("confidence", 0.0) or 0.0)
    if next_confidence >= previous_confidence:
        return dict(estimate)
    return previous


def _updated_status(current: str, best: dict[str, Any]) -> str:
    if current == "approved":
        return current
    confidence = float(best.get("confidence", 0.0) or 0.0)
    if confidence >= AUTO_RULE_MIN_CONFIDENCE:
        return "trusted"
    return "candidate"


def _append_candidate(entry: dict[str, Any], estimate: dict[str, Any]) -> None:
    candidates = entry.setdefault("candidates", [])
    key = (
        str(estimate.get("spoken_as", "") or "").casefold(),
        str(estimate.get("ipa", "") or "").casefold(),
    )
    for candidate in candidates:
        if (
            str(candidate.get("spoken_as", "") or "").casefold(),
            str(candidate.get("ipa", "") or "").casefold(),
        ) == key:
            candidate["last_seen_at"] = utc_now()
            candidate["confidence"] = max(
                float(candidate.get("confidence", 0.0) or 0.0),
                float(estimate.get("confidence", 0.0) or 0.0),
            )
            return
    candidates.append({**estimate, "first_seen_at": utc_now(), "last_seen_at": utc_now()})
    entry["candidates"] = candidates[-12:]


def _estimate_confidence(*, source_reason: str, has_ipa: bool, changes_spoken_text: bool) -> float:
    confidence = 0.28
    if source_reason == "existing_pronunciation_rule":
        confidence = 0.84
    elif changes_spoken_text:
        confidence = 0.56
    if has_ipa:
        confidence += 0.08
    return round(min(0.95, confidence), 3)


def _prosody_hint(value: str, *, language_code: str) -> dict[str, Any]:
    tokens = [token for token in re.split(r"\s+", value.strip()) if token]
    syllables = sum(_rough_syllable_count(token) for token in tokens)
    return {
        "language": language_code,
        "syllable_count": syllables,
        "stress_hint": "first_content_syllable" if language_code.startswith("de") else "estimated",
        "name_emphasis": "light_focus",
        "pause_hint": "no_extra_pause",
    }


def _rough_syllable_count(token: str) -> int:
    groups = re.findall(r"[aeiouyäöüAEIOUYÄÖÜ]+", token)
    return max(1, len(groups))


def _estimate_ipa(value: str, *, language_code: str) -> tuple[str, str]:
    phonemizer_ipa = _phonemizer_ipa(value, language_code=language_code)
    if phonemizer_ipa:
        return phonemizer_ipa, "phonemizer"
    espeak_ipa = _espeak_ipa(value, language_code=language_code)
    if espeak_ipa:
        return espeak_ipa, "espeak"
    return "", "unavailable"


def _phonemizer_ipa(value: str, *, language_code: str) -> str:
    try:
        from phonemizer import phonemize
    except Exception:
        return ""
    try:
        result = phonemize(
            value,
            language=_phonemizer_language(language_code),
            backend="espeak",
            strip=True,
            preserve_punctuation=True,
            with_stress=True,
        )
    except Exception:
        return ""
    return " ".join(str(result or "").split()).strip()


def _espeak_ipa(value: str, *, language_code: str) -> str:
    executable = shutil.which("espeak-ng") or shutil.which("espeak")
    if not executable:
        return ""
    try:
        result = subprocess.run(
            [executable, "-q", "--ipa", "-v", _espeak_language(language_code), value],
            capture_output=True,
            text=True,
            timeout=8,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if result.returncode != 0:
        return ""
    return " ".join(result.stdout.split()).strip()


def _phonemizer_language(language_code: str) -> str:
    code = str(language_code or "de").strip().lower().replace("_", "-")
    if code.startswith("en"):
        return "en-us"
    if code.startswith("de"):
        return "de"
    return code.split("-", 1)[0] or "de"


def _espeak_language(language_code: str) -> str:
    return _phonemizer_language(language_code)


def _contains_name(text: str, name: str) -> bool:
    parts = [re.escape(part) for part in name.strip().split() if part]
    if not parts:
        return False
    pattern = r"(?<!\w)" + r"\s+".join(parts) + r"(?!\w)"
    return re.search(pattern, text, flags=re.IGNORECASE | re.UNICODE) is not None

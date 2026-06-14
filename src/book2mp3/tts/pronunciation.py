from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any

from book2mp3.xtts_options import normalize_pronunciation_rules

_PROTECTED_BLOCK_PATTERN = re.compile(
    r"(https?://\S+|www\.\S+|\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b)",
    re.IGNORECASE,
)
_NAME_CANDIDATE_PATTERN = re.compile(
    r"\b[A-ZÄÖÜ][A-Za-zÄÖÜäöüß'’\-]{2,}(?:\s+[A-ZÄÖÜ][A-Za-zÄÖÜäöüß'’\-]{2,})*\b"
)
_COMMON_NAME_WORDS = {
    "Kapitel",
    "Chapter",
    "Teil",
    "Prolog",
    "Epilog",
    "Audiobook",
    "Segment",
    "Gesamttext",
    "Dragon",
}


def spoken_hint(candidate: str) -> str:
    hinted = " ".join(str(candidate or "").split()).strip()
    if not hinted:
        return ""
    if "," in hinted:
        parts = [part.strip() for part in hinted.split(",") if part.strip()]
        if len(parts) >= 2:
            hinted = " ".join(parts[1:] + [parts[0]])
    hinted = hinted.replace("&", " and ")
    hinted = re.sub(r"\b([A-Za-zÄÖÜ])\.\s*(?=[A-Za-zÄÖÜ]\b|[A-Za-zÄÖÜ]\.)", r"\1 ", hinted)
    hinted = re.sub(r"\b([A-Za-zÄÖÜ])\.(?!\w)", r"\1", hinted)
    hinted = re.sub(r"[_/,;]+", " ", hinted)
    hinted = re.sub(r"[-]+", " ", hinted)
    hinted = hinted.replace("’", " ").replace("'", " ")
    hinted = re.sub(r"\s+", " ", hinted).strip()
    return hinted or str(candidate or "").strip()


@dataclass
class PronunciationTransformResult:
    spoken_text: str
    applied_rules: list[dict[str, Any]] = field(default_factory=list)
    applied_rule_count: int = 0
    applied_occurrences: int = 0


def _rule_pattern(match: str) -> re.Pattern[str]:
    escaped = re.escape(match)
    escaped = escaped.replace(r"\ ", r"\s+")
    return re.compile(rf"(?<!\w)({escaped})(?!\w)", re.IGNORECASE)


def apply_pronunciation_rules(
    text: str,
    rules: list[dict[str, Any]] | None,
) -> PronunciationTransformResult:
    normalized_rules = [
        rule
        for rule in normalize_pronunciation_rules(rules)
        if bool(rule.get("enabled", True))
    ]
    if not normalized_rules:
        return PronunciationTransformResult(spoken_text=text)
    ordered_rules = sorted(normalized_rules, key=lambda item: len(str(item["match"])), reverse=True)
    applied_rules: list[dict[str, Any]] = []
    applied_occurrences = 0
    pieces: list[str] = []
    cursor = 0
    for protected in _PROTECTED_BLOCK_PATTERN.finditer(text):
        if protected.start() > cursor:
            pieces.append(_apply_rules_to_segment(text[cursor:protected.start()], ordered_rules, applied_rules))
        pieces.append(protected.group(0))
        cursor = protected.end()
    if cursor < len(text):
        pieces.append(_apply_rules_to_segment(text[cursor:], ordered_rules, applied_rules))
    spoken_text = "".join(pieces)
    for item in applied_rules:
        applied_occurrences += int(item.get("occurrences", 0) or 0)
    return PronunciationTransformResult(
        spoken_text=spoken_text,
        applied_rules=applied_rules,
        applied_rule_count=len(applied_rules),
        applied_occurrences=applied_occurrences,
    )


def _apply_rules_to_segment(
    segment: str,
    rules: list[dict[str, Any]],
    applied_rules: list[dict[str, Any]],
) -> str:
    transformed = segment
    for rule in rules:
        pattern = _rule_pattern(str(rule["match"]))
        transformed, count = pattern.subn(str(rule["spoken_as"]), transformed)
        if count <= 0:
            continue
        applied_rules.append(
            {
                "match": str(rule["match"]),
                "spoken_as": str(rule["spoken_as"]),
                "scope": str(rule.get("scope", "whole_phrase")),
                "occurrences": count,
            }
        )
    return transformed


def suggest_pronunciation_candidates(
    text: str,
    *,
    existing_rules: list[dict[str, Any]] | None = None,
    limit: int = 16,
) -> list[dict[str, str]]:
    existing = {
        str(rule.get("match", "") or "").strip().casefold()
        for rule in normalize_pronunciation_rules(existing_rules)
    }
    seen: set[str] = set()
    suggestions: list[dict[str, str]] = []
    for match in _NAME_CANDIDATE_PATTERN.finditer(text):
        candidate = " ".join(match.group(0).split()).strip()
        folded = candidate.casefold()
        if not candidate or folded in existing or folded in seen:
            continue
        if candidate in _COMMON_NAME_WORDS:
            continue
        if len(candidate) < 4:
            continue
        seen.add(folded)
        suggestions.append(
            {
                "match": candidate,
                "spoken_as": spoken_hint(candidate),
                "reason": _suggestion_reason(candidate),
            }
        )
        if len(suggestions) >= max(1, limit):
            break
    return suggestions


def suggest_explicit_pronunciation_candidates(
    terms: list[str] | tuple[str, ...],
    *,
    existing_rules: list[dict[str, Any]] | None = None,
    limit: int = 12,
    reason: str = "explicit_name",
) -> list[dict[str, str]]:
    existing = {
        str(rule.get("match", "") or "").strip().casefold()
        for rule in normalize_pronunciation_rules(existing_rules)
    }
    suggestions: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw_term in terms:
        candidate = " ".join(str(raw_term or "").split()).strip()
        if not candidate:
            continue
        folded = candidate.casefold()
        if folded in existing or folded in seen:
            continue
        seen.add(folded)
        suggestions.append(
            {
                "match": candidate,
                "spoken_as": spoken_hint(candidate),
                "reason": reason,
            }
        )
        if len(suggestions) >= max(1, limit):
            break
    return suggestions


def _suggestion_reason(candidate: str) -> str:
    if "-" in candidate or "'" in candidate or "’" in candidate:
        return "hyphenated_or_apostrophe_name"
    if " " in candidate:
        return "multi_word_name"
    return "capitalized_name"

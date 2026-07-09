from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import re
import unicodedata
from typing import Any

from book2mp3.xtts_options import normalize_pronunciation_rules

_PROTECTED_BLOCK_PATTERN = re.compile(
    r"(https?://\S+|www\.\S+|\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b)",
    re.IGNORECASE,
)
_NAME_LETTERS = "A-Za-zÄÖÜäöüßÉéÁáÀàÂâÈèÊêÍíÌìÎîÓóÒòÔôÚúÙùÛûÇçÑñ"
_NAME_START_LETTERS = "A-ZÄÖÜÉÁÀÂÈÊÍÌÎÓÒÔÚÙÛÇÑ"
_NAME_CANDIDATE_PATTERN = re.compile(
    rf"\b[{_NAME_START_LETTERS}][{_NAME_LETTERS}'’\-]{{2,}}"
    rf"(?:\s+[{_NAME_START_LETTERS}][{_NAME_LETTERS}'’\-]{{2,}})*\b"
)
_COMMON_NAME_WORDS = {
    "Aber",
    "Abend",
    "Alle",
    "Alles",
    "Als",
    "Also",
    "Am",
    "An",
    "And",
    "Audiobook",
    "Auf",
    "Aus",
    "Bei",
    "Beim",
    "Bis",
    "Das",
    "Dass",
    "De",
    "Den",
    "Der",
    "Des",
    "Die",
    "Doch",
    "Donnerstag",
    "Dragon",
    "Drachen",
    "Diesmal",
    "Durch",
    "Ein",
    "Eine",
    "Einem",
    "Einen",
    "Einer",
    "Eines",
    "Epilog",
    "Er",
    "Es",
    "Eva",
    "Freitag",
    "Fuer",
    "Für",
    "Gebrüll",
    "Gesamttext",
    "Gestalt",
    "Greifen",
    "Gänsehaut",
    "Form",
    "Haar",
    "Hälfte",
    "Halsansatz",
    "Harpyie",
    "Heiliger",
    "Hell",
    "Heute",
    "Hohen",
    "Ich",
    "Kapitel",
    "Kein",
    "Keine",
    "Man",
    "Mit",
    "Mittwoch",
    "Montag",
    "Nach",
    "Noch",
    "Nun",
    "Oder",
    "Prolog",
    "Samstag",
    "Schon",
    "Segment",
    "Selbst",
    "Sie",
    "Silber",
    "Schäferhundmischling",
    "Sonntag",
    "Reiter",
    "Rücken",
    "Rüstung",
    "Überraschung",
    "Teil",
    "Tiergestalten",
    "Und",
    "Vom",
    "Von",
    "Vor",
    "Was",
    "Wenn",
    "Wer",
    "Wie",
    "Wir",
    "Viele",
    "Zähne",
    "Zügen",
    "Zum",
    "Zur",
    "Chapter",
}
_SPECIAL_SHORT_NAME_TOKENS = {
    "Wyr",
}
_FANTASY_SPOKEN_EXCEPTIONS = {
    "ainissesthai": "Anissestai",
    "aryal": "Arial",
    "bayne": "Beyn",
    "baynes": "Beyns",
    "beluviel": "Beluwiel",
    "caeravorn": "Keravorn",
    "calondir": "Kalondir",
    "calondirs": "Kalondirs",
    "carling": "Karling",
    "constantine": "Konstantin",
    "cuelebre": "Kuelebre",
    "eibhear": "Eiwer",
    "graydon": "Greydon",
    "grym": "Grimm",
    "hugh": "Hju",
    "irish": "Airisch",
    "james": "Dschehms",
    "johnny": "Dschonni",
    "miguel": "Migel",
    "quentin": "Kwentin",
    "rhoswen": "Roswen",
    "rune": "Rune",
    "runes": "Ruuns",
    "wolfhound": "Wolfhaund",
    "wyr": "Wier",
}
_GERMAN_DIACRITICS = str.maketrans(
    {
        "Ä": "Ae",
        "Ö": "Oe",
        "Ü": "Ue",
        "ä": "ae",
        "ö": "oe",
        "ü": "ue",
        "ß": "ss",
    }
)
_NAME_TOKEN_RE = re.compile(rf"[{_NAME_LETTERS}]+")


def spoken_hint(candidate: str) -> str:
    return _fantasy_spoken_hint(_basic_spoken_hint(candidate))


def _basic_spoken_hint(candidate: str) -> str:
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
    hinted = _strip_non_german_diacritics(hinted)
    hinted = re.sub(r"\s+", " ", hinted).strip()
    return hinted or str(candidate or "").strip()


def _fantasy_spoken_hint(value: str) -> str:
    hinted = " ".join(str(value or "").split()).strip()
    if not hinted:
        return ""
    tokens = hinted.split()
    spoken_tokens = [_fantasy_token_spoken_hint(token) for token in tokens]
    return " ".join(token for token in spoken_tokens if token).strip() or hinted


def _fantasy_token_spoken_hint(token: str) -> str:
    raw = str(token or "").strip()
    if not raw:
        return ""
    prefix_match = re.match(r"^[^A-Za-zÄÖÜäöüßÉéÁáÀàÂâÈèÊêÍíÌìÎîÓóÒòÔôÚúÙùÛûÇçÑñ]+", raw)
    suffix_match = re.search(r"[^A-Za-zÄÖÜäöüßÉéÁáÀàÂâÈèÊêÍíÌìÎîÓóÒòÔôÚúÙùÛûÇçÑñ]+$", raw)
    prefix = prefix_match.group(0) if prefix_match else ""
    suffix = suffix_match.group(0) if suffix_match else ""
    core = raw[len(prefix): len(raw) - len(suffix) if suffix else len(raw)]
    if not core:
        return raw
    folded = core.casefold()
    explicit = _FANTASY_SPOKEN_EXCEPTIONS.get(folded)
    if explicit:
        return f"{prefix}{explicit}{suffix}"

    transformed = core
    replacements = (
        (r"(?i)^qu", "Kw"),
        (r"(?i)^caer", "Ker"),
        (r"(?i)^cue", "Kue"),
        (r"(?i)^car", "Kar"),
        (r"(?i)^cal", "Kal"),
        (r"(?i)^con", "Kon"),
        (r"(?i)^rh", "R"),
        (r"(?i)^ph", "F"),
        (r"(?i)gray", "Grey"),
        (r"(?i)bay", "Bey"),
        (r"(?i)gh$", ""),
        (r"(?i)ph", "f"),
        (r"(?i)th", "t"),
        (r"(?i)c(?=[aouAOU])", "K"),
        (r"(?i)c(?=[eiEI])", "S"),
    )
    for pattern, replacement in replacements:
        transformed = re.sub(pattern, replacement, transformed)
    return f"{prefix}{transformed}{suffix}"


def _strip_non_german_diacritics(value: str) -> str:
    protected = value.translate(_GERMAN_DIACRITICS)
    normalized = unicodedata.normalize("NFKD", protected)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


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


def suggest_document_pronunciation_rules(
    text: str,
    *,
    seed_terms: list[str] | tuple[str, ...] | None = None,
    existing_rules: list[dict[str, Any]] | None = None,
    limit: int = 80,
    min_occurrences: int = 2,
) -> list[dict[str, str]]:
    existing = {
        str(rule.get("match", "") or "").strip().casefold()
        for rule in normalize_pronunciation_rules(existing_rules)
    }
    suggestions: list[dict[str, str]] = []
    seen: set[str] = set(existing)

    for suggestion in suggest_explicit_pronunciation_candidates(
        list(seed_terms or []),
        existing_rules=existing_rules,
        limit=24,
        reason="metadata_or_heading_name",
    ):
        _append_name_suggestion(suggestions, suggestion, seen, limit)

    counts: Counter[str] = Counter()
    canonical: dict[str, str] = {}
    for raw_candidate in _iter_name_candidates(text):
        candidate = _clean_name_candidate(raw_candidate)
        if not _is_document_name_candidate(candidate):
            continue
        folded = candidate.casefold()
        counts[folded] += 1
        canonical.setdefault(folded, candidate)
        for token in _interesting_name_tokens(candidate):
            token_folded = token.casefold()
            counts[token_folded] += 1
            canonical.setdefault(token_folded, token)

    ranked = sorted(
        canonical.items(),
        key=lambda item: (_candidate_priority(item[1], counts[item[0]]), counts[item[0]], len(item[1])),
        reverse=True,
    )
    for folded, candidate in ranked:
        if folded in seen:
            continue
        occurrences = counts[folded]
        if occurrences < max(1, min_occurrences) and not _name_has_strong_signal(candidate):
            continue
        _append_name_suggestion(
            suggestions,
            {
                "match": candidate,
                "spoken_as": spoken_hint(candidate),
                "reason": _suggestion_reason(candidate),
            },
            seen,
            limit,
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


def _iter_name_candidates(text: str) -> list[str]:
    pieces: list[str] = []
    cursor = 0
    for protected in _PROTECTED_BLOCK_PATTERN.finditer(text):
        if protected.start() > cursor:
            pieces.extend(match.group(0) for match in _NAME_CANDIDATE_PATTERN.finditer(text[cursor:protected.start()]))
        cursor = protected.end()
    if cursor < len(text):
        pieces.extend(match.group(0) for match in _NAME_CANDIDATE_PATTERN.finditer(text[cursor:]))
    return pieces


def _clean_name_candidate(candidate: str) -> str:
    return " ".join(str(candidate or "").replace("’", "'").split()).strip(" ,.;:!?()[]{}\"")


def _is_document_name_candidate(candidate: str) -> bool:
    tokens = _NAME_TOKEN_RE.findall(candidate)
    has_special_short_token = any(token in _SPECIAL_SHORT_NAME_TOKENS for token in tokens)
    if (len(candidate) < 4 and not has_special_short_token) or len(candidate) > 80:
        return False
    if not tokens:
        return False
    if all(token in _COMMON_NAME_WORDS for token in tokens):
        return False
    if len(tokens) == 1 and tokens[0] in _COMMON_NAME_WORDS:
        return False
    return any(
        (len(token) >= 4 or token in _SPECIAL_SHORT_NAME_TOKENS)
        and token not in _COMMON_NAME_WORDS
        for token in tokens
    )


def _interesting_name_tokens(candidate: str) -> list[str]:
    raw_tokens = _NAME_TOKEN_RE.findall(candidate)
    tokens = [
        token
        for token in raw_tokens
        if (len(token) >= 4 or token in _SPECIAL_SHORT_NAME_TOKENS)
        and token not in _COMMON_NAME_WORDS
    ]
    if len(raw_tokens) <= 1:
        return []
    return tokens


def _name_has_strong_signal(candidate: str) -> bool:
    if any(marker in candidate for marker in ("-", "'", "’")):
        return True
    basic_hint = _basic_spoken_hint(candidate)
    fantasy_hint = _fantasy_spoken_hint(basic_hint)
    if fantasy_hint.casefold() != basic_hint.casefold():
        return True
    if _strip_non_german_diacritics(candidate) != candidate.translate(_GERMAN_DIACRITICS):
        return True
    tokens = _NAME_TOKEN_RE.findall(candidate)
    return len(tokens) >= 2


def _candidate_priority(candidate: str, occurrences: int) -> int:
    score = min(occurrences, 8)
    if _name_has_strong_signal(candidate):
        score += 5
    if " " in candidate:
        score += 3
    return score


def _append_name_suggestion(
    suggestions: list[dict[str, str]],
    suggestion: dict[str, str],
    seen: set[str],
    limit: int,
) -> None:
    if len(suggestions) >= max(1, limit):
        return
    match = _clean_name_candidate(str(suggestion.get("match", "") or ""))
    if not match:
        return
    if _is_common_noun_phrase(match):
        return
    folded = match.casefold()
    if folded in seen or not _is_document_name_candidate(match):
        return
    seen.add(folded)
    spoken_as = " ".join(str(suggestion.get("spoken_as", "") or spoken_hint(match)).split()).strip() or match
    if spoken_as.casefold() == match.casefold():
        return
    if _is_low_value_spoken_hint(match, spoken_as):
        return
    suggestions.append(
        {
            "match": match,
            "spoken_as": spoken_as,
            "scope": "whole_phrase",
            "enabled": True,
            "reason": str(suggestion.get("reason", "") or _suggestion_reason(match)),
        }
    )


def _is_common_noun_phrase(candidate: str) -> bool:
    tokens = _NAME_TOKEN_RE.findall(candidate)
    if len(tokens) <= 1:
        return False
    if any(token in _COMMON_NAME_WORDS for token in tokens):
        return True
    return False


def _is_low_value_spoken_hint(match: str, spoken_as: str) -> bool:
    basic_hint = _basic_spoken_hint(match)
    fantasy_hint = _fantasy_spoken_hint(basic_hint)
    if fantasy_hint.casefold() != basic_hint.casefold():
        return False
    return spoken_as.casefold() == basic_hint.casefold()

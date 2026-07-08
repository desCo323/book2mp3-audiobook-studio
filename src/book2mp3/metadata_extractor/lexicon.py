from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
import unicodedata
from typing import Any

from ebooklib import ITEM_DOCUMENT, epub
from pypdf import PdfReader

from book2mp3.xtts_options import (
    XTTS_QUALITY_MAX,
    default_xtts_inference,
    normalize_pronunciation_rules,
)


DEFAULT_LEXICON_FILENAME = "global_book_lexicon.json"


def default_lexicon_path() -> Path:
    return Path(__file__).with_name(DEFAULT_LEXICON_FILENAME)


def load_global_lexicon(path: str | Path | None = None) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve() if path else default_lexicon_path()
    payload = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Lexicon root must be a JSON object")
    return payload


def iter_lexicon_entries(payload: dict[str, Any]) -> list[dict[str, Any]]:
    entries = payload.get("entries", [])
    if not isinstance(entries, list):
        raise ValueError("Lexicon 'entries' must be a list")
    return [entry for entry in entries if isinstance(entry, dict)]


def iter_lexicon_characters(
    payload: dict[str, Any],
    *,
    authors: set[str] | None = None,
) -> list[dict[str, Any]]:
    wanted = {_normalize_label(author) for author in authors or set()}
    collected: list[dict[str, Any]] = []
    for entry in iter_lexicon_entries(payload):
        author = str(entry.get("author", "") or "").strip()
        if wanted and _normalize_label(author) not in wanted:
            continue
        for character in entry.get("characters", []):
            if not isinstance(character, dict):
                continue
            clone = dict(character)
            clone["_entry_id"] = str(entry.get("entry_id", "") or "")
            clone["_author"] = author
            clone["_series"] = str(entry.get("series", "") or "")
            clone["_book_title"] = str(entry.get("book_title", "") or "")
            collected.append(clone)
    return collected


def build_pronunciation_rules(
    payload: dict[str, Any] | None = None,
    *,
    authors: set[str] | None = None,
) -> list[dict[str, Any]]:
    lexicon = payload or load_global_lexicon()
    rules = build_author_pronunciation_rules(lexicon, authors=authors)
    for character in iter_lexicon_characters(lexicon, authors=authors):
        if not bool(character.get("use_for_xtts", False)):
            continue
        spoken_as = " ".join(str(character.get("spoken_as", "") or "").split()).strip()
        if not spoken_as:
            continue
        name = str(character.get("name", "") or "").strip()
        variants: list[tuple[str, str]] = []
        if name:
            variants.append((name, spoken_as))
        for alias in character.get("rule_aliases", []):
            match = str(alias).strip()
            if not match:
                continue
            variants.append((match, _character_alias_spoken_as(name, spoken_as, match)))
        for match, variant_spoken_as in variants:
            if _normalize_label(match) == _normalize_label(variant_spoken_as):
                continue
            rules.append(
                {
                    "match": match,
                    "spoken_as": variant_spoken_as,
                    "scope": "whole_phrase",
                    "enabled": True,
                }
            )
    return normalize_pronunciation_rules(rules)


def build_author_pronunciation_rules(
    payload: dict[str, Any] | None = None,
    *,
    authors: set[str] | None = None,
) -> list[dict[str, Any]]:
    lexicon = payload or load_global_lexicon()
    wanted = {_normalize_label(author) for author in authors or set() if str(author or "").strip()}
    grouped: dict[str, dict[str, Any]] = {}
    for entry in iter_lexicon_entries(lexicon):
        author = str(entry.get("author", "") or "").strip()
        aliases = [
            str(alias).strip()
            for alias in entry.get("author_aliases", [])
            if str(alias).strip()
        ]
        variants = [author, *aliases, *_derived_author_variants(author)]
        normalized_variants = {_normalize_label(item) for item in variants if item}
        if wanted and not (normalized_variants & wanted):
            continue
        if not author:
            continue
        group_key = _normalize_label(author)
        info = grouped.setdefault(
            group_key,
            {
                "author": author,
                "spoken_as": "",
                "variants": set(),
            },
        )
        explicit_spoken_as = " ".join(str(entry.get("author_spoken_as", "") or "").split()).strip()
        if explicit_spoken_as and not info["spoken_as"]:
            info["spoken_as"] = explicit_spoken_as
        info["variants"].update(item for item in variants if item)
    rules: list[dict[str, Any]] = []
    for info in grouped.values():
        spoken_as = str(info.get("spoken_as") or "").strip() or _author_spoken_hint(str(info["author"]))
        if not spoken_as:
            continue
        for match in sorted(info["variants"], key=lambda item: (-len(item), item.casefold())):
            rules.append(
                {
                    "match": match,
                    "spoken_as": spoken_as,
                    "scope": "whole_phrase",
                    "enabled": True,
                }
            )
    return normalize_pronunciation_rules(rules)


def build_xtts_profile_patch(
    profile_data: dict[str, Any],
    *,
    payload: dict[str, Any] | None = None,
    authors: set[str] | None = None,
) -> dict[str, Any]:
    updated = dict(profile_data)
    updated["xtts_quality_mode"] = XTTS_QUALITY_MAX
    updated["xtts_inference"] = default_xtts_inference(XTTS_QUALITY_MAX)
    updated["pronunciation_rules"] = build_pronunciation_rules(payload, authors=authors)
    updated["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    notes = str(updated.get("notes", "") or "").strip()
    suffix = "Mit globalem Autoren-/Figurenlexikon fuer Aiken, Harrison und Rowling erweitert"
    updated["notes"] = f"{notes} | {suffix}" if notes and suffix not in notes else (notes or suffix)
    return updated


def validate_global_lexicon(path: str | Path | None = None) -> dict[str, Any]:
    payload = load_global_lexicon(path)
    errors: list[str] = []
    warnings: list[str] = []

    version = payload.get("version")
    if not isinstance(version, int) or version < 1:
        errors.append("Top-level 'version' must be an integer >= 1")

    seen_entry_ids: set[str] = set()
    seen_rule_matches: dict[str, str] = {}
    total_characters = 0
    total_rule_candidates = 0

    for entry in iter_lexicon_entries(payload):
        entry_id = str(entry.get("entry_id", "") or "").strip()
        if not entry_id:
            errors.append("Entry without entry_id")
            continue
        if entry_id in seen_entry_ids:
            errors.append(f"Duplicate entry_id: {entry_id}")
        seen_entry_ids.add(entry_id)

        if not str(entry.get("author", "") or "").strip():
            errors.append(f"{entry_id}: missing author")
        if not str(entry.get("book_title", "") or "").strip():
            warnings.append(f"{entry_id}: missing book_title")
        if not isinstance(entry.get("book_title_aliases", []), list):
            errors.append(f"{entry_id}: book_title_aliases must be a list")
        if not isinstance(entry.get("characters", []), list):
            errors.append(f"{entry_id}: characters must be a list")
            continue

        for character in entry.get("characters", []):
            if not isinstance(character, dict):
                errors.append(f"{entry_id}: character entry must be an object")
                continue
            total_characters += 1
            name = " ".join(str(character.get("name", "") or "").split()).strip()
            spoken_as = " ".join(str(character.get("spoken_as", "") or "").split()).strip()
            if not name:
                errors.append(f"{entry_id}: character without name")
                continue
            aliases = character.get("aliases", [])
            if not isinstance(aliases, list):
                errors.append(f"{entry_id}: aliases for {name!r} must be a list")
                aliases = []
            sources = character.get("sources", [])
            if not isinstance(sources, list) or not sources:
                warnings.append(f"{entry_id}: character {name!r} should carry at least one source")
            if bool(character.get("use_for_xtts", False)):
                total_rule_candidates += 1
                if not spoken_as:
                    errors.append(f"{entry_id}: XTTS character {name!r} is missing spoken_as")
                variants = [name]
                variants.extend(
                    str(alias).strip()
                    for alias in character.get("rule_aliases", [])
                    if str(alias).strip()
                )
                for variant in variants:
                    key = _normalize_label(variant)
                    previous = seen_rule_matches.get(key)
                    if previous and previous != spoken_as:
                        errors.append(
                            f"{entry_id}: conflicting spoken_as for variant {variant!r}: {previous!r} vs {spoken_as!r}"
                        )
                    else:
                        seen_rule_matches[key] = spoken_as

    rules = build_pronunciation_rules(payload)
    return {
        "path": str(Path(path).expanduser().resolve()) if path else str(default_lexicon_path()),
        "version": int(version or 0),
        "entry_count": len(seen_entry_ids),
        "character_count": total_characters,
        "xtts_character_count": total_rule_candidates,
        "pronunciation_rule_count": len(rules),
        "errors": errors,
        "warnings": warnings,
        "is_valid": not errors,
    }


def scan_books_for_lexicon(
    root: str | Path,
    *,
    path: str | Path | None = None,
    suffixes: set[str] | None = None,
) -> dict[str, Any]:
    lexicon = load_global_lexicon(path)
    root_path = Path(root).expanduser().resolve()
    allowed = {suffix.lower() for suffix in (suffixes or {".epub", ".pdf", ".txt"})}
    files = sorted(
        source
        for source in root_path.rglob("*")
        if source.is_file() and source.suffix.lower() in allowed
    )
    file_reports: list[dict[str, Any]] = []
    total_books = 0
    total_books_with_hits = 0
    total_expected = 0
    total_found = 0

    for source in files:
        matched_entries = _match_entries_for_source(source, lexicon)
        if not matched_entries:
            continue
        total_books += 1
        content = _read_source_text(source)
        normalized_content = _normalize_label(content)
        book_expected = 0
        book_found = 0
        entry_reports: list[dict[str, Any]] = []

        for entry in matched_entries:
            found_names: list[str] = []
            missing_names: list[str] = []
            for character in entry.get("characters", []):
                if not isinstance(character, dict):
                    continue
                name = str(character.get("name", "") or "").strip()
                if not name:
                    continue
                book_expected += 1
                total_expected += 1
                variants = [name]
                variants.extend(str(alias).strip() for alias in character.get("aliases", []) if str(alias).strip())
                if any(_contains_variant(normalized_content, variant) for variant in variants):
                    found_names.append(name)
                    book_found += 1
                    total_found += 1
                else:
                    missing_names.append(name)
            entry_reports.append(
                {
                    "entry_id": str(entry.get("entry_id", "") or ""),
                    "author": str(entry.get("author", "") or ""),
                    "book_title": str(entry.get("book_title", "") or ""),
                    "found_character_count": len(found_names),
                    "missing_character_count": len(missing_names),
                    "found_characters": found_names,
                    "missing_characters": missing_names,
                }
            )

        if book_found:
            total_books_with_hits += 1
        file_reports.append(
            {
                "source_path": str(source),
                "matched_entry_ids": [str(entry.get("entry_id", "") or "") for entry in matched_entries],
                "expected_character_count": book_expected,
                "found_character_count": book_found,
                "coverage": round((book_found / book_expected), 4) if book_expected else 0.0,
                "entries": entry_reports,
            }
        )

    return {
        "root": str(root_path),
        "book_count": total_books,
        "books_with_hits": total_books_with_hits,
        "expected_character_count": total_expected,
        "found_character_count": total_found,
        "coverage": round((total_found / total_expected), 4) if total_expected else 0.0,
        "files": file_reports,
    }


def _match_entries_for_source(source: Path, payload: dict[str, Any]) -> list[dict[str, Any]]:
    searchable = _normalize_label(str(source))
    matched: list[dict[str, Any]] = []
    for entry in iter_lexicon_entries(payload):
        variants = [str(entry.get("book_title", "") or "").strip()]
        variants.extend(
            str(alias).strip() for alias in entry.get("book_title_aliases", []) if str(alias).strip()
        )
        if any(_contains_variant(searchable, variant) for variant in variants):
            matched.append(entry)
    return matched


def _contains_variant(normalized_haystack: str, variant: str) -> bool:
    needle = _normalize_label(variant)
    if not needle:
        return False
    return needle in normalized_haystack


def _read_source_text(source: Path) -> str:
    suffix = source.suffix.lower()
    if suffix == ".epub":
        try:
            book = epub.read_epub(str(source))
        except Exception:
            return ""
        chunks: list[str] = []
        for item in book.get_items_of_type(ITEM_DOCUMENT):
            try:
                chunks.append(item.get_body_content().decode("utf-8", errors="ignore"))
            except Exception:
                continue
        html = " ".join(chunks)
        return re.sub(r"<[^>]+>", " ", html)
    if suffix == ".pdf":
        try:
            reader = PdfReader(str(source))
        except Exception:
            return ""
        text_parts: list[str] = []
        for page in reader.pages[:40]:
            try:
                text_parts.append(page.extract_text() or "")
            except Exception:
                continue
        return "\n".join(text_parts)
    if suffix == ".txt":
        try:
            return source.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                return source.read_text(encoding="latin-1")
            except Exception:
                return ""
        except Exception:
            return ""
    return ""


def _normalize_label(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    normalized = normalized.casefold()
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return " ".join(normalized.split())


def _derived_author_variants(author: str) -> list[str]:
    normalized = " ".join(str(author or "").split()).strip()
    if not normalized:
        return []
    variants = [normalized]
    if "," in normalized:
        parts = [part.strip() for part in normalized.split(",") if part.strip()]
        if len(parts) >= 2:
            variants.append(" ".join(parts[1:] + [parts[0]]))
    else:
        parts = normalized.split()
        if len(parts) >= 2:
            surname = parts[-1]
            given = " ".join(parts[:-1])
            variants.append(f"{surname}, {given}")
            variants.append(f"{surname}, {given.replace('. ', '.')}")
    return [variant for variant in variants if variant]


def _author_spoken_hint(author: str) -> str:
    hinted = " ".join(str(author or "").split()).strip()
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
    hinted = re.sub(r"\s+", " ", hinted).strip()
    return hinted


def _character_alias_spoken_as(name: str, spoken_as: str, alias: str) -> str:
    alias = " ".join(str(alias or "").split()).strip()
    if not alias:
        return ""
    name_tokens = _name_tokens(name)
    alias_tokens = _name_tokens(alias)
    spoken_tokens = str(spoken_as or "").split()
    if not name_tokens or not alias_tokens or not spoken_tokens:
        return alias
    span_start = _token_span_start(name_tokens, alias_tokens)
    if span_start < 0:
        if len(alias_tokens) == len(name_tokens) and any(
            alias_token == name_token
            for alias_token, name_token in zip(alias_tokens, name_tokens, strict=False)
        ):
            return " ".join(spoken_tokens[:len(name_tokens)]).strip() or _author_spoken_hint(alias)
        return _author_spoken_hint(alias)
    if len(spoken_tokens) >= len(name_tokens):
        selected = spoken_tokens[span_start:span_start + len(alias_tokens)]
    elif len(alias_tokens) == 1 and span_start == 0:
        selected = spoken_tokens[:1]
    elif len(alias_tokens) == 1 and span_start == len(name_tokens) - 1:
        selected = spoken_tokens[-1:]
    elif span_start == 0:
        selected = spoken_tokens[:len(alias_tokens)]
    elif span_start + len(alias_tokens) == len(name_tokens):
        selected = spoken_tokens[-len(alias_tokens):]
    else:
        selected = []
    return " ".join(selected).strip() or _author_spoken_hint(alias)


def _name_tokens(value: str) -> list[str]:
    normalized = unicodedata.normalize("NFKD", value.replace("’", "'"))
    stripped = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return [token.casefold() for token in re.findall(r"[A-Za-zÄÖÜäöüß]+", stripped)]


def _token_span_start(tokens: list[str], needle: list[str]) -> int:
    if not needle or len(needle) > len(tokens):
        return -1
    for index in range(0, len(tokens) - len(needle) + 1):
        if tokens[index:index + len(needle)] == needle:
            return index
    return -1

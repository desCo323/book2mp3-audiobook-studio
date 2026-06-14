from __future__ import annotations

from difflib import SequenceMatcher
import re
import unicodedata


COPY_SUFFIX_RE = re.compile(r"\s*\((\d+|copy|kopie)\)\s*$", re.IGNORECASE)
GENERIC_NOISE_RE = re.compile(
    r"\b("
    r"isbn(?:-1[03])?|pages?|auflage|edition|german|english|deutsch|pdf|epub|mobi|mb|kb|"
    r"springer|reference|technik|press|verlag|magazin|heise|guide|kobo|cover|sample|excerpt|"
    r"impressum|copyright|herausgegeben|further information|weitere information"
    r")\b",
    re.IGNORECASE,
)
AUTHOR_PARTICLES = {"von", "van", "de", "del", "da", "di", "ten", "den", "der", "la", "le"}
TITLE_LINK_WORDS = {"and", "und", "of", "the", "for", "to", "a", "an", "y", "e"}
COMMON_GIVEN_NAMES = {
    "albrecht",
    "andreas",
    "anne",
    "beate",
    "benedikt",
    "birgit",
    "daniel",
    "derek",
    "detlef",
    "dietmar",
    "gabriel",
    "hans",
    "jane",
    "joachim",
    "jochen",
    "josephine",
    "jürgen",
    "katharina",
    "kristin",
    "manuela",
    "martina",
    "michael",
    "nikola",
    "patrick",
    "ralph",
    "rachel",
    "thomas",
    "thea",
    "wolf",
}
TITLE_START_STOPWORDS = {"das", "der", "die", "dem", "den", "des", "the", "a", "an", "le", "la", "les"}


def repair_mojibake(value: str) -> str:
    text = value or ""
    if not text:
        return ""
    if any(marker in text for marker in ("Ã", "Â", "â", "Г")):
        replacements = {
            "Ã¤": "ä",
            "Ã„": "Ä",
            "Ã¶": "ö",
            "Ã–": "Ö",
            "Ã¼": "ü",
            "Ãœ": "Ü",
            "ÃŸ": "ß",
            "Ã©": "é",
            "Ã¨": "è",
            "Ã¡": "á",
            "Ã³": "ó",
            "Ã±": "ñ",
            "â€“": "–",
            "â€”": "-",
            "â€ž": "\"",
            "â€œ": "\"",
            "â€š": "'",
            "â€™": "'",
            "â€¦": "...",
            "Â": "",
            "Гј": "ü",
            "Гњ": "Ü",
            "Г¤": "ä",
            "Г„": "Ä",
            "Г¶": "ö",
            "Г–": "Ö",
            "ГŸ": "ß",
        }
        for source, target in replacements.items():
            text = text.replace(source, target)
    return text


def _protect_decimal_dots(value: str) -> str:
    return re.sub(r"(?<=\d)\.(?=\d)", "<DECIMAL_DOT>", value)


def _restore_decimal_dots(value: str) -> str:
    return value.replace("<DECIMAL_DOT>", ".")


def cleanup_label_text(value: str) -> str:
    text = repair_mojibake(value or "")
    text = COPY_SUFFIX_RE.sub("", text)
    text = text.replace("@", " ")
    protected = _protect_decimal_dots(text)
    protected = protected.replace("__", " __ ")
    protected = protected.replace("_", " ")
    protected = protected.replace("/", " ")
    protected = protected.replace("\\", " ")
    protected = protected.replace(":", ": ")
    protected = re.sub(r"\.(?=[A-Za-z])", " ", protected)
    protected = re.sub(r"(?<=[A-Za-z])\.(?!\d)", " ", protected)
    protected = re.sub(r"\s+", " ", protected)
    return _restore_decimal_dots(protected).strip(" -_.,;|")


def clean_title_fragment(value: str) -> str:
    text = cleanup_label_text(value)
    text = re.sub(r"\b(German Edition|Deutsche Ausgabe)\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip(" -_.,;|")
    return text


def clean_author_fragment(value: str) -> str:
    text = cleanup_label_text(value)
    text = re.sub(r"^(by|von)\s+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(Hrsg\.?|Herausgeber|Editor|Editors)\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip(" -_.,;|")
    return text


def canonical_text(value: str) -> str:
    text = repair_mojibake(value or "").casefold()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.replace("&", " and ")
    text = text.replace("ß", "ss")
    text = re.sub(r"\b(bd|band|vol|volume|teil|book)\.?\s*\d+\b", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def similarity(left: str, right: str) -> float:
    normalized_left = canonical_text(left)
    normalized_right = canonical_text(right)
    if not normalized_left or not normalized_right:
        return 0.0
    if normalized_left == normalized_right:
        return 1.0
    if normalized_left in normalized_right or normalized_right in normalized_left:
        return 0.93
    return SequenceMatcher(a=normalized_left, b=normalized_right).ratio()


def looks_like_noise(value: str) -> bool:
    text = cleanup_label_text(value)
    if not text:
        return True
    if len(text) <= 1:
        return True
    if " by " in text.casefold() or " von " in text.casefold():
        return False
    if GENERIC_NOISE_RE.search(text) and len(text.split()) <= 8:
        return True
    if re.fullmatch(r"[\d\W_]+", text):
        return True
    return False


def looks_like_person_name(value: str) -> bool:
    text = clean_author_fragment(value)
    if not text:
        return False
    if len(text) > 70:
        return False
    if ":" in text or "!" in text or "?" in text:
        return False
    if re.search(r"\d{3,}", text):
        return False
    parts = [part for part in re.split(r"[\s,;/•]+", text) if part]
    if not parts or len(parts) > 7:
        return False
    if "," in text:
        return True
    if len(parts) == 1:
        if "-" in parts[0]:
            subparts = [part for part in parts[0].split("-") if part]
            if len(subparts) >= 2 and all(part[:1].isupper() for part in subparts):
                return False
        return len(parts[0]) >= 3 and not looks_like_noise(parts[0])
    if parts[0].casefold() in TITLE_START_STOPWORDS:
        return False
    if any(part.casefold() in TITLE_LINK_WORDS for part in parts[1:-1]):
        return False
    if parts[0].casefold() in COMMON_GIVEN_NAMES:
        return True
    if len(parts) == 2 and all(re.fullmatch(r"[A-Za-zÄÖÜäöüß'`.-]+", part) for part in parts):
        return False
    capitalized = 0
    for part in parts:
        lowered = part.casefold()
        if lowered in AUTHOR_PARTICLES:
            capitalized += 1
            continue
        if re.fullmatch(r"[A-ZÄÖÜ]\.?", part):
            capitalized += 1
            continue
        if part[:1].isupper() or any(character.isupper() for character in part[1:]):
            capitalized += 1
            continue
        if re.fullmatch(r"[A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß'`.-]+", part):
            capitalized += 1
    return capitalized >= max(1, len(parts) - 1)


def refine_author_fragment(value: str) -> str:
    text = clean_author_fragment(value)
    if not text:
        return ""
    segments = [
        clean_author_fragment(segment)
        for segment in re.split(r"[;|•·]", text)
        if clean_author_fragment(segment)
    ]
    person_segments = [segment for segment in segments if looks_like_person_name(segment)]
    if person_segments:
        unique_segments: list[str] = []
        for segment in person_segments:
            if segment not in unique_segments:
                unique_segments.append(segment)
        return "; ".join(unique_segments)
    return text


def is_generic_file_stem(value: str) -> bool:
    text = cleanup_label_text(value)
    if not text:
        return True
    if re.fullmatch(r"[0-9Xx@._-]+", value):
        return True
    if re.fullmatch(r"[A-Za-z]{0,4}\d{3,}", text):
        return True
    if len(text.split()) == 1 and re.search(r"\d", text) and len(text) <= 12:
        return True
    return False


def short_text(value: str, *, limit: int = 180) -> str:
    text = repair_mojibake(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"

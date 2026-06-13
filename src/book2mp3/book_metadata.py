from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen


OPEN_LIBRARY_SEARCH_URL = "https://openlibrary.org/search.json"


def _clean_part(value: str) -> str:
    cleaned = value.replace("_", " ").strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(r"\b(epub|pdf|txt)\b", "", cleaned, flags=re.IGNORECASE).strip()
    return cleaned.strip(" -_")


def guess_metadata_from_filename(source_path: Path) -> dict[str, str]:
    stem = source_path.stem
    normalized = re.sub(r"[\[\(].*?[\]\)]", "", stem)
    normalized = re.sub(r"\s+", " ", normalized.replace("_", " ")).strip()
    guesses = {
        "title": _clean_part(normalized),
        "author": "",
        "album": "",
        "artist": "",
        "album_artist": "",
        "narrator": "",
        "genre": "Audiobook",
        "language": "",
        "comment": "",
        "search_query": "",
    }
    patterns = [
        re.compile(r"^(?P<author>.+?)\s+-\s+(?P<title>.+)$"),
        re.compile(r"^(?P<title>.+?)\s+by\s+(?P<author>.+)$", re.IGNORECASE),
        re.compile(r"^(?P<title>.+?)\s+von\s+(?P<author>.+)$", re.IGNORECASE),
    ]
    for pattern in patterns:
        match = pattern.match(normalized)
        if not match:
            continue
        title = _clean_part(match.group("title"))
        author = _clean_part(match.group("author"))
        if title and author:
            guesses["title"] = title
            guesses["author"] = author
            break
    guesses["album"] = guesses["title"]
    guesses["search_query"] = " ".join(part for part in (guesses["title"], guesses["author"]) if part).strip()
    return guesses


def search_open_library_metadata(
    *,
    query: str = "",
    title: str = "",
    author: str = "",
    limit: int = 5,
) -> list[dict[str, str | int]]:
    params: dict[str, str | int] = {"limit": max(1, min(limit, 10))}
    if query:
        params["q"] = query
    if title:
        params["title"] = title
    if author:
        params["author"] = author
    if "q" not in params and "title" not in params and "author" not in params:
        return []
    url = f"{OPEN_LIBRARY_SEARCH_URL}?{urlencode(params)}"
    with urlopen(url, timeout=20) as response:
        payload = json.load(response)
    results: list[dict[str, str | int]] = []
    for doc in payload.get("docs", [])[:limit]:
        author_names = doc.get("author_name") or []
        first_sentence = doc.get("first_sentence") or []
        subjects = doc.get("subject") or []
        language = (doc.get("language") or [""])[0]
        cover_id = doc.get("cover_i")
        cover_url = f"https://covers.openlibrary.org/b/id/{cover_id}-M.jpg" if cover_id else ""
        results.append(
            {
                "title": str(doc.get("title") or ""),
                "author": ", ".join(str(name) for name in author_names[:3]),
                "year": int(doc.get("first_publish_year") or 0),
                "language": str(language or ""),
                "genre": ", ".join(str(item) for item in subjects[:4]),
                "comment": str(first_sentence[0] if isinstance(first_sentence, list) and first_sentence else ""),
                "cover_url": cover_url,
                "source": "Open Library",
                "open_library_key": str(doc.get("key") or ""),
            }
        )
    return results


def choose_best_metadata_result(
    suggestions: list[dict[str, str | int]],
    *,
    guessed_title: str,
    guessed_author: str,
) -> dict[str, str | int] | None:
    if not suggestions:
        return None
    target_title = guessed_title.lower().strip()
    target_author = guessed_author.lower().strip()

    def score(item: dict[str, str | int]) -> tuple[int, int]:
        title = str(item.get("title") or "").lower()
        author = str(item.get("author") or "").lower()
        title_score = 2 if target_title and target_title in title else 1 if title.startswith(target_title) else 0
        author_score = 2 if target_author and target_author in author else 1 if target_author and author.startswith(target_author) else 0
        return (title_score + author_score, int(item.get("year") or 0))

    ranked = sorted(suggestions, key=score, reverse=True)
    return ranked[0]


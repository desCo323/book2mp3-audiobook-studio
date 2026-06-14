from __future__ import annotations

from hashlib import sha1
import json
from pathlib import Path
from typing import Any

import requests

from .models import MetadataCandidate
from .normalize import canonical_text, short_text, similarity


OPEN_LIBRARY_SEARCH_URL = "https://openlibrary.org/search.json"
GOOGLE_BOOKS_SEARCH_URL = "https://www.googleapis.com/books/v1/volumes"


class JsonMetadataCache:
    def __init__(self, path: Path | None) -> None:
        self.path = path

    def _load(self) -> dict[str, Any]:
        if self.path is None or not self.path.exists():
            return {"entries": {}}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return {"entries": {}}
        if not isinstance(payload, dict):
            return {"entries": {}}
        entries = payload.get("entries")
        if not isinstance(entries, dict):
            payload["entries"] = {}
        return payload

    def get(self, key: str) -> Any | None:
        payload = self._load()
        return payload.get("entries", {}).get(key)

    def set(self, key: str, value: Any) -> None:
        if self.path is None:
            return
        payload = self._load()
        payload.setdefault("entries", {})
        payload["entries"][key] = value
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _search_key(provider: str, *, query: str, title: str, author: str, limit: int) -> str:
    material = json.dumps(
        {
            "provider": provider,
            "query": query,
            "title": title,
            "author": author,
            "limit": limit,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return sha1(material.encode("utf-8")).hexdigest()


def search_open_library_metadata(
    *,
    query: str = "",
    title: str = "",
    author: str = "",
    limit: int = 5,
    cache: JsonMetadataCache | None = None,
    timeout: float = 12.0,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"limit": max(1, min(limit, 10))}
    if query:
        params["q"] = query
    if title:
        params["title"] = title
    if author:
        params["author"] = author
    if "q" not in params and "title" not in params and "author" not in params:
        return []
    key = _search_key("open_library", query=query, title=title, author=author, limit=limit)
    if cache:
        cached = cache.get(key)
        if isinstance(cached, list):
            return cached
    response = requests.get(OPEN_LIBRARY_SEARCH_URL, params=params, timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    results: list[dict[str, Any]] = []
    for doc in payload.get("docs", [])[:limit]:
        author_names = doc.get("author_name") or []
        first_sentence = doc.get("first_sentence") or []
        subjects = doc.get("subject") or []
        language = (doc.get("language") or [""])[0]
        cover_id = doc.get("cover_i")
        cover_url = f"https://covers.openlibrary.org/b/id/{cover_id}-M.jpg" if cover_id else ""
        result = {
            "title": str(doc.get("title") or ""),
            "author": ", ".join(str(name) for name in author_names[:3]),
            "year": int(doc.get("first_publish_year") or 0),
            "language": str(language or ""),
            "genre": ", ".join(str(item) for item in subjects[:4]),
            "publisher": ", ".join(str(item) for item in (doc.get("publisher") or [])[:2]),
            "subjects": [str(item) for item in subjects[:6]],
            "identifiers": [str(item) for item in (doc.get("isbn") or [])[:4]],
            "comment": short_text(str(first_sentence[0] if isinstance(first_sentence, list) and first_sentence else "")),
            "cover_url": cover_url,
            "source": "Open Library",
            "open_library_key": str(doc.get("key") or ""),
        }
        results.append(result)
    if cache:
        cache.set(key, results)
    return results


def search_google_books_metadata(
    *,
    query: str = "",
    title: str = "",
    author: str = "",
    limit: int = 5,
    cache: JsonMetadataCache | None = None,
    timeout: float = 12.0,
) -> list[dict[str, Any]]:
    query_parts: list[str] = []
    if title:
        query_parts.append(f'intitle:"{title}"')
    if author:
        query_parts.append(f'inauthor:"{author}"')
    if query and not query_parts:
        query_parts.append(query)
    elif query:
        query_parts.append(query)
    if not query_parts:
        return []
    params = {
        "q": " ".join(part for part in query_parts if part).strip(),
        "printType": "books",
        "maxResults": max(1, min(limit, 10)),
        "langRestrict": "",
    }
    key = _search_key("google_books", query=query, title=title, author=author, limit=limit)
    if cache:
        cached = cache.get(key)
        if isinstance(cached, list):
            return cached
    response = requests.get(GOOGLE_BOOKS_SEARCH_URL, params=params, timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    results: list[dict[str, Any]] = []
    for item in payload.get("items", [])[:limit]:
        volume = item.get("volumeInfo", {}) or {}
        identifiers = volume.get("industryIdentifiers") or []
        results.append(
            {
                "title": str(volume.get("title") or ""),
                "author": ", ".join(str(name) for name in volume.get("authors") or []),
                "year": int(str(volume.get("publishedDate") or "0")[:4] or 0),
                "language": str(volume.get("language") or ""),
                "genre": ", ".join(str(name) for name in volume.get("categories") or []),
                "publisher": str(volume.get("publisher") or ""),
                "subjects": [str(name) for name in volume.get("categories") or []],
                "comment": short_text(str(volume.get("description") or "")),
                "cover_url": str((volume.get("imageLinks") or {}).get("thumbnail") or ""),
                "source": "Google Books",
                "google_books_id": str(item.get("id") or ""),
                "identifiers": [str(entry.get("identifier") or "") for entry in identifiers if entry.get("identifier")],
            }
        )
    if cache:
        cache.set(key, results)
    return results


def _rank_online_result(result: dict[str, Any], *, title: str, author: str) -> float:
    title_similarity = similarity(result.get("title", ""), title)
    author_similarity = similarity(result.get("author", ""), author)
    if not title and not author:
        return 0.0
    provider_bonus = 0.06 if result.get("source") == "Open Library" else 0.04
    return (title_similarity * 0.7) + (author_similarity * 0.3) + provider_bonus


def search_online_book_metadata(
    *,
    query: str = "",
    title: str = "",
    author: str = "",
    limit: int = 5,
    cache_path: Path | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    cache = JsonMetadataCache(cache_path)
    errors: list[str] = []
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for provider in (search_open_library_metadata, search_google_books_metadata):
        try:
            results = provider(query=query, title=title, author=author, limit=limit, cache=cache)
        except Exception as exc:
            errors.append(f"{provider.__name__}: {exc}")
            continue
        for result in results:
            key = (canonical_text(str(result.get("title") or "")), canonical_text(str(result.get("author") or "")))
            if key not in merged:
                merged[key] = result
                continue
            if result.get("comment") and not merged[key].get("comment"):
                merged[key]["comment"] = result["comment"]
            if result.get("genre") and not merged[key].get("genre"):
                merged[key]["genre"] = result["genre"]
            if result.get("cover_url") and not merged[key].get("cover_url"):
                merged[key]["cover_url"] = result["cover_url"]
            if result.get("source") and result["source"] not in str(merged[key].get("source") or ""):
                merged[key]["source"] = f"{merged[key]['source']} + {result['source']}"
    ranked = sorted(
        merged.values(),
        key=lambda item: _rank_online_result(item, title=title, author=author),
        reverse=True,
    )
    return ranked[:limit], errors


def online_result_as_candidate(result: dict[str, Any], *, confidence: float) -> MetadataCandidate:
    return MetadataCandidate(
        title=str(result.get("title") or ""),
        author=str(result.get("author") or ""),
        language=str(result.get("language") or ""),
        genre=str(result.get("genre") or ""),
        publisher=str(result.get("publisher") or ""),
        comment=str(result.get("comment") or ""),
        source=f"online.{result.get('source') or 'unknown'}",
        confidence=confidence,
        evidence=str(result.get("source") or ""),
        year=int(result.get("year") or 0),
        identifiers=[str(value) for value in result.get("identifiers") or [] if value],
        subjects=[str(value) for value in result.get("subjects") or [] if value],
        extra={key: value for key, value in result.items() if key not in {"title", "author", "language", "genre", "comment", "source", "year", "identifiers"}},
    )

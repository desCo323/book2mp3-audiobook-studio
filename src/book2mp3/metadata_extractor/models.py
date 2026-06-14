from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class MetadataCandidate:
    title: str = ""
    author: str = ""
    language: str = ""
    genre: str = ""
    publisher: str = ""
    comment: str = ""
    source: str = ""
    confidence: float = 0.0
    evidence: str = ""
    year: int = 0
    identifiers: list[str] = field(default_factory=list)
    subjects: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["confidence"] = round(float(self.confidence), 4)
        return payload


@dataclass
class MetadataExtractionResult:
    source_path: str
    title: str
    author: str
    language: str
    genre: str
    publisher: str
    year: int
    identifiers: list[str]
    subjects: list[str]
    comment: str
    confidence: float
    title_source: str
    author_source: str
    candidates: list[MetadataCandidate]
    online_results: list[dict[str, Any]]
    online_errors: list[str]
    cover_url: str = ""
    debug: dict[str, Any] = field(default_factory=dict)

    def guessed_metadata(self) -> dict[str, str]:
        title = self.title.strip()
        return {
            "title": title,
            "album": title,
            "artist": "",
            "album_artist": "",
            "narrator": "",
            "author": self.author.strip(),
            "genre": self.genre.strip() or "Audiobook",
            "language": self.language.strip(),
            "comment": self.comment.strip(),
        }

    def extended_book_metadata(self) -> dict[str, Any]:
        return {
            "publisher": self.publisher.strip(),
            "year": int(self.year or 0),
            "identifiers": list(self.identifiers),
            "subjects": list(self.subjects),
            "confidence": round(float(self.confidence), 4),
            "title_source": self.title_source,
            "author_source": self.author_source,
            "source_path": self.source_path,
            "cover_url": self.cover_url,
        }

    def mp3_transfer_payload(self, *, narrator: str = "") -> dict[str, Any]:
        resolved_narrator = narrator.strip()
        core = self.guessed_metadata()
        core["narrator"] = resolved_narrator
        core["artist"] = resolved_narrator or self.author.strip()
        core["album_artist"] = resolved_narrator or self.author.strip()
        ffmetadata_tags = {
            "title": self.title.strip(),
            "album": self.title.strip(),
            "artist": core["artist"],
            "album_artist": core["album_artist"],
            "author": self.author.strip(),
            "genre": self.genre.strip(),
            "language": self.language.strip(),
            "comment": self.comment.strip(),
            "description": self.comment.strip(),
            "publisher": self.publisher.strip(),
            "date": str(self.year) if self.year else "",
            "year": str(self.year) if self.year else "",
            "subject": "; ".join(self.subjects),
            "isbn": next((identifier for identifier in self.identifiers if identifier.replace("-", "").isdigit()), ""),
            "narrator": resolved_narrator,
        }
        return {
            "core_metadata": core,
            "ffmetadata_tags": {key: value for key, value in ffmetadata_tags.items() if value},
            "cover_url": self.cover_url,
            "extended_book_metadata": self.extended_book_metadata(),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_path": self.source_path,
            "title": self.title,
            "author": self.author,
            "language": self.language,
            "genre": self.genre,
            "publisher": self.publisher,
            "year": int(self.year or 0),
            "cover_url": self.cover_url,
            "identifiers": list(self.identifiers),
            "subjects": list(self.subjects),
            "comment": self.comment,
            "confidence": round(float(self.confidence), 4),
            "title_source": self.title_source,
            "author_source": self.author_source,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "online_results": list(self.online_results),
            "online_errors": list(self.online_errors),
            "mp3_transfer": self.mp3_transfer_payload(),
            "debug": dict(self.debug),
        }

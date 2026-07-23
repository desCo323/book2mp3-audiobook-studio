from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from ebooklib import ITEM_DOCUMENT, epub
from pypdf import PdfReader

from .models import MetadataCandidate, MetadataExtractionResult
from .normalize import (
    AUTHOR_PARTICLES,
    canonical_text,
    clean_author_fragment,
    clean_title_fragment,
    cleanup_label_text,
    is_generic_file_stem,
    looks_like_author_handle,
    looks_like_noise,
    looks_like_person_name,
    repair_mojibake,
    refine_author_fragment,
    short_text,
    similarity,
)
from .providers import online_result_as_candidate, search_online_book_metadata


FRONTMATTER_BY_RE = re.compile(
    r"^(?P<title>.+?)\s+(?P<marker>by|von)\s+(?P<author>.+?)(?:\s*\||\s*$)",
    re.IGNORECASE,
)
QUOTED_TITLE_RE = re.compile(
    r"^(?P<author>[^,\"]{3,80}),\s*[\"“](?P<title>.+?)[\"”](?:\s|$)",
    re.IGNORECASE,
)
GENERIC_PATH_LABELS = {
    "ebooks",
    "ebooks alina",
    "ebook",
    "epub",
    "epubs",
    "epubfe",
    "fanfiction",
    "fanfic",
    "ff",
    "pdf",
    "txt",
    "mobi",
    "azw",
    "azw3",
    "ebubtest",
    "library",
    "books",
    "synthetic",
    "__metadata_fixture__",
    "metadata fixture",
    "workspace",
    "input",
}
GERMAN_LANGUAGE_WORDS = {
    "der",
    "die",
    "das",
    "und",
    "ich",
    "nicht",
    "mit",
    "ist",
    "ein",
    "eine",
    "den",
    "dem",
    "des",
    "sich",
    "auf",
    "für",
    "war",
    "hatte",
    "aber",
    "auch",
    "dass",
    "wenn",
    "wie",
    "sein",
    "sie",
    "er",
    "wir",
    "ihr",
}
ENGLISH_LANGUAGE_WORDS = {
    "the",
    "and",
    "i",
    "you",
    "he",
    "she",
    "it",
    "we",
    "they",
    "to",
    "of",
    "in",
    "that",
    "was",
    "with",
    "for",
    "not",
    "his",
    "her",
    "had",
    "have",
    "this",
    "but",
    "from",
    "as",
}


class BookMetadataExtractor:
    def __init__(self, *, cache_path: Path | None = None) -> None:
        self.cache_path = cache_path

    def extract(
        self,
        source_path: str | Path,
        *,
        allow_online: bool = True,
        online_limit: int = 5,
    ) -> MetadataExtractionResult:
        source = Path(source_path).expanduser().resolve()
        candidates = self._collect_candidates(source)
        offline = self._build_offline_result(source, candidates)

        online_results: list[dict[str, Any]] = []
        online_errors: list[str] = []
        final_title = offline["title"]
        final_author = offline["author"]
        final_language = offline["language"]
        final_genre = offline["genre"] or "Audiobook"
        final_comment = offline["comment"]
        final_confidence = offline["confidence"]

        query_title = final_title or source.stem
        query_author = final_author
        if allow_online and query_title.strip():
            online_results, online_errors = search_online_book_metadata(
                query=" ".join(part for part in (query_title, query_author) if part).strip(),
                title=query_title,
                author=query_author,
                limit=online_limit,
                cache_path=self.cache_path,
            )
            chosen_online = self._pick_online_candidate(
                online_results,
                title=query_title,
                author=query_author,
            )
            if chosen_online is not None:
                final_title = self._prefer_field(current=final_title, online=chosen_online.title, current_confidence=offline["title_confidence"])
                final_author = self._prefer_field(current=final_author, online=chosen_online.author, current_confidence=offline["author_confidence"])
                if not final_language and chosen_online.language:
                    final_language = chosen_online.language
                if not final_comment and chosen_online.comment:
                    final_comment = chosen_online.comment
                if (not final_genre or final_genre == "Audiobook") and chosen_online.genre:
                    final_genre = chosen_online.genre
                final_confidence = max(final_confidence, chosen_online.confidence)
                candidates.append(chosen_online)

        extended = self._aggregate_extended_metadata(candidates)
        series = self._series_metadata(final_title, candidates, source)

        cover_url = self._pick_cover_url(
            candidates,
            fallback=(final_title.strip() or source.stem),
            fallback_author=final_author.strip(),
            online_results=online_results,
        )

        return MetadataExtractionResult(
            source_path=str(source),
            title=final_title,
            author=final_author,
            language=final_language,
            genre=final_genre or "Audiobook",
            publisher=extended["publisher"],
            year=extended["year"],
            identifiers=extended["identifiers"],
            subjects=extended["subjects"],
            comment=short_text(final_comment),
            confidence=round(final_confidence, 4),
            cover_url=cover_url,
            title_source=offline["title_source"],
            author_source=offline["author_source"],
            candidates=sorted(candidates, key=lambda item: item.confidence, reverse=True),
            online_results=online_results,
            online_errors=online_errors,
            series=series["series"],
            series_index=series["series_index"],
            display_title=series["display_title"],
            sort_title=series["sort_title"],
            subtitle=series["subtitle"],
            debug={
                "offline_confidence": round(offline["confidence"], 4),
                "offline_title_confidence": round(offline["title_confidence"], 4),
                "offline_author_confidence": round(offline["author_confidence"], 4),
                "field_sources": offline["field_sources"],
                "conflicts": offline["conflicts"],
                "warnings": offline["warnings"],
                "raw_metadata": offline["raw_metadata"],
                "language_source": offline["language_source"],
                "language_confidence": round(float(offline["language_confidence"]), 4),
            },
        )

    def suggest_metadata(self, source_path: str | Path, *, allow_online: bool = True) -> dict[str, str]:
        return self.extract(source_path, allow_online=allow_online).guessed_metadata()

    def guess_from_filename(self, source_path: str | Path) -> dict[str, str]:
        path = Path(source_path)
        candidates = self._path_candidates(path)
        offline = self._build_offline_result(path, candidates)
        title = offline["title"] or cleanup_label_text(path.stem)
        author = offline["author"]
        return {
            "title": title,
            "album": title,
            "artist": "",
            "album_artist": "",
            "narrator": "",
            "author": author,
            "genre": "Audiobook",
            "language": "",
            "comment": "",
        }

    def parse_filename_label(self, file_label: str, *, parent_label: str = "", suffix: str = ".epub") -> dict[str, str]:
        synthetic_path = Path("/__metadata_fixture__")
        if parent_label:
            synthetic_path /= parent_label
        synthetic_path /= f"{file_label}{suffix}"
        return self.guess_from_filename(synthetic_path)

    def _collect_candidates(self, source: Path) -> list[MetadataCandidate]:
        candidates = self._path_candidates(source)
        suffix = source.suffix.lower()
        if suffix == ".epub":
            candidates.extend(self._epub_candidates(source))
        elif suffix == ".pdf":
            candidates.extend(self._pdf_candidates(source))
        elif suffix == ".txt":
            candidates.extend(self._txt_candidates(source))
        candidates.extend(self._path_content_combo_candidates(source, candidates))
        return self._boost_consensus(candidates)

    def _build_offline_result(self, source: Path, candidates: list[MetadataCandidate]) -> dict[str, Any]:
        title_choice = self._choose_field_candidate(source, candidates, "title")
        author_choice = self._choose_field_candidate(source, candidates, "author")
        language_choice = self._choose_field_candidate(source, candidates, "language")
        comment_choice = self._choose_field_candidate(source, candidates, "comment")
        genre_choice = self._choose_field_candidate(source, candidates, "genre")

        title = title_choice.title if title_choice else cleanup_label_text(source.stem)
        author = author_choice.author if author_choice else ""
        language = language_choice.language if language_choice else ""
        comment = comment_choice.comment if comment_choice else ""
        genre = genre_choice.genre if genre_choice else "Audiobook"
        title_confidence = title_choice.confidence if title_choice else 0.0
        author_confidence = author_choice.confidence if author_choice else 0.0
        confidence = max(title_confidence, author_confidence)
        if title_confidence and author_confidence:
            confidence = (title_confidence + author_confidence) / 2.0
        return {
            "title": title,
            "author": author,
            "language": language,
            "genre": genre,
            "comment": comment,
            "confidence": confidence,
            "title_confidence": title_confidence,
            "author_confidence": author_confidence,
            "title_source": title_choice.source if title_choice else "",
            "author_source": author_choice.source if author_choice else "",
            "field_sources": self._field_sources(
                {
                    "title": title_choice,
                    "author": author_choice,
                    "language": language_choice,
                    "genre": genre_choice,
                    "comment": comment_choice,
                }
            ),
            "conflicts": self._field_conflicts(candidates),
            "warnings": self._candidate_warnings(candidates),
            "raw_metadata": self._compact_raw_metadata(candidates),
            "language_source": (
                str(language_choice.extra.get("language_source") or language_choice.source)
                if language_choice
                else ""
            ),
            "language_confidence": (
                float(language_choice.extra.get("language_confidence") or language_choice.confidence)
                if language_choice
                else 0.0
            ),
        }

    def _choose_field_candidate(
        self,
        source: Path,
        candidates: list[MetadataCandidate],
        field: str,
    ) -> MetadataCandidate | None:
        field_candidates = [candidate for candidate in candidates if str(getattr(candidate, field, "") or "").strip()]
        if not field_candidates:
            return None
        if source.suffix.lower() == ".epub" and field in {"title", "author"}:
            epub_choice = max(
                (
                    candidate
                    for candidate in field_candidates
                    if candidate.source == "epub.dc_metadata" and self._candidate_field_sane(candidate, field)
                ),
                key=lambda item: item.confidence,
                default=None,
            )
            if epub_choice is not None:
                return epub_choice
        return max(
            field_candidates,
            key=lambda item: (
                item.confidence + self._field_source_bonus(item, field),
                self._source_rank(item.source),
            ),
        )

    def _candidate_field_sane(self, candidate: MetadataCandidate, field: str) -> bool:
        if field == "title":
            return self._plausible_title(candidate.title)
        if field == "author":
            return self._plausible_author(candidate.author)
        return True

    def _field_source_bonus(self, candidate: MetadataCandidate, field: str) -> float:
        if candidate.source == "epub.dc_metadata" and field in {"title", "author", "language"}:
            return 0.08
        if candidate.source.startswith("filename.") and field in {"title", "author"}:
            return 0.02
        if candidate.source.startswith("path.parent"):
            return -0.08
        if candidate.source.startswith("path.grandparent"):
            return -0.12
        return 0.0

    def _source_rank(self, source: str) -> int:
        if source == "epub.dc_metadata":
            return 5
        if source.startswith("filename."):
            return 4
        if source.startswith(("pdf.", "txt.", "epub.text")):
            return 3
        if source.startswith("path.parent"):
            return 1
        return 0

    def _field_sources(self, choices: dict[str, MetadataCandidate | None]) -> dict[str, dict[str, Any]]:
        field_sources: dict[str, dict[str, Any]] = {}
        for field, candidate in choices.items():
            if candidate is None:
                continue
            field_sources[field] = {
                "source": candidate.source,
                "confidence": round(float(candidate.confidence), 4),
                "value": str(getattr(candidate, field, "") or ""),
            }
        return field_sources

    def _field_conflicts(self, candidates: list[MetadataCandidate]) -> list[dict[str, Any]]:
        conflicts: list[dict[str, Any]] = []
        for field, threshold in (("title", 0.86), ("author", 0.84)):
            epub_choice = max(
                (candidate for candidate in candidates if candidate.source == "epub.dc_metadata" and getattr(candidate, field)),
                key=lambda item: item.confidence,
                default=None,
            )
            filename_choice = max(
                (
                    candidate
                    for candidate in candidates
                    if candidate.source.startswith("filename.") and getattr(candidate, field)
                ),
                key=lambda item: item.confidence,
                default=None,
            )
            if epub_choice is None or filename_choice is None:
                continue
            epub_value = str(getattr(epub_choice, field) or "")
            filename_value = str(getattr(filename_choice, field) or "")
            score = similarity(epub_value, filename_value)
            if score < threshold:
                conflicts.append(
                    {
                        "field": field,
                        "left_source": epub_choice.source,
                        "left": epub_value,
                        "right_source": filename_choice.source,
                        "right": filename_value,
                        "similarity": round(score, 4),
                    }
                )
        return conflicts

    def _candidate_warnings(self, candidates: list[MetadataCandidate]) -> list[str]:
        warnings: list[str] = []
        for candidate in candidates:
            for warning in candidate.extra.get("warnings", []):
                text = str(warning or "").strip()
                if text and text not in warnings:
                    warnings.append(text)
        return warnings

    def _compact_raw_metadata(self, candidates: list[MetadataCandidate]) -> dict[str, Any]:
        for candidate in candidates:
            raw = candidate.extra.get("raw_metadata")
            if isinstance(raw, dict):
                return raw
        return {}

    def _path_content_combo_candidates(self, source: Path, candidates: list[MetadataCandidate]) -> list[MetadataCandidate]:
        if source.suffix.lower() not in {".pdf", ".txt"}:
            return []
        parent_title = max(
            (candidate for candidate in candidates if candidate.source == "path.parent_title" and candidate.title),
            key=lambda item: item.confidence,
            default=None,
        )
        content_author = max(
            (
                candidate
                for candidate in candidates
                if candidate.author
                and candidate.source.startswith(("pdf.", "txt."))
                and self._plausible_author(candidate.author)
            ),
            key=lambda item: item.confidence,
            default=None,
        )
        if not parent_title or not content_author:
            return []
        return [
            MetadataCandidate(
                title=parent_title.title,
                author=content_author.author,
                source="path.content_combo",
                confidence=min((parent_title.confidence + content_author.confidence) / 2.0 + 0.12, 0.97),
                evidence=f"{parent_title.evidence} | {content_author.evidence}",
            )
        ]

    def _boost_consensus(self, candidates: list[MetadataCandidate]) -> list[MetadataCandidate]:
        boosted: list[MetadataCandidate] = []
        for candidate in candidates:
            confidence = candidate.confidence
            for other in candidates:
                if other is candidate:
                    continue
                if candidate.title and other.title and similarity(candidate.title, other.title) >= 0.92:
                    confidence += 0.05
                if candidate.author and other.author and similarity(candidate.author, other.author) >= 0.9:
                    confidence += 0.05
            boosted.append(
                MetadataCandidate(
                    title=candidate.title,
                    author=candidate.author,
                    language=candidate.language,
                    genre=candidate.genre,
                    publisher=candidate.publisher,
                    comment=candidate.comment,
                    source=candidate.source,
                    confidence=min(confidence, 0.99),
                    evidence=candidate.evidence,
                    year=candidate.year,
                    identifiers=list(candidate.identifiers),
                    subjects=list(candidate.subjects),
                    extra=dict(candidate.extra),
                )
            )
        return boosted

    def _aggregate_extended_metadata(self, candidates: list[MetadataCandidate]) -> dict[str, Any]:
        publisher_choice = max((candidate for candidate in candidates if candidate.publisher), key=lambda item: item.confidence, default=None)
        year_choice = max((candidate for candidate in candidates if candidate.year), key=lambda item: item.confidence, default=None)
        identifiers: list[str] = []
        subjects: list[str] = []
        for candidate in sorted(candidates, key=lambda item: item.confidence, reverse=True):
            for identifier in candidate.identifiers:
                normalized = identifier.strip()
                if normalized and normalized not in identifiers:
                    identifiers.append(normalized)
            for subject in candidate.subjects:
                normalized = cleanup_label_text(subject)
                if normalized and normalized not in subjects:
                    subjects.append(normalized)
        return {
            "publisher": publisher_choice.publisher if publisher_choice else "",
            "year": int(year_choice.year or 0) if year_choice else 0,
            "identifiers": identifiers[:8],
            "subjects": subjects[:8],
        }

    def _series_metadata(
        self,
        final_title: str,
        candidates: list[MetadataCandidate],
        source: Path,
    ) -> dict[str, str]:
        labels: list[str] = [final_title]
        for candidate in sorted(candidates, key=lambda item: item.confidence, reverse=True):
            if candidate.title:
                labels.append(candidate.title)
            if candidate.evidence:
                labels.append(Path(candidate.evidence).stem)
        labels.append(source.stem)
        for label in labels:
            parsed = self._parse_series_label(label)
            if parsed["series"] or parsed["series_index"]:
                return parsed
        display_title = clean_title_fragment(final_title)
        return {
            "series": "",
            "series_index": "",
            "display_title": display_title,
            "sort_title": self._sort_title(display_title),
            "subtitle": self._subtitle(display_title),
        }

    def _parse_series_label(self, label: str) -> dict[str, str]:
        text = clean_title_fragment(label)
        text = re.sub(r"\s+", " ", text).strip()
        patterns = [
            re.compile(
                r"^(?P<series>.+?)\s+Bd\.?\s*(?P<index>\d+(?:[.,]\d+)?)\s*-\s*(?P<title>.+)$",
                re.IGNORECASE,
            ),
            re.compile(
                r"^(?P<series>.+?)\s+(?:Band|Teil|Book|Vol\.?|Volume)\s*(?P<index>\d+(?:[.,]\d+)?)\s*-\s*(?P<title>.+)$",
                re.IGNORECASE,
            ),
            re.compile(r"^(?P<series>.+?)\.(?P<index>\d{1,3})\s*-\s*(?P<title>.+)$", re.IGNORECASE),
        ]
        for pattern in patterns:
            match = pattern.match(text)
            if not match:
                continue
            display_title = clean_title_fragment(match.group("title"))
            return {
                "series": clean_title_fragment(match.group("series")),
                "series_index": match.group("index").replace(",", "."),
                "display_title": display_title,
                "sort_title": self._sort_title(display_title),
                "subtitle": self._subtitle(display_title),
            }
        numbered_match = re.match(r"^(?P<title>.+?)\s*\((?P<index>\d+(?:[.,]\d+)?)\)$", text)
        if numbered_match:
            display_title = clean_title_fragment(numbered_match.group("title"))
            return {
                "series": display_title,
                "series_index": numbered_match.group("index").replace(",", "."),
                "display_title": display_title,
                "sort_title": self._sort_title(display_title),
                "subtitle": self._subtitle(display_title),
            }
        return {
            "series": "",
            "series_index": "",
            "display_title": clean_title_fragment(text),
            "sort_title": self._sort_title(text),
            "subtitle": self._subtitle(text),
        }

    def _sort_title(self, title: str) -> str:
        text = clean_title_fragment(title)
        return re.sub(r"^(das|der|die|the|a|an|le|la|les)\s+", "", text, flags=re.IGNORECASE).strip() or text

    def _subtitle(self, title: str) -> str:
        text = clean_title_fragment(title)
        for separator in (" - ", ": "):
            if separator in text:
                return clean_title_fragment(text.split(separator, 1)[1])
        return ""

    def _pick_cover_url(
        self,
        candidates: list[MetadataCandidate],
        *,
        fallback: str,
        fallback_author: str,
        online_results: list[dict[str, Any]],
    ) -> str:
        for candidate in sorted(candidates, key=lambda item: item.confidence, reverse=True):
            value = str(candidate.extra.get("cover_url") or "").strip()
            if value.startswith("http://") or value.startswith("https://"):
                return value

        for result in online_results:
            value = str(result.get("cover_url") or "").strip()
            if value.startswith("http://") or value.startswith("https://"):
                return value

        if fallback:
            lower_title = canonical_text(fallback)
            lower_author = canonical_text(fallback_author)
            for result in online_results:
                title = canonical_text(str(result.get("title") or ""))
                author = canonical_text(str(result.get("author") or ""))
                if lower_title and lower_title in title and (not lower_author or lower_author in author):
                    value = str(result.get("cover_url") or "").strip()
                    if value.startswith("http://") or value.startswith("https://"):
                        return value
        return ""

    def _path_candidates(self, path: Path) -> list[MetadataCandidate]:
        candidates: list[MetadataCandidate] = []
        raw_stem = path.stem
        parent_label = path.parent.name if path.parent != path else ""
        grandparent_label = path.parent.parent.name if path.parent.parent != path.parent else ""
        candidates.extend(self._parse_label_candidates(raw_stem, source_prefix="filename"))

        cleaned_parent = cleanup_label_text(parent_label)
        cleaned_grandparent = cleanup_label_text(grandparent_label)
        if self._is_generic_path_label(cleaned_parent):
            cleaned_parent = ""
        if self._is_generic_path_label(cleaned_grandparent):
            cleaned_grandparent = ""
        if cleaned_parent and not is_generic_file_stem(parent_label):
            parent_candidates = self._parse_label_candidates(parent_label, source_prefix="path.parent")
            candidates.extend(parent_candidates)
            if looks_like_person_name(cleaned_parent):
                candidates.append(
                    MetadataCandidate(
                        title="",
                        author=clean_author_fragment(cleaned_parent),
                        source="path.parent.author_only",
                        confidence=0.52,
                        evidence=cleaned_parent,
                    )
                )
        if cleaned_grandparent and cleaned_grandparent != cleaned_parent and not is_generic_file_stem(grandparent_label):
            candidates.extend(self._parse_label_candidates(grandparent_label, source_prefix="path.grandparent"))

        filename_title_candidates = [item for item in candidates if item.source.startswith("filename") and item.title]
        parent_author_candidates = [item for item in candidates if item.source.startswith("path.parent") and item.author]
        if filename_title_candidates and parent_author_candidates:
            best_title = max(filename_title_candidates, key=lambda item: item.confidence)
            best_author = max(parent_author_candidates, key=lambda item: item.confidence)
            if best_title.title and best_author.author and not best_title.author:
                candidates.append(
                    MetadataCandidate(
                        title=best_title.title,
                        author=best_author.author,
                        source="path.filename_parent_combo",
                        confidence=min((best_title.confidence + best_author.confidence) / 2.0 + 0.08, 0.88),
                        evidence=f"{raw_stem} | {parent_label}",
                    )
                )

        if is_generic_file_stem(raw_stem) and cleaned_parent:
            parent_title = clean_title_fragment(parent_label)
            if parent_title:
                candidates.append(
                    MetadataCandidate(
                        title=parent_title,
                        author="",
                        source="path.parent_title",
                        confidence=0.74,
                        evidence=parent_label,
                    )
                )
        return candidates

    def _is_generic_path_label(self, label: str) -> bool:
        cleaned = cleanup_label_text(label).casefold()
        if not cleaned:
            return True
        if cleaned in GENERIC_PATH_LABELS:
            return True
        if re.fullmatch(r"(epub|pdf|txt|mobi|azw3?|fb2|cbz|cbr)s?", cleaned):
            return True
        if re.fullmatch(r"(fanfic|fanfiction|ebooks?)(\s+[a-z0-9]+)?", cleaned):
            return True
        return False

    def _parse_label_candidates(self, label: str, *, source_prefix: str) -> list[MetadataCandidate]:
        raw = repair_mojibake(label or "").strip()
        cleaned = cleanup_label_text(raw)
        if not cleaned:
            return []
        candidates: list[MetadataCandidate] = []
        path_label = source_prefix == "filename" or source_prefix.startswith("path.")

        def append_by_pattern_candidate() -> None:
            match = FRONTMATTER_BY_RE.match(cleaned)
            if not match:
                return
            marker = match.group("marker")
            title = clean_title_fragment(match.group("title"))
            author = clean_author_fragment(match.group("author"))
            if not self._accept_by_pattern(
                cleaned,
                source_prefix=source_prefix,
                marker=marker,
                title=title,
                author=author,
            ):
                return
            if title or author:
                candidates.append(
                    MetadataCandidate(
                        title=title,
                        author=author,
                        source=f"{source_prefix}.by_pattern",
                        confidence=0.78 if path_label else 0.82,
                        evidence=cleaned,
                    )
                )

        if not path_label:
            append_by_pattern_candidate()

        if "__" in raw:
            left, right = raw.split("__", 1)
            author = clean_author_fragment(left)
            title = clean_title_fragment(right)
            if title or author:
                candidates.append(
                    MetadataCandidate(
                        title=title,
                        author=author,
                        source=f"{source_prefix}.double_underscore",
                        confidence=0.84,
                        evidence=cleaned,
                    )
                )

        dash_text = cleaned
        if " - " in dash_text:
            parts = [part.strip() for part in dash_text.split(" - ") if part.strip()]
            left = " - ".join(parts[:-1]) if len(parts) > 1 else ""
            first = parts[0] if parts else ""
            middle_right = " - ".join(parts[1:]) if len(parts) > 1 else ""
            right = parts[-1] if len(parts) > 1 else ""
            left_clean = clean_title_fragment(left)
            right_clean = clean_title_fragment(right)
            right_author = clean_author_fragment(right)
            left_author = clean_author_fragment(left)
            first_author = clean_author_fragment(first)
            right_is_author = self._looks_like_author_label(right_author, strong_delimiter=True)
            left_is_author = len(parts) == 2 and self._looks_like_author_label(left_author, strong_delimiter=True)
            first_is_author = (
                len(parts) > 2
                and not self._looks_like_series_prefix(first_author)
                and self._looks_like_author_label(first_author, strong_delimiter=True)
            )
            right_looks_like_title_phrase = self._looks_like_title_phrase(right)
            left_looks_like_title_phrase = self._looks_like_title_phrase(left)
            added_dash_candidate = False
            if right_is_author and (not left_is_author or left_looks_like_title_phrase or len(parts) > 2):
                candidates.append(
                    MetadataCandidate(
                        title=left_clean,
                        author=right_author,
                        source=f"{source_prefix}.title_dash_author",
                        confidence=0.86 if not first_is_author else 0.8,
                        evidence=cleaned,
                    )
                )
                added_dash_candidate = True
            if first_is_author:
                first_author_confidence = 0.88 if ("," in first_author or looks_like_author_handle(first_author)) else 0.78
                candidates.append(
                    MetadataCandidate(
                        title=clean_title_fragment(middle_right),
                        author=first_author,
                        source=f"{source_prefix}.author_dash_title",
                        confidence=first_author_confidence,
                        evidence=cleaned,
                    )
                )
                added_dash_candidate = True
            elif left_is_author and (
                not right_is_author
                or right_looks_like_title_phrase
                or "," in left_author
                or looks_like_author_handle(left_author)
            ):
                candidates.append(
                    MetadataCandidate(
                        title=clean_title_fragment(right),
                        author=left_author,
                        source=f"{source_prefix}.author_dash_title",
                        confidence=0.82,
                        evidence=cleaned,
                    )
                )
                added_dash_candidate = True
            if not added_dash_candidate:
                candidates.append(
                    MetadataCandidate(
                        title=clean_title_fragment(left),
                        author=clean_author_fragment(right),
                        source=f"{source_prefix}.dash_ambiguous",
                        confidence=0.6,
                        evidence=cleaned,
                    )
                )
                candidates.append(
                    MetadataCandidate(
                        title=clean_title_fragment(right),
                        author=clean_author_fragment(left),
                        source=f"{source_prefix}.dash_ambiguous_reverse",
                        confidence=0.52,
                        evidence=cleaned,
                    )
                )

        if path_label:
            append_by_pattern_candidate()

        if "," in cleaned and not any(candidate.author for candidate in candidates):
            candidates.append(
                MetadataCandidate(
                    title="",
                    author=clean_author_fragment(cleaned),
                    source=f"{source_prefix}.comma_author",
                    confidence=0.56,
                    evidence=cleaned,
                )
            )
        elif looks_like_person_name(cleaned):
            candidates.append(
                MetadataCandidate(
                    title="",
                    author=clean_author_fragment(cleaned),
                    source=f"{source_prefix}.author_only",
                    confidence=0.64,
                    evidence=cleaned,
                )
            )

        if not looks_like_noise(cleaned):
            candidates.append(
                MetadataCandidate(
                    title=clean_title_fragment(cleaned),
                    author="",
                    source=f"{source_prefix}.title_only",
                    confidence=0.46 if is_generic_file_stem(raw) else 0.58,
                    evidence=cleaned,
                )
            )
        return candidates

    def _looks_like_author_label(self, value: str, *, strong_delimiter: bool) -> bool:
        if looks_like_person_name(value):
            return True
        if not strong_delimiter:
            return False
        if looks_like_author_handle(value):
            return True
        return self._looks_like_delimited_author(value)

    def _looks_like_series_prefix(self, value: str) -> bool:
        text = cleanup_label_text(value)
        return bool(
            re.search(r"\b(Bd|Band|Teil|Book|Vol|Volume)\.?\s*\d+\b", text, flags=re.IGNORECASE)
            or re.search(r"\.\d{1,3}\b", text)
        )

    def _looks_like_delimited_author(self, value: str) -> bool:
        text = clean_author_fragment(value)
        if not text or len(text) > 70:
            return False
        if any(marker in text for marker in (":", "!", "?", " - ")):
            return False
        parts = [part for part in re.split(r"[\s,;/•·-]+", text) if part]
        if not parts or len(parts) > 5:
            return False
        if parts[0].casefold() in {"das", "der", "die", "the", "a", "an"}:
            return False
        capitalized = 0
        for part in parts:
            if part.casefold() in AUTHOR_PARTICLES:
                capitalized += 1
                continue
            if re.fullmatch(r"[A-ZÄÖÜ]\.?", part):
                capitalized += 1
                continue
            if part[:1].isupper() or any(character.isupper() for character in part[1:]):
                capitalized += 1
        return capitalized >= max(1, len(parts) - 1)

    def _accept_by_pattern(
        self,
        cleaned: str,
        *,
        source_prefix: str,
        marker: str,
        title: str,
        author: str,
    ) -> bool:
        path_label = source_prefix == "filename" or source_prefix.startswith("path.")
        if not title or not author:
            return False
        if not path_label:
            return self._plausible_author(author)
        if title.casefold() in {"kopie", "copy"} or cleaned.casefold().startswith(("kopie von ", "copy of ")):
            return False
        if marker.casefold() == "von":
            if " - " in author or "__" in author:
                return False
            return self._looks_like_author_label(author, strong_delimiter=True)
        return self._looks_like_author_label(author, strong_delimiter=True)

    def _looks_like_title_phrase(self, value: str) -> bool:
        repaired = repair_mojibake(value or "").strip()
        if not repaired:
            return False
        words = [word for word in re.findall(r"[A-Za-zÄÖÜäöüßÁÉÍÓÚáéíóúÑñÇç'`.-]+", repaired) if word]
        if len(words) < 2:
            return False
        return any(
            word[:1].islower() and word.casefold() not in AUTHOR_PARTICLES
            for word in words[1:]
        )

    def _epub_candidates(self, source: Path) -> list[MetadataCandidate]:
        candidates: list[MetadataCandidate] = []
        try:
            book = epub.read_epub(str(source), options={"ignore_ncx": True})
        except Exception:
            return candidates
        titles = [clean_title_fragment(str(value)) for value, _ in book.get_metadata("DC", "title") if value]
        authors = [clean_author_fragment(str(value)) for value, _ in book.get_metadata("DC", "creator") if value]
        languages = [cleanup_label_text(str(value)) for value, _ in book.get_metadata("DC", "language") if value]
        descriptions = [short_text(str(value)) for value, _ in book.get_metadata("DC", "description") if value]
        subjects = [cleanup_label_text(str(value)) for value, _ in book.get_metadata("DC", "subject") if value]
        identifiers = [cleanup_label_text(str(value)) for value, _ in book.get_metadata("DC", "identifier") if value]
        publishers = [cleanup_label_text(str(value)) for value, _ in book.get_metadata("DC", "publisher") if value]
        dates = [cleanup_label_text(str(value)) for value, _ in book.get_metadata("DC", "date") if value]
        title = next((value for value in titles if value), "")
        author = refine_author_fragment(", ".join(value for value in authors[:3] if value))
        language = next((value for value in languages if value), "")
        comment = next((value for value in descriptions if value), "")
        genre = ", ".join(value for value in subjects[:3] if value)
        publisher = next((value for value in publishers if value), "")
        year = 0
        for date_value in dates:
            match = re.search(r"\b(1[6-9]\d{2}|20\d{2}|21\d{2})\b", date_value)
            if match:
                year = int(match.group(1))
                break
        snippet = self._first_epub_text_snippet(book)
        language_info = self._verified_language(
            language,
            "\n".join(part for part in (title, comment, snippet) if part),
        )
        language = language_info["language"] or language
        warnings = list(language_info.get("warnings", []))
        if title or author:
            candidates.append(
                MetadataCandidate(
                    title=title,
                    author=author,
                    language=language,
                    genre=genre,
                    publisher=publisher,
                    comment=comment,
                    source="epub.dc_metadata",
                    confidence=0.97,
                    evidence=source.name,
                    year=year,
                    identifiers=[value for value in identifiers if value],
                    subjects=[value for value in subjects if value],
                    extra={
                        "language_source": language_info["source"],
                        "language_confidence": language_info["confidence"],
                        "original_language": language_info["original_language"],
                        "warnings": warnings,
                        "raw_metadata": {
                            "titles": titles[:3],
                            "creators": authors[:5],
                            "languages": languages[:3],
                            "publisher": publisher,
                            "dates": dates[:3],
                            "subjects": subjects[:5],
                            "identifiers": identifiers[:5],
                        },
                    },
                )
            )
        if not title:
            candidates.extend(self._content_candidates(snippet, source_label="epub.text_frontmatter", confidence=0.62))
        return candidates

    def _pdf_candidates(self, source: Path) -> list[MetadataCandidate]:
        candidates: list[MetadataCandidate] = []
        try:
            reader = PdfReader(str(source))
        except Exception:
            return candidates

        metadata = reader.metadata or {}
        title = clean_title_fragment(str(metadata.get("/Title") or ""))
        author = refine_author_fragment(str(metadata.get("/Author") or ""))
        subject = cleanup_label_text(str(metadata.get("/Subject") or ""))
        if title or author:
            candidates.append(
                MetadataCandidate(
                    title=title,
                    author=author,
                    genre=subject,
                    source="pdf.info_metadata",
                    confidence=0.74,
                    evidence=source.name,
                )
            )
        snippet = self._pdf_frontmatter_text(reader)
        candidates.extend(self._content_candidates(snippet, source_label="pdf.frontmatter", confidence=0.72))
        sibling_txt = next(
            (
                candidate
                for candidate in source.parent.glob("*.txt")
                if candidate.is_file()
            ),
            None,
        )
        if sibling_txt is not None:
            try:
                sidecar_text = sibling_txt.read_text(encoding="utf-8", errors="ignore")[:6000]
            except OSError:
                sidecar_text = ""
            if sidecar_text.strip():
                candidates.extend(self._content_candidates(sidecar_text, source_label="pdf.sidecar_txt", confidence=0.86))
        return candidates

    def _txt_candidates(self, source: Path) -> list[MetadataCandidate]:
        try:
            snippet = source.read_text(encoding="utf-8", errors="ignore")[:6000]
        except OSError:
            return []
        return self._content_candidates(snippet, source_label="txt.frontmatter", confidence=0.78)

    def _first_epub_text_snippet(self, book: epub.EpubBook) -> str:
        for item in book.get_items_of_type(ITEM_DOCUMENT):
            try:
                body = item.get_body_content().decode("utf-8", errors="ignore")
            except Exception:
                continue
            cleaned = repair_mojibake(body)
            if cleaned.strip():
                return cleaned[:4000]
        return ""

    def _verified_language(self, opf_language: str, text: str) -> dict[str, Any]:
        original = cleanup_label_text(opf_language).casefold()
        normalized_opf = self._normalize_language_code(original)
        signal = self._text_language_signal(text)
        if not normalized_opf and signal["language"]:
            return {
                "language": signal["language"],
                "source": "text_heuristic",
                "confidence": signal["confidence"],
                "original_language": original,
                "warnings": [],
            }
        if signal["language"] and signal["confidence"] >= 0.72:
            if normalized_opf and normalized_opf != signal["language"]:
                return {
                    "language": signal["language"],
                    "source": "text_heuristic_conflict",
                    "confidence": signal["confidence"],
                    "original_language": original,
                    "warnings": [
                        f"OPF language {normalized_opf!r} conflicts with strong text signal {signal['language']!r}."
                    ],
                }
            return {
                "language": normalized_opf or signal["language"],
                "source": "opf_text_agree" if normalized_opf else "text_heuristic",
                "confidence": max(signal["confidence"], 0.8),
                "original_language": original,
                "warnings": [],
            }
        return {
            "language": normalized_opf,
            "source": "opf" if normalized_opf else "",
            "confidence": 0.7 if normalized_opf else 0.0,
            "original_language": original,
            "warnings": [],
        }

    def _normalize_language_code(self, value: str) -> str:
        text = (value or "").strip().casefold().replace("_", "-")
        if not text:
            return ""
        if text.startswith("de") or text in {"ger", "deu", "deutsch", "german"}:
            return "de"
        if text.startswith("en") or text in {"eng", "english"}:
            return "en"
        return text.split("-", 1)[0]

    def _text_language_signal(self, text: str) -> dict[str, Any]:
        repaired = repair_mojibake(text or "").casefold()
        words = re.findall(r"[a-zäöüß]+", repaired)
        if not words:
            return {"language": "", "confidence": 0.0, "de_score": 0, "en_score": 0}
        de_score = sum(1 for word in words if word in GERMAN_LANGUAGE_WORDS)
        en_score = sum(1 for word in words if word in ENGLISH_LANGUAGE_WORDS)
        de_score += min(6, sum(1 for char in repaired if char in "äöüß"))
        total = de_score + en_score
        if total < 4:
            return {"language": "", "confidence": 0.0, "de_score": de_score, "en_score": en_score}
        if de_score >= en_score + 4 and de_score >= int(en_score * 1.45):
            confidence = min(0.97, 0.58 + ((de_score - en_score) / max(total, 1)) * 0.42)
            return {"language": "de", "confidence": confidence, "de_score": de_score, "en_score": en_score}
        if en_score >= de_score + 4 and en_score >= int(de_score * 1.45):
            confidence = min(0.97, 0.58 + ((en_score - de_score) / max(total, 1)) * 0.42)
            return {"language": "en", "confidence": confidence, "de_score": de_score, "en_score": en_score}
        return {"language": "", "confidence": 0.0, "de_score": de_score, "en_score": en_score}

    def _pdf_frontmatter_text(self, reader: PdfReader) -> str:
        collected: list[str] = []
        for page in reader.pages[:3]:
            try:
                text = page.extract_text() or ""
            except Exception:
                continue
            if text.strip():
                collected.append(text)
        return "\n".join(collected)[:5000]

    def _content_candidates(self, text: str, *, source_label: str, confidence: float) -> list[MetadataCandidate]:
        candidates: list[MetadataCandidate] = []
        raw_lines = self._raw_frontmatter_lines(text)
        lines = self._frontmatter_lines(text)
        for line in raw_lines[:10]:
            match = QUOTED_TITLE_RE.match(line)
            if match:
                title = clean_title_fragment(match.group("title"))
                author = refine_author_fragment(match.group("author"))
                if self._plausible_title(title) and self._plausible_author(author):
                    candidates.append(
                        MetadataCandidate(
                            title=title,
                            author=author,
                            source=f"{source_label}.quoted_pattern",
                            confidence=confidence + 0.12,
                            evidence=line,
                        )
                    )
            match = FRONTMATTER_BY_RE.match(line)
            if not match:
                continue
            title = clean_title_fragment(match.group("title"))
            author = refine_author_fragment(match.group("author"))
            if self._plausible_title(title) and self._plausible_author(author):
                candidates.append(
                    MetadataCandidate(
                        title=title,
                        author=author,
                        source=f"{source_label}.by_pattern",
                        confidence=confidence + 0.1,
                        evidence=line,
                    )
                )

        for index, line in enumerate(lines[:12]):
            if not looks_like_person_name(line):
                continue
            author_lines = [line]
            cursor = index + 1
            while cursor < min(len(lines), index + 4) and looks_like_person_name(lines[cursor]):
                author_lines.append(lines[cursor])
                cursor += 1
            title_lines: list[str] = []
            back_cursor = index - 1
            while back_cursor >= 0 and len(title_lines) < 4:
                candidate_line = lines[back_cursor]
                if looks_like_person_name(candidate_line):
                    break
                title_lines.insert(0, candidate_line)
                back_cursor -= 1
            if cursor < len(lines) and len(title_lines) < 4:
                trailing = lines[cursor]
                if trailing and not looks_like_person_name(trailing) and not looks_like_noise(trailing):
                    title_lines.append(trailing)
            title = clean_title_fragment(" ".join(title_lines))
            author = refine_author_fragment("; ".join(author_lines))
            if self._plausible_title(title) and self._plausible_author(author):
                candidates.append(
                    MetadataCandidate(
                        title=title,
                        author=author,
                        source=f"{source_label}.title_author_cluster",
                        confidence=confidence,
                        evidence=" | ".join(lines[max(0, index - 2) : min(len(lines), cursor + 2)]),
                    )
                )

        if lines:
            title_only = clean_title_fragment(" ".join(lines[:3]))
            if self._plausible_title(title_only) and not looks_like_person_name(title_only):
                candidates.append(
                    MetadataCandidate(
                        title=title_only,
                        author="",
                        source=f"{source_label}.title_only",
                        confidence=confidence - 0.18,
                        evidence=" | ".join(lines[:3]),
                    )
                )
        return candidates

    def _raw_frontmatter_lines(self, text: str) -> list[str]:
        repaired = repair_mojibake(text or "")
        flattened = repaired.replace("\r", "\n").replace("|", "\n")
        return [cleanup_label_text(item) for item in flattened.splitlines() if cleanup_label_text(item)]

    def _frontmatter_lines(self, text: str) -> list[str]:
        raw_lines = self._raw_frontmatter_lines(text)
        filtered: list[str] = []
        for line in raw_lines:
            if not line or looks_like_noise(line):
                continue
            if not self._plausible_title(line) and not looks_like_person_name(line):
                continue
            if len(line) <= 1:
                continue
            if line in filtered:
                continue
            filtered.append(line)
        return filtered[:30]

    def _pick_online_candidate(
        self,
        online_results: list[dict[str, Any]],
        *,
        title: str,
        author: str,
    ) -> MetadataCandidate | None:
        best_candidate: MetadataCandidate | None = None
        best_score = 0.0
        for result in online_results:
            title_similarity = similarity(result.get("title", ""), title)
            author_similarity = similarity(result.get("author", ""), author)
            if not title and not author:
                continue
            score = (title_similarity * 0.7) + (author_similarity * 0.3)
            if title and not author and title_similarity >= 0.84:
                score += 0.06
            if author and not title and author_similarity >= 0.84:
                score += 0.06
            if score > best_score:
                best_score = score
                best_candidate = online_result_as_candidate(result, confidence=min(0.72 + score * 0.22, 0.95))
        return best_candidate if best_score >= 0.62 else None

    def _prefer_field(self, *, current: str, online: str, current_confidence: float) -> str:
        if current and current_confidence >= 0.9:
            return current
        if current and online and similarity(current, online) < 0.55:
            return current
        return current or online

    def _plausible_title(self, title: str) -> bool:
        if not title:
            return False
        lowered = title.casefold()
        if len(title) > 180 or len(title.split()) > 22:
            return False
        if lowered.startswith(("herausgegeben von", "weitere information", "dieses e-book", "an imprint")):
            return False
        if title in {"(Hrsg )", "Hrsg", "Impressum"}:
            return False
        return True

    def _plausible_author(self, author: str) -> bool:
        if not author:
            return False
        if len(author) > 120:
            return False
        if len(author.split()) > 14:
            return False
        if any(marker in author.casefold() for marker in ("dieses e-book", "weitere information", "impressum")):
            return False
        return True


def extract_metadata_from_source(
    source_path: str | Path,
    *,
    allow_online: bool = True,
    cache_path: Path | None = None,
) -> MetadataExtractionResult:
    extractor = BookMetadataExtractor(cache_path=cache_path)
    return extractor.extract(source_path, allow_online=allow_online)


def guess_metadata_from_filename(source_path: str | Path) -> dict[str, str]:
    extractor = BookMetadataExtractor()
    return extractor.guess_from_filename(source_path)

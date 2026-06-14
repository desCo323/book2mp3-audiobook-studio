from __future__ import annotations

from collections import Counter
from pathlib import Path
import re
from typing import Any

from ebooklib import epub
from pypdf import PdfReader

from .extractor import BookMetadataExtractor
from .normalize import clean_author_fragment, clean_title_fragment, similarity


BY_PATTERN_RE = re.compile(r"^(?P<title>.+?)\s+(?:by|von)\s+(?P<author>.+?)(?:\s*\||\s*$)", re.IGNORECASE)
QUOTED_TITLE_RE = re.compile(r"^(?P<author>[^,\"]{3,80}),\s*[\"“](?P<title>.+?)[\"”](?:\s|$)", re.IGNORECASE)


def _discover_files(root: Path, *, suffixes: set[str] | None = None) -> list[Path]:
    allowed_suffixes = {suffix.lower() for suffix in suffixes} if suffixes else {".epub", ".pdf", ".txt"}
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in allowed_suffixes
    )


def _reference_from_epub(path: Path) -> dict[str, str] | None:
    try:
        book = epub.read_epub(str(path), options={"ignore_ncx": True})
    except Exception:
        return None
    titles = [clean_title_fragment(str(value)) for value, _ in book.get_metadata("DC", "title") if value]
    authors = [clean_author_fragment(str(value)) for value, _ in book.get_metadata("DC", "creator") if value]
    title = next((value for value in titles if value), "")
    author = next((value for value in authors if value), "")
    if title and author:
        return {"title": title, "author": author}
    return None


def _reference_from_txt(path: Path) -> dict[str, str] | None:
    try:
        snippet = path.read_text(encoding="utf-8", errors="ignore")[:1200]
    except OSError:
        return None
    for line in snippet.splitlines():
        quoted_match = QUOTED_TITLE_RE.match(line.strip())
        if quoted_match:
            title = clean_title_fragment(quoted_match.group("title"))
            author = clean_author_fragment(quoted_match.group("author"))
            if title and author:
                return {"title": title, "author": author}
        match = BY_PATTERN_RE.match(line.strip())
        if match:
            title = clean_title_fragment(match.group("title"))
            author = clean_author_fragment(match.group("author"))
            if title and author:
                return {"title": title, "author": author}
    return None


def _reference_from_pdf(path: Path) -> dict[str, str] | None:
    sibling_txt = next((candidate for candidate in path.parent.glob("*.txt") if candidate.is_file()), None)
    if sibling_txt is not None:
        reference = _reference_from_txt(sibling_txt)
        if reference:
            return reference
    try:
        reader = PdfReader(str(path))
    except Exception:
        return None
    metadata = reader.metadata or {}
    title = clean_title_fragment(str(metadata.get("/Title") or ""))
    author = clean_author_fragment(str(metadata.get("/Author") or ""))
    if title and author:
        return {"title": title, "author": author}
    return None


def build_reference_map(root: Path, *, suffixes: set[str] | None = None) -> dict[Path, dict[str, str]]:
    references: dict[Path, dict[str, str]] = {}
    for path in _discover_files(root, suffixes=suffixes):
        if path.suffix.lower() == ".epub":
            reference = _reference_from_epub(path)
        elif path.suffix.lower() == ".pdf":
            reference = _reference_from_pdf(path)
        else:
            reference = _reference_from_txt(path)
        if reference:
            references[path] = reference
    return references


def _pass_metrics(result_title: str, result_author: str, reference: dict[str, str]) -> dict[str, bool]:
    title_ok = similarity(result_title, reference["title"]) >= 0.86
    author_ok = similarity(result_author, reference["author"]) >= 0.84
    return {
        "title_ok": title_ok,
        "author_ok": author_ok,
        "pair_ok": title_ok and author_ok,
    }


def _filename_variants(title: str, author: str) -> list[tuple[str, str]]:
    dotted_title = title.replace(" ", ".")
    slug_title = title.replace(" ", "-")
    return [
        (f"{author} - {title}", author),
        (f"{title} - {author}", author),
        (f"{author}__{slug_title}", author),
        (f"{dotted_title} - {author}", author),
        (f"{title} (1) - {author}", author),
        (f"{slug_title}", author),
    ]


def evaluate_metadata_extractor(
    root: Path,
    *,
    allow_online: bool = False,
    suffixes: set[str] | None = None,
) -> dict[str, Any]:
    extractor = BookMetadataExtractor(cache_path=root.parent / "workspace" / "statistics" / "metadata_online_cache.json")
    files = _discover_files(root, suffixes=suffixes)
    references = build_reference_map(root, suffixes=suffixes)

    case_counter = Counter()
    samples: list[dict[str, Any]] = []

    for path in files:
        case_counter["real_file_cases"] += 1
        reference = references.get(path)
        result = extractor.extract(path, allow_online=allow_online)
        if reference:
            metrics = _pass_metrics(result.title, result.author, reference)
            for key, passed in metrics.items():
                case_counter[f"{key}_passes"] += int(passed)
                case_counter[f"{key}_total"] += 1
            if not metrics["pair_ok"] and len(samples) < 15:
                samples.append(
                    {
                        "kind": "real_file",
                        "path": str(path),
                        "reference": reference,
                        "result": {"title": result.title, "author": result.author, "confidence": result.confidence},
                    }
                )

    for path, reference in references.items():
        for label, parent_author in _filename_variants(reference["title"], reference["author"]):
            case_counter["synthetic_filename_cases"] += 1
            guessed = extractor.parse_filename_label(label, parent_label=parent_author)
            metrics = _pass_metrics(str(guessed.get("title") or ""), str(guessed.get("author") or ""), reference)
            for key, passed in metrics.items():
                case_counter[f"synthetic_{key}_passes"] += int(passed)
                case_counter[f"synthetic_{key}_total"] += 1
            if not metrics["pair_ok"] and len(samples) < 30:
                samples.append(
                    {
                        "kind": "synthetic_filename",
                        "label": label,
                        "reference": reference,
                        "result": {"title": guessed.get("title"), "author": guessed.get("author")},
                    }
                )

    total_cases = case_counter["real_file_cases"] + case_counter["synthetic_filename_cases"]
    return {
        "root": str(root),
        "suffixes": sorted(suffixes) if suffixes else [".epub", ".pdf", ".txt"],
        "file_count": len(files),
        "reference_count": len(references),
        "total_test_cases": int(total_cases),
        "real_file_cases": int(case_counter["real_file_cases"]),
        "synthetic_filename_cases": int(case_counter["synthetic_filename_cases"]),
        "real_pair_accuracy": round(case_counter["pair_ok_passes"] / max(1, case_counter["pair_ok_total"]), 4),
        "real_title_accuracy": round(case_counter["title_ok_passes"] / max(1, case_counter["title_ok_total"]), 4),
        "real_author_accuracy": round(case_counter["author_ok_passes"] / max(1, case_counter["author_ok_total"]), 4),
        "synthetic_pair_accuracy": round(
            case_counter["synthetic_pair_ok_passes"] / max(1, case_counter["synthetic_pair_ok_total"]),
            4,
        ),
        "synthetic_title_accuracy": round(
            case_counter["synthetic_title_ok_passes"] / max(1, case_counter["synthetic_title_ok_total"]),
            4,
        ),
        "synthetic_author_accuracy": round(
            case_counter["synthetic_author_ok_passes"] / max(1, case_counter["synthetic_author_ok_total"]),
            4,
        ),
        "samples": samples,
    }

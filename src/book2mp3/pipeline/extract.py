from __future__ import annotations

from dataclasses import dataclass, field
import re
import unicodedata
from pathlib import Path

from bs4 import BeautifulSoup
from ebooklib import epub
from pypdf import PdfReader


PLAIN_CHAPTER_HEADING_RE = re.compile(
    r"^(?:kapitel|chapter|teil|prolog|epilog|anhang)\b.*$",
    re.IGNORECASE,
)
ROMAN_HEADING_RE = re.compile(r"^(?:[IVXLCDM]+|\d+)(?:[.)-]\s*.*)?$", re.IGNORECASE)


@dataclass
class ExtractedChapter:
    title: str
    text: str


@dataclass
class ExtractedDocument:
    text: str
    chapters: list[ExtractedChapter]
    chapter_detection_method: str = ""
    analysis_notes: list[str] = field(default_factory=list)


@dataclass
class DocumentStructure:
    source_type: str
    chapter_count: int
    chapter_titles: list[str]
    supports_chapter_files: bool
    summary: str
    analysis_status: str = "idle"
    error: str = ""
    detection_method: str = ""
    analysis_notes: list[str] = field(default_factory=list)


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\u00ad", "")
    text = text.replace("\u200b", "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _normalize_heading(text: str) -> str:
    heading = re.sub(r"\s+", " ", text).strip(" -:\t")
    return heading


def _looks_like_heading(line: str) -> bool:
    stripped = line.strip()
    if not stripped or len(stripped) > 90:
        return False
    if PLAIN_CHAPTER_HEADING_RE.match(stripped):
        return True
    if stripped.isupper() and 3 <= len(stripped) <= 60 and not stripped.endswith((".", "!", "?")):
        return True
    if ROMAN_HEADING_RE.match(stripped) and len(stripped.split()) <= 6:
        return True
    return False


def _looks_like_pdf_page_heading(line: str) -> bool:
    stripped = _normalize_heading(line)
    if not stripped or len(stripped) > 80:
        return False
    lowered = stripped.lower()
    if lowered.startswith("seite ") or lowered.startswith("page "):
        return False
    if _looks_like_heading(stripped):
        return True
    words = stripped.split()
    if 1 <= len(words) <= 7 and stripped == stripped.title() and not stripped.endswith((".", "!", "?")):
        return any(word[0].isupper() for word in words if word)
    return False


def _plain_text_chapters(raw_text: str) -> list[ExtractedChapter]:
    text = raw_text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in text.split("\n")]
    chapters: list[ExtractedChapter] = []
    current_title = ""
    current_lines: list[str] = []

    def flush() -> None:
        nonlocal current_title, current_lines
        normalized = normalize_text("\n".join(current_lines))
        if not normalized:
            current_lines = []
            return
        title = _normalize_heading(current_title) if current_title else ""
        chapters.append(ExtractedChapter(title=title, text=normalized))
        current_title = ""
        current_lines = []

    for line in lines:
        stripped = line.strip()
        if _looks_like_heading(stripped):
            flush()
            current_title = stripped
            continue
        current_lines.append(line)
    flush()

    if not chapters:
        normalized = normalize_text(text)
        if normalized:
            return [ExtractedChapter(title="Gesamttext", text=normalized)]
        return []

    if len(chapters) == 1 and not chapters[0].title:
        chapters[0].title = "Gesamttext"
        return chapters

    for index, chapter in enumerate(chapters, start=1):
        if not chapter.title:
            chapter.title = f"Kapitel {index:02d}"
    return chapters


def _join_chapters(
    chapters: list[ExtractedChapter],
    *,
    detection_method: str = "",
    analysis_notes: list[str] | None = None,
) -> ExtractedDocument:
    filtered = [ExtractedChapter(title=chapter.title, text=normalize_text(chapter.text)) for chapter in chapters if normalize_text(chapter.text)]
    if not filtered:
        return ExtractedDocument(text="", chapters=[], chapter_detection_method=detection_method, analysis_notes=analysis_notes or [])
    return ExtractedDocument(
        text=normalize_text("\n\n".join(chapter.text for chapter in filtered)),
        chapters=filtered,
        chapter_detection_method=detection_method,
        analysis_notes=analysis_notes or [],
    )


def _pdf_outline_entries(reader: PdfReader) -> list[tuple[str, int]]:
    try:
        outline = reader.outline
    except Exception:
        return []

    entries: list[tuple[str, int]] = []

    def visit(items: object) -> None:
        if isinstance(items, list):
            for item in items:
                visit(item)
            return
        title = _normalize_heading(str(getattr(items, "title", "") or ""))
        if not title:
            return
        try:
            page_index = int(reader.get_destination_page_number(items))
        except Exception:
            return
        entries.append((title, page_index))

    visit(outline)
    filtered: list[tuple[str, int]] = []
    seen_page_indexes: set[int] = set()
    for title, page_index in sorted(entries, key=lambda item: (item[1], item[0].lower())):
        if page_index in seen_page_indexes:
            continue
        filtered.append((title, page_index))
        seen_page_indexes.add(page_index)
    return filtered


def _chapters_from_pdf_outline(page_texts: list[str], outline_entries: list[tuple[str, int]]) -> list[ExtractedChapter]:
    chapters: list[ExtractedChapter] = []
    for index, (title, start_page) in enumerate(outline_entries, start=1):
        if start_page < 0 or start_page >= len(page_texts):
            continue
        next_start = outline_entries[index][1] if index < len(outline_entries) else len(page_texts)
        end_page = max(start_page + 1, next_start)
        joined = normalize_text("\n\n".join(page_texts[start_page:end_page]))
        if not joined:
            continue
        chapters.append(ExtractedChapter(title=title or f"Kapitel {index:02d}", text=joined))
    return chapters


def _chapters_from_pdf_page_headings(page_texts: list[str]) -> list[ExtractedChapter]:
    starts: list[tuple[int, str]] = []
    for page_index, page_text in enumerate(page_texts):
        lines = [line.strip() for line in page_text.splitlines() if line.strip()]
        heading = ""
        for candidate in lines[:6]:
            if _looks_like_pdf_page_heading(candidate):
                heading = _normalize_heading(candidate)
                break
        if not heading:
            continue
        starts.append((page_index, heading))

    if len(starts) < 2:
        return []

    chapters: list[ExtractedChapter] = []
    for index, (start_page, heading) in enumerate(starts, start=1):
        next_start = starts[index][0] if index < len(starts) else len(page_texts)
        joined = normalize_text("\n\n".join(page_texts[start_page:next_start]))
        if len(joined) < 120:
            continue
        chapters.append(ExtractedChapter(title=heading or f"Kapitel {index:02d}", text=joined))
    return chapters if len(chapters) >= 2 else []


def extract_document(source_path: Path) -> ExtractedDocument:
    suffix = source_path.suffix.lower()
    if suffix == ".txt":
        return _join_chapters(_plain_text_chapters(source_path.read_text(encoding="utf-8")))
    if suffix == ".pdf":
        return extract_pdf_document(source_path)
    if suffix == ".epub":
        return extract_epub_document(source_path)
    raise ValueError(f"Unsupported source type: {source_path.suffix}")


def extract_text(source_path: Path) -> str:
    return extract_document(source_path).text


def analyze_document_structure(source_path: Path) -> DocumentStructure:
    suffix = source_path.suffix.lower().lstrip(".")
    try:
        document = extract_document(source_path)
    except Exception as exc:
        return DocumentStructure(
            source_type=suffix or source_path.suffix.lower(),
            chapter_count=0,
            chapter_titles=[],
            supports_chapter_files=False,
            summary=f"Quelle konnte nicht analysiert werden: {exc}",
            analysis_status="error",
            error=str(exc),
            detection_method="error",
            analysis_notes=["Die Quelle ließ sich nicht lesen oder extrahieren."],
        )

    chapter_titles = [
        _normalize_heading(chapter.title)
        for chapter in document.chapters
        if _normalize_heading(chapter.title) and _normalize_heading(chapter.title) != "Gesamttext"
    ]
    chapter_count = len(document.chapters)
    supports_chapter_files = chapter_count >= 2 and len(chapter_titles) >= 2
    detection_method = document.chapter_detection_method or "unknown"
    analysis_notes = list(document.analysis_notes)

    if supports_chapter_files:
        if suffix == "epub":
            summary = f"EPUB-Struktur erkannt: {chapter_count} Kapitel gefunden."
        elif suffix == "pdf" and detection_method == "pdf_outline":
            summary = f"PDF-Inhaltsverzeichnis erkannt: {chapter_count} Kapitel über Lesezeichen/Gliederung gefunden."
        elif suffix == "pdf" and detection_method == "pdf_page_headings":
            summary = f"PDF-Kapitel erkannt: {chapter_count} Kapitel über Seitenanfang-Überschriften gefunden."
        elif suffix == "pdf":
            summary = f"PDF-Kapitel erkannt: {chapter_count} Kapitel über Überschriften gefunden."
        elif suffix == "txt":
            summary = f"Kapitelüberschriften erkannt: {chapter_count} Abschnitte gefunden."
        else:
            summary = f"{chapter_count} Kapitel erkannt."
    else:
        if suffix == "epub":
            summary = "Keine stabile EPUB-Kapitelstruktur für getrennte Kapiteldateien erkannt."
        elif suffix == "pdf":
            summary = "Keine stabilen PDF-Kapitelüberschriften erkannt. Kapiteldateien bleiben deaktiviert."
        elif suffix == "txt":
            summary = "Keine klaren Kapitelüberschriften erkannt. Kapiteldateien bleiben deaktiviert."
        else:
            summary = "Keine ausreichende Kapitelstruktur erkannt."

    return DocumentStructure(
        source_type=suffix or source_path.suffix.lower(),
        chapter_count=chapter_count,
        chapter_titles=chapter_titles,
        supports_chapter_files=supports_chapter_files,
        summary=summary,
        analysis_status="supported" if supports_chapter_files else "unsupported",
        detection_method=detection_method,
        analysis_notes=analysis_notes,
    )


def extract_pdf(source_path: Path) -> str:
    return extract_pdf_document(source_path).text


def extract_pdf_document(source_path: Path) -> ExtractedDocument:
    reader = PdfReader(str(source_path))
    parts: list[str] = []
    for page in reader.pages:
        parts.append(page.extract_text() or "")
    outline_entries = _pdf_outline_entries(reader)
    if len(outline_entries) >= 2:
        chapters = _chapters_from_pdf_outline(parts, outline_entries)
        if len(chapters) >= 2:
            return _join_chapters(
                chapters,
                detection_method="pdf_outline",
                analysis_notes=[
                    f"PDF-Lesezeichen ausgewertet: {len(outline_entries)} Kapitelstart(s) im Inhaltsverzeichnis.",
                    f"Erste Kapitelstarts auf den Seiten: {', '.join(str(page + 1) for _, page in outline_entries[:4])}",
                ],
            )
    page_heading_chapters = _chapters_from_pdf_page_headings(parts)
    if len(page_heading_chapters) >= 2:
        return _join_chapters(
            page_heading_chapters,
            detection_method="pdf_page_headings",
            analysis_notes=[
                f"Kapitelstarts über Seitenanfänge erkannt: {len(page_heading_chapters)} Seite(n) mit Kapitelüberschrift.",
            ],
        )
    return _join_chapters(
        _plain_text_chapters("\n\n".join(parts)),
        detection_method="flat_text",
        analysis_notes=[
            "PDF hatte keine verwertbaren Lesezeichen. Fallback auf reine Textüberschriften verwendet.",
        ],
    )


def extract_epub(source_path: Path) -> str:
    return extract_epub_document(source_path).text


def extract_epub_document(source_path: Path) -> ExtractedDocument:
    book = epub.read_epub(str(source_path))
    chapters = []
    for item_id, _ in book.spine:
        if item_id.lower() == "nav":
            continue
        item = book.get_item_with_id(item_id)
        if item is not None and isinstance(item, epub.EpubHtml):
            chapters.append(item)
    if not chapters:
        chapters = [item for item in book.get_items() if isinstance(item, epub.EpubHtml)]

    texts: list[ExtractedChapter] = []
    for index, chapter in enumerate(chapters, start=1):
        soup = BeautifulSoup(chapter.get_content(), "html.parser")
        heading = ""
        for tag_name in ("h1", "h2", "h3", "title"):
            tag = soup.find(tag_name)
            if tag and tag.get_text(strip=True):
                heading = tag.get_text(" ", strip=True)
                break
        if not heading:
            file_name = getattr(chapter, "file_name", "") or getattr(chapter, "get_name", lambda: "")()
            heading = file_name.rsplit("/", 1)[-1].rsplit(".", 1)[0] if file_name else f"Kapitel {index:02d}"
        text = soup.get_text(separator=" ")
        texts.append(ExtractedChapter(title=_normalize_heading(heading) or f"Kapitel {index:02d}", text=text))
    return _join_chapters(
        texts,
        detection_method="epub_spine",
        analysis_notes=[f"EPUB-Spine ausgewertet: {len(texts)} HTML-Kapitel gelesen."],
    )

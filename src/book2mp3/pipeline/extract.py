from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from bs4 import BeautifulSoup
from ebooklib import epub
from pypdf import PdfReader


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\u00ad", "")
    text = text.replace("\u200b", "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_text(source_path: Path) -> str:
    suffix = source_path.suffix.lower()
    if suffix == ".txt":
        return normalize_text(source_path.read_text(encoding="utf-8"))
    if suffix == ".pdf":
        return extract_pdf(source_path)
    if suffix == ".epub":
        return extract_epub(source_path)
    raise ValueError(f"Unsupported source type: {source_path.suffix}")


def extract_pdf(source_path: Path) -> str:
    reader = PdfReader(str(source_path))
    parts: list[str] = []
    for page in reader.pages:
        parts.append(page.extract_text() or "")
    return normalize_text("\n\n".join(parts))


def extract_epub(source_path: Path) -> str:
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

    texts: list[str] = []
    for chapter in chapters:
        soup = BeautifulSoup(chapter.get_content(), "html.parser")
        text = soup.get_text(separator=" ")
        texts.append(text)
    return normalize_text("\n\n".join(texts))

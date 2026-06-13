from __future__ import annotations

import json
import tempfile
from pathlib import Path

import book2mp3.pipeline.extract as extract


class FakePage:
    def __init__(self, text: str) -> None:
        self._text = text

    def extract_text(self) -> str:
        return self._text


class FakeDestination:
    def __init__(self, title: str, page_index: int) -> None:
        self.title = title
        self.page_index = page_index


class FakePdfReader:
    def __init__(self, _path: str) -> None:
        self.pages = [
            FakePage("Kapitel 1\nDie alte Stadt lag still unter dem Regen.\n" * 10),
            FakePage("Die Gassen blieben leer, bis die Uhr am Turm schlug.\n" * 10),
            FakePage("Kapitel 2\nAm Morgen entdeckte Mara die offene Werkstatt.\n" * 10),
            FakePage("Der Geruch nach Holz und Metall hing noch in der Luft.\n" * 10),
            FakePage("Kapitel 3\nSpät am Abend kehrte endlich das Licht zurück.\n" * 10),
        ]
        self.outline = [
            FakeDestination("Kapitel 1", 0),
            FakeDestination("Kapitel 2", 2),
            FakeDestination("Kapitel 3", 4),
        ]

    def get_destination_page_number(self, item: FakeDestination) -> int:
        return item.page_index


class FakePdfReaderNoOutline(FakePdfReader):
    def __init__(self, _path: str) -> None:
        super().__init__(_path)
        self.outline = []


def run_case(reader_cls, pdf_path: Path) -> dict[str, object]:
    original_reader = extract.PdfReader
    extract.PdfReader = reader_cls
    try:
        document = extract.extract_pdf_document(pdf_path)
        structure = extract.analyze_document_structure(pdf_path)
    finally:
        extract.PdfReader = original_reader
    return {
        "method": document.chapter_detection_method,
        "chapter_count": len(document.chapters),
        "supports_chapter_files": structure.supports_chapter_files,
        "summary": structure.summary,
        "notes": structure.analysis_notes,
    }


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="book2mp3-smoke-pdf-") as tmp_dir:
        pdf_path = Path(tmp_dir) / "fake.pdf"
        pdf_path.write_bytes(b"%PDF-1.4\n%fake\n")
        outline_case = run_case(FakePdfReader, pdf_path)
        heading_case = run_case(FakePdfReaderNoOutline, pdf_path)
        if outline_case["method"] != "pdf_outline":
            raise AssertionError(f"Expected pdf_outline, got {outline_case}")
        if heading_case["method"] != "pdf_page_headings":
            raise AssertionError(f"Expected pdf_page_headings, got {heading_case}")
        if not outline_case["supports_chapter_files"] or not heading_case["supports_chapter_files"]:
            raise AssertionError("Expected chapter-capable PDF detection in both smoke cases")
        print(
            json.dumps(
                {
                    "outline_case": outline_case,
                    "heading_case": heading_case,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

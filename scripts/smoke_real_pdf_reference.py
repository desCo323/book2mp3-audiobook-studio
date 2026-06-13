from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from PySide6.QtGui import QFont, QPageSize, QPainter, QPdfWriter
from PySide6.QtWidgets import QApplication
from pypdf import PdfReader, PdfWriter

from book2mp3.config import AppPaths
from book2mp3.pipeline.audio import probe_media_duration_seconds
from book2mp3.service import Book2Mp3Service
from book2mp3.tts.piper import PiperBackend
from book2mp3.voice_settings import PROFILE_STATUS_APPROVED, save_voice_setting


ROOT = Path("/home/codex/repo/book2mp3")


def ensure_fixture_link(app_root: Path, name: str) -> None:
    target = ROOT / name
    link = app_root / name
    if link.exists():
        return
    link.symlink_to(target, target_is_directory=True)


def write_pdf(path: Path, pages: list[tuple[str, str]]) -> None:
    writer = QPdfWriter(str(path))
    writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    writer.setResolution(72)
    painter = QPainter(writer)
    painter.setFont(QFont("Helvetica", 14))
    for index, (heading, body) in enumerate(pages):
        painter.drawText(72, 72, heading)
        y = 118
        for line in body.splitlines():
            painter.drawText(72, y, line)
            y += 20
        if index < len(pages) - 1:
            writer.newPage()
    painter.end()


def add_outline(base_pdf: Path, outlined_pdf: Path, titles: list[str]) -> None:
    reader = PdfReader(str(base_pdf))
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    for page_index, title in enumerate(titles):
        writer.add_outline_item(title, page_index)
    with outlined_pdf.open("wb") as handle:
        writer.write(handle)


def repeated_body(seed: str) -> str:
    line = f"{seed} Die Werkstatt blieb still, bis jemand die Lampe wieder einschaltete."
    return "\n".join([line for _ in range(12)])


def select_german_voice(paths: AppPaths) -> str:
    voices = PiperBackend(paths.runtime, paths.voices).installed_voices()
    preferred = [
        "de_DE-thorsten-high",
        "de_DE-thorsten_emotional-medium",
        "de_DE-mls-medium",
        "de_DE-ramona-low",
        "de_DE-kerstin-low",
    ]
    for voice_id in preferred:
        if voice_id in voices:
            return voice_id
    german = [voice_id for voice_id in voices if voice_id.startswith("de_DE-")]
    if german:
        return german[0]
    raise RuntimeError("No German Piper voice found for the real PDF smoke test")


def main() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication([])
    with tempfile.TemporaryDirectory(prefix="book2mp3-smoke-real-pdf-") as tmp_dir:
        app_root = Path(tmp_dir) / "app"
        app_root.mkdir(parents=True, exist_ok=True)
        ensure_fixture_link(app_root, "runtime")
        ensure_fixture_link(app_root, "voices")
        paths = AppPaths.from_project_root(app_root)
        service = Book2Mp3Service(paths)
        service.reset_workspace()

        outline_base = app_root / "outline_base.pdf"
        outline_pdf = app_root / "outline_story.pdf"
        heading_pdf = app_root / "heading_story.pdf"
        flat_pdf = app_root / "flat_story.pdf"

        write_pdf(
            outline_base,
            [
                ("Kapitel 1", repeated_body("Im ersten Kapitel")),
                ("Kapitel 2", repeated_body("Im zweiten Kapitel")),
                ("Kapitel 3", repeated_body("Im dritten Kapitel")),
            ],
        )
        add_outline(outline_base, outline_pdf, ["Kapitel 1", "Kapitel 2", "Kapitel 3"])
        write_pdf(
            heading_pdf,
            [
                ("Kapitel 1", repeated_body("In der alten Gießerei")),
                ("Kapitel 2", repeated_body("Am Morgen danach")),
                ("Kapitel 3", repeated_body("Bevor die Stadt erwachte")),
            ],
        )
        write_pdf(
            flat_pdf,
            [
                ("Vorwort", "Dies ist ein flacher PDF-Text ohne echte Kapiteltrennung.\n" * 24),
            ],
        )

        outline_analysis = service.analyze_source(outline_pdf)
        heading_analysis = service.analyze_source(heading_pdf)
        flat_analysis = service.analyze_source(flat_pdf)

        if outline_analysis["detection_method"] != "pdf_outline":
            raise AssertionError(f"Expected pdf_outline detection, got {outline_analysis}")
        if heading_analysis["detection_method"] != "pdf_page_headings":
            raise AssertionError(f"Expected pdf_page_headings detection, got {heading_analysis}")
        if flat_analysis["supports_chapter_files"]:
            raise AssertionError(f"Flat PDF should not enable chapter files: {flat_analysis}")

        voice_id = select_german_voice(paths)
        approved_profile = save_voice_setting(
            paths.voice_settings,
            display_name="Real PDF Smoke Profile",
            backend="piper",
            voice_id=voice_id,
            voice_profile_id="",
            preset_hint="balanced",
            max_chars=200,
            output_mode="chapter_files",
            target_part_minutes=15,
            sentence_silence=0.2,
            length_scale=1.0,
            status=PROFILE_STATUS_APPROVED,
            notes="Real PDF smoke profile",
        )
        created = service.create_job(
            source_path=outline_pdf,
            saved_profile_id=approved_profile.setting_id,
            output_mode="chapter_files",
        )
        finished = service.run_job(created["job_id"])
        if finished["status"] != "completed":
            raise AssertionError(f"Expected completed PDF job, got {finished['status']}")
        if len(finished["final_output_files"]) != 3:
            raise AssertionError(f"Expected 3 chapter MP3s, got {finished['final_output_files']}")
        durations = {
            Path(output).name: round(probe_media_duration_seconds(Path(output)), 3)
            for output in finished["final_output_files"]
        }
        print(
            json.dumps(
                {
                    "outline_analysis": outline_analysis,
                    "heading_analysis": heading_analysis,
                    "flat_analysis": flat_analysis,
                    "pdf_job_id": finished["job_id"],
                    "pdf_job_status": finished["status"],
                    "pdf_output_count": len(finished["final_output_files"]),
                    "pdf_output_durations": durations,
                    "manifest_file": finished["manifest_file"],
                    "chapters_file": finished["chapters_file"],
                },
                indent=2,
                ensure_ascii=False,
            )
        )
    app.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

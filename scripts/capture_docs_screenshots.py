from __future__ import annotations

import math
import os
from pathlib import Path
import sys
import wave

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from book2mp3.config import AppPaths
from book2mp3.pipeline.jobs import JobManager
from book2mp3.service import Book2Mp3Service
from book2mp3.tts.piper import PiperBackend
from book2mp3.ui.find_best_setting_dialog import FindBestSettingDialog
from book2mp3.ui.main_window import MainWindow
from book2mp3.voice_lab import create_voice_profile
from book2mp3.voice_settings import PROFILE_STATUS_APPROVED, save_voice_setting


def create_demo_wav(target: Path, seconds: float = 4.0, sample_rate: int = 22050) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    frames = int(seconds * sample_rate)
    with wave.open(str(target), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        for i in range(frames):
            sample = int(10000 * math.sin(2.0 * math.pi * 220.0 * (i / sample_rate)))
            wav_file.writeframesraw(sample.to_bytes(2, byteorder="little", signed=True))


def screenshot(widget, target: Path, size: QSize | None = None) -> None:
    if size is not None:
        widget.resize(size)
    widget.show()
    QApplication.processEvents()
    pixmap = widget.grab()
    target.parent.mkdir(parents=True, exist_ok=True)
    pixmap.save(str(target))


def select_tab(window: MainWindow, label: str) -> None:
    for index in range(window.main_tabs.count()):
        if window.main_tabs.tabText(index) == label:
            window.main_tabs.setCurrentIndex(index)
            QApplication.processEvents()
            return
    raise RuntimeError(f"Tab not found: {label}")


def prepare_demo_state(project_root: Path) -> AppPaths:
    paths = AppPaths.from_project_root(project_root)
    service = Book2Mp3Service(paths)
    service.reset_workspace()
    paths.ensure()

    demo_source = paths.workspace / "demo_story.txt"
    demo_source.write_text(
        "\n".join(
            [
                "Kapitel 1",
                "Im alten Bahnhof lag noch etwas Morgenkühle in der Luft. Mara hob den Koffer an und ging zwischen den leeren Bänken hindurch.",
                "",
                "Kapitel 2",
                "Auf dem Bahnsteig summte nur eine einzelne Lampe. Sie hörte aus der Ferne das erste Rollen der Räder und sah den Nebel über den Schienen tanzen.",
                "",
                "Kapitel 3",
                "Als der Zug einfuhr, klappte sie ihr Notizbuch auf. Diesmal wollte sie jedes Detail festhalten und daraus später ein ganzes Hörbuch machen.",
            ]
        ),
        encoding="utf-8",
    )

    piper_backend = PiperBackend(paths.runtime, paths.voices)
    voices = piper_backend.installed_voices()
    if not voices:
        raise RuntimeError("No Piper voices installed for screenshots.")
    demo_voice = voices[0]

    save_voice_setting(
        paths.voice_settings,
        display_name="Roman Deutsch Standard",
        backend="piper",
        voice_id=demo_voice,
        voice_profile_id="",
        preset_hint="balanced",
        max_chars=240,
        output_mode="chapter_files",
        target_part_minutes=15,
        sentence_silence=0.22,
        length_scale=1.0,
        notes="Freigegebenes Demo-Produktionsprofil für die Dokumentation.",
        status=PROFILE_STATUS_APPROVED,
        ensure_unique_name=False,
        setting_id="roman_deutsch_standard",
    )

    sample_wav = paths.workspace / "demo_voice.wav"
    create_demo_wav(sample_wav)
    create_voice_profile(
        paths.voice_profiles,
        display_name="XTTS Demo Sprecherin",
        target_language="de",
        backend="xtts_v2",
        notes="Synthetisches Demo-Profil für Dokumentations-Screenshots.",
        sample_paths=[sample_wav],
    )
    save_voice_setting(
        paths.voice_settings,
        display_name="XTTS Natürlich Deutsch",
        backend="xtts",
        voice_id="",
        voice_profile_id="xtts_demo_sprecherin",
        preset_hint="premium_natural",
        max_chars=260,
        output_mode="chapter_files",
        target_part_minutes=15,
        sentence_silence=0.18,
        length_scale=1.0,
        notes="Freigegebenes XTTS-Demo-Profil für die Dokumentation.",
        status=PROFILE_STATUS_APPROVED,
        ensure_unique_name=False,
        setting_id="xtts_natuerlich_deutsch",
    )

    completed = service.create_job(
        source_path=demo_source,
        profile_id="roman_deutsch_standard",
        priority=70,
    )
    service.run_job(completed["job_id"])

    queued = service.create_job(
        source_path=demo_source,
        profile_id="roman_deutsch_standard",
        priority=45,
    )
    service.enqueue_job(queued["job_id"])
    return paths


def main() -> int:
    project_root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT
    output_dir = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else project_root / "docs" / "assets"
    paths = prepare_demo_state(project_root)

    app = QApplication.instance() or QApplication([])

    window = MainWindow(paths)
    window.refresh_jobs()
    window.set_selected_source_files([paths.workspace / "demo_story.txt"])
    QApplication.processEvents()
    if window.jobs_list.count() > 1:
        window.jobs_list.setCurrentRow(1)
    elif window.jobs_list.count():
        window.jobs_list.setCurrentRow(0)
    QApplication.processEvents()

    screenshot(window, output_dir / "screenshot-main-window.png", QSize(1560, 980))
    select_tab(window, "Aufträge")
    if window.jobs_list.count() > 1:
        window.jobs_list.setCurrentRow(1)
    QApplication.processEvents()
    screenshot(window, output_dir / "screenshot-jobs.png", QSize(1560, 980))
    select_tab(window, "XTTS-Profile")
    screenshot(window, output_dir / "screenshot-xtts-profiles.png", QSize(1560, 980))

    dialog = FindBestSettingDialog(paths, JobManager(paths), focus_assistant=True)
    dialog.current_source = paths.workspace / "demo_story.txt"
    dialog.source_label.setText(str(dialog.current_source))
    dialog.create_session()
    dialog.resize(1460, 980)
    screenshot(dialog, output_dir / "screenshot-benchmark-studio.png", QSize(1460, 980))

    dialog.close()
    window.close()
    app.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
import time
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox

from book2mp3.config import AppPaths
from book2mp3.pipeline.audio import probe_media_duration_seconds
from book2mp3.service import Book2Mp3Service
from book2mp3.tts.piper import PiperBackend
from book2mp3.ui.main_window import MainWindow
from book2mp3.voice_settings import PROFILE_STATUS_APPROVED, save_voice_setting


ROOT = Path("/home/codex/repo/book2mp3")


def ensure_fixture_link(app_root: Path, name: str) -> None:
    target = ROOT / name
    link = app_root / name
    if link.exists():
        return
    link.symlink_to(target, target_is_directory=True)


STORY_TEXT = """Kapitel 1
Im alten Bahnhof von Sommerfeld stand jede Nacht eine Lampe unter dem Vordach, obwohl seit Jahren kein Zug mehr dort hielt.
Mira bemerkte das Licht auf dem Heimweg und glaubte zuerst an einen vergesslichen Hausmeister. Doch als sie naeher kam, sah sie,
dass die Lampe immer genau dann heller wurde, wenn der Wind ueber die rostigen Schienen strich.

Kapitel 2
Am naechsten Abend brachte sie ihren Freund Jona mit. Gemeinsam fanden sie hinter dem Fahrplankasten ein duennes Heft,
in dem der letzte Bahnhofsvorsteher kurze Geschichten ueber gestrandete Reisende gesammelt hatte. Jede Geschichte endete mit demselben Satz:
Wer zuhoert, findet den Weg nach Hause. Als Mira die Worte laut las, vibrierte die Lampe wie eine kleine Glocke.

Kapitel 3
In der dritten Nacht nahmen sie eine Thermoskanne Tee mit und lasen dem leeren Bahnsteig weiter vor. Mit jedem Kapitel wurde die Luft waermer,
und kurz vor Mitternacht rollte ein silberner Schein ueber die Schienen, als ob ein unsichtbarer Zug ein letztes Mal einfahren wuerde.
Als das Licht verschwand, war das Heft leer. Nur auf der letzten Seite stand noch ein Dankesgruss, und die Lampe am Bahnsteig blieb von da an dunkel."""


def select_german_voice(paths: AppPaths) -> str:
    voices = PiperBackend(paths.runtime, paths.voices).installed_voices()
    preferred = [
        "de_DE-thorsten-high",
        "de_DE-thorsten_emotional-medium",
        "de_DE-mls-medium",
        "de_DE-kerstin-low",
        "de_DE-eva_k-x_low",
    ]
    for voice_id in preferred:
        if voice_id in voices:
            return voice_id
    german = [voice_id for voice_id in voices if voice_id.startswith("de_DE-")]
    if german:
        return german[0]
    raise RuntimeError("No German Piper voice found for the real story smoke test")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--app-root",
        help=(
            "Optional existing app root to test directly. "
            "When omitted, the smoke test creates a temporary app root and copies runtime/ and voices/."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    temp_dir: tempfile.TemporaryDirectory[str] | None = None
    try:
        if args.app_root:
            app_root = Path(args.app_root).resolve()
        else:
            temp_dir = tempfile.TemporaryDirectory(prefix="book2mp3-smoke-story-")
            app_root = Path(temp_dir.name) / "app"
            app_root.mkdir(parents=True, exist_ok=True)
            ensure_fixture_link(app_root, "runtime")
            ensure_fixture_link(app_root, "voices")

        paths = AppPaths.from_project_root(app_root)
        service = Book2Mp3Service(paths)
        service.reset_workspace()

        source = app_root / "kurzgeschichte.txt"
        source.write_text(STORY_TEXT, encoding="utf-8")

        app = QApplication([])
        QMessageBox.information = staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Ok)
        QMessageBox.warning = staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Ok)
        QMessageBox.question = staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Yes)

        window = MainWindow(paths)
        voice_id = select_german_voice(paths)
        approved_profile = save_voice_setting(
            paths.voice_settings,
            display_name="Smoke Story Approved",
            backend="piper",
            voice_id=voice_id,
            voice_profile_id="",
            preset_hint="natural",
            max_chars=220,
            output_mode="chapter_files",
            target_part_minutes=15,
            sentence_silence=0.28,
            length_scale=1.05,
            status=PROFILE_STATUS_APPROVED,
            notes="Automatisch freigegeben für den echten Story-Smoke",
        )
        window.refresh_saved_profiles()
        window.source_edit.setText(str(source))
        if not window.job_output_chapter_radio.isEnabled():
            raise AssertionError("Chapter output should be enabled for the chaptered smoke story")
        approved_index = window.saved_profile_combo.findData(approved_profile.setting_id)
        if approved_index < 0:
            raise AssertionError(f"Approved profile not visible in job dialog: {approved_profile.setting_id}")
        window.saved_profile_combo.setCurrentIndex(approved_index)
        window.priority_spin.setValue(80)

        window.create_job()
        assert window.current_job_id, "Expected create_job to populate current_job_id"
        window.start_selected_job()

        deadline = time.time() + 240
        while window.worker and window.worker.isRunning() and time.time() < deadline:
            app.processEvents()
            time.sleep(0.1)

        if window.worker and window.worker.isRunning():
            raise AssertionError("Real story GUI job did not finish in time")

        state = window.manager.load_state(window.current_job_id)
        assert state.status == "completed", state.status
        assert len(state.final_output_files) >= 1
        assert len(state.chapters) >= 3

        durations = {}
        for output_file in state.final_output_files:
            path = Path(output_file)
            assert path.exists()
            assert path.stat().st_size > 0
            durations[path.name] = round(probe_media_duration_seconds(path), 3)

        chapters_payload = json.loads(Path(state.chapters_file).read_text(encoding="utf-8"))
        assert chapters_payload["timeline_kind"] == "chapter"

        print(
            json.dumps(
                {
                    "app_root": str(app_root),
                    "job_id": state.job_id,
                    "status": state.status,
                    "voice_id": voice_id,
                    "profile_id": approved_profile.setting_id,
                    "chapter_count": len(state.chapters),
                    "chapter_output_enabled": window.job_output_chapter_radio.isEnabled(),
                    "job_output_mode": state.output_mode,
                    "outputs": state.final_output_files,
                    "durations": durations,
                    "manifest_file": state.manifest_file,
                    "chapters_file": state.chapters_file,
                },
                indent=2,
                ensure_ascii=False,
            )
        )

        window.close()
        app.quit()
    finally:
        if temp_dir is not None:
            temp_dir.cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

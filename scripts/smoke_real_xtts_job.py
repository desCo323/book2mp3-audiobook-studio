from __future__ import annotations

import json
import tempfile
from pathlib import Path

from book2mp3.config import AppPaths
from book2mp3.pipeline.audio import probe_media_duration_seconds
from book2mp3.pipeline.jobs import JobManager
from book2mp3.presets import get_preset
from book2mp3.utils.logging_utils import configure_logging
from book2mp3.voice_lab import list_voice_profiles


ROOT = Path("/home/codex/repo/book2mp3")


XTTS_TEXT = """Kapitel 1
In der stillen Seitenstrasse summte der Regen an den Fenstern, waehrend Lena den Schluessel zu dem kleinen Atelier drehte.

Kapitel 2
Auf dem Tisch lag nur ein einziger Zettel: Male heute nichts, sondern hoere zuerst zu.

Kapitel 3
Als sie das Licht einschaltete, antwortete der Raum mit einem warmen Echo, und fuer einen Moment klang es so, als beginne das Haus selbst zu erzaehlen."""


def choose_profile(paths: AppPaths) -> str:
    preferred = [
        "xtts_kerstin_hq_female",
        "xtts_thorsten_neutral",
        "xtts_thorsten_emotional",
        "xtts_deutsch_weiblich_warm",
        "xtts_deutsch_weiblich_klar",
    ]
    available = {profile.profile_id for profile in list_voice_profiles(paths.voice_profiles)}
    for profile_id in preferred:
        if profile_id in available:
            return profile_id
    if available:
        return sorted(available)[0]
    raise RuntimeError("No XTTS profile available for the real XTTS smoke test")


def main() -> int:
    paths = AppPaths.from_project_root(ROOT)
    paths.ensure()
    configure_logging(paths.logs)
    manager = JobManager(paths)

    with tempfile.TemporaryDirectory(prefix="book2mp3-real-xtts-") as tmp_dir:
        source = Path(tmp_dir) / "xtts_real_story.txt"
        source.write_text(XTTS_TEXT, encoding="utf-8")
        profile_id = choose_profile(paths)
        preset = get_preset("premium_natural")
        job = manager.create_job(
            source_path=source,
            voice_id="",
            voice_profile_id=profile_id,
            preset_id=preset.preset_id,
            priority=85,
            max_chars=220,
            output_mode="chapter_files",
            target_part_minutes=preset.target_part_minutes,
            keep_wav=False,
            sentence_silence=preset.sentence_silence,
            length_scale=1.0,
            backend="xtts",
        )
        state = manager.run_job(job)

        assert state.status == "completed", state.status
        assert state.final_output_files
        durations = {}
        for output_file in state.final_output_files:
            path = Path(output_file)
            assert path.exists()
            assert path.stat().st_size > 0
            durations[path.name] = round(probe_media_duration_seconds(path, logger=manager.job_logger(state)), 3)

        print(
            json.dumps(
                {
                    "job_id": state.job_id,
                    "status": state.status,
                    "voice_profile_id": profile_id,
                    "outputs": state.final_output_files,
                    "durations": durations,
                    "manifest_file": state.manifest_file,
                    "chapters_file": state.chapters_file,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

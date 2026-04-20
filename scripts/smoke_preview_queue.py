from __future__ import annotations

import json
import tempfile
from pathlib import Path

from book2mp3.config import AppPaths
from book2mp3.pipeline.jobs import JobManager
from book2mp3.preview_sessions import create_preview_session, list_preview_sessions
from book2mp3.presets import get_preset
from book2mp3.tts.piper import PiperBackend
from book2mp3.utils.logging_utils import configure_logging


def main() -> int:
    root = Path("/home/codex/repo/book2mp3")
    paths = AppPaths.from_project_root(root)
    paths.ensure()
    configure_logging(paths.logs)
    manager = JobManager(paths)

    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "preview_queue_source.txt"
        source.write_text(
            ("Dies ist ein Preview-Queue-Test fuer mehrere Vergleichs-MP3s. " * 80).strip(),
            encoding="utf-8",
        )
        voices = PiperBackend(paths.runtime, paths.voices).installed_voices()
        session = create_preview_session(paths, source, voices)
        created_jobs = []
        for test in session.tests[:3]:
            preset = get_preset(test.preset_id)
            job = manager.create_job(
                source_path=Path(session.preview_source_file),
                voice_id=test.voice_id,
                voice_profile_id="",
                preset_id=preset.preset_id,
                priority=96 - test.index,
                max_chars=preset.max_chars,
                output_mode="single_file",
                keep_wav=False,
                sentence_silence=preset.sentence_silence,
                length_scale=preset.length_scale,
            )
            created_jobs.append(job.job_id)

        ordered = []
        for _ in range(3):
            next_job = manager.next_queued_job()
            assert next_job is not None
            ordered.append(next_job.job_id)
            manager.run_job(next_job)

        refreshed = {item.session_id: item for item in list_preview_sessions(paths)}[session.session_id]
        print(
            json.dumps(
                {
                    "session_id": refreshed.session_id,
                    "jobs_created": created_jobs,
                    "queue_order": ordered,
                },
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

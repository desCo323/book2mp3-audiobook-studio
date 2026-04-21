from __future__ import annotations

import json
import tempfile
from pathlib import Path

from book2mp3.config import AppPaths
from book2mp3.pipeline.jobs import JobManager
from book2mp3.preview_sessions import attach_preview_job, create_preview_session, list_preview_sessions
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
        session = create_preview_session(paths, source)
        created_jobs = []
        job = manager.create_job(
            source_path=Path(session.preview_source_file),
            voice_id="de_DE-eva_k-x_low",
            voice_profile_id="",
            preset_id="natural",
            priority=98,
            max_chars=260,
            output_mode="single_file",
            target_part_minutes=20,
            keep_wav=False,
            sentence_silence=0.28,
            length_scale=1.05,
        )
        created_jobs.append(job.job_id)

        next_job = manager.next_queued_job()
        assert next_job is not None
        ordered = [next_job.job_id]
        state = manager.run_job(next_job)
        attach_preview_job(
            paths,
            session.session_id,
            backend="piper",
            voice_id="de_DE-eva_k-x_low",
            voice_profile_id="",
            preset_hint="natural",
            job_id=state.job_id,
            output_mp3=state.final_output_file,
            status="completed",
        )

        refreshed = {item.session_id: item for item in list_preview_sessions(paths)}[session.session_id]
        print(
            json.dumps(
                {
                    "session_id": refreshed.session_id,
                    "jobs_created": created_jobs,
                    "queue_order": ordered,
                    "last_preview_status": refreshed.last_preview_status,
                },
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

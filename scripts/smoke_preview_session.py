from __future__ import annotations

import json
import tempfile
from pathlib import Path

from book2mp3.config import AppPaths
from book2mp3.pipeline.jobs import JobManager
from book2mp3.preview_sessions import (
    attach_preview_job,
    create_preview_session,
    link_saved_setting,
    list_preview_sessions,
    refresh_preview_excerpt,
)
from book2mp3.utils.logging_utils import configure_logging
from book2mp3.voice_settings import save_voice_setting


def main() -> int:
    root = Path("/home/codex/repo/book2mp3")
    paths = AppPaths.from_project_root(root)
    paths.ensure()
    configure_logging(paths.logs)
    manager = JobManager(paths)

    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "preview_source.txt"
        source.write_text(
            ("Dies ist ein kurzer Preview-Text fuer den Find-Best-Setting-Test. " * 60).strip(),
            encoding="utf-8",
        )
        session = create_preview_session(paths, source)
        assert session.preview_excerpt
        initial_excerpt = session.preview_excerpt
        session = refresh_preview_excerpt(paths, session.session_id)
        assert session.preview_excerpt
        voice_id = "de_DE-eva_k-x_low"
        job = manager.create_job(
            source_path=Path(session.preview_source_file),
            voice_id=voice_id,
            voice_profile_id="",
            preset_id="balanced",
            priority=95,
            max_chars=220,
            output_mode="single_file",
            keep_wav=False,
            sentence_silence=0.2,
            length_scale=1.0,
        )
        state = manager.run_job(job)
        assert Path(state.final_output_file).exists()
        attach_preview_job(
            paths,
            session.session_id,
            voice_id=voice_id,
            preset_hint="balanced",
            job_id=state.job_id,
            output_mp3=state.final_output_file,
            status="completed",
        )
        saved = save_voice_setting(
            paths.voice_settings,
            "Smoke Balanced",
            voice_id=voice_id,
            preset_hint="balanced",
            max_chars=220,
            sentence_silence=0.2,
            length_scale=1.0,
        )
        link_saved_setting(paths, session.session_id, saved.setting_id)
        refreshed = {item.session_id: item for item in list_preview_sessions(paths)}[session.session_id]
        assert refreshed.last_preview_job_id == state.job_id
        assert refreshed.saved_setting_id == saved.setting_id
        print(
            json.dumps(
                {
                    "session_id": refreshed.session_id,
                    "excerpt_changed": refreshed.preview_excerpt != initial_excerpt,
                    "saved_setting_id": refreshed.saved_setting_id,
                    "final_output_file": state.final_output_file,
                },
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

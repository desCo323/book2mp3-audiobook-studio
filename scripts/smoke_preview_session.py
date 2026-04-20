from __future__ import annotations

import json
import tempfile
from pathlib import Path

from book2mp3.config import AppPaths
from book2mp3.pipeline.jobs import JobManager
from book2mp3.preview_sessions import choose_preview_case, create_preview_session, list_preview_sessions
from book2mp3.tts.piper import PiperBackend
from book2mp3.utils.logging_utils import configure_logging


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
        voices = PiperBackend(paths.runtime, paths.voices).installed_voices()
        session = create_preview_session(paths, source, voices)
        assert len(session.tests) <= 10
        assert len(session.tests) > 0
        first = session.tests[0]
        from book2mp3.presets import get_preset

        preset = get_preset(first.preset_id)
        job = manager.create_job(
            source_path=Path(session.preview_source_file),
            voice_id=first.voice_id,
            voice_profile_id="",
            preset_id=preset.preset_id,
            priority=95,
            max_chars=preset.max_chars,
            output_mode="single_file",
            keep_wav=False,
            sentence_silence=preset.sentence_silence,
            length_scale=preset.length_scale,
        )
        state = manager.run_job(job)
        assert Path(state.final_output_file).exists()
        choose_preview_case(paths, session.session_id, first.index)
        refreshed = {item.session_id: item for item in list_preview_sessions(paths)}[session.session_id]
        assert refreshed.selected_case_index == first.index
        print(
            json.dumps(
                {
                    "session_id": refreshed.session_id,
                    "tests": len(refreshed.tests),
                    "selected_case_index": refreshed.selected_case_index,
                    "final_output_file": state.final_output_file,
                },
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

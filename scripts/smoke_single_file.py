from __future__ import annotations

import json
import tempfile
from pathlib import Path

from book2mp3.config import AppPaths
from book2mp3.pipeline.jobs import JobManager
from book2mp3.presets import get_preset
from book2mp3.utils.logging_utils import configure_logging


def main() -> int:
    root = Path("/home/codex/repo/book2mp3")
    paths = AppPaths.from_project_root(root)
    paths.ensure()
    configure_logging(paths.logs)
    manager = JobManager(paths)

    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "single_file_source.txt"
        source.write_text(
            ("Dies ist ein Single-File-Test. " * 120).strip(),
            encoding="utf-8",
        )
        preset = get_preset("natural")
        job = manager.create_job(
            source_path=source,
            voice_id="de_DE-eva_k-x_low",
            voice_profile_id="",
            preset_id=preset.preset_id,
            priority=70,
            max_chars=preset.max_chars,
            output_mode="single_file",
            target_part_minutes=preset.target_part_minutes,
            keep_wav=False,
            sentence_silence=preset.sentence_silence,
            length_scale=preset.length_scale,
        )
        state = manager.run_job(job)
        final_output = Path(state.final_output_file)
        assert state.status == "completed"
        assert final_output.exists()
        assert final_output.stat().st_size > 0
        print(
            json.dumps(
                {
                    "job_id": state.job_id,
                    "status": state.status,
                    "final_output_file": state.final_output_file,
                    "chunks": state.total_chunks,
                },
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

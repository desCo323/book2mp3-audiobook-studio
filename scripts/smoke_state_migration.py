from __future__ import annotations

import json
import tempfile
from pathlib import Path

from book2mp3.config import AppPaths
from book2mp3.pipeline.jobs import JobManager
from book2mp3.utils.logging_utils import configure_logging


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        paths = AppPaths.from_project_root(root)
        paths.ensure()
        configure_logging(paths.logs)
        manager = JobManager(paths)

        job_dir = paths.jobs / "legacy123456"
        job_dir.mkdir(parents=True, exist_ok=True)
        legacy = {
            "job_id": "legacy123456",
            "title": "legacy",
            "source_name": "legacy.txt",
            "source_type": "txt",
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
            "status": "queued",
            "backend": "piper",
            "voice_id": "de_DE-eva_k-x_low",
            "priority": 50,
            "output_mode": "segments",
            "keep_wav": False,
            "max_chars": 220,
            "source_file": str(job_dir / "input" / "legacy.txt"),
            "extracted_file": str(job_dir / "extracted" / "source.txt"),
            "final_output_file": str(job_dir / "output" / "legacy.mp3"),
            "chunks": [],
            "logs": [],
        }
        (job_dir / "state.json").write_text(json.dumps(legacy, indent=2), encoding="utf-8")
        state = manager.load_state("legacy123456")
        assert state.preset_id == "balanced"
        assert state.sentence_silence > 0
        assert state.length_scale > 0
        print(
            json.dumps(
                {
                    "job_id": state.job_id,
                    "preset_id": state.preset_id,
                    "sentence_silence": state.sentence_silence,
                    "length_scale": state.length_scale,
                },
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from book2mp3.config import AppPaths
from book2mp3.models import ChunkRecord
from book2mp3.pipeline.jobs import JobManager
from book2mp3.presets import get_preset


def _source(root: Path) -> Path:
    path = root / "source.txt"
    path.write_text("Kapitel Eins. Ein kurzer XTTS Recovery Test.", encoding="utf-8")
    return path


def _add_chunk(paths: AppPaths, state, *, status: str = "pending") -> None:
    job_dir = state.job_dir(paths.jobs)
    chunks_dir = job_dir / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)
    output_dir = job_dir / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    text_path = chunks_dir / "00001.txt"
    text = "Aurelia sah Bercelak an und schwieg einen Moment."
    text_path.write_text(text, encoding="utf-8")
    state.chunks = [
        ChunkRecord(
            index=1,
            text_file=str(text_path),
            wav_file=str(output_dir / "00001.wav"),
            mp3_file=str(output_dir / "00001.mp3"),
            text_length=len(text),
            status=status,
        )
    ]


def _create_xtts_job(manager: JobManager, paths: AppPaths, source: Path):
    preset = get_preset("premium_natural")
    return manager.create_job(
        source_path=source,
        voice_id="",
        voice_profile_id="fake-profile",
        preset_id=preset.preset_id,
        priority=50,
        max_chars=120,
        output_mode="single_file",
        target_part_minutes=preset.target_part_minutes,
        keep_wav=False,
        sentence_silence=preset.sentence_silence,
        length_scale=1.0,
        backend="xtts",
    )


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="book2mp3-smoke-startup-recovery-") as tmp_dir:
        root = Path(tmp_dir)
        paths = AppPaths.from_project_root(root)
        paths.ensure()
        manager = JobManager(paths)
        source = _source(root)

        completed = _create_xtts_job(manager, paths, source)
        _add_chunk(paths, completed)
        completed.status = "completed"
        completed.final_output_files = [str(completed.job_dir(paths.jobs) / "output" / "book.mp3")]
        manager.save_state(completed)

        guarded = manager._rechunk_xtts_job_chunks_if_needed(
            manager.load_state(completed.job_id),
            logger=manager.job_logger(completed),
        )
        assert guarded.status == "completed", guarded.status
        assert guarded.final_output_files == completed.final_output_files
        assert len(guarded.chunks) == 1

        queued = _create_xtts_job(manager, paths, source)
        _add_chunk(paths, queued)
        manager.save_state(queued)

        running = _create_xtts_job(manager, paths, source)
        _add_chunk(paths, running)
        running.status = "running"
        manager.save_state(running)

        rechunk_calls: list[str] = []

        def fail_rechunk(state, logger):
            del logger
            rechunk_calls.append(f"{state.job_id}:{state.status}")
            raise AssertionError("startup recovery must not rechunk XTTS jobs")

        manager._rechunk_xtts_job_chunks_if_needed = fail_rechunk  # type: ignore[method-assign]
        manager.backend_block_reason = lambda state: None  # type: ignore[method-assign]

        manager.recover_interrupted_jobs()

        queued_after = manager.load_state(queued.job_id)
        running_after = manager.load_state(running.job_id)
        assert rechunk_calls == [], rechunk_calls
        assert queued_after.status == "queued", queued_after.status
        assert len(queued_after.chunks) == 1
        assert running_after.status == "queued", running_after.status
        assert len(running_after.chunks) == 1

        print(
            json.dumps(
                {
                    "completed_job": completed.job_id,
                    "queued_job": queued.job_id,
                    "running_job": running.job_id,
                    "rechunk_calls": rechunk_calls,
                    "running_status_after_recovery": running_after.status,
                },
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

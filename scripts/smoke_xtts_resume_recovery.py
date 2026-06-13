from __future__ import annotations

import json
import tempfile
from pathlib import Path

from book2mp3.config import AppPaths
from book2mp3.pipeline import jobs as jobs_module
from book2mp3.pipeline.jobs import JobManager
from book2mp3.presets import get_preset


class FakeXttsBackend:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def is_available(self) -> bool:
        return True

    def availability_reason(self) -> str:
        return "fake xtts backend available"

    def synthesize_many_to_wavs(
        self,
        texts: list[str],
        profile: object,
        wav_paths: list[Path],
        length_scale: float = 1.0,
        enable_text_splitting: bool = False,
    ) -> None:
        del texts, profile, length_scale, enable_text_splitting
        self.calls.append([path.stem for path in wav_paths])
        for wav_path in wav_paths:
            wav_path.parent.mkdir(parents=True, exist_ok=True)
            wav_path.write_bytes(b"RIFFfakeWAVEdata")


def make_source_text() -> str:
    paragraph = (
        "Kapitel 1\n"
        "Mara stand still, counted the lamps in the corridor, and listened for the old lift to start again. "
        "Every time the cable trembled, the whole house seemed to breathe with it. "
    )
    return "\n\n".join(paragraph for _ in range(6))


def fake_wav_to_mp3(wav_path: Path, mp3_path: Path, logger=None) -> None:
    del logger
    mp3_path.parent.mkdir(parents=True, exist_ok=True)
    mp3_path.write_bytes(b"ID3recovered-mp3-data")


def fake_concat_mp3_files(inputs: list[Path], output_file: Path, logger=None) -> None:
    del logger
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_bytes(b"".join(path.read_bytes() for path in inputs))


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="book2mp3-smoke-xtts-resume-") as tmp_dir:
        app_root = Path(tmp_dir)
        paths = AppPaths.from_project_root(app_root)
        paths.ensure()
        manager = JobManager(paths)
        preset = get_preset("premium_natural")
        source = app_root / "resume_source.txt"
        source.write_text(make_source_text(), encoding="utf-8")

        backend = FakeXttsBackend()
        original_backend_factory = manager._xtts_backend
        original_batch_parameters = manager._xtts_batch_parameters
        original_parallel = manager._xtts_should_parallel_postprocess
        original_workers = manager._xtts_postprocess_workers
        original_load_voice_profile = jobs_module.load_voice_profile
        original_wav_to_mp3 = jobs_module.wav_to_mp3
        original_concat_mp3_files = jobs_module.concat_mp3_files
        original_concat_audio_files_to_mp3 = jobs_module.concat_audio_files_to_mp3
        original_finalize_outputs = manager._finalize_outputs
        try:
            manager._xtts_backend = lambda logger=None: backend  # type: ignore[method-assign]
            manager._xtts_batch_parameters = lambda state: (2, 10_000)  # type: ignore[method-assign]
            manager._xtts_should_parallel_postprocess = lambda state: False  # type: ignore[method-assign]
            manager._xtts_postprocess_workers = lambda: 1  # type: ignore[method-assign]
            manager._finalize_outputs = lambda state, logger: None  # type: ignore[method-assign]
            jobs_module.load_voice_profile = lambda *args, **kwargs: object()
            jobs_module.wav_to_mp3 = fake_wav_to_mp3
            jobs_module.concat_mp3_files = fake_concat_mp3_files
            jobs_module.concat_audio_files_to_mp3 = fake_concat_mp3_files

            job = manager.create_job(
                source_path=source,
                voice_id="",
                voice_profile_id="xtts-recovery-profile",
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
            state = manager.prepare_job(job)
            assert len(state.chunks) == 12, len(state.chunks)

            for index, chunk in enumerate(state.chunks[:4], start=1):
                mp3_path = Path(chunk.mp3_file)
                mp3_path.parent.mkdir(parents=True, exist_ok=True)
                mp3_path.write_bytes(f"fake-{index}".encode("utf-8"))
            wav_only_chunk = state.chunks[4]
            wav_only_path = Path(wav_only_chunk.wav_file)
            wav_only_path.parent.mkdir(parents=True, exist_ok=True)
            wav_only_path.write_bytes(b"wav-only")

            state.chunks[0].status = "pending"
            state.chunks[1].status = "failed"
            state.chunks[1].error = "Broken pipe"
            state.chunks[2].status = "done"
            state.chunks[3].status = "pending"
            state.chunks[4].status = "done"
            state.status = "running"
            manager.save_state(state)

            manager.recover_interrupted_jobs()
            recovered = manager.load_state(state.job_id)
            assert recovered.status == "queued", recovered.status
            assert [chunk.status for chunk in recovered.chunks[:5]] == ["done", "done", "done", "done", "done"]
            assert all(chunk.status == "pending" for chunk in recovered.chunks[5:])

            resumed = manager.run_job(recovered)
        finally:
            manager._xtts_backend = original_backend_factory  # type: ignore[method-assign]
            manager._xtts_batch_parameters = original_batch_parameters  # type: ignore[method-assign]
            manager._xtts_should_parallel_postprocess = original_parallel  # type: ignore[method-assign]
            manager._xtts_postprocess_workers = original_workers  # type: ignore[method-assign]
            manager._finalize_outputs = original_finalize_outputs  # type: ignore[method-assign]
            jobs_module.load_voice_profile = original_load_voice_profile
            jobs_module.wav_to_mp3 = original_wav_to_mp3
            jobs_module.concat_mp3_files = original_concat_mp3_files
            jobs_module.concat_audio_files_to_mp3 = original_concat_audio_files_to_mp3

        assert resumed.status == "completed", resumed.status
        assert backend.calls == [["00006", "00007"], ["00008", "00009"], ["00010", "00011"], ["00012"]], backend.calls
        assert all(chunk.status == "done" for chunk in resumed.chunks)

        print(
            json.dumps(
                {
                    "job_id": resumed.job_id,
                    "backend_calls": backend.calls,
                    "recovered_first_statuses": [chunk.status for chunk in recovered.chunks[:6]],
                    "remaining_after_recovery": [chunk.index for chunk in recovered.chunks if chunk.status != "done"],
                },
                indent=2,
                ensure_ascii=False,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

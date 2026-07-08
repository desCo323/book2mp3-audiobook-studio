from __future__ import annotations

import json
import tempfile
from pathlib import Path

from book2mp3.config import AppPaths
from book2mp3.pipeline import jobs as jobs_module
from book2mp3.pipeline.jobs import JobManager
from book2mp3.presets import get_preset


ROOT = Path("/home/codex/repo/book2mp3")


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
        inference_options: dict[str, object] | None = None,
    ) -> None:
        del texts, profile, length_scale, enable_text_splitting, inference_options
        batch = [path.stem for path in wav_paths]
        self.calls.append(batch)
        for wav_path in wav_paths:
            wav_path.parent.mkdir(parents=True, exist_ok=True)
            wav_path.write_bytes(b"RIFFfakeWAVEdata" * 16)


def make_source_text() -> str:
    paragraph = (
        "Kapitel 1\n"
        "Der Wind strich durch die leere Bahnhofshalle, waehrend Mara die Schritte auf dem Steinboden zaehlte. "
        "Sie blieb stehen, horchte, ging weiter und wusste doch noch immer nicht, ob sie verfolgt wurde. "
    )
    return "\n\n".join(paragraph for _ in range(12))


def fake_wav_to_mp3(wav_path: Path, mp3_path: Path, logger=None) -> None:
    del logger
    mp3_path.parent.mkdir(parents=True, exist_ok=True)
    mp3_path.write_bytes(b"ID3fake-mp3-data" * 16)


def fake_concat_mp3_files(inputs: list[Path], output_file: Path, logger=None) -> None:
    del logger
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_bytes(b"".join(path.read_bytes() for path in inputs))


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="book2mp3-smoke-xtts-loop-") as tmp_dir:
        app_root = Path(tmp_dir)
        paths = AppPaths.from_project_root(app_root)
        paths.ensure()
        manager = JobManager(paths)
        preset = get_preset("premium_natural")
        source = app_root / "source.txt"
        source.write_text(make_source_text(), encoding="utf-8")

        backend = FakeXttsBackend()
        original_backend_factory = manager._xtts_backend
        original_batch_parameters = manager._xtts_batch_parameters
        original_parallel = manager._xtts_should_parallel_postprocess
        original_workers = manager._xtts_postprocess_workers
        original_load_voice_profile = jobs_module.load_voice_profile
        original_wav_to_mp3 = jobs_module.wav_to_mp3
        original_concat_mp3_files = jobs_module.concat_mp3_files
        original_finalize_outputs = manager._finalize_outputs
        try:
            manager._xtts_backend = lambda logger=None: backend  # type: ignore[method-assign]
            manager._xtts_batch_parameters = lambda state: (2, 10_000)  # type: ignore[method-assign]
            manager._xtts_should_parallel_postprocess = lambda state: True  # type: ignore[method-assign]
            manager._xtts_postprocess_workers = lambda: 1  # type: ignore[method-assign]
            manager._finalize_outputs = lambda state, logger: None  # type: ignore[method-assign]
            jobs_module.load_voice_profile = lambda *args, **kwargs: object()
            jobs_module.wav_to_mp3 = fake_wav_to_mp3
            jobs_module.concat_mp3_files = fake_concat_mp3_files

            job = manager.create_job(
                source_path=source,
                voice_id="",
                voice_profile_id="xtts-smoke-profile",
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
            state = manager.run_job(job)
        finally:
            manager._xtts_backend = original_backend_factory  # type: ignore[method-assign]
            manager._xtts_batch_parameters = original_batch_parameters  # type: ignore[method-assign]
            manager._xtts_should_parallel_postprocess = original_parallel  # type: ignore[method-assign]
            manager._xtts_postprocess_workers = original_workers  # type: ignore[method-assign]
            manager._finalize_outputs = original_finalize_outputs  # type: ignore[method-assign]
            jobs_module.load_voice_profile = original_load_voice_profile
            jobs_module.wav_to_mp3 = original_wav_to_mp3
            jobs_module.concat_mp3_files = original_concat_mp3_files

        assert state.status == "completed", state.status
        processed_ranges = [
            line.split("Processed XTTS batch ", 1)[1].split(" ", 1)[0]
            for line in state.logs
            if "Processed XTTS batch " in line
        ]
        processed_indexes: list[int] = []
        for processed_range in processed_ranges:
            if "-" in processed_range:
                start, end = (int(value) for value in processed_range.split("-", 1))
                processed_indexes.extend(range(start, end + 1))
            else:
                processed_indexes.append(int(processed_range))
        assert processed_indexes, "No processed XTTS batch logs captured"
        assert len(processed_indexes) == len(state.chunks), (len(processed_indexes), len(state.chunks))
        assert len(set(processed_indexes)) == len(state.chunks), processed_indexes
        assert all(chunk.status == "done" for chunk in state.chunks)
        assert all(Path(chunk.mp3_file).exists() for chunk in state.chunks)

        print(
            json.dumps(
                {
                    "job_id": state.job_id,
                    "chunk_count": len(state.chunks),
                    "backend_calls": backend.calls,
                    "processed_indexes": processed_indexes,
                    "final_output": state.final_output_file,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

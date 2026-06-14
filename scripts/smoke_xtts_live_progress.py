from __future__ import annotations

import json
import tempfile
import threading
import time
from pathlib import Path

from book2mp3.config import AppPaths
from book2mp3.pipeline import jobs as jobs_module
from book2mp3.pipeline.jobs import JobManager
from book2mp3.presets import get_preset


class SlowFakeXttsBackend:
    def is_available(self) -> bool:
        return True

    def availability_reason(self) -> str:
        return "slow fake xtts backend available"

    def synthesize_many_to_wavs(
        self,
        texts: list[str],
        profile: object,
        wav_paths: list[Path],
        length_scale: float = 1.0,
        enable_text_splitting: bool = False,
    ) -> None:
        del texts, profile, length_scale, enable_text_splitting
        for wav_path in wav_paths:
            wav_path.parent.mkdir(parents=True, exist_ok=True)
            time.sleep(1.2)
            wav_path.write_bytes(b"RIFFfakeWAVEdata")


def make_source_text() -> str:
    paragraph = (
        "Kapitel 1\n"
        "Mara zaehlte die Schritte im verlassenen Bahnhof und wartete auf ein Zeichen. "
        "Sie hob den Blick, lauschte auf das Echo und ging weiter.\n\n"
    )
    return paragraph * 5


def fake_wav_to_mp3(wav_path: Path, mp3_path: Path, logger=None) -> None:
    del logger
    mp3_path.parent.mkdir(parents=True, exist_ok=True)
    mp3_path.write_bytes(b"ID3fake-mp3-data")


def fake_concat_mp3_files(inputs: list[Path], output_file: Path, logger=None) -> None:
    del logger
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_bytes(b"".join(path.read_bytes() for path in inputs))


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="book2mp3-smoke-xtts-live-", dir="/home/codex") as tmp_dir:
        app_root = Path(tmp_dir)
        paths = AppPaths.from_project_root(app_root)
        paths.ensure()
        manager = JobManager(paths)
        preset = get_preset("premium_natural")
        source = app_root / "source.txt"
        source.write_text(make_source_text(), encoding="utf-8")

        backend = SlowFakeXttsBackend()
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

            state = manager.create_job(
                source_path=source,
                voice_id="",
                voice_profile_id="xtts-smoke-profile",
                preset_id=preset.preset_id,
                priority=50,
                max_chars=160,
                output_mode="single_file",
                target_part_minutes=preset.target_part_minutes,
                keep_wav=False,
                sentence_silence=preset.sentence_silence,
                length_scale=1.0,
                backend="xtts",
            )

            result: dict[str, object] = {}

            def runner() -> None:
                result["state"] = manager.run_job(state)

            thread = threading.Thread(target=runner, daemon=True)
            thread.start()

            observed_live_done = 0
            deadline = time.time() + 8
            state_file = paths.jobs / state.job_id / "state.json"
            while thread.is_alive() and time.time() < deadline:
                if state_file.exists():
                    payload = json.loads(state_file.read_text(encoding="utf-8"))
                    done = sum(1 for chunk in payload.get("chunks", []) if chunk.get("status") == "done")
                    if payload.get("status") == "running":
                        observed_live_done = max(observed_live_done, done)
                    if observed_live_done > 0:
                        break
                time.sleep(0.5)

            thread.join(timeout=20)
            if thread.is_alive():
                raise AssertionError("XTTS live-progress smoke timed out")

            finished = result["state"]
            assert finished.status == "completed", finished.status
            assert observed_live_done > 0, observed_live_done
            assert finished.final_output_files, finished.final_output_files
            assert all(Path(path).exists() for path in finished.final_output_files), finished.final_output_files

            print(
                json.dumps(
                    {
                        "job_id": finished.job_id,
                        "chunk_count": len(finished.chunks),
                        "observed_live_done": observed_live_done,
                        "final_status": finished.status,
                    },
                    indent=2,
                    ensure_ascii=False,
                )
            )
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

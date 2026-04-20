from __future__ import annotations

import json
import tempfile
import wave
from pathlib import Path

from book2mp3.config import AppPaths
from book2mp3.pipeline.jobs import JobManager
from book2mp3.presets import get_preset
from book2mp3.utils.logging_utils import configure_logging
from book2mp3.voice_lab import create_voice_profile


def create_dummy_wav(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes(b"\x00\x00" * 16000 * 3)


def main() -> int:
    root = Path("/home/codex/repo/book2mp3")
    paths = AppPaths.from_project_root(root)
    paths.ensure()
    configure_logging(paths.logs)
    manager = JobManager(paths)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_root = Path(tmp)
        source = tmp_root / "xtts_source.txt"
        source.write_text("Dies ist ein XTTS-Jobmodelltest. " * 20, encoding="utf-8")
        sample = tmp_root / "speaker.wav"
        create_dummy_wav(sample)
        manifest = create_voice_profile(
            paths.voice_profiles,
            display_name="XTTS Smoke Voice",
            target_language="de",
            backend="xtts_v2",
            notes="Smoke-Test-Profil",
            sample_paths=[sample],
        )
        profile_id = manifest.parent.name
        preset = get_preset("balanced")
        job = manager.create_job(
            source_path=source,
            voice_id="",
            voice_profile_id=profile_id,
            preset_id=preset.preset_id,
            priority=60,
            max_chars=preset.max_chars,
            output_mode="segments",
            keep_wav=False,
            sentence_silence=preset.sentence_silence,
            length_scale=preset.length_scale,
            backend="xtts",
        )
        loaded = manager.load_state(job.job_id)
        assert loaded.backend == "xtts"
        assert loaded.voice_profile_id == profile_id
        print(
            json.dumps(
                {
                    "job_id": loaded.job_id,
                    "backend": loaded.backend,
                    "voice_profile_id": loaded.voice_profile_id,
                },
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

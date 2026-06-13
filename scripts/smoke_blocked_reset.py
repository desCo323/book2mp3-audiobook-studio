from __future__ import annotations

import json
import math
import shutil
import struct
import tempfile
import wave
from pathlib import Path

from book2mp3.config import AppPaths
from book2mp3.service import Book2Mp3Service
from book2mp3.voice_lab import create_voice_profile


ROOT = Path("/home/codex/repo/book2mp3")


def write_reference_wav(path: Path, *, seconds: float = 3.2, sample_rate: int = 22050) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    total_frames = int(seconds * sample_rate)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        frames = bytearray()
        for frame_index in range(total_frames):
            value = int(12000 * math.sin(2 * math.pi * 220 * (frame_index / sample_rate)))
            frames.extend(struct.pack("<h", value))
        handle.writeframes(bytes(frames))


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="book2mp3-smoke-blocked-") as tmp_dir:
        app_root = Path(tmp_dir) / "app"
        app_root.mkdir(parents=True, exist_ok=True)
        shutil.copytree(ROOT / "runtime", app_root / "runtime")
        shutil.copytree(ROOT / "voices", app_root / "voices")

        paths = AppPaths.from_project_root(app_root)
        service = Book2Mp3Service(paths)

        source = app_root / "blocked_source.txt"
        source.write_text("Dies ist ein XTTS-Blockier-Test.", encoding="utf-8")

        sample = app_root / "speaker.wav"
        write_reference_wav(sample)
        manifest = create_voice_profile(
            paths.voice_profiles,
            display_name="Smoke XTTS",
            target_language="de",
            backend="xtts_v2",
            notes="smoke profile",
            sample_paths=[sample],
        )
        profile_id = manifest.parent.name

        xtts_job = service.create_job(
            source_path=source,
            backend="xtts",
            voice_profile_id=profile_id,
            preset_id="balanced",
            output_mode="segments",
        )
        piper_job = service.create_job(
            source_path=source,
            backend="piper",
            voice_id="de_DE-eva_k-x_low",
            preset_id="balanced",
            output_mode="segments",
        )

        next_job = service.manager.next_queued_job()
        xtts_state = service.manager.load_state(str(xtts_job["job_id"]))
        piper_state = service.manager.load_state(str(piper_job["job_id"]))

        assert next_job is not None
        assert next_job.job_id == piper_state.job_id
        assert xtts_state.status == "blocked"
        assert xtts_state.block_reason
        assert piper_state.status == "queued"

        reset_summary = service.reset_workspace()
        assert reset_summary["reset"] is True
        assert not list(paths.jobs.glob("*/state.json"))
        assert not list(paths.voice_profiles.glob("*/profile.json"))

        print(
            json.dumps(
                {
                    "blocked_job": xtts_state.job_id,
                    "blocked_reason": xtts_state.block_reason,
                    "next_runnable_job": next_job.job_id,
                    "reset_workspace": reset_summary["workspace"],
                },
                indent=2,
                ensure_ascii=False,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

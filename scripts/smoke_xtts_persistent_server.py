from __future__ import annotations

import json
import os
import tempfile
import time
import wave
from pathlib import Path

from book2mp3.config import AppPaths
from book2mp3.tts.xtts import XttsBackend
from book2mp3.voice_lab import create_voice_profile, load_voice_profile


ROOT = Path("/home/codex/repo/book2mp3")
APP_SRC_ROOT = ROOT / "src"


def runtime_fixture_root() -> Path:
    candidate = APP_SRC_ROOT / "runtime"
    return candidate if candidate.exists() else ROOT / "runtime"


def ensure_runtime_fixture(app_root: Path) -> None:
    runtime_target = runtime_fixture_root()
    runtime_link = app_root / "runtime"
    if runtime_link.exists():
        return
    runtime_link.symlink_to(runtime_target, target_is_directory=True)


def ensure_voices_fixture(app_root: Path) -> None:
    voices_target = ROOT / "voices"
    voices_link = app_root / "voices"
    if voices_link.exists():
        return
    voices_link.symlink_to(voices_target, target_is_directory=True)


def create_dummy_wav(path: Path, seconds: int = 4) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(22050)
        wav_file.writeframes(b"\x00\x00" * 22050 * seconds)


def main() -> int:
    os.environ.pop("BOOK2MP3_DISABLE_XTTS_SERVER", None)
    with tempfile.TemporaryDirectory(prefix="book2mp3-smoke-xtts-server-") as tmp_dir:
        app_root = Path(tmp_dir) / "src"
        app_root.mkdir(parents=True, exist_ok=True)
        ensure_runtime_fixture(app_root)
        ensure_voices_fixture(app_root)
        paths = AppPaths.from_project_root(app_root)
        paths.ensure()

        sample = app_root / "samples" / "speaker.wav"
        create_dummy_wav(sample)
        manifest = create_voice_profile(
            paths.voice_profiles,
            display_name="XTTS Persistent Server Smoke",
            target_language="de",
            backend="xtts_v2",
            notes="Persistent XTTS server smoke test",
            sample_paths=[sample],
        )
        profile = load_voice_profile(paths.voice_profiles, manifest.parent.name)
        backend = XttsBackend(paths.runtime)

        first_wav = app_root / "out" / "first.wav"
        second_wav = app_root / "out" / "second.wav"
        first_started = time.perf_counter()
        backend.synthesize_many_to_wavs(
            ["Das ist ein erster kurzer XTTS Test."],
            profile,
            [first_wav],
        )
        first_seconds = time.perf_counter() - first_started
        first_connection = backend.server_connection()
        first_pid = first_connection.process.pid

        second_started = time.perf_counter()
        backend.synthesize_many_to_wavs(
            ["Das ist ein zweiter kurzer XTTS Test."],
            profile,
            [second_wav],
        )
        second_seconds = time.perf_counter() - second_started
        second_connection = backend.server_connection()
        second_pid = second_connection.process.pid

        if not first_wav.exists():
            raise AssertionError(f"Missing first XTTS output: {first_wav}")
        if not second_wav.exists():
            raise AssertionError(f"Missing second XTTS output: {second_wav}")
        if first_pid != second_pid:
            raise AssertionError(f"Expected XTTS server reuse, got PIDs {first_pid} and {second_pid}")

        XttsBackend.shutdown_all_servers()
        summary = {
            "first_output": str(first_wav),
            "second_output": str(second_wav),
            "server_pid": first_pid,
            "first_seconds": round(first_seconds, 2),
            "second_seconds": round(second_seconds, 2),
        }
        print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

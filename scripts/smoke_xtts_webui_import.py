from __future__ import annotations

import json
import tempfile
import wave
from pathlib import Path

from book2mp3.config import AppPaths
from book2mp3.voice_lab import list_voice_profiles
from book2mp3.xtts_speakers import import_xtts_webui_speakers


def create_dummy_wav(path: Path, seconds: int = 4) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes(b"\x00\x00" * 16000 * seconds)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="book2mp3-xtts-webui-") as tmp_dir:
        root = Path(tmp_dir)
        app_root = root / "src"
        app_root.mkdir(parents=True, exist_ok=True)
        paths = AppPaths.from_project_root(app_root)
        paths.ensure()

        speakers_root = root / "speakers"
        create_dummy_wav(speakers_root / "de" / "roman_narrator" / "sample1.wav")
        create_dummy_wav(speakers_root / "de" / "roman_narrator" / "sample2.wav")
        create_dummy_wav(speakers_root / "en" / "warm_reader" / "sample1.wav")

        manifests = import_xtts_webui_speakers(paths, speakers_root, fallback_language="en")
        profiles = list_voice_profiles(paths.voice_profiles)
        summary = {
            "imported_count": len(manifests),
            "profile_ids": [profile.profile_id for profile in profiles],
            "languages": sorted({profile.target_language for profile in profiles}),
            "sample_counts": {profile.profile_id: len(profile.samples) for profile in profiles},
        }
        assert len(manifests) == 2
        assert "de" in summary["languages"]
        assert "en" in summary["languages"]
        print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

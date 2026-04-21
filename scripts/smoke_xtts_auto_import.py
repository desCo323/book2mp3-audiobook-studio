from __future__ import annotations

import json
import tempfile
import wave
from pathlib import Path

from book2mp3.config import AppPaths
from book2mp3.voice_lab import list_voice_profiles
from book2mp3.xtts_speakers import auto_import_xtts_speakers


def create_dummy_wav(path: Path, seconds: int = 4) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes(b"\x00\x00" * 16000 * seconds)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="book2mp3-xtts-auto-") as tmp_dir:
        root = Path(tmp_dir)
        app_root = root / "src"
        app_root.mkdir(parents=True, exist_ok=True)
        paths = AppPaths.from_project_root(app_root)
        paths.ensure()

        create_dummy_wav(app_root / "speakers" / "de" / "story_reader" / "sample.wav")
        source_root, manifests = auto_import_xtts_speakers(paths, fallback_language="de")
        profiles = list_voice_profiles(paths.voice_profiles)

        summary = {
            "source_root": str(source_root) if source_root else "",
            "imported_count": len(manifests),
            "profiles": [profile.profile_id for profile in profiles],
        }
        assert source_root is not None
        assert len(manifests) == 1
        assert "story_reader" in summary["profiles"]
        print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

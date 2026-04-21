from __future__ import annotations

import json
import tempfile
import wave
from pathlib import Path

from book2mp3.config import AppPaths
from book2mp3.xtts_speakers import find_candidate_speaker_roots


def create_dummy_wav(path: Path, seconds: int = 4) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes(b"\x00\x00" * 16000 * seconds)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="book2mp3-xtts-scan-") as tmp_dir:
        root = Path(tmp_dir)
        app_root = root / "src"
        app_root.mkdir(parents=True, exist_ok=True)
        paths = AppPaths.from_project_root(app_root)
        paths.ensure()

        create_dummy_wav(root / "xtts-webui-v1_0-portable" / "speakers" / "de" / "reader_a" / "sample.wav")
        candidates = find_candidate_speaker_roots(paths)
        summary = {
            "candidate_count": len(candidates),
            "candidates": [str(path) for path in candidates],
        }
        assert any("xtts-webui-v1_0-portable" in str(path) for path in candidates)
        print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

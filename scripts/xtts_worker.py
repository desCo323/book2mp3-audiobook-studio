from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    payload = json.loads(sys.stdin.read())
    try:
        from TTS.api import TTS
    except Exception as exc:
        raise SystemExit(f"XTTS runtime is not installed correctly: {exc}")

    output_file = Path(payload["output_file"])
    output_file.parent.mkdir(parents=True, exist_ok=True)
    tts = TTS(payload["model_name"])
    tts.tts_to_file(
        text=payload["text"],
        speaker_wav=payload["speaker_wav"],
        language=payload["language"],
        file_path=str(output_file),
        speed=1.0 / float(payload.get("length_scale", 1.0)),
    )
    print(json.dumps({"ok": True, "output_file": str(output_file)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

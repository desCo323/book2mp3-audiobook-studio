from __future__ import annotations

import json
import tempfile
from pathlib import Path

from book2mp3.piper_custom import import_custom_piper_model
from book2mp3.tts.piper import PiperBackend


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="book2mp3-smoke-piper-custom-") as tmp_dir:
        root = Path(tmp_dir)
        voices_root = root / "voices"
        runtime_root = root / "runtime"
        voices_root.mkdir(parents=True, exist_ok=True)
        runtime_root.mkdir(parents=True, exist_ok=True)

        source_model = root / "de_DE-custom_female-high.onnx"
        source_config = root / "de_DE-custom_female-high.onnx.json"
        source_model.write_bytes(b"dummy-onnx")
        source_config.write_text('{"audio":{"sample_rate":22050}}', encoding="utf-8")

        imported = import_custom_piper_model(voices_root, source_model, source_config)
        backend = PiperBackend(runtime_root, voices_root)
        voices = backend.installed_voices()
        if imported.voice_id not in voices:
            raise AssertionError(f"Imported voice missing from Piper scan: {voices}")
        resolved = backend.voice_path(imported.voice_id)
        if resolved != imported.model_path:
            raise AssertionError(f"Expected imported model path {imported.model_path}, got {resolved}")

        print(
            json.dumps(
                {
                    "voice_id": imported.voice_id,
                    "installed_model": str(imported.model_path),
                    "installed_config": str(imported.config_path),
                },
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

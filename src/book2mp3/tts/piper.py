from __future__ import annotations

import json
import logging
import os
import platform
import subprocess
from pathlib import Path


class PiperBackend:
    name = "piper"

    def __init__(
        self, runtime_root: Path, voices_root: Path, logger: logging.Logger | None = None
    ) -> None:
        self.runtime_root = runtime_root
        self.voices_root = voices_root
        self.logger = logger

    def binary_path(self) -> Path:
        system = platform.system().lower()
        if system == "windows":
            candidate = self.runtime_root / "piper" / "windows" / "piper.exe"
        elif system == "linux":
            candidate = self.runtime_root / "piper" / "linux" / "piper" / "piper"
        else:
            raise RuntimeError(f"Unsupported platform: {platform.system()}")
        if not candidate.exists():
            raise FileNotFoundError(
                "Piper runtime not found. Run scripts/bootstrap_runtime.py first."
            )
        return candidate

    def voice_path(self, voice_id: str) -> Path:
        candidate = self.voices_root / f"{voice_id}.onnx"
        if candidate.exists():
            return candidate
        matches = list(self.voices_root.rglob(f"{voice_id}.onnx"))
        if matches:
            return matches[0]
        raise FileNotFoundError(f"Voice model not found for '{voice_id}'.")

    def installed_voices(self) -> list[str]:
        voices = []
        for path in self.voices_root.rglob("*.onnx"):
            voices.append(path.stem)
        return sorted(set(voices))

    def synthesize_to_wav(
        self,
        text: str,
        voice_id: str,
        wav_path: Path,
        sentence_silence: float = 0.2,
        length_scale: float = 1.0,
    ) -> None:
        wav_path.parent.mkdir(parents=True, exist_ok=True)
        model_path = self.voice_path(voice_id)
        payload = json.dumps({"text": text}, ensure_ascii=False) + "\n"
        cmd = [
            str(self.binary_path()),
            "--model",
            str(model_path),
            "--output_file",
            str(wav_path),
            "--sentence_silence",
            str(sentence_silence),
            "--length_scale",
            str(length_scale),
            "--json-input",
        ]
        env = os.environ.copy()
        binary_dir = str(self.binary_path().parent)
        if platform.system().lower() == "linux":
            env["LD_LIBRARY_PATH"] = (
                f"{binary_dir}:{env['LD_LIBRARY_PATH']}"
                if env.get("LD_LIBRARY_PATH")
                else binary_dir
            )
        if self.logger:
            self.logger.debug("Synthesizing chunk with Piper command: %s", cmd)
            self.logger.debug("Chunk text length: %s", len(text))
        try:
            result = subprocess.run(
                cmd,
                input=payload,
                check=True,
                capture_output=True,
                text=True,
                cwd=binary_dir,
                env=env,
            )
            if self.logger:
                self.logger.debug("Piper stdout: %s", result.stdout.strip())
                self.logger.debug("Piper stderr: %s", result.stderr.strip())
        except subprocess.CalledProcessError as exc:
            if self.logger:
                self.logger.exception("Piper synthesis failed")
                self.logger.debug("Piper stdout: %s", exc.stdout)
                self.logger.debug("Piper stderr: %s", exc.stderr)
            raise

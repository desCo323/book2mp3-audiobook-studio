from __future__ import annotations

import json
import logging
import platform
import subprocess
from pathlib import Path

from book2mp3.voice_lab import VoiceProfile


class XttsBackend:
    name = "xtts"

    def __init__(self, runtime_root: Path, logger: logging.Logger | None = None) -> None:
        self.runtime_root = runtime_root
        self.logger = logger

    def python_path(self) -> Path:
        system = platform.system().lower()
        if system == "windows":
            candidate = self.runtime_root / "xtts" / "windows" / "python" / "python.exe"
        elif system == "linux":
            candidate = self.runtime_root / "xtts" / "linux" / "bin" / "python3"
        else:
            raise RuntimeError(f"Unsupported platform: {platform.system()}")
        if not candidate.exists():
            raise FileNotFoundError(
                "XTTS runtime not found. Install a dedicated XTTS runtime first."
            )
        return candidate

    def synthesize_to_wav(
        self,
        text: str,
        profile: VoiceProfile,
        wav_path: Path,
        length_scale: float = 1.0,
    ) -> None:
        wav_path.parent.mkdir(parents=True, exist_ok=True)
        worker = Path(__file__).resolve().parents[3] / "scripts" / "xtts_worker.py"
        payload = {
            "text": text,
            "language": profile.target_language,
            "speaker_wav": profile.samples,
            "model_name": profile.preferred_model,
            "output_file": str(wav_path),
            "length_scale": length_scale,
        }
        cmd = [str(self.python_path()), str(worker)]
        if self.logger:
            self.logger.debug("Synthesizing chunk with XTTS command: %s", cmd)
            self.logger.debug("XTTS payload: %s", payload)
        result = subprocess.run(cmd, input=json.dumps(payload), capture_output=True, text=True)
        if result.returncode != 0:
            if self.logger:
                self.logger.error("XTTS worker stdout: %s", result.stdout)
                self.logger.error("XTTS worker stderr: %s", result.stderr)
            raise RuntimeError(f"XTTS synthesis failed with exit code {result.returncode}")
        if self.logger:
            self.logger.debug("XTTS worker stdout: %s", result.stdout.strip())
            self.logger.debug("XTTS worker stderr: %s", result.stderr.strip())

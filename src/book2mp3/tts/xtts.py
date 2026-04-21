from __future__ import annotations

import importlib.util
import json
import logging
import os
import platform
import subprocess
import sys
from pathlib import Path

from book2mp3.voice_lab import VoiceProfile


class XttsBackend:
    name = "xtts"

    def __init__(self, runtime_root: Path, logger: logging.Logger | None = None) -> None:
        self.runtime_root = runtime_root
        self.logger = logger

    def dedicated_python_path(self) -> Path:
        system = platform.system().lower()
        if system == "windows":
            candidate = self.runtime_root / "xtts" / "windows" / "python" / "python.exe"
        elif system == "linux":
            candidate = self.runtime_root / "xtts" / "linux" / "bin" / "python3"
        else:
            raise RuntimeError(f"Unsupported platform: {platform.system()}")
        return candidate

    def current_python_supports_xtts(self) -> bool:
        return importlib.util.find_spec("TTS") is not None

    def is_available(self) -> bool:
        return self.dedicated_python_path().exists() or self.current_python_supports_xtts()

    def availability_reason(self) -> str:
        candidate = self.dedicated_python_path()
        if candidate.exists():
            return f"XTTS runtime gefunden: {candidate}"
        if self.current_python_supports_xtts():
            return f"XTTS nutzt aktuelles Python: {sys.executable}"
        return (
            "XTTS runtime fehlt. Installiere sie mit "
            "`python scripts/setup_xtts_runtime.py runtime/xtts/linux --bootstrap-linux-standalone` "
            "oder nutze vorerst Piper."
        )

    def python_path(self) -> Path:
        candidate = self.dedicated_python_path()
        if not candidate.exists():
            if self.current_python_supports_xtts():
                return Path(sys.executable)
            raise FileNotFoundError(
                self.availability_reason()
            )
        return candidate

    def subprocess_env(self) -> dict[str, str]:
        env = os.environ.copy()
        python_path = self.python_path()
        if python_path.resolve() != Path(sys.executable).resolve():
            for key in (
                "PYTHONHOME",
                "PYTHONPATH",
                "PYTHONSTARTUP",
                "PYTHONUSERBASE",
                "PYTHONEXECUTABLE",
                "VIRTUAL_ENV",
                "__PYVENV_LAUNCHER__",
            ):
                env.pop(key, None)
            env["PYTHONNOUSERSITE"] = "1"
        return env

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
        python_path = self.python_path()
        cmd = [str(python_path), str(worker)]
        env = self.subprocess_env()
        if self.logger:
            self.logger.debug("Synthesizing chunk with XTTS command: %s", cmd)
            self.logger.debug("XTTS payload: %s", payload)
            self.logger.debug(
                "XTTS env override: %s",
                {
                    "PYTHONHOME": env.get("PYTHONHOME", ""),
                    "PYTHONPATH": env.get("PYTHONPATH", ""),
                    "PYTHONNOUSERSITE": env.get("PYTHONNOUSERSITE", ""),
                },
            )
        result = subprocess.run(
            cmd,
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            env=env,
        )
        if result.returncode != 0:
            if self.logger:
                self.logger.error("XTTS worker stdout: %s", result.stdout)
                self.logger.error("XTTS worker stderr: %s", result.stderr)
            raise RuntimeError(f"XTTS synthesis failed with exit code {result.returncode}")
        if self.logger:
            self.logger.debug("XTTS worker stdout: %s", result.stdout.strip())
            self.logger.debug("XTTS worker stderr: %s", result.stderr.strip())

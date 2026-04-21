from __future__ import annotations

import atexit
import importlib.util
import json
import logging
import os
import platform
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from book2mp3.voice_lab import VoiceProfile


@dataclass
class _XttsServerConnection:
    process: subprocess.Popen[str]
    io_lock: threading.Lock
    stderr_thread: threading.Thread


class XttsBackend:
    name = "xtts"
    _server_registry_lock = threading.Lock()
    _server_connections: dict[str, _XttsServerConnection] = {}
    _atexit_registered = False

    def __init__(self, runtime_root: Path, logger: logging.Logger | None = None, device_mode: str = "auto") -> None:
        self.runtime_root = runtime_root
        self.logger = logger
        self.device_mode = device_mode

    def set_device_mode(self, device_mode: str) -> None:
        self.device_mode = device_mode

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

    def runtime_probe(self) -> dict[str, object]:
        checker = Path(__file__).resolve().parents[3] / "scripts" / "check_xtts_cuda.py"
        env = self.subprocess_env()
        result = subprocess.run(
            [str(self.python_path()), str(checker)],
            capture_output=True,
            text=True,
            env=env,
        )
        if result.returncode not in {0, 1}:
            raise RuntimeError(f"XTTS runtime probe failed: {result.stderr.strip() or result.stdout.strip()}")
        return json.loads(result.stdout)

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
        env.setdefault("COQUI_TOS_AGREED", "1")
        return env

    def server_enabled(self) -> bool:
        return os.environ.get("BOOK2MP3_DISABLE_XTTS_SERVER", "").strip() not in {"1", "true", "yes"}

    def server_key(self) -> str:
        return f"{self.python_path().resolve()}::{self.device_mode}"

    @classmethod
    def shutdown_all_servers(cls) -> None:
        with cls._server_registry_lock:
            connections = list(cls._server_connections.values())
            cls._server_connections.clear()
        for connection in connections:
            try:
                if connection.process.poll() is None and connection.process.stdin is not None:
                    connection.process.stdin.write(json.dumps({"command": "shutdown"}) + "\n")
                    connection.process.stdin.flush()
                    connection.process.wait(timeout=5)
            except Exception:
                try:
                    connection.process.terminate()
                    connection.process.wait(timeout=5)
                except Exception:
                    connection.process.kill()

    def _register_atexit(self) -> None:
        if not XttsBackend._atexit_registered:
            atexit.register(XttsBackend.shutdown_all_servers)
            XttsBackend._atexit_registered = True

    def _start_server_stderr_thread(self, process: subprocess.Popen[str]) -> threading.Thread:
        logger = self.logger

        def _reader() -> None:
            if process.stderr is None:
                return
            for line in process.stderr:
                message = line.rstrip()
                if not message:
                    continue
                if logger:
                    logger.debug("XTTS server stderr: %s", message)

        thread = threading.Thread(target=_reader, name="xtts-server-stderr", daemon=True)
        thread.start()
        return thread

    def server_connection(self) -> _XttsServerConnection:
        self._register_atexit()
        key = self.server_key()
        with XttsBackend._server_registry_lock:
            connection = XttsBackend._server_connections.get(key)
            if connection and connection.process.poll() is None:
                return connection

            worker = Path(__file__).resolve().parents[3] / "scripts" / "xtts_worker.py"
            cmd = [str(self.python_path()), str(worker), "--server"]
            env = self.subprocess_env()
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                env=env,
            )
            connection = _XttsServerConnection(
                process=process,
                io_lock=threading.Lock(),
                stderr_thread=self._start_server_stderr_thread(process),
            )
            XttsBackend._server_connections[key] = connection
            if self.logger:
                self.logger.info("Started persistent XTTS server: %s", cmd)
            return connection

    @classmethod
    def _drop_server_connection(cls, key: str) -> None:
        with cls._server_registry_lock:
            connection = cls._server_connections.pop(key, None)
        if not connection:
            return
        try:
            if connection.process.poll() is None:
                connection.process.terminate()
                connection.process.wait(timeout=5)
        except Exception:
            try:
                connection.process.kill()
            except Exception:
                pass

    def _request_server(self, payload: dict[str, object]) -> dict[str, object]:
        key = self.server_key()
        connection = self.server_connection()
        with connection.io_lock:
            if connection.process.poll() is not None:
                XttsBackend._drop_server_connection(key)
                raise RuntimeError("XTTS server process terminated unexpectedly")
            if connection.process.stdin is None or connection.process.stdout is None:
                XttsBackend._drop_server_connection(key)
                raise RuntimeError("XTTS server pipes are not available")
            connection.process.stdin.write(json.dumps(payload) + "\n")
            connection.process.stdin.flush()
            line = connection.process.stdout.readline()
        if not line:
            XttsBackend._drop_server_connection(key)
            raise RuntimeError("XTTS server returned no response")
        try:
            response = json.loads(line)
        except json.JSONDecodeError as exc:
            XttsBackend._drop_server_connection(key)
            raise RuntimeError(f"XTTS server returned invalid JSON: {line.strip()}") from exc
        if not response.get("ok"):
            details = str(response.get("error", "Unknown XTTS server error"))
            traceback_text = response.get("traceback")
            if traceback_text:
                details = f"{details}\n{traceback_text}"
            raise RuntimeError(details)
        return response

    def _run_one_shot(self, payload: dict[str, object]) -> None:
        worker = Path(__file__).resolve().parents[3] / "scripts" / "xtts_worker.py"
        python_path = self.python_path()
        cmd = [str(python_path), str(worker)]
        env = self.subprocess_env()
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

    def synthesize_to_wav(
        self,
        text: str,
        profile: VoiceProfile,
        wav_path: Path,
        length_scale: float = 1.0,
        enable_text_splitting: bool = False,
    ) -> None:
        self.synthesize_many_to_wavs(
            [text],
            profile,
            [wav_path],
            length_scale=length_scale,
            enable_text_splitting=enable_text_splitting,
        )

    def synthesize_many_to_wavs(
        self,
        texts: list[str],
        profile: VoiceProfile,
        wav_paths: list[Path],
        length_scale: float = 1.0,
        enable_text_splitting: bool = False,
    ) -> None:
        if len(texts) != len(wav_paths):
            raise ValueError("texts and wav_paths must have the same length")
        for wav_path in wav_paths:
            wav_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "texts": texts,
            "language": profile.target_language,
            "speaker_wav": profile.samples,
            "model_name": profile.preferred_model,
            "output_files": [str(path) for path in wav_paths],
            "length_scale": length_scale,
            "enable_text_splitting": enable_text_splitting,
            "device_mode": self.device_mode,
        }
        if self.logger:
            self.logger.debug("Synthesizing %s chunk(s) with XTTS payload", len(texts))
            self.logger.debug("XTTS payload: %s", payload)
        started = time.perf_counter()
        try:
            if self.server_enabled():
                response = self._request_server(payload)
                if self.logger:
                    self.logger.debug("XTTS server response: %s", response)
                    self.logger.info(
                        "XTTS server synthesis finished in %.2fs for %s text item(s)",
                        time.perf_counter() - started,
                        len(texts),
                    )
                return
        except Exception:
            if self.logger:
                self.logger.exception("Persistent XTTS server request failed, falling back to one-shot worker")
        self._run_one_shot(payload)
        if self.logger:
            self.logger.info(
                "XTTS one-shot synthesis finished in %.2fs for %s text item(s)",
                time.perf_counter() - started,
                len(texts),
            )

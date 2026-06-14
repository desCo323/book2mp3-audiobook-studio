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

from book2mp3.utils.perf_logging import perf_event, perf_scope
from book2mp3.voice_lab import VoiceProfile
from book2mp3.xtts_setup import xtts_launcher_hint, xtts_license_hint, xtts_setup_command_text, xtts_setup_supported


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
    _dependency_cache: dict[str, tuple[float, bool, str]] = {}
    _repair_lock = threading.Lock()
    _repair_cache: dict[str, tuple[float, bool, str]] = {}

    def __init__(self, runtime_root: Path, logger: logging.Logger | None = None, device_mode: str = "auto") -> None:
        self.runtime_root = runtime_root
        self.logger = logger
        self.device_mode = device_mode

    def set_device_mode(self, device_mode: str) -> None:
        self.device_mode = device_mode

    def preferred_device_mode(self) -> str:
        if not self.is_available():
            return "auto"
        try:
            probe = self.runtime_probe()
        except Exception:
            return "auto"
        if probe.get("ok") and probe.get("cuda_available"):
            return "cuda"
        return "auto"

    def dedicated_python_path(self) -> Path:
        system = platform.system().lower()
        if system == "windows":
            candidates = [
                self.runtime_root / "xtts" / "windows" / "python" / "python.exe",
                self.runtime_root / "xtts" / "windows" / "python" / "Scripts" / "python.exe",
            ]
        elif system == "linux":
            candidates = [self.runtime_root / "xtts" / "linux" / "bin" / "python3"]
        else:
            raise RuntimeError(f"Unsupported platform: {platform.system()}")
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return candidates[0]

    def current_python_supports_xtts(self) -> bool:
        return importlib.util.find_spec("TTS") is not None and importlib.util.find_spec("numpy") is not None

    def runtime_dependencies_ok(self) -> tuple[bool, str]:
        candidate = self.dedicated_python_path()
        if candidate.exists():
            python_path = candidate
        elif self.current_python_supports_xtts():
            python_path = Path(sys.executable)
        else:
            return False, "XTTS runtime fehlt."
        cache_key = str(python_path.resolve())
        cached = XttsBackend._dependency_cache.get(cache_key)
        now = time.time()
        if cached and now - cached[0] < 15:
            return cached[1], cached[2]
        env = os.environ.copy()
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
        result = subprocess.run(
            [
                str(python_path),
                "-c",
                "import numpy; import TTS; print('ok')",
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=20,
        )
        ok = result.returncode == 0
        detail = "ok" if ok else (result.stderr.strip() or result.stdout.strip() or "XTTS runtime dependencies missing")
        XttsBackend._dependency_cache[cache_key] = (now, ok, detail)
        return ok, detail

    def is_available(self) -> bool:
        ok, _ = self.runtime_dependencies_ok()
        return ok

    def availability_reason(self) -> str:
        candidate = self.dedicated_python_path()
        if candidate.exists():
            ok, detail = self.runtime_dependencies_ok()
            if ok:
                return f"XTTS runtime gefunden: {candidate}"
            return (
                "XTTS runtime gefunden, aber unvollständig. "
                f"Details: {detail}. Für XTTS nutze den vorbereiteten Setup-Pfad über `{xtts_launcher_hint()}`."
            )
        if self.current_python_supports_xtts():
            return f"XTTS nutzt aktuelles Python: {sys.executable}"
        setup_command = ""
        try:
            setup_paths = self._setup_paths()
            if xtts_setup_supported(setup_paths):
                setup_command = xtts_setup_command_text(setup_paths, python_executable=sys.executable)
        except Exception:
            setup_command = ""
        launcher_hint = xtts_launcher_hint()
        command_hint = f"Alternativ direkt: {setup_command}" if setup_command else ""
        return (
            "XTTS runtime fehlt. Piper funktioniert sofort. "
            f"Für XTTS nutze den vorbereiteten Setup-Pfad über `{launcher_hint}`. "
            f"{command_hint} {xtts_license_hint()}"
        )

    def attempt_runtime_self_heal(self, detail: str = "") -> tuple[bool, str]:
        candidate = self.dedicated_python_path()
        if not candidate.exists():
            return False, "Keine dedizierte XTTS-Runtime vorhanden."
        cache_key = str(candidate.resolve())
        now = time.time()
        with XttsBackend._repair_lock:
            cached = XttsBackend._repair_cache.get(cache_key)
            if cached and now - cached[0] < 180:
                return cached[1], cached[2]
            if self.logger:
                self.logger.warning("Attempting XTTS runtime self-heal for %s", cache_key)
            env = self.subprocess_env()
            normalized_detail = detail or ""
            runtime_root = candidate.parent.parent if candidate.parent.name == "bin" else candidate.parent
            if (
                platform.system().lower() == "linux"
                and any(
                    marker in normalized_detail
                    for marker in (
                        "No module named 'numpy'",
                        "No module named 'TTS'",
                        "No module named 'torch'",
                        "No module named 'torchaudio'",
                        'No module named "numpy"',
                        'No module named "TTS"',
                        'No module named "torch"',
                        'No module named "torchaudio"',
                    )
                )
            ):
                setup_script = Path(__file__).resolve().parents[3] / "scripts" / "setup_xtts_runtime.py"
                rebuild = subprocess.run(
                    [
                        sys.executable,
                        str(setup_script),
                        str(runtime_root),
                        "--bootstrap-linux-standalone",
                        "--torch-variant",
                        "auto",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=5400,
                )
                if rebuild.returncode != 0:
                    message = rebuild.stderr.strip() or rebuild.stdout.strip() or "XTTS-Runtime konnte nicht vollständig neu aufgebaut werden"
                    XttsBackend._repair_cache[cache_key] = (now, False, message)
                    return False, message
                XttsBackend.shutdown_all_servers()
                XttsBackend._dependency_cache.pop(cache_key, None)
                ok, check_detail = self.runtime_dependencies_ok()
                message = "XTTS-Runtime vollständig neu aufgebaut." if ok else check_detail
                XttsBackend._repair_cache[cache_key] = (now, ok, message)
                return ok, message
            pip_probe = subprocess.run(
                [str(candidate), "-m", "pip", "--version"],
                capture_output=True,
                text=True,
                env=env,
                timeout=30,
            )
            if pip_probe.returncode != 0:
                ensure_pip = subprocess.run(
                    [str(candidate), "-m", "ensurepip", "--upgrade"],
                    capture_output=True,
                    text=True,
                    env=env,
                    timeout=120,
                )
                if ensure_pip.returncode != 0:
                    message = ensure_pip.stderr.strip() or ensure_pip.stdout.strip() or "pip konnte nicht vorbereitet werden"
                    XttsBackend._repair_cache[cache_key] = (now, False, message)
                    return False, message
            install_targets = ["numpy"]
            if "No module named 'TTS'" in normalized_detail or 'No module named "TTS"' in normalized_detail:
                install_targets.extend(["TTS", "transformers<4.50"])
            install_cmd = [
                str(candidate),
                "-m",
                "pip",
                "install",
                "--upgrade",
                *install_targets,
            ]
            install = subprocess.run(
                install_cmd,
                capture_output=True,
                text=True,
                env=env,
                timeout=900,
            )
            if install.returncode != 0:
                message = install.stderr.strip() or install.stdout.strip() or "XTTS-Runtime konnte nicht automatisch repariert werden"
                XttsBackend._repair_cache[cache_key] = (now, False, message)
                return False, message
            XttsBackend.shutdown_all_servers()
            XttsBackend._dependency_cache.pop(cache_key, None)
            ok, check_detail = self.runtime_dependencies_ok()
            message = (
                "XTTS-Runtime automatisch repariert."
                if ok
                else f"Automatische XTTS-Reparatur lief durch, aber die Runtime bleibt unvollständig: {check_detail}"
            )
            XttsBackend._repair_cache[cache_key] = (now, ok, message)
            return ok, message

    def _setup_paths(self):
        from book2mp3.config import AppPaths

        return AppPaths.from_project_root(self.runtime_root.parent if self.runtime_root.name == "runtime" else self.runtime_root)

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
        with perf_scope("xtts.runtime_probe", category="xtts", device_mode=self.device_mode):
            result = subprocess.run(
                [str(self.python_path()), str(checker)],
                capture_output=True,
                text=True,
                env=env,
            )
        if result.returncode not in {0, 1}:
            raise RuntimeError(f"XTTS runtime probe failed: {result.stderr.strip() or result.stdout.strip()}")
        probe = json.loads(result.stdout)
        perf_event(
            "xtts.runtime_probe.result",
            category="xtts",
            device_mode=self.device_mode,
            torch_version=probe.get("torch_version"),
            cuda_available=probe.get("cuda_available"),
            device_count=probe.get("device_count"),
            allocation_ok=probe.get("allocation_ok"),
            gpu_names=probe.get("gpu_names", []),
        )
        return probe

    def subprocess_env(self) -> dict[str, str]:
        env = os.environ.copy()
        python_path = self.python_path()
        app_src_root = Path(__file__).resolve().parents[2]
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
            env["PYTHONPATH"] = str(app_src_root)
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

    def warmup_profile(self, profile: VoiceProfile, *, speaker_sample_limit: int = 1) -> None:
        if not self.server_enabled():
            return
        payload: dict[str, object] = {
            "command": "warmup",
            "model_name": profile.preferred_model,
            "device_mode": self.device_mode,
        }
        speaker_samples = profile.samples[:speaker_sample_limit] if speaker_sample_limit > 0 else profile.samples
        if speaker_samples:
            payload["speaker_wav"] = speaker_samples
            preview_profile = VoiceProfile(
                profile_id=profile.profile_id,
                display_name=profile.display_name,
                target_language=profile.target_language,
                backend=profile.backend,
                notes=profile.notes,
                samples=speaker_samples,
                validation_warnings=profile.validation_warnings,
                preferred_model=profile.preferred_model,
            )
            cache_dir = self.conditioning_cache_dir(preview_profile)
            if cache_dir is not None:
                payload["conditioning_cache_dir"] = str(cache_dir)
        started = time.perf_counter()
        try:
            response = self._request_server(payload)
        except Exception as exc:
            if self.logger:
                self.logger.info("XTTS warmup skipped after server issue: %s", exc)
            return
        if self.logger:
            self.logger.info(
                "XTTS warmup finished in %.2fs for profile=%s response=%s",
                time.perf_counter() - started,
                profile.profile_id,
                response,
            )

    def conditioning_cache_dir(self, profile: VoiceProfile) -> Path | None:
        sample_paths = [Path(sample) for sample in profile.samples]
        if not sample_paths:
            return None
        try:
            profile_dir = sample_paths[0].resolve().parent.parent
        except OSError:
            return None
        return profile_dir / ".xtts_cache"

    def synthesize_to_wav(
        self,
        text: str,
        profile: VoiceProfile,
        wav_path: Path,
        length_scale: float = 1.0,
        enable_text_splitting: bool = False,
        inference_options: dict[str, object] | None = None,
    ) -> None:
        self.synthesize_many_to_wavs(
            [text],
            profile,
            [wav_path],
            length_scale=length_scale,
            enable_text_splitting=enable_text_splitting,
            inference_options=inference_options,
        )

    def synthesize_many_to_wavs(
        self,
        texts: list[str],
        profile: VoiceProfile,
        wav_paths: list[Path],
        length_scale: float = 1.0,
        enable_text_splitting: bool = False,
        inference_options: dict[str, object] | None = None,
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
        if inference_options:
            payload["xtts_inference"] = dict(inference_options)
        cache_dir = self.conditioning_cache_dir(profile)
        if cache_dir is not None:
            payload["conditioning_cache_dir"] = str(cache_dir)
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

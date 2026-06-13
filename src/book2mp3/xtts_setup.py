from __future__ import annotations

import platform
import shlex
import sys
from pathlib import Path

from book2mp3.config import AppPaths


def current_platform() -> str:
    system = platform.system().lower()
    if system not in {"linux", "windows"}:
        return "unsupported"
    return system


def xtts_setup_script(paths: AppPaths) -> Path:
    return paths.root / "scripts" / "setup_xtts_runtime.py"


def xtts_runtime_target(paths: AppPaths) -> Path:
    system = current_platform()
    if system == "linux":
        return paths.runtime / "xtts" / "linux"
    if system == "windows":
        return paths.runtime / "xtts" / "windows" / "python"
    raise RuntimeError(f"Unsupported platform for XTTS setup: {platform.system()}")


def xtts_setup_supported(paths: AppPaths) -> bool:
    return current_platform() in {"linux", "windows"} and xtts_setup_script(paths).exists()


def xtts_setup_command(paths: AppPaths, python_executable: str | Path | None = None) -> list[str]:
    python_bin = str(Path(python_executable or sys.executable))
    script = str(xtts_setup_script(paths))
    target = str(xtts_runtime_target(paths))
    system = current_platform()
    if system == "linux":
        return [python_bin, script, target, "--bootstrap-linux-standalone", "--torch-variant", "auto"]
    if system == "windows":
        return [python_bin, script, target, "--python", python_bin, "--torch-variant", "auto"]
    raise RuntimeError(f"Unsupported platform for XTTS setup: {platform.system()}")


def xtts_setup_command_text(paths: AppPaths, python_executable: str | Path | None = None) -> str:
    command = xtts_setup_command(paths, python_executable=python_executable)
    if current_platform() == "windows":
        return " ".join(_quote_windows_argument(part) for part in command)
    return shlex.join(command)


def xtts_launcher_hint() -> str:
    return "start.bat --install-xtts" if current_platform() == "windows" else "./start.sh --install-xtts"


def xtts_setup_summary(paths: AppPaths) -> str:
    if not xtts_setup_supported(paths):
        return "XTTS-Setup ist in dieser Laufzeit nicht vorbereitet."
    target = xtts_runtime_target(paths)
    if current_platform() == "linux":
        return (
            "XTTS ist optional. Piper funktioniert sofort. Für XTTS wird eine eigene Linux-Runtime "
            f"unter {target} aufgebaut."
        )
    return (
        "XTTS ist optional. Piper funktioniert sofort. Für XTTS wird eine eigene Windows-Runtime "
        f"unter {target} vorbereitet."
    )


def xtts_license_hint() -> str:
    return (
        "XTTS bleibt ein optionaler Zusatzpfad. Der automatische Download verbessert nur die Bedienung "
        "und löst die Modelllizenz nicht automatisch für öffentliche oder kommerzielle Nutzung."
    )


def _quote_windows_argument(value: str) -> str:
    if not value or any(char.isspace() or char in "\"&()[]{}^=;!'+,`~" for char in value):
        return f'"{value}"'
    return value

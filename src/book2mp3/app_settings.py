from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class AppSettings:
    debug_logging: bool = True
    default_preset_id: str = "balanced"
    default_output_mode: str = "timed_parts"
    default_target_part_minutes: int = 15
    default_keep_wav: bool = False
    default_max_chars: int = 220
    default_priority: int = 50
    xtts_device_mode: str = "auto"


def load_app_settings(path: Path) -> AppSettings:
    if not path.exists():
        return AppSettings()
    payload = json.loads(path.read_text(encoding="utf-8"))
    data = asdict(AppSettings())
    data.update(payload)
    return AppSettings(**data)


def save_app_settings(path: Path, settings: AppSettings) -> AppSettings:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(settings), indent=2, ensure_ascii=False), encoding="utf-8")
    return settings


def reset_workspace_state(workspace: Path) -> None:
    for name in ("jobs", "voice_settings", "preview_sessions", "voice_profiles"):
        target = workspace / name
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True, exist_ok=True)
    logs_dir = workspace / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    for entry in logs_dir.iterdir():
        if entry.is_file():
            entry.unlink()
        elif entry.is_dir():
            shutil.rmtree(entry)

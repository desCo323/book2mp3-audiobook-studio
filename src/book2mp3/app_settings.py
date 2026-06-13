from __future__ import annotations

import json
import os
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class AppSettings:
    ui_language: str = "auto"
    debug_logging: bool = True
    default_preset_id: str = "balanced"
    default_output_mode: str = "timed_parts"
    default_target_part_minutes: int = 15
    default_keep_wav: bool = False
    default_max_chars: int = 220
    default_priority: int = 50
    xtts_device_mode: str = "auto"
    xtts_processing_mode: str = "auto"


def load_app_settings(path: Path) -> AppSettings:
    if not path.exists():
        return AppSettings()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return AppSettings()
    data = asdict(AppSettings())
    data.update(payload)
    return AppSettings(**data)


def save_app_settings(path: Path, settings: AppSettings) -> AppSettings:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(asdict(settings), indent=2, ensure_ascii=False)
    try:
        path.write_text(payload, encoding="utf-8")
    except PermissionError:
        if path.exists():
            try:
                path.unlink()
            except OSError:
                pass
        try:
            path.write_text(payload, encoding="utf-8")
        except OSError:
            fallback = path.with_name(f"{path.stem}-{os.getpid()}{path.suffix}")
            fallback.write_text(payload, encoding="utf-8")
    return settings


def reset_workspace_state(workspace: Path) -> None:
    app_settings_path = workspace / "app_settings.json"
    for name in ("jobs", "voice_settings", "preview_sessions", "voice_profiles", "statistics"):
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
    for entry in workspace.iterdir():
        if entry == app_settings_path or entry.name in {"jobs", "voice_settings", "preview_sessions", "voice_profiles", "logs", "statistics"}:
            continue
        if entry.is_file():
            entry.unlink()
        elif entry.is_dir():
            shutil.rmtree(entry)

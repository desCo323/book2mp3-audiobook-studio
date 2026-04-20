from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from book2mp3.models import utc_now


@dataclass
class VoiceSetting:
    setting_id: str
    display_name: str
    voice_id: str
    preset_hint: str
    max_chars: int
    sentence_silence: float
    length_scale: float
    created_at: str
    updated_at: str
    notes: str = ""


def _settings_dir(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    return root


def _setting_path(root: Path, setting_id: str) -> Path:
    return _settings_dir(root) / f"{setting_id}.json"


def sanitize_setting_id(name: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "_" for ch in name.strip())
    cleaned = "_".join(part for part in cleaned.split("_") if part)
    return cleaned or "voice_setting"


def save_voice_setting(
    root: Path,
    display_name: str,
    voice_id: str,
    preset_hint: str,
    max_chars: int,
    sentence_silence: float,
    length_scale: float,
    notes: str = "",
) -> VoiceSetting:
    setting_id = sanitize_setting_id(display_name)
    now = utc_now()
    existing = load_voice_setting(root, setting_id) if _setting_path(root, setting_id).exists() else None
    setting = VoiceSetting(
        setting_id=setting_id,
        display_name=display_name,
        voice_id=voice_id,
        preset_hint=preset_hint,
        max_chars=max_chars,
        sentence_silence=sentence_silence,
        length_scale=length_scale,
        created_at=existing.created_at if existing else now,
        updated_at=now,
        notes=notes,
    )
    _setting_path(root, setting_id).write_text(
        json.dumps(asdict(setting), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return setting


def list_voice_settings(root: Path) -> list[VoiceSetting]:
    settings: list[VoiceSetting] = []
    for path in sorted(_settings_dir(root).glob("*.json")):
        settings.append(VoiceSetting(**json.loads(path.read_text(encoding="utf-8"))))
    return sorted(settings, key=lambda item: item.updated_at, reverse=True)


def load_voice_setting(root: Path, setting_id: str) -> VoiceSetting:
    return VoiceSetting(**json.loads(_setting_path(root, setting_id).read_text(encoding="utf-8")))

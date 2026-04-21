from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ImportedPiperModel:
    voice_id: str
    model_path: Path
    config_path: Path
    manifest_path: Path


def sanitize_voice_id(name: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() or ch in {"_", "-"} else "_" for ch in name.strip())
    cleaned = "_".join(part for part in cleaned.replace("-", "_").split("_") if part)
    return cleaned or "custom_piper_voice"


def default_config_for_model(model_path: Path) -> Path:
    candidates = [
        model_path.with_suffix(model_path.suffix + ".json"),
        model_path.with_name(model_path.name + ".json"),
        model_path.with_suffix(".json"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"No Piper config JSON found next to {model_path}")


def import_custom_piper_model(
    voices_root: Path,
    model_path: Path,
    config_path: Path | None = None,
    *,
    voice_id: str | None = None,
) -> ImportedPiperModel:
    if not model_path.exists():
        raise FileNotFoundError(f"Piper model file not found: {model_path}")
    config_path = config_path or default_config_for_model(model_path)
    if not config_path.exists():
        raise FileNotFoundError(f"Piper config file not found: {config_path}")

    resolved_voice_id = sanitize_voice_id(voice_id or model_path.stem)
    target_dir = voices_root / "custom" / resolved_voice_id
    target_dir.mkdir(parents=True, exist_ok=True)
    target_model = target_dir / f"{resolved_voice_id}.onnx"
    target_config = target_dir / f"{resolved_voice_id}.onnx.json"
    shutil.copy2(model_path, target_model)
    shutil.copy2(config_path, target_config)

    manifest = target_dir / "custom_piper_model.json"
    manifest.write_text(
        json.dumps(
            {
                "voice_id": resolved_voice_id,
                "source_model": str(model_path.resolve()),
                "source_config": str(config_path.resolve()),
                "installed_model": str(target_model),
                "installed_config": str(target_config),
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return ImportedPiperModel(
        voice_id=resolved_voice_id,
        model_path=target_model,
        config_path=target_config,
        manifest_path=manifest,
    )

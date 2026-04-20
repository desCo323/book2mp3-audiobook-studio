from __future__ import annotations

import json
import shutil
import wave
from dataclasses import asdict, dataclass
from pathlib import Path


SUPPORTED_SAMPLE_EXTENSIONS = {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac"}


@dataclass
class VoiceProfile:
    profile_id: str
    display_name: str
    target_language: str
    backend: str
    notes: str
    samples: list[str]
    validation_warnings: list[str]
    preferred_model: str = "tts_models/multilingual/multi-dataset/xtts_v2"


def sanitize_profile_id(name: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "_" for ch in name.strip())
    cleaned = "_".join(part for part in cleaned.split("_") if part)
    return cleaned or "voice_profile"


def validate_sample(sample_path: Path) -> list[str]:
    warnings: list[str] = []
    if sample_path.suffix.lower() not in SUPPORTED_SAMPLE_EXTENSIONS:
        warnings.append(f"Unsupported extension: {sample_path.suffix}")
        return warnings
    if sample_path.suffix.lower() == ".wav":
        try:
            with wave.open(str(sample_path), "rb") as wav_file:
                frames = wav_file.getnframes()
                rate = wav_file.getframerate()
                duration = frames / rate if rate else 0
                channels = wav_file.getnchannels()
                if duration < 3:
                    warnings.append("Reference sample is very short; aim for at least 3 seconds.")
                if duration > 30:
                    warnings.append("Reference sample is long; short focused samples usually clone better.")
                if channels != 1:
                    warnings.append("Mono WAV is recommended for predictable cloning quality.")
        except wave.Error as exc:
            warnings.append(f"WAV parse failed: {exc}")
    else:
        warnings.append("Non-WAV sample added. Acceptable, but WAV is recommended for first-pass cloning.")
    if sample_path.stat().st_size < 16_000:
        warnings.append("Sample file is very small; quality may be poor.")
    return warnings


def create_voice_profile(
    profiles_root: Path,
    display_name: str,
    target_language: str,
    backend: str,
    notes: str,
    sample_paths: list[Path],
) -> Path:
    profile_id = sanitize_profile_id(display_name)
    profile_dir = profiles_root / profile_id
    sample_dir = profile_dir / "samples"
    sample_dir.mkdir(parents=True, exist_ok=True)

    copied_samples: list[str] = []
    warnings: list[str] = []
    for source in sample_paths:
        target = sample_dir / source.name
        if source.resolve() != target.resolve():
            shutil.copy2(source, target)
        copied_samples.append(str(target))
        warnings.extend(validate_sample(target))

    profile = VoiceProfile(
        profile_id=profile_id,
        display_name=display_name,
        target_language=target_language,
        backend=backend,
        notes=notes,
        samples=copied_samples,
        validation_warnings=warnings,
    )
    manifest = profile_dir / "profile.json"
    manifest.write_text(json.dumps(asdict(profile), indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


def list_voice_profiles(profiles_root: Path) -> list[VoiceProfile]:
    profiles: list[VoiceProfile] = []
    for manifest in sorted(profiles_root.glob("*/profile.json")):
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        profiles.append(VoiceProfile(**payload))
    return profiles


def load_voice_profile(profiles_root: Path, profile_id: str) -> VoiceProfile:
    manifest = profiles_root / profile_id / "profile.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    return VoiceProfile(**payload)

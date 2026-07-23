from __future__ import annotations

import json
import tempfile
from pathlib import Path

from book2mp3.config import AppPaths
from book2mp3.service import Book2Mp3Service
from book2mp3.voice_settings import (
    DEFAULT_RAMONA_VOICE_PROFILE_ID,
    PROFILE_STATUS_APPROVED,
    STANDARD_XTTS_DISPLAY_NAME,
    STANDARD_XTTS_LENGTH_SCALE,
    STANDARD_XTTS_MAX_CHARS,
    STANDARD_XTTS_SETTING_ID,
    ensure_standard_xtts_setting,
    load_voice_setting,
    save_voice_setting,
    standard_xtts_inference,
)
from book2mp3.xtts_options import normalize_xtts_inference

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    real_paths = AppPaths.from_project_root(ROOT)
    expected_inference = normalize_xtts_inference(standard_xtts_inference(), quality_mode="max_quality")

    with tempfile.TemporaryDirectory(prefix="book2mp3-smoke-standard-xtts-") as tmp_dir:
        root = Path(tmp_dir)
        (root / "runtime").symlink_to(real_paths.runtime, target_is_directory=True)
        (root / "voices").symlink_to(real_paths.voices, target_is_directory=True)
        workspace = root / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        (workspace / "voice_profiles").symlink_to(real_paths.voice_profiles, target_is_directory=True)
        paths = AppPaths.from_project_root(root)
        paths.ensure()

        save_voice_setting(
            paths.voice_settings,
            display_name="Ramona Live XTTS",
            backend="xtts",
            voice_id="de_DE-ramona-low",
            voice_profile_id="xtts_deutsch_weiblich_warm",
            preset_hint="premium_natural",
            max_chars=100,
            output_mode="chapter_files",
            target_part_minutes=20,
            sentence_silence=0.24,
            length_scale=1.03,
            status=PROFILE_STATUS_APPROVED,
            xtts_quality_mode="max_quality",
            xtts_inference={"temperature": 0.65, "top_p": 0.85, "top_k": 50, "num_beams": 2},
            pronunciation_rules=[{"match": "Talwyn", "spoken_as": "Talwin", "enabled": True}],
            setting_id=STANDARD_XTTS_SETTING_ID,
        )

        migrated = ensure_standard_xtts_setting(paths.voice_settings, paths.voice_profiles)
        if migrated is None:
            raise AssertionError("Expected Standard XTTS profile to be created")
        if migrated.display_name != STANDARD_XTTS_DISPLAY_NAME:
            raise AssertionError(f"Expected {STANDARD_XTTS_DISPLAY_NAME!r}, got {migrated.display_name!r}")
        if migrated.status != PROFILE_STATUS_APPROVED:
            raise AssertionError(f"Expected approved profile, got {migrated.status!r}")
        if migrated.max_chars != STANDARD_XTTS_MAX_CHARS:
            raise AssertionError(f"Expected max_chars={STANDARD_XTTS_MAX_CHARS}, got {migrated.max_chars}")
        if migrated.length_scale != STANDARD_XTTS_LENGTH_SCALE:
            raise AssertionError(f"Expected length_scale={STANDARD_XTTS_LENGTH_SCALE}, got {migrated.length_scale}")
        if migrated.xtts_inference != expected_inference:
            raise AssertionError(f"Expected Standard XTTS inference, got {migrated.xtts_inference}")
        if migrated.voice_profile_id != DEFAULT_RAMONA_VOICE_PROFILE_ID:
            raise AssertionError(
                f"Expected Standard XTTS profile {DEFAULT_RAMONA_VOICE_PROFILE_ID}, got {migrated.voice_profile_id}"
            )

        source_path = root / "Talwyn Test.txt"
        source_path.write_text("Talwyn sprach mit Éibhear und Rhi.", encoding="utf-8")
        service = Book2Mp3Service(paths)
        created = service.create_job(source_path=source_path)
        state = service.manager.load_state(created["job_id"])
        if state.saved_profile_id != STANDARD_XTTS_SETTING_ID:
            raise AssertionError(f"Expected fallback profile {STANDARD_XTTS_SETTING_ID}, got {state.saved_profile_id}")
        if state.saved_profile_name != STANDARD_XTTS_DISPLAY_NAME:
            raise AssertionError(f"Expected fallback name {STANDARD_XTTS_DISPLAY_NAME}, got {state.saved_profile_name}")
        if state.backend != "xtts":
            raise AssertionError(f"Expected XTTS backend, got {state.backend}")
        if state.max_chars != STANDARD_XTTS_MAX_CHARS:
            raise AssertionError(f"Expected job max_chars={STANDARD_XTTS_MAX_CHARS}, got {state.max_chars}")
        if state.length_scale != STANDARD_XTTS_LENGTH_SCALE:
            raise AssertionError(f"Expected job length_scale={STANDARD_XTTS_LENGTH_SCALE}, got {state.length_scale}")
        if state.xtts_inference != expected_inference:
            raise AssertionError(f"Expected job Standard XTTS inference, got {state.xtts_inference}")

        stored = load_voice_setting(paths.voice_settings, STANDARD_XTTS_SETTING_ID)
        print(
            json.dumps(
                {
                    "setting_id": stored.setting_id,
                    "display_name": stored.display_name,
                    "job_id": state.job_id,
                    "job_backend": state.backend,
                    "job_profile": state.saved_profile_id,
                    "voice_profile_id": stored.voice_profile_id,
                    "max_chars": state.max_chars,
                    "length_scale": state.length_scale,
                    "xtts_inference": state.xtts_inference,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

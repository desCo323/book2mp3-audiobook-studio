from __future__ import annotations

import json
import tempfile
from pathlib import Path

from book2mp3.config import AppPaths
from book2mp3.service import Book2Mp3Service
from book2mp3.voice_settings import load_voice_setting, save_voice_setting

ROOT = Path(__file__).resolve().parents[1]
CUSTOM_PROFILE_ID = "xtts_custom_pronunciation"


def main() -> int:
    real_paths = AppPaths.from_project_root(ROOT)
    source_setting = load_voice_setting(real_paths.voice_settings, "xtts1")
    with tempfile.TemporaryDirectory(prefix="book2mp3-smoke-xtts-pron-") as tmp_dir:
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
            display_name=source_setting.display_name,
            backend=source_setting.backend,
            voice_id=source_setting.voice_id,
            voice_profile_id=source_setting.voice_profile_id,
            preset_hint=source_setting.preset_hint,
            max_chars=source_setting.max_chars,
            output_mode=source_setting.output_mode,
            target_part_minutes=source_setting.target_part_minutes,
            sentence_silence=source_setting.sentence_silence,
            length_scale=source_setting.length_scale,
            notes=source_setting.notes,
            status=source_setting.status,
            approved_at=source_setting.approved_at,
            benchmark_average_ms=source_setting.benchmark_average_ms,
            last_benchmark_ms=source_setting.last_benchmark_ms,
            last_benchmark_at=source_setting.last_benchmark_at,
            source_session_id=source_setting.source_session_id,
            source_run_id=source_setting.source_run_id,
            source_candidate_id=source_setting.source_candidate_id,
            xtts_quality_mode="quality",
            pronunciation_rules=[{"match": "Aiken", "spoken_as": "Eyken", "enabled": True}],
            setting_id=CUSTOM_PROFILE_ID,
        )
        source_path = root / "source.txt"
        source_path.write_text(
            "Dragon Dream von Aiken. Aiken sah zum Mond hinauf.",
            encoding="utf-8",
        )
        service = Book2Mp3Service(paths)
        created = service.create_job(source_path=source_path, saved_profile_id=CUSTOM_PROFILE_ID)
        state = service.manager.load_state(created["job_id"])
        chunk = state.chunks[0]
        spoken_text_path = Path(chunk.spoken_text_file) if chunk.spoken_text_file else Path(chunk.text_file)
        if spoken_text_path.is_dir():
            spoken_text_path = Path(chunk.text_file)
        spoken_text = spoken_text_path.read_text(encoding="utf-8")
        if state.xtts_quality_mode != "quality":
            raise AssertionError(f"Expected quality mode, got {state.xtts_quality_mode}")
        if state.xtts_inference.get("num_beams") != 2:
            raise AssertionError(f"Expected num_beams=2, got {state.xtts_inference}")
        if "Eyken" not in spoken_text:
            raise AssertionError(f"Expected transformed spoken text, got {spoken_text!r}")
        if spoken_text.count("Eyken") < 2:
            raise AssertionError(f"Expected repeated pronunciation replacement, got {spoken_text!r}")
        print(
            json.dumps(
                {
                    "job_id": state.job_id,
                    "quality_mode": state.xtts_quality_mode,
                    "xtts_inference": state.xtts_inference,
                    "spoken_text_file": str(spoken_text_path),
                    "spoken_text": spoken_text,
                    "rule_occurrences": spoken_text.count("Eyken"),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

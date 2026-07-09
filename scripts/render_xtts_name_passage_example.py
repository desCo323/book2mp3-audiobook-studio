from __future__ import annotations

import json
import shutil
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from book2mp3.config import AppPaths
from book2mp3.tts.xtts import XttsBackend
from book2mp3.voice_lab import load_voice_profile
from book2mp3.voice_settings import load_voice_setting
from book2mp3.xtts_options import safe_xtts_chunk_chars
from scripts.render_xtts_dialogue_example import RenderVariant, _logger, _render_variant


SOURCE_JOB_ID = "d683f2a91148"
SOURCE_CHUNK_START = 1948
SOURCE_CHUNK_END = 1956
VARIANT_KEY = "names_01_expressive_context"

NAME_PRONUNCIATION_OVERRIDES = [
    {"match": "Calondirs", "spoken_as": "Kalondirs", "scope": "whole_phrase", "enabled": True},
    {"match": "Calondir", "spoken_as": "Kalondir", "scope": "whole_phrase", "enabled": True},
    {"match": "Dragos", "spoken_as": "Dragos", "scope": "whole_phrase", "enabled": True},
    {"match": "Pia", "spoken_as": "Pia", "scope": "whole_phrase", "enabled": True},
    {"match": "Wyr", "spoken_as": "Wier", "scope": "whole_phrase", "enabled": True},
    {"match": "Quentin", "spoken_as": "Kwentin", "scope": "whole_phrase", "enabled": True},
    {"match": "Pegasus", "spoken_as": "Pegasus", "scope": "whole_phrase", "enabled": True},
    {"match": "Carling", "spoken_as": "Karling", "scope": "whole_phrase", "enabled": True},
    {"match": "Runes", "spoken_as": "Ruuns", "scope": "whole_phrase", "enabled": True},
    {"match": "Baynes", "spoken_as": "Beyns", "scope": "whole_phrase", "enabled": True},
    {"match": "Bayne", "spoken_as": "Beyn", "scope": "whole_phrase", "enabled": True},
    {"match": "Constantine", "spoken_as": "Konstantin", "scope": "whole_phrase", "enabled": True},
    {"match": "Graydon", "spoken_as": "Greydon", "scope": "whole_phrase", "enabled": True},
    {"match": "Eva", "spoken_as": "Eva", "scope": "whole_phrase", "enabled": True},
    {"match": "Miguel", "spoken_as": "Migel", "scope": "whole_phrase", "enabled": True},
    {"match": "Hugh", "spoken_as": "Hju", "scope": "whole_phrase", "enabled": True},
    {"match": "Andrea", "spoken_as": "Andrea", "scope": "whole_phrase", "enabled": True},
    {"match": "Johnny", "spoken_as": "Dschonni", "scope": "whole_phrase", "enabled": True},
    {"match": "James", "spoken_as": "Dschehms", "scope": "whole_phrase", "enabled": True},
    {"match": "Irish Wolfhound", "spoken_as": "Airisch Wolfhaund", "scope": "whole_phrase", "enabled": True},
]


def _read_source_passage(paths: AppPaths) -> tuple[str, list[str]]:
    chunk_dir = paths.workspace / "jobs" / SOURCE_JOB_ID / "chunks"
    selected_paths = [chunk_dir / f"{index:05d}.txt" for index in range(SOURCE_CHUNK_START, SOURCE_CHUNK_END + 1)]
    missing = [str(path) for path in selected_paths if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Missing source chunks for name passage example: {missing}")
    chunks = [path.read_text(encoding="utf-8").strip() for path in selected_paths]
    return " ".join(chunk for chunk in chunks if chunk), [str(path) for path in selected_paths]


def _remove_variant_artifacts(example_dir: Path) -> None:
    for child in (
        example_dir / "wav" / VARIANT_KEY,
        example_dir / "spoken_chunks" / VARIANT_KEY,
    ):
        if child.exists():
            shutil.rmtree(child)
    for child in (
        example_dir / f"{VARIANT_KEY}.mp3",
        example_dir / "name_passage_source.txt",
        example_dir / "name_passage_summary.json",
    ):
        if child.exists():
            child.unlink()


def main() -> int:
    root = Path.cwd()
    paths = AppPaths.from_project_root(root)
    example_dir = paths.workspace / "manual_checks" / "xtts_example"
    example_dir.mkdir(parents=True, exist_ok=True)
    _remove_variant_artifacts(example_dir)

    source_text, source_files = _read_source_passage(paths)
    source_path = example_dir / "name_passage_source.txt"
    source_path.write_text(source_text + "\n", encoding="utf-8")

    logger = _logger()
    setting = load_voice_setting(paths.voice_settings, "xtts1")
    profile = load_voice_profile(paths.voice_profiles, setting.voice_profile_id)
    expressive_context_inference_options = {
        **dict(setting.xtts_inference),
        "temperature": 0.82,
        "top_p": 0.96,
        "top_k": 80,
        "repetition_penalty": 4.0,
        "num_beams": 1,
        "do_sample": True,
        "gpt_cond_len": 30,
        "gpt_cond_chunk_len": 6,
        "max_ref_length": 45,
        "sound_norm_refs": True,
        "librosa_trim_db": None,
    }
    variant = RenderVariant(
        key=VARIANT_KEY,
        label="Expressive context test with dense fantasy and character names",
        file_name=f"{VARIANT_KEY}.mp3",
        max_chars=safe_xtts_chunk_chars(160, profile.target_language),
        length_scale=0.96,
        inference_options=expressive_context_inference_options,
        pronunciation_overrides=NAME_PRONUNCIATION_OVERRIDES,
    )

    try:
        result = _render_variant(
            paths,
            example_dir,
            source_text,
            variant,
            setting.pronunciation_rules,
            profile,
            logger,
        )
    finally:
        XttsBackend.shutdown_all_servers()

    summary = {
        "accepted": result.accepted,
        "setting_id": setting.setting_id,
        "setting_name": setting.display_name,
        "profile_id": profile.profile_id,
        "profile_name": profile.display_name,
        "source_job_id": SOURCE_JOB_ID,
        "source_chunks": [SOURCE_CHUNK_START, SOURCE_CHUNK_END],
        "source_files": source_files,
        "source_file": str(source_path),
        "variant": asdict(result),
        "selected_reason": (
            "Manual pick from the name-density scan: a Wyr/dragon passage with Calondir, Dragos, Pia, "
            "Quentin, Pegasus, Carling, Rune, Bayne, Constantine, Graydon, Eva, Miguel, Hugh, Andrea, "
            "Johnny, James, and Irish Wolfhound."
        ),
    }
    (example_dir / "name_passage_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    if not result.accepted:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

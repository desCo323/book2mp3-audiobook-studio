from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path

from book2mp3.config import AppPaths
from book2mp3.models import utc_now
from book2mp3.presets import get_preset
from book2mp3.voice_catalog import filter_voice_ids, is_female_voice, voice_language_code
from book2mp3.voice_lab import VoiceProfile, list_voice_profiles
from book2mp3.utils.workspace_files import ensure_writable_directory, safe_write_json


LOGGER = logging.getLogger("book2mp3.voice_test_assistant")


@dataclass
class VoiceTestCandidate:
    candidate_id: str
    label: str
    backend: str
    language_code: str
    gender_hint: str
    voice_id: str
    voice_profile_id: str
    preset_id: str
    max_chars: int
    output_mode: str
    target_part_minutes: int
    sentence_silence: float
    length_scale: float
    notes: str = ""
    rating: int = 0
    rating_note: str = ""
    preview_file: str = ""
    render_duration_ms: float = 0.0
    last_rendered_at: str = ""
    benchmark_runs: int = 0
    benchmark_total_ms: float = 0.0


@dataclass
class VoiceTestRun:
    run_id: str
    session_id: str
    title: str
    requested_language: str
    requested_gender: str
    requested_style: str
    created_at: str
    updated_at: str
    selected_backend: str = "piper"
    workflow_step: str = "prepare"
    winner_candidate_id: str = ""
    refinement_round: int = 0
    mode: str = "assistant"
    manual_candidate_counter: int = 0
    candidates: list[VoiceTestCandidate] = field(default_factory=list)


def _run_path(paths: AppPaths, session_id: str) -> Path:
    return paths.preview_sessions / session_id / "voice_test_run.json"


def load_voice_test_run(paths: AppPaths, session_id: str) -> VoiceTestRun | None:
    path = _run_path(paths, session_id)
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.setdefault("selected_backend", "piper")
    payload.setdefault("workflow_step", "prepare")
    payload.setdefault("winner_candidate_id", "")
    payload["candidates"] = [VoiceTestCandidate(**candidate) for candidate in payload.get("candidates", [])]
    return VoiceTestRun(**payload)


def save_voice_test_run(paths: AppPaths, run: VoiceTestRun) -> VoiceTestRun:
    run.updated_at = utc_now()
    path = _run_path(paths, run.session_id)
    ensure_writable_directory(path.parent, logger=LOGGER)
    safe_write_json(path, asdict(run), logger=LOGGER)
    return run


def profile_gender_hint(profile: VoiceProfile) -> str:
    haystack = f"{profile.display_name} {profile.profile_id}".lower()
    if any(token in haystack for token in ("female", "weib", "frau")):
        return "female"
    if any(token in haystack for token in ("male", "maenn", "mann", "thorsten")):
        return "male"
    return "unknown"


def profile_matches_language(profile: VoiceProfile, language_code: str) -> bool:
    if not language_code:
        return True
    target = (profile.target_language or "").lower()
    wanted = language_code.lower()
    if target == wanted:
        return True
    return target.split("_", 1)[0] == wanted.split("_", 1)[0]


def _gender_matches(requested_gender: str, actual_gender: str) -> bool:
    if requested_gender in {"", "any"}:
        return True
    if actual_gender == "unknown":
        return requested_gender == "any"
    return requested_gender == actual_gender


def _style_defaults(style: str, backend: str) -> dict[str, object]:
    preset_map = {
        "novel": ("natural", 260, "chapter_files", 20, 0.28, 1.04),
        "nonfiction": ("balanced", 220, "chapter_files", 15, 0.20, 1.00),
        "children": ("natural", 240, "chapter_files", 12, 0.30, 1.03),
        "cpu": ("fast_cpu", 170, "segments", 10, 0.12, 0.95),
    }
    preset_id, max_chars, output_mode, part_minutes, sentence_silence, length_scale = preset_map.get(
        style,
        preset_map["nonfiction"],
    )
    if backend == "xtts":
        preset_id = "premium_natural"
        max_chars = max(max_chars, 260)
        sentence_silence = 0.22
        length_scale = 1.0
    preset = get_preset(preset_id)
    return {
        "preset_id": preset.preset_id,
        "max_chars": max_chars,
        "output_mode": output_mode,
        "target_part_minutes": part_minutes,
        "sentence_silence": sentence_silence,
        "length_scale": length_scale,
        "notes": preset.description,
    }


def _piper_candidates(
    voice_ids: list[str],
    language_code: str,
    requested_gender: str,
    style: str,
) -> list[VoiceTestCandidate]:
    female_only = requested_gender == "female"
    filtered = filter_voice_ids(voice_ids, language_code, female_only=female_only, high_only=False)
    if not filtered and language_code:
        wanted_prefix = language_code.lower().split("_", 1)[0]
        filtered = [
            voice_id
            for voice_id in voice_ids
            if voice_language_code(voice_id).lower().split("_", 1)[0] == wanted_prefix
        ]
        if female_only:
            filtered = [voice_id for voice_id in filtered if is_female_voice(voice_id)]
    if requested_gender == "male":
        filtered = [voice_id for voice_id in filtered if not is_female_voice(voice_id)]
    defaults = _style_defaults(style, "piper")
    candidates: list[VoiceTestCandidate] = []
    for index, voice_id in enumerate(filtered[:4], start=1):
        gender_hint = "female" if is_female_voice(voice_id) else "male"
        candidates.append(
            VoiceTestCandidate(
                candidate_id=f"piper_{index:02d}_{voice_id}",
                label=f"Piper {index}: {voice_id}",
                backend="piper",
                language_code=voice_language_code(voice_id),
                gender_hint=gender_hint,
                voice_id=voice_id,
                voice_profile_id="",
                **defaults,
            )
        )
    return candidates


def _xtts_candidates(
    profiles: list[VoiceProfile],
    language_code: str,
    requested_gender: str,
    style: str,
) -> list[VoiceTestCandidate]:
    defaults = _style_defaults(style, "xtts")
    matches = []
    for profile in profiles:
        if not profile.samples or not profile_matches_language(profile, language_code):
            continue
        gender_hint = profile_gender_hint(profile)
        if not _gender_matches(requested_gender, gender_hint if gender_hint != "unknown" else "any"):
            continue
        matches.append((profile, gender_hint))
    candidates: list[VoiceTestCandidate] = []
    for index, (profile, gender_hint) in enumerate(matches[:3], start=1):
        candidates.append(
            VoiceTestCandidate(
                candidate_id=f"xtts_{index:02d}_{profile.profile_id}",
                label=f"XTTS {index}: {profile.display_name}",
                backend="xtts",
                language_code=profile.target_language,
                gender_hint=gender_hint,
                voice_id="",
                voice_profile_id=profile.profile_id,
                **defaults,
            )
        )
    return candidates


def create_voice_test_run(
    paths: AppPaths,
    *,
    session_id: str,
    title: str,
    requested_language: str,
    requested_gender: str,
    requested_style: str,
) -> VoiceTestRun:
    piper_voice_ids = [
        voice_id
        for voice_id in sorted({path.stem.split(".onnx", 1)[0] for path in paths.voices.rglob("*.onnx")})
        if voice_id
    ]
    xtts_profiles = list_voice_profiles(paths.voice_profiles)
    candidates = _piper_candidates(piper_voice_ids, requested_language, requested_gender, requested_style)
    candidates.extend(_xtts_candidates(xtts_profiles, requested_language, requested_gender, requested_style))
    run = VoiceTestRun(
        run_id=f"run_{session_id}",
        session_id=session_id,
        title=title,
        requested_language=requested_language,
        requested_gender=requested_gender or "any",
        requested_style=requested_style,
        created_at=utc_now(),
        updated_at=utc_now(),
        selected_backend="piper",
        workflow_step="candidates",
        refinement_round=0,
        candidates=candidates,
    )
    return save_voice_test_run(paths, run)


def create_benchmark_run(
    paths: AppPaths,
    *,
    session_id: str,
    title: str,
    requested_language: str,
    requested_gender: str,
    requested_style: str,
) -> VoiceTestRun:
    run = VoiceTestRun(
        run_id=f"benchmark_{session_id}",
        session_id=session_id,
        title=title,
        requested_language=requested_language,
        requested_gender=requested_gender or "any",
        requested_style=requested_style,
        created_at=utc_now(),
        updated_at=utc_now(),
        selected_backend="piper",
        workflow_step="candidates",
        refinement_round=0,
        mode="benchmark",
        candidates=[],
    )
    return save_voice_test_run(paths, run)


def best_rated_candidate(run: VoiceTestRun) -> VoiceTestCandidate | None:
    rated = [candidate for candidate in run.candidates if candidate.rating > 0]
    if not rated:
        return None
    return sorted(
        rated,
        key=lambda item: (
            -item.rating,
            item.render_duration_ms if item.render_duration_ms > 0 else 10**9,
            item.label,
        ),
    )[0]


def create_refinement_round(paths: AppPaths, run: VoiceTestRun) -> VoiceTestRun:
    best = best_rated_candidate(run)
    if best is None:
        return run
    run.selected_backend = best.backend
    run.workflow_step = "refine"
    run.winner_candidate_id = best.candidate_id
    base = best
    adjustments = [
        ("Fokus schneller", -20, -0.02, -0.02),
        ("Fokus ruhiger", 20, 0.04, 0.03),
        ("Fokus neutral", 0, 0.0, 0.0),
    ]
    refined: list[VoiceTestCandidate] = []
    for index, (label_suffix, chars_delta, silence_delta, length_delta) in enumerate(adjustments, start=1):
        refined.append(
            VoiceTestCandidate(
                candidate_id=f"{base.candidate_id}_r{run.refinement_round + 1}_{index}",
                label=f"{base.label} | {label_suffix}",
                backend=base.backend,
                language_code=base.language_code,
                gender_hint=base.gender_hint,
                voice_id=base.voice_id,
                voice_profile_id=base.voice_profile_id,
                preset_id=base.preset_id,
                max_chars=max(140, min(420, base.max_chars + chars_delta)),
                output_mode=base.output_mode,
                target_part_minutes=base.target_part_minutes,
                sentence_silence=max(0.08, min(0.40, base.sentence_silence + silence_delta)),
                length_scale=max(0.90, min(1.12, base.length_scale + length_delta)),
                notes=f"Verfeinerung aus {base.label}",
            )
        )
    run.refinement_round += 1
    run.candidates = refined
    return save_voice_test_run(paths, run)


def create_chunk_tuning_round(paths: AppPaths, run: VoiceTestRun) -> VoiceTestRun:
    base = best_rated_candidate(run)
    if base is None:
        return run
    run.selected_backend = base.backend
    run.workflow_step = "chunk_tuning"
    run.winner_candidate_id = base.candidate_id
    variants = [
        ("Chunk kompakt", max(140, base.max_chars - 80), max(0.10, base.sentence_silence - 0.04), max(0.94, base.length_scale - 0.02)),
        ("Chunk ausgewogen", max(160, base.max_chars - 20), base.sentence_silence, base.length_scale),
        ("Chunk gross", min(420, base.max_chars + 40), min(0.36, base.sentence_silence + 0.02), min(1.08, base.length_scale + 0.01)),
        ("Chunk maximal", min(450, base.max_chars + 100), min(0.38, base.sentence_silence + 0.04), min(1.10, base.length_scale + 0.02)),
    ]
    run.refinement_round += 1
    run.mode = "chunk_tuning"
    run.candidates = [
        VoiceTestCandidate(
            candidate_id=f"{base.candidate_id}_chunk_{run.refinement_round}_{index}",
            label=f"{base.label} | {label}",
            backend=base.backend,
            language_code=base.language_code,
            gender_hint=base.gender_hint,
            voice_id=base.voice_id,
            voice_profile_id=base.voice_profile_id,
            preset_id=base.preset_id,
            max_chars=max_chars,
            output_mode=base.output_mode,
            target_part_minutes=base.target_part_minutes,
            sentence_silence=sentence_silence,
            length_scale=length_scale,
            notes=f"Chunk-Tuning aus {base.label}",
        )
        for index, (label, max_chars, sentence_silence, length_scale) in enumerate(variants, start=1)
    ]
    return save_voice_test_run(paths, run)


def update_candidate_feedback(
    paths: AppPaths,
    run: VoiceTestRun,
    candidate_id: str,
    *,
    rating: int | None = None,
    rating_note: str | None = None,
    preview_file: str | None = None,
    render_duration_ms: float | None = None,
) -> VoiceTestRun:
    for candidate in run.candidates:
        if candidate.candidate_id != candidate_id:
            continue
        if rating is not None:
            candidate.rating = rating
        if rating_note is not None:
            candidate.rating_note = rating_note
        if preview_file is not None:
            candidate.preview_file = preview_file
        if render_duration_ms is not None:
            candidate.render_duration_ms = render_duration_ms
        candidate.last_rendered_at = utc_now()
        break
    winner = best_rated_candidate(run)
    run.winner_candidate_id = winner.candidate_id if winner is not None else ""
    return save_voice_test_run(paths, run)


def add_candidate_to_run(paths: AppPaths, run: VoiceTestRun, candidate: VoiceTestCandidate) -> VoiceTestRun:
    run.manual_candidate_counter += 1
    if not candidate.candidate_id:
        candidate.candidate_id = f"manual_{run.manual_candidate_counter:03d}"
    run.selected_backend = candidate.backend
    run.workflow_step = "candidates"
    run.candidates.append(candidate)
    return save_voice_test_run(paths, run)


def average_render_duration_ms(candidate: VoiceTestCandidate) -> float:
    if candidate.benchmark_runs > 0 and candidate.benchmark_total_ms > 0:
        return candidate.benchmark_total_ms / candidate.benchmark_runs
    return candidate.render_duration_ms


def record_benchmark_result(
    paths: AppPaths,
    run: VoiceTestRun,
    candidate_id: str,
    *,
    preview_file: str | None = None,
    render_duration_ms: float | None = None,
) -> VoiceTestRun:
    for candidate in run.candidates:
        if candidate.candidate_id != candidate_id:
            continue
        if preview_file is not None:
            candidate.preview_file = preview_file
        if render_duration_ms is not None:
            candidate.render_duration_ms = render_duration_ms
            candidate.benchmark_runs += 1
            candidate.benchmark_total_ms += render_duration_ms
        candidate.last_rendered_at = utc_now()
        break
    winner = best_rated_candidate(run)
    run.winner_candidate_id = winner.candidate_id if winner is not None else run.winner_candidate_id
    run.workflow_step = "benchmark"
    return save_voice_test_run(paths, run)

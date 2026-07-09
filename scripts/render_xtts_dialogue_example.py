from __future__ import annotations

import json
import logging
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from book2mp3.config import AppPaths
from book2mp3.pipeline.audio import (
    concat_audio_files_to_mp3,
    ffmpeg_executable,
    probe_media_duration_seconds,
    trim_wav_silence_in_place,
)
from book2mp3.pipeline.chunking import split_text
from book2mp3.tts.pronunciation import apply_pronunciation_rules, suggest_pronunciation_candidates
from book2mp3.tts.xtts import XttsBackend
from book2mp3.voice_lab import load_voice_profile
from book2mp3.voice_settings import load_voice_setting
from book2mp3.xtts_options import normalize_pronunciation_rules, normalize_xtts_dialog_text, safe_xtts_chunk_chars


DIALOGUE_EXAMPLE_TEXT = """« »Wirst du uns überhaupt nicht vermissen?« Talwyn sackte ein wenig in sich zusammen. »Darum geht es nicht, und das weißt du auch.« »Ich weiß nur, dass wir gemeinsam am stärksten sind.« »Und ich weiß nur, dass wir in den letzten fünf Jahren nur stagniert haben. Wir haben unsere Fähigkeiten nicht weiterentwickelt.« »Unsere Fähigkeiten oder unsere Macht?« »Beides.« »Was ist los, Schwester? Willst du Drachenkönigin und Südlandkönigin werden?« »Nein. Ich will diese Blutlinie auch noch für die nächsten Jahrtausende blühen und gedeihen sehen. Und wenn du glaubst, wir drei schaffen das, während wir hier herumsitzen und Mum und Dad sich um uns kümmern, bist du ein Idiot.« »He! Ihr zwei!« Sie beugten sich vor und schauten nach unten. Izzy stand unter dem Baum. Hinter ihr warteten Éibhear und Rhi. »Na los!« »Wohin?«, fragte Talan. »Die Familie treffen. Es wird Zeit, das zu besprechen.« Talwyn grunzte. Was nie ein gutes Zeichen war. »Ich habe meiner Mutter nichts zu sagen.« »Das ist mir egal. Schwing deinen Hintern hier runter!«"""
SILENCE_THRESHOLDS = ("-30dB", "-35dB", "-40dB", "-45dB")
MAX_ACCEPTED_CHUNK_SECONDS = 12.0


@dataclass
class RenderVariant:
    key: str
    label: str
    file_name: str
    max_chars: int
    length_scale: float
    inference_options: dict[str, Any]
    pronunciation_overrides: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class VariantResult:
    variant_key: str
    label: str
    accepted: bool
    mp3_file: str
    max_chars: int
    length_scale: float
    inference_options: dict[str, Any]
    pronunciation_overrides: list[dict[str, Any]]
    spoken_chars: int
    chunk_lengths: list[int]
    chunk_durations_seconds: list[float]
    mp3_seconds: float
    silence_events: dict[str, list[str]]
    trimmed_wavs: list[dict[str, object]]
    device_mode: str
    render_seconds: float
    pronunciation_replacements: int
    applied_pronunciation_rules: list[dict[str, Any]]
    unmatched_name_candidates: list[dict[str, str]]
    rejection_reasons: list[str]


def _logger() -> logging.Logger:
    logger = logging.getLogger("book2mp3.render_xtts_dialogue_example")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s"))
        logger.addHandler(handler)
    return logger


def _clean_example_dir(example_dir: Path) -> None:
    if example_dir.exists():
        for child in example_dir.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
    example_dir.mkdir(parents=True, exist_ok=True)


def _silence_events(mp3_path: Path) -> dict[str, list[str]]:
    results: dict[str, list[str]] = {}
    for threshold in SILENCE_THRESHOLDS:
        probe = subprocess.run(
            [
                ffmpeg_executable(),
                "-hide_banner",
                "-nostats",
                "-i",
                str(mp3_path),
                "-af",
                f"silencedetect=n={threshold}:d=1.0",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        lines = [line.strip() for line in probe.stderr.splitlines() if "silence_" in line]
        results[threshold] = lines
    return results


def _write_spoken_chunks(spoken_dir: Path, chunks: list[str]) -> None:
    spoken_dir.mkdir(parents=True, exist_ok=True)
    for index, chunk in enumerate(chunks, start=1):
        (spoken_dir / f"{index:03d}.txt").write_text(chunk, encoding="utf-8")


def _variant_pronunciation_rules(
    base_rules: list[dict[str, Any]],
    overrides: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    normalized_overrides = normalize_pronunciation_rules(overrides)
    if not normalized_overrides:
        return normalize_pronunciation_rules(base_rules)
    override_matches = {str(rule["match"]).casefold() for rule in normalized_overrides}
    base_without_overridden_matches = [
        rule
        for rule in normalize_pronunciation_rules(base_rules)
        if str(rule["match"]).casefold() not in override_matches
    ]
    return normalize_pronunciation_rules([*normalized_overrides, *base_without_overridden_matches])


def _name_audit(
    source_text: str,
    rules: list[dict[str, Any]],
    applied_rules: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    normalized_rules = normalize_pronunciation_rules(rules)
    applied_matches = {
        str(rule.get("match", "") or "").strip().casefold()
        for rule in applied_rules
        if str(rule.get("match", "") or "").strip()
    }
    unmatched = suggest_pronunciation_candidates(source_text, existing_rules=normalized_rules, limit=40)
    return {
        "applied_rules": applied_rules,
        "unmatched_name_candidates": [
            suggestion
            for suggestion in unmatched
            if str(suggestion.get("match", "") or "").strip().casefold() not in applied_matches
        ],
    }


def _render_variant(
    paths: AppPaths,
    example_dir: Path,
    source_text: str,
    variant: RenderVariant,
    base_pronunciation_rules: list[dict[str, Any]],
    profile,
    logger: logging.Logger,
) -> VariantResult:
    rules = _variant_pronunciation_rules(base_pronunciation_rules, variant.pronunciation_overrides)
    transformed = apply_pronunciation_rules(source_text, rules)
    spoken_text = normalize_xtts_dialog_text(transformed.spoken_text)
    chunks = split_text(spoken_text, variant.max_chars)

    _write_spoken_chunks(example_dir / "spoken_chunks" / variant.key, chunks)
    wav_dir = example_dir / "wav" / variant.key
    wav_dir.mkdir(parents=True, exist_ok=True)
    wav_paths = [wav_dir / f"{index:03d}.wav" for index in range(1, len(chunks) + 1)]
    mp3_path = example_dir / variant.file_name
    inference_options = dict(variant.inference_options)
    inference_options["enable_text_splitting"] = False

    started = time.perf_counter()

    def render(device_mode: str) -> str:
        backend = XttsBackend(paths.runtime, logger=logger, device_mode=device_mode)
        backend.synthesize_many_to_wavs(
            chunks,
            profile,
            wav_paths,
            length_scale=variant.length_scale,
            enable_text_splitting=False,
            inference_options=inference_options,
        )
        return device_mode

    try:
        device_mode = render("cuda")
    except Exception:
        logger.exception("CUDA dialogue example render failed; retrying on CPU")
        XttsBackend.shutdown_all_servers()
        for wav_path in wav_paths:
            if wav_path.exists():
                wav_path.unlink()
        device_mode = render("cpu")

    trimmed_wavs: list[dict[str, object]] = []
    for wav_path in wav_paths:
        before = probe_media_duration_seconds(wav_path)
        changed = trim_wav_silence_in_place(wav_path, logger=logger)
        after = probe_media_duration_seconds(wav_path)
        trimmed_wavs.append(
            {
                "file": wav_path.name,
                "changed": changed,
                "before": round(before, 3),
                "after": round(after, 3),
            }
        )

    concat_audio_files_to_mp3(wav_paths, mp3_path, logger=logger)
    chunk_durations = [round(probe_media_duration_seconds(path), 3) for path in wav_paths]
    mp3_seconds = round(probe_media_duration_seconds(mp3_path), 3)
    silence_events = _silence_events(mp3_path)

    rejection_reasons: list[str] = []
    if len(chunks) < 3:
        rejection_reasons.append(f"expected at least 3 chunks, got {len(chunks)}")
    oversized = [len(chunk) for chunk in chunks if len(chunk) > variant.max_chars]
    if oversized:
        rejection_reasons.append(f"chunk over max_chars={variant.max_chars}: {oversized}")
    long_chunks = [duration for duration in chunk_durations if duration > MAX_ACCEPTED_CHUNK_SECONDS]
    if long_chunks:
        rejection_reasons.append(f"chunk duration over {MAX_ACCEPTED_CHUNK_SECONDS}s: {long_chunks}")
    active_silences = {threshold: lines for threshold, lines in silence_events.items() if lines}
    if active_silences:
        rejection_reasons.append(f"silence over 1s detected: {active_silences}")

    audit = _name_audit(source_text, rules, transformed.applied_rules)
    return VariantResult(
        variant_key=variant.key,
        label=variant.label,
        accepted=not rejection_reasons,
        mp3_file=str(mp3_path),
        max_chars=variant.max_chars,
        length_scale=variant.length_scale,
        inference_options=inference_options,
        pronunciation_overrides=normalize_pronunciation_rules(variant.pronunciation_overrides),
        spoken_chars=len(spoken_text),
        chunk_lengths=[len(chunk) for chunk in chunks],
        chunk_durations_seconds=chunk_durations,
        mp3_seconds=mp3_seconds,
        silence_events=silence_events,
        trimmed_wavs=trimmed_wavs,
        device_mode=device_mode,
        render_seconds=round(time.perf_counter() - started, 3),
        pronunciation_replacements=transformed.applied_occurrences,
        applied_pronunciation_rules=audit["applied_rules"],
        unmatched_name_candidates=audit["unmatched_name_candidates"],
        rejection_reasons=rejection_reasons,
    )


def main() -> int:
    root = Path.cwd()
    paths = AppPaths.from_project_root(root)
    example_dir = paths.workspace / "manual_checks" / "xtts_example"
    _clean_example_dir(example_dir)

    source_path = example_dir / "fantasy_dialogue_example.txt"
    source_path.write_text(DIALOGUE_EXAMPLE_TEXT + "\n", encoding="utf-8")

    logger = _logger()
    setting = load_voice_setting(paths.voice_settings, "xtts1")
    profile = load_voice_profile(paths.voice_profiles, setting.voice_profile_id)
    effective_max_chars = safe_xtts_chunk_chars(setting.max_chars, profile.target_language)
    base_inference_options = dict(setting.xtts_inference)
    livelier_inference_options = {
        **base_inference_options,
        "temperature": 0.72,
        "top_p": 0.90,
        "top_k": 50,
        "repetition_penalty": 5.0,
        "num_beams": 1,
        "do_sample": True,
    }
    expressive_context_inference_options = {
        **base_inference_options,
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
    expressive_punchy_inference_options = {
        **base_inference_options,
        "temperature": 0.92,
        "top_p": 0.98,
        "top_k": 100,
        "repetition_penalty": 3.5,
        "num_beams": 1,
        "do_sample": True,
        "gpt_cond_len": 30,
        "gpt_cond_chunk_len": 6,
        "max_ref_length": 45,
        "sound_norm_refs": True,
        "librosa_trim_db": None,
    }
    fantasy_name_overrides = [
        {"match": "Talwyn", "spoken_as": "Tallwin", "scope": "whole_phrase", "enabled": True},
        {"match": "Éibhear", "spoken_as": "Eiwer", "scope": "whole_phrase", "enabled": True},
        {"match": "Eibhear", "spoken_as": "Eiwer", "scope": "whole_phrase", "enabled": True},
        {"match": "Rhi", "spoken_as": "Rie", "scope": "whole_phrase", "enabled": True},
        {"match": "Izzy", "spoken_as": "Issi", "scope": "whole_phrase", "enabled": True},
    ]
    variants = [
        RenderVariant(
            key="dialogue_01_current",
            label="Current Standard XTTS",
            file_name="dialogue_01_current.mp3",
            max_chars=effective_max_chars,
            length_scale=setting.length_scale,
            inference_options=base_inference_options,
        ),
        RenderVariant(
            key="dialogue_02_livelier",
            label="Livelier XTTS server parameters",
            file_name="dialogue_02_livelier.mp3",
            max_chars=100,
            length_scale=0.99,
            inference_options=livelier_inference_options,
        ),
        RenderVariant(
            key="dialogue_03_livelier_names",
            label="Livelier XTTS parameters with alternate fantasy-name pronunciations",
            file_name="dialogue_03_livelier_names.mp3",
            max_chars=100,
            length_scale=0.99,
            inference_options=livelier_inference_options,
            pronunciation_overrides=fantasy_name_overrides,
        ),
        RenderVariant(
            key="dialogue_04_expressive_context",
            label="Expressive decoding with longer dialogue context",
            file_name="dialogue_04_expressive_context.mp3",
            max_chars=safe_xtts_chunk_chars(160, profile.target_language),
            length_scale=0.96,
            inference_options=expressive_context_inference_options,
            pronunciation_overrides=fantasy_name_overrides,
        ),
        RenderVariant(
            key="dialogue_05_expressive_punchy",
            label="Stronger expressive sampling with punchier pace",
            file_name="dialogue_05_expressive_punchy.mp3",
            max_chars=safe_xtts_chunk_chars(140, profile.target_language),
            length_scale=0.93,
            inference_options=expressive_punchy_inference_options,
            pronunciation_overrides=fantasy_name_overrides,
        ),
    ]

    variant_results: list[VariantResult] = []
    try:
        for variant in variants:
            logger.info("Rendering dialogue example variant %s with max_chars=%s", variant.key, variant.max_chars)
            variant_results.append(
                _render_variant(
                    paths,
                    example_dir,
                    DIALOGUE_EXAMPLE_TEXT,
                    variant,
                    setting.pronunciation_rules,
                    profile,
                    logger,
                )
            )
    finally:
        XttsBackend.shutdown_all_servers()
    accepted_variants = [result for result in variant_results if result.accepted]
    expressive_feedback_variants = [
        result.variant_key
        for result in accepted_variants
        if "expressive" in result.variant_key
    ]
    fallback_feedback_variants = [
        result.variant_key
        for result in accepted_variants
        if result.variant_key != "dialogue_01_current" and result.variant_key not in expressive_feedback_variants
    ]
    summary = {
        "accepted": bool(accepted_variants),
        "setting_id": setting.setting_id,
        "setting_name": setting.display_name,
        "profile_id": profile.profile_id,
        "profile_name": profile.display_name,
        "source_chars": len(DIALOGUE_EXAMPLE_TEXT),
        "base_max_chars": effective_max_chars,
        "source_file": str(source_path),
        "variants": [asdict(result) for result in variant_results],
        "accepted_variants": [result.variant_key for result in accepted_variants],
        "recommended_feedback_order": [*expressive_feedback_variants, *fallback_feedback_variants],
        "note": "A/B dialogue examples with shared XTTS normalization, Ramona pronunciation rules, edge-only WAV trimming, and render-only parameter/name variants.",
    }
    (example_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    if not accepted_variants:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

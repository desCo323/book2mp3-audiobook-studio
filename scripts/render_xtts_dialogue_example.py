from __future__ import annotations

import json
import logging
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from book2mp3.config import AppPaths
from book2mp3.pipeline.audio import (
    concat_audio_files_to_mp3,
    ffmpeg_executable,
    probe_media_duration_seconds,
    trim_wav_silence_in_place,
)
from book2mp3.pipeline.chunking import split_text
from book2mp3.tts.pronunciation import apply_pronunciation_rules
from book2mp3.tts.xtts import XttsBackend
from book2mp3.voice_lab import load_voice_profile
from book2mp3.voice_settings import load_voice_setting
from book2mp3.xtts_options import normalize_xtts_dialog_text, safe_xtts_chunk_chars


DIALOGUE_EXAMPLE_TEXT = """« »Wirst du uns überhaupt nicht vermissen?« Talwyn sackte ein wenig in sich zusammen. »Darum geht es nicht, und das weißt du auch.« »Ich weiß nur, dass wir gemeinsam am stärksten sind.« »Und ich weiß nur, dass wir in den letzten fünf Jahren nur stagniert haben. Wir haben unsere Fähigkeiten nicht weiterentwickelt.« »Unsere Fähigkeiten oder unsere Macht?« »Beides.« »Was ist los, Schwester? Willst du Drachenkönigin und Südlandkönigin werden?« »Nein. Ich will diese Blutlinie auch noch für die nächsten Jahrtausende blühen und gedeihen sehen. Und wenn du glaubst, wir drei schaffen das, während wir hier herumsitzen und Mum und Dad sich um uns kümmern, bist du ein Idiot.« »He! Ihr zwei!« Sie beugten sich vor und schauten nach unten. Izzy stand unter dem Baum. Hinter ihr warteten Éibhear und Rhi. »Na los!« »Wohin?«, fragte Talan. »Die Familie treffen. Es wird Zeit, das zu besprechen.« Talwyn grunzte. Was nie ein gutes Zeichen war. »Ich habe meiner Mutter nichts zu sagen.« »Das ist mir egal. Schwing deinen Hintern hier runter!«"""
SILENCE_THRESHOLDS = ("-30dB", "-35dB", "-40dB", "-45dB")
MAX_ACCEPTED_CHUNK_SECONDS = 12.0


@dataclass
class AttemptResult:
    accepted: bool
    max_chars: int
    chunk_lengths: list[int]
    chunk_durations_seconds: list[float]
    mp3_seconds: float
    silence_events: dict[str, list[str]]
    trimmed_wavs: list[dict[str, object]]
    device_mode: str
    render_seconds: float
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


def _render_attempt(
    paths: AppPaths,
    example_dir: Path,
    spoken_text: str,
    max_chars: int,
    setting,
    profile,
    logger: logging.Logger,
) -> AttemptResult:
    for child_name in ("wav", "spoken_chunks"):
        child = example_dir / child_name
        if child.exists():
            shutil.rmtree(child)
    for child_name in ("fantasy_dialogue_example.mp3", "summary.json"):
        child = example_dir / child_name
        if child.exists():
            child.unlink()

    chunks = split_text(spoken_text, max_chars)
    _write_spoken_chunks(example_dir / "spoken_chunks", chunks)
    wav_dir = example_dir / "wav"
    wav_dir.mkdir(parents=True, exist_ok=True)
    wav_paths = [wav_dir / f"{index:03d}.wav" for index in range(1, len(chunks) + 1)]
    mp3_path = example_dir / "fantasy_dialogue_example.mp3"
    inference_options = dict(setting.xtts_inference)
    inference_options["enable_text_splitting"] = False

    started = time.perf_counter()

    def render(device_mode: str) -> str:
        backend = XttsBackend(paths.runtime, logger=logger, device_mode=device_mode)
        backend.synthesize_many_to_wavs(
            chunks,
            profile,
            wav_paths,
            length_scale=setting.length_scale,
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
    oversized = [len(chunk) for chunk in chunks if len(chunk) > max_chars]
    if oversized:
        rejection_reasons.append(f"chunk over max_chars={max_chars}: {oversized}")
    long_chunks = [duration for duration in chunk_durations if duration > MAX_ACCEPTED_CHUNK_SECONDS]
    if long_chunks:
        rejection_reasons.append(f"chunk duration over {MAX_ACCEPTED_CHUNK_SECONDS}s: {long_chunks}")
    active_silences = {threshold: lines for threshold, lines in silence_events.items() if lines}
    if active_silences:
        rejection_reasons.append(f"silence over 1s detected: {active_silences}")

    return AttemptResult(
        accepted=not rejection_reasons,
        max_chars=max_chars,
        chunk_lengths=[len(chunk) for chunk in chunks],
        chunk_durations_seconds=chunk_durations,
        mp3_seconds=mp3_seconds,
        silence_events=silence_events,
        trimmed_wavs=trimmed_wavs,
        device_mode=device_mode,
        render_seconds=round(time.perf_counter() - started, 3),
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
    transformed = apply_pronunciation_rules(DIALOGUE_EXAMPLE_TEXT, setting.pronunciation_rules)
    spoken_text = normalize_xtts_dialog_text(transformed.spoken_text)
    effective_max_chars = safe_xtts_chunk_chars(setting.max_chars, profile.target_language)
    attempts: list[AttemptResult] = []
    for max_chars in dict.fromkeys((effective_max_chars, 100)):
        if attempts and attempts[-1].accepted:
            break
        logger.info("Rendering dialogue example with max_chars=%s", max_chars)
        attempts.append(_render_attempt(paths, example_dir, spoken_text, max_chars, setting, profile, logger))
        XttsBackend.shutdown_all_servers()

    accepted = next((attempt for attempt in attempts if attempt.accepted), attempts[-1])
    summary = {
        "accepted": accepted.accepted,
        "setting_id": setting.setting_id,
        "setting_name": setting.display_name,
        "profile_id": profile.profile_id,
        "profile_name": profile.display_name,
        "source_chars": len(DIALOGUE_EXAMPLE_TEXT),
        "spoken_chars": len(spoken_text),
        "pronunciation_replacements": transformed.applied_occurrences,
        "mp3_file": str(example_dir / "fantasy_dialogue_example.mp3"),
        "source_file": str(source_path),
        "attempts": [asdict(attempt) for attempt in attempts],
        "selected_attempt": asdict(accepted),
        "note": "Dialogue example with shared XTTS normalization, Ramona pronunciation rules, and edge-only WAV trimming.",
    }
    (example_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    if not accepted.accepted:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

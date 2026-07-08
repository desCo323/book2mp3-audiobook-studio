from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from urllib.request import urlopen
import json

from book2mp3.config import AppPaths
from book2mp3.voice_lab import sanitize_profile_id
from book2mp3.voice_lab import SUPPORTED_SAMPLE_EXTENSIONS, create_voice_profile, list_voice_profiles
from book2mp3.voice_settings import seed_default_voice_settings


LANGUAGE_HINTS = {"de", "en", "fr", "es", "it", "nl", "pl", "pt", "tr", "ru", "cs", "ar", "zh", "ja", "hu", "ko"}
STARTER_XTTS_SPEAKERS = (
    {
        "display_name": "XTTS Calm Female",
        "language": "en",
        "samples": [
            {
                "kind": "url",
                "filename": "calm_female.wav",
                "url": "https://raw.githubusercontent.com/daswer123/xtts-webui/main/speakers/calm_female.wav",
            }
        ],
    },
    {
        "display_name": "XTTS Deutsch Weiblich Warm",
        "language": "de",
        "samples": [
            {
                "kind": "url",
                "filename": "de_warm_female.wav",
                "url": "https://raw.githubusercontent.com/daswer123/xtts-webui/main/speakers/calm_female.wav",
            }
        ],
    },
    {
        "display_name": "XTTS Female",
        "language": "en",
        "samples": [
            {
                "kind": "url",
                "filename": "female.wav",
                "url": "https://raw.githubusercontent.com/daswer123/xtts-webui/main/speakers/female.wav",
            }
        ],
    },
    {
        "display_name": "XTTS Deutsch Weiblich Klar",
        "language": "de",
        "samples": [
            {
                "kind": "url",
                "filename": "de_clear_female.wav",
                "url": "https://raw.githubusercontent.com/daswer123/xtts-webui/main/speakers/female.wav",
            }
        ],
    },
    {
        "display_name": "XTTS Male",
        "language": "en",
        "samples": [
            {
                "kind": "url",
                "filename": "male.wav",
                "url": "https://raw.githubusercontent.com/daswer123/xtts-webui/main/speakers/male.wav",
            }
        ],
    },
    {
        "display_name": "XTTS Espanol Femenino",
        "language": "es",
        "samples": [
            {
                "kind": "url",
                "filename": "es_female.wav",
                "url": "https://raw.githubusercontent.com/daswer123/xtts-webui/main/speakers/female.wav",
            }
        ],
    },
    {
        "display_name": "XTTS Portugues Feminino",
        "language": "pt",
        "samples": [
            {
                "kind": "url",
                "filename": "pt_female.wav",
                "url": "https://raw.githubusercontent.com/daswer123/xtts-webui/main/speakers/calm_female.wav",
            }
        ],
    },
    {
        "display_name": "XTTS Espanol Masculino",
        "language": "es",
        "samples": [
            {
                "kind": "url",
                "filename": "es_male.wav",
                "url": "https://raw.githubusercontent.com/daswer123/xtts-webui/main/speakers/male.wav",
            }
        ],
    },
    {
        "display_name": "XTTS Portugues Masculino",
        "language": "pt",
        "samples": [
            {
                "kind": "url",
                "filename": "pt_male.wav",
                "url": "https://raw.githubusercontent.com/daswer123/xtts-webui/main/speakers/male.wav",
            }
        ],
    },
    {
        "display_name": "XTTS Thorsten Neutral",
        "language": "de",
        "samples": [
            {
                "kind": "hf_first_rows",
                "filename": "thorsten_neutral_1.wav",
                "dataset": "Thorsten-Voice/TV-44kHz-Full",
                "config": "TV-2022.10-Neutral",
                "split": "train",
                "row_index": 0,
            },
            {
                "kind": "hf_first_rows",
                "filename": "thorsten_neutral_2.wav",
                "dataset": "Thorsten-Voice/TV-44kHz-Full",
                "config": "TV-2022.10-Neutral",
                "split": "train",
                "row_index": 1,
            },
        ],
    },
    {
        "display_name": "XTTS Thorsten Emotional",
        "language": "de",
        "samples": [
            {
                "kind": "hf_first_rows",
                "filename": "thorsten_emotional_angry.wav",
                "dataset": "Thorsten-Voice/TV-44kHz-Full",
                "config": "TV-2021.06-Emotional",
                "split": "train",
                "row_index": 0,
            },
            {
                "kind": "hf_first_rows",
                "filename": "thorsten_emotional_amused.wav",
                "dataset": "Thorsten-Voice/TV-44kHz-Full",
                "config": "TV-2021.06-Emotional",
                "split": "train",
                "row_index": 1,
            },
        ],
    },
)


def _audio_files(root: Path) -> list[Path]:
    return sorted(
        path for path in root.iterdir() if path.is_file() and path.suffix.lower() in SUPPORTED_SAMPLE_EXTENSIONS
    )


def _speaker_groups(source_root: Path) -> list[tuple[str, list[Path], str]]:
    groups: list[tuple[str, list[Path], str]] = []
    for child in sorted(source_root.iterdir()):
        if child.is_dir():
            nested_dirs = [item for item in sorted(child.iterdir()) if item.is_dir()]
            files = _audio_files(child)
            if files:
                language = child.name if child.name in LANGUAGE_HINTS else "auto"
                groups.append((child.name, files, language))
                continue
            if child.name in LANGUAGE_HINTS:
                for nested in nested_dirs:
                    nested_files = _audio_files(nested)
                    if nested_files:
                        groups.append((nested.name, nested_files, child.name))
                continue
            for nested in nested_dirs:
                nested_files = _audio_files(nested)
                if nested_files:
                    groups.append((nested.name, nested_files, "auto"))
        elif child.is_file() and child.suffix.lower() in SUPPORTED_SAMPLE_EXTENSIONS:
            groups.append((child.stem, [child], "auto"))
    return groups


def import_xtts_webui_speakers(
    paths: AppPaths,
    source_root: Path,
    fallback_language: str,
) -> list[Path]:
    manifests: list[Path] = []
    existing_ids = {profile.profile_id for profile in list_voice_profiles(paths.voice_profiles)}
    for display_name, sample_paths, detected_language in _speaker_groups(source_root):
        profile_id = sanitize_profile_id(display_name)
        if profile_id in existing_ids:
            continue
        language = detected_language if detected_language != "auto" else fallback_language
        manifest = create_voice_profile(
            paths.voice_profiles,
            display_name=display_name,
            target_language=language,
            backend="xtts_v2",
            notes=f"Imported from XTTS WebUI speaker folder: {source_root}",
            sample_paths=sample_paths,
        )
        manifests.append(manifest)
        existing_ids.add(manifest.parent.name)
    return manifests


def find_candidate_speaker_roots(paths: AppPaths) -> list[Path]:
    home = Path.home()
    scan_roots = [
        paths.root,
        paths.root.parent,
        home,
        home / "Documents",
        home / "Downloads",
        home / "Desktop",
        Path("/mnt"),
        Path("/media"),
    ]
    candidates = [
        paths.root / "speakers",
        paths.root.parent / "speakers",
        paths.root / "xtts-webui" / "speakers",
        paths.root.parent / "xtts-webui" / "speakers",
        paths.root / "webui" / "speakers",
        paths.root.parent / "webui" / "speakers",
        paths.runtime / "xtts" / "speakers",
        paths.runtime / "xtts" / "linux" / "speakers",
        paths.runtime / "xtts" / "windows" / "speakers",
    ]
    install_name_hints = (
        "xtts-webui",
        "xtts_webui",
        "xtts webui",
        "xtts",
        "coqui",
        "tts",
        "webui",
    )
    for root in scan_roots:
        if not root.exists():
            continue
        try:
            for child in root.iterdir():
                if not child.is_dir():
                    continue
                lowered = child.name.lower()
                if any(hint in lowered for hint in install_name_hints):
                    candidates.append(child / "speakers")
                    candidates.append(child / "webui" / "speakers")
                    candidates.append(child / "xtts-webui" / "speakers")
                    candidates.append(child / "xtts_webui" / "speakers")
                    candidates.append(child / "data" / "speakers")
        except PermissionError:
            continue
    result: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        if candidate.exists() and any(candidate.iterdir()):
            result.append(candidate)
    return result


def auto_import_xtts_speakers(paths: AppPaths, fallback_language: str) -> tuple[Path | None, list[Path]]:
    for candidate in find_candidate_speaker_roots(paths):
        manifests = import_xtts_webui_speakers(paths, candidate, fallback_language)
        if manifests:
            return candidate, manifests
    return None, []


def _download_from_hf_first_rows(
    tmp_root: Path,
    dataset: str,
    config: str,
    split: str,
    row_index: int,
    filename: str,
) -> Path:
    api_url = (
        "https://datasets-server.huggingface.co/first-rows"
        f"?dataset={dataset}&config={config}&split={split}"
    ).replace(" ", "%20")
    payload = json.load(urlopen(api_url, timeout=30))
    rows = payload.get("rows", [])
    row = next((item for item in rows if int(item.get("row_idx", -1)) == row_index), None)
    if not row:
        raise RuntimeError(f"No Hugging Face row {row_index} found for {dataset}/{config}/{split}")
    audio = row.get("row", {}).get("audio", [])
    if not audio:
        raise RuntimeError(f"No audio payload found for {dataset}/{config}/{split} row {row_index}")
    audio_url = audio[0]["src"]
    target = tmp_root / filename
    with urlopen(audio_url, timeout=30) as response, target.open("wb") as handle:
        shutil.copyfileobj(response, handle)
    return target


def _resolve_starter_samples(tmp_root: Path, starter: dict[str, object]) -> list[Path]:
    resolved: list[Path] = []
    for sample in starter["samples"]:
        if sample["kind"] == "url":
            downloaded = tmp_root / sample["filename"]
            with urlopen(sample["url"], timeout=20) as response, downloaded.open("wb") as target:
                shutil.copyfileobj(response, target)
            resolved.append(downloaded)
        elif sample["kind"] == "hf_first_rows":
            resolved.append(
                _download_from_hf_first_rows(
                    tmp_root,
                    sample["dataset"],
                    sample["config"],
                    sample["split"],
                    sample["row_index"],
                    sample["filename"],
                )
            )
        else:
            raise RuntimeError(f"Unsupported XTTS starter sample kind: {sample['kind']}")
    return resolved


def install_starter_xtts_profiles(paths: AppPaths) -> list[Path]:
    manifests: list[Path] = []
    existing_ids = {profile.profile_id for profile in list_voice_profiles(paths.voice_profiles)}
    with tempfile.TemporaryDirectory(prefix="book2mp3-xtts-starters-") as tmp_dir:
        tmp_root = Path(tmp_dir)
        for starter in STARTER_XTTS_SPEAKERS:
            profile_id = sanitize_profile_id(starter["display_name"])
            if profile_id in existing_ids:
                continue
            sample_paths = _resolve_starter_samples(tmp_root, starter)
            manifest = create_voice_profile(
                paths.voice_profiles,
                display_name=starter["display_name"],
                target_language=starter["language"],
                backend="xtts_v2",
                notes=(
                    "Starter XTTS profile imported from curated public demo sources. "
                    "Current sources include xtts-webui sample speakers and Thorsten-Voice CC0 German dataset rows."
                ),
                sample_paths=sample_paths,
            )
            manifests.append(manifest)
            existing_ids.add(manifest.parent.name)
    seed_default_voice_settings(paths.voice_settings, paths.voice_profiles)
    return manifests


def describe_candidate_speaker_roots(paths: AppPaths) -> list[dict[str, object]]:
    summaries: list[dict[str, object]] = []
    for candidate in find_candidate_speaker_roots(paths):
        groups = _speaker_groups(candidate)
        summaries.append(
            {
                "path": str(candidate),
                "speaker_groups": len(groups),
                "examples": [group_name for group_name, _files, _language in groups[:5]],
            }
        )
    return summaries

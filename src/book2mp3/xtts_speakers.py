from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from urllib.request import urlopen

from book2mp3.config import AppPaths
from book2mp3.voice_lab import sanitize_profile_id
from book2mp3.voice_lab import SUPPORTED_SAMPLE_EXTENSIONS, create_voice_profile, list_voice_profiles


LANGUAGE_HINTS = {"de", "en", "fr", "es", "it", "nl", "pl", "pt", "tr", "ru", "cs", "ar", "zh", "ja", "hu", "ko"}
STARTER_XTTS_SPEAKERS = (
    {
        "display_name": "XTTS Calm Female",
        "language": "en",
        "filename": "calm_female.wav",
        "url": "https://raw.githubusercontent.com/daswer123/xtts-webui/main/speakers/calm_female.wav",
    },
    {
        "display_name": "XTTS Female",
        "language": "en",
        "filename": "female.wav",
        "url": "https://raw.githubusercontent.com/daswer123/xtts-webui/main/speakers/female.wav",
    },
    {
        "display_name": "XTTS Male",
        "language": "en",
        "filename": "male.wav",
        "url": "https://raw.githubusercontent.com/daswer123/xtts-webui/main/speakers/male.wav",
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


def install_starter_xtts_profiles(paths: AppPaths) -> list[Path]:
    manifests: list[Path] = []
    existing_ids = {profile.profile_id for profile in list_voice_profiles(paths.voice_profiles)}
    with tempfile.TemporaryDirectory(prefix="book2mp3-xtts-starters-") as tmp_dir:
        tmp_root = Path(tmp_dir)
        for starter in STARTER_XTTS_SPEAKERS:
            profile_id = sanitize_profile_id(starter["display_name"])
            if profile_id in existing_ids:
                continue
            downloaded = tmp_root / starter["filename"]
            with urlopen(starter["url"], timeout=20) as response, downloaded.open("wb") as target:
                shutil.copyfileobj(response, target)
            manifest = create_voice_profile(
                paths.voice_profiles,
                display_name=starter["display_name"],
                target_language=starter["language"],
                backend="xtts_v2",
                notes=(
                    "Starter XTTS sample imported from the xtts-webui repository speakers folder: "
                    f"{starter['url']}"
                ),
                sample_paths=[downloaded],
            )
            manifests.append(manifest)
            existing_ids.add(manifest.parent.name)
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

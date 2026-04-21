from __future__ import annotations

from pathlib import Path

from book2mp3.config import AppPaths
from book2mp3.voice_lab import sanitize_profile_id
from book2mp3.voice_lab import SUPPORTED_SAMPLE_EXTENSIONS, create_voice_profile, list_voice_profiles


LANGUAGE_HINTS = {"de", "en", "fr", "es", "it", "nl", "pl", "pt", "tr", "ru", "cs", "ar", "zh", "ja", "hu", "ko"}


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
    result: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
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

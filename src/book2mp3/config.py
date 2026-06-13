from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path


def _has_contents(path: Path) -> bool:
    return path.exists() and any(path.iterdir())


def _prefer_local_or_parent(root: Path, relative: str) -> Path:
    primary = root / relative
    parent_candidate = root.parent / relative
    if _has_contents(primary):
        return primary
    if _has_contents(parent_candidate):
        return parent_candidate
    return primary


def _timestamp_token() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")


def _path_is_writable(path: Path) -> bool:
    if path.is_dir():
        return os.access(path, os.W_OK | os.X_OK)
    return os.access(path, os.W_OK)


def _quarantine_path(path: Path, reason: str) -> Path:
    suffix_base = f"{path.name}.{reason}-{_timestamp_token()}"
    candidate = path.with_name(suffix_base)
    counter = 1
    while candidate.exists():
        candidate = path.with_name(f"{suffix_base}-{counter}")
        counter += 1
    path.rename(candidate)
    return candidate


@dataclass(frozen=True)
class AppPaths:
    root: Path
    workspace: Path
    jobs: Path
    runtime: Path
    voices: Path
    logs: Path
    statistics: Path
    runtime_stats_file: Path
    app_settings_file: Path
    voice_profiles: Path
    voice_settings: Path
    preview_sessions: Path

    @classmethod
    def from_project_root(cls, root: Path) -> "AppPaths":
        workspace = root / "workspace"
        return cls(
            root=root,
            workspace=workspace,
            jobs=workspace / "jobs",
            runtime=_prefer_local_or_parent(root, "runtime"),
            voices=_prefer_local_or_parent(root, "voices"),
            logs=workspace / "logs",
            statistics=workspace / "statistics",
            runtime_stats_file=workspace / "statistics" / "runtime_stats.json",
            app_settings_file=workspace / "app_settings.json",
            voice_profiles=workspace / "voice_profiles",
            voice_settings=workspace / "voice_settings",
            preview_sessions=workspace / "preview_sessions",
        )

    def ensure(self) -> list[Path]:
        repaired: list[Path] = []
        self.workspace.mkdir(parents=True, exist_ok=True)
        for path in (self.runtime, self.voices):
            path.mkdir(parents=True, exist_ok=True)

        for path in (self.jobs, self.logs, self.statistics, self.voice_profiles, self.voice_settings, self.preview_sessions):
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                if not path.is_dir():
                    repaired.append(_quarantine_path(path, "invalid"))
                elif not _path_is_writable(path):
                    repaired.append(_quarantine_path(path, "readonly"))
            path.mkdir(parents=True, exist_ok=True)

        if self.app_settings_file.exists():
            if self.app_settings_file.is_dir():
                repaired.append(_quarantine_path(self.app_settings_file, "invalid"))
            elif not _path_is_writable(self.app_settings_file):
                repaired.append(_quarantine_path(self.app_settings_file, "readonly"))
        if self.runtime_stats_file.exists():
            if self.runtime_stats_file.is_dir():
                repaired.append(_quarantine_path(self.runtime_stats_file, "invalid"))
            elif not _path_is_writable(self.runtime_stats_file):
                repaired.append(_quarantine_path(self.runtime_stats_file, "readonly"))
        return repaired

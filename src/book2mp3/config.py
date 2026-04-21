from __future__ import annotations

from dataclasses import dataclass
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


@dataclass(frozen=True)
class AppPaths:
    root: Path
    workspace: Path
    jobs: Path
    runtime: Path
    voices: Path
    logs: Path
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
            app_settings_file=workspace / "app_settings.json",
            voice_profiles=workspace / "voice_profiles",
            voice_settings=workspace / "voice_settings",
            preview_sessions=workspace / "preview_sessions",
        )

    def ensure(self) -> None:
        for path in (
            self.workspace,
            self.jobs,
            self.runtime,
            self.voices,
            self.logs,
            self.voice_profiles,
            self.voice_settings,
            self.preview_sessions,
        ):
            path.mkdir(parents=True, exist_ok=True)

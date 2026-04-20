from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppPaths:
    root: Path
    workspace: Path
    jobs: Path
    runtime: Path
    voices: Path
    logs: Path
    voice_profiles: Path

    @classmethod
    def from_project_root(cls, root: Path) -> "AppPaths":
        workspace = root / "workspace"
        return cls(
            root=root,
            workspace=workspace,
            jobs=workspace / "jobs",
            runtime=root / "runtime",
            voices=root / "voices",
            logs=workspace / "logs",
            voice_profiles=workspace / "voice_profiles",
        )

    def ensure(self) -> None:
        for path in (
            self.workspace,
            self.jobs,
            self.runtime,
            self.voices,
            self.logs,
            self.voice_profiles,
        ):
            path.mkdir(parents=True, exist_ok=True)

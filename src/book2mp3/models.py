from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from book2mp3.presets import get_preset


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ChunkRecord:
    index: int
    text_file: str
    wav_file: str
    mp3_file: str
    status: str = "pending"
    error: str = ""
    updated_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class JobState:
    job_id: str
    title: str
    source_name: str
    source_type: str
    created_at: str
    updated_at: str
    status: str
    backend: str
    voice_id: str
    voice_profile_id: str
    preset_id: str
    priority: int
    output_mode: str
    keep_wav: bool
    max_chars: int
    sentence_silence: float
    length_scale: float
    source_file: str
    extracted_file: str
    final_output_file: str
    chunks: list[ChunkRecord]
    logs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["chunks"] = [chunk.to_dict() for chunk in self.chunks]
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "JobState":
        payload = dict(payload)
        preset = get_preset(payload.get("preset_id", "balanced"))
        payload.setdefault("preset_id", preset.preset_id)
        payload.setdefault("sentence_silence", preset.sentence_silence)
        payload.setdefault("length_scale", preset.length_scale)
        payload.setdefault("voice_profile_id", "")
        payload["chunks"] = [ChunkRecord(**chunk) for chunk in payload.get("chunks", [])]
        return cls(**payload)

    @property
    def completed_chunks(self) -> int:
        return sum(1 for chunk in self.chunks if chunk.status == "done")

    @property
    def total_chunks(self) -> int:
        return len(self.chunks)

    def append_log(self, message: str) -> None:
        self.logs.append(f"{utc_now()} {message}")
        self.updated_at = utc_now()

    def job_dir(self, jobs_root: Path) -> Path:
        return jobs_root / self.job_id

    @property
    def is_queue_candidate(self) -> bool:
        return self.status in {"queued", "prepared", "running"}

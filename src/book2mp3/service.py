from __future__ import annotations

from dataclasses import asdict
import os
from pathlib import Path
import subprocess
from typing import Any

from book2mp3.app_settings import AppSettings, load_app_settings, reset_workspace_state, save_app_settings
from book2mp3.book_metadata import (
    choose_best_metadata_result,
    guess_metadata_from_filename,
    search_open_library_metadata,
)
from book2mp3.config import AppPaths
from book2mp3.models import AudiobookMetadata, JobState, default_audiobook_metadata
from book2mp3.pipeline.extract import DocumentStructure, analyze_document_structure
from book2mp3.pipeline.jobs import JobManager
from book2mp3.presets import QUALITY_PRESETS, get_preset
from book2mp3.runtime_stats import runtime_statistics_summary
from book2mp3.tts.piper import PiperBackend
from book2mp3.tts.xtts import XttsBackend
from book2mp3.utils.perf_logging import current_run_id, is_perf_logging_enabled, perf_log_target_hint
from book2mp3.voice_catalog import format_voice_label, voice_language_code
from book2mp3.voice_lab import list_voice_profiles, load_voice_profile
from book2mp3.voice_settings import (
    PROFILE_STATUS_ARCHIVED,
    PROFILE_STATUS_APPROVED,
    PROFILE_STATUS_DRAFT,
    VALID_PROFILE_STATUSES,
    list_voice_settings,
    load_voice_setting,
    profile_status_label,
    update_voice_setting_status,
)
from book2mp3.xtts_setup import xtts_launcher_hint, xtts_setup_supported


VALID_OUTPUT_MODES = {"single_file", "timed_parts", "segments", "chapter_files"}


class Book2Mp3Service:
    def __init__(self, paths: AppPaths) -> None:
        self.paths = paths
        self.paths.ensure()
        self.manager = JobManager(paths)

    def recover_interrupted_jobs(self) -> None:
        self.manager.recover_interrupted_jobs()

    def reset_workspace(self) -> dict[str, Any]:
        default_settings = AppSettings()
        reset_workspace_state(self.paths.workspace)
        save_app_settings(self.paths.app_settings_file, default_settings)
        self.manager = JobManager(self.paths)
        return {
            "workspace": str(self.paths.workspace),
            "reset": True,
            "app_settings_file": str(self.paths.app_settings_file),
        }

    def list_jobs(self) -> list[dict[str, Any]]:
        return [self.summarize_job(job) for job in self.manager.list_jobs()]

    def analyze_source(self, source_path: str | Path) -> dict[str, Any]:
        source = Path(source_path).expanduser().resolve()
        if not source.exists():
            return asdict(
                DocumentStructure(
                    source_type=source.suffix.lower().lstrip("."),
                    chapter_count=0,
                    chapter_titles=[],
                    supports_chapter_files=False,
                    summary="Datei nicht gefunden. Die Kapitelanalyse kann erst mit einer vorhandenen Quelle laufen.",
                    analysis_status="error",
                    error=f"Source file not found: {source}",
                )
            )
        return asdict(analyze_document_structure(source))

    def metadata_suggestions(self, source_path: str | Path) -> dict[str, Any]:
        source = Path(source_path).expanduser().resolve()
        guessed = guess_metadata_from_filename(source)
        search_error = ""
        try:
            results = search_open_library_metadata(
                query=str(guessed.get("search_query") or ""),
                title=str(guessed.get("title") or ""),
                author=str(guessed.get("author") or ""),
                limit=5,
            )
        except Exception as exc:
            results = []
            search_error = str(exc)
        best = choose_best_metadata_result(
            results,
            guessed_title=str(guessed.get("title") or ""),
            guessed_author=str(guessed.get("author") or ""),
        )
        return {
            "source": str(source),
            "guessed": guessed,
            "results": results,
            "best_result": best,
            "search_error": search_error,
        }

    def search_book_metadata(
        self,
        *,
        query: str = "",
        title: str = "",
        author: str = "",
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        return search_open_library_metadata(query=query, title=title, author=author, limit=limit)

    def get_job(self, job_id: str) -> dict[str, Any]:
        return self.serialize_job(self.manager.load_state(job_id))

    def create_job(
        self,
        *,
        source_path: str | Path,
        saved_profile_id: str = "",
        profile_id: str = "",
        backend: str = "piper",
        voice_id: str = "",
        voice_profile_id: str = "",
        preset_id: str = "balanced",
        priority: int = 50,
        max_chars: int | None = None,
        output_mode: str | None = None,
        target_part_minutes: int | None = None,
        keep_wav: bool | None = None,
        sentence_silence: float | None = None,
        length_scale: float | None = None,
        audiobook_metadata: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        source = Path(source_path).expanduser().resolve()
        if not source.exists():
            raise FileNotFoundError(f"Source file not found: {source}")

        resolved_saved_profile_id = saved_profile_id.strip() or profile_id.strip()
        saved_profile_name = ""
        if resolved_saved_profile_id:
            saved_profile = load_voice_setting(self.paths.voice_settings, resolved_saved_profile_id)
            if saved_profile.status == PROFILE_STATUS_ARCHIVED:
                raise ValueError(f"Saved profile is archived and cannot be used: {saved_profile.display_name}")
            if saved_profile.status == PROFILE_STATUS_DRAFT:
                raise ValueError(
                    f"Saved profile is still a draft and must be tested or approved first: {saved_profile.display_name}"
                )
            saved_profile_name = saved_profile.display_name
            backend = saved_profile.backend
            voice_id = saved_profile.voice_id
            voice_profile_id = saved_profile.voice_profile_id
            preset_id = saved_profile.preset_hint or preset_id
            if max_chars is None:
                max_chars = saved_profile.max_chars
            if output_mode is None:
                output_mode = saved_profile.output_mode
            if target_part_minutes is None:
                target_part_minutes = saved_profile.target_part_minutes
            if sentence_silence is None:
                sentence_silence = saved_profile.sentence_silence
            if length_scale is None:
                length_scale = saved_profile.length_scale
        preset = get_preset(preset_id)
        backend = backend.strip().lower()
        if backend not in {"piper", "xtts"}:
            raise ValueError(f"Unsupported backend: {backend}")
        if backend == "piper" and not voice_id:
            raise ValueError("voice_id is required for Piper jobs")
        if backend == "xtts" and not voice_profile_id:
            raise ValueError("voice_profile_id is required for XTTS jobs")
        if output_mode is not None and output_mode not in VALID_OUTPUT_MODES:
            raise ValueError(f"Unsupported output mode: {output_mode}")

        resolved_output_mode = self._resolve_output_mode_for_source(source, output_mode or preset.output_mode)
        metadata = self._resolve_metadata(
            title=source.stem,
            backend=backend,
            voice_id=voice_id,
            voice_profile_id=voice_profile_id,
            overrides=audiobook_metadata,
        )
        state = self.manager.create_job(
            source_path=source,
            saved_profile_id=resolved_saved_profile_id,
            saved_profile_name=saved_profile_name,
            voice_id=voice_id,
            voice_profile_id=voice_profile_id,
            preset_id=preset.preset_id,
            priority=priority,
            max_chars=max_chars if max_chars is not None else preset.max_chars,
            output_mode=resolved_output_mode,
            target_part_minutes=target_part_minutes if target_part_minutes is not None else preset.target_part_minutes,
            keep_wav=keep_wav if keep_wav is not None else preset.keep_wav,
            sentence_silence=sentence_silence if sentence_silence is not None else preset.sentence_silence,
            length_scale=length_scale if length_scale is not None else preset.length_scale,
            backend=backend,
            audiobook_metadata=metadata,
        )
        state = self.manager.prepare_job(state)
        return self.serialize_job(state)

    def create_jobs(
        self,
        *,
        source_paths: list[str | Path],
        saved_profile_id: str = "",
        profile_id: str = "",
        backend: str = "piper",
        voice_id: str = "",
        voice_profile_id: str = "",
        preset_id: str = "balanced",
        priority: int = 50,
        max_chars: int | None = None,
        output_mode: str | None = None,
        target_part_minutes: int | None = None,
        keep_wav: bool | None = None,
        sentence_silence: float | None = None,
        length_scale: float | None = None,
        audiobook_metadata: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        created: list[dict[str, Any]] = []
        source_items = [Path(source).expanduser().resolve() for source in source_paths]
        for source in source_items:
            per_source_metadata = dict(audiobook_metadata or {})
            if len(source_items) > 1 and per_source_metadata.get("title"):
                per_source_metadata["title"] = f"{per_source_metadata['title']} - {source.stem}"
            created.append(
                self.create_job(
                    source_path=source,
                    saved_profile_id=saved_profile_id,
                    profile_id=profile_id,
                    backend=backend,
                    voice_id=voice_id,
                    voice_profile_id=voice_profile_id,
                    preset_id=preset_id,
                    priority=priority,
                    max_chars=max_chars,
                    output_mode=output_mode,
                    target_part_minutes=target_part_minutes,
                    keep_wav=keep_wav,
                    sentence_silence=sentence_silence,
                    length_scale=length_scale,
                    audiobook_metadata=per_source_metadata or None,
                )
            )
        return created

    def enqueue_job(self, job_id: str) -> dict[str, Any]:
        return self.serialize_job(self.manager.enqueue_job(job_id))

    def run_job(self, job_id: str) -> dict[str, Any]:
        state = self.manager.load_state(job_id)
        finished = self.manager.run_job(state)
        return self.serialize_job(finished)

    def run_next_job(self) -> dict[str, Any] | None:
        next_job = self.manager.next_queued_job()
        if not next_job:
            return None
        return self.serialize_job(self.manager.run_job(next_job))

    def retry_job(
        self,
        job_id: str,
        *,
        chunk_indexes: list[int] | None = None,
        reset_output: bool = True,
    ) -> dict[str, Any]:
        state = self.manager.retry_job(job_id, chunk_indexes=chunk_indexes, reset_output=reset_output)
        return self.serialize_job(state)

    def update_job_metadata(
        self,
        job_id: str,
        *,
        audiobook_metadata: dict[str, str],
        reapply_outputs: bool = True,
    ) -> dict[str, Any]:
        state = self.manager.update_audiobook_metadata(
            job_id,
            metadata_overrides=audiobook_metadata,
            reapply_outputs=reapply_outputs,
        )
        return self.serialize_job(state)

    def delete_job(self, job_id: str) -> None:
        self.manager.delete_job(job_id)

    def list_voices(self) -> dict[str, Any]:
        piper = PiperBackend(self.paths.runtime, self.paths.voices)
        piper_voices = [
            {
                "voice_id": voice_id,
                "label": format_voice_label(voice_id),
                "language": voice_language_code(voice_id),
            }
            for voice_id in piper.installed_voices()
        ]
        xtts_profiles = [
            {
                "profile_id": profile.profile_id,
                "display_name": profile.display_name,
                "language": profile.target_language,
                "sample_count": len(profile.samples),
            }
            for profile in list_voice_profiles(self.paths.voice_profiles)
        ]
        return {"piper": piper_voices, "xtts_profiles": xtts_profiles}

    def list_saved_profiles(self) -> list[dict[str, Any]]:
        return [self.serialize_saved_profile(setting) for setting in list_voice_settings(self.paths.voice_settings)]

    def get_saved_profile(self, setting_id: str) -> dict[str, Any]:
        return self.serialize_saved_profile(load_voice_setting(self.paths.voice_settings, setting_id))

    def update_saved_profile_status(self, setting_id: str, status: str) -> dict[str, Any]:
        normalized = (status or "").strip().lower()
        if normalized not in VALID_PROFILE_STATUSES:
            raise ValueError(f"Unsupported profile status: {status}")
        updated = update_voice_setting_status(self.paths.voice_settings, setting_id, normalized)
        return self.serialize_saved_profile(updated)

    def list_presets(self) -> list[dict[str, Any]]:
        return [asdict(preset) for preset in QUALITY_PRESETS]

    def diagnostics(self, *, include_runtime_probe: bool = False) -> dict[str, Any]:
        app_settings = load_app_settings(self.paths.app_settings_file)
        jobs = self.manager.list_jobs()
        profiles = list_voice_settings(self.paths.voice_settings)
        xtts_profiles = list_voice_profiles(self.paths.voice_profiles)
        piper_backend = PiperBackend(self.paths.runtime, self.paths.voices)
        piper_voice_count = len(piper_backend.installed_voices())
        xtts_backend = XttsBackend(self.paths.runtime, device_mode=app_settings.xtts_device_mode)

        probe: dict[str, Any] | None = None
        preferred_device_mode = app_settings.xtts_device_mode or "auto"
        if include_runtime_probe and xtts_backend.is_available():
            try:
                probe = xtts_backend.runtime_probe()
                if probe.get("ok") and probe.get("cuda_available"):
                    preferred_device_mode = "cuda"
                else:
                    preferred_device_mode = "auto"
            except Exception as exc:
                probe = {"ok": False, "error": str(exc)}

        job_status_counts: dict[str, int] = {}
        for job in jobs:
            job_status_counts[job.status] = job_status_counts.get(job.status, 0) + 1
        profile_status_counts: dict[str, int] = {status: 0 for status in sorted(VALID_PROFILE_STATUSES)}
        for profile in profiles:
            profile_status_counts[profile.status] = profile_status_counts.get(profile.status, 0) + 1

        return {
            "paths": {
                "root": self._path_info(self.paths.root),
                "workspace": self._path_info(self.paths.workspace),
                "jobs": self._path_info(self.paths.jobs),
                "logs": self._path_info(self.paths.logs),
                "statistics": self._path_info(self.paths.statistics),
                "runtime_stats_file": self._path_info(self.paths.runtime_stats_file),
                "runtime": self._path_info(self.paths.runtime),
                "voices": self._path_info(self.paths.voices),
                "voice_profiles": self._path_info(self.paths.voice_profiles),
                "voice_settings": self._path_info(self.paths.voice_settings),
                "preview_sessions": self._path_info(self.paths.preview_sessions),
                "app_settings_file": self._path_info(self.paths.app_settings_file),
            },
            "app_settings": asdict(app_settings),
            "jobs": {
                "count": len(jobs),
                "status_counts": job_status_counts,
                "blocked_jobs": [
                    {"job_id": job.job_id, "title": job.title, "block_reason": job.block_reason}
                    for job in jobs
                    if job.status == "blocked"
                ],
            },
            "profiles": {
                "count": len(profiles),
                "status_counts": profile_status_counts,
                "approved_profiles": [profile.setting_id for profile in profiles if profile.status == PROFILE_STATUS_APPROVED],
            },
            "voices": {
                "piper_voice_count": piper_voice_count,
                "xtts_profile_count": len(xtts_profiles),
            },
            "xtts": {
                "available": xtts_backend.is_available(),
                "availability_reason": xtts_backend.availability_reason(),
                "setup_supported": xtts_setup_supported(self.paths),
                "launcher_hint": xtts_launcher_hint(),
                "selected_device_mode": app_settings.xtts_device_mode,
                "preferred_device_mode": preferred_device_mode,
                "probe": probe,
            },
            "performance_logging": {
                "enabled": is_perf_logging_enabled(),
                "run_id": current_run_id(),
                "target_file": str(perf_log_target_hint()) if perf_log_target_hint() else "",
            },
            "runtime_statistics": runtime_statistics_summary(self.paths.runtime_stats_file),
            "environment": {
                "cpu_count": os.cpu_count() or 1,
                "app_root": str(self.paths.root),
            },
            "system_usage": self._system_usage_snapshot(),
        }

    def serialize_job(self, state: JobState) -> dict[str, Any]:
        payload = state.to_dict()
        payload["completed_chunks"] = state.completed_chunks
        payload["total_chunks"] = state.total_chunks
        payload["failed_chunk_indexes"] = [chunk.index for chunk in state.failed_chunks]
        payload["pending_chunk_indexes"] = [chunk.index for chunk in state.pending_chunks]
        payload["stage_statuses"] = state.stage_statuses()
        payload["job_dir"] = str(state.job_dir(self.paths.jobs))
        payload["job_log_file"] = str(state.job_dir(self.paths.jobs) / "job.log")
        return payload

    def summarize_job(self, state: JobState) -> dict[str, Any]:
        return {
            "job_id": state.job_id,
            "title": state.title,
            "status": state.status,
            "backend": state.backend,
            "saved_profile_id": state.saved_profile_id,
            "saved_profile_name": state.saved_profile_name,
            "voice_id": state.voice_id,
            "voice_profile_id": state.voice_profile_id,
            "preset_id": state.preset_id,
            "priority": state.priority,
            "output_mode": state.output_mode,
            "target_part_minutes": state.target_part_minutes,
            "device_mode": state.device_mode,
            "processing_mode": state.processing_mode,
            "processing_mode_reason": state.processing_mode_reason,
            "completed_chunks": state.completed_chunks,
            "total_chunks": state.total_chunks,
            "chapter_count": len(state.chapters),
            "block_reason": state.block_reason,
            "source_characters": state.source_characters,
            "estimated_total_seconds": state.estimated_total_seconds,
            "estimated_remaining_seconds": state.estimated_remaining_seconds,
            "estimated_confidence": state.estimated_confidence,
            "estimated_from_samples": state.estimated_from_samples,
            "actual_total_seconds": state.actual_total_seconds,
            "final_output_files": state.final_output_files,
            "manifest_file": state.manifest_file,
            "chapters_file": state.chapters_file,
            "failed_chunk_indexes": [chunk.index for chunk in state.failed_chunks],
            "stage_statuses": state.stage_statuses(),
            "job_dir": str(state.job_dir(self.paths.jobs)),
        }

    def serialize_saved_profile(self, setting) -> dict[str, Any]:
        return {
            "setting_id": setting.setting_id,
            "display_name": setting.display_name,
            "backend": setting.backend,
            "voice_id": setting.voice_id,
            "voice_profile_id": setting.voice_profile_id,
            "preset_hint": setting.preset_hint,
            "max_chars": setting.max_chars,
            "output_mode": setting.output_mode,
            "target_part_minutes": setting.target_part_minutes,
            "sentence_silence": setting.sentence_silence,
            "length_scale": setting.length_scale,
            "notes": setting.notes,
            "status": setting.status,
            "status_label": profile_status_label(setting.status),
            "available_for_jobs": setting.status == PROFILE_STATUS_APPROVED,
            "approved_at": setting.approved_at,
            "benchmark_average_ms": setting.benchmark_average_ms,
            "last_benchmark_ms": setting.last_benchmark_ms,
            "last_benchmark_at": setting.last_benchmark_at,
            "source_session_id": setting.source_session_id,
            "source_run_id": setting.source_run_id,
            "source_candidate_id": setting.source_candidate_id,
            "created_at": setting.created_at,
            "updated_at": setting.updated_at,
        }

    def _path_info(self, path: Path) -> dict[str, Any]:
        exists = path.exists()
        return {
            "path": str(path),
            "exists": exists,
            "is_dir": path.is_dir() if exists else False,
            "is_file": path.is_file() if exists else False,
            "writable": os.access(path if exists else path.parent, os.W_OK),
        }

    def _system_usage_snapshot(self) -> dict[str, Any]:
        cpu_percent = None
        memory_percent = None
        memory_used_gb = None
        memory_total_gb = None
        load_1m = None
        load_5m = None
        load_15m = None
        try:
            import psutil

            cpu_percent = float(psutil.cpu_percent(interval=0.05))
            memory = psutil.virtual_memory()
            memory_percent = float(memory.percent)
            memory_used_gb = round(memory.used / (1024**3), 2)
            memory_total_gb = round(memory.total / (1024**3), 2)
        except Exception:
            pass
        try:
            load_1m, load_5m, load_15m = (round(value, 2) for value in os.getloadavg())
        except Exception:
            pass

        gpus: list[dict[str, Any]] = []
        gpu_error = ""
        try:
            result = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=name,utilization.gpu,utilization.memory,memory.used,memory.total",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=5,
                check=True,
            )
            for line in result.stdout.splitlines():
                parts = [part.strip() for part in line.split(",")]
                if len(parts) != 5:
                    continue
                name, gpu_util, memory_util, memory_used, memory_total = parts
                gpus.append(
                    {
                        "name": name,
                        "gpu_percent": float(gpu_util or 0),
                        "memory_percent": float(memory_util or 0),
                        "memory_used_mb": float(memory_used or 0),
                        "memory_total_mb": float(memory_total or 0),
                    }
                )
        except Exception as exc:
            gpu_error = str(exc)

        return {
            "cpu_percent": cpu_percent,
            "memory_percent": memory_percent,
            "memory_used_gb": memory_used_gb,
            "memory_total_gb": memory_total_gb,
            "load_1m": load_1m,
            "load_5m": load_5m,
            "load_15m": load_15m,
            "gpus": gpus,
            "gpu_error": gpu_error,
        }

    def _resolve_metadata(
        self,
        *,
        title: str,
        backend: str,
        voice_id: str,
        voice_profile_id: str,
        overrides: dict[str, str] | None,
    ) -> AudiobookMetadata:
        language = ""
        narrator = ""
        if backend == "piper" and voice_id:
            language = voice_language_code(voice_id).split("_", 1)[0]
            narrator = voice_id
        elif backend == "xtts" and voice_profile_id:
            profile = load_voice_profile(self.paths.voice_profiles, voice_profile_id)
            language = profile.target_language
            narrator = profile.display_name
        fallback = default_audiobook_metadata(
            title=title,
            backend=backend,
            voice_id=voice_id,
            voice_profile_id=voice_profile_id,
            narrator=narrator,
            language=language,
        )
        return AudiobookMetadata.from_dict(overrides, fallback=fallback)

    def _resolve_output_mode_for_source(self, source: Path, requested_output_mode: str) -> str:
        if requested_output_mode != "chapter_files":
            return requested_output_mode
        structure = analyze_document_structure(source)
        return "chapter_files" if structure.supports_chapter_files else "single_file"

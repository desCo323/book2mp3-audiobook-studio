from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
import os
import mimetypes
from pathlib import Path
import subprocess
import tempfile
import urllib.parse
from typing import Any

import requests

from book2mp3.app_settings import AppSettings, load_app_settings, reset_workspace_state, save_app_settings
from book2mp3.config import AppPaths
from book2mp3.metadata_extractor import (
    build_pronunciation_rules,
    extract_metadata_from_source,
    guess_metadata_from_filename,
    search_online_book_metadata,
)
from book2mp3.models import AudiobookMetadata, JobState, default_audiobook_metadata
from book2mp3.pipeline.extract import DocumentStructure, analyze_document_structure
from book2mp3.pipeline.jobs import JobManager
from book2mp3.presets import QUALITY_PRESETS, get_preset
from book2mp3.runtime_stats import runtime_statistics_summary
from book2mp3.tts.piper import PiperBackend
from book2mp3.tts.xtts import XttsBackend
from book2mp3.utils.perf_logging import current_run_id, is_perf_logging_enabled, perf_log_target_hint
from book2mp3.utils.logging_utils import get_logger
from book2mp3.voice_catalog import core_language_voice_counts, format_voice_label, voice_language_code
from book2mp3.voice_lab import list_voice_profiles, load_voice_profile
from book2mp3.voice_settings import (
    STANDARD_XTTS_SETTING_ID,
    PROFILE_STATUS_ARCHIVED,
    PROFILE_STATUS_APPROVED,
    PROFILE_STATUS_DRAFT,
    VALID_PROFILE_STATUSES,
    ensure_standard_xtts_setting,
    list_voice_settings,
    load_voice_setting,
    profile_status_label,
    update_voice_setting_status,
)
from book2mp3.xtts_options import default_xtts_inference, normalize_pronunciation_rules, normalize_xtts_inference, normalize_xtts_quality_mode
from book2mp3.xtts_setup import xtts_launcher_hint, xtts_setup_supported


VALID_OUTPUT_MODES = {"single_file", "timed_parts", "segments", "chapter_files"}


class Book2Mp3Service:
    def __init__(self, paths: AppPaths) -> None:
        self.paths = paths
        self.paths.ensure()
        ensure_standard_xtts_setting(self.paths.voice_settings, self.paths.voice_profiles)
        self.manager = JobManager(paths)
        self.logger = get_logger("service")
        self._metadata_history_warning_emitted = False

    def recover_interrupted_jobs(self) -> None:
        self.manager.recover_interrupted_jobs()

    def reset_workspace(self) -> dict[str, Any]:
        default_settings = AppSettings()
        reset_workspace_state(self.paths.workspace)
        save_app_settings(self.paths.app_settings_file, default_settings)
        self.paths.ensure()
        ensure_standard_xtts_setting(self.paths.voice_settings, self.paths.voice_profiles)
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
        try:
            result = extract_metadata_from_source(
                source,
                allow_online=True,
                cache_path=self.paths.workspace / "statistics" / "metadata_online_cache.json",
            )
        except Exception as exc:
            guessed = guess_metadata_from_filename(source)
            return {
                "source": str(source),
                "guessed": guessed,
                "results": [],
                "best_result": None,
                "search_error": str(exc),
                "confidence": 0.0,
                "title_source": "error",
                "author_source": "error",
                "candidates": [],
                "online_results": [],
                "online_errors": [str(exc)],
                "extended_book_metadata": {},
                "mp3_transfer": {"core_metadata": guessed, "ffmetadata_tags": {}, "extended_book_metadata": {}},
            }
        candidates = [item.to_dict() for item in result.candidates]
        best = candidates[0] if candidates else None
        return {
            "source": str(source),
            "guessed": result.guessed_metadata(),
            "results": candidates,
            "best_result": best,
            "search_error": " | ".join(result.online_errors),
            "confidence": result.confidence,
            "title_source": result.title_source,
            "author_source": result.author_source,
            "candidates": candidates,
            "online_results": result.online_results,
            "online_errors": result.online_errors,
            "extended_book_metadata": result.extended_book_metadata(),
            "mp3_transfer": result.mp3_transfer_payload(),
        }

    def search_book_metadata(
        self,
        *,
        query: str = "",
        title: str = "",
        author: str = "",
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        results, _errors = search_online_book_metadata(
            query=query,
            title=title,
            author=author,
            limit=limit,
            cache_path=self.paths.workspace / "statistics" / "metadata_online_cache.json",
        )
        return results

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
        xtts_quality_mode: str | None = None,
        xtts_inference: dict[str, Any] | None = None,
        pronunciation_rules: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        source = Path(source_path).expanduser().resolve()
        if not source.exists():
            raise FileNotFoundError(f"Source file not found: {source}")

        resolved_saved_profile_id = saved_profile_id.strip() or profile_id.strip()
        saved_profile_name = ""
        resolved_xtts_quality_mode = normalize_xtts_quality_mode(xtts_quality_mode)
        resolved_xtts_inference = normalize_xtts_inference(xtts_inference, quality_mode=resolved_xtts_quality_mode)
        resolved_pronunciation_rules = normalize_pronunciation_rules(pronunciation_rules)
        if not resolved_saved_profile_id:
            requested_backend = backend.strip().lower()
            should_use_standard_xtts = (
                (requested_backend == "xtts" and not voice_profile_id.strip())
                or (not voice_id.strip() and not voice_profile_id.strip())
            )
            standard_profile = (
                ensure_standard_xtts_setting(self.paths.voice_settings, self.paths.voice_profiles)
                if should_use_standard_xtts
                else None
            )
            if standard_profile is not None:
                resolved_saved_profile_id = STANDARD_XTTS_SETTING_ID
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
            if xtts_quality_mode is None:
                resolved_xtts_quality_mode = saved_profile.xtts_quality_mode
            if xtts_inference is None:
                resolved_xtts_inference = dict(saved_profile.xtts_inference)
            if pronunciation_rules is None:
                resolved_pronunciation_rules = list(saved_profile.pronunciation_rules)
        preset = get_preset(preset_id)
        backend = backend.strip().lower()
        if backend not in {"piper", "xtts"}:
            raise ValueError(f"Unsupported backend: {backend}")
        if backend == "piper" and not voice_id:
            raise ValueError("voice_id is required for Piper jobs")
        if backend == "xtts" and not voice_profile_id:
            raise ValueError("voice_profile_id is required for XTTS jobs")
        if backend == "xtts":
            resolved_xtts_quality_mode = normalize_xtts_quality_mode(resolved_xtts_quality_mode)
            resolved_xtts_inference = normalize_xtts_inference(
                resolved_xtts_inference,
                quality_mode=resolved_xtts_quality_mode,
            )
            resolved_pronunciation_rules = normalize_pronunciation_rules(resolved_pronunciation_rules)
        else:
            resolved_xtts_quality_mode = "fast"
            resolved_xtts_inference = default_xtts_inference("fast")
            resolved_pronunciation_rules = []
        if output_mode is not None and output_mode not in VALID_OUTPUT_MODES:
            raise ValueError(f"Unsupported output mode: {output_mode}")

        resolved_output_mode = self._resolve_output_mode_for_source(source, output_mode or preset.output_mode)
        metadata = self._resolve_metadata(
            source_path=source,
            title=source.stem,
            backend=backend,
            voice_id=voice_id,
            voice_profile_id=voice_profile_id,
            overrides=audiobook_metadata,
        )
        if backend == "xtts":
            resolved_pronunciation_rules = self._merge_pronunciation_rules(
                resolved_pronunciation_rules,
                build_pronunciation_rules(authors={metadata.author}),
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
            xtts_quality_mode=resolved_xtts_quality_mode,
            xtts_inference=resolved_xtts_inference,
            pronunciation_rules=resolved_pronunciation_rules,
        )
        state = self.manager.prepare_job(state)
        self.record_metadata_history(state.audiobook_metadata.to_dict())
        return self.serialize_job(state)

    def _merge_pronunciation_rules(
        self,
        preferred_rules: list[dict[str, Any]] | None,
        fallback_rules: list[dict[str, Any]] | None,
    ) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        seen_matches: set[str] = set()
        for raw_rule in normalize_pronunciation_rules(preferred_rules):
            match = str(raw_rule.get("match", "") or "").strip()
            if not match:
                continue
            seen_matches.add(match.casefold())
            merged.append(raw_rule)
        for raw_rule in normalize_pronunciation_rules(fallback_rules):
            match = str(raw_rule.get("match", "") or "").strip()
            if not match or match.casefold() in seen_matches:
                continue
            seen_matches.add(match.casefold())
            merged.append(raw_rule)
        return merged

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
        audiobook_metadata: dict[str, Any] | list[dict[str, Any]] | None = None,
        xtts_quality_mode: str | None = None,
        xtts_inference: dict[str, Any] | None = None,
        pronunciation_rules: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        source_items = self._collect_source_paths(source_paths)
        if not source_items:
            raise ValueError("No supported source files found. Supported: .txt, .pdf, .epub")
        normalized_overrides = self._normalize_job_metadata_overrides(source_items, audiobook_metadata)
        created: list[dict[str, Any]] = []
        for index, source in enumerate(source_items):
            per_source_metadata = dict(normalized_overrides[index]) if index < len(normalized_overrides) else {}
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
                    xtts_quality_mode=xtts_quality_mode,
                    xtts_inference=xtts_inference,
                    pronunciation_rules=pronunciation_rules,
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
        self.record_metadata_history(state.audiobook_metadata.to_dict())
        return self.serialize_job(state)

    def metadata_history_suggestions(self, field_name: str, prefix: str = "", limit: int = 12) -> list[str]:
        payload = self._load_metadata_history()
        values = [str(item).strip() for item in payload.get(field_name, []) if str(item).strip()]
        if prefix.strip():
            lowered = prefix.strip().lower()
            values = [value for value in values if lowered in value.lower()]
        # Newest entries should appear first.
        values = list(reversed(values))
        deduplicated: list[str] = []
        seen: set[str] = set()
        for value in values:
            marker = value.casefold()
            if marker in seen:
                continue
            seen.add(marker)
            deduplicated.append(value)
            if len(deduplicated) >= max(1, int(limit)):
                break
        return deduplicated

    def record_metadata_history(self, metadata: dict[str, Any]) -> None:
        tracked_fields = ("title", "author", "narrator", "publisher", "subject", "genre", "language")
        payload = self._load_metadata_history()
        changed = False
        for field_name in tracked_fields:
            value = str(metadata.get(field_name, "") or "").strip()
            if not value:
                continue
            existing = [str(item).strip() for item in payload.get(field_name, []) if str(item).strip()]
            existing = [item for item in existing if item.casefold() != value.casefold()]
            existing.append(value)
            payload[field_name] = existing[-80:]
            changed = True
        if changed:
            self._save_metadata_history(payload)

    def _metadata_history_path(self) -> Path:
        return self.paths.statistics / "metadata_history.json"

    def _metadata_history_fallback_path(self) -> Path:
        return Path(tempfile.gettempdir()) / "book2mp3-state" / "metadata_history.json"

    def _write_metadata_history(self, path: Path, payload: dict[str, list[str]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    def _load_metadata_history(self) -> dict[str, list[str]]:
        history_path = self._metadata_history_path()
        fallback_path = self._metadata_history_fallback_path()
        bootstrap = self._collect_metadata_history_from_jobs()
        if not history_path.exists():
            if bootstrap:
                self._save_metadata_history(bootstrap)
            if fallback_path.exists():
                try:
                    payload = json.loads(fallback_path.read_text(encoding="utf-8"))
                    if isinstance(payload, dict):
                        bootstrap = {**bootstrap, **{str(k): [str(v) for v in vals if str(v).strip()] for k, vals in payload.items() if isinstance(vals, list)}}
                except (OSError, json.JSONDecodeError):
                    pass
            return bootstrap
        try:
            payload = json.loads(history_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            try:
                payload = json.loads(fallback_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return bootstrap
        if not isinstance(payload, dict):
            return bootstrap
        normalized: dict[str, list[str]] = {}
        for key, values in payload.items():
            if not isinstance(values, list):
                continue
            normalized[str(key)] = [str(item) for item in values if str(item).strip()]
        for key, values in bootstrap.items():
            merged = normalized.get(key, [])
            for value in values:
                if value.casefold() not in {item.casefold() for item in merged}:
                    merged.append(value)
            normalized[key] = merged[-80:]
        return normalized

    def _save_metadata_history(self, payload: dict[str, list[str]]) -> None:
        history_path = self._metadata_history_path()
        try:
            self._write_metadata_history(history_path, payload)
            return
        except PermissionError:
            fallback_path = self._metadata_history_fallback_path()
            self._write_metadata_history(fallback_path, payload)
            if not self._metadata_history_warning_emitted:
                self.logger.warning(
                    "Primary metadata history file was not writable, using fallback file %s",
                    fallback_path,
                )
                self._metadata_history_warning_emitted = True

    def _collect_metadata_history_from_jobs(self) -> dict[str, list[str]]:
        tracked_fields = ("title", "author", "narrator", "publisher", "subject", "genre", "language")
        collected: dict[str, list[str]] = {field_name: [] for field_name in tracked_fields}
        for job in self.manager.list_jobs():
            metadata = job.audiobook_metadata.to_dict()
            for field_name in tracked_fields:
                value = str(metadata.get(field_name, "") or "").strip()
                if not value:
                    continue
                if value.casefold() in {item.casefold() for item in collected[field_name]}:
                    continue
                collected[field_name].append(value)
        return {key: values for key, values in collected.items() if values}

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
        installed_piper_voices = piper_backend.installed_voices()
        piper_voice_count = len(installed_piper_voices)
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
                "final_books": self._path_info(self.paths.final_books),
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
                "core_language_voice_counts": core_language_voice_counts(installed_piper_voices),
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
            "xtts_quality_mode": state.xtts_quality_mode,
            "pronunciation_rule_count": len(state.pronunciation_rules),
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
            "xtts_quality_mode": setting.xtts_quality_mode,
            "xtts_inference": setting.xtts_inference,
            "pronunciation_rules": setting.pronunciation_rules,
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

    def _collect_source_paths(self, source_paths: list[str | Path]) -> list[Path]:
        allowed_suffixes = {".txt", ".pdf", ".epub"}
        collected: list[Path] = []
        seen: set[Path] = set()
        for source_path in source_paths:
            source = Path(source_path).expanduser().resolve()
            if source.is_dir():
                for candidate in sorted(source.rglob("*")):
                    if candidate.is_file() and candidate.suffix.lower() in allowed_suffixes:
                        normalized = candidate.resolve()
                        if normalized in seen:
                            continue
                        seen.add(normalized)
                        collected.append(normalized)
                continue
            if source.is_file() and source.suffix.lower() in allowed_suffixes:
                normalized = source
                if normalized in seen:
                    continue
                seen.add(normalized)
                collected.append(normalized)
        return collected

    def _normalize_job_metadata_overrides(
        self,
        source_paths: list[Path],
        audiobook_metadata: dict[str, Any] | list[dict[str, Any]] | None,
    ) -> list[dict[str, Any]]:
        if not source_paths:
            return []
        if audiobook_metadata is None:
            return [dict() for _ in source_paths]
        if isinstance(audiobook_metadata, dict):
            return [dict(audiobook_metadata) for _ in source_paths]
        normalized_list: list[dict[str, Any]] = []
        for item in audiobook_metadata:
            if isinstance(item, dict):
                normalized_list.append(dict(item))
        if not normalized_list:
            return [dict() for _ in source_paths]
        while len(normalized_list) < len(source_paths):
            normalized_list.append(dict(normalized_list[-1]))
        return normalized_list[: len(source_paths)]

    def _resolve_metadata(
        self,
        *,
        source_path: Path | None,
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
        if overrides is None:
            overrides = {}
        overrides_dict = {str(key): value for key, value in overrides.items()}
        fallback = default_audiobook_metadata(
            title=title,
            backend=backend,
            voice_id=voice_id,
            voice_profile_id=voice_profile_id,
            narrator=narrator,
            language=language,
        )
        suggested_payload: dict[str, Any] = {}
        if source_path is not None:
            needs_suggestion = not overrides or any(
                not str(overrides.get(key) or "").strip()
                for key in ("title", "author", "genre", "language", "comment", "publisher", "subject", "isbn")
            )
            if needs_suggestion:
                try:
                    result = extract_metadata_from_source(
                        source_path,
                        allow_online=True,
                        cache_path=self.paths.workspace / "statistics" / "metadata_online_cache.json",
                    )
                    transfer = result.mp3_transfer_payload(narrator=narrator)
                    suggested_payload = {
                        **transfer.get("core_metadata", {}),
                        "cover_url": str(transfer.get("cover_url") or ""),
                        "publisher": str(transfer.get("ffmetadata_tags", {}).get("publisher") or ""),
                        "year": int(str(transfer.get("ffmetadata_tags", {}).get("year") or "0") or 0),
                        "subject": str(transfer.get("ffmetadata_tags", {}).get("subject") or ""),
                        "isbn": str(transfer.get("ffmetadata_tags", {}).get("isbn") or ""),
                        "description": str(transfer.get("ffmetadata_tags", {}).get("description") or ""),
                    }
                    suggested_payload.pop("artist", None)
                    suggested_payload.pop("album_artist", None)
                    suggested_payload.pop("narrator", None)
                except Exception:
                    suggested_payload = {}
        resolved = AudiobookMetadata.from_dict(suggested_payload or None, fallback=fallback)
        with_overrides = AudiobookMetadata.from_dict(overrides_dict, fallback=resolved)
        resolved_cover_file = self._resolve_cover_art_file(
            source_path=source_path,
            override_cover_url=str(overrides_dict.get("cover_url", "") or ""),
            suggested_cover_url=resolved.cover_url,
            override_cover_art_file=str(overrides_dict.get("cover_art_file", "") or ""),
        )
        with_overrides.cover_art_file = str(resolved_cover_file)
        override_cover_url = str(overrides_dict.get("cover_url", "") or "").strip()
        with_overrides.cover_url = override_cover_url or str(with_overrides.cover_url).strip()
        return with_overrides

    def _resolve_cover_art_file(
        self,
        *,
        source_path: Path | None,
        override_cover_url: str,
        suggested_cover_url: str,
        override_cover_art_file: str,
    ) -> Path | str:
        source_hint = source_path.name if source_path else "unknown_source"
        requested_local_path = str(override_cover_art_file or "").strip()
        if requested_local_path:
            if not Path(requested_local_path).is_absolute():
                candidate = Path(requested_local_path)
                if candidate.exists():
                    return candidate.resolve()
            candidate = Path(requested_local_path)
            if candidate.exists():
                return candidate.resolve()
        requested_url = str(override_cover_url or "").strip()
        url = requested_url.strip() or str(suggested_cover_url or "").strip()
        if url and source_path is not None:
            if not (url.startswith("http://") or url.startswith("https://")):
                local_candidate = Path(url)
                if local_candidate.exists():
                    return local_candidate.resolve()
                return ""
            cache_root = self.paths.workspace / "metadata_covers"
            cache_root.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha1(url.encode("utf-8")).hexdigest()
            extension = self._image_extension_from_url(url)
            filename = f"{source_hint}_{digest}{extension}"
            target_path = cache_root / filename
            if target_path.exists() and target_path.stat().size > 0:
                return target_path.resolve()
            try:
                response = requests.get(url, timeout=20)
                response.raise_for_status()
                if not response.content:
                    return ""
                extension = extension or self._image_extension_from_content_type(response.headers.get("Content-Type"))
                target_path = cache_root / f"{source_hint}_{digest}{extension}"
                target_path.write_bytes(response.content)
                return target_path.resolve()
            except Exception:
                return ""
        return ""

    def _image_extension_from_url(self, value: str) -> str:
        parsed = urllib.parse.urlparse(value)
        candidate = Path(parsed.path or "").suffix.lower()
        if candidate in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}:
            return candidate
        return ""

    def _image_extension_from_content_type(self, content_type: str | None) -> str:
        if not content_type:
            return ".jpg"
        mime = content_type.split(";", 1)[0].strip().lower()
        extension = mimetypes.guess_extension(mime) or ".jpg"
        return extension if extension in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"} else ".jpg"

    def _resolve_output_mode_for_source(self, source: Path, requested_output_mode: str) -> str:
        if requested_output_mode != "chapter_files":
            return requested_output_mode
        structure = analyze_document_structure(source)
        return "chapter_files" if structure.supports_chapter_files else "single_file"

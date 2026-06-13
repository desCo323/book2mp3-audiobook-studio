from __future__ import annotations

import concurrent.futures
import json
import os
import re
import shutil
import time
import uuid
from collections.abc import Iterable
from dataclasses import replace
from pathlib import Path
import logging

from book2mp3.config import AppPaths
from book2mp3.app_settings import load_app_settings
from book2mp3.models import AudiobookMetadata, ChapterRecord, ChunkRecord, JobState, default_audiobook_metadata, utc_now
from book2mp3.pipeline.audio import (
    apply_mp3_metadata_in_place,
    concat_audio_files_to_mp3,
    concat_mp3_files,
    probe_media_duration_seconds,
    segment_mp3_file,
    wav_to_mp3,
)
from book2mp3.pipeline.chunking import split_text
from book2mp3.pipeline.extract import extract_document
from book2mp3.presets import get_preset
from book2mp3.runtime_stats import estimate_runtime, preferred_processing_mode, record_runtime_stat
from book2mp3.tts.piper import PiperBackend
from book2mp3.tts.xtts import XttsBackend
from book2mp3.utils.logging_utils import attach_job_file_logger, get_logger
from book2mp3.voice_lab import load_voice_profile


class StopRequested(Exception):
    pass


def _safe_file_component(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    cleaned = re.sub(r"_+", "_", cleaned).strip("._-")
    return cleaned or "chapter"


class JobManager:
    def __init__(self, paths: AppPaths) -> None:
        self.paths = paths
        self.paths.ensure()
        self.logger = get_logger("jobs")

    def job_logger(self, state: JobState) -> logging.Logger:
        app_settings = load_app_settings(self.paths.app_settings_file)
        logger = attach_job_file_logger(
            state.job_id,
            self.paths.jobs / state.job_id,
            debug_enabled=app_settings.debug_logging,
        )
        return logger

    def create_job(
        self,
        source_path: Path,
        voice_id: str,
        voice_profile_id: str,
        preset_id: str,
        priority: int,
        max_chars: int,
        output_mode: str,
        target_part_minutes: int,
        keep_wav: bool,
        sentence_silence: float,
        length_scale: float,
        backend: str = "piper",
        saved_profile_id: str = "",
        saved_profile_name: str = "",
        audiobook_metadata: AudiobookMetadata | dict[str, str] | None = None,
    ) -> JobState:
        job_id = uuid.uuid4().hex[:12]
        job_dir = self.paths.jobs / job_id
        input_dir = job_dir / "input"
        input_dir.mkdir(parents=True, exist_ok=True)
        target_source = input_dir / source_path.name
        shutil.copy2(source_path, target_source)
        self.logger.info("Creating job for source %s", source_path)

        title = source_path.stem
        output_dir = job_dir / "output"
        default_metadata = default_audiobook_metadata(
            title=title,
            backend=backend,
            voice_id=voice_id,
            voice_profile_id=voice_profile_id,
        )
        resolved_metadata = AudiobookMetadata.from_dict(
            audiobook_metadata if isinstance(audiobook_metadata, dict) else audiobook_metadata.to_dict() if audiobook_metadata else None,
            fallback=default_metadata,
        )
        state = JobState(
            job_id=job_id,
            title=title,
            source_name=source_path.name,
            source_type=source_path.suffix.lower().lstrip("."),
            created_at=utc_now(),
            updated_at=utc_now(),
            status="queued",
            backend=backend,
            saved_profile_id=saved_profile_id,
            saved_profile_name=saved_profile_name,
            voice_id=voice_id,
            voice_profile_id=voice_profile_id,
            preset_id=preset_id,
            priority=priority,
            output_mode=output_mode,
            target_part_minutes=target_part_minutes,
            keep_wav=keep_wav,
            max_chars=max_chars,
            sentence_silence=sentence_silence,
            length_scale=length_scale,
            source_file=str(target_source),
            extracted_file=str(job_dir / "extracted" / "source.txt"),
            final_output_file=str(output_dir / f"{title}.mp3"),
            final_output_files=[],
            block_reason="",
            audiobook_metadata=resolved_metadata,
            manifest_file=str(output_dir / "manifest.json"),
            chapters_file=str(output_dir / "chapters.json"),
            chapters=[],
            chunks=[],
            device_mode="cpu" if backend == "piper" else "auto",
            processing_mode="serial",
            processing_mode_reason="Noch kein Lauf gestartet.",
            source_characters=0,
            estimated_total_seconds=0.0,
            estimated_remaining_seconds=0.0,
            estimated_confidence="none",
            estimated_from_samples=0,
            actual_total_seconds=0.0,
            processing_started_at="",
            processing_completed_at="",
        )
        state.append_log(f"Job queued for {source_path.name} with priority {priority}")
        self.save_state(state)
        self.job_logger(state).info("Job created: %s", state.to_dict())
        return state

    def list_jobs(self) -> list[JobState]:
        jobs: list[JobState] = []
        for state_file in sorted(self.paths.jobs.glob("*/state.json")):
            jobs.append(self.load_state(state_file.parent.name))
        return sorted(
            jobs,
            key=lambda item: (
                0 if item.status in {"running", "queued", "prepared"} else 1 if item.status == "blocked" else 2,
                -item.priority,
                item.created_at,
            ),
        )

    def load_state(self, job_id: str) -> JobState:
        state_file = self.paths.jobs / job_id / "state.json"
        payload = json.loads(state_file.read_text(encoding="utf-8"))
        return JobState.from_dict(payload)

    def save_state(self, state: JobState) -> None:
        job_dir = self.paths.jobs / state.job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        state.updated_at = utc_now()
        (job_dir / "state.json").write_text(
            json.dumps(state.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def recover_interrupted_jobs(self) -> None:
        for job in self.list_jobs():
            logger = self.job_logger(job)
            if job.chunks:
                job = self._reconcile_chunk_artifacts(
                    job,
                    logger=logger,
                    append_log=job.status in {"running", "failed", "stopped"},
                )
                job = self._catch_up_xtts_deferred_mp3_artifacts(
                    job,
                    logger=logger,
                    append_log=job.status in {"running", "failed", "stopped"},
                )
            if job.status == "running":
                job.status = "queued"
                job.append_log("Recovered running job after restart and returned it to the queue")
                self.save_state(job)
                logger.warning("Recovered interrupted running job after restart")
            elif job.status == "failed" and job.backend == "xtts":
                reason = self.backend_block_reason(job)
                if reason:
                    if self._should_attempt_xtts_self_heal(reason) and job.auto_recovery_attempts < 1:
                        job.auto_recovery_attempts += 1
                        repaired, repair_message = self._attempt_xtts_self_heal(logger=logger, detail=reason)
                        if repaired:
                            job.status = "queued"
                            job.block_reason = ""
                            job.append_log(f"Recovered failed XTTS job after automatic runtime repair: {repair_message}")
                            self.save_state(job)
                            logger.warning("Recovered failed XTTS job %s after runtime repair", job.job_id)
                            continue
                        job.append_log(f"Automatic XTTS repair failed during restart recovery: {repair_message}")
                    job.status = "blocked"
                    job.block_reason = reason
                    job.append_log(f"Recovered failed XTTS job into blocked state: {reason}")
                    job = self._write_failure_report(
                        job,
                        category="xtts_runtime_incomplete",
                        error=reason,
                        recovery_result="Automatische Prüfung beim Neustart ergab eine unvollständige XTTS-Runtime.",
                        auto_recovery_attempted=job.auto_recovery_attempts > 0,
                        recommended_action="XTTS-Setup prüfen oder Piper nutzen, bis die Runtime wieder vollständig ist.",
                        details={"source": "recover_interrupted_jobs"},
                    )
                    self.save_state(job)
                    logger.warning("Recovered failed XTTS job %s into blocked state", job.job_id)
                else:
                    failed_error_text = " | ".join(chunk.error for chunk in job.failed_chunks if chunk.error)
                    if (
                        job.failed_chunks
                        and (
                            job.last_failure_category == "xtts_runtime_incomplete"
                            or "XTTS synthesis failed with exit code 1" in failed_error_text
                            or "XTTS server returned no response" in failed_error_text
                        )
                    ):
                        job.status = "queued"
                        job.block_reason = ""
                        job.auto_recovery_attempts += 1
                        job.append_log("Recovered failed XTTS job after transient/runtime failure and returned it to the queue")
                        self.save_state(job)
                        logger.warning("Recovered failed XTTS job %s back into queue", job.job_id)
        self.refresh_queue_availability()

    def _xtts_backend(self, logger: logging.Logger | None = None) -> XttsBackend:
        app_settings = load_app_settings(self.paths.app_settings_file)
        device_mode = self._resolved_xtts_device_mode(app_settings.xtts_device_mode, logger=logger)
        return XttsBackend(
            self.paths.runtime,
            logger=logger,
            device_mode=device_mode,
        )

    def _resolved_xtts_device_mode(self, requested_mode: str, logger: logging.Logger | None = None) -> str:
        normalized = (requested_mode or "auto").strip().lower()
        if normalized != "auto":
            return normalized
        backend = XttsBackend(self.paths.runtime, logger=logger, device_mode="auto")
        preferred = backend.preferred_device_mode()
        return preferred if preferred in {"cuda", "cpu"} else "auto"

    def _xtts_batch_parameters(self, state: JobState) -> tuple[int, int]:
        del state
        app_settings = load_app_settings(self.paths.app_settings_file)
        if self._resolved_xtts_device_mode(app_settings.xtts_device_mode) == "cuda":
            return 12, 3600
        return 8, 2200

    def _xtts_should_defer_mp3(self, state: JobState) -> bool:
        return state.backend == "xtts" and state.output_mode in {"single_file", "chapter_files", "timed_parts"}

    def _xtts_should_parallel_postprocess(self, state: JobState) -> bool:
        app_settings = load_app_settings(self.paths.app_settings_file)
        return (
            state.backend == "xtts"
            and self._xtts_should_defer_mp3(state)
            and self._resolved_xtts_device_mode(app_settings.xtts_device_mode) == "cuda"
            and (os.cpu_count() or 1) >= 4
        )

    def _eligible_processing_modes(self, state: JobState) -> set[str]:
        modes = {"serial"}
        if self._xtts_should_parallel_postprocess(state):
            modes.add("parallel_cpu_postprocess")
        return modes

    def _select_processing_mode(self, state: JobState, *, logger: logging.Logger | None = None) -> tuple[str, str]:
        eligible_modes = self._eligible_processing_modes(state)
        if state.backend != "xtts":
            return "serial", "Piper nutzt den seriellen Standardpfad."
        app_settings = load_app_settings(self.paths.app_settings_file)
        requested_mode = (app_settings.xtts_processing_mode or "auto").strip().lower()
        if requested_mode in {"serial", "parallel_cpu_postprocess"}:
            if requested_mode in eligible_modes:
                return requested_mode, f"Fester XTTS-Verarbeitungsmodus aus den App-Einstellungen: {requested_mode}."
            return "serial", f"Gewünschter XTTS-Modus {requested_mode} ist hier nicht verfügbar."
        preferred = preferred_processing_mode(
            self.paths.runtime_stats_file,
            backend=state.backend,
            saved_profile_id=state.saved_profile_id,
            voice_id=state.voice_id,
            voice_profile_id=state.voice_profile_id,
            device_mode=state.device_mode,
            output_mode=state.output_mode,
        )
        preferred_mode = str(preferred.get("mode", "") or "")
        if preferred_mode and preferred_mode in eligible_modes:
            return preferred_mode, str(preferred.get("reason", "") or "Aus historischen Laufzeitdaten abgeleitet.")
        if "parallel_cpu_postprocess" in eligible_modes:
            return "parallel_cpu_postprocess", "CUDA aktiv und CPU-Kapazität frei; paralleler Postprozess ist der Startstandard."
        return "serial", "Keine sichere oder gemessene Paralleloption verfügbar."

    def _update_runtime_estimate(self, state: JobState) -> JobState:
        estimate = estimate_runtime(
            self.paths.runtime_stats_file,
            backend=state.backend,
            saved_profile_id=state.saved_profile_id,
            voice_id=state.voice_id,
            voice_profile_id=state.voice_profile_id,
            device_mode=state.device_mode,
            processing_mode=state.processing_mode,
            output_mode=state.output_mode,
            source_characters=state.source_characters,
            chunk_count=state.total_chunks,
        )
        state.estimated_total_seconds = float(estimate.get("estimated_total_seconds", 0.0) or 0.0)
        state.estimated_remaining_seconds = float(estimate.get("estimated_remaining_seconds", 0.0) or 0.0)
        state.estimated_confidence = str(estimate.get("confidence", "none") or "none")
        state.estimated_from_samples = int(estimate.get("sample_count", 0) or 0)
        return state

    def _update_runtime_progress(self, state: JobState, *, started_monotonic: float) -> JobState:
        if state.total_chunks <= 0:
            state.estimated_remaining_seconds = 0.0
            return state
        elapsed = max(0.0, time.perf_counter() - started_monotonic)
        completed = max(0, state.completed_chunks)
        if completed <= 0:
            state.estimated_remaining_seconds = state.estimated_total_seconds
            return state
        projected_total = max(elapsed, (elapsed / completed) * state.total_chunks)
        if state.estimated_total_seconds > 0:
            blended_total = (state.estimated_total_seconds * 0.45) + (projected_total * 0.55)
        else:
            blended_total = projected_total
        state.estimated_total_seconds = round(max(blended_total, elapsed), 3)
        state.estimated_remaining_seconds = round(max(0.0, state.estimated_total_seconds - elapsed), 3)
        return state

    def _xtts_postprocess_workers(self) -> int:
        cpu_count = os.cpu_count() or 1
        return 2 if cpu_count >= 8 else 1

    def _convert_xtts_batch_to_mp3(
        self,
        batch: list[ChunkRecord],
        *,
        keep_wav: bool,
        logger: logging.Logger,
    ) -> None:
        for item in batch:
            wav_path = Path(item.wav_file)
            mp3_path = Path(item.mp3_file)
            if not wav_path.exists():
                continue
            wav_to_mp3(wav_path, mp3_path, logger=logger)
            if not keep_wav and wav_path.exists():
                wav_path.unlink()
                logger.debug("Removed intermediate WAV %s after CPU postprocess", item.wav_file)

    def _chunk_audio_path(self, chunk: ChunkRecord) -> Path | None:
        mp3_path = Path(chunk.mp3_file)
        if mp3_path.exists():
            return mp3_path
        wav_path = Path(chunk.wav_file)
        if wav_path.exists():
            return wav_path
        return None

    def _xtts_chunk_has_audio(self, chunk: ChunkRecord, *, defer_mp3: bool) -> bool:
        mp3_path = Path(chunk.mp3_file)
        if mp3_path.exists():
            return True
        if defer_mp3:
            wav_path = Path(chunk.wav_file)
            if wav_path.exists():
                return True
        return False

    def _xtts_chunk_needs_processing(self, chunk: ChunkRecord, *, defer_mp3: bool) -> bool:
        if chunk.status != "done":
            return True
        return not self._xtts_chunk_has_audio(chunk, defer_mp3=defer_mp3)

    def _chunk_text_has_content(self, chunk: ChunkRecord) -> bool:
        text_path = Path(chunk.text_file)
        if not text_path.exists():
            return False
        try:
            return text_path.stat().st_size > 0
        except OSError:
            return False

    def _catch_up_xtts_deferred_mp3_artifacts(
        self,
        state: JobState,
        *,
        logger: logging.Logger,
        append_log: bool = False,
    ) -> JobState:
        if state.backend != "xtts" or not self._xtts_should_defer_mp3(state):
            return state
        repaired = 0
        updated_chunks = list(state.chunks)
        for chunk in state.chunks:
            if not self._chunk_text_has_content(chunk):
                continue
            mp3_path = Path(chunk.mp3_file)
            if mp3_path.exists():
                continue
            wav_path = Path(chunk.wav_file)
            if not wav_path.exists():
                continue
            logger.warning(
                "Found text-bearing XTTS chunk with WAV but missing MP3; catching up deferred postprocess for chunk %s",
                chunk.index,
            )
            wav_to_mp3(wav_path, mp3_path, logger=logger)
            if not state.keep_wav and wav_path.exists():
                wav_path.unlink()
                logger.debug("Removed intermediate WAV %s after deferred catch-up", chunk.wav_file)
            updated_chunks[chunk.index - 1] = replace(
                chunk,
                status="done",
                error="",
                updated_at=utc_now(),
            )
            repaired += 1
        if not repaired:
            return state
        state.chunks = updated_chunks
        if append_log:
            state.append_log(f"Recovered {repaired} XTTS chunk MP3 file(s) from existing WAV artifacts")
        self.save_state(state)
        logger.info("Recovered %s deferred XTTS MP3 artifact(s) for job %s", repaired, state.job_id)
        return state

    def _missing_text_audio_chunks(self, state: JobState) -> list[int]:
        missing: list[int] = []
        for chunk in state.chunks:
            if not self._chunk_text_has_content(chunk):
                continue
            if self._chunk_audio_path(chunk) is None:
                missing.append(chunk.index)
        return missing

    def _reconcile_chunk_artifacts(
        self,
        state: JobState,
        *,
        logger: logging.Logger | None = None,
        append_log: bool = False,
    ) -> JobState:
        defer_mp3 = self._xtts_should_defer_mp3(state)
        restored_done = 0
        reset_pending = 0
        updated_chunks: list[ChunkRecord] = []
        for chunk in state.chunks:
            has_audio = self._xtts_chunk_has_audio(chunk, defer_mp3=defer_mp3)
            updated = chunk
            if has_audio and chunk.status != "done":
                updated = replace(
                    chunk,
                    status="done",
                    error="",
                    updated_at=utc_now(),
                )
                restored_done += 1
            elif not has_audio and chunk.status == "done":
                updated = replace(
                    chunk,
                    status="pending",
                    error="",
                    updated_at=utc_now(),
                )
                reset_pending += 1
            updated_chunks.append(updated)
        if not restored_done and not reset_pending:
            return state
        state.chunks = updated_chunks
        if append_log:
            summary_bits: list[str] = []
            if restored_done:
                summary_bits.append(f"{restored_done} Chunk(s) aus vorhandenen Audiodateien wiederhergestellt")
            if reset_pending:
                summary_bits.append(f"{reset_pending} Chunk(s) ohne Audio auf pending zurückgesetzt")
            state.append_log("Recovery synchronised chunk state: " + ", ".join(summary_bits))
        if logger:
            logger.info(
                "Reconciled chunk artifacts for job %s: restored_done=%s reset_pending=%s",
                state.job_id,
                restored_done,
                reset_pending,
            )
        self.save_state(state)
        return state

    def _select_xtts_batch(self, state: JobState, pending_chunks: list[ChunkRecord]) -> list[ChunkRecord]:
        batch_limit, char_limit = self._xtts_batch_parameters(state)
        selected: list[ChunkRecord] = []
        total_chars = 0
        for chunk in pending_chunks:
            text_size = Path(chunk.text_file).stat().st_size if Path(chunk.text_file).exists() else state.max_chars
            if selected and (len(selected) >= batch_limit or total_chars + text_size > char_limit):
                break
            selected.append(chunk)
            total_chars += text_size
        return selected[:batch_limit] or pending_chunks[:1]

    def _job_failure_report_path(self, state: JobState) -> Path:
        return state.job_dir(self.paths.jobs) / "failure_report.json"

    def _write_failure_report(
        self,
        state: JobState,
        *,
        category: str,
        error: str,
        recovery_result: str,
        auto_recovery_attempted: bool,
        recommended_action: str,
        details: dict[str, object] | None = None,
    ) -> JobState:
        report_path = self._job_failure_report_path(state)
        payload = {
            "job_id": state.job_id,
            "title": state.title,
            "backend": state.backend,
            "status": state.status,
            "category": category,
            "error": error,
            "block_reason": state.block_reason,
            "auto_recovery_attempts": state.auto_recovery_attempts,
            "auto_recovery_attempted": auto_recovery_attempted,
            "recovery_result": recovery_result,
            "device_mode": state.device_mode,
            "processing_mode": state.processing_mode,
            "completed_chunks": state.completed_chunks,
            "total_chunks": state.total_chunks,
            "failed_chunk_indexes": [chunk.index for chunk in state.failed_chunks],
            "recommended_action": recommended_action,
            "details": details or {},
            "generated_at": utc_now(),
        }
        report_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        state.failure_report_file = str(report_path)
        state.last_failure_category = category
        state.append_log(f"Failure report written: {report_path.name} ({category})")
        return state

    def _xtts_runtime_reason(self, logger: logging.Logger | None = None) -> str:
        backend = self._xtts_backend(logger=logger)
        return backend.availability_reason()

    def _should_attempt_xtts_self_heal(self, reason: str) -> bool:
        normalized = (reason or "").lower()
        return any(
            marker in normalized
            for marker in (
                "unvollständig",
                "dependencies missing",
                "module not found",
                "no module named",
            )
        )

    def _attempt_xtts_self_heal(self, logger: logging.Logger | None = None, detail: str = "") -> tuple[bool, str]:
        backend = self._xtts_backend(logger=logger)
        reason = backend.availability_reason()
        if not self._should_attempt_xtts_self_heal(f"{reason}\n{detail}"):
            return False, "Automatische XTTS-Reparatur ist fuer diesen Fehler nicht geeignet."
        return backend.attempt_runtime_self_heal(detail=detail or reason)

    def backend_block_reason(self, state: JobState) -> str | None:
        if state.backend == "piper":
            backend = PiperBackend(self.paths.runtime, self.paths.voices)
            try:
                backend.binary_path()
                backend.voice_path(state.voice_id)
            except FileNotFoundError as exc:
                return str(exc)
            return None
        if state.backend == "xtts":
            backend = self._xtts_backend()
            if not backend.is_available():
                return backend.availability_reason()
            if not state.voice_profile_id:
                return "XTTS-Profil fehlt fuer diesen Auftrag."
            try:
                load_voice_profile(self.paths.voice_profiles, state.voice_profile_id)
            except FileNotFoundError:
                return f"XTTS-Profil nicht gefunden: {state.voice_profile_id}"
            return None
        return f"Unsupported backend: {state.backend}"

    def refresh_job_availability(self, state: JobState) -> JobState:
        reason = self.backend_block_reason(state)
        if reason:
            if state.backend == "xtts" and self._should_attempt_xtts_self_heal(reason) and state.auto_recovery_attempts < 1:
                logger = self.job_logger(state)
                state.auto_recovery_attempts += 1
                repaired, repair_message = self._attempt_xtts_self_heal(logger=logger, detail=reason)
                state.append_log(
                    "Automatic XTTS runtime repair "
                    + ("succeeded." if repaired else f"failed: {repair_message}")
                )
                if repaired:
                    state.block_reason = ""
                    self.save_state(state)
                    logger.warning("XTTS runtime self-heal succeeded for blocked job %s", state.job_id)
                    reason = self.backend_block_reason(state)
                    if not reason:
                        if state.status == "blocked":
                            state.status = "queued"
                        self.save_state(state)
                        return state
                else:
                    self.save_state(state)
            if state.status in {"queued", "prepared", "blocked"} and (
                state.status != "blocked" or state.block_reason != reason
            ):
                state.status = "blocked"
                state.block_reason = reason
                state.append_log(f"Job blocked: {reason}")
                self.save_state(state)
                self.job_logger(state).warning("Job blocked: %s", reason)
            return state
        if state.status == "blocked":
            state.status = "queued"
            state.block_reason = ""
            state.append_log("Job unblocked and returned to the queue")
            self.save_state(state)
            self.job_logger(state).info("Job unblocked and returned to the queue")
            return state
        if state.block_reason:
            state.block_reason = ""
            self.save_state(state)
        return state

    def refresh_queue_availability(self) -> list[JobState]:
        refreshed: list[JobState] = []
        for job in self.list_jobs():
            if job.status in {"queued", "prepared", "blocked"}:
                refreshed.append(self.refresh_job_availability(job))
            else:
                refreshed.append(job)
        return refreshed

    def update_priority(self, job_id: str, priority: int) -> JobState:
        state = self.load_state(job_id)
        state.priority = priority
        state.append_log(f"Priority changed to {priority}")
        self.save_state(state)
        self.job_logger(state).info("Priority updated to %s", priority)
        return state

    def reorder_jobs(self, ordered_ids: list[str]) -> None:
        jobs_by_id = {job.job_id: job for job in self.list_jobs()}
        descending_priorities = list(range(len(ordered_ids), 0, -1))
        for job_id, priority in zip(ordered_ids, descending_priorities, strict=False):
            state = jobs_by_id.get(job_id)
            if not state:
                continue
            state.priority = priority
            state.append_log(f"Queue position changed. New priority {priority}")
            self.save_state(state)
            self.job_logger(state).info("Queue order updated to priority %s", priority)

    def move_job(self, job_id: str, direction: str) -> JobState | None:
        jobs = self.list_jobs()
        ordered_ids = [job.job_id for job in jobs]
        if job_id not in ordered_ids:
            return None
        index = ordered_ids.index(job_id)
        if direction == "top":
            target_index = 0
        elif direction == "up":
            target_index = max(0, index - 1)
        elif direction == "down":
            target_index = min(len(ordered_ids) - 1, index + 1)
        elif direction == "bottom":
            target_index = len(ordered_ids) - 1
        else:
            raise ValueError(f"Unsupported direction: {direction}")
        ordered_ids.insert(target_index, ordered_ids.pop(index))
        self.reorder_jobs(ordered_ids)
        return self.load_state(job_id)

    def delete_job(self, job_id: str) -> None:
        job_dir = self.paths.jobs / job_id
        if job_dir.exists():
            shutil.rmtree(job_dir)
        self.logger.info("Deleted job %s", job_id)

    def update_audiobook_metadata(
        self,
        job_id: str,
        *,
        metadata_overrides: dict[str, str],
        reapply_outputs: bool = True,
    ) -> JobState:
        state = self.load_state(job_id)
        fallback = state.audiobook_metadata
        updated_metadata = AudiobookMetadata.from_dict(metadata_overrides, fallback=fallback)
        state.audiobook_metadata = updated_metadata
        if updated_metadata.title:
            state.title = updated_metadata.title
        state.append_log("Audiobook metadata updated")
        logger = self.job_logger(state)
        if reapply_outputs and state.final_output_files:
            self._finalize_outputs(state, logger)
            state.append_log("Updated MP3 tags and export manifests for completed outputs")
        self.save_state(state)
        logger.info("Updated audiobook metadata for job %s", job_id)
        return state

    def retry_job(
        self,
        job_id: str,
        *,
        chunk_indexes: Iterable[int] | None = None,
        reset_output: bool = True,
    ) -> JobState:
        state = self.load_state(job_id)
        selected = {int(index) for index in chunk_indexes} if chunk_indexes else {chunk.index for chunk in state.chunks}
        for chunk in state.chunks:
            if chunk.index not in selected:
                continue
            for artifact in (chunk.wav_file, chunk.mp3_file):
                path = Path(artifact)
                if path.exists():
                    path.unlink()
            state.chunks[chunk.index - 1] = replace(
                chunk,
                status="pending",
                error="",
                updated_at=utc_now(),
            )
        if reset_output:
            self._delete_export_artifacts(state)
            state.final_output_files = []
            for chapter in state.chapters:
                chapter.output_file = ""
        state.status = "queued"
        state.block_reason = ""
        state.append_log(
            "Retry requested for "
            + ("all chunks" if not chunk_indexes else f"chunks {sorted(selected)}")
        )
        self.save_state(state)
        self.job_logger(state).info(
            "Retry prepared for %s chunk(s); reset_output=%s",
            len(selected),
            reset_output,
        )
        return self.refresh_job_availability(state)

    def apply_preset(self, job_id: str, preset_id: str) -> JobState:
        state = self.load_state(job_id)
        preset = get_preset(preset_id)
        state.preset_id = preset.preset_id
        state.max_chars = preset.max_chars
        state.output_mode = preset.output_mode
        state.target_part_minutes = preset.target_part_minutes
        state.keep_wav = preset.keep_wav
        state.sentence_silence = preset.sentence_silence
        state.length_scale = preset.length_scale
        state.append_log(f"Preset changed to {preset.label}")
        self.save_state(state)
        self.job_logger(state).info("Applied preset %s", preset.preset_id)
        return state

    def enqueue_job(self, job_id: str) -> JobState:
        state = self.load_state(job_id)
        if state.chunks:
            state = self._reconcile_chunk_artifacts(state, logger=self.job_logger(state), append_log=True)
            state = self._catch_up_xtts_deferred_mp3_artifacts(state, logger=self.job_logger(state), append_log=True)
        if state.status not in {"completed"}:
            state.status = "queued"
            state.block_reason = ""
            state.append_log("Job queued manually")
            self.save_state(state)
            self.job_logger(state).info("Job queued manually")
        return self.refresh_job_availability(state)

    def next_queued_job(self) -> JobState | None:
        for job in self.refresh_queue_availability():
            if job.status in {"queued", "prepared"}:
                return job
        return None

    def prepare_job(self, state: JobState) -> JobState:
        job_dir = self.paths.jobs / state.job_id
        logger = self.job_logger(state)
        extracted_path = Path(state.extracted_file)
        if not extracted_path.exists() or not state.chapters:
            extracted_path.parent.mkdir(parents=True, exist_ok=True)
            logger.info("Extracting source text from %s", state.source_file)
            document = extract_document(Path(state.source_file))
            extracted_path.write_text(document.text, encoding="utf-8")
            state.source_characters = len(document.text)
            chapters_dir = extracted_path.parent / "chapters"
            chapters_dir.mkdir(parents=True, exist_ok=True)
            chapters: list[ChapterRecord] = []
            for index, chapter in enumerate(document.chapters or [], start=1):
                chapter_title = chapter.title or f"Kapitel {index:02d}"
                chapter_file = chapters_dir / f"{index:03d}_{_safe_file_component(chapter_title)}.txt"
                chapter_file.write_text(chapter.text, encoding="utf-8")
                chapters.append(
                    ChapterRecord(
                        index=index,
                        title=chapter_title,
                        text_file=str(chapter_file),
                        chunk_start_index=0,
                        chunk_end_index=0,
                    )
                )
            if not chapters and document.text:
                chapter_file = chapters_dir / "001_gesamttext.txt"
                chapter_file.write_text(document.text, encoding="utf-8")
                chapters.append(
                    ChapterRecord(
                        index=1,
                        title="Gesamttext",
                        text_file=str(chapter_file),
                        chunk_start_index=0,
                        chunk_end_index=0,
                    )
                )
            state.chapters = chapters
            state.append_log(f"Extracted source text and detected {len(chapters)} chapter(s)")
            logger.debug("Extracted text length: %s", len(document.text))

        if not state.chunks:
            chunks_dir = job_dir / "chunks"
            chunks_dir.mkdir(parents=True, exist_ok=True)
            chunks: list[ChunkRecord] = []
            chunk_index = 1
            logger.info("Preparing chunks with max_chars=%s across %s chapter(s)", state.max_chars, len(state.chapters))
            for chapter in state.chapters or [
                ChapterRecord(
                    index=1,
                    title="Gesamttext",
                    text_file=str(extracted_path),
                    chunk_start_index=0,
                    chunk_end_index=0,
                )
            ]:
                chapter_text = Path(chapter.text_file).read_text(encoding="utf-8")
                parts = split_text(chapter_text, state.max_chars)
                if not parts:
                    continue
                chapter.chunk_start_index = chunk_index
                for part in parts:
                    text_file = chunks_dir / f"{chunk_index:05d}.txt"
                    wav_file = job_dir / "audio" / "wav" / f"{chunk_index:05d}.wav"
                    mp3_file = job_dir / "audio" / "mp3" / f"{chunk_index:05d}.mp3"
                    text_file.write_text(part, encoding="utf-8")
                    chunks.append(
                        ChunkRecord(
                            index=chunk_index,
                            text_file=str(text_file),
                            wav_file=str(wav_file),
                            mp3_file=str(mp3_file),
                            chapter_index=chapter.index,
                            chapter_title=chapter.title,
                        )
                    )
                    chunk_index += 1
                chapter.chunk_end_index = chunk_index - 1
            state.chunks = chunks
            state.chapters = [chapter for chapter in state.chapters if chapter.chunk_end_index >= chapter.chunk_start_index > 0]
            state.append_log(f"Prepared {len(chunks)} chunk files")
            logger.debug("Chunk manifest prepared")
        state.status = "queued"
        if state.backend == "xtts":
            state.device_mode = self._resolved_xtts_device_mode(load_app_settings(self.paths.app_settings_file).xtts_device_mode)
            state.processing_mode, state.processing_mode_reason = self._select_processing_mode(state)
        else:
            state.device_mode = "cpu"
            state.processing_mode = "serial"
            state.processing_mode_reason = "Piper nutzt den seriellen Standardpfad."
        state = self._update_runtime_estimate(state)
        self.save_state(state)
        return state

    def _handle_runtime_failure(
        self,
        state: JobState,
        exc: Exception,
        *,
        logger: logging.Logger,
    ) -> JobState:
        message = str(exc).strip() or exc.__class__.__name__
        details: dict[str, object] = {}
        category = "job_failure"
        recommended_action = "Prüfe den Jobordner, die Runtime und die Quelldatei."
        auto_recovery_attempted = False
        recovery_result = "Keine automatische Korrektur versucht."
        if state.backend == "xtts":
            runtime_reason = self._xtts_runtime_reason(logger=logger)
            details["xtts_runtime_reason"] = runtime_reason
            if self._should_attempt_xtts_self_heal(f"{runtime_reason}\n{message}"):
                category = "xtts_runtime_incomplete"
                recommended_action = (
                    "XTTS-Runtime prüfen oder den eingebauten XTTS-Setup-Pfad erneut ausführen. "
                    "Bis dahin kann Piper weiter genutzt werden."
                )
                if state.auto_recovery_attempts < 1:
                    state.auto_recovery_attempts += 1
                    auto_recovery_attempted = True
                    repaired, repair_message = self._attempt_xtts_self_heal(logger=logger, detail=f"{runtime_reason}\n{message}")
                    recovery_result = repair_message
                    if repaired:
                        state.status = "queued"
                        state.block_reason = ""
                        state.append_log(f"Automatic XTTS repair succeeded. Job returned to queue: {repair_message}")
                        state = self._write_failure_report(
                            state,
                            category=category,
                            error=message,
                            recovery_result=repair_message,
                            auto_recovery_attempted=True,
                            recommended_action="Keine Aktion nötig. Der Auftrag wurde automatisch erneut eingereiht.",
                            details=details,
                        )
                        self.save_state(state)
                        logger.warning("XTTS runtime repaired automatically for job %s; requeued", state.job_id)
                        return state
                else:
                    auto_recovery_attempted = True
                    recovery_result = "Automatische XTTS-Reparatur wurde bereits versucht."
                state.status = "blocked"
                state.block_reason = f"XTTS-Runtime nicht einsatzbereit: {runtime_reason}"
            elif "potential_endless_loop" in message.lower() or "endless loop" in message.lower():
                category = "potential_endless_loop"
                state.status = "blocked"
                state.block_reason = (
                    "Mögliche Endlosschleife erkannt. Der Auftrag wurde gestoppt, um erneute Überschreibungen oder "
                    "endlose Wiederholungen zu verhindern."
                )
                recommended_action = "Prüfe den Fehlerbericht und starte den Auftrag erst nach Korrektur erneut."
        state = self._write_failure_report(
            state,
            category=category,
            error=message,
            recovery_result=recovery_result,
            auto_recovery_attempted=auto_recovery_attempted,
            recommended_action=recommended_action,
            details=details,
        )
        self.save_state(state)
        logger.error("Structured failure report written for job %s: %s", state.job_id, state.failure_report_file)
        return state

    def run_job(
        self,
        state: JobState,
        should_stop: callable | None = None,
        progress: callable | None = None,
    ) -> JobState:
        logger = self.job_logger(state)
        if state.chunks:
            state = self._reconcile_chunk_artifacts(
                state,
                logger=logger,
                append_log=state.status in {"failed", "stopped", "running"},
            )
            state = self._catch_up_xtts_deferred_mp3_artifacts(
                state,
                logger=logger,
                append_log=state.status in {"failed", "stopped", "running"},
            )
        state = self.refresh_job_availability(state)
        if state.status == "blocked":
            logger.warning("Skipping blocked job %s: %s", state.job_id, state.block_reason)
            return state
        state = self.prepare_job(state)
        if state.backend == "piper":
            backend = PiperBackend(self.paths.runtime, self.paths.voices, logger=logger)
        elif state.backend == "xtts":
            backend = self._xtts_backend(logger=logger)
        else:
            raise ValueError(f"Unsupported backend: {state.backend}")

        try:
            run_started = time.perf_counter()
            synthesis_started = run_started
            state.block_reason = ""
            state.status = "running"
            state.processing_started_at = utc_now()
            if state.backend == "xtts":
                state.device_mode = self._resolved_xtts_device_mode(
                    load_app_settings(self.paths.app_settings_file).xtts_device_mode,
                    logger=logger,
                )
                state.processing_mode, state.processing_mode_reason = self._select_processing_mode(state, logger=logger)
            else:
                state.device_mode = "cpu"
                state.processing_mode = "serial"
                state.processing_mode_reason = "Piper nutzt den seriellen Standardpfad."
            state = self._update_runtime_estimate(state)
            self.save_state(state)
            logger.info(
                "Starting queued job with %s chunks, priority=%s, output_mode=%s, preset=%s, device_mode=%s, processing_mode=%s",
                len(state.chunks),
                state.priority,
                state.output_mode,
                state.preset_id,
                state.device_mode,
                state.processing_mode,
            )
            xtts_profile = None
            xtts_defer_mp3 = self._xtts_should_defer_mp3(state)
            xtts_parallel_postprocess = False
            postprocess_executor: concurrent.futures.ThreadPoolExecutor | None = None
            postprocess_futures: list[concurrent.futures.Future[None]] = []
            if state.backend == "xtts":
                xtts_profile = load_voice_profile(self.paths.voice_profiles, state.voice_profile_id)
                batch_limit, char_limit = self._xtts_batch_parameters(state)
                xtts_parallel_postprocess = state.processing_mode == "parallel_cpu_postprocess"
                if xtts_parallel_postprocess:
                    postprocess_executor = concurrent.futures.ThreadPoolExecutor(
                        max_workers=self._xtts_postprocess_workers(),
                        thread_name_prefix="xtts-postprocess",
                    )
                logger.info(
                    "XTTS batching enabled with batch_limit=%s char_limit=%s defer_mp3=%s parallel_postprocess=%s",
                    batch_limit,
                    char_limit,
                    xtts_defer_mp3,
                    xtts_parallel_postprocess,
                )
            if state.backend == "xtts":
                try:
                    loop_guard: dict[str, int] = {}
                    while True:
                        pending_chunks = [
                            candidate
                            for candidate in state.chunks
                            if self._xtts_chunk_needs_processing(candidate, defer_mp3=xtts_defer_mp3)
                        ]
                        if not pending_chunks:
                            break
                        batch = self._select_xtts_batch(state, pending_chunks)
                        first_chunk = batch[0]
                        if should_stop and should_stop():
                            state.status = "stopped"
                            state.append_log("Stop requested by user")
                            self.save_state(state)
                            logger.warning("Stop requested before chunk %s", first_chunk.index)
                            raise StopRequested()
                        try:
                            loop_key = f"{first_chunk.index}:{batch[-1].index}:{state.completed_chunks}"
                            loop_guard[loop_key] = loop_guard.get(loop_key, 0) + 1
                            if loop_guard[loop_key] >= 3:
                                raise RuntimeError(
                                    f"Potential endless loop detected for XTTS batch {first_chunk.index}-{batch[-1].index} "
                                    f"without progress (completed_chunks={state.completed_chunks})."
                                )
                            texts = [Path(item.text_file).read_text(encoding="utf-8") for item in batch]
                            wav_paths = [Path(item.wav_file) for item in batch]
                            logger.info(
                                "Processing XTTS batch starting at chunk %s with %s chunk(s)",
                                first_chunk.index,
                                len(batch),
                            )
                            backend.synthesize_many_to_wavs(
                                texts,
                                xtts_profile,
                                wav_paths,
                                length_scale=state.length_scale,
                            )
                            if xtts_parallel_postprocess and postprocess_executor is not None:
                                logger.info(
                                    "Dispatching XTTS CPU postprocess for batch %s-%s while GPU continues",
                                    batch[0].index,
                                    batch[-1].index,
                                )
                                postprocess_futures.append(
                                    postprocess_executor.submit(
                                        self._convert_xtts_batch_to_mp3,
                                        list(batch),
                                        keep_wav=state.keep_wav,
                                        logger=logger,
                                    )
                                )
                            for item in batch:
                                if not xtts_defer_mp3:
                                    wav_to_mp3(Path(item.wav_file), Path(item.mp3_file), logger=logger)
                                    if not state.keep_wav and Path(item.wav_file).exists():
                                        Path(item.wav_file).unlink()
                                        logger.debug("Removed intermediate WAV %s", item.wav_file)
                                state.chunks[item.index - 1] = replace(
                                    item,
                                    status="done",
                                    error="",
                                    updated_at=utc_now(),
                                )
                                state = self._update_runtime_progress(state, started_monotonic=run_started)
                                state.append_log(f"Processed chunk {item.index}/{len(state.chunks)}")
                            self.save_state(state)
                            loop_guard.clear()
                            if progress:
                                progress(
                                    batch[-1].index,
                                    len(state.chunks),
                                    f"XTTS batch {batch[0].index}-{batch[-1].index} finished",
                                )
                        except Exception as exc:
                            logger.exception("Chunk %s failed", first_chunk.index)
                            state.chunks[first_chunk.index - 1] = replace(
                                first_chunk,
                                status="failed",
                                error=str(exc),
                                updated_at=utc_now(),
                            )
                            state.status = "failed"
                            state.append_log(f"Chunk {first_chunk.index} failed: {exc}")
                            self.save_state(state)
                            raise
                finally:
                    if postprocess_executor is not None:
                        postprocess_executor.shutdown(wait=False)
                if xtts_parallel_postprocess and postprocess_futures:
                    logger.info("Waiting for %s XTTS CPU postprocess task(s)", len(postprocess_futures))
                    try:
                        for future in postprocess_futures:
                            future.result()
                    except Exception as exc:
                        logger.exception("XTTS CPU postprocess failed")
                        state.status = "failed"
                        state.append_log(f"XTTS CPU postprocess failed: {exc}")
                        self.save_state(state)
                        raise
                    state = self._catch_up_xtts_deferred_mp3_artifacts(state, logger=logger, append_log=True)
                    xtts_defer_mp3 = False
            else:
                for idx, chunk in enumerate(state.chunks, start=1):
                    if should_stop and should_stop():
                        state.status = "stopped"
                        state.append_log("Stop requested by user")
                        self.save_state(state)
                        logger.warning("Stop requested before chunk %s", chunk.index)
                        raise StopRequested()
                    if chunk.status == "done" and Path(chunk.mp3_file).exists():
                        logger.debug("Skipping completed chunk %s", chunk.index)
                        if progress:
                            progress(idx, len(state.chunks), f"Skipping completed chunk {chunk.index}")
                        continue

                    try:
                        text = Path(chunk.text_file).read_text(encoding="utf-8")
                        logger.info("Processing chunk %s/%s", chunk.index, len(state.chunks))
                        logger.debug("Chunk source file: %s", chunk.text_file)
                        logger.debug("Chunk output wav: %s", chunk.wav_file)
                        logger.debug("Chunk output mp3: %s", chunk.mp3_file)
                        backend.synthesize_to_wav(
                            text,
                            state.voice_id,
                            Path(chunk.wav_file),
                            sentence_silence=state.sentence_silence,
                            length_scale=state.length_scale,
                        )
                        wav_to_mp3(Path(chunk.wav_file), Path(chunk.mp3_file), logger=logger)
                        if not state.keep_wav and Path(chunk.wav_file).exists():
                            Path(chunk.wav_file).unlink()
                            logger.debug("Removed intermediate WAV %s", chunk.wav_file)
                        state.chunks[chunk.index - 1] = replace(
                            chunk,
                            status="done",
                            error="",
                            updated_at=utc_now(),
                        )
                        state = self._update_runtime_progress(state, started_monotonic=run_started)
                        state.append_log(f"Processed chunk {chunk.index}/{len(state.chunks)}")
                        self.save_state(state)
                        if progress:
                            progress(idx, len(state.chunks), f"Chunk {chunk.index} finished")
                    except Exception as exc:
                        logger.exception("Chunk %s failed", chunk.index)
                        state.chunks[chunk.index - 1] = replace(
                            chunk,
                            status="failed",
                            error=str(exc),
                            updated_at=utc_now(),
                        )
                        state.status = "failed"
                        state.append_log(f"Chunk {chunk.index} failed: {exc}")
                        self.save_state(state)
                        raise

            synthesis_finished = time.perf_counter()
            missing_audio_chunks = self._missing_text_audio_chunks(state)
            if missing_audio_chunks:
                preview = ", ".join(str(index) for index in missing_audio_chunks[:12])
                raise RuntimeError(
                    "Missing audio artifacts for text-bearing chunk(s): "
                    f"{preview}"
                    + (" ..." if len(missing_audio_chunks) > 12 else "")
                )
            state.final_output_files = []
            for chapter in state.chapters:
                chapter.output_file = ""
            mp3_files = [Path(chunk.mp3_file) for chunk in state.chunks if Path(chunk.mp3_file).exists()]
            if xtts_defer_mp3:
                assembly_inputs = [Path(chunk.wav_file) for chunk in state.chunks if Path(chunk.wav_file).exists()]
            else:
                assembly_inputs = mp3_files
            if state.output_mode == "single_file":
                if assembly_inputs:
                    logger.info("Concatenating %s audio files into final output", len(assembly_inputs))
                    if xtts_defer_mp3:
                        concat_audio_files_to_mp3(assembly_inputs, Path(state.final_output_file), logger=logger)
                    else:
                        concat_mp3_files(assembly_inputs, Path(state.final_output_file), logger=logger)
                    state.final_output_files = [state.final_output_file]
                    state.append_log("Created one final MP3 file")
            elif state.output_mode == "chapter_files":
                state.final_output_files = self._chapter_output_files(state, logger, prefer_wav=xtts_defer_mp3)
                state.append_log(f"Created {len(state.final_output_files)} chapter MP3 file(s)")
            elif state.output_mode == "timed_parts":
                if assembly_inputs:
                    output_dir = Path(state.final_output_file).parent
                    output_dir.mkdir(parents=True, exist_ok=True)
                    master_mp3 = output_dir / f"{Path(state.final_output_file).stem}__full.mp3"
                    logger.info("Creating temporary master MP3 for timed split")
                    if xtts_defer_mp3:
                        concat_audio_files_to_mp3(assembly_inputs, master_mp3, logger=logger)
                    else:
                        concat_mp3_files(assembly_inputs, master_mp3, logger=logger)
                    part_pattern = output_dir / f"{Path(state.final_output_file).stem}_part_%03d.mp3"
                    part_files = segment_mp3_file(
                        master_mp3,
                        part_pattern,
                        max(60, state.target_part_minutes * 60),
                        logger=logger,
                    )
                    state.final_output_files = [str(path) for path in part_files]
                    if master_mp3.exists():
                        master_mp3.unlink()
                    state.append_log(
                        f"Created {len(part_files)} final MP3 parts with target length {state.target_part_minutes} minutes"
                    )
            else:
                state.final_output_files = [str(path) for path in mp3_files]
                state.append_log("Keeping per-chunk MP3 files as final output")

            assembly_finished = time.perf_counter()
            self._finalize_outputs(state, logger)
            if xtts_defer_mp3 and not state.keep_wav:
                self._cleanup_intermediate_wavs(state, logger)
            state.status = "completed"
            state.actual_total_seconds = round(max(0.0, time.perf_counter() - run_started), 3)
            state.estimated_remaining_seconds = 0.0
            state.processing_completed_at = utc_now()
            self.save_state(state)
            record_runtime_stat(
                self.paths.runtime_stats_file,
                {
                    "recorded_at": utc_now(),
                    "job_id": state.job_id,
                    "title": state.title,
                    "backend": state.backend,
                    "saved_profile_id": state.saved_profile_id,
                    "voice_id": state.voice_id,
                    "voice_profile_id": state.voice_profile_id,
                    "device_mode": state.device_mode,
                    "processing_mode": state.processing_mode,
                    "output_mode": state.output_mode,
                    "source_characters": state.source_characters,
                    "chunk_count": state.total_chunks,
                    "chapter_count": len(state.chapters),
                    "total_duration_seconds": state.actual_total_seconds,
                    "synthesis_duration_seconds": round(max(0.0, synthesis_finished - synthesis_started), 3),
                    "assembly_duration_seconds": round(max(0.0, assembly_finished - synthesis_finished), 3),
                    "estimated_total_seconds": state.estimated_total_seconds,
                },
            )
            logger.info("Job completed successfully")
            return state
        except StopRequested:
            raise
        except Exception as exc:
            return self._handle_runtime_failure(state, exc, logger=logger)

    def _delete_export_artifacts(self, state: JobState) -> None:
        paths = {
            state.final_output_file,
            state.manifest_file,
            state.chapters_file,
            *state.final_output_files,
            *(chapter.output_file for chapter in state.chapters),
        }
        for path_str in paths:
            if not path_str:
                continue
            path = Path(path_str)
            if path.exists():
                path.unlink()

    def _chapter_output_files(self, state: JobState, logger: logging.Logger, *, prefer_wav: bool = False) -> list[str]:
        output_dir = Path(state.final_output_file).parent
        output_dir.mkdir(parents=True, exist_ok=True)
        output_stem = Path(state.final_output_file).stem
        output_files: list[str] = []
        for chapter in state.chapters:
            chapter_audio_files = []
            for chunk in state.chunks:
                if chunk.chapter_index != chapter.index:
                    continue
                if prefer_wav and Path(chunk.wav_file).exists():
                    chapter_audio_files.append(Path(chunk.wav_file))
                elif Path(chunk.mp3_file).exists():
                    chapter_audio_files.append(Path(chunk.mp3_file))
            if not chapter_audio_files:
                chapter.output_file = ""
                continue
            chapter_slug = _safe_file_component(chapter.title)[:48]
            chapter_output = output_dir / f"{output_stem}_chapter_{chapter.index:03d}_{chapter_slug}.mp3"
            logger.info(
                "Concatenating %s audio files for chapter %s into %s",
                len(chapter_audio_files),
                chapter.index,
                chapter_output.name,
            )
            if prefer_wav:
                concat_audio_files_to_mp3(chapter_audio_files, chapter_output, logger=logger)
            else:
                concat_mp3_files(chapter_audio_files, chapter_output, logger=logger)
            chapter.output_file = str(chapter_output)
            output_files.append(str(chapter_output))
        return output_files

    def _build_output_metadata(
        self,
        state: JobState,
        output_path: Path,
        index: int,
        total: int,
        *,
        chapter: ChapterRecord | None = None,
    ) -> dict[str, str]:
        meta = state.audiobook_metadata
        if state.output_mode == "chapter_files" and chapter:
            title = meta.title if chapter.title == "Gesamttext" else f"{meta.title} - {chapter.title}"
        elif total == 1:
            title = meta.title
        elif state.output_mode == "timed_parts":
            title = f"{meta.title} - Teil {index:02d}"
        elif state.output_mode == "segments":
            title = f"{meta.title} - Segment {index:03d}"
        else:
            title = f"{meta.title} - Datei {index:02d}"
        return {
            "title": title,
            "album": meta.album or meta.title,
            "artist": meta.artist or meta.narrator,
            "album_artist": meta.album_artist or meta.artist or meta.narrator,
            "performer": meta.narrator or meta.artist,
            "author": meta.author,
            "genre": meta.genre,
            "language": meta.language,
            "comment": meta.comment,
            "track": f"{index}/{total}",
        }

    def _chunk_timeline(self, state: JobState, logger: logging.Logger) -> list[dict[str, object]]:
        timeline: list[dict[str, object]] = []
        current_ms = 0
        for chunk in state.chunks:
            chunk_path = self._chunk_audio_path(chunk)
            if chunk_path is None:
                continue
            duration_seconds = probe_media_duration_seconds(chunk_path, logger=logger)
            duration_ms = int(round(duration_seconds * 1000))
            timeline.append(
                {
                    "index": chunk.index,
                    "title": f"Abschnitt {chunk.index:03d}",
                    "text_file": chunk.text_file,
                    "mp3_file": chunk.mp3_file,
                    "audio_file": str(chunk_path),
                    "chapter_index": chunk.chapter_index,
                    "chapter_title": chunk.chapter_title,
                    "start_ms": current_ms,
                    "end_ms": current_ms + duration_ms,
                    "duration_seconds": round(duration_seconds, 3),
                }
            )
            current_ms += duration_ms
        return timeline

    def _chapter_timeline(
        self,
        state: JobState,
        chunk_timeline: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        if not chunk_timeline:
            return []
        timeline_by_index = {int(entry["index"]): entry for entry in chunk_timeline}
        chapters: list[dict[str, object]] = []
        for chapter in state.chapters:
            first_chunk = timeline_by_index.get(chapter.chunk_start_index)
            last_chunk = timeline_by_index.get(chapter.chunk_end_index)
            if not first_chunk or not last_chunk:
                continue
            start_ms = int(first_chunk["start_ms"])
            end_ms = int(last_chunk["end_ms"])
            chapters.append(
                {
                    "index": chapter.index,
                    "title": chapter.title,
                    "text_file": chapter.text_file,
                    "output_file": chapter.output_file,
                    "chunk_start_index": chapter.chunk_start_index,
                    "chunk_end_index": chapter.chunk_end_index,
                    "start_ms": start_ms,
                    "end_ms": end_ms,
                    "duration_seconds": round((end_ms - start_ms) / 1000, 3),
                }
            )
        return chapters

    def _write_output_manifests(
        self,
        state: JobState,
        logger: logging.Logger,
        outputs: list[dict[str, object]],
        chunk_timeline: list[dict[str, object]],
        chapter_timeline: list[dict[str, object]],
    ) -> None:
        manifest_path = Path(state.manifest_file)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest = {
            "job_id": state.job_id,
            "title": state.title,
            "status": "completed",
            "backend": state.backend,
            "voice_id": state.voice_id,
            "voice_profile_id": state.voice_profile_id,
            "preset_id": state.preset_id,
            "output_mode": state.output_mode,
            "target_part_minutes": state.target_part_minutes,
            "source_file": state.source_file,
            "audiobook_metadata": state.audiobook_metadata.to_dict(),
            "outputs": outputs,
            "chunk_count": state.total_chunks,
            "chapter_count": len(chapter_timeline) or len(state.chapters),
        }
        chapters_payload = {
            "job_id": state.job_id,
            "title": state.audiobook_metadata.title,
            "timeline_kind": "chapter" if chapter_timeline else "chunk",
            "entries": chapter_timeline or chunk_timeline,
            "chunk_entries": chunk_timeline,
        }
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        Path(state.chapters_file).write_text(
            json.dumps(chapters_payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info("Wrote output manifest %s and chapter timeline %s", state.manifest_file, state.chapters_file)

    def _finalize_outputs(self, state: JobState, logger: logging.Logger) -> None:
        output_paths = [Path(path) for path in state.final_output_files if Path(path).exists()]
        if not output_paths:
            return
        chunk_timeline = self._chunk_timeline(state, logger)
        chapter_timeline = self._chapter_timeline(state, chunk_timeline)
        chapter_by_output = {chapter.output_file: chapter for chapter in state.chapters if chapter.output_file}
        outputs: list[dict[str, object]] = []
        total = len(output_paths)
        for index, output_path in enumerate(output_paths, start=1):
            chapter = chapter_by_output.get(str(output_path))
            metadata = self._build_output_metadata(state, output_path, index, total, chapter=chapter)
            embedded_chapters = chapter_timeline if state.output_mode == "single_file" and index == 1 else None
            apply_mp3_metadata_in_place(output_path, metadata, logger=logger, chapters=embedded_chapters)
            duration_seconds = probe_media_duration_seconds(output_path, logger=logger)
            output_entry = {
                "index": index,
                "path": str(output_path),
                "file_name": output_path.name,
                "kind": state.output_mode,
                "track_number": index,
                "track_total": total,
                "duration_seconds": round(duration_seconds, 3),
            }
            if chapter:
                output_entry["chapter_index"] = chapter.index
                output_entry["chapter_title"] = chapter.title
            outputs.append(output_entry)
        self._write_output_manifests(state, logger, outputs, chunk_timeline, chapter_timeline)
        state.append_log("Applied MP3 metadata and wrote export manifests")

    def _cleanup_intermediate_wavs(self, state: JobState, logger: logging.Logger) -> None:
        for chunk in state.chunks:
            wav_path = Path(chunk.wav_file)
            if wav_path.exists():
                wav_path.unlink()
                logger.debug("Removed deferred XTTS WAV %s", wav_path)

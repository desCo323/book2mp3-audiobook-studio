from __future__ import annotations

import concurrent.futures
import json
import os
import re
import shutil
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
            if job.status == "running":
                job.status = "queued"
                job.append_log("Recovered running job after restart and returned it to the queue")
                self.save_state(job)
                self.job_logger(job).warning("Recovered interrupted running job after restart")
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
        self.save_state(state)
        return state

    def run_job(
        self,
        state: JobState,
        should_stop: callable | None = None,
        progress: callable | None = None,
    ) -> JobState:
        logger = self.job_logger(state)
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

        state.block_reason = ""
        state.status = "running"
        self.save_state(state)
        logger.info(
            "Starting queued job with %s chunks, priority=%s, output_mode=%s, preset=%s",
            len(state.chunks),
            state.priority,
            state.output_mode,
            state.preset_id,
        )
        xtts_profile = None
        xtts_defer_mp3 = self._xtts_should_defer_mp3(state)
        xtts_parallel_postprocess = False
        postprocess_executor: concurrent.futures.ThreadPoolExecutor | None = None
        postprocess_futures: list[concurrent.futures.Future[None]] = []
        if state.backend == "xtts":
            xtts_profile = load_voice_profile(self.paths.voice_profiles, state.voice_profile_id)
            batch_limit, char_limit = self._xtts_batch_parameters(state)
            xtts_parallel_postprocess = self._xtts_should_parallel_postprocess(state)
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
                while True:
                    pending_chunks = [
                        candidate
                        for candidate in state.chunks
                        if candidate.status != "done"
                        or (
                            xtts_defer_mp3
                            and not Path(candidate.wav_file).exists()
                        )
                        or (
                            not xtts_defer_mp3
                            and not Path(candidate.mp3_file).exists()
                        )
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
                            state.append_log(f"Processed chunk {item.index}/{len(state.chunks)}")
                        self.save_state(state)
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

        self._finalize_outputs(state, logger)
        if xtts_defer_mp3 and not state.keep_wav:
            self._cleanup_intermediate_wavs(state, logger)
        state.status = "completed"
        self.save_state(state)
        logger.info("Job completed successfully")
        return state

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

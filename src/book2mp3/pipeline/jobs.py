from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import replace
from pathlib import Path
import logging

from book2mp3.config import AppPaths
from book2mp3.models import ChunkRecord, JobState, utc_now
from book2mp3.pipeline.audio import concat_mp3_files, wav_to_mp3
from book2mp3.pipeline.chunking import split_text
from book2mp3.pipeline.extract import extract_text
from book2mp3.presets import get_preset
from book2mp3.tts.piper import PiperBackend
from book2mp3.tts.xtts import XttsBackend
from book2mp3.utils.logging_utils import attach_job_file_logger, get_logger
from book2mp3.voice_lab import load_voice_profile


class StopRequested(Exception):
    pass


class JobManager:
    def __init__(self, paths: AppPaths) -> None:
        self.paths = paths
        self.paths.ensure()
        self.logger = get_logger("jobs")

    def job_logger(self, state: JobState) -> logging.Logger:
        logger = attach_job_file_logger(state.job_id, self.paths.jobs / state.job_id)
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
        keep_wav: bool,
        sentence_silence: float,
        length_scale: float,
        backend: str = "piper",
    ) -> JobState:
        job_id = uuid.uuid4().hex[:12]
        job_dir = self.paths.jobs / job_id
        input_dir = job_dir / "input"
        input_dir.mkdir(parents=True, exist_ok=True)
        target_source = input_dir / source_path.name
        shutil.copy2(source_path, target_source)
        self.logger.info("Creating job for source %s", source_path)

        title = source_path.stem
        state = JobState(
            job_id=job_id,
            title=title,
            source_name=source_path.name,
            source_type=source_path.suffix.lower().lstrip("."),
            created_at=utc_now(),
            updated_at=utc_now(),
            status="queued",
            backend=backend,
            voice_id=voice_id,
            voice_profile_id=voice_profile_id,
            preset_id=preset_id,
            priority=priority,
            output_mode=output_mode,
            keep_wav=keep_wav,
            max_chars=max_chars,
            sentence_silence=sentence_silence,
            length_scale=length_scale,
            source_file=str(target_source),
            extracted_file=str(job_dir / "extracted" / "source.txt"),
            final_output_file=str(job_dir / "output" / f"{title}.mp3"),
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
                0 if item.status in {"running", "queued", "prepared"} else 1,
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

    def update_priority(self, job_id: str, priority: int) -> JobState:
        state = self.load_state(job_id)
        state.priority = priority
        state.append_log(f"Priority changed to {priority}")
        self.save_state(state)
        self.job_logger(state).info("Priority updated to %s", priority)
        return state

    def apply_preset(self, job_id: str, preset_id: str) -> JobState:
        state = self.load_state(job_id)
        preset = get_preset(preset_id)
        state.preset_id = preset.preset_id
        state.max_chars = preset.max_chars
        state.output_mode = preset.output_mode
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
            state.append_log("Job queued manually")
            self.save_state(state)
            self.job_logger(state).info("Job queued manually")
        return state

    def next_queued_job(self) -> JobState | None:
        queued = [
            job
            for job in self.list_jobs()
            if job.status in {"queued", "prepared"}
        ]
        return queued[0] if queued else None

    def prepare_job(self, state: JobState) -> JobState:
        job_dir = self.paths.jobs / state.job_id
        logger = self.job_logger(state)
        extracted_path = Path(state.extracted_file)
        if not extracted_path.exists():
            extracted_path.parent.mkdir(parents=True, exist_ok=True)
            logger.info("Extracting source text from %s", state.source_file)
            text = extract_text(Path(state.source_file))
            extracted_path.write_text(text, encoding="utf-8")
            state.append_log("Extracted source text")
            logger.debug("Extracted text length: %s", len(text))

        if not state.chunks:
            chunks_dir = job_dir / "chunks"
            chunks_dir.mkdir(parents=True, exist_ok=True)
            text = extracted_path.read_text(encoding="utf-8")
            parts = split_text(text, state.max_chars)
            logger.info("Preparing %s chunks with max_chars=%s", len(parts), state.max_chars)
            chunks: list[ChunkRecord] = []
            for index, part in enumerate(parts, start=1):
                text_file = chunks_dir / f"{index:05d}.txt"
                wav_file = job_dir / "audio" / "wav" / f"{index:05d}.wav"
                mp3_file = job_dir / "audio" / "mp3" / f"{index:05d}.mp3"
                text_file.write_text(part, encoding="utf-8")
                chunks.append(
                    ChunkRecord(
                        index=index,
                        text_file=str(text_file),
                        wav_file=str(wav_file),
                        mp3_file=str(mp3_file),
                    )
                )
            state.chunks = chunks
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
        state = self.prepare_job(state)
        logger = self.job_logger(state)
        if state.backend == "piper":
            backend = PiperBackend(self.paths.runtime, self.paths.voices, logger=logger)
        elif state.backend == "xtts":
            backend = XttsBackend(self.paths.runtime, logger=logger)
        else:
            raise ValueError(f"Unsupported backend: {state.backend}")

        state.status = "running"
        self.save_state(state)
        logger.info(
            "Starting queued job with %s chunks, priority=%s, output_mode=%s, preset=%s",
            len(state.chunks),
            state.priority,
            state.output_mode,
            state.preset_id,
        )
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
                if state.backend == "piper":
                    backend.synthesize_to_wav(
                        text,
                        state.voice_id,
                        Path(chunk.wav_file),
                        sentence_silence=state.sentence_silence,
                        length_scale=state.length_scale,
                    )
                else:
                    profile = load_voice_profile(self.paths.voice_profiles, state.voice_profile_id)
                    backend.synthesize_to_wav(
                        text,
                        profile,
                        Path(chunk.wav_file),
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

        if state.output_mode == "single_file":
            mp3_files = [Path(chunk.mp3_file) for chunk in state.chunks if Path(chunk.mp3_file).exists()]
            if mp3_files:
                logger.info("Concatenating %s MP3 files into final output", len(mp3_files))
                concat_mp3_files(mp3_files, Path(state.final_output_file), logger=logger)
                state.append_log("Created concatenated output")

        state.status = "completed"
        self.save_state(state)
        logger.info("Job completed successfully")
        return state

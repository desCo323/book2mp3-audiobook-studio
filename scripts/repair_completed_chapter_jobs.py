from __future__ import annotations

import argparse
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from book2mp3.config import AppPaths
from book2mp3.models import JobState, utc_now
from book2mp3.pipeline.audio import probe_media_duration_seconds
from book2mp3.pipeline.jobs import JobManager
from book2mp3.utils.logging_utils import configure_logging


RECHUNK_MARKER = "Rechunking job because existing chunk files exceeded XTTS safety"
METADATA_MARKER = "Applied MP3 metadata and wrote export manifests"
CREATED_CHAPTER_RE = re.compile(r"Created\s+(\d+)\s+chapter MP3 file\(s\)")
PROCESSED_BATCH_RE = re.compile(r"Processed XTTS batch\s+(\d+)-(\d+)")
CHAPTER_FILE_RE = re.compile(r"_chapter_(\d{3,})_")


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def mp3_signature_ok(path: Path) -> bool:
    header = path.read_bytes()[:4]
    return header.startswith(b"ID3") or (len(header) >= 2 and header[0] == 0xFF and (header[1] & 0xE0) == 0xE0)


def created_chapter_count(state: JobState) -> int | None:
    matches = [CREATED_CHAPTER_RE.search(line) for line in state.logs]
    counts = [int(match.group(1)) for match in matches if match]
    return counts[-1] if counts else None


def inferred_total_chunks(state: JobState) -> int:
    last_end = 0
    for line in state.logs:
        match = PROCESSED_BATCH_RE.search(line)
        if match:
            last_end = max(last_end, int(match.group(2)))
    return last_end


def output_mp3s_by_chapter(output_dir: Path) -> dict[int, Path]:
    result: dict[int, Path] = {}
    for path in sorted(output_dir.glob("*.mp3")):
        match = CHAPTER_FILE_RE.search(path.name)
        if not match:
            continue
        result[int(match.group(1))] = path
    return result


def repairable_reason(state: JobState, output_dir: Path) -> tuple[bool, str]:
    if state.status == "completed":
        return False, "already completed"
    if state.output_mode != "chapter_files":
        return False, f"output mode is {state.output_mode!r}"
    if state.chunks:
        return False, f"state still has {len(state.chunks)} chunk records"
    if not state.chapters:
        return False, "state has no chapter records"
    logs = "\n".join(state.logs)
    if RECHUNK_MARKER not in logs:
        return False, "missing startup-rechunk marker"
    if METADATA_MARKER not in logs:
        return False, "missing previous metadata/manifests completion marker"
    created_count = created_chapter_count(state)
    if created_count != len(state.chapters):
        return False, f"created-chapter log count {created_count} does not match {len(state.chapters)} chapters"
    by_chapter = output_mp3s_by_chapter(output_dir)
    chapter_indexes = {chapter.index for chapter in state.chapters}
    if set(by_chapter) != chapter_indexes:
        return False, f"output MP3 chapter indexes do not match state chapters ({len(by_chapter)} files)"
    bad = [path.name for path in by_chapter.values() if not mp3_signature_ok(path)]
    if bad:
        return False, f"{len(bad)} MP3 file(s) have unexpected signatures"
    return True, "repairable"


def backup_state(paths: AppPaths, state: JobState, backup_root: Path) -> Path:
    source = paths.jobs / state.job_id / "state.json"
    target = backup_root / state.job_id / "state.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return target


def repair_state(
    manager: JobManager,
    state: JobState,
    backup_root: Path,
    *,
    apply: bool,
) -> dict[str, object]:
    output_dir = Path(state.final_output_file).parent
    ok, reason = repairable_reason(state, output_dir)
    if not ok:
        return {
            "job_id": state.job_id,
            "title": state.title,
            "status": state.status,
            "action": "skipped",
            "reason": reason,
        }

    by_chapter = output_mp3s_by_chapter(output_dir)
    output_paths = [by_chapter[chapter.index] for chapter in sorted(state.chapters, key=lambda item: item.index)]
    byte_total = sum(path.stat().st_size for path in output_paths)
    chunk_total = inferred_total_chunks(state)

    if not apply:
        return {
            "job_id": state.job_id,
            "title": state.title,
            "status": state.status,
            "action": "would_repair",
            "outputs": len(output_paths),
            "bytes": byte_total,
            "inferred_chunks": chunk_total,
        }

    backup_path = backup_state(manager.paths, state, backup_root)
    logger = manager.job_logger(state)

    current_ms = 0
    outputs: list[dict[str, object]] = []
    chapter_timeline: list[dict[str, object]] = []
    total = len(output_paths)
    for index, chapter in enumerate(sorted(state.chapters, key=lambda item: item.index), start=1):
        output_path = by_chapter[chapter.index]
        chapter.output_file = str(output_path)
        duration_seconds = probe_media_duration_seconds(output_path, logger=logger)
        duration_ms = int(round(duration_seconds * 1000))
        outputs.append(
            {
                "index": index,
                "path": str(output_path),
                "file_name": output_path.name,
                "kind": state.output_mode,
                "track_number": index,
                "track_total": total,
                "duration_seconds": round(duration_seconds, 3),
                "chapter_index": chapter.index,
                "chapter_title": chapter.title,
            }
        )
        chapter_timeline.append(
            {
                "index": chapter.index,
                "title": chapter.title,
                "text_file": chapter.text_file,
                "output_file": chapter.output_file,
                "chunk_start_index": chapter.chunk_start_index,
                "chunk_end_index": chapter.chunk_end_index,
                "start_ms": current_ms,
                "end_ms": current_ms + duration_ms,
                "duration_seconds": round(duration_seconds, 3),
            }
        )
        current_ms += duration_ms

    state.final_output_files = [str(path) for path in output_paths]
    state.status = "completed"
    state.block_reason = ""
    state.estimated_remaining_seconds = 0.0
    state.cached_total_chunks = chunk_total
    state.cached_completed_chunks = chunk_total
    state.cached_failed_chunks = 0
    if not state.processing_completed_at:
        state.processing_completed_at = utc_now()
    manager._write_output_manifests(state, logger, outputs, [], chapter_timeline)
    manager._sync_final_books_outputs(state, logger)
    state.append_log(
        f"Recovered completed chapter-file job from existing output MP3 files after startup rechunk regression (outputs={len(output_paths)})"
    )
    manager.save_state(state)

    return {
        "job_id": state.job_id,
        "title": state.title,
        "status": state.status,
        "action": "repaired",
        "outputs": len(output_paths),
        "bytes": byte_total,
        "inferred_chunks": chunk_total,
        "backup": str(backup_path),
        "final_books": str(manager.final_books_directory(state)),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="write repaired job state/manifests and finalbooks mirrors")
    args = parser.parse_args()

    root = project_root()
    paths = AppPaths.from_project_root(root)
    paths.ensure()
    configure_logging(paths.logs)
    manager = JobManager(paths)
    backup_root = paths.workspace / "repair_backups" / (
        "completed_chapter_jobs_" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    )

    results = [
        repair_state(manager, manager.load_state(summary.job_id), backup_root, apply=args.apply)
        for summary in manager.list_jobs()
        if summary.status != "completed"
    ]
    print(json.dumps(results, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

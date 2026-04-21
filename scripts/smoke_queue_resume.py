from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from pathlib import Path

from book2mp3.config import AppPaths
from book2mp3.pipeline.jobs import JobManager
from book2mp3.presets import get_preset
from book2mp3.utils.logging_utils import configure_logging


SMOKE_TEXT = """
Kapitel Eins. Dies ist ein kurzer Stop-und-Resume-Test fuer die Queue.
Die Anwendung soll kleine Abschnitte erzeugen, stoppen, den Zustand speichern und spaeter fortsetzen.
Kapitel Zwei. Danach muss der Job an derselben Stelle wieder anlaufen.
Kapitel Drei. Zum Schluss pruefen wir die Prioritaet der Queue.
""" * 10


def make_source_file(root: Path) -> Path:
    source = root / "smoke_resume_source.txt"
    source.write_text(SMOKE_TEXT, encoding="utf-8")
    return source


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--voice", default="de_DE-eva_k-x_low")
    parser.add_argument("--preset", default="fast_cpu")
    args = parser.parse_args()

    root = Path(tempfile.mkdtemp(prefix="book2mp3_smoke_"))
    shutil.copytree("/home/codex/repo/book2mp3/runtime", root / "runtime")
    shutil.copytree("/home/codex/repo/book2mp3/voices", root / "voices")
    paths = AppPaths.from_project_root(root)
    paths.ensure()
    configure_logging(paths.logs)
    manager = JobManager(paths)

    source = make_source_file(root)
    preset = get_preset(args.preset)
    high = manager.create_job(
        source_path=source,
        voice_id=args.voice,
        voice_profile_id="",
        preset_id=preset.preset_id,
        priority=90,
        max_chars=preset.max_chars,
        output_mode="segments",
        target_part_minutes=preset.target_part_minutes,
        keep_wav=False,
        sentence_silence=preset.sentence_silence,
        length_scale=preset.length_scale,
    )
    low = manager.create_job(
        source_path=source,
        voice_id=args.voice,
        voice_profile_id="",
        preset_id=preset.preset_id,
        priority=10,
        max_chars=preset.max_chars,
        output_mode="segments",
        target_part_minutes=preset.target_part_minutes,
        keep_wav=False,
        sentence_silence=preset.sentence_silence,
        length_scale=preset.length_scale,
    )

    stop_after = {"count": 0}

    def should_stop() -> bool:
        return stop_after["count"] >= 2

    def progress(_current: int, _total: int, _message: str) -> None:
        stop_after["count"] += 1

    try:
        manager.run_job(high, should_stop=should_stop, progress=progress)
    except Exception:
        pass

    high_state = manager.load_state(high.job_id)
    assert high_state.status == "stopped", high_state.status
    assert high_state.completed_chunks >= 2, high_state.completed_chunks

    manager.enqueue_job(high.job_id)
    recovered_next = manager.next_queued_job()
    assert recovered_next is not None
    assert recovered_next.job_id == high.job_id

    resumed = manager.run_job(manager.load_state(high.job_id))
    assert resumed.status == "completed", resumed.status

    next_job = manager.next_queued_job()
    assert next_job is not None
    assert next_job.job_id == low.job_id

    payload = {
        "root": str(root),
        "high_job": high.job_id,
        "low_job": low.job_id,
        "high_status": resumed.status,
        "completed_chunks_after_resume": resumed.completed_chunks,
    }
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

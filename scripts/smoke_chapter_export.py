from __future__ import annotations

import json
import tempfile
from pathlib import Path

from book2mp3.config import AppPaths
from book2mp3.pipeline.jobs import JobManager
from book2mp3.presets import get_preset
from book2mp3.utils.logging_utils import configure_logging


ROOT = Path("/home/codex/repo/book2mp3")


def ensure_fixture_link(app_root: Path, name: str) -> None:
    target = ROOT / name
    link = app_root / name
    if link.exists():
        return
    link.symlink_to(target, target_is_directory=True)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="book2mp3-smoke-chapters-") as tmp_dir:
        app_root = Path(tmp_dir) / "app"
        app_root.mkdir(parents=True, exist_ok=True)
        ensure_fixture_link(app_root, "runtime")
        ensure_fixture_link(app_root, "voices")

        paths = AppPaths.from_project_root(app_root)
        paths.ensure()
        configure_logging(paths.logs)
        manager = JobManager(paths)

        source = app_root / "chapter_source.txt"
        source.write_text(
            "\n\n".join(
                [
                    "Kapitel 1\n" + ("Dies ist der erste Kapiteltest. " * 90).strip(),
                    "Kapitel 2\n" + ("Dies ist der zweite Kapiteltest. " * 110).strip(),
                    "Kapitel 3\n" + ("Dies ist der dritte Kapiteltest. " * 80).strip(),
                ]
            ),
            encoding="utf-8",
        )

        preset = get_preset("balanced")
        job = manager.create_job(
            source_path=source,
            voice_id="de_DE-eva_k-x_low",
            voice_profile_id="",
            preset_id=preset.preset_id,
            priority=60,
            max_chars=180,
            output_mode="chapter_files",
            target_part_minutes=preset.target_part_minutes,
            keep_wav=False,
            sentence_silence=preset.sentence_silence,
            length_scale=preset.length_scale,
        )
        state = manager.run_job(job)

        manifest_path = Path(state.manifest_file)
        chapters_path = Path(state.chapters_file)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        chapters_payload = json.loads(chapters_path.read_text(encoding="utf-8"))

        assert state.status == "completed"
        assert len(state.chapters) == 3
        assert len(state.final_output_files) == 3
        assert manifest_path.exists()
        assert chapters_path.exists()
        assert chapters_payload["timeline_kind"] == "chapter"
        assert manifest["chapter_count"] == 3
        assert len(chapters_payload["entries"]) == 3
        for output_file in state.final_output_files:
            output_path = Path(output_file)
            assert output_path.exists()
            assert output_path.stat().st_size > 0

        print(
            json.dumps(
                {
                    "job_id": state.job_id,
                    "status": state.status,
                    "chapter_count": len(state.chapters),
                    "output_files": state.final_output_files,
                    "chapters_file": state.chapters_file,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

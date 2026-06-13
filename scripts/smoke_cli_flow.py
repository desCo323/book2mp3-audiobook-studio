from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

from book2mp3.config import AppPaths
from book2mp3.voice_settings import PROFILE_STATUS_TESTED, save_voice_setting


ROOT = Path("/home/codex/repo/book2mp3")


def ensure_fixture_link(app_root: Path, name: str) -> None:
    target = ROOT / name
    link = app_root / name
    if link.exists():
        return
    link.symlink_to(target, target_is_directory=True)


def bundled_python_env(app_root: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["BOOK2MP3_APP_ROOT"] = str(app_root)
    env["PYTHONHOME"] = str(ROOT / "src/python/linux")
    env["PYTHONNOUSERSITE"] = "1"
    env["PYTHONPATH"] = ":".join(
        [
            str(ROOT / "src"),
            str(ROOT / "src/python/linux/lib/python3.13/dist-packages"),
            str(ROOT / "src/python/linux/lib/python3.13/site-packages"),
        ]
    )
    env["LD_LIBRARY_PATH"] = str(ROOT / "src/python/linux/lib")
    return env


def run_cli(app_root: Path, *args: str) -> dict[str, object]:
    env = bundled_python_env(app_root)
    result = subprocess.run(
        [str(ROOT / "src/python/linux/bin/python3"), "-m", "book2mp3.cli", *args],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    return json.loads(result.stdout)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="book2mp3-smoke-cli-") as tmp_dir:
        app_root = Path(tmp_dir) / "app"
        app_root.mkdir(parents=True, exist_ok=True)
        ensure_fixture_link(app_root, "runtime")
        ensure_fixture_link(app_root, "voices")
        paths = AppPaths.from_project_root(app_root)
        paths.ensure()

        profile = save_voice_setting(
            paths.voice_settings,
            display_name="CLI Smoke Approved",
            backend="piper",
            voice_id="de_DE-eva_k-x_low",
            voice_profile_id="",
            preset_hint="natural",
            max_chars=220,
            output_mode="chapter_files",
            target_part_minutes=15,
            sentence_silence=0.24,
            length_scale=1.02,
            status=PROFILE_STATUS_TESTED,
            notes="Automatisch getestet für den CLI-Smoke",
        )

        source = app_root / "cli_source.txt"
        source.write_text(("Dies ist ein CLI-Test. " * 100).strip(), encoding="utf-8")
        analyzed = run_cli(app_root, "source-analyze", str(source))
        assert analyzed["analysis_status"] in {"supported", "unsupported"}
        metadata_source = app_root / "Jane Austen - Pride and Prejudice.txt"
        metadata_source.write_text("Metadata smoke.", encoding="utf-8")
        metadata_suggest = run_cli(app_root, "metadata-suggest", str(metadata_source))
        assert metadata_suggest["guessed"]["title"] == "Pride and Prejudice"
        assert metadata_suggest["guessed"]["author"] == "Jane Austen"
        metadata_search = run_cli(app_root, "metadata-search", "--title", "Pride and Prejudice", "--author", "Jane Austen", "--limit", "1")
        assert "results" in metadata_search

        shown = run_cli(app_root, "profile-show", profile.setting_id)
        assert shown["status"] == "tested"
        updated = run_cli(app_root, "profile-status", profile.setting_id, "approved")
        assert updated["status"] == "approved"
        profiles = run_cli(app_root, "profiles")
        matching_profile = next(
            item for item in profiles["profiles"] if item["setting_id"] == profile.setting_id
        )
        assert matching_profile["status"] == "approved"
        assert matching_profile["available_for_jobs"] is True
        diagnostics = run_cli(app_root, "diagnostics")
        assert diagnostics["paths"]["workspace"]["exists"] is True
        assert diagnostics["profiles"]["status_counts"]["approved"] >= 1
        assert diagnostics["voices"]["piper_voice_count"] >= 1

        created = run_cli(
            app_root,
            "create",
            str(source),
            "--profile-id",
            profile.setting_id,
            "--title",
            "CLI Smoke Buch",
            "--author",
            "Codex",
            "--language",
            "de",
        )
        job_id = str(created["job_id"])
        assert created["saved_profile_id"] == profile.setting_id

        inspected = run_cli(app_root, "inspect", job_id)
        assert inspected["audiobook_metadata"]["title"] == "CLI Smoke Buch"
        assert inspected["saved_profile_id"] == profile.setting_id
        assert inspected["estimated_total_seconds"] >= 0

        bulk_a = app_root / "cli_bulk_a.txt"
        bulk_a.write_text(("Kapitel 1\n" + ("Bulk A. " * 20)).strip(), encoding="utf-8")
        bulk_b = app_root / "cli_bulk_b.txt"
        bulk_b.write_text(("Dies ist ein zweiter Bulk-Test. " * 30).strip(), encoding="utf-8")
        bulk_created = run_cli(
            app_root,
            "create-bulk",
            str(bulk_a),
            str(bulk_b),
            "--profile-id",
            profile.setting_id,
        )
        assert len(bulk_created["jobs"]) == 2

        finished = run_cli(app_root, "run", job_id)
        manifest_path = Path(finished["manifest_file"])
        chapters_path = Path(finished["chapters_file"])
        assert manifest_path.exists()
        assert chapters_path.exists()

        listed = run_cli(app_root, "list")
        assert listed["jobs"]

        print(
            json.dumps(
                {
                    "job_id": job_id,
                    "status": finished["status"],
                    "profile_id": profile.setting_id,
                    "source_analysis_status": analyzed["analysis_status"],
                    "metadata_guess_title": metadata_suggest["guessed"]["title"],
                    "metadata_search_results": len(metadata_search["results"]),
                    "bulk_jobs_created": len(bulk_created["jobs"]),
                    "diagnostics_piper_count": diagnostics["voices"]["piper_voice_count"],
                    "manifest_file": str(manifest_path),
                    "chapters_file": str(chapters_path),
                    "jobs_listed": len(listed["jobs"]),
                },
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

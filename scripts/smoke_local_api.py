from __future__ import annotations

import json
import tempfile
import threading
from pathlib import Path
from urllib.request import Request, urlopen

from book2mp3.api import create_api_server
from book2mp3.config import AppPaths
from book2mp3.voice_settings import PROFILE_STATUS_TESTED, save_voice_setting


ROOT = Path("/home/codex/repo/book2mp3")


def ensure_fixture_link(app_root: Path, name: str) -> None:
    target = ROOT / name
    link = app_root / name
    if link.exists():
        return
    link.symlink_to(target, target_is_directory=True)


def api_json(method: str, url: str, payload: dict[str, object] | None = None) -> dict[str, object]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(url, method=method, data=data)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    with urlopen(request, timeout=120) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="book2mp3-smoke-api-", dir="/home/codex") as tmp_dir:
        app_root = Path(tmp_dir) / "app"
        app_root.mkdir(parents=True, exist_ok=True)
        ensure_fixture_link(app_root, "runtime")
        ensure_fixture_link(app_root, "voices")
        paths = AppPaths.from_project_root(app_root)
        paths.ensure()
        profile = save_voice_setting(
            paths.voice_settings,
            display_name="API Smoke Approved",
            backend="piper",
            voice_id="de_DE-eva_k-x_low",
            voice_profile_id="",
            preset_hint="balanced",
            max_chars=220,
            output_mode="chapter_files",
            target_part_minutes=15,
            sentence_silence=0.22,
            length_scale=1.0,
            status=PROFILE_STATUS_TESTED,
            notes="Automatisch getestet für den API-Smoke",
        )

        server = create_api_server(paths, host="127.0.0.1", port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        host, port = server.server_address
        base_url = f"http://{host}:{port}"

        try:
            health = api_json("GET", f"{base_url}/health")
            assert health["status"] == "ok"

            source = app_root / "api_source.txt"
            source.write_text(("Dies ist ein API-Test. " * 60).strip(), encoding="utf-8")
            analyzed = api_json("POST", f"{base_url}/source/analyze", {"source_path": str(source)})
            assert analyzed["analysis_status"] in {"supported", "unsupported"}
            metadata_source = app_root / "Gabriel García Márquez - Cien años de soledad.txt"
            metadata_source.write_text("Metadata API smoke.", encoding="utf-8")
            metadata_suggest = api_json("POST", f"{base_url}/metadata/suggest", {"source_path": str(metadata_source)})
            assert metadata_suggest["guessed"]["author"] == "Gabriel García Márquez"
            metadata_search = api_json(
                "POST",
                f"{base_url}/metadata/search",
                {"title": "Cien años de soledad", "author": "Gabriel García Márquez", "limit": 1},
            )
            assert "results" in metadata_search
            created = api_json(
                "POST",
                f"{base_url}/jobs",
                {
                    "source_path": str(source),
                    "voice_id": "de_DE-eva_k-x_low",
                    "preset_id": "balanced",
                    "backend": "piper",
                    "audiobook_metadata": {
                        "title": "API Smoke Buch",
                        "language": "de",
                        "author": "Codex",
                    },
                },
            )
            job_id = str(created["job_id"])

            voices = api_json("GET", f"{base_url}/voices")
            assert voices["piper"]
            shown = api_json("GET", f"{base_url}/profiles/{profile.setting_id}")
            assert shown["status"] == "tested"
            updated = api_json("POST", f"{base_url}/profiles/{profile.setting_id}/status", {"status": "approved"})
            assert updated["status"] == "approved"
            profiles = api_json("GET", f"{base_url}/profiles")
            matching_profile = next(
                item for item in profiles["profiles"] if item["setting_id"] == profile.setting_id
            )
            assert matching_profile["status"] == "approved"
            assert matching_profile["available_for_jobs"] is True
            diagnostics = api_json("GET", f"{base_url}/diagnostics")
            assert diagnostics["paths"]["workspace"]["exists"] is True
            assert diagnostics["profiles"]["status_counts"]["approved"] >= 1

            finished = api_json("POST", f"{base_url}/jobs/{job_id}/run", {})
            manifest_path = Path(finished["manifest_file"])
            chapters_path = Path(finished["chapters_file"])
            assert manifest_path.exists()
            assert chapters_path.exists()

            profiled_source = app_root / "api_profile_source.txt"
            profiled_source.write_text(("Dies ist ein API-Profiltest. " * 45).strip(), encoding="utf-8")
            profiled_job = api_json(
                "POST",
                f"{base_url}/jobs",
                {
                    "source_path": str(profiled_source),
                    "profile_id": profile.setting_id,
                    "audiobook_metadata": {
                        "title": "API Profil Buch",
                        "language": "de",
                        "author": "Codex",
                    },
                },
            )
            profiled_job_id = str(profiled_job["job_id"])
            assert profiled_job["saved_profile_id"] == profile.setting_id
            profiled_finished = api_json("POST", f"{base_url}/jobs/{profiled_job_id}/run", {})
            assert profiled_finished["saved_profile_id"] == profile.setting_id
            assert profiled_finished["estimated_total_seconds"] >= 0

            bulk_a = app_root / "api_bulk_a.txt"
            bulk_a.write_text(("Kapitel 1\n" + ("Bulk A. " * 20)).strip(), encoding="utf-8")
            bulk_b = app_root / "api_bulk_b.txt"
            bulk_b.write_text(("Dies ist ein zweiter API-Bulk-Test. " * 25).strip(), encoding="utf-8")
            bulk_created = api_json(
                "POST",
                f"{base_url}/jobs/bulk",
                {
                    "source_paths": [str(bulk_a), str(bulk_b)],
                    "profile_id": profile.setting_id,
                },
            )
            assert len(bulk_created["jobs"]) == 2

            listed = api_json("GET", f"{base_url}/jobs")
            assert listed["jobs"]

            print(
                json.dumps(
                    {
                        "job_id": job_id,
                        "status": finished["status"],
                        "source_analysis_status": analyzed["analysis_status"],
                        "metadata_guess_author": metadata_suggest["guessed"]["author"],
                        "metadata_search_results": len(metadata_search["results"]),
                        "profiled_job_id": profiled_job_id,
                        "profile_id": profile.setting_id,
                        "bulk_jobs_created": len(bulk_created["jobs"]),
                        "diagnostics_profile_approved": diagnostics["profiles"]["status_counts"]["approved"],
                        "manifest_file": str(manifest_path),
                        "chapters_file": str(chapters_path),
                        "voice_count": len(voices["piper"]),
                    },
                    indent=2,
                )
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

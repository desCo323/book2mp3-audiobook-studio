from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from book2mp3.api import serve as serve_api
from book2mp3.config import AppPaths
from book2mp3.service import Book2Mp3Service
from book2mp3.voice_settings import VALID_PROFILE_STATUSES


def project_root() -> Path:
    configured_root = os.environ.get("BOOK2MP3_APP_ROOT", "").strip()
    if configured_root:
        return Path(configured_root).resolve()
    return Path(__file__).resolve().parents[2]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="book2mp3-cli")
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create", help="Create a new audiobook job")
    create.add_argument("source_path")
    create.add_argument("--saved-profile-id", "--profile-id", dest="saved_profile_id", default="")
    create.add_argument("--backend", default="piper")
    create.add_argument("--voice-id", default="")
    create.add_argument("--voice-profile-id", default="")
    create.add_argument("--preset", default="balanced")
    create.add_argument("--priority", type=int, default=50)
    create.add_argument("--max-chars", type=int)
    create.add_argument("--output-mode")
    create.add_argument("--target-part-minutes", type=int)
    create.add_argument("--keep-wav", action="store_true")
    create.add_argument("--sentence-silence", type=float)
    create.add_argument("--length-scale", type=float)
    _add_metadata_args(create)

    create_bulk = sub.add_parser("create-bulk", help="Create multiple audiobook jobs at once")
    create_bulk.add_argument("source_paths", nargs="+")
    create_bulk.add_argument("--saved-profile-id", "--profile-id", dest="saved_profile_id", default="")
    create_bulk.add_argument("--backend", default="piper")
    create_bulk.add_argument("--voice-id", default="")
    create_bulk.add_argument("--voice-profile-id", default="")
    create_bulk.add_argument("--preset", default="balanced")
    create_bulk.add_argument("--priority", type=int, default=50)
    create_bulk.add_argument("--max-chars", type=int)
    create_bulk.add_argument("--output-mode")
    create_bulk.add_argument("--target-part-minutes", type=int)
    create_bulk.add_argument("--keep-wav", action="store_true")
    create_bulk.add_argument("--sentence-silence", type=float)
    create_bulk.add_argument("--length-scale", type=float)
    _add_metadata_args(create_bulk)

    sub.add_parser("list", help="List all jobs")

    source_analyze = sub.add_parser("source-analyze", help="Analyze a source file for chapter support")
    source_analyze.add_argument("source_path")

    metadata_suggest = sub.add_parser("metadata-suggest", help="Suggest audiobook metadata from a file name and optional Open Library lookup")
    metadata_suggest.add_argument("source_path")

    metadata_search = sub.add_parser("metadata-search", help="Search Open Library for audiobook metadata")
    metadata_search.add_argument("--query", default="")
    metadata_search.add_argument("--title", default="")
    metadata_search.add_argument("--author", default="")
    metadata_search.add_argument("--limit", type=int, default=5)

    inspect = sub.add_parser("inspect", help="Inspect a single job")
    inspect.add_argument("job_id")

    run = sub.add_parser("run", help="Run one job immediately")
    run.add_argument("job_id")

    enqueue = sub.add_parser("enqueue", help="Put a job back into the queue")
    enqueue.add_argument("job_id")

    retry = sub.add_parser("retry", help="Reset chunks and retry a job")
    retry.add_argument("job_id")
    retry.add_argument("--chunk", type=int, action="append", default=[])
    retry.add_argument("--keep-output", action="store_true")

    reset = sub.add_parser("reset", help="Reset workspace state")
    reset.add_argument("--workspace", action="store_true")

    sub.add_parser("run-next", help="Run the next queued job")
    sub.add_parser("voices", help="List installed Piper voices and XTTS profiles")
    sub.add_parser("profiles", help="List saved production profiles")
    profile_show = sub.add_parser("profile-show", help="Show one saved production profile")
    profile_show.add_argument("profile_id")
    profile_status = sub.add_parser("profile-status", help="Change the status of a saved production profile")
    profile_status.add_argument("profile_id")
    profile_status.add_argument("status", choices=sorted(VALID_PROFILE_STATUSES))
    sub.add_parser("presets", help="List available quality presets")
    sub.add_parser("diagnostics", help="Show runtime, workspace and profile diagnostics")

    serve = sub.add_parser("serve", help="Run the local REST API")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    return parser


def _add_metadata_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--title")
    parser.add_argument("--album")
    parser.add_argument("--artist")
    parser.add_argument("--album-artist")
    parser.add_argument("--narrator")
    parser.add_argument("--author")
    parser.add_argument("--genre")
    parser.add_argument("--language")
    parser.add_argument("--comment")


def _metadata_from_args(args: argparse.Namespace) -> dict[str, str] | None:
    metadata = {
        "title": args.title,
        "album": args.album,
        "artist": args.artist,
        "album_artist": args.album_artist,
        "narrator": args.narrator,
        "author": args.author,
        "genre": args.genre,
        "language": args.language,
        "comment": args.comment,
    }
    filtered = {key: value for key, value in metadata.items() if value}
    return filtered or None


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    paths = AppPaths.from_project_root(project_root())
    service = Book2Mp3Service(paths)
    service.recover_interrupted_jobs()

    if args.command == "create":
        payload = service.create_job(
            source_path=args.source_path,
            saved_profile_id=args.saved_profile_id,
            backend=args.backend,
            voice_id=args.voice_id,
            voice_profile_id=args.voice_profile_id,
            preset_id=args.preset,
            priority=args.priority,
            max_chars=args.max_chars,
            output_mode=args.output_mode,
            target_part_minutes=args.target_part_minutes,
            keep_wav=True if args.keep_wav else None,
            sentence_silence=args.sentence_silence,
            length_scale=args.length_scale,
            audiobook_metadata=_metadata_from_args(args),
        )
        _print_json(payload)
        return 0
    if args.command == "create-bulk":
        payload = service.create_jobs(
            source_paths=args.source_paths,
            saved_profile_id=args.saved_profile_id,
            backend=args.backend,
            voice_id=args.voice_id,
            voice_profile_id=args.voice_profile_id,
            preset_id=args.preset,
            priority=args.priority,
            max_chars=args.max_chars,
            output_mode=args.output_mode,
            target_part_minutes=args.target_part_minutes,
            keep_wav=True if args.keep_wav else None,
            sentence_silence=args.sentence_silence,
            length_scale=args.length_scale,
            audiobook_metadata=_metadata_from_args(args),
        )
        _print_json({"jobs": payload})
        return 0
    if args.command == "list":
        _print_json({"jobs": service.list_jobs()})
        return 0
    if args.command == "source-analyze":
        _print_json(service.analyze_source(args.source_path))
        return 0
    if args.command == "metadata-suggest":
        _print_json(service.metadata_suggestions(args.source_path))
        return 0
    if args.command == "metadata-search":
        _print_json(
            {
                "results": service.search_book_metadata(
                    query=args.query,
                    title=args.title,
                    author=args.author,
                    limit=args.limit,
                )
            }
        )
        return 0
    if args.command == "inspect":
        _print_json(service.get_job(args.job_id))
        return 0
    if args.command == "run":
        _print_json(service.run_job(args.job_id))
        return 0
    if args.command == "enqueue":
        _print_json(service.enqueue_job(args.job_id))
        return 0
    if args.command == "retry":
        _print_json(
            service.retry_job(
                args.job_id,
                chunk_indexes=args.chunk or None,
                reset_output=not args.keep_output,
            )
        )
        return 0
    if args.command == "reset":
        if not args.workspace:
            parser.error("reset currently requires --workspace")
        _print_json(service.reset_workspace())
        return 0
    if args.command == "run-next":
        _print_json({"job": service.run_next_job()})
        return 0
    if args.command == "voices":
        _print_json(service.list_voices())
        return 0
    if args.command == "profiles":
        _print_json({"profiles": service.list_saved_profiles()})
        return 0
    if args.command == "profile-show":
        _print_json(service.get_saved_profile(args.profile_id))
        return 0
    if args.command == "profile-status":
        _print_json(service.update_saved_profile_status(args.profile_id, args.status))
        return 0
    if args.command == "presets":
        _print_json({"presets": service.list_presets()})
        return 0
    if args.command == "diagnostics":
        _print_json(service.diagnostics(include_runtime_probe=True))
        return 0
    if args.command == "serve":
        return serve_api(paths, host=args.host, port=args.port)

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

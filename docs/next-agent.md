# AI Agent Briefing

This file is the canonical handover for future agents working on `book2mp3`.

## Mission

`book2mp3` is a local-first desktop application for turning `TXT`, `PDF`, and `EPUB` sources into resumable MP3 audiobooks.

The product goal is not “a demo TTS tool.” It is a user-friendly audiobook production studio with:

- resumable jobs
- queue management
- chapter-aware export
- saved production profiles
- benchmark and tuning workflows
- local GUI, CLI, and local API access
- portable end-user releases

The software is intended to feel simple for non-technical users while still exposing enough control for high-quality audiobook work.

## Product Principles

- Keep the pipeline file-based and resumable.
- Keep the desktop app local/offline-first.
- Treat `Piper` as the default ready-to-use path.
- Treat `XTTS` as an optional premium path with stricter runtime and license caveats.
- Never mix “test lab” controls into the normal production job flow.
- Completed books belong in the finished-books/finalization area, not in the active queue.
- Any change that harms recovery, resume, or artifact integrity is a regression.

## Current Product Shape

Main UI areas:

- `Neuer Auftrag`
- `Aufträge`
- `Produktionsprofile`
- `Benchmark-Studio`
- `XTTS-Profile`
- `Diagnose`
- `Einstellungen`

Important UI behavior already expected by the user:

- only active jobs in the left job list
- completed jobs only in the finished/finalization area
- metadata can be edited before and after synthesis
- queue ETA is visible per job and as a combined total
- laptop-sized layouts must remain usable
- backend-specific controls must not appear everywhere at once

## Current Feature Baseline

The app already supports:

- importing `TXT`, `PDF`, `EPUB`
- source analysis and chapter detection
- chunked processing with persisted state
- resumable queue-based jobs
- `Piper` and `XTTS`
- CUDA-aware XTTS mode selection
- saved production profiles with approval workflow
- benchmark/tuning sessions
- metadata guessing from filenames
- metadata lookup via Open Library
- final MP3 tagging and manifest regeneration
- CLI and local API access
- queue ETA and runtime statistics
- portable Linux and Windows release scripts
- multilingual UI infrastructure

## Languages

The UI is designed to support:

- English
- German
- Spanish
- Portuguese

Desired behavior:

- default to English when nothing better is known
- prefer the operating system language when supported
- language can be changed explicitly in settings

When adding UI strings, keep translations in sync in `src/book2mp3/i18n.py`.

## Architecture Overview

Read these files first:

- [README.md](/home/codex/repo/book2mp3/README.md)
- [docs/architecture.md](/home/codex/repo/book2mp3/docs/architecture.md)
- [docs/user-guide.md](/home/codex/repo/book2mp3/docs/user-guide.md)
- [src/book2mp3/service.py](/home/codex/repo/book2mp3/src/book2mp3/service.py)
- [src/book2mp3/pipeline/jobs.py](/home/codex/repo/book2mp3/src/book2mp3/pipeline/jobs.py)
- [src/book2mp3/ui/main_window.py](/home/codex/repo/book2mp3/src/book2mp3/ui/main_window.py)
- [src/book2mp3/ui/find_best_setting_dialog.py](/home/codex/repo/book2mp3/src/book2mp3/ui/find_best_setting_dialog.py)
- [src/book2mp3/tts/xtts.py](/home/codex/repo/book2mp3/src/book2mp3/tts/xtts.py)
- [src/book2mp3/runtime_stats.py](/home/codex/repo/book2mp3/src/book2mp3/runtime_stats.py)

High-level layers:

- `src/book2mp3/ui/`: desktop interface
- `src/book2mp3/service.py`: shared orchestration for GUI, CLI, API
- `src/book2mp3/pipeline/`: extraction, chunking, synthesis, output assembly
- `src/book2mp3/tts/`: Piper and XTTS backends
- `src/book2mp3/models.py`: persisted state models
- `src/book2mp3/runtime_stats.py`: learned timings, ETA, mode heuristics
- `scripts/`: smoke tests, release builders, runtime setup helpers

## State and Artifact Model

Jobs are persisted under `workspace/jobs/<job_id>/`.

Important persisted artifacts include:

- `state.json`
- extracted source text
- chapter text files
- chunk text files
- generated WAV and MP3 chunk files
- final output files
- `manifest.json`
- `chapters.json`
- `failure_report.json` when recovery fails

The pipeline must remain restartable from artifacts already on disk.

## Parallel Processing Rules

Parallel processing exists, but correctness is more important than speed.

Current intent:

- `serial`
- `parallel_cpu_postprocess`

Rules that must remain true:

- a finished chunk with valid MP3 output must never be re-synthesized
- deleting an intermediate WAV must not cause a re-run
- restart/resume must reconcile artifacts before continuing
- loop behavior must be detected and turned into a clear structured failure if self-heal cannot solve it

If a performance feature threatens correctness, disable or degrade it first, then optimize again safely.

## XTTS Expectations

XTTS is optional, not the default baseline for first-time users.

Expected behavior:

- app still starts and works without XTTS
- XTTS setup is optional and guided
- missing or broken XTTS runtime should trigger recovery or a blocked state, not a silent failure loop
- CUDA should be preferred when truly available
- runtime issues should produce actionable diagnostics

Recent work already added:

- XTTS runtime self-heal attempts
- loop detection for repeated batch processing without progress
- resume/recovery based on real artifact state

## Metadata Expectations

Metadata matters to the user.

The app should support:

- title
- author
- narrator
- genre
- language
- comment/source note
- final MP3 tags
- post-processing metadata editing for finished books

Open Library search is present as a helper, but filename-based guessing must also stay useful.

## Finished Books UX

The user wants a clear separation:

- active production queue on the left
- finished audiobooks in a dedicated finalization area

The finalization area should support:

- opening the audiobook
- opening the output folder
- deleting the finished project
- editing and saving metadata/tags after completion

Do not regress this separation.

## Runtime Statistics and ETA

The app is intended to learn over time.

Persisted timing data should improve:

- ETA before job start
- remaining time during the job
- choice between serial and parallel processing
- rough duration expectations for future books using similar profiles/backends

The user explicitly wants:

- per-job estimated duration in the queue
- combined queue duration in hours/minutes
- useful early estimates after the first successful real book

## Portable Release Policy

The repository is source-first.

End-user consumption should happen through portable builds, not by asking users to install Python manually.

Rules:

- do not commit large portable bundles into the repo
- use the GitHub Actions portable release workflow
- keep release scripts working on Linux and Windows
- starter releases should be Piper-ready
- XTTS remains optional

Portable release entry points:

- [scripts/build_portable_bundle.py](/home/codex/repo/book2mp3/scripts/build_portable_bundle.py)
- [scripts/build_linux_portable_release.py](/home/codex/repo/book2mp3/scripts/build_linux_portable_release.py)
- [scripts/build_windows_portable_release.py](/home/codex/repo/book2mp3/scripts/build_windows_portable_release.py)
- [scripts/check_portable_bundle.py](/home/codex/repo/book2mp3/scripts/check_portable_bundle.py)
- [.github/workflows/portable-release.yml](/home/codex/repo/book2mp3/.github/workflows/portable-release.yml)

## Licensing and Publication Constraints

Do not claim that XTTS licensing is “solved.”

Known publication caveats:

- `XTTS-v2` has license restrictions that must be communicated clearly
- `EbookLib` is an AGPL-related concern for release strategy
- bundled third-party binaries and voices require notice handling

Relevant docs:

- [docs/open-source-compliance.md](/home/codex/repo/book2mp3/docs/open-source-compliance.md)
- [THIRD_PARTY_NOTICES.md](/home/codex/repo/book2mp3/THIRD_PARTY_NOTICES.md)
- [LICENSE](/home/codex/repo/book2mp3/LICENSE)

## How to Work Safely in This Repo

- Do not commit user-generated `workspace/` data.
- Do not commit secrets, tokens, or machine-local credentials.
- Do not assume the app is closed; the user may have it open.
- If you need screenshots or disruptive UI tests, prefer a separate temporary copy of the repo/workspace.
- Do not revert unrelated local changes.
- The deleted file `Der Weg der Liebe - Nico Robin.epub` is a known local worktree change and should not be force-restored or blindly committed.

## Testing Expectations

Do not stop at static reasoning. Run the relevant smoke tests.

Commonly useful smoke tests:

- `scripts/smoke_i18n_metadata_finished_books.py`
- `scripts/smoke_laptop_layout.py`
- `scripts/smoke_profile_approval_flow.py`
- `scripts/smoke_jobs_and_benchmark_workflow.py`
- `scripts/smoke_bulk_import_and_eta.py`
- `scripts/smoke_xtts_loop_guard.py`
- `scripts/smoke_xtts_resume_recovery.py`
- `scripts/smoke_xtts_main_window_job.py`
- `scripts/smoke_real_story_gui.py`
- `scripts/smoke_real_pdf_reference.py`
- `scripts/smoke_cli_flow.py`
- `scripts/smoke_local_api.py`

When touching packaging or launch behavior, also run:

- `./start.sh` in offscreen/headless form if needed
- portable bundle build/check scripts relevant to the changed platform

## Current Priorities

When choosing work, prefer this order unless the user overrides it:

1. correctness and recovery
2. self-explanatory UI on standard laptop screens
3. finished-books and metadata workflow
4. ETA quality and queue transparency
5. portable release reliability
6. benchmark-studio simplification
7. deeper performance optimization

## Definition of Good Work Here

Good changes in this repo are:

- measurable
- tested
- reversible
- consistent across GUI, CLI, and API where relevant
- understandable to a non-technical audiobook user

Bad changes in this repo are:

- technically clever but UI-confusing
- fast but artifact-unsafe
- local-only hacks that break portable releases
- changes that hide failures instead of compensating or reporting them

## Short Summary for the Next Agent

You are working on a resumable audiobook studio, not a toy converter.

Protect:

- artifact integrity
- queue correctness
- finished-book workflow
- portable usability
- clear, calm UI

Improve:

- reliability
- simplicity
- ETA confidence
- metadata quality
- cross-language usability

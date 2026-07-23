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

### Current XTTS Production Handoff

The improved ebook quality render was promoted to the approved production profile on 2026-07-15. The usable standard profile is `xtts1` / `Standard XTTS` in `workspace/voice_settings/xtts1.json`; `service.py` and the UI seed it via `ensure_standard_xtts_setting()`.

Production profile values:

- Backend/profile: XTTS, voice `de_DE-ramona-low`, voice profile `xtts_kerstin_hq_female`
- Output: `chapter_files`, target part length 20 minutes
- Text sizing: `max_chars=130`, `length_scale=0.96`, `sentence_silence=0.24`
- Quality: `xtts_quality_mode=max_quality`
- Inference: `temperature=0.82`, `top_p=0.96`, `top_k=80`, `repetition_penalty=4.0`, `num_beams=1`, `do_sample=true`, `enable_text_splitting=false`, `gpt_cond_len=30`, `gpt_cond_chunk_len=6`, `max_ref_length=45`, `sound_norm_refs=true`
- Pronunciation: curated default rules from the metadata lexicon plus project-specific fantasy-name rules

Relevant production code:

- [src/book2mp3/tts/pronunciation.py](/home/codex/repo/book2mp3/src/book2mp3/tts/pronunciation.py): name markers, fantasy-name hints, and fast marker scoring
- [src/book2mp3/tts/learned_lexicon.py](/home/codex/repo/book2mp3/src/book2mp3/tts/learned_lexicon.py): workspace learning DB with optional IPA backends
- [src/book2mp3/pipeline/prosody.py](/home/codex/repo/book2mp3/src/book2mp3/pipeline/prosody.py): optional-pySBD prosody/text segmentation, dialogue/question/suspense styles, planned pause metadata, and dense-name chunk refinement
- [src/book2mp3/pipeline/jobs.py](/home/codex/repo/book2mp3/src/book2mp3/pipeline/jobs.py): production integration for learned lexicon rules, global identity name markers, prosody-aware XTTS chunking, and chunk metadata

Workflow details:

- Known clean lexicon hits are treated as identity/name markers and are not reinterpreted.
- The learned lexicon was reset to zero entries/test runs for the production handoff. Current DB path: `workspace/learned_lexicon/xtts_names.json`.
- The XTTS render path enforces `XTTS_MIN_RENDER_CHUNK_CHARS = 80` and merges short fragments before rendering. This specifically prevents the previous word-salad failure from a 19-character chunk such as `fuhr Kuelebre fort.` while keeping more context for XTTS prosody.
- `NameMarkerScorer` precompiles marker patterns and `pipeline/prosody.py` caches per-chunk scores; use that path instead of calling `name_marker_score()` inside tight chunking loops.
- Active test jobs were removed from the app queue by replacing `workspace/jobs` with a new empty directory. Old root-owned job directories were moved as a whole to `workspace/jobs_rootowned_backup_20260715_223138`; three codex-owned old jobs are in `workspace/jobs_removed_20260715_223117`.

Latest validated ebook quality checks:

- `workspace/manual_checks_xtts_ebook_quality/harrison_khalil_rune_grace/improved_prosody.mp3`
- `workspace/manual_checks_xtts_ebook_quality/aiken_eibhear_rhiannon_izzy/improved_prosody.mp3`
- The improved files were judged better by the user and are the reference for the production profile.
- The previously bad `workspace/manual_checks_xtts_ebook_quality/harrison_khalil_rune_grace/improved_prosody/wav/003.wav` was fixed by merging short fragments; it now contains a stable full sentence instead of a tiny continuation chunk.

Temporary tuning, scanning, and smoke scripts from the experiment were removed from the code tree during this handoff. Manual check output under `workspace/` is retained only as evidence/reference and is not part of the app workflow.

Optional phonetic libraries are not installed in the current environment. `learned_lexicon.py` will use `phonemizer` or `espeak` if they are installed later; otherwise it stores heuristic spoken forms, confidence, syllable counts, and stress/prosody hints. `pipeline/prosody.py` will use `pySBD` if it is installed later; otherwise it uses the built-in regex segmenter.

### Metadata Detection Handoff

The programming task in `workspace/metadata_analysis/metadata_detection_programming_task.md` was implemented for the extractor path on 2026-07-15.

Implemented in `book2mp3.metadata_extractor`:

- Fixed the `extractor.extract()` `NameError` by using `final_title` for cover fallback.
- EPUB OPF/DC title and author now win for sane EPUB metadata; filename/path candidates still contribute conflicts and fallback data.
- Debug output now includes `field_sources`, `conflicts`, `warnings`, compact `raw_metadata`, `language_source`, and `language_confidence`.
- `repair_mojibake()` repairs damaged pseudo-entities such as `Handuuml;`, `grandouml;andszlig;te`, and `Vermandauml;`.
- Filename parsing handles `Kopie von ...`, German `von` false positives, fanfiction handles with digits, generic folders such as `epubfe`, article inversion such as `Herz des Wolfes, Das`, and multi-dash author/title cases.
- Optional series fields are exposed through `MetadataExtractionResult` and `extended_book_metadata`: `series`, `series_index`, `display_title`, `sort_title`, `subtitle`.
- EPUB language is verified with a no-dependency de/en text heuristic; strong conflicts override OPF language and are recorded in warnings.

Validation:

- `PYTHONPYCACHEPREFIX=/tmp/book2mp3-pycache PYTHONPATH=src ./src/python/linux/bin/python3 -m py_compile src/book2mp3/metadata_extractor/normalize.py src/book2mp3/metadata_extractor/models.py src/book2mp3/metadata_extractor/extractor.py src/book2mp3/metadata_extractor/evaluation.py`
- `PYTHONPYCACHEPREFIX=/tmp/book2mp3-pycache PYTHONPATH=src ./src/python/linux/bin/python3 -m book2mp3.metadata_extractor evaluate /home/codex/Dokumente/Ebooks\ Alina/ebubtest --offline --suffix .epub`
- Final corpus result: 141/141 files, real title/author/pair accuracy all `1.0`; synthetic filename pair accuracy `0.9137`, title `0.974`, author `0.9303`.

Follow-up state:

- The `_resolve_metadata(...)` logging fallback in [src/book2mp3/service.py](/home/codex/repo/book2mp3/src/book2mp3/service.py) is now applied. Metadata extraction exceptions are logged with traceback and fall back to `guess_metadata_from_filename(source_path)`.
- `src/book2mp3/service.py` and `src/book2mp3/ui/main_window.py` were restored to codex-owned writable files after previously being root-owned in this checkout.

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
- re-running the full metadata detector for one finished book or all finished books

Do not regress this separation.

Recent finished-books metadata work:

- [src/book2mp3/ui/main_window.py](/home/codex/repo/book2mp3/src/book2mp3/ui/main_window.py) adds `Neu erkennen & ersetzen` and `Alle neu erkennen` in the finished-books metadata area.
- [src/book2mp3/service.py](/home/codex/repo/book2mp3/src/book2mp3/service.py) exposes `redetect_finished_job_metadata()` and `redetect_all_finished_metadata()`. These run the current extractor against the persisted source file, replace the job metadata, write metadata history, and reapply final MP3 outputs.
- [src/book2mp3/pipeline/jobs.py](/home/codex/repo/book2mp3/src/book2mp3/pipeline/jobs.py) now renames existing final MP3 files from the replaced metadata before retagging/manifests/finalbooks sync. Single-file output becomes `Author - Title.mp3`; chapter/part/segment modes use the same stem with mode-specific suffixes. The finalbooks folder continues to follow the book title and is moved when the detected title changes.
- The metadata year transfer path now tolerates non-numeric date strings instead of failing on values such as full publication dates.
- Startup recovery now skips stale chunk artifact paths that are empty or directories, preventing `Path('')`/`.` from crashing recovery with `IsADirectoryError`.
- Three non-finished jobs found during verification were moved out of the live queue to `workspace/jobs_removed_20260715_230000` so the app starts with `0 jobs` for fresh testing.

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

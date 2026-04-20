# Next Agent Handover

## Current branch state

The repository was initialized from a loose folder, not from an existing local git clone. The current codebase now contains the first structured rewrite around a resumable desktop app.

## What exists

- legacy scripts preserved in `ebooksp/`
- new app package in `src/book2mp3/`
- documentation in `docs/`
- runtime bootstrap script in `scripts/bootstrap_runtime.py`

## What the first rewrite already does

- imports `TXT`, `PDF`, `EPUB`
- extracts text into job-local files
- chunks text into small `.txt` files
- persists job settings and chunk status in `state.json`
- persists a priority-based queue across restarts
- synthesizes with local `Piper`
- writes MP3 segment files
- can stop and resume a job
- can optionally concatenate segments into one MP3
- writes detailed diagnostics to `workspace/logs/app.log` and per-job `job.log`
- exposes quality presets and a first Voice Lab dialog

## Important constraints

- do not remove `ebooksp/`; it is reference material
- do not replace the chunked pipeline with monolithic synthesis
- keep resume file-based
- keep runtime assets outside the Python package so users can swap voices and binaries

## High-value next tasks

1. Add a voice management screen that discovers installed voices and offers guided download.
2. Add an XTTS backend that consumes `workspace/voice_profiles/`.
3. Extend automated smoke coverage beyond the current queue/resume script.
4. Create platform-specific build scripts with `pyside6-deploy`.

## Files to read first

- [README.md](/home/codex/repo/book2mp3/README.md)
- [docs/architecture.md](/home/codex/repo/book2mp3/docs/architecture.md)
- [docs/voice-strategy.md](/home/codex/repo/book2mp3/docs/voice-strategy.md)
- [src/book2mp3/pipeline/jobs.py](/home/codex/repo/book2mp3/src/book2mp3/pipeline/jobs.py)
- [src/book2mp3/tts/piper.py](/home/codex/repo/book2mp3/src/book2mp3/tts/piper.py)
- [src/book2mp3/ui/main_window.py](/home/codex/repo/book2mp3/src/book2mp3/ui/main_window.py)

## Known gaps

- no automated tests yet
- no XTTS backend yet
- no finished packaging scripts yet
- no remote push confirmed yet

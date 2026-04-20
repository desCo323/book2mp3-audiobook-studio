# Next Agent Handover

## Current branch state

The repository was initialized from a loose folder, not from an existing local git clone. The current codebase now contains the first structured rewrite around a resumable desktop app.

## What exists

- legacy scripts preserved in `ebooksp/`
- new app package in `src/book2mp3/`
- documentation in `docs/`
- runtime bootstrap script in `scripts/bootstrap_runtime.py`
- portable launchers in `start.sh` and `start.bat`

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
- includes a defined portable bundle layout with app-local Python requirement
- marks unfinished XTTS/custom-voice UI paths in orange beta styling
- can bootstrap a dedicated Linux XTTS runtime with standalone Python 3.11

## Important constraints

- do not remove `ebooksp/`; it is reference material
- do not replace the chunked pipeline with monolithic synthesis
- keep resume file-based
- keep runtime assets outside the Python package so users can swap voices and binaries

## High-value next tasks

1. Add a voice management screen that discovers installed voices and offers guided download.
2. Make the XTTS runtime path run an actual synthesis smoke test on Linux with the new CPU-first torch install path.
3. Push the Windows self-contained bundle path from prepared scripts to a fully validated build.
4. Extend GUI automation beyond the current smoke scripts.

## Files to read first

- [README.md](/home/codex/repo/book2mp3/README.md)
- [docs/architecture.md](/home/codex/repo/book2mp3/docs/architecture.md)
- [docs/voice-strategy.md](/home/codex/repo/book2mp3/docs/voice-strategy.md)
- [src/book2mp3/pipeline/jobs.py](/home/codex/repo/book2mp3/src/book2mp3/pipeline/jobs.py)
- [src/book2mp3/tts/piper.py](/home/codex/repo/book2mp3/src/book2mp3/tts/piper.py)
- [src/book2mp3/ui/main_window.py](/home/codex/repo/book2mp3/src/book2mp3/ui/main_window.py)

## Known gaps

- Windows self-contained packaging is prepared but not yet practically validated end-to-end
- XTTS runtime packaging exists, but a full heavyweight synthesis smoke path is still missing
- plain `pip install TTS` on Linux tries to pull very large CUDA dependencies; the runtime bootstrap now defaults to CPU-first torch wheels to avoid that
- GUI interaction testing is still lighter than the non-GUI smoke coverage

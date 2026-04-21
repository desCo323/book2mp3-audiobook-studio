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
- can now probe XTTS CUDA capability from the UI and choose `Auto`, `CPU`, or `CUDA`
- can import external custom Piper `.onnx` + `.onnx.json` models into the app

## Verified local runtime state

As of April 21, 2026 on this workstation:

- host GPU: `NVIDIA GeForce RTX 3050 Laptop GPU`
- driver: `580.126.09`
- XTTS runtime Python: `src/runtime/xtts/linux/bin/python3`
- XTTS runtime torch: `2.6.0+cu124`
- XTTS runtime CUDA probe: `cuda_available = true`

Real validation commands that were green:

- `PYTHONPATH=src python3 scripts/smoke_xtts_cuda_probe.py`
- `PYTHONPATH=src python3 scripts/smoke_xtts_persistent_server.py`

Most recent real timing after the CUDA runtime fix:

- first XTTS request in a fresh worker: about `31.11s`
- second XTTS request in the warm persistent worker: about `1.55s`

This is a large improvement over the prior CPU-only state, but first-request latency is still noticeable because model load is expensive.

## Important constraints

- do not remove `ebooksp/`; it is reference material
- do not replace the chunked pipeline with monolithic synthesis
- keep resume file-based
- keep runtime assets outside the Python package so users can swap voices and binaries

## High-value next tasks

1. Add a voice management screen that discovers installed voices and offers guided download.
2. Push the Windows self-contained bundle path from prepared scripts to a fully validated build.
3. Extend GUI automation beyond the current smoke scripts.
4. If XTTS still feels too slow in practice, profile first-request latency separately from warm-worker latency before changing synthesis logic again.

## Files to read first

- [README.md](/home/codex/repo/book2mp3/README.md)
- [docs/architecture.md](/home/codex/repo/book2mp3/docs/architecture.md)
- [docs/voice-strategy.md](/home/codex/repo/book2mp3/docs/voice-strategy.md)
- [src/book2mp3/pipeline/jobs.py](/home/codex/repo/book2mp3/src/book2mp3/pipeline/jobs.py)
- [src/book2mp3/tts/piper.py](/home/codex/repo/book2mp3/src/book2mp3/tts/piper.py)
- [src/book2mp3/ui/main_window.py](/home/codex/repo/book2mp3/src/book2mp3/ui/main_window.py)

## Known gaps

- Windows self-contained packaging is prepared but not yet practically validated end-to-end
- XTTS runtime packaging exists and CUDA can be validated locally, but first-request latency is still high enough that users may still perceive XTTS as slow
- plain `pip install TTS` on Linux tries to pull very large CUDA dependencies; the runtime bootstrap now supports `--torch-variant auto|cpu|cuda` and validates the result with a CUDA probe
- GUI interaction testing is still lighter than the non-GUI smoke coverage

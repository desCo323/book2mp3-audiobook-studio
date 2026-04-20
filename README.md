# book2mp3

`book2mp3` is a desktop-first audiobook production tool for Windows and Linux. It imports `PDF`, `TXT` and `EPUB`, extracts clean text, splits it into stable chunks, synthesizes speech chunk by chunk, and writes resumable MP3 outputs.

The old `ebooksp` scripts showed why this needs to happen in small steps:

- large monolithic TTS runs are fragile
- partial output must survive crashes
- each intermediate step must be inspectable and restartable

This rewrite keeps those properties, but wraps them in a structured application with a modern GUI, persistent jobs, resumability, progress tracking, queueing and cleanup rules.

## Current status

This repository now contains the first production-oriented foundation:

- PySide6 desktop GUI
- persistent job directories with `state.json`
- persistent queue with priorities across restarts
- extensive debug logging with app-level and job-level log files
- import pipeline for `TXT`, `PDF` and `EPUB`
- sentence-aware chunking
- resumable per-chunk synthesis
- local `Piper` backend integration
- MP3 segment export and optional single-file concat
- runtime bootstrap script for `Piper`
- handover documentation for follow-up agents

Voice cloning and an XTTS backend are prepared architecturally but not implemented in this first pass.

## Project layout

- `src/book2mp3/`: application code
- `docs/`: architecture, roadmap, agent handover
- `scripts/bootstrap_runtime.py`: downloads local runtime components
- `ebooksp/`: legacy reference scripts kept for comparison

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
python scripts/bootstrap_runtime.py --voice de_DE-thorsten-high
book2mp3
```

On Windows, activate the virtual environment with:

```powershell
.venv\Scripts\Activate.ps1
```

Then run:

```powershell
pip install -e .
python scripts\bootstrap_runtime.py --voice de_DE-thorsten-high
book2mp3
```

## Packaging direction

The intended packaging target is folder-based desktop deployment, not a single giant executable:

- Windows: `pyside6-deploy` / Nuitka one-folder
- Linux: `pyside6-deploy` / Nuitka one-folder
- runtime assets stored next to the app in `runtime/` and `voices/`

That fits the toolchain constraints better than a one-file build and keeps large TTS assets replaceable by the user.

## Documentation

- [Architecture](docs/architecture.md)
- [Roadmap](docs/roadmap.md)
- [Next Agent Handover](docs/next-agent.md)

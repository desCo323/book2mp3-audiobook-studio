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
- quality presets for fast, balanced and natural reading
- persistent Voice-Tuning sessions with random book excerpts and saved voice settings
- optional XTTS runtime path for custom voice profiles
- import pipeline for `TXT`, `PDF` and `EPUB`
- sentence-aware chunking
- resumable per-chunk synthesis
- local `Piper` backend integration
- MP3 segment export and optional single-file concat
- runtime bootstrap script for `Piper`
- handover documentation for follow-up agents

Voice cloning is now modeled as an optional XTTS runtime path. Linux now has an automated standalone Python 3.11 bootstrap for that dedicated XTTS runtime.

## How Users Work With The App

This README is intended to stay current with the actual software state.

Typical workflow:

1. Run `python scripts/bootstrap_runtime.py`
2. Start the app with `book2mp3`
3. Choose a `TXT`, `PDF` or `EPUB`
4. Select a voice
5. Select a quality preset
6. Set priority if you want the project earlier in the queue
7. Create the job
8. Add more jobs if needed
9. Let the queue run, stop it, or resume later

Current user-facing features:

- persistent queue across restarts
- priority-based scheduling
- chunk-based resume
- larger multilingual starter voice pack, sorted by language in the UI, with priority on less mechanical `medium`/`high` Piper models
- quality presets: `Schnell`, `Balanciert`, `Natuerlich`
- `Find Best Setting` as a simple live preview mode: choose a book, hear a random excerpt, tweak 3 controls, press play
- first Voice Lab dialog for collecting custom voice references
- backend choice between `piper` and `xtts`
- detailed logs for debugging

XTTS note:

- XTTS quality usually comes from good speaker reference samples, not from a fixed built-in voice list
- the app can now import an `xtts-webui` style `speakers/` folder into reusable XTTS voice profiles
- the live tuning dialog now supports both `piper` and `xtts` previews
- the main job UI now recommends XTTS with `Premium Natuerlich` when speaker profiles exist
- the app can now auto-detect local `speakers/` folders for XTTS and import them into profiles

## Project layout

- `src/book2mp3/`: application code
- `docs/`: architecture, roadmap, agent handover
- `scripts/bootstrap_runtime.py`: downloads local runtime components
- `ebooksp/`: legacy reference scripts kept for comparison

## Quick start

For a finished end-user bundle, users should start the app directly with:

```bash
./start.sh
```

or on Windows:

```bat
start.bat
```

Those launchers are intended for the self-contained bundle that includes Python inside the app folder.

For source checkout development, the current setup is still:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
python scripts/bootstrap_runtime.py
book2mp3
```

On Windows, activate the virtual environment with:

```powershell
.venv\Scripts\Activate.ps1
```

Then run:

```powershell
pip install -e .
python scripts\bootstrap_runtime.py
book2mp3
```

The bootstrap now installs a starter pack of standard female voices by default when available:

- `de_DE-eva_k-x_low`
- `de_DE-kerstin-low`
- `de_DE-ramona-low`
- `en_US-amy-medium`
- `en_US-kathleen-low`
- `en_GB-alba-medium`
- `en_GB-cori-medium`
- `fr_FR-siwis-low`

## Packaging direction

The intended packaging target is folder-based desktop deployment, not a single giant executable. The portable release must include app-local Python:

- Windows: `pyside6-deploy` / Nuitka one-folder
- Linux: `pyside6-deploy` / Nuitka one-folder
- runtime assets stored next to the app in `runtime/` and `voices/`
- bundled Python stored in `python/<platform>/`

That fits the toolchain constraints better than a one-file build and keeps large TTS assets replaceable by the user.

## Documentation

- [User Guide](docs/user-guide.md)
- [Architecture](docs/architecture.md)
- [Portable Distribution](docs/portable-distribution.md)
- [Roadmap](docs/roadmap.md)
- [Voice Strategy](docs/voice-strategy.md)
- [Next Agent Handover](docs/next-agent.md)
- [Third-Party Notices](THIRD_PARTY_NOTICES.md)

## Smoke test

For a queue and resume smoke test without the GUI:

```bash
python scripts/smoke_queue_resume.py
```

For a voice-tuning session smoke test:

```bash
python scripts/smoke_preview_session.py
```

Additional targeted smoke tests:

```bash
python scripts/smoke_single_file.py
python scripts/smoke_state_migration.py
python scripts/smoke_preview_queue.py
python scripts/smoke_bundle_build.py
python scripts/smoke_portable_linux_runtime.py
python scripts/smoke_linux_release_build.py
python scripts/smoke_xtts_job_model.py
python scripts/smoke_xtts_linux_runtime_bootstrap.py
```

Current validated smoke coverage:

- queue stop/resume flow
- voice-tuning session persistence, saved settings and preview render flow
- `single_file` MP3 output
- legacy `state.json` migration
- preview queue ordering

To validate a built portable bundle:

```bash
python scripts/check_portable_bundle.py /path/to/bundle
```

To assemble a portable bundle skeleton:

```bash
python scripts/build_portable_bundle.py dist/book2mp3-portable --clean
```

To turn that into a local Linux self-contained bundle from the current machine:

```bash
python scripts/populate_bundle_python_linux.py dist/book2mp3-portable
```

Or do the larger Linux release step in one command:

```bash
python scripts/build_linux_portable_release.py dist/book2mp3-linux-portable --archive
```

To bootstrap the optional Linux XTTS runtime with a dedicated standalone Python 3.11:

```bash
python scripts/setup_xtts_runtime.py runtime/xtts/linux --bootstrap-linux-standalone
```

This setup now prefers CPU Torch wheels by default so the portable runtime does not accidentally pull the full CUDA stack.

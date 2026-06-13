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
- persistent profile studio sessions with saved production profiles and release states
- optional XTTS runtime path for custom voice profiles
- import pipeline for `TXT`, `PDF` and `EPUB`
- sentence-aware chunking
- resumable per-chunk synthesis
- local `Piper` backend integration
- MP3 segment export and optional single-file concat
- MP3 metadata tagging plus export `manifest.json` and `chapters.json`
- local CLI for headless job creation and execution
- local REST API for service-style automation
- runtime bootstrap script for `Piper`
- handover documentation for follow-up agents

Voice cloning is now modeled as an optional XTTS runtime path. Linux now has an automated standalone Python 3.11 bootstrap for that dedicated XTTS runtime.

## How Users Work With The App

This README is intended to stay current with the actual software state.

Typical workflow:

1. Run `python scripts/bootstrap_runtime.py`
2. Start the app with `book2mp3`
3. Build or refine a voice/profile setup in `Profilstudio` or `XTTS-Profilstudio`
4. Mark the best result as a released production profile
5. Choose a `TXT`, `PDF` or `EPUB` in `Auftrag`
6. Select the released production profile
7. Set priority if you want the project earlier in the queue
8. Create the job
9. Start the selected job or queue it for later
10. Watch stage progress and export artifacts in `Aufträge`
11. Check runtime and CUDA state in `Diagnose` when needed

Headless workflow:

1. Create a job with `book2mp3-cli create ...`
2. Inspect jobs with `book2mp3-cli list` or `book2mp3-cli inspect <job-id>`
3. Run one job with `book2mp3-cli run <job-id>` or the next queued job with `book2mp3-cli run-next`
4. Start the local API with `book2mp3-cli serve`

Current user-facing features:

- persistent queue across restarts
- priority-based scheduling
- chunk-based resume
- production profiles with `draft`, `tested`, `approved` and `archived`
- job creation only from approved production profiles
- larger multilingual starter voice pack, sorted by language in the UI, with priority on less mechanical `medium`/`high` Piper models
- quality presets: `Schnell`, `Balanciert`, `Natuerlich`
- separate `Profilstudio` for preview, benchmarking and profile refinement
- separate `XTTS-Profilstudio` for speaker profile import and validation
- diagnostics view for workspace, runtime, queue and performance logging
- backend choice between `piper` and `xtts`
- XTTS device mode option with CUDA-first preference when supported
- XTTS CUDA probe in the UI, so users can see whether the runtime really uses CUDA
- custom Piper model import for external `.onnx` + `.onnx.json` voices
- detailed logs for debugging
- output manifests with tagged final MP3 metadata

XTTS note:

- XTTS quality usually comes from good speaker reference samples, not from a fixed built-in voice list
- XTTS speed depends heavily on whether the dedicated XTTS runtime really has working CUDA; the UI now exposes an explicit runtime probe
- the app can now import an `xtts-webui` style `speakers/` folder into reusable XTTS voice profiles
- the live tuning dialog now supports both `piper` and `xtts` previews
- the main job UI now recommends XTTS with `Premium Natuerlich` when speaker profiles exist
- the app can now auto-detect local `speakers/` folders for XTTS and import them into profiles
- the XTTS migration path now also scans common old `xtts-webui` installation locations
- if no old XTTS installation exists, the app can now install starter XTTS sample profiles including English `xtts-webui` examples and German `Thorsten-Voice` examples
- XTTS profiles can now be previewed directly in the UI via their stored reference sample before you run a synthesis test
- for German female XTTS use, the app now also ships cross-language female starter profiles with `de` as target language, based on curated female reference samples

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

For headless local automation:

```bash
book2mp3-cli list
book2mp3-cli voices
book2mp3-cli profiles
book2mp3-cli profile-status mein_profil approved
book2mp3-cli diagnostics
book2mp3-cli create /path/to/book.txt --profile-id mein_profil --language de
book2mp3-cli run-next
book2mp3-cli serve --host 127.0.0.1 --port 8765
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

- [Project Description](docs/project-description.md)
- [Quickstart: Source Checkout](docs/quickstart-source.md)
- [Quickstart: First Audiobook](docs/quickstart-first-audiobook.md)
- [Quickstart: Portable Bundle](docs/quickstart-portable.md)
- [Open-Source and Release Check](docs/open-source-compliance.md)
- [GitHub Pages Landing Page](docs/index.md)
- [User Guide](docs/user-guide.md)
- [Architecture](docs/architecture.md)
- [Requirements V1](docs/anforderungen-book2mp3-v1.md)
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
python scripts/smoke_cli_flow.py
python scripts/smoke_local_api.py
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

To install XTTS directly into that portable app Python too:

```bash
python scripts/install_xtts_into_bundle_python.py dist/book2mp3-portable
```

Or do the larger Linux release step in one command:

```bash
python scripts/build_linux_portable_release.py dist/book2mp3-linux-portable --archive
```

If XTTS should be available directly inside the portable app Python, build with:

```bash
python scripts/build_linux_portable_release.py dist/book2mp3-linux-portable --include-xtts-in-app-python --archive
```

To bootstrap the optional Linux XTTS runtime with a dedicated standalone Python 3.11:

```bash
python scripts/setup_xtts_runtime.py runtime/xtts/linux --bootstrap-linux-standalone
```

This setup now prefers CPU Torch wheels by default so the portable runtime does not accidentally pull the full CUDA stack.

If you want XTTS to try CUDA on NVIDIA systems, use:

```bash
python scripts/setup_xtts_runtime.py runtime/xtts/linux --bootstrap-linux-standalone --torch-variant auto
```

The runtime now probes CUDA after install and reports whether it actually worked.

To make the local `src/` program folder itself self-contained on Linux, populate the embedded app Python directly:

```bash
python scripts/populate_bundle_python_linux.py src
```

After that, `src/start.sh` and `src/book2mp3/start.sh` start with `src/python/linux/` and no longer need a local system Python.

To prepare the local `src/` program folder for Windows as well, including the official embeddable Python and unpacked `win_amd64` dependency wheels:

```bash
python scripts/populate_bundle_python_windows.py src --clean
```

As verified on April 21, 2026, the default Windows embeddable source used by that script is:

```text
https://www.python.org/ftp/python/3.13.13/python-3.13.13-embeddable-amd64.zip
```

# Architecture

## Goal

Build the simplest serious offline-first tool for generating high-quality audiobooks from `PDF`, `TXT` and `EPUB`, with resumability, progress tracking and replaceable voices.

## Why the legacy pipeline was split

The scripts in `ebooksp/` separated the flow into many steps:

1. extract and split text
2. synthesize small audio fragments
3. merge them later
4. clean up already processed fragments

That structure exists for good reasons:

- TTS systems fail more often on long input
- long-running jobs must survive crashes and power loss
- intermediate files make debugging possible
- resume is far easier when each chunk is explicit

The new application keeps the staged model, but formalizes it into persistent jobs.

The next architecture step is no longer GUI-only. The desktop app, CLI and local API
must all use the same core job logic.

## Current architecture

### UI

- `PySide6`
- single desktop window with clear workflow tabs
- `Auftrag` for source + approved production profile only
- `Fertige Bücher` for completed outputs, retagging and cleanup
- `Profile` for profile library, runtime stock and studio entrypoints
- `Betrieb` for queue, stage status, artifacts, logs and diagnostics
- separate `Profilstudio` for preview, benchmark and profile release
- direct `Lexikon` entrypoint into the XTTS pronunciation area
- separate `XTTS-Profilstudio` for speaker profile import and validation

### Shared core and headless access

- `JobManager` remains the file-based execution core
- `Book2Mp3Service` exposes that core for non-GUI callers
- `book2mp3-cli` provides local headless operation
- a local REST API exposes the same operations for automation or service mode
- all three entrypoints must operate on the same workspace layout and state files

### Job model

Each import creates a stable job directory:

```text
workspace/jobs/<job-id>/
  input/
  extracted/
  chunks/
  audio/wav/
  audio/mp3/
  output/
  state.json
```

This makes resume deterministic and keeps cleanup local to one job.

Completed outputs are additionally mirrored to the application root as:

```text
finalbooks/
  <title>/
    *.mp3
    manifest.json
    chapters.json
```

### Persistent queue

The application is designed as a queue runner, not as a single-job launcher.

- users can enqueue multiple jobs
- each job stores a persistent priority in `state.json`
- jobs are sorted by priority, then by age
- only one synthesis worker runs at a time
- on restart, jobs that were `running` are returned to `queued`

This keeps hardware use predictable and avoids CPU or GPU contention from parallel synthesis.

### Pipeline stages

1. Import source file into the job folder
2. Extract normalized text
3. Split text into sentence-aware chunk files
4. For XTTS, derive a spoken working copy with pronunciation rules
5. Synthesize one chunk at a time to WAV
6. Convert WAV to MP3
7. Optionally concatenate MP3 segments into one output file
8. Tag final MP3 outputs and write `manifest.json` plus `chapters.json`
9. Update `state.json` after every meaningful step

### Debug logging

The first version is intentionally log-heavy.

- global application log: `workspace/logs/app.log`
- per-job diagnostic log: `workspace/jobs/<job-id>/job.log`
- every queue transition is logged
- every chunk step is logged
- subprocess calls for `Piper` and `FFmpeg` log stdout and stderr
- failures include Python tracebacks

The purpose is operational clarity first. Log volume can be tuned down later once real failure patterns are known.

### Quality presets

The app now exposes three first-pass presets:

- `fast_cpu`
- `balanced`
- `natural`

They currently tune:

- chunk size
- output mode
- Piper sentence pause
- Piper length scale

This keeps the UX simple while still giving the user meaningful control over rhythm and reliability.

### TTS abstraction

The app is designed around a backend interface:

- `PiperBackend`: implemented now
- `XTTSBackend`: implemented as optional premium path with dedicated runtime and CUDA probe

That separation matters because the user requirement has two distinct needs:

- fast, offline, robust synthesis on CPU and weaker machines
- optional premium voices and voice cloning

`Piper` is the right default engine for the first category. `XTTS` fits the second, but requires heavier runtime, better speaker samples and more careful packaging.

### Pronunciation and metadata layer

The XTTS path now includes a pronunciation layer between chunk text and synthesis:

- profile-bound pronunciation rules
- author-aware auto-rules from the global book lexicon
- spoken-text artifacts per chunk for debugging
- UI suggestions derived from source excerpts and metadata

This keeps the original book text untouched while making name handling reproducible.

## Resume model

Resume is file-based, not memory-based.

- `state.json` stores per-job settings and per-chunk status
- `state.json` also stores queue priority and queue-relevant status
- a chunk is only marked complete after MP3 output exists
- stop requests are cooperative and checked between chunks
- rerunning a job skips completed chunks

This avoids repeating expensive work and makes interrupted runs recoverable.

## Packaging direction

The recommended distribution target is a folder bundle per platform:

- app executable
- embedded Python runtime from deployment tool
- `runtime/piper/<platform>/`
- `voices/`
- `workspace/`

This is more practical than trying to embed large models and FFmpeg into one binary.

## Research-backed decisions

The following current sources informed the initial direction:

- Qt for Python documents `pyside6-deploy` as the official desktop deployment path for Windows and Linux.
- Piper documents local offline synthesis from an executable plus `.onnx` and `.onnx.json` voice files, including JSON input and multi-speaker support.
- Coqui TTS documents `xtts_v2` for multilingual voice cloning and CPU/GPU execution, which fits as a second backend rather than the default one.

## Immediate hardening priorities

1. finish the release-grade `Aufträge` detail view with stronger stage, artifact and error presentation
2. complete CLI/API parity for profile administration and diagnostics
3. harden benchmark, chunk-tuning and XTTS performance workflows
4. validate portable Linux and Windows bundles end-to-end
5. keep architecture docs aligned with the actual GUI/API behavior

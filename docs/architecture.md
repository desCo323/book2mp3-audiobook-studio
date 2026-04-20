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

## Current architecture

### UI

- `PySide6`
- single desktop window
- job creation form
- live status view
- start / stop / resume controls
- log output pane

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
4. Synthesize one chunk at a time to WAV
5. Convert WAV to MP3
6. Optionally concatenate MP3 segments into one output file
7. Update `state.json` after every meaningful step

### Debug logging

The first version is intentionally log-heavy.

- global application log: `workspace/logs/app.log`
- per-job diagnostic log: `workspace/jobs/<job-id>/job.log`
- every queue transition is logged
- every chunk step is logged
- subprocess calls for `Piper` and `FFmpeg` log stdout and stderr
- failures include Python tracebacks

The purpose is operational clarity first. Log volume can be tuned down later once real failure patterns are known.

### TTS abstraction

The app is designed around a backend interface:

- `PiperBackend`: implemented now
- `XTTSBackend`: planned next

That separation matters because the user requirement has two distinct needs:

- fast, offline, robust synthesis on CPU and weaker machines
- optional premium voices and voice cloning

`Piper` is the right default engine for the first category. `XTTS` fits the second, but requires heavier runtime and more careful packaging.

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

## Immediate next engineering steps

1. finish the voice library UI and runtime downloader UX
2. add XTTS backend with optional speaker sample management
3. add chapter-aware output grouping
4. add cleanup policies and retention presets
5. add packaged builds for Linux and Windows

# User Guide

This page is meant to be the current practical guide for people using `book2mp3`.

## What The App Does

`book2mp3` turns `EPUB`, `PDF` and `TXT` files into spoken audio projects.

It does not process a whole book in one fragile step. Instead it:

1. imports the source file
2. extracts clean text
3. splits the text into chunks
4. synthesizes chunk by chunk
5. exports MP3 segments or one combined MP3
6. saves progress after every chunk

That means jobs can be stopped and resumed safely.

## First Start

For the final portable release:

- on Linux: run `./start.sh`
- on Windows: run `start.bat`

That release is intended to include Python inside the application folder.

For the current source repository state, the development bootstrap is still:

Install the runtime and starter voices:

```bash
python scripts/bootstrap_runtime.py
```

Then start the application:

```bash
book2mp3
```

## The Main Screen

### Source file

Choose a `TXT`, `PDF` or `EPUB`.

### Voice

Pick one of the installed Piper voices.

Starter voices currently included by default:

- `de_DE-eva_k-x_low`
- `de_DE-kerstin-low`
- `de_DE-ramona-low`
- `en_US-amy-medium`
- `en_US-kathleen-low`
- `en_GB-alba-medium`
- `en_GB-cori-medium`
- `fr_FR-siwis-low`

### Quality preset

The preset controls chunk size and Piper narration behavior.

- `Schnell`: smaller chunks, good for CPU machines and safer long runs
- `Balanciert`: the recommended default
- `Natuerlich`: slightly slower and calmer reading, more suited for listening quality

### Find Best Setting / Voice Tuning

This mode is now a simple live tuning workflow instead of a static multi-test list.

What it does:

- loads a random excerpt from the selected book
- lets you request a different random excerpt with one click
- lets you tune voice, chunk size, sentence pause and speaking length
- renders a preview immediately from the dialog with one play button
- saves the chosen setup as a reusable voice setting

Simple workflow:

- choose the book
- listen to the random excerpt with `Play Preview jetzt`
- move the sliders until it sounds right
- click `Neue Stelle` if you want to test a different passage
- save the setting when you are satisfied

Recommended voice direction:

- prefer `medium` or `high` voices for audiobook export
- use `low` voices mainly for fast previews or weak CPUs
- for German, try `de_DE-thorsten_emotional-medium` or `de_DE-thorsten-high` first
- for English, try `en_US-lessac-high`, `en_US-libritts-high`, or `en_GB-cori-high`

Recommended starting values:

- `Roman natuerlich`: `240-280` chars, `0.24-0.32s` sentence pause, `1.02-1.08` length
- `Standard ausgewogen`: `200-240` chars, `0.18-0.24s` sentence pause, `0.98-1.03` length
- `Schnell/CPU`: `150-190` chars, `0.10-0.16s` sentence pause, `0.92-0.98` length

### Output mode

- `segments`: keep the result as many MP3 pieces
- `single_file`: concatenate the generated MP3 pieces into one final MP3

### Priority

Higher priority jobs are processed earlier in the queue.

Example:

- `90` for urgent work
- `50` for normal work
- `10` for background work

## Queue Behavior

The queue is persistent.

- you can create several projects
- they are processed one after another
- after a restart, interrupted running jobs go back to the queue
- completed chunks are not regenerated on resume

## Stop And Resume

Use `Stop` to request a clean stop.

The app will not cut the current chunk in half. It stops between chunks and saves the current state. After that:

- select the job again
- use `Start / Resume`
- the app continues from the first unfinished chunk

## Voice Lab

The current `Voice Lab` is the preparation step for custom voices.

What it does now:

- stores custom speaker profiles
- copies reference audio into `workspace/voice_profiles/`
- saves a profile manifest
- shows validation warnings
- can be used by XTTS jobs once a dedicated XTTS runtime is installed

What it does not do yet:

- no one-click custom-voice training workflow
- no built-in guided recording wizard yet

Use it to collect speaker references and then install the optional XTTS runtime when you want to test cloned-voice generation.

## Logs And Troubleshooting

Global app log:

- `workspace/logs/app.log`

Per-job log:

- `workspace/jobs/<job-id>/job.log`

Each job also stores:

- `state.json`
- extracted text
- chunk files
- generated MP3 files

If something fails, these are the first places to inspect.

## Useful Folders

- `runtime/`: local Piper binaries
- `voices/`: installed voice models
- `workspace/jobs/`: all jobs and outputs
- `workspace/voice_profiles/`: Voice Lab profiles
- `workspace/voice_settings/`: saved voice settings from the tuning mode

## Smoke Test

To verify queue and resume behavior without the GUI:

```bash
python scripts/smoke_queue_resume.py
```

## Current Limits

- the optional XTTS path needs its own dedicated runtime setup
- Windows XTTS packaging is not yet validated end-to-end
- chapter-aware export is not finished yet
- packaged desktop builds are not finished yet
- the repo source tree is not yet the final bundled release folder

## Status Rule

This guide should be updated whenever the user-facing workflow changes.

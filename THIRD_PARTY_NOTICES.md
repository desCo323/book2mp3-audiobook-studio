# Third-Party Notices

This file documents the major third-party components currently used by `book2mp3`.

It is a practical notice file, not legal advice. If you distribute `book2mp3`, you should verify the exact licenses and obligations for the final shipped versions and binaries.

## Core application dependencies

### PySide6 6.11.0

- Purpose: desktop GUI
- Source: https://pypi.org/project/PySide6/
- License metadata observed locally: `LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only`

### shiboken6 6.11.0

- Purpose: binding helper used by PySide6
- Source: https://pypi.org/project/shiboken6/
- License metadata observed locally: `LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only`

### beautifulsoup4 4.13.4

- Purpose: EPUB/HTML text extraction
- Source: https://pypi.org/project/beautifulsoup4/
- License metadata observed locally: `MIT License`

### pypdf 6.10.2

- Purpose: PDF text extraction
- Source: https://github.com/py-pdf/pypdf
- Local package metadata shows: `license_expression = BSD-3-Clause`

### requests 2.32.3

- Purpose: runtime and voice downloads
- Source: https://requests.readthedocs.io/
- License metadata observed locally: `Apache-2.0`

### imageio-ffmpeg 0.6.0

- Purpose: Python wrapper used to locate and execute FFmpeg
- Source: https://github.com/imageio/imageio-ffmpeg
- Upstream wrapper license: `BSD-2-Clause`

## Runtime and binary components

### XTTS starter speaker samples

- Purpose: optional starter XTTS voice-profile samples so the XTTS path is not empty on first use
- Source repository: https://github.com/daswer123/xtts-webui
- Sample folder used by the app: https://github.com/daswer123/xtts-webui/tree/main/speakers
- Repository license shown upstream: `MIT`

Additional German starter source:

- Dataset: https://huggingface.co/datasets/Thorsten-Voice/TV-44kHz-Full
- Dataset page states: `License: CC0`
- Dataset page describes the `TV-2022.10-Neutral` subset as a single German male speaker with clear, high-quality speech

Important note:

- The app currently pulls the sample WAV files `calm_female.wav`, `female.wav` and `male.wav` from that upstream repository when the user installs XTTS starter speakers.
- The app now also pulls a few German starter WAV files at install time from the Thorsten-Voice dataset through the Hugging Face datasets API.
- Some German female starter profiles are currently built from curated public female reference samples while targeting German generation in XTTS. Those still reuse the `xtts-webui` sample WAV files listed above.
- If you redistribute those starter samples, you should preserve attribution to the upstream repository and re-check the upstream licensing state at release time.

### Piper runtime

- Purpose: local text-to-speech synthesis
- Source: https://github.com/rhasspy/piper
- Upstream repository license: `MIT`

Important upstream note:

- Piper voice models are not all covered by one simple blanket assumption.
- Piper upstream explicitly states that each voice `MODEL_CARD` contains important licensing information.

For that reason, `book2mp3` now downloads `MODEL_CARD` together with each installed voice.

### Piper voices

- Source: https://huggingface.co/rhasspy/piper-voices
- Important note from Piper upstream: each voice may have its own licensing terms in `MODEL_CARD`

The application currently installs starter voices into `voices/...`. Their individual `MODEL_CARD` files should be preserved and distributed with the voice files.

### FFmpeg binary used through imageio-ffmpeg

- The Python wrapper `imageio-ffmpeg` is BSD-2-Clause.
- The currently observed bundled Linux FFmpeg binary comes from John Van Sickle static builds.
- John Van Sickle's site states that those static builds are licensed under `GNU GPL version 3`.

This matters for redistribution. If `book2mp3` ships that FFmpeg binary in releases, the release process must preserve the corresponding FFmpeg license notices and source-offer obligations required by that distribution path.

Source:

- https://johnvansickle.com/ffmpeg/

## Portable Python runtime

The planned portable distribution includes app-local Python.

For Windows bundles, the intended source is the official Python embeddable package published on Python.org release pages.

Relevant references:

- https://www.python.org/downloads/windows/
- https://docs.python.org/3.10/using/windows.html

## Important compliance risk

### EbookLib 0.20

- Purpose: EPUB parsing
- Source: https://github.com/aerkalov/ebooklib
- Local package metadata observed: `GNU Affero General Public License`

This is not a minor detail. `AGPL` is a strong copyleft license and may impose obligations that are incompatible with how you may want to distribute a desktop product.

Inference from the observed metadata:

- If `book2mp3` is distributed with EbookLib as part of the application, this dependency needs a deliberate legal and architectural decision.
- A safer future path may be to replace `ebooklib` with a permissively licensed EPUB parser.

## Files that should remain with distributed bundles

- this `THIRD_PARTY_NOTICES.md`
- all upstream license files shipped by bundled runtimes
- `MODEL_CARD` files for bundled voices

## Sources used for this notice file

- Local package metadata from the installed Python environment
- Piper upstream repository and voice documentation
- imageio-ffmpeg upstream repository
- John Van Sickle FFmpeg static build site
- Python.org Windows distribution pages and docs

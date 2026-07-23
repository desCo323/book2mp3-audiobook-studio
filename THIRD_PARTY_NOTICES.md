# Third-Party Notices

This file documents the major third-party components used by `book2mp3`.

It is a practical notice file, not legal advice.

For the current publication assessment, also read:

- [docs/open-source-compliance.md](docs/open-source-compliance.md)

## Project license

The `book2mp3` source code written in this repository is licensed under the root [LICENSE](LICENSE) file.

That license does **not** replace or override the licenses of bundled or downloaded third-party components.

## Core dependencies

### PySide6 / Qt for Python

- Purpose: desktop GUI
- Source: https://pypi.org/project/PySide6/
- Official licensing summary: LGPLv3, GPL variants, or commercial licensing
- Additional obligations reference: https://www.qt.io/development/open-source-lgpl-obligations

### Beautiful Soup 4

- Purpose: HTML / EPUB parsing support
- Source: https://www.crummy.com/software/BeautifulSoup/
- License: MIT

### pypdf

- Purpose: PDF parsing and metadata handling
- Source: https://pypdf.readthedocs.io/en/stable/meta/faq.html
- License: BSD-3-Clause

### requests

- Purpose: network downloads for runtime and voice bootstrap
- Source: https://pypi.org/project/requests/
- License: Apache-2.0

### imageio-ffmpeg

- Purpose: Python wrapper and FFmpeg binary lookup
- Source: https://github.com/imageio/imageio-ffmpeg
- Wrapper license: BSD-2-Clause

### Python runtime

- Purpose: app-local runtime in portable bundles
- Source: https://docs.python.org/3/license.html
- License: PSF-2.0

## TTS runtimes and models

### Piper engine

- Purpose: local standard TTS backend
- Source: https://github.com/rhasspy/piper
- License: MIT

### Piper voices

- Source: https://huggingface.co/rhasspy/piper-voices
- Repository page shows: MIT
- Important upstream rule: individual voices carry additional provenance and dataset licensing information in their `MODEL_CARD` files

`book2mp3` downloads `MODEL_CARD` together with each voice. If you distribute bundled voices, preserve those files.

Observed locally in the default voice store:

- some voices use CC0 datasets
- some voices use CC-BY 4.0 datasets
- some voices use public-domain sources
- at least one bundled voice references CC-BY-SA 4.0 in its `MODEL_CARD`

That means a release bundle should not claim a single blanket voice license.

### Coqui TTS toolkit

- Purpose: XTTS runtime code
- Source: https://github.com/coqui-ai/TTS
- License: MPL-2.0

### XTTS-v2 model

- Purpose: multilingual cloning model used by the optional XTTS path
- Source: https://huggingface.co/coqui/XTTS-v2
- Model license: Coqui Public Model License 1.0.0

Important note:

- the official XTTS-v2 model license states non-commercial restrictions
- therefore an `as-is` commercial XTTS bundle is not currently a clean release path

### XTTS starter profiles and samples

- `book2mp3` can install starter profile samples from:
  - https://github.com/rhasspy/dataset-voice-kerstin
  - https://huggingface.co/datasets/alibabasglab/LJSpeech-1.1-48kHz
  - https://huggingface.co/voices/VCTK_British_English_Females
  - https://github.com/daswer123/xtts-webui
  - https://huggingface.co/datasets/Thorsten-Voice/TV-44kHz-Full
- Kerstin voice dataset license: CC0-1.0
- LJSpeech-1.1-48kHz sample pack license: Apache-2.0; derived from public-domain LJ Speech recordings
- VCTK British English female sample model card license: CC-BY-4.0
- `xtts-webui` repository license: MIT
- Thorsten-Voice dataset license: CC0

The app currently pulls sample WAV/FLAC files from these public upstream sources when the user installs starter XTTS profiles. Those sources should be documented in distributed bundles.

## EPUB dependency risk

### EbookLib

- Purpose: EPUB parsing
- Source: https://github.com/aerkalov/ebooklib
- Upstream project states: AGPL

This is a real compliance issue for distribution strategy. If `book2mp3` continues to ship with EbookLib in the application environment, the release plan should treat AGPL as an explicit legal and product decision rather than an incidental dependency.

## FFmpeg note

The Python wrapper is permissively licensed, but the actual FFmpeg binary shipped in a bundle may come from a different source and license.

Current project documentation references Linux static builds from:

- https://johnvansickle.com/ffmpeg/

If those binaries are redistributed, keep the corresponding FFmpeg license notices and source-availability obligations for that exact binary source.

## What should remain in release bundles

- this `THIRD_PARTY_NOTICES.md`
- upstream runtime license files where available
- relevant model licenses
- all `MODEL_CARD` files for bundled Piper voices
- the root `LICENSE`

# Voice Strategy

## Goal

The product needs two different voice paths:

1. very robust offline voices that work well on CPU-only machines
2. optional custom voices for users who want a specific narrator identity

The first path should ship with `Piper` support. The second path should be added with `XTTS v2`.

## Research summary

### What makes audiobook output sound natural

Based on the current official documentation reviewed during implementation:

- `XTTS v2` supports voice cloning from one or multiple reference recordings and multilingual generation.
- `Piper` expects local `.onnx` and `.onnx.json` files per voice and is suited for offline packaged use.
- OpenAI's current TTS guide emphasizes that the model copies the reference sample's tone, cadence, energy, pauses and speaking habits, which matches practical voice-cloning experience in other systems as well.

### Practical implications for this project

Natural audiobook output depends on much more than selecting a model.

- Text normalization must remove OCR garbage, duplicated whitespace and broken hyphenation.
- Chunking should respect sentences and punctuation.
- Very long chunks reduce reliability and prosody quality.
- The app must allow punctuation-aware pause tuning.
- Chapter boundaries should be treated as stronger pause boundaries than ordinary sentence boundaries.
- Users need different presets for `fast CPU`, `balanced`, and `premium natural`.

## Recommended backend split

### Default backend: Piper

Use `Piper` as the default because it is:

- offline
- local
- lightweight compared with XTTS
- practical for packaged Windows and Linux desktop builds

Use it for:

- standard voices
- low-friction installation
- CPU-friendly jobs

For the first usable version, the app should ship with a small default voice pack when available:

- `de_DE-eva_k-x_low`
- `de_DE-kerstin-low`
- `de_DE-ramona-low`
- `en_US-amy-medium`
- `en_US-kathleen-low`
- `en_GB-alba-medium`
- `en_GB-cori-medium`
- `fr_FR-siwis-low`

### Premium backend: XTTS v2

Use `XTTS v2` for:

- user-created narrator voices
- multiple reference samples
- more expressive narration when GPU is available

Keep it optional because runtime size and hardware demands are higher.

## New voice creation design

The app should expose a guided workflow instead of a generic file picker.

### User flow

1. Create a voice profile
2. Record or import consent audio
3. Record or import one or more clean reference clips
4. Validate sample quality automatically
5. Generate a preview sentence
6. Save the voice profile for reuse

### What the validator should check

- file format supported
- sample duration in expected range
- clipping detection
- background noise estimate
- silence at beginning and end
- average loudness consistency
- sample rate normalization

### Recommended capture guidance

For the UI guidance, we should instruct the user to:

- record in a quiet room with minimal echo
- keep constant distance to the microphone
- use the exact narration style desired for the final audiobook
- avoid music, reverb and room noise
- provide multiple short samples with consistent tone and pace

## Engineering decisions for next phase

1. Add a `voice_profiles/` directory with one manifest per custom voice.
2. Implement `XTTSBackend`.
3. Add a `Voice Lab` screen in the GUI.
4. Add preview generation before a full book run.
5. Add narration presets that tune chunk size and pause behavior.

## Sources

- Coqui XTTS docs: https://docs.coqui.ai/en/latest/models/xtts.html
- OpenAI TTS guide: https://developers.openai.com/api/docs/guides/text-to-speech
- Piper voices and model packaging: https://github.com/rhasspy/piper/blob/master/VOICES.md

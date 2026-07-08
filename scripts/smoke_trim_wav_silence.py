from __future__ import annotations

import math
import tempfile
import wave
from pathlib import Path

from book2mp3.pipeline.audio import probe_media_duration_seconds, trim_wav_silence_in_place


def write_tone_and_silence_wav(path: Path) -> None:
    sample_rate = 24000
    segments = [
        ("tone", 0.60),
        ("silence", 2.40),
        ("tone", 0.55),
        ("silence", 2.20),
    ]
    frames = bytearray()
    for kind, seconds in segments:
        frame_count = int(sample_rate * seconds)
        for index in range(frame_count):
            if kind == "tone":
                value = int(9000 * math.sin(2 * math.pi * 440 * index / sample_rate))
            else:
                value = 0
            frames.extend(value.to_bytes(2, byteorder="little", signed=True))
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(bytes(frames))


def write_silent_wav(path: Path) -> None:
    sample_rate = 24000
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(b"\x00\x00" * sample_rate)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="book2mp3-trim-wav-") as tmp_dir:
        root = Path(tmp_dir)
        noisy = root / "long_silence.wav"
        write_tone_and_silence_wav(noisy)
        before = probe_media_duration_seconds(noisy)
        changed = trim_wav_silence_in_place(noisy)
        after = probe_media_duration_seconds(noisy)
        if not changed:
            raise AssertionError("Expected long-silence WAV to be compressed")
        if before < 5.5 or after > 3.4:
            raise AssertionError(f"Unexpected trim duration before={before:.3f}s after={after:.3f}s")

        silent = root / "silent.wav"
        write_silent_wav(silent)
        silent_before = probe_media_duration_seconds(silent)
        silent_changed = trim_wav_silence_in_place(silent)
        silent_after = probe_media_duration_seconds(silent)
        if silent_changed or abs(silent_before - silent_after) > 0.01:
            raise AssertionError("Completely silent WAV should remain unchanged")

        print(
            {
                "long_silence_before": round(before, 3),
                "long_silence_after": round(after, 3),
                "silent_unchanged": round(silent_after, 3),
            }
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

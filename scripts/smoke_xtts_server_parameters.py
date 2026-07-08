from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np

import xtts_worker


class FakeModel:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def inference(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "wav": np.zeros(1200, dtype=np.float32),
        }


class FakeConfig:
    gpt_cond_len = 12
    gpt_cond_chunk_len = 4
    max_ref_len = 10
    sound_norm_refs = False


class FakeSynthesizer:
    def __init__(self) -> None:
        self.tts_model = FakeModel()
        self.tts_config = FakeConfig()
        self.output_sample_rate = 24000


class FakeTts:
    def __init__(self) -> None:
        self.synthesizer = FakeSynthesizer()


def main() -> int:
    fake_tts = FakeTts()
    captured_conditioning: dict[str, object] = {}
    original_get_tts = xtts_worker.get_tts
    original_conditioning = xtts_worker.get_conditioning_latents

    def fake_get_tts(_tts_cache, _model_name, _device_mode):
        return fake_tts

    def fake_conditioning(payload, _tts, _conditioning_cache):
        captured_conditioning.update(xtts_worker.conditioning_options_from_payload(payload))
        return "gpt-latent", "speaker-embedding"

    xtts_worker.get_tts = fake_get_tts
    xtts_worker.get_conditioning_latents = fake_conditioning
    try:
        with tempfile.TemporaryDirectory(prefix="book2mp3-xtts-server-params-") as tmp_dir:
            output_file = Path(tmp_dir) / "sample.wav"
            payload = {
                "texts": ["Conall Viga Feilan sprach in einem langen zusammenhaengenden Satz."],
                "language": "de",
                "speaker_wav": ["speaker.wav"],
                "model_name": "tts_models/multilingual/multi-dataset/xtts_v2",
                "output_files": [str(output_file)],
                "length_scale": 1.02,
                "enable_text_splitting": True,
                "device_mode": "cpu",
                "xtts_inference": {
                    "temperature": 0.62,
                    "top_p": 0.85,
                    "top_k": 50,
                    "repetition_penalty": 5.0,
                    "length_penalty": 1.0,
                    "num_beams": 2,
                    "do_sample": True,
                    "enable_text_splitting": False,
                    "gpt_cond_len": 30,
                    "gpt_cond_chunk_len": 4,
                    "max_ref_length": 30,
                    "sound_norm_refs": True,
                    "librosa_trim_db": 30,
                },
            }
            written = xtts_worker.synthesize_payload(payload, {}, {})
            if written != [str(output_file)] or not output_file.exists() or output_file.stat().st_size <= 128:
                raise AssertionError(f"Expected synthesized fake WAV at {output_file}, got {written}")
            call = fake_tts.synthesizer.tts_model.calls[0]
            expected_call_values = {
                "temperature": 0.62,
                "top_p": 0.85,
                "top_k": 50,
                "repetition_penalty": 5.0,
                "length_penalty": 1.0,
                "num_beams": 2,
                "do_sample": True,
                "enable_text_splitting": False,
            }
            for key, expected in expected_call_values.items():
                if call.get(key) != expected:
                    raise AssertionError(f"Expected inference {key}={expected!r}, got {call.get(key)!r}")
            expected_conditioning = {
                "gpt_cond_len": 30,
                "gpt_cond_chunk_len": 4,
                "max_ref_length": 30,
                "sound_norm_refs": True,
                "librosa_trim_db": 30.0,
            }
            if captured_conditioning != expected_conditioning:
                raise AssertionError(f"Expected conditioning {expected_conditioning}, got {captured_conditioning}")
            print(
                {
                    "output_file": str(output_file),
                    "inference": {key: call[key] for key in expected_call_values},
                    "conditioning": captured_conditioning,
                }
            )
    finally:
        xtts_worker.get_tts = original_get_tts
        xtts_worker.get_conditioning_latents = original_conditioning
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import contextlib
import json
import sys
import traceback
from pathlib import Path

import numpy as np


def patch_transformers_exports() -> None:
    try:
        import transformers
        from transformers.generation.beam_search import BeamSearchScorer
    except Exception:
        return
    transformers.__dict__["BeamSearchScorer"] = BeamSearchScorer
    try:
        from transformers import BeamSearchScorer as exported_beam_search_scorer
    except Exception:
        return
    if exported_beam_search_scorer is not BeamSearchScorer:
        transformers.__dict__["BeamSearchScorer"] = BeamSearchScorer


def patch_torch_load_defaults() -> None:
    try:
        import torch
    except Exception:
        return

    original_torch_load = torch.load

    def compat_torch_load(*args, **kwargs):
        kwargs.setdefault("weights_only", False)
        return original_torch_load(*args, **kwargs)

    torch.load = compat_torch_load


def patch_torchaudio_load() -> None:
    try:
        import soundfile as sf
        import torch
        import torchaudio
    except Exception:
        return

    def compat_load(filepath, frame_offset=0, num_frames=-1, normalize=True, channels_first=True, format=None, buffer_size=4096, backend=None):
        del normalize, format, buffer_size, backend
        audio, sample_rate = sf.read(str(filepath), dtype="float32", always_2d=True)
        if frame_offset:
            audio = audio[frame_offset:]
        if num_frames not in (-1, None):
            audio = audio[:num_frames]
        if channels_first:
            audio = audio.T
        tensor = torch.from_numpy(np.ascontiguousarray(audio))
        return tensor, sample_rate

    torchaudio.load = compat_load


def warm_up_xtts_imports() -> None:
    patch_transformers_exports()
    patch_torch_load_defaults()
    patch_torchaudio_load()
    import TTS.tts.layers.xtts.stream_generator  # noqa: F401


def get_tts(tts_cache: dict[str, object], model_name: str):
    warm_up_xtts_imports()
    try:
        from TTS.api import TTS
    except Exception as exc:
        raise SystemExit(f"XTTS runtime is not installed correctly: {exc}")
    tts = tts_cache.get(model_name)
    if tts is None:
        with contextlib.redirect_stdout(sys.stderr):
            tts = TTS(model_name)
        tts_cache[model_name] = tts
    return tts


def synthesize_payload(payload: dict[str, object], tts_cache: dict[str, object]) -> list[str]:
    texts = payload.get("texts")
    output_files = payload.get("output_files")
    if texts is None:
        texts = [payload["text"]]
    if output_files is None:
        output_files = [payload["output_file"]]
    if len(texts) != len(output_files):
        raise ValueError("XTTS payload mismatch: texts and output_files must have same length")

    tts = get_tts(tts_cache, str(payload["model_name"]))
    written_files: list[str] = []
    for text, output_file_value in zip(texts, output_files, strict=True):
        output_file = Path(output_file_value)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with contextlib.redirect_stdout(sys.stderr):
            tts.tts_to_file(
                text=text,
                speaker_wav=payload["speaker_wav"],
                language=payload["language"],
                file_path=str(output_file),
                speed=1.0 / float(payload.get("length_scale", 1.0)),
            )
        written_files.append(str(output_file))
    return written_files


def run_one_shot() -> int:
    payload = json.loads(sys.stdin.read())
    written_files = synthesize_payload(payload, {})
    print(json.dumps({"ok": True, "output_files": written_files}))
    return 0


def run_server() -> int:
    tts_cache: dict[str, object] = {}
    for line in sys.stdin:
        message = line.strip()
        if not message:
            continue
        try:
            payload = json.loads(message)
            if payload.get("command") == "shutdown":
                print(json.dumps({"ok": True, "shutdown": True}), flush=True)
                return 0
            written_files = synthesize_payload(payload, tts_cache)
            print(json.dumps({"ok": True, "output_files": written_files}), flush=True)
        except Exception as exc:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "error": str(exc),
                        "traceback": traceback.format_exc(),
                    }
                ),
                flush=True,
            )
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", action="store_true", help="Run as a persistent JSON-line XTTS worker")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.server:
        return run_server()
    return run_one_shot()


if __name__ == "__main__":
    raise SystemExit(main())

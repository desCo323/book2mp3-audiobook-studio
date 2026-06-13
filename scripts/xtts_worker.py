from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import sys
import time
import traceback
from contextlib import nullcontext
from pathlib import Path

import numpy as np
import soundfile as sf

try:
    from book2mp3.utils.perf_logging import perf_event, perf_scope
except Exception:  # pragma: no cover - dedicated runtime can still run without app imports
    def perf_event(*args, **kwargs):  # type: ignore[no-redef]
        return None

    def perf_scope(*args, **kwargs):  # type: ignore[no-redef]
        return nullcontext()


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


def worker_log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def configure_torch_runtime(torch, use_cuda: bool) -> None:
    cpu_threads = max(1, min(os.cpu_count() or 1, 8))
    try:
        torch.set_num_threads(cpu_threads)
    except Exception:
        pass
    if not use_cuda:
        return
    try:
        torch.backends.cuda.matmul.allow_tf32 = True
    except Exception:
        pass
    try:
        torch.backends.cudnn.allow_tf32 = True
        torch.backends.cudnn.benchmark = True
    except Exception:
        pass


def get_tts(tts_cache: dict[str, object], model_name: str, device_mode: str):
    with perf_scope("xtts.imports_and_model", category="xtts", model_name=model_name, device_mode=device_mode):
        warm_up_xtts_imports()
        try:
            from TTS.api import TTS
            import torch
        except Exception as exc:
            raise SystemExit(f"XTTS runtime is not installed correctly: {exc}")
        cache_key = f"{model_name}::{device_mode}"
        tts = tts_cache.get(cache_key)
        if tts is None:
            cuda_available = bool(torch.cuda.is_available())
            if device_mode == "cuda" and not cuda_available:
                raise RuntimeError("CUDA wurde fuer XTTS erzwungen, ist in dieser Runtime aber nicht verfuegbar.")
            use_cuda = cuda_available if device_mode == "auto" else device_mode == "cuda"
            configure_torch_runtime(torch, use_cuda)
            load_started = time.perf_counter()
            with contextlib.redirect_stdout(sys.stderr):
                tts = TTS(model_name, gpu=use_cuda)
            load_seconds = round(time.perf_counter() - load_started, 3)
            perf_event(
                "xtts.model_loaded",
                category="xtts",
                model_name=model_name,
                device_mode=device_mode,
                use_cuda=use_cuda,
                torch_version=torch.__version__,
                cuda_available=torch.cuda.is_available(),
                duration_ms=round(load_seconds * 1000, 3),
            )
            worker_log(
                "XTTS model loaded "
                f"model={model_name} device_mode={device_mode} use_cuda={use_cuda} "
                f"torch={torch.__version__} cuda_available={torch.cuda.is_available()} "
                f"in {load_seconds:.2f}s"
            )
            tts_cache[cache_key] = tts
        return tts


def model_device(model) -> object | None:
    device = getattr(model, "device", None)
    if device is not None:
        return device
    try:
        return next(model.parameters()).device
    except Exception:
        return None


def move_latents_to_device(latents: tuple[object, object], device: object | None) -> tuple[object, object]:
    if device is None:
        return latents
    moved: list[object] = []
    for item in latents:
        if hasattr(item, "to"):
            moved.append(item.to(device))
        else:
            moved.append(item)
    return moved[0], moved[1]


def cpu_copy_latents(latents: tuple[object, object]) -> tuple[object, object]:
    copied: list[object] = []
    for item in latents:
        if hasattr(item, "detach") and hasattr(item, "cpu"):
            copied.append(item.detach().cpu())
        elif hasattr(item, "cpu"):
            copied.append(item.cpu())
        else:
            copied.append(item)
    return copied[0], copied[1]


def speaker_cache_key(payload: dict[str, object]) -> str:
    sample_paths = payload.get("speaker_wav") or []
    if not isinstance(sample_paths, list):
        sample_paths = [sample_paths]
    digest = hashlib.sha256()
    digest.update(str(payload.get("model_name", "")).encode("utf-8"))
    for sample_path in sample_paths:
        path = Path(str(sample_path))
        digest.update(str(path.resolve()).encode("utf-8"))
        try:
            stat = path.stat()
            digest.update(str(stat.st_mtime_ns).encode("utf-8"))
            digest.update(str(stat.st_size).encode("utf-8"))
        except FileNotFoundError:
            digest.update(b"missing")
    return digest.hexdigest()


def conditioning_cache_path(payload: dict[str, object]) -> Path | None:
    cache_dir_value = str(payload.get("conditioning_cache_dir", "") or "").strip()
    if not cache_dir_value:
        return None
    cache_dir = Path(cache_dir_value)
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / f"{speaker_cache_key(payload)}.pt"


def get_conditioning_latents(
    payload: dict[str, object],
    tts,
    conditioning_cache: dict[str, tuple[object, object]],
) -> tuple[object, object]:
    import torch

    cache_key = speaker_cache_key(payload)
    cached = conditioning_cache.get(cache_key)
    if cached is not None:
        worker_log(f"XTTS conditioning cache hit key={cache_key[:12]}")
        perf_event("xtts.conditioning_cache_hit", category="xtts", key=cache_key[:12], source="memory")
        return cached

    cache_path = conditioning_cache_path(payload)
    model = tts.synthesizer.tts_model
    device = model_device(model)
    if cache_path is not None and cache_path.exists():
        with perf_scope("xtts.conditioning_disk_cache_load", category="xtts", key=cache_key[:12]):
            started = time.perf_counter()
            saved = torch.load(cache_path, map_location="cpu")
            loaded = (saved["gpt_cond_latent"], saved["speaker_embedding"])
            latents = move_latents_to_device(loaded, device)
            conditioning_cache[cache_key] = latents
            worker_log(
                f"XTTS conditioning disk cache hit key={cache_key[:12]} loaded_in={time.perf_counter() - started:.2f}s"
            )
            return latents

    config = tts.synthesizer.tts_config
    started = time.perf_counter()
    with perf_scope(
        "xtts.conditioning_compute",
        category="xtts",
        key=cache_key[:12],
        sample_count=len(payload.get("speaker_wav") or []),
    ):
        with contextlib.redirect_stdout(sys.stderr), torch.inference_mode():
            latents = model.get_conditioning_latents(
                audio_path=payload["speaker_wav"],
                gpt_cond_len=config.gpt_cond_len,
                gpt_cond_chunk_len=config.gpt_cond_chunk_len,
                max_ref_length=config.max_ref_len,
                sound_norm_refs=config.sound_norm_refs,
            )
    conditioning_cache[cache_key] = latents
    if cache_path is not None:
        try:
            torch.save(
                {
                    "gpt_cond_latent": cpu_copy_latents(latents)[0],
                    "speaker_embedding": cpu_copy_latents(latents)[1],
                },
                cache_path,
            )
        except OSError as exc:
            worker_log(f"XTTS conditioning cache save failed key={cache_key[:12]} error={exc}")
    worker_log(
        f"XTTS conditioning cache miss key={cache_key[:12]} computed_in={time.perf_counter() - started:.2f}s"
    )
    return latents


def save_output_wav(tts, wav: np.ndarray, output_file: Path) -> None:
    with perf_scope("xtts.save_wav", category="xtts", output_file=output_file, samples=len(wav)):
        output_file.parent.mkdir(parents=True, exist_ok=True)
        sample_rate = int(tts.synthesizer.output_sample_rate)
        sf.write(str(output_file), wav, sample_rate)


def synthesize_payload(
    payload: dict[str, object],
    tts_cache: dict[str, object],
    conditioning_cache: dict[str, tuple[object, object]],
) -> list[str]:
    import torch

    texts = payload.get("texts")
    output_files = payload.get("output_files")
    if texts is None:
        texts = [payload["text"]]
    if output_files is None:
        output_files = [payload["output_file"]]
    if len(texts) != len(output_files):
        raise ValueError("XTTS payload mismatch: texts and output_files must have same length")

    request_started = time.perf_counter()
    device_mode = str(payload.get("device_mode", "auto"))
    with perf_scope(
        "xtts.request",
        category="xtts",
        text_count=len(texts),
        total_chars=sum(len(str(text)) for text in texts),
        device_mode=device_mode,
        language=payload.get("language", ""),
    ):
        tts = get_tts(tts_cache, str(payload["model_name"]), device_mode)
        model = tts.synthesizer.tts_model
        gpt_cond_latent, speaker_embedding = get_conditioning_latents(payload, tts, conditioning_cache)
        enable_text_splitting = bool(payload.get("enable_text_splitting", False))
        speed = 1.0 / float(payload.get("length_scale", 1.0))
        written_files: list[str] = []
        per_text_timings: list[dict[str, object]] = []
        for index, (text, output_file_value) in enumerate(zip(texts, output_files, strict=True), start=1):
            output_file = Path(output_file_value)
            started = time.perf_counter()
            with perf_scope(
                "xtts.inference",
                category="xtts",
                index=index,
                chars=len(text),
                split=enable_text_splitting,
                speed=speed,
            ):
                with contextlib.redirect_stdout(sys.stderr), torch.inference_mode():
                    result = model.inference(
                        text=text,
                        language=payload["language"],
                        gpt_cond_latent=gpt_cond_latent,
                        speaker_embedding=speaker_embedding,
                        speed=speed,
                        enable_text_splitting=enable_text_splitting,
                    )
            save_output_wav(tts, result["wav"], output_file)
            written_files.append(str(output_file))
            per_text_timings.append(
                {
                    "index": index,
                    "chars": len(text),
                    "seconds": round(time.perf_counter() - started, 2),
                }
            )
        worker_log(
            "XTTS request complete "
            f"texts={len(texts)} split={enable_text_splitting} speed={speed:.3f} device_mode={device_mode} "
            f"total={time.perf_counter() - request_started:.2f}s details={json.dumps(per_text_timings, ensure_ascii=False)}"
        )
        return written_files


def warmup_payload(
    payload: dict[str, object],
    tts_cache: dict[str, object],
    conditioning_cache: dict[str, tuple[object, object]],
) -> dict[str, object]:
    device_mode = str(payload.get("device_mode", "auto"))
    with perf_scope("xtts.warmup", category="xtts", model_name=payload.get("model_name", ""), device_mode=device_mode):
        tts = get_tts(tts_cache, str(payload["model_name"]), device_mode)
        warmed_conditioning = False
        speaker_wav = payload.get("speaker_wav") or []
        if speaker_wav:
            get_conditioning_latents(payload, tts, conditioning_cache)
            warmed_conditioning = True
        return {"model_name": str(payload["model_name"]), "warmed_conditioning": warmed_conditioning}


def run_one_shot() -> int:
    payload = json.loads(sys.stdin.read())
    written_files = synthesize_payload(payload, {}, {})
    print(json.dumps({"ok": True, "output_files": written_files}))
    return 0


def run_server() -> int:
    tts_cache: dict[str, object] = {}
    conditioning_cache: dict[str, tuple[object, object]] = {}
    worker_log("XTTS persistent server ready")
    try:
        for line in sys.stdin:
            message = line.strip()
            if not message:
                continue
            try:
                payload = json.loads(message)
                if payload.get("command") == "shutdown":
                    print(json.dumps({"ok": True, "shutdown": True}), flush=True)
                    return 0
                if payload.get("command") == "warmup":
                    details = warmup_payload(payload, tts_cache, conditioning_cache)
                    print(json.dumps({"ok": True, "warmup": True, "details": details}), flush=True)
                    continue
                written_files = synthesize_payload(payload, tts_cache, conditioning_cache)
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
    except KeyboardInterrupt:
        worker_log("XTTS persistent server interrupted during shutdown")
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

from __future__ import annotations

import argparse
import json
import subprocess
import sys


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--require-cuda", action="store_true", help="Exit non-zero when CUDA is unavailable")
    return parser.parse_args()


def host_nvidia_smi() -> dict[str, object]:
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            check=True,
        )
        gpus = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        return {"found": True, "gpus": gpus}
    except Exception as exc:
        return {"found": False, "error": str(exc), "gpus": []}


def main() -> int:
    args = parse_args()
    try:
        import torch
    except Exception as exc:
        payload = {"ok": False, "error": f"torch import failed: {exc}"}
        print(json.dumps(payload, indent=2))
        return 2

    cuda_available = bool(torch.cuda.is_available())
    gpu_names: list[str] = []
    device_count = int(torch.cuda.device_count()) if cuda_available else 0
    allocation_ok = False
    allocation_error = ""
    if cuda_available:
        try:
            for index in range(device_count):
                gpu_names.append(torch.cuda.get_device_name(index))
            tensor = torch.tensor([1.0], device="cuda")
            allocation_ok = bool(float(tensor.item()) == 1.0)
        except Exception as exc:
            allocation_error = str(exc)
            cuda_available = False
            device_count = 0
            gpu_names = []

    payload = {
        "ok": True,
        "python": sys.executable,
        "torch_version": torch.__version__,
        "cuda_available": cuda_available,
        "device_count": device_count,
        "gpu_names": gpu_names,
        "allocation_ok": allocation_ok,
        "allocation_error": allocation_error,
        "host_nvidia_smi": host_nvidia_smi(),
    }
    print(json.dumps(payload, indent=2))
    if args.require_cuda and not cuda_available:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

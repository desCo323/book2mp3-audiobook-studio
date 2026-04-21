from __future__ import annotations

import json
from pathlib import Path

from book2mp3.tts.xtts import XttsBackend


ROOT = Path("/home/codex/repo/book2mp3")


def main() -> int:
    backend = XttsBackend(ROOT / "src" / "runtime", device_mode="auto")
    if not backend.is_available():
        raise AssertionError(f"XTTS runtime unavailable: {backend.availability_reason()}")
    probe = backend.runtime_probe()
    if "cuda_available" not in probe:
        raise AssertionError(f"Missing cuda_available in probe: {probe}")
    print(json.dumps(probe, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

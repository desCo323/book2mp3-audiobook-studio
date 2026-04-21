from __future__ import annotations

import json
from pathlib import Path

from book2mp3.config import AppPaths
from book2mp3.tts.piper import PiperBackend


ROOT = Path("/home/codex/repo/book2mp3")


def main() -> int:
    paths = AppPaths.from_project_root(ROOT / "src")
    backend = PiperBackend(paths.runtime, paths.voices)
    binary = backend.binary_path()
    summary = {
        "app_root": str(paths.root),
        "runtime_root": str(paths.runtime),
        "resolved_binary": str(binary),
        "binary_exists": binary.exists(),
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("runtime_root", help="Target runtime root, e.g. runtime/xtts/linux")
    parser.add_argument("--python", required=True, help="Python interpreter for XTTS runtime")
    return parser.parse_args()


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def main() -> int:
    args = parse_args()
    runtime_root = Path(args.runtime_root).resolve()
    runtime_root.mkdir(parents=True, exist_ok=True)
    run([args.python, "-m", "venv", str(runtime_root)])
    python_bin = runtime_root / ("Scripts/python.exe" if Path(args.python).suffix.lower() == ".exe" else "bin/python3")
    run([str(python_bin), "-m", "pip", "install", "-U", "pip", "setuptools", "wheel"])
    run([str(python_bin), "-m", "pip", "install", "TTS"])
    manifest = {
        "runtime_root": str(runtime_root),
        "python": str(python_bin),
        "packages": ["TTS"],
    }
    (runtime_root / "xtts-runtime-manifest.json").write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

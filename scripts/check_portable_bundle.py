from __future__ import annotations

import argparse
import json
from pathlib import Path


def app_root(root: Path) -> Path:
    candidate = root / "src"
    return candidate if candidate.exists() else root


def expected_items(root: Path) -> list[Path]:
    program_root = app_root(root)
    return [
        root / "START_HERE.md",
        program_root / "start.sh",
        program_root / "start.bat",
        program_root / "book2mp3" / "main.py",
        program_root / "scripts" / "xtts_worker.py",
        program_root / "scripts" / "setup_xtts_runtime.py",
        program_root / "runtime",
        program_root / "finalbooks",
        program_root / "voices",
        program_root / "python",
    ]


def platform_runtime_summary(root: Path) -> dict[str, bool]:
    program_root = app_root(root)
    return {
        "linux": (program_root / "python" / "linux" / "bin" / "python3").exists(),
        "windows": (program_root / "python" / "windows" / "python.exe").exists(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle_root", nargs="?", default=".")
    args = parser.parse_args()

    root = Path(args.bundle_root).resolve()
    missing = [str(path.relative_to(root)) for path in expected_items(root) if not path.exists()]
    runtimes = platform_runtime_summary(root)
    program_root = app_root(root)

    summary = {
        "bundle_root": str(root),
        "program_root": str(program_root),
        "ok": not missing,
        "missing": missing,
        "python_runtimes": runtimes,
        "note": (
            "A production bundle must ship with app-local Python under python/<platform>/ "
            "so users do not need system Python."
        ),
    }
    print(json.dumps(summary, indent=2))
    return 0 if not missing else 1


if __name__ == "__main__":
    raise SystemExit(main())

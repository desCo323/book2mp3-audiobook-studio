from __future__ import annotations

import argparse
import json
from pathlib import Path


def expected_items(root: Path) -> list[Path]:
    return [
        root / "start.sh",
        root / "start.bat",
        root / "src" / "book2mp3" / "main.py",
        root / "runtime",
        root / "voices",
        root / "python",
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle_root", nargs="?", default=".")
    args = parser.parse_args()

    root = Path(args.bundle_root).resolve()
    missing = [str(path.relative_to(root)) for path in expected_items(root) if not path.exists()]

    summary = {
        "bundle_root": str(root),
        "ok": not missing,
        "missing": missing,
        "note": (
            "A production bundle must ship with app-local Python under python/<platform>/ "
            "so users do not need system Python."
        ),
    }
    print(json.dumps(summary, indent=2))
    return 0 if not missing else 1


if __name__ == "__main__":
    raise SystemExit(main())

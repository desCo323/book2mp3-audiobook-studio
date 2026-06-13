from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from book2mp3.config import AppPaths
from book2mp3.xtts_speakers import install_starter_xtts_profiles


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "program_root",
        nargs="?",
        default=".",
        help="book2mp3 program root containing runtime/, voices/ and workspace/",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    program_root = Path(args.program_root).resolve()
    paths = AppPaths.from_project_root(program_root)
    paths.ensure()
    manifests = install_starter_xtts_profiles(paths)
    print(
        json.dumps(
            {
                "program_root": str(program_root),
                "installed_profiles": [str(path) for path in manifests],
                "count": len(manifests),
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

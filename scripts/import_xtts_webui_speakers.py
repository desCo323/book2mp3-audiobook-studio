from __future__ import annotations

import argparse
import json
from pathlib import Path

from book2mp3.config import AppPaths
from book2mp3.xtts_speakers import import_xtts_webui_speakers


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_root", help="XTTS-WebUI speakers folder")
    parser.add_argument("--app-root", default="/home/codex/repo/book2mp3/src")
    parser.add_argument("--language", default="en", help="Fallback language code")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    paths = AppPaths.from_project_root(Path(args.app_root).resolve())
    paths.ensure()
    manifests = import_xtts_webui_speakers(paths, Path(args.source_root).resolve(), args.language)
    print(
        json.dumps(
            {
                "source_root": str(Path(args.source_root).resolve()),
                "imported_profiles": [manifest.parent.name for manifest in manifests],
                "count": len(manifests),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

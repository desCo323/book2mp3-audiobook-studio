from __future__ import annotations

import json
import tempfile
from pathlib import Path

from book2mp3.config import AppPaths
from book2mp3.xtts_speakers import install_starter_xtts_profiles


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="book2mp3-xtts-starters-") as tmp_dir:
        root = Path(tmp_dir)
        paths = AppPaths.from_project_root(root)
        paths.ensure()
        manifests = install_starter_xtts_profiles(paths)
        if len(manifests) < 5:
            raise AssertionError(f"Expected at least 5 starter manifests, got {len(manifests)}")
        print(
            json.dumps(
                {
                    "installed_profiles": [manifest.parent.name for manifest in manifests],
                    "voice_profiles_root": str(paths.voice_profiles),
                },
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

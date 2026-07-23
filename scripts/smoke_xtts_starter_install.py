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
        installed_profile_ids = {manifest.parent.name for manifest in manifests}
        expected_profile_ids = {
            "xtts_kerstin_hq_female",
            "xtts_ljspeech_hq_female",
            "xtts_vctk_hq_female_clear",
            "xtts_vctk_hq_female_north",
            "xtts_vctk_hq_female_oxford",
            "xtts_vctk_hq_female_southern",
        }
        missing_profile_ids = expected_profile_ids - installed_profile_ids
        if missing_profile_ids:
            raise AssertionError(f"Missing high-quality XTTS starter profiles: {sorted(missing_profile_ids)}")
        if len(manifests) < 13:
            raise AssertionError(f"Expected at least 13 starter manifests, got {len(manifests)}")
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

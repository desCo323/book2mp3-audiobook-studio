from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from book2mp3.config import AppPaths
from book2mp3.tts.xtts import XttsBackend


ROOT = Path("/home/codex/repo/book2mp3")


def main() -> int:
    paths = AppPaths.from_project_root(ROOT / "src")
    backend = XttsBackend(paths.runtime)

    # Reproduce the exact contamination that previously broke the XTTS subprocess.
    os.environ["PYTHONHOME"] = str(ROOT / "src" / "python" / "linux")
    os.environ["PYTHONPATH"] = (
        f"{ROOT / 'src'}:"
        f"{ROOT / 'src' / 'python' / 'linux' / 'lib' / 'python3.13' / 'dist-packages'}:"
        f"{ROOT / 'src' / 'python' / 'linux' / 'lib' / 'python3.13' / 'site-packages'}"
    )
    python_path = backend.python_path()
    env = backend.subprocess_env()

    result = subprocess.run(
        [str(python_path), "-c", "import encodings, json; print(json.dumps({'ok': True}))"],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    print(
        json.dumps(
            {
                "python": str(python_path),
                "stdout": result.stdout.strip(),
                "env_pythonhome": env.get("PYTHONHOME", ""),
                "env_pythonpath": env.get("PYTHONPATH", ""),
                "env_pythonnousersite": env.get("PYTHONNOUSERSITE", ""),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

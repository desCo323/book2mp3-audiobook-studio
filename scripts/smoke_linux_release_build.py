from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path


ROOT = Path("/home/codex/repo/book2mp3")


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        output_dir = Path(tmp) / "release"
        subprocess.run(
            [
                "python3",
                str(ROOT / "scripts" / "build_linux_portable_release.py"),
                str(output_dir),
                "--archive",
            ],
            check=True,
        )
        archive = output_dir.with_suffix(".tar.gz")
        assert output_dir.exists()
        assert archive.exists()
        assert (output_dir / "python" / "linux" / "bin" / "python3").exists()
        print(
            json.dumps(
                {
                    "output_dir": str(output_dir),
                    "archive": str(archive),
                },
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

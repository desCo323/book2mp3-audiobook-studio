from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path


ROOT = Path("/home/codex/repo/book2mp3")


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        bundle = Path(tmp) / "bundle"
        subprocess.run(
            [
                "python3",
                str(ROOT / "scripts" / "build_portable_bundle.py"),
                str(bundle),
                "--clean",
                "--without-voices",
            ],
            check=True,
        )
        subprocess.run(
            [
                "python3",
                str(ROOT / "scripts" / "populate_bundle_python_linux.py"),
                str(bundle / "src"),
            ],
            check=True,
        )
        code = (
            "import json,book2mp3.main,PySide6,requests,pypdf,ebooklib,bs4,imageio_ffmpeg;"
            "print(json.dumps({'ok': True, 'main': str(book2mp3.main.project_root())}))"
        )
        result = subprocess.run(
            [str(bundle / "src" / "python" / "linux" / "bin" / "python3"), "-c", code],
            check=True,
            capture_output=True,
            text=True,
            env={
                "PYTHONHOME": str(bundle / "src" / "python" / "linux"),
                "PYTHONNOUSERSITE": "1",
                "PYTHONPATH": f"{bundle / 'src'}:{bundle / 'src' / 'python' / 'linux' / 'lib' / 'python3.13' / 'site-packages'}",
            },
        )
        print(
            json.dumps(
                {
                    "bundle_root": str(bundle),
                    "program_root": str(bundle / "src"),
                    "python_manifest": str(bundle / "src" / "python" / "linux" / "linux-python-manifest.json"),
                    "import_check": result.stdout.strip(),
                },
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

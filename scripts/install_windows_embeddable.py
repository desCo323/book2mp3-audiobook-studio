from __future__ import annotations

import argparse
import io
import json
import zipfile
from pathlib import Path

import requests


def app_root(root: Path) -> Path:
    candidate = root / "src"
    return candidate if candidate.exists() else root


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle_root", help="Portable bundle root created by build_portable_bundle.py")
    parser.add_argument(
        "--url",
        required=True,
        help="Direct URL to a Python.org Windows embeddable package zip",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    bundle_root = Path(args.bundle_root).resolve()
    program_root = app_root(bundle_root)
    target = program_root / "python" / "windows"
    target.mkdir(parents=True, exist_ok=True)

    response = requests.get(args.url, timeout=300)
    response.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        archive.extractall(target)

    (target / "Lib" / "site-packages").mkdir(parents=True, exist_ok=True)
    pth_files = sorted(target.glob("python*._pth"))
    patched_files: list[str] = []
    for pth_file in pth_files:
        pth_file.write_text(
            "\n".join(
                [
                    "python313.zip",
                    ".",
                    "Lib",
                    "Lib/site-packages",
                    "../..",
                    "import site",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        patched_files.append(str(pth_file))

    manifest = {
        "bundle_root": str(bundle_root),
        "program_root": str(program_root),
        "windows_python": str(target),
        "source_url": args.url,
        "patched_pth_files": patched_files,
    }
    manifest_path = target / "windows-python-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

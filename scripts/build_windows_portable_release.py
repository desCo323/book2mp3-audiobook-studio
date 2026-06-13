from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "output_dir",
        nargs="?",
        default="dist/book2mp3-windows-portable",
        help="Target directory for the portable Windows release",
    )
    parser.add_argument("--without-voices", action="store_true", help="Do not copy voices/")
    parser.add_argument("--archive", action="store_true", help="Create a .zip archive")
    return parser.parse_args()


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, cwd=ROOT)


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir).resolve()
    run(
        [
            sys.executable,
            str(ROOT / "scripts" / "build_portable_bundle.py"),
            str(output_dir),
            "--clean",
            *(["--without-voices"] if args.without_voices else []),
        ]
    )
    run([sys.executable, str(ROOT / "scripts" / "populate_bundle_python_windows.py"), str(output_dir), "--clean"])
    run([sys.executable, str(ROOT / "scripts" / "check_portable_bundle.py"), str(output_dir)])

    if args.archive:
        archive_base = output_dir.parent / output_dir.name
        shutil.make_archive(str(archive_base), "zip", root_dir=output_dir.parent, base_dir=output_dir.name)
        print(archive_base.with_suffix(".zip"))
    else:
        print(output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def program_root(output_dir: Path) -> Path:
    return output_dir / "src"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "output_dir",
        nargs="?",
        default="dist/book2mp3-linux-portable",
        help="Target directory for the portable Linux release",
    )
    parser.add_argument("--without-voices", action="store_true", help="Do not copy voices/")
    parser.add_argument("--archive", action="store_true", help="Create a .tar.gz archive")
    parser.add_argument(
        "--include-xtts-runtime",
        action="store_true",
        help="Bootstrap an optional dedicated XTTS runtime under runtime/xtts/linux",
    )
    parser.add_argument(
        "--skip-xtts-packages",
        action="store_true",
        help="When bootstrapping XTTS runtime, skip TTS pip installation",
    )
    parser.add_argument(
        "--xtts-torch-variant",
        choices=["cpu", "default"],
        default="cpu",
        help="Torch package preference for XTTS runtime bootstrapping",
    )
    return parser.parse_args()


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, cwd=ROOT)


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir).resolve()
    run(
        [
            "python3",
            str(ROOT / "scripts" / "build_portable_bundle.py"),
            str(output_dir),
            "--clean",
            *(["--without-voices"] if args.without_voices else []),
        ]
    )
    run(["python3", str(ROOT / "scripts" / "populate_bundle_python_linux.py"), str(program_root(output_dir))])
    if args.include_xtts_runtime:
        run(
            [
                "python3",
                str(ROOT / "scripts" / "setup_xtts_runtime.py"),
                str(program_root(output_dir) / "runtime" / "xtts" / "linux"),
                "--bootstrap-linux-standalone",
                "--torch-variant",
                args.xtts_torch_variant,
                *(["--skip-package-install"] if args.skip_xtts_packages else []),
            ]
        )
    run(["python3", str(ROOT / "scripts" / "check_portable_bundle.py"), str(output_dir)])

    if args.archive:
        archive_base = output_dir.parent / output_dir.name
        shutil.make_archive(str(archive_base), "gztar", root_dir=output_dir.parent, base_dir=output_dir.name)
        print(archive_base.with_suffix(".tar.gz"))
    else:
        print(output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

XTTS_COMPAT_PACKAGES = [
    "transformers<5",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle_program_root", help="Portable program root, usually dist/.../src")
    parser.add_argument(
        "--torch-variant",
        choices=["cpu", "default"],
        default="cpu",
        help="Install CPU-first torch packages by default to avoid pulling CUDA runtimes",
    )
    return parser.parse_args()


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def main() -> int:
    args = parse_args()
    program_root = Path(args.bundle_program_root).resolve()
    python_bin = program_root / "python" / "linux" / "bin" / "python3"
    if not python_bin.exists():
        raise FileNotFoundError(f"Portable bundle python not found: {python_bin}")
    if sys.version_info >= (3, 12):
        raise SystemExit(
            "XTTS cannot currently be installed into the portable app Python on this base version. "
            "Upstream `TTS` does not publish compatible wheels for Python 3.12+ here. "
            "Use the bundled dedicated XTTS runtime instead: "
            "`python scripts/build_linux_portable_release.py <out> --include-xtts-runtime`"
        )

    installed_packages: list[str] = []
    pip_prefix = [str(python_bin), "-m", "pip", "install", "--break-system-packages"]
    run([*pip_prefix, "-U", "pip", "setuptools", "wheel"])
    if args.torch_variant == "cpu":
        run(
            [
                *pip_prefix,
                "--index-url",
                "https://download.pytorch.org/whl/cpu",
                "torch",
                "torchaudio",
            ]
        )
        installed_packages.extend(["torch[cpu]", "torchaudio[cpu]"])
    run([*pip_prefix, "TTS"])
    run([*pip_prefix, *XTTS_COMPAT_PACKAGES])
    installed_packages.extend(["TTS", *XTTS_COMPAT_PACKAGES])

    manifest = {
        "bundle_program_root": str(program_root),
        "python": str(python_bin),
        "packages": installed_packages,
        "torch_variant": args.torch_variant,
    }
    manifest_path = program_root / "python" / "linux" / "xtts-app-python-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

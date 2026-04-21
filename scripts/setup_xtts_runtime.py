from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
XTTS_COMPAT_PACKAGES = [
    "torch<2.6",
    "torchaudio<2.6",
    "transformers<4.50",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("runtime_root", help="Target runtime root, e.g. runtime/xtts/linux")
    parser.add_argument("--python", help="Python interpreter for XTTS runtime")
    parser.add_argument(
        "--bootstrap-linux-standalone",
        action="store_true",
        help="Download and install a portable Python 3.11 runtime into runtime_root first",
    )
    parser.add_argument(
        "--standalone-tag",
        default="latest",
        help="python-build-standalone release tag or 'latest'",
    )
    parser.add_argument(
        "--skip-package-install",
        action="store_true",
        help="Only prepare the runtime and manifest, skip pip package installation",
    )
    parser.add_argument(
        "--torch-variant",
        choices=["cpu", "default"],
        default="cpu",
        help="Install CPU-first torch packages by default to avoid pulling large CUDA runtimes",
    )
    return parser.parse_args()


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def bootstrap_linux_standalone(runtime_root: Path, tag: str) -> Path:
    installer = ROOT / "scripts" / "install_xtts_linux_standalone_python.py"
    run([sys.executable, str(installer), str(runtime_root), "--tag", tag, "--clean"])
    python_bin = runtime_root / "bin" / "python3"
    if not python_bin.exists():
        raise FileNotFoundError(f"Standalone XTTS Python was not installed correctly: {python_bin}")
    return python_bin


def main() -> int:
    args = parse_args()
    runtime_root = Path(args.runtime_root).resolve()
    runtime_root.mkdir(parents=True, exist_ok=True)

    portable_manifest_path: Path | None = None
    if args.bootstrap_linux_standalone:
        if args.python:
            raise SystemExit("--python and --bootstrap-linux-standalone are mutually exclusive")
        python_bin = bootstrap_linux_standalone(runtime_root, args.standalone_tag)
        portable_manifest_path = runtime_root / "linux-standalone-python-manifest.json"
    elif args.python:
        run([args.python, "-m", "venv", str(runtime_root)])
        python_bin = runtime_root / (
            "Scripts/python.exe" if Path(args.python).suffix.lower() == ".exe" else "bin/python3"
        )
    else:
        raise SystemExit("Provide either --python or --bootstrap-linux-standalone")

    installed_packages: list[str] = []
    if not args.skip_package_install:
        run([str(python_bin), "-m", "pip", "install", "-U", "pip", "setuptools", "wheel"])
        if args.torch_variant == "cpu":
            run(
                [
                    str(python_bin),
                    "-m",
                    "pip",
                    "install",
                    "--index-url",
                    "https://download.pytorch.org/whl/cpu",
                    "torch<2.6",
                    "torchaudio<2.6",
                ]
            )
            installed_packages.extend(["torch[cpu]<2.6", "torchaudio[cpu]<2.6"])
        run([str(python_bin), "-m", "pip", "install", "TTS"])
        run([str(python_bin), "-m", "pip", "install", *XTTS_COMPAT_PACKAGES])
        installed_packages.extend(["TTS", *XTTS_COMPAT_PACKAGES])

    manifest = {
        "runtime_root": str(runtime_root),
        "python": str(python_bin),
        "packages": installed_packages,
        "portable_python_manifest": str(portable_manifest_path) if portable_manifest_path else "",
        "torch_variant": args.torch_variant,
    }
    (runtime_root / "xtts-runtime-manifest.json").write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

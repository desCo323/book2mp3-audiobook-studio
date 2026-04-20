from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle_root")
    parser.add_argument("--python-exe", help="Path to Windows embedded python.exe inside the bundle")
    parser.add_argument("--include-xtts", action="store_true")
    return parser.parse_args()


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def main() -> int:
    args = parse_args()
    bundle_root = Path(args.bundle_root).resolve()
    python_exe = (
        Path(args.python_exe)
        if args.python_exe
        else bundle_root / "python" / "windows" / "python.exe"
    )
    if not python_exe.exists():
        raise FileNotFoundError(f"Windows bundle python not found: {python_exe}")

    get_pip = ROOT / "scripts" / "_tmp_get_pip.py"
    response = requests.get("https://bootstrap.pypa.io/get-pip.py", timeout=300)
    response.raise_for_status()
    get_pip.write_bytes(response.content)
    try:
        run([str(python_exe), str(get_pip)])
        run([str(python_exe), "-m", "pip", "install", "-U", "pip", "setuptools", "wheel"])
        run([str(python_exe), "-m", "pip", "install", "-e", str(ROOT)])
        if args.include_xtts:
            run([str(python_exe), "-m", "pip", "install", "TTS"])
    finally:
        if get_pip.exists():
            get_pip.unlink()
    print(python_exe)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

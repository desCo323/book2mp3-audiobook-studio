from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

COPY_ITEMS = [
    "README.md",
    "THIRD_PARTY_NOTICES.md",
    "start.sh",
    "start.bat",
    "pyproject.toml",
    "src",
    "docs",
    "runtime",
    "voices",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir", help="Target directory for the portable bundle")
    parser.add_argument("--python-linux", help="Path to a relocatable Linux Python runtime")
    parser.add_argument("--python-windows", help="Path to a Windows embeddable Python runtime")
    parser.add_argument("--without-voices", action="store_true", help="Do not copy voices/")
    parser.add_argument("--without-runtime", action="store_true", help="Do not copy runtime/")
    parser.add_argument("--clean", action="store_true", help="Delete output directory before build")
    return parser.parse_args()


def reset_output(output_dir: Path, clean: bool) -> None:
    if output_dir.exists() and clean:
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)


def copy_path(source: Path, target: Path) -> None:
    if source.is_dir():
        shutil.copytree(source, target, dirs_exist_ok=True)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def copy_project_files(output_dir: Path, without_voices: bool, without_runtime: bool) -> list[str]:
    copied: list[str] = []
    for item in COPY_ITEMS:
        if item == "voices" and without_voices:
            continue
        if item == "runtime" and without_runtime:
            continue
        source = PROJECT_ROOT / item
        target = output_dir / item
        if source.exists():
            copy_path(source, target)
            copied.append(item)
    for rel in [
        "workspace/jobs",
        "workspace/logs",
        "workspace/voice_profiles",
        "workspace/preview_sessions",
    ]:
        (output_dir / rel).mkdir(parents=True, exist_ok=True)
    return copied


def copy_python_runtime(source_dir: str | None, target_dir: Path) -> bool:
    if not source_dir:
        return False
    source = Path(source_dir).resolve()
    if not source.exists():
        raise FileNotFoundError(f"Python runtime not found: {source}")
    copy_path(source, target_dir)
    return True


def write_manifest(
    output_dir: Path,
    copied: list[str],
    linux_python: bool,
    windows_python: bool,
) -> Path:
    manifest = {
        "bundle_root": str(output_dir.resolve()),
        "copied_items": copied,
        "python": {
            "linux": linux_python,
            "windows": windows_python,
        },
        "note": (
            "Portable users should start with start.sh or start.bat. "
            "A finished release should include at least one app-local Python runtime."
        ),
    }
    manifest_path = output_dir / "bundle-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest_path


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir).resolve()
    reset_output(output_dir, clean=args.clean)
    copied = copy_project_files(
        output_dir,
        without_voices=args.without_voices,
        without_runtime=args.without_runtime,
    )

    python_root = output_dir / "python"
    linux_python = copy_python_runtime(args.python_linux, python_root / "linux")
    windows_python = copy_python_runtime(args.python_windows, python_root / "windows")
    manifest_path = write_manifest(output_dir, copied, linux_python, windows_python)

    print(
        json.dumps(
            {
                "bundle_root": str(output_dir),
                "manifest": str(manifest_path),
                "linux_python": linux_python,
                "windows_python": windows_python,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

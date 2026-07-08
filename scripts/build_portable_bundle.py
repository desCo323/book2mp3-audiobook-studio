from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


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


def program_root(output_dir: Path) -> Path:
    return output_dir / "src"


def copy_project_files(output_dir: Path, without_voices: bool, without_runtime: bool) -> list[str]:
    app_dir = program_root(output_dir)
    app_dir.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    items: list[tuple[Path, Path, str]] = [
        (PROJECT_ROOT / "README.md", app_dir / "README.md", "src/README.md"),
        (
            PROJECT_ROOT / "THIRD_PARTY_NOTICES.md",
            app_dir / "THIRD_PARTY_NOTICES.md",
            "src/THIRD_PARTY_NOTICES.md",
        ),
        (PROJECT_ROOT / "src" / "start.sh", app_dir / "start.sh", "src/start.sh"),
        (PROJECT_ROOT / "src" / "start.bat", app_dir / "start.bat", "src/start.bat"),
        (PROJECT_ROOT / "src" / "book2mp3", app_dir / "book2mp3", "src/book2mp3"),
        (PROJECT_ROOT / "scripts", app_dir / "scripts", "src/scripts"),
        (PROJECT_ROOT / "docs", app_dir / "docs", "src/docs"),
        (PROJECT_ROOT / "runtime", app_dir / "runtime", "src/runtime"),
        (PROJECT_ROOT / "voices", app_dir / "voices", "src/voices"),
    ]
    for source, target, label in items:
        if label == "src/voices" and without_voices:
            continue
        if label == "src/runtime" and without_runtime:
            continue
        if source.exists():
            copy_path(source, target)
            copied.append(label)
    for rel in [
        "finalbooks",
        "runtime",
        "voices",
    ]:
        (app_dir / rel).mkdir(parents=True, exist_ok=True)
    for rel in [
        "workspace/jobs",
        "workspace/logs",
        "workspace/voice_profiles",
        "workspace/preview_sessions",
    ]:
        (app_dir / rel).mkdir(parents=True, exist_ok=True)
    return copied


def copy_python_runtime(source_dir: str | None, target_dir: Path) -> bool:
    if not source_dir:
        return False
    source = Path(source_dir).resolve()
    if not source.exists():
        raise FileNotFoundError(f"Python runtime not found: {source}")
    copy_path(source, target_dir)
    return True


def installed_voice_counts_by_core_language(voices_root: Path) -> dict[str, int]:
    counts = {"de": 0, "en": 0, "es": 0, "pt": 0}
    for model in voices_root.rglob("*.onnx"):
        voice_id = model.stem
        prefix = voice_id.split("_", 1)[0]
        if prefix in counts:
            counts[prefix] += 1
    return counts


def write_start_here(output_dir: Path) -> Path:
    app_dir = program_root(output_dir)
    voices_root = app_dir / "voices"
    counts = installed_voice_counts_by_core_language(voices_root) if voices_root.exists() else {"de": 0, "en": 0, "es": 0, "pt": 0}
    lines = [
        "# START HERE",
        "",
        "## What this bundle is",
        "",
        "This portable build is meant for end users.",
        "You do not need to install Python separately.",
        "",
        "## Start the app",
        "",
        "- Linux: `./start.sh`",
        "- Windows: `start.bat`",
        "",
        "## What works immediately",
        "",
        "- Piper is bundled and ready to use.",
        "- Local GUI, CLI and local API are included.",
        "- Finished MP3 exports are automatically mirrored to `finalbooks/<book-title>/`.",
        "- Saved jobs, queue resume and final MP3 export work without extra Python setup.",
        "",
        "## Included Piper language coverage",
        "",
        f"- German voices: {counts['de']}",
        f"- English voices: {counts['en']}",
        f"- Spanish voices: {counts['es']}",
        f"- Portuguese voices: {counts['pt']}",
        "",
        "## Optional XTTS setup",
        "",
        "XTTS is optional and not required for normal Piper-based use.",
        "",
        "- Linux: `./start.sh --install-xtts`",
        "- Windows: `start.bat --install-xtts`",
        "",
        "After XTTS setup, open `XTTS-Profile` or `Diagnostics` in the app to verify the runtime.",
        "",
        "Important: the optional XTTS download path improves setup convenience,",
        "but it does not automatically resolve XTTS model licensing constraints for public or commercial distribution.",
        "",
        "## Main areas in the app",
        "",
        "- `Neuer Auftrag` / `New job`: import books and create production jobs",
        "- `Aufträge` / `Jobs`: active queue, ETA, stages, chapters, chunks, logs",
        "- `Produktionsprofile` / `Production profiles`: approved job presets",
        "- `Benchmark-Studio` / `Benchmark Studio`: compare voices and tune settings",
        "- `Fertige Hörbücher` / `Finished audiobooks`: open final books and edit metadata/tags",
        "",
        "## More documentation",
        "",
        "- `src/README.md`",
        "- `src/docs/quickstart-portable.md`",
        "- `src/docs/open-source-compliance.md`",
        "- `src/THIRD_PARTY_NOTICES.md`",
        "",
    ]
    target = output_dir / "START_HERE.md"
    target.write_text("\n".join(lines), encoding="utf-8")
    return target


def write_manifest(
    output_dir: Path,
    copied: list[str],
    linux_python: bool,
    windows_python: bool,
    start_here_path: Path,
) -> Path:
    manifest = {
        "bundle_root": str(output_dir.resolve()),
        "program_root": str(program_root(output_dir).resolve()),
        "copied_items": copied,
        "start_here": str(start_here_path.resolve()),
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
    start_here_path = write_start_here(output_dir)

    python_root = program_root(output_dir) / "python"
    linux_python = copy_python_runtime(args.python_linux, python_root / "linux")
    windows_python = copy_python_runtime(args.python_windows, python_root / "windows")
    manifest_path = write_manifest(output_dir, copied, linux_python, windows_python, start_here_path)

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

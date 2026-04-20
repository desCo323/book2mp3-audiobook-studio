from __future__ import annotations

import argparse
import io
import platform
import zipfile
from pathlib import Path

import requests


PIPER_RELEASES = {
    "linux": "https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_linux_x86_64.tar.gz",
    "windows": "https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_windows_amd64.zip",
}

VOICE_BASE_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main"


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def download(url: str) -> bytes:
    response = requests.get(url, timeout=120)
    response.raise_for_status()
    return response.content


def ensure_dirs() -> tuple[Path, Path]:
    root = project_root()
    runtime = root / "runtime"
    voices = root / "voices"
    runtime.mkdir(parents=True, exist_ok=True)
    voices.mkdir(parents=True, exist_ok=True)
    return runtime, voices


def install_piper(runtime_root: Path) -> None:
    system = platform.system().lower()
    if system not in PIPER_RELEASES:
        raise RuntimeError(f"Unsupported platform: {platform.system()}")
    url = PIPER_RELEASES[system]
    target_dir = runtime_root / "piper" / system
    if target_dir.exists() and any(target_dir.iterdir()):
        print(f"Piper runtime already present in {target_dir}")
        return
    target_dir.mkdir(parents=True, exist_ok=True)
    payload = download(url)
    if url.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            archive.extractall(target_dir)
    else:
        raise RuntimeError(
            "Linux tar.gz extraction is not implemented yet. Use the Windows package or add tar support."
        )
    print(f"Installed Piper runtime into {target_dir}")


def install_voice(voices_root: Path, voice_id: str) -> None:
    language, name, quality = voice_id.split("-", 2)
    language_group, region = language.split("_", 1)
    voice_dir = voices_root / language_group / f"{language}_{region}" / name / quality
    voice_dir.mkdir(parents=True, exist_ok=True)
    base_name = f"{voice_id}.onnx"
    for suffix in ("", ".json"):
        filename = base_name + suffix
        url = f"{VOICE_BASE_URL}/v1.0.0/{language_group}/{language}/{name}/{quality}/{filename}"
        content = download(url)
        (voice_dir / filename).write_bytes(content)
        print(f"Downloaded {filename}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--voice", help="Voice id like de_DE-thorsten-high")
    parser.add_argument("--skip-runtime", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    runtime_root, voices_root = ensure_dirs()
    if not args.skip_runtime:
        install_piper(runtime_root)
    if args.voice:
        install_voice(voices_root, args.voice)
    print("Bootstrap finished")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

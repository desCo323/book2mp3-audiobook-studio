from __future__ import annotations

import argparse
import io
import json
import shutil
import tarfile
import tempfile
from pathlib import Path

import requests


LATEST_RELEASE_URL = (
    "https://raw.githubusercontent.com/astral-sh/python-build-standalone/latest-release/latest-release.json"
)
RELEASE_API_URL = "https://api.github.com/repos/astral-sh/python-build-standalone/releases/tags/{tag}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("runtime_root", help="Target XTTS runtime root, e.g. runtime/xtts/linux")
    parser.add_argument("--tag", default="latest", help="Release tag to use or 'latest'")
    parser.add_argument("--python-version", default="3.11", help="CPython major.minor version")
    parser.add_argument(
        "--target",
        default="x86_64-unknown-linux-gnu",
        help="python-build-standalone target triple",
    )
    parser.add_argument(
        "--asset-suffix",
        default="install_only.tar.gz",
        help="Preferred asset suffix",
    )
    parser.add_argument("--clean", action="store_true", help="Delete existing runtime_root before install")
    return parser.parse_args()


def resolve_tag(tag: str) -> str:
    if tag != "latest":
        return tag
    response = requests.get(LATEST_RELEASE_URL, timeout=60)
    response.raise_for_status()
    payload = response.json()
    return payload["tag"]


def select_asset(tag: str, python_version: str, target: str, asset_suffix: str) -> tuple[str, str]:
    response = requests.get(
        RELEASE_API_URL.format(tag=tag),
        timeout=60,
        headers={"Accept": "application/vnd.github+json"},
    )
    response.raise_for_status()
    assets = response.json().get("assets", [])
    prefix = f"cpython-{python_version}."
    matches = [
        asset
        for asset in assets
        if asset["name"].startswith(prefix)
        and target in asset["name"]
        and asset["name"].endswith(asset_suffix)
    ]
    if not matches:
        raise FileNotFoundError(
            f"No python-build-standalone asset found for Python {python_version}, target {target}, suffix {asset_suffix}"
        )
    asset = sorted(matches, key=lambda item: item["name"], reverse=True)[0]
    return asset["name"], asset["browser_download_url"]


def install_archive(url: str, runtime_root: Path) -> None:
    response = requests.get(url, timeout=300)
    response.raise_for_status()
    with tempfile.TemporaryDirectory(prefix="book2mp3-xtts-python-") as temp_dir:
        temp_path = Path(temp_dir)
        with tarfile.open(fileobj=io.BytesIO(response.content), mode="r:gz") as archive:
            archive.extractall(temp_path)
        extracted_python_root = temp_path / "python"
        if not extracted_python_root.exists():
            raise FileNotFoundError("Standalone Python archive does not contain a top-level 'python/' directory")
        if runtime_root.exists():
            shutil.rmtree(runtime_root)
        shutil.copytree(extracted_python_root, runtime_root)


def main() -> int:
    args = parse_args()
    runtime_root = Path(args.runtime_root).resolve()
    if args.clean and runtime_root.exists():
        shutil.rmtree(runtime_root)
    runtime_root.parent.mkdir(parents=True, exist_ok=True)

    resolved_tag = resolve_tag(args.tag)
    asset_name, asset_url = select_asset(
        resolved_tag,
        args.python_version,
        args.target,
        args.asset_suffix,
    )
    install_archive(asset_url, runtime_root)

    python_bin = runtime_root / "bin" / "python3"
    pip_bin = runtime_root / "bin" / "pip3"
    manifest = {
        "runtime_root": str(runtime_root),
        "tag": resolved_tag,
        "asset_name": asset_name,
        "asset_url": asset_url,
        "python": str(python_bin),
        "pip": str(pip_bin),
    }
    (runtime_root / "linux-standalone-python-manifest.json").write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

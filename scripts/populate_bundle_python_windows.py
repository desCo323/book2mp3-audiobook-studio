from __future__ import annotations

import argparse
import io
import json
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

import requests

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EMBED_URL = "https://www.python.org/ftp/python/3.13.13/python-3.13.13-embeddable-amd64.zip"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "bundle_root",
        help="Portable bundle root or src/ program root that should receive python/windows",
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_EMBED_URL,
        help="Official Python.org Windows embeddable ZIP URL",
    )
    parser.add_argument(
        "--platform-tag",
        default="win_amd64",
        help="Target wheel platform for pip download",
    )
    parser.add_argument(
        "--python-version",
        default="3.13",
        help="Target Python version for wheel resolution",
    )
    parser.add_argument(
        "--abi",
        default="cp313",
        help="Target ABI tag for wheel resolution",
    )
    parser.add_argument(
        "--implementation",
        default="cp",
        help="Target Python implementation for wheel resolution",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Delete an existing python/windows tree before repopulating it",
    )
    return parser.parse_args()


def app_root(root: Path) -> Path:
    candidate = root / "src"
    return candidate if candidate.exists() else root


def windows_root(root: Path) -> Path:
    return app_root(root) / "python" / "windows"


def project_dependencies() -> list[str]:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    deps = pyproject.get("project", {}).get("dependencies", [])
    return [str(dep) for dep in deps]


def reset_target(target: Path, clean: bool) -> None:
    if clean and target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)


def download_and_extract_embed(url: str, target: Path) -> list[str]:
    response = requests.get(url, timeout=300)
    response.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        archive.extractall(target)
        names = archive.namelist()
    return names


def patch_embedded_pth(target: Path) -> list[str]:
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
    return patched_files


def unpack_wheels(wheels_dir: Path, site_packages: Path) -> list[str]:
    unpacked: list[str] = []
    for wheel in sorted(wheels_dir.glob("*.whl")):
        with zipfile.ZipFile(wheel) as archive:
            archive.extractall(site_packages)
        unpacked.append(wheel.name)
    return unpacked


def download_windows_wheels(
    wheels_dir: Path,
    requirements: list[str],
    platform_tag: str,
    python_version: str,
    abi: str,
    implementation: str,
) -> list[str]:
    wheels_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        "python3",
        "-m",
        "pip",
        "download",
        "--dest",
        str(wheels_dir),
        "--only-binary=:all:",
        "--platform",
        platform_tag,
        "--python-version",
        python_version,
        "--abi",
        abi,
        "--implementation",
        implementation,
        *requirements,
    ]
    subprocess.run(cmd, check=True, cwd=ROOT)
    return sorted(path.name for path in wheels_dir.glob("*"))


def main() -> int:
    args = parse_args()
    bundle_root = Path(args.bundle_root).resolve()
    program_root = app_root(bundle_root)
    target = windows_root(bundle_root)
    reset_target(target, clean=args.clean)

    embedded_files = download_and_extract_embed(args.url, target)
    patched_pth_files = patch_embedded_pth(target)

    requirements = project_dependencies()
    site_packages = target / "Lib" / "site-packages"
    with tempfile.TemporaryDirectory(prefix="book2mp3-win-wheels-") as tmp_dir:
        wheels_dir = Path(tmp_dir) / "wheels"
        downloaded_wheels = download_windows_wheels(
            wheels_dir,
            requirements,
            args.platform_tag,
            args.python_version,
            args.abi,
            args.implementation,
        )
        unpacked_wheels = unpack_wheels(wheels_dir, site_packages)

    manifest = {
        "bundle_root": str(bundle_root),
        "program_root": str(program_root),
        "windows_python": str(target),
        "embed_url": args.url,
        "patched_pth_files": patched_pth_files,
        "requirements": requirements,
        "downloaded_wheels": downloaded_wheels,
        "unpacked_wheels": unpacked_wheels,
        "embedded_files_sample": embedded_files[:20],
    }
    manifest_path = target / "windows-python-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

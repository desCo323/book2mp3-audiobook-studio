from __future__ import annotations

import argparse
import json
import shutil
import site
import sys
import sysconfig
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle_root", help="Portable bundle root created by build_portable_bundle.py")
    parser.add_argument(
        "--system-dist-packages",
        default="/usr/lib/python3/dist-packages",
        help="System dist-packages path to copy for runtime completeness",
    )
    return parser.parse_args()


def copy_tree(source: Path, target: Path) -> None:
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target, dirs_exist_ok=True)


def main() -> int:
    args = parse_args()
    bundle_root = Path(args.bundle_root).resolve()
    python_root = bundle_root / "python" / "linux"
    bin_dir = python_root / "bin"
    lib_dir = python_root / "lib"
    py_version = f"python{sys.version_info.major}.{sys.version_info.minor}"
    stdlib_target = lib_dir / py_version
    site_target = stdlib_target / "site-packages"

    bin_dir.mkdir(parents=True, exist_ok=True)
    site_target.mkdir(parents=True, exist_ok=True)

    python_exe = Path(sys.executable).resolve()
    shutil.copy2(python_exe, bin_dir / "python3")
    shutil.copy2(python_exe, bin_dir / py_version)

    stdlib_source = Path(sysconfig.get_path("stdlib")).resolve()
    copy_tree(stdlib_source, stdlib_target)

    copied_sources: list[str] = []

    purelib = Path(sysconfig.get_path("purelib")).resolve()
    if purelib.exists():
        copy_tree(purelib, site_target)
        copied_sources.append(str(purelib))

    user_site = Path(site.getusersitepackages()).resolve()
    if user_site.exists():
        for item in user_site.iterdir():
            target = site_target / item.name
            if item.is_dir():
                shutil.copytree(item, target, dirs_exist_ok=True)
            else:
                shutil.copy2(item, target)
        copied_sources.append(str(user_site))

    system_dist = Path(args.system_dist_packages).resolve()
    if system_dist.exists():
        for item in system_dist.iterdir():
            target = site_target / item.name
            if item.is_dir():
                shutil.copytree(item, target, dirs_exist_ok=True)
            else:
                shutil.copy2(item, target)

    manifest = {
        "bundle_root": str(bundle_root),
        "python_executable": str(bin_dir / "python3"),
        "stdlib_source": str(stdlib_source),
        "site_package_sources": copied_sources,
        "system_dist_packages": str(system_dist),
    }
    manifest_path = python_root / "linux-python-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

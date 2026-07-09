from __future__ import annotations

import argparse
import json
import os
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
    parser.add_argument(
        "--skip-system-dist-packages",
        action="store_true",
        help="Do not copy host system dist-packages into the portable runtime",
    )
    return parser.parse_args()


def copy_tree(source: Path, target: Path) -> None:
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target, dirs_exist_ok=True)


def merge_tree(source: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        item_target = target / item.name
        if item.is_dir():
            shutil.copytree(item, item_target, dirs_exist_ok=True)
        else:
            shutil.copy2(item, item_target)


def replace_file(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_target = target.with_name(f".{target.name}.tmp")
    if temp_target.exists():
        temp_target.unlink()
    shutil.copy2(source, temp_target)
    os.replace(temp_target, target)


def main() -> int:
    args = parse_args()
    bundle_root = Path(args.bundle_root).resolve()
    python_root = bundle_root / "python" / "linux"
    bin_dir = python_root / "bin"
    lib_dir = python_root / "lib"
    py_version = f"python{sys.version_info.major}.{sys.version_info.minor}"
    stdlib_target = lib_dir / py_version
    site_target = stdlib_target / "site-packages"
    dist_target = stdlib_target / "dist-packages"

    bin_dir.mkdir(parents=True, exist_ok=True)

    python_exe = Path(sys.executable).resolve()
    replace_file(python_exe, bin_dir / "python3")
    replace_file(python_exe, bin_dir / py_version)

    stdlib_source = Path(sysconfig.get_path("stdlib")).resolve()
    copy_tree(stdlib_source, stdlib_target)
    site_target.mkdir(parents=True, exist_ok=True)
    dist_target.mkdir(parents=True, exist_ok=True)

    copied_sources: list[str] = []

    package_sources = [
        Path(sysconfig.get_path("purelib")).resolve(),
        Path(sysconfig.get_path("platlib")).resolve(),
        Path(sys.prefix).resolve() / "lib" / py_version / "dist-packages",
        Path(sys.prefix).resolve() / "lib" / py_version / "site-packages",
    ]
    seen_package_sources: set[Path] = set()
    for package_source in package_sources:
        if package_source in seen_package_sources or not package_source.exists():
            continue
        seen_package_sources.add(package_source)
        merge_tree(package_source, dist_target)
        copied_sources.append(str(package_source))

    user_site = Path(site.getusersitepackages()).resolve()
    if user_site.exists():
        for item in user_site.iterdir():
            target = dist_target / item.name
            if item.is_dir():
                shutil.copytree(item, target, dirs_exist_ok=True)
            else:
                shutil.copy2(item, target)
        copied_sources.append(str(user_site))

    system_dist = Path(args.system_dist_packages).resolve()
    if not args.skip_system_dist_packages and system_dist.exists():
        for item in system_dist.iterdir():
            target = dist_target / item.name
            if item.is_dir():
                shutil.copytree(item, target, dirs_exist_ok=True, symlinks=True, ignore_dangling_symlinks=True)
            else:
                shutil.copy2(item, target)

    (site_target / "book2mp3-portable-runtime.pth").write_text(
        "../dist-packages\n",
        encoding="utf-8",
    )

    manifest = {
        "bundle_root": str(bundle_root),
        "python_executable": str(bin_dir / "python3"),
        "stdlib_source": str(stdlib_source),
        "site_package_sources": copied_sources,
        "system_dist_packages": "" if args.skip_system_dist_packages else str(system_dist),
    }
    manifest_path = python_root / "linux-python-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

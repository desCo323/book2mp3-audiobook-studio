from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path


ROOT = Path("/home/codex/repo/book2mp3")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="book2mp3-smoke-win-bundle-") as tmp:
        bundle = Path(tmp) / "bundle"
        subprocess.run(
            [
                "python3",
                str(ROOT / "scripts" / "build_portable_bundle.py"),
                str(bundle),
                "--without-voices",
                "--clean",
            ],
            check=True,
        )
        subprocess.run(
            [
                "python3",
                str(ROOT / "scripts" / "populate_bundle_python_windows.py"),
                str(bundle),
                "--clean",
            ],
            check=True,
        )

        program_root = bundle / "src"
        windows_root = program_root / "python" / "windows"
        manifest_path = windows_root / "windows-python-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        pth_files = sorted(windows_root.glob("python*._pth"))
        assert (windows_root / "python.exe").exists()
        assert pth_files
        assert (windows_root / "Lib" / "site-packages" / "PySide6").exists()
        assert (windows_root / "Lib" / "site-packages" / "requests").exists()
        assert (program_root / "start.bat").exists()
        print(
            json.dumps(
                {
                    "program_root": str(program_root),
                    "windows_root": str(windows_root),
                    "patched_pth_files": manifest["patched_pth_files"],
                    "wheel_count": len(manifest["downloaded_wheels"]),
                },
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

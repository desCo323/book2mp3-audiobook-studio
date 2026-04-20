from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd or ROOT, check=True, capture_output=True, text=True)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="book2mp3-smoke-xtts-linux-") as tmp_dir:
        runtime_root = Path(tmp_dir) / "runtime" / "xtts" / "linux"
        run(
            [
                "python3",
                str(ROOT / "scripts" / "setup_xtts_runtime.py"),
                str(runtime_root),
                "--bootstrap-linux-standalone",
                "--skip-package-install",
            ]
        )

        manifest_path = runtime_root / "xtts-runtime-manifest.json"
        runtime_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        python_bin = Path(runtime_manifest["python"])
        if not python_bin.exists():
            raise AssertionError(f"Expected runtime python at {python_bin}")

        version_result = run([str(python_bin), "--version"])
        version = (version_result.stdout or version_result.stderr).strip()
        if "Python 3.11" not in version:
            raise AssertionError(f"Expected Python 3.11 runtime, got: {version}")

        standalone_manifest_path = runtime_root / "linux-standalone-python-manifest.json"
        if not standalone_manifest_path.exists():
            raise AssertionError("Standalone Python manifest missing")

        print(
            json.dumps(
                {
                    "runtime_root": str(runtime_root),
                    "python_version": version,
                    "standalone_manifest": str(standalone_manifest_path),
                },
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

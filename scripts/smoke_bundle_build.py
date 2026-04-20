from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path("/home/codex/repo/book2mp3")
sys.path.insert(0, str(ROOT / "scripts"))

from check_portable_bundle import expected_items


def main() -> int:
    root = ROOT
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "bundle"
        subprocess.run(
            [
                "python3",
                str(root / "scripts" / "build_portable_bundle.py"),
                str(target),
                "--without-voices",
                "--clean",
            ],
            check=True,
        )
        assert (target / "bundle-manifest.json").exists()
        manifest = json.loads((target / "bundle-manifest.json").read_text(encoding="utf-8"))
        assert manifest["python"]["linux"] is False
        assert manifest["python"]["windows"] is False
        missing = [str(path.relative_to(target)) for path in expected_items(target) if not path.exists()]
        assert "python" in missing
        assert (target / "src" / "book2mp3" / "main.py").exists()
        assert (target / "workspace" / "jobs").exists()
        print(json.dumps({"bundle_root": str(target), "missing": missing}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path("/home/codex/repo/book2mp3")


def main() -> int:
    python_bin = ROOT / "src" / "runtime" / "xtts" / "linux" / "bin" / "python3"
    worker = ROOT / "scripts" / "xtts_worker.py"
    result = subprocess.run(
        [
            str(python_bin),
            "-c",
            (
                "import json, pathlib; "
                "ns = {}; "
                "exec(pathlib.Path(r'%s').read_text(encoding='utf-8'), ns); "
                "ns['patch_transformers_exports'](); "
                "from TTS.api import TTS; "
                "import transformers; "
                "print(json.dumps({'ok': True, 'transformers': transformers.__version__, "
                "'beam_search_exported': hasattr(transformers, 'BeamSearchScorer')}))"
            )
            % worker,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    print(result.stdout.strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

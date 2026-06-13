from __future__ import annotations

import json
import os
import stat
import tempfile
from pathlib import Path

from book2mp3.config import AppPaths
from book2mp3.preview_sessions import create_preview_session, refresh_preview_excerpt


ROOT = Path("/home/codex/repo/book2mp3")


def ensure_fixture_link(app_root: Path, name: str) -> None:
    target = ROOT / name
    link = app_root / name
    if link.exists():
        return
    link.symlink_to(target, target_is_directory=True)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="book2mp3-smoke-preview-perm-") as tmp_dir:
        app_root = Path(tmp_dir) / "app"
        app_root.mkdir(parents=True, exist_ok=True)
        ensure_fixture_link(app_root, "runtime")
        ensure_fixture_link(app_root, "voices")
        paths = AppPaths.from_project_root(app_root)
        paths.ensure()

        source = app_root / "preview_source.txt"
        source.write_text(
            (
                "Kapitel 1\nDie Glocke im Hof schlug dreimal zu früh.\n\n"
                "Kapitel 2\nAm Morgen klebte ein Zettel an der Werkstatt.\n\n"
                "Kapitel 3\nAm Abend lief die Uhr wieder richtig."
            ),
            encoding="utf-8",
        )
        session = create_preview_session(paths, source)
        preview_file = Path(session.preview_source_file)
        preview_dir = preview_file.parent

        preview_file.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
        repaired = refresh_preview_excerpt(paths, session.session_id)
        repaired_file = Path(repaired.preview_source_file)
        if not repaired_file.exists():
            raise AssertionError("Expected preview source file after repair")
        if os.access(repaired_file, os.W_OK) is False:
            raise AssertionError("Preview source file stayed read-only after repair")

        preview_dir.chmod(stat.S_IRUSR | stat.S_IXUSR | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)
        repaired_again = refresh_preview_excerpt(paths, session.session_id)
        repaired_dir = Path(repaired_again.preview_source_file).parent
        if not repaired_dir.exists():
            raise AssertionError("Expected preview session directory after directory repair")
        if os.access(repaired_dir, os.W_OK | os.X_OK) is False:
            raise AssertionError("Preview session directory stayed read-only after repair")

        print(
            json.dumps(
                {
                    "session_id": session.session_id,
                    "repaired_file": str(repaired_file),
                    "repaired_dir": str(repaired_dir),
                    "excerpt_chars": len(repaired_again.preview_excerpt),
                },
                indent=2,
                ensure_ascii=False,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

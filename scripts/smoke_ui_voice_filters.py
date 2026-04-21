from __future__ import annotations

import json
import os
from pathlib import Path

from PySide6.QtWidgets import QApplication

from book2mp3.config import AppPaths
from book2mp3.ui.find_best_setting_dialog import FindBestSettingDialog
from book2mp3.ui.main_window import MainWindow


ROOT = Path("/home/codex/repo/book2mp3")


def combo_payload(combo) -> list[dict[str, str]]:
    items = []
    for index in range(combo.count()):
        items.append(
            {
                "label": combo.itemText(index),
                "voice_id": combo.itemData(index) or "",
            }
        )
    return items


def assert_filtered(items: list[dict[str, str]]) -> None:
    real_items = [item for item in items if item["voice_id"]]
    if not real_items:
        raise AssertionError("Expected filtered voices, got none")
    for item in real_items:
        label = item["label"]
        if "| female" not in label:
            raise AssertionError(f"Expected female label, got {label}")
        if "| high" not in label:
            raise AssertionError(f"Expected high label, got {label}")


def main() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication([])
    paths = AppPaths.from_project_root(ROOT / "src")

    window = MainWindow(paths)
    window.voice_female_only_checkbox.setChecked(True)
    window.voice_high_only_checkbox.setChecked(True)
    window.rebuild_voice_combo()
    main_items = combo_payload(window.voice_combo)
    assert_filtered(main_items)

    dialog = FindBestSettingDialog(paths, window.manager, window)
    dialog.voice_language_combo.setCurrentIndex(0)
    dialog.voice_female_only_checkbox.setChecked(True)
    dialog.voice_high_only_checkbox.setChecked(True)
    dialog.rebuild_voice_combo()
    dialog_items = combo_payload(dialog.voice_combo)
    assert_filtered(dialog_items)

    print(
        json.dumps(
            {
                "main_window": main_items[:6],
                "find_best_setting": dialog_items[:6],
            },
            indent=2,
        )
    )
    dialog.close()
    window.close()
    app.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

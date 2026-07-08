from __future__ import annotations

import traceback
from typing import Any, Callable

from PySide6.QtCore import QThread, Signal


TaskFn = Callable[[], Any]


class AsyncTaskRunner(QThread):
    """Small helper to run synchronous callables in a dedicated worker thread."""

    success = Signal(int, object)
    failure = Signal(int, str)

    def __init__(self, request_id: int, task: TaskFn, parent=None) -> None:
        super().__init__(parent)
        self.request_id = request_id
        self._task = task

    def run(self) -> None:  # pragma: no cover - exercised indirectly via UI flows
        try:
            result = self._task()
            self.success.emit(self.request_id, result)
        except Exception:
            self.failure.emit(self.request_id, traceback.format_exc())

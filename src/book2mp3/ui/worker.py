from __future__ import annotations

import traceback

from PySide6.QtCore import QThread, Signal

from book2mp3.models import JobState
from book2mp3.pipeline.jobs import JobManager, StopRequested
from book2mp3.utils.logging_utils import get_logger


class JobWorker(QThread):
    progress_changed = Signal(int, int, str)
    job_finished = Signal(object)
    job_failed = Signal(str)

    def __init__(self, manager: JobManager, state: JobState) -> None:
        super().__init__()
        self.manager = manager
        self.state = state
        self._stop_requested = False
        self.logger = get_logger("worker")

    def request_stop(self) -> None:
        self._stop_requested = True

    def run(self) -> None:
        try:
            self.logger.info("Worker started for job %s", self.state.job_id)
            state = self.manager.run_job(
                self.state,
                should_stop=lambda: self._stop_requested,
                progress=lambda current, total, message: self.progress_changed.emit(
                    current, total, message
                ),
            )
            self.job_finished.emit(state)
        except StopRequested:
            self.logger.warning("Worker stopped for job %s", self.state.job_id)
            state = self.manager.load_state(self.state.job_id)
            self.job_finished.emit(state)
        except Exception:
            self.logger.exception("Worker failed for job %s", self.state.job_id)
            self.job_failed.emit(traceback.format_exc())

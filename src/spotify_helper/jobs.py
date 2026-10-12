"""Tiny in-memory background jobs, so long scans can report progress to a polling page."""

from __future__ import annotations

import logging
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)
_KEEP = 20  # finished jobs to remember


@dataclass
class Job:
    id: str
    label: str
    done: int = 0
    total: int = 0
    finished: bool = False
    error: str | None = None
    result: Any = None


class Jobs:
    def __init__(self):
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def start(self, label: str, fn: Callable[[Callable[[int, int], None]], Any]) -> str:
        job = Job(id=uuid.uuid4().hex, label=label)

        def progress(done: int, total: int) -> None:
            job.done, job.total = done, total

        def run() -> None:
            try:
                job.result = fn(progress)
            except Exception as e:  # shown to the user on the progress page
                log.exception("job %s failed", job.id)
                job.error = str(e) or e.__class__.__name__
            finally:
                job.finished = True

        with self._lock:
            finished = [j for j in self._jobs.values() if j.finished]
            for old in finished[:max(0, len(finished) - _KEEP)]:
                del self._jobs[old.id]
            self._jobs[job.id] = job
        threading.Thread(target=run, daemon=True).start()
        return job.id

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

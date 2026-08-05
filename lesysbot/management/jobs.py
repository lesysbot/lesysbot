"""Background jobs for the control panel.

Installing something can take tens of seconds — a zipball download, then pip.
The panel's request handler cannot simply do that: the browser would hang with
no output, and a slow network would look identical to a crash.

So an install starts a job, the response carries its id, and the page polls
``/api/jobs/<id>`` for progress. Deliberately the smallest thing that works: a
bounded dict and a daemon thread, no queue, no persistence. Jobs are per-process
and die with the service, which is correct — a job whose process is gone did not
finish, and resuming one halfway through an extraction would be worse than
letting the user run it again.
"""

from __future__ import annotations

import itertools
import threading
import time
import uuid
from dataclasses import dataclass, field

#: How many finished jobs to keep before evicting the oldest. Enough to survive
#: a burst of installs and a slow poll; small enough that a long-lived service
#: can't accumulate a leak's worth of output.
MAX_JOBS = 50


@dataclass
class Job:
    id: str
    kind: str
    title: str
    state: str = "running"          # running | done | failed
    lines: list[str] = field(default_factory=list)
    result: dict | None = None
    error: str = ""
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    def as_dict(self) -> dict:
        return {
            "id": self.id, "kind": self.kind, "title": self.title,
            "state": self.state, "lines": self.lines, "result": self.result,
            "error": self.error,
            "elapsed": round((self.finished_at or time.time()) - self.started_at, 1),
        }


class _Writer:
    """A file-like sink so Rich can render an installer's output into a job.

    The installer talks to a ``rich.Console``; giving it one backed by this means
    the panel shows the same progress text the terminal does, rather than a
    second description of it that could drift.
    """

    def __init__(self, job: Job, lock: threading.Lock) -> None:
        self._job = job
        self._lock = lock
        self._buffer = ""

    def write(self, text: str) -> int:
        with self._lock:
            self._buffer += text
            *complete, self._buffer = self._buffer.split("\n")
            self._job.lines.extend(line.rstrip() for line in complete)
        return len(text)

    def flush(self) -> None:
        with self._lock:
            if self._buffer:
                self._job.lines.append(self._buffer.rstrip())
                self._buffer = ""


class JobRegistry:
    """The panel's in-process job table."""

    def __init__(self, max_jobs: int = MAX_JOBS) -> None:
        self._jobs: dict[str, Job] = {}
        self._order: list[str] = []
        self._lock = threading.Lock()
        self._max = max_jobs
        self._counter = itertools.count(1)

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self) -> list[dict]:
        with self._lock:
            return [self._jobs[i].as_dict() for i in self._order]

    def start(self, kind: str, title: str, work) -> Job:
        """Run *work(console)* on a daemon thread; returns the job immediately.

        *work* receives a Console writing into the job's output, and whatever it
        returns becomes ``job.result``.
        """
        from rich.console import Console

        job = Job(id=uuid.uuid4().hex[:12], kind=kind, title=title)
        with self._lock:
            self._jobs[job.id] = job
            self._order.append(job.id)
            self._evict_locked()

        writer = _Writer(job, self._lock)
        console = Console(file=writer, width=100, force_terminal=False,
                          no_color=True, highlight=False)

        def run() -> None:
            try:
                job.result = work(console)
                job.state = "done"
            except Exception as e:
                # The panel must show *why*, and a traceback in a browser is
                # both useless and a disclosure; the message is what helps.
                job.state = "failed"
                job.error = f"{type(e).__name__}: {e}"
            finally:
                writer.flush()
                job.finished_at = time.time()

        threading.Thread(target=run, name=f"lesysbot-job-{job.id}",
                         daemon=True).start()
        return job

    def _evict_locked(self) -> None:
        """Drop the oldest *finished* jobs past the cap, never a running one."""
        while len(self._order) > self._max:
            for index, job_id in enumerate(self._order):
                if self._jobs[job_id].state != "running":
                    del self._jobs[self._order.pop(index)]
                    break
            else:
                return          # everything is still running; let it grow

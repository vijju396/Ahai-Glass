"""A small background job runner.

Ingestion streams 2.6 M rows and takes minutes, so it cannot run inside a
request. Both reference projects background this work in an in-process daemon
thread behind a single global lock; this keeps in-process execution but
replaces the global lock with a bounded pool and per-job cancellation tokens
(docs/DECISIONS.md D-007). Phase 7 reuses this runner for training.
"""

from __future__ import annotations

import threading
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable

from app.core.logging import get_correlation_id, get_logger, set_correlation_id

logger = get_logger(__name__)


class JobCancelled(RuntimeError):
    """Raised inside a job when its cancellation token is set."""


@dataclass
class CancellationToken:
    _event: threading.Event = field(default_factory=threading.Event)

    def cancel(self) -> None:
        self._event.set()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        if self._event.is_set():
            raise JobCancelled("The job was cancelled.")


@dataclass
class JobHandle:
    job_id: str
    kind: str
    future: Future
    token: CancellationToken


class JobRunner:
    """Bounded thread pool with a registry of live jobs.

    Deliberately not a task queue: a monthly-cadence POC does not need Redis,
    and a queue would not make a single 6-minute ingestion faster.
    """

    def __init__(self, max_workers: int = 4) -> None:
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="ais-job"
        )
        self._jobs: dict[str, JobHandle] = {}
        self._lock = threading.Lock()

    def submit(
        self, job_id: str, kind: str, fn: Callable[..., Any], *args: Any, **kwargs: Any
    ) -> JobHandle:
        token = CancellationToken()
        correlation_id = get_correlation_id()

        def _wrapped() -> Any:
            # Carry the submitting request's correlation ID into the worker
            # thread so a job's logs tie back to the request that started it.
            set_correlation_id(correlation_id)
            logger.info("job_started", extra={"job_id": job_id, "kind": kind})
            try:
                result = fn(*args, token=token, **kwargs)
            except JobCancelled:
                logger.info("job_cancelled", extra={"job_id": job_id, "kind": kind})
                raise
            except Exception:
                logger.exception("job_failed", extra={"job_id": job_id, "kind": kind})
                raise
            logger.info("job_completed", extra={"job_id": job_id, "kind": kind})
            return result

        future = self._executor.submit(_wrapped)
        handle = JobHandle(job_id=job_id, kind=kind, future=future, token=token)
        with self._lock:
            self._jobs[job_id] = handle
        return handle

    def get(self, job_id: str) -> JobHandle | None:
        with self._lock:
            return self._jobs.get(job_id)

    def cancel(self, job_id: str) -> bool:
        """Request cancellation. Returns False if the job is unknown or done."""
        handle = self.get(job_id)
        if handle is None or handle.future.done():
            return False
        handle.token.cancel()
        return True

    def is_running(self, job_id: str) -> bool:
        handle = self.get(job_id)
        return handle is not None and not handle.future.done()

    def active_count(self) -> int:
        with self._lock:
            return sum(1 for handle in self._jobs.values() if not handle.future.done())

    def shutdown(self, wait: bool = False) -> None:
        with self._lock:
            for handle in self._jobs.values():
                handle.token.cancel()
        self._executor.shutdown(wait=wait, cancel_futures=True)


_runner: JobRunner | None = None
_runner_lock = threading.Lock()


def get_runner() -> JobRunner:
    global _runner
    with _runner_lock:
        if _runner is None:
            from app.core.config import get_settings

            _runner = JobRunner(max_workers=get_settings().max_training_workers)
        return _runner


def shutdown_runner() -> None:
    global _runner
    with _runner_lock:
        if _runner is not None:
            _runner.shutdown()
            _runner = None

"""MLflow tracking, and what happens when it is not there.

Neither reference project tracks experiments at all - Meriton writes flat JSON
under session UUIDs and Sodexo writes SQLite rows. MLflow is new work here
(`docs/MODEL_INVENTORY.md` §4).

Two properties matter more than the tracking itself:

**Tracking never breaks a run.** If MLflow is missing, misconfigured, or its
backing store is locked, the run continues and the reason is recorded on the
run's warnings. A forecast that did not get logged is a bookkeeping problem; a
run that died because a logger failed is a real one.

**The database is the source of truth, not MLflow.** Every metric written to
MLflow is also written to `model_run`. MLflow is a convenience for comparing
runs interactively, and nothing in the application reads back from it. That
keeps a corrupt or deleted tracking store from being able to change what the
leaderboard says.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator

from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class TrackingSession:
    """A no-op-capable MLflow handle.

    `available` is False when tracking is disabled or unusable; every method
    then does nothing and `warnings` explains why once, rather than per call.
    """

    available: bool = False
    run_id: str | None = None
    warnings: list[str] = field(default_factory=list)
    _mlflow: Any = None

    def log_params(self, params: dict[str, Any]) -> None:
        if not self.available:
            return
        try:
            # MLflow rejects a param value over 500 chars and non-scalars.
            self._mlflow.log_params(
                {key: str(value)[:499] for key, value in params.items()}
            )
        except Exception as exc:  # noqa: BLE001
            self._degrade(f"log_params failed: {type(exc).__name__}: {exc}")

    def log_metrics(self, metrics: dict[str, float | None], *, step: int | None = None) -> None:
        if not self.available:
            return
        # A None metric is not zero. It is dropped rather than coerced, because
        # MLflow has no representation for "undefined" and 0.0 would read as a
        # perfect score on a window where the metric does not exist.
        numeric = {
            key: float(value)
            for key, value in metrics.items()
            if value is not None and isinstance(value, (int, float))
        }
        if not numeric:
            return
        try:
            self._mlflow.log_metrics(numeric, step=step)
        except Exception as exc:  # noqa: BLE001
            self._degrade(f"log_metrics failed: {type(exc).__name__}: {exc}")

    def set_tags(self, tags: dict[str, Any]) -> None:
        if not self.available:
            return
        try:
            self._mlflow.set_tags({key: str(value)[:499] for key, value in tags.items()})
        except Exception as exc:  # noqa: BLE001
            self._degrade(f"set_tags failed: {type(exc).__name__}: {exc}")

    def _degrade(self, message: str) -> None:
        """One warning, then silence. A per-call warning would drown the run."""
        self.available = False
        self.warnings.append(f"MLflow tracking stopped: {message}")
        logger.warning("mlflow_degraded", extra={"detail": message})


@contextmanager
def tracking_run(
    *, run_name: str, tags: dict[str, Any] | None = None
) -> Iterator[TrackingSession]:
    """Open an MLflow run, or hand back a no-op session with the reason.

    The `finally` closes the run even when the job raises, so a cancelled or
    failed run does not leave an MLflow run open forever.
    """
    from app.core.config import get_settings

    settings = get_settings()
    session = TrackingSession()

    if not settings.mlflow_enabled:
        session.warnings.append("MLflow tracking is disabled by configuration")
        yield session
        return

    try:
        import mlflow
    except Exception as exc:  # noqa: BLE001
        session.warnings.append(
            f"MLflow is not importable ({type(exc).__name__}), so the run was not "
            "tracked; every metric is still in the database"
        )
        yield session
        return

    started = False
    try:
        settings.mlflow_artifact_root.mkdir(parents=True, exist_ok=True)
        mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
        mlflow.set_experiment(settings.mlflow_experiment)
        active = mlflow.start_run(run_name=run_name)
        started = True
        session.available = True
        session._mlflow = mlflow
        session.run_id = active.info.run_id
        if tags:
            session.set_tags(tags)
    except Exception as exc:  # noqa: BLE001
        session.available = False
        session.warnings.append(
            f"MLflow could not start a run ({type(exc).__name__}: {exc}); the run "
            "continued untracked"
        )
        logger.warning("mlflow_unavailable", extra={"detail": str(exc)})

    try:
        yield session
    finally:
        if started:
            try:
                session._mlflow.end_run()
            except Exception:  # noqa: BLE001 - nothing useful to do at this point
                logger.warning("mlflow_end_run_failed")

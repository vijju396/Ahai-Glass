"""Training submission, progress and per-model results.

Three properties of this router matter more than its shape:

**No work happens in a request handler.** `POST /api/training` writes the run
row, hands the job to the runner and returns 202 with a run id
(`docs/ARCHITECTURE.md` §8).

**The estimate is returned with the submission**, taken from what was stored on
the run, so the number the caller saw is the number that was recorded and can
be audited against `duration_seconds` afterwards.

**No status filter exists on the model-run listing.** A caller can filter by
tier or scope, but not by status: the ineligible, failed and timed-out rows are
the point of the table. `models_missing` on the detail response makes an
accidental omission visible instead of silent.
"""

from __future__ import annotations

import json
import time
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Iterator

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db, session_scope
from app.models.training import ModelRun, QuantileCalibration, TrainingRun
from app.schemas.common import Page
from app.schemas.training import (
    ModelRunOut,
    ModelStatusCount,
    QuantileCalibrationOut,
    RunEstimateOut,
    TrainingRunDetail,
    TrainingRunRequest,
    TrainingRunSummary,
)
from app.services import panel_service
from app.services.training import monitor as monitor_service
from app.services.training import training_service
from app.services.training.hard_timeout import DEFAULT_HARD_TIMEOUT_MODELS

router = APIRouter(prefix="/training", tags=["training"])

#: Terminal run states. The SSE stream closes when it sees one.
#: A run is over in these states.
#:
#: `completed_with_warnings` was missing, and it is how almost every run here
#: actually ends - a run with any Ineligible model reports it. Both SSE streams
#: test membership to decide when to send `end`, so neither ever terminated on
#: a normal run: they held the connection open until `max_seconds` and never
#: emitted the final events. The race showed every model stuck at "running"
#: long after its run had finished (docs/DECISIONS.md D-079).
#:
#: `cancelling` is deliberately absent - that run is still winding down.
_TERMINAL_RUN_STATES = frozenset(
    {"completed", "completed_with_warnings", "failed", "cancelled"}
)


def _resolve_build_id(db: Session, requested: str | None) -> str:
    if requested:
        return requested
    return panel_service.latest_build(db).id


def _estimate_out(estimate_dict: dict[str, Any]) -> RunEstimateOut:
    return RunEstimateOut.model_validate(estimate_dict)


@router.post(
    "/estimate",
    response_model=RunEstimateOut,
    summary="What the run will cost, without starting it",
)
def estimate(
    payload: TrainingRunRequest, db: Session = Depends(get_db)
) -> RunEstimateOut:
    settings = get_settings()
    hard = sorted(
        set(
            payload.hard_timeout_models
            if payload.hard_timeout_models is not None
            else DEFAULT_HARD_TIMEOUT_MODELS
        )
    )
    result = training_service.estimate_run(
        db,
        panel_build_id=_resolve_build_id(db, payload.panel_build_id),
        tiers=payload.tiers,
        max_local_series=(
            settings.max_local_series
            if payload.max_local_series is None
            else payload.max_local_series
        ),
        hard_timeout_models=hard,
    )
    return _estimate_out({**result.as_dict(), "hard_timeout_models": hard})


@router.post(
    "",
    response_model=TrainingRunSummary,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit a training run; returns a run id and the stored estimate",
)
def submit(
    payload: TrainingRunRequest, db: Session = Depends(get_db)
) -> TrainingRunSummary:
    run = training_service.start_run(
        db,
        panel_build_id=_resolve_build_id(db, payload.panel_build_id),
        tiers=payload.tiers,
        min_history_profile=payload.min_history_profile,
        xgboost_training_profile=payload.xgboost_training_profile,
        max_local_series=payload.max_local_series,
        local_series_selection=payload.local_series_selection,
        branches=payload.branches,
        skus=payload.skus,
        max_skus=payload.max_skus,
        total_budget_seconds=payload.total_budget_seconds,
        per_model_timeout_seconds=payload.per_model_timeout_seconds,
        hard_timeout_models=payload.hard_timeout_models,
    )
    return TrainingRunSummary.model_validate(run)


@router.get(
    "",
    response_model=Page[TrainingRunSummary],
    summary="List training runs, newest first",
)
def list_runs(
    offset: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=200),
    db: Session = Depends(get_db),
) -> Page[TrainingRunSummary]:
    rows, total = training_service.list_runs(db, offset=offset, limit=limit)
    return Page[TrainingRunSummary](
        items=[TrainingRunSummary.model_validate(row) for row in rows],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get(
    "/explain",
    summary="How training works: validation design, the 13 models, metrics and tuning",
)
def explain(db: Session = Depends(get_db)) -> Any:
    """Everything the Training tab shows, derived from the code that runs it.

    Not a document: fold boundaries come from `ml.evaluation.folds`, thresholds
    from each adapter's own `min_required_history`, the ranking rule from
    `ml.selection.champion`. A restated summary would drift; this cannot.
    """
    from app.services.training import explain as explain_service

    return explain_service.explain(db)


@router.get(
    "/{run_id}/accuracy-windows",
    summary="The same forecasts scored over one month, a quarter and half a year",
)
def accuracy_windows(
    run_id: str,
    scope_key: str | None = Query(
        None,
        description=(
            "One branch x SKU line, as 'BRANCH|SKU'. Omitted, the whole "
            "workspace is scored together."
        ),
    ),
    db: Session = Depends(get_db),
) -> Any:
    """Accuracy at each planning window, from the champions' own backtests.

    The leaderboard answers "how wrong on one SKU in one month". A plant
    usually acts on a quarter's total or a branch's total, which is the same
    forecasts added up differently - and measurably more accurate, because
    errors in both directions cancel. Nothing here is re-fitted and no metric
    is redefined; the monthly figure is the first row and is unchanged.
    """
    from app.services.training.accuracy_windows import accuracy_by_window

    training_service.get_run(db, run_id)
    return accuracy_by_window(db, run_id, scope_key=scope_key)


@router.get(
    "/current",
    response_model=TrainingRunSummary,
    summary="The most recent training run",
)
def current_run(db: Session = Depends(get_db)) -> TrainingRunSummary:
    rows, _ = training_service.list_runs(db, offset=0, limit=1)
    if not rows:
        from app.core.errors import NotFoundError

        raise NotFoundError(
            "No training run has been submitted yet.",
            remediation="POST /api/training to start one.",
        )
    return TrainingRunSummary.model_validate(rows[0])


@router.get(
    "/{run_id}",
    response_model=TrainingRunDetail,
    summary="Run detail with per-model status; no model is ever omitted",
)
def get_run(
    run_id: str,
    tier: str | None = Query(None),
    scope_level: str | None = Query(None),
    scope_key: str | None = Query(None),
    include_baselines: bool = Query(True),
    offset: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=2000),
    db: Session = Depends(get_db),
) -> TrainingRunDetail:
    run = training_service.get_run(db, run_id)
    rows, matching = training_service.model_runs_for(
        db,
        run_id,
        tier=tier,
        scope_level=scope_level,
        scope_key=scope_key,
        include_baselines=include_baselines,
        offset=offset,
        limit=limit,
    )

    # Status counts and the missing-model check are computed over the whole run,
    # never over the returned page: a page of 200 rows must not be able to make
    # a model look absent.
    counts = Counter(
        db.execute(
            select(ModelRun.status).where(ModelRun.training_run_id == run_id)
        ).scalars()
    )
    present = set(
        db.execute(
            select(ModelRun.model_id)
            .where(ModelRun.training_run_id == run_id)
            .distinct()
        ).scalars()
    )
    from app.ml.registry.canonical_models import CANONICAL_MODEL_IDS

    missing = [
        model_id for model_id in CANONICAL_MODEL_IDS if model_id not in present
    ]

    return TrainingRunDetail(
        run=TrainingRunSummary.model_validate(run),
        status_counts=[
            ModelStatusCount(status=key, count=value)
            for key, value in sorted(counts.items())
        ],
        models_missing=missing,
        model_runs=[ModelRunOut.model_validate(row) for row in rows],
        model_runs_returned=len(rows),
        model_runs_matching=matching,
        offset=offset,
        limit=limit,
    )


@router.get(
    "/{run_id}/model-runs",
    response_model=Page[ModelRunOut],
    summary="Per-model rows for a run, paginated; status is never filtered",
)
def list_model_runs(
    run_id: str,
    tier: str | None = Query(None),
    scope_level: str | None = Query(None),
    scope_key: str | None = Query(None),
    include_baselines: bool = Query(True),
    offset: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=2000),
    db: Session = Depends(get_db),
) -> Page[ModelRunOut]:
    training_service.get_run(db, run_id)
    rows, total = training_service.model_runs_for(
        db,
        run_id,
        tier=tier,
        scope_level=scope_level,
        scope_key=scope_key,
        include_baselines=include_baselines,
        offset=offset,
        limit=limit,
    )
    return Page[ModelRunOut](
        items=[ModelRunOut.model_validate(row) for row in rows],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get(
    "/{run_id}/calibrations",
    response_model=Page[QuantileCalibrationOut],
    summary="The (model, horizon, segment) quantile cells this run calibrated",
)
def list_calibrations(
    run_id: str,
    model_id: str | None = Query(None),
    horizon: int | None = Query(None, ge=1),
    offset: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=2000),
    db: Session = Depends(get_db),
) -> Page[QuantileCalibrationOut]:
    training_service.get_run(db, run_id)
    conditions = [QuantileCalibration.training_run_id == run_id]
    if model_id:
        conditions.append(QuantileCalibration.model_id == model_id)
    if horizon is not None:
        conditions.append(QuantileCalibration.horizon == horizon)
    total = (
        db.scalar(
            select(func.count()).select_from(QuantileCalibration).where(*conditions)
        )
        or 0
    )
    rows = list(
        db.scalars(
            select(QuantileCalibration)
            .where(*conditions)
            .order_by(
                QuantileCalibration.model_id,
                QuantileCalibration.horizon,
                QuantileCalibration.segment,
            )
            .offset(offset)
            .limit(limit)
        )
    )
    return Page[QuantileCalibrationOut](
        items=[QuantileCalibrationOut.model_validate(row) for row in rows],
        total=int(total),
        offset=offset,
        limit=limit,
    )


@router.post(
    "/{run_id}/cancel",
    response_model=TrainingRunSummary,
    summary="Request cancellation; rows already written are kept",
)
def cancel(run_id: str, db: Session = Depends(get_db)) -> TrainingRunSummary:
    return TrainingRunSummary.model_validate(training_service.cancel_run(db, run_id))


def _event_payload(run: TrainingRun) -> dict[str, Any]:
    return {
        "run_id": run.id,
        "status": run.status,
        "stage_detail": run.stage_detail,
        "progress_pct": run.progress_pct,
        "model_runs_total": run.model_runs_total,
        "model_runs_completed": run.model_runs_completed,
        "model_runs_ineligible": run.model_runs_ineligible,
        "model_runs_failed": run.model_runs_failed,
        "model_runs_timed_out": run.model_runs_timed_out,
        "model_runs_not_evaluated": run.model_runs_not_evaluated,
        "emitted_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get(
    "/{run_id}/monitor",
    summary="Per-model progress and the validation design, for the live monitor",
)
def monitor(run_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    """What every model is doing in this run, plus the fold design it used.

    The run-level SSE stream carries counters; counters cannot say *which*
    models are working and which are refusing, which is the question someone
    watching a run actually has. Aggregated here rather than in the browser
    because the per-model rows number in the hundreds and would be re-sent on
    every poll (docs/DECISIONS.md D-073).
    """
    from app.services.training import monitor as monitor_service

    run = training_service.get_run(db, run_id)
    return monitor_service.snapshot(db, run)


@router.get(
    "/{run_id}/model-events",
    summary="Per-model training events for the race: started/progress/finished/failed",
)
def model_events(
    run_id: str,
    poll_seconds: float = Query(1.0, ge=0.2, le=10.0),
    max_seconds: float = Query(1800.0, ge=1.0, le=86_400.0),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """How each model is scoring, as a stream.

    `/{run_id}/events` carries run-level counters, which cannot drive a race:
    the race needs each model's own score, not how much work is left. This
    emits the four-event contract the client speaks, with `epoch` meaning
    scopes scored so far (docs/DECISIONS.md D-078).

    The full field is replayed on connect, so a client arriving after a run
    ended still renders a complete race rather than an empty stage.
    """
    from app.services.training import race_events

    run = training_service.get_run(db, run_id)

    def stream() -> Iterator[str]:
        deadline = time.monotonic() + max_seconds
        seen: dict[str, tuple[int, float]] = {}

        while True:
            with session_scope() as scoped:
                current = scoped.get(TrainingRun, run_id)
                if current is None:
                    yield 'event: error\ndata: {"detail": "run disappeared"}\n\n'
                    return
                models = monitor_service.model_progress(scoped, run_id)
                terminal = current.status in _TERMINAL_RUN_STATES

            events, seen = race_events.diff(seen, models)
            for event in events:
                yield f"event: training\ndata: {json.dumps(event)}\n\n"

            if terminal:
                for event in race_events.terminal_events(models):
                    yield f"event: training\ndata: {json.dumps(event)}\n\n"
                yield f"event: end\ndata: {json.dumps({'run_id': run_id})}\n\n"
                return

            if time.monotonic() >= deadline:
                yield (
                    "event: timeout\ndata: "
                    + json.dumps({"detail": "stream reached max_seconds", "run_id": run_id})
                    + "\n\n"
                )
                return
            time.sleep(poll_seconds)

    _ = run
    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get(
    "/{run_id}/events",
    summary="Server-sent progress stream; closes when the run reaches a terminal state",
)
def events(
    run_id: str,
    poll_seconds: float = Query(1.0, ge=0.1, le=10.0),
    max_seconds: float = Query(900.0, ge=1.0, le=86_400.0),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    # Resolved once, up front, so an unknown id is a structured 404 rather than
    # a 200 that streams an error into the body.
    training_service.get_run(db, run_id)

    def stream() -> Iterator[str]:
        deadline = time.monotonic() + max_seconds
        last: str | None = None
        while True:
            with session_scope() as scoped:
                run = scoped.get(TrainingRun, run_id)
                if run is None:
                    yield "event: error\ndata: {\"detail\": \"run disappeared\"}\n\n"
                    return
                payload = _event_payload(run)
                terminal = run.status in _TERMINAL_RUN_STATES
            # Progress is emitted only when it changed, so a slow run does not
            # produce 900 identical frames; `emitted_at` is excluded from the
            # comparison for the same reason.
            fingerprint = json.dumps(
                {k: v for k, v in payload.items() if k != "emitted_at"},
                sort_keys=True,
            )
            if fingerprint != last:
                last = fingerprint
                yield f"event: progress\ndata: {json.dumps(payload)}\n\n"
            if terminal:
                yield f"event: end\ndata: {json.dumps(payload)}\n\n"
                return
            if time.monotonic() >= deadline:
                yield (
                    "event: timeout\ndata: "
                    + json.dumps(
                        {
                            "detail": (
                                "The stream reached max_seconds while the run was "
                                "still going. The run is unaffected; reconnect or "
                                "poll GET /api/training/{run_id}."
                            ),
                            "run_id": run_id,
                        }
                    )
                    + "\n\n"
                )
                return
            time.sleep(poll_seconds)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

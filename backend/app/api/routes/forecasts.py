"""Forecast generation and retrieval.

Generation is a background job that returns a run id; nothing forecasts inside
a request handler.

Retrieval defaults to including the rows that have **no** forecast, because a
scope whose champion would not refit is a fact a planner needs, and a response
that quietly returned five rows instead of six would hide it.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.errors import ValidationFailedError
from app.db.session import get_db
from app.ml.reconciliation.mint import METHODS
from app.schemas.common import Page
from app.schemas.forecasts import (
    ForecastRowOut,
    ForecastRunOut,
    ForecastRunRequest,
    HierarchyResponse,
    SeriesForecastResponse,
)
from app.services import forecast_service

router = APIRouter(prefix="/forecasts", tags=["forecasts"])


def _resolve_run_id(db: Session, requested: str | None) -> str:
    if requested:
        return forecast_service.get_run(db, requested).id
    return forecast_service.latest_run(db).id


@router.post(
    "/runs",
    response_model=ForecastRunOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Generate forecasts for horizons 1-6 from the active champions",
)
def create_run(
    payload: ForecastRunRequest, db: Session = Depends(get_db)
) -> ForecastRunOut:
    if payload.reconciliation not in METHODS:
        raise ValidationFailedError(
            f"Unknown reconciliation method {payload.reconciliation!r}.",
            details={"valid": list(METHODS)},
        )
    horizons = sorted({h for h in payload.horizons if h >= 1})
    if not horizons:
        raise ValidationFailedError(
            "At least one horizon of 1 or more is required.",
            details={"horizons": payload.horizons},
        )
    run = forecast_service.start_run(
        db,
        training_run_id=payload.training_run_id,
        reconciliation=payload.reconciliation,
        horizons=horizons,
    )
    return ForecastRunOut.model_validate(run)


@router.get(
    "/runs",
    response_model=Page[ForecastRunOut],
    summary="List forecast runs, newest first",
)
def list_runs(
    offset: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=200),
    db: Session = Depends(get_db),
) -> Page[ForecastRunOut]:
    rows, total = forecast_service.list_runs(db, offset=offset, limit=limit)
    return Page[ForecastRunOut](
        items=[ForecastRunOut.model_validate(row) for row in rows],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get(
    "/runs/current",
    response_model=ForecastRunOut,
    summary="The most recent completed forecast run",
)
def current_run(db: Session = Depends(get_db)) -> ForecastRunOut:
    return ForecastRunOut.model_validate(forecast_service.latest_run(db))


@router.get(
    "/runs/{run_id}",
    response_model=ForecastRunOut,
    summary="Forecast run detail, including the reconciliation verdict",
)
def get_run(run_id: str, db: Session = Depends(get_db)) -> ForecastRunOut:
    return ForecastRunOut.model_validate(forecast_service.get_run(db, run_id))


@router.get(
    "",
    response_model=Page[ForecastRowOut],
    summary="Query forecast rows by scope, period and model",
)
def query(
    forecast_run_id: str | None = Query(None),
    scope_level: str | None = Query(None),
    scope_key: str | None = Query(None),
    period_from: str | None = Query(None),
    period_to: str | None = Query(None),
    model_id: str | None = Query(None),
    include_unavailable: bool = Query(
        True,
        description=(
            "Rows with no forecast carry a reason and a null point forecast. "
            "Excluding them hides scopes the run could not serve."
        ),
    ),
    offset: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=2000),
    db: Session = Depends(get_db),
) -> Page[ForecastRowOut]:
    run_id = _resolve_run_id(db, forecast_run_id)
    rows, total = forecast_service.query_rows(
        db,
        forecast_run_id=run_id,
        scope_level=scope_level,
        scope_key=scope_key,
        period_from=period_from,
        period_to=period_to,
        model_id=model_id,
        include_unavailable=include_unavailable,
        offset=offset,
        limit=limit,
    )
    return Page[ForecastRowOut](
        items=[ForecastRowOut.model_validate(row) for row in rows],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get(
    "/series",
    response_model=SeriesForecastResponse,
    summary="One scope: history, horizons 1-6, point/q80/q90/q95, and drivers",
)
def series(
    scope_level: str = Query("national"),
    scope_key: str = Query("NATIONAL"),
    forecast_run_id: str | None = Query(None),
    history_months: int = Query(24, ge=1, le=120),
    db: Session = Depends(get_db),
) -> SeriesForecastResponse:
    run_id = _resolve_run_id(db, forecast_run_id)
    payload = forecast_service.series_payload(
        db,
        forecast_run_id=run_id,
        scope_level=scope_level,
        scope_key=scope_key,
        history_months=history_months,
    )
    return SeriesForecastResponse.model_validate(payload)


@router.get(
    "/hierarchy",
    response_model=HierarchyResponse,
    summary="Level totals with the reconciliation adjustment shown",
)
def hierarchy(
    forecast_run_id: str | None = Query(None),
    period: str | None = Query(None),
    db: Session = Depends(get_db),
) -> HierarchyResponse:
    run_id = _resolve_run_id(db, forecast_run_id)
    return HierarchyResponse.model_validate(
        forecast_service.hierarchy_payload(
            db, forecast_run_id=run_id, period=period
        )
    )

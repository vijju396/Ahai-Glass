"""Monitoring, scenarios, exports and the effective runtime settings.

Three routers' worth of surface, grouped because they share one property: they
are all read-only views over what other phases produced. Nothing here trains,
forecasts or writes a baseline.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.domain.ais.inventory import SERVICE_LEVELS
from app.ml.registry.canonical_models import (
    BASELINE_METHOD_IDS,
    CANONICAL_MODEL_IDS,
    REQUIRED_MODEL_COUNT,
)
from app.schemas.operations import (
    MonitoringResponse,
    ScenarioRequest,
    ScenarioResponse,
    SettingsResponse,
)
from app.services import export_service, monitoring_service, scenario_service

monitoring_router = APIRouter(prefix="/monitoring", tags=["monitoring"])
scenario_router = APIRouter(prefix="/scenarios", tags=["scenarios"])
export_router = APIRouter(prefix="/exports", tags=["exports"])
settings_router = APIRouter(prefix="/settings", tags=["settings"])


@monitoring_router.get(
    "",
    response_model=MonitoringResponse,
    summary="Data freshness, input drift, champion age and error deterioration",
)
def monitoring(db: Session = Depends(get_db)) -> MonitoringResponse:
    return MonitoringResponse.model_validate(monitoring_service.snapshot(db))


@scenario_router.post(
    "",
    response_model=ScenarioResponse,
    summary="Evaluate a what-if against a baseline forecast; never overwrites it",
)
def create_scenario(
    payload: ScenarioRequest, db: Session = Depends(get_db)
) -> ScenarioResponse:
    return ScenarioResponse.model_validate(
        scenario_service.evaluate(
            db,
            forecast_run_id=payload.baseline_forecast_run_id,
            name=payload.name,
            demand_multiplier=payload.demand_multiplier,
            service_level=payload.service_level,
            lead_time_days=payload.lead_time_days,
            review_period_days=payload.review_period_days,
            scope_level=payload.scope_level,
            scope_keys=payload.scope_keys,
            period=payload.period,
            limit=payload.limit,
        )
    )


@export_router.get(
    "/{kind}",
    summary="CSV of exactly what a page displays, including its unavailable rows",
    response_class=Response,
)
def export(
    kind: str,
    training_run_id: str | None = Query(None),
    forecast_run_id: str | None = Query(None),
    scope_level: str = Query("national"),
    scope_key: str = Query("NATIONAL"),
    service_level: int = Query(95, description=f"One of {list(SERVICE_LEVELS)}."),
    period: str | None = Query(None),
    limit: int = Query(5000, ge=1, le=100_000),
    db: Session = Depends(get_db),
) -> Response:
    filename, body = export_service.export(
        db,
        kind,
        training_run_id=training_run_id,
        forecast_run_id=forecast_run_id,
        scope_level=scope_level,
        scope_key=scope_key,
        service_level=service_level,
        period=period,
        limit=limit,
    )
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@export_router.get(
    "",
    summary="Which exports are available and which page each mirrors",
)
def list_exports() -> dict[str, Any]:
    return {
        "kinds": [
            {"kind": kind, "description": description}
            for kind, description in sorted(export_service.EXPORT_KINDS.items())
        ],
        "note": (
            "Every export contains the same rows the page showed, including the "
            "rows that carry a reason instead of a number. An empty metric cell "
            "means undefined, never zero."
        ),
    }


@settings_router.get(
    "",
    response_model=SettingsResponse,
    summary="The effective runtime configuration",
)
def effective_settings() -> SettingsResponse:
    settings = get_settings()
    return SettingsResponse(
        app_name=settings.app_name,
        app_version=settings.app_version,
        environment=settings.environment,
        official_model_count=REQUIRED_MODEL_COUNT,
        registered_model_ids=list(CANONICAL_MODEL_IDS),
        baseline_method_ids=list(BASELINE_METHOD_IDS),
        min_history_profile=settings.min_history_profile,
        xgboost_training_profile=settings.xgboost_training_profile,
        forecast_horizon_months=settings.forecast_horizon_months,
        service_levels=list(settings.service_levels),
        random_seed=settings.random_seed,
        max_local_series=settings.max_local_series,
        local_series_selection=settings.local_series_selection,
        per_model_timeout_seconds=settings.per_model_timeout_seconds,
        lstm_timeout_seconds=settings.lstm_timeout_seconds,
        max_training_workers=settings.max_training_workers,
        review_period_days=settings.review_period_days,
        default_lead_time_days=settings.default_lead_time_days,
        stock_snapshot_date=settings.stock_snapshot_date,
        mlflow_enabled=settings.mlflow_enabled,
        mlflow_tracking_uri=settings.mlflow_tracking_uri,
        database_dialect=settings.database_url.split(":", 1)[0],
        expected_controls={
            "sales_rows": settings.expected_sales_rows,
            "order_rows": settings.expected_order_rows,
            "stock_rows": settings.expected_stock_rows,
            "product_master_rows": settings.expected_product_master_rows,
            "location_master_rows": settings.expected_location_master_rows,
            "sales_skus": settings.expected_sales_skus,
            "series": settings.expected_series,
            "normalized_depots": settings.expected_normalized_depots,
        },
        notes=[
            "The database URL, file paths and MLflow artifact root are omitted "
            "deliberately: a settings page is not a place to publish "
            "filesystem layout. Only the dialect is exposed, because whether "
            "this is SQLite or PostgreSQL is a real operational fact.",
            "Changing these values is a deployment action, not a UI action - "
            "there is no write endpoint, so a planner cannot silently change "
            "the seed or the history profile behind a stored run.",
        ],
    )

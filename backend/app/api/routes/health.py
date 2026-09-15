"""Liveness/readiness. The only route that never requires auth."""

from __future__ import annotations

import importlib.util

from fastapi import APIRouter
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import engine
from app.ml.registry.canonical_models import (
    CANONICAL_MODEL_IDS,
    REQUIRED_MODEL_COUNT,
    assert_canonical_registry,
)
from app.schemas.common import HealthComponent, HealthResponse

router = APIRouter(tags=["health"])


def _check_database() -> HealthComponent:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return HealthComponent(name="database", status="ok")
    except Exception as exc:
        return HealthComponent(
            name="database", status="error", detail=type(exc).__name__
        )


def _check_registry() -> HealthComponent:
    try:
        assert_canonical_registry()
        return HealthComponent(
            name="model_registry",
            status="ok",
            detail=f"{len(CANONICAL_MODEL_IDS)} of {REQUIRED_MODEL_COUNT} models registered.",
        )
    except AssertionError as exc:
        return HealthComponent(name="model_registry", status="error", detail=str(exc))


def _check_source_data() -> HealthComponent:
    settings = get_settings()
    expected = {
        "Sales Data FY 24~26.xlsb",
        "Orders & Receipts (Lead Time).xlsx",
        "Stock in Hand as on 1st Aug'26.xlsx",
        "Substitution Mapping.xlsx",
        "Location Master.csv",
    }
    if not settings.source_data_dir.exists():
        return HealthComponent(
            name="source_data", status="error", detail="data/source is missing."
        )
    present = {p.name for p in settings.source_data_dir.iterdir() if p.is_file()}
    missing = sorted(expected - present)
    if missing:
        return HealthComponent(
            name="source_data",
            status="degraded",
            detail=f"{len(missing)} of 5 source files missing: {missing}",
        )
    return HealthComponent(
        name="source_data", status="ok", detail="All 5 source files present."
    )


def _check_ml_dependencies() -> HealthComponent:
    required = ("statsmodels", "pmdarima", "xgboost", "sklearn", "tensorflow")
    missing = [m for m in required if importlib.util.find_spec(m) is None]
    if missing:
        return HealthComponent(
            name="ml_dependencies",
            status="degraded",
            detail=f"Not installed: {missing}. Affected models report Ineligible with this reason.",
        )
    return HealthComponent(name="ml_dependencies", status="ok")


def _check_mlflow() -> HealthComponent:
    settings = get_settings()
    if not settings.mlflow_enabled:
        return HealthComponent(
            name="mlflow", status="ok", detail="Disabled by configuration."
        )
    if importlib.util.find_spec("mlflow") is None:
        return HealthComponent(
            name="mlflow", status="degraded", detail="mlflow is not installed."
        )
    return HealthComponent(
        name="mlflow", status="ok", detail=settings.mlflow_tracking_uri
    )


@router.get("/health", response_model=HealthResponse, summary="Service health")
def health() -> HealthResponse:
    settings = get_settings()
    components = [
        _check_database(),
        _check_registry(),
        _check_source_data(),
        _check_ml_dependencies(),
        _check_mlflow(),
    ]
    statuses = {c.status for c in components}
    overall = "error" if "error" in statuses else ("degraded" if "degraded" in statuses else "ok")
    return HealthResponse(
        status=overall,
        app_name=settings.app_name,
        version=settings.app_version,
        environment=settings.environment,
        components=components,
    )

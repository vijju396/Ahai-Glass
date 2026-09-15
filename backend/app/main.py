"""FastAPI application factory.

The registry assertion runs at startup, before the app accepts traffic: if the
official 13 have drifted in count, order, or naming, the process refuses to
start rather than serving a quietly wrong leaderboard.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging, get_logger, set_correlation_id
from app.ml.registry.canonical_models import (
    CANONICAL_MODEL_IDS,
    REQUIRED_MODEL_COUNT,
    assert_canonical_registry,
)

logger = get_logger(__name__)

CORRELATION_HEADER = "X-Correlation-ID"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging("DEBUG" if settings.debug else "INFO")
    settings.ensure_runtime_dirs()

    # Startup assertion required by the build contract: exactly these 13 IDs,
    # in this order. Failing here is deliberate and preferable to booting.
    #
    # Two checks, not one: the canonical list, then the adapters actually bound
    # to it. A drift in either - a renamed display name, a reordered id, a
    # capability flag disagreeing with the registry - stops the process rather
    # than serving a quietly wrong leaderboard.
    assert_canonical_registry()
    from app.ml.registry.model_registry import assert_registry_bound

    assert_registry_bound()
    logger.info(
        "registry_verified",
        extra={
            "model_count": len(CANONICAL_MODEL_IDS),
            "required": REQUIRED_MODEL_COUNT,
            "min_history_profile": settings.min_history_profile,
        },
    )
    # Alembic owns the schema. `ensure_schema` upgrades to head on a fresh
    # clone, and adopts a pre-baseline database by stamping rather than
    # rebuilding it - see app/db/migrate.py.
    import app.models  # noqa: F401 - registers every table on Base.metadata
    from app.db.migrate import ensure_schema

    ensure_schema()

    # The job runner is in-process, so a restart orphans any run that was
    # executing - its row would say `running` forever. Correct those now,
    # before the app serves a status it cannot back up.
    from app.services.training.training_service import reconcile_orphaned_runs

    orphaned = reconcile_orphaned_runs()
    if orphaned:
        logger.warning("orphaned_runs_reconciled", extra={"count": orphaned})

    logger.info(
        "startup_complete",
        extra={"app": settings.app_name, "version": settings.app_version},
    )
    yield
    from app.jobs.runner import shutdown_runner

    shutdown_runner()
    logger.info("shutdown_complete")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "Demand forecasting and inventory intelligence for the AIS Consumer "
            "Glass Solutions branch network. Forecasts ordered quantity at "
            "branch x SKU x month across 13 registered models."
        ),
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )

    # CORS is scoped to the React dev origin only - never a wildcard.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.frontend_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", CORRELATION_HEADER],
        expose_headers=[CORRELATION_HEADER],
    )

    @app.middleware("http")
    async def _correlation(request: Request, call_next):  # noqa: ANN001, ANN202
        correlation_id = set_correlation_id(request.headers.get(CORRELATION_HEADER))
        response = await call_next(request)
        response.headers[CORRELATION_HEADER] = correlation_id
        return response

    register_exception_handlers(app)
    app.include_router(api_router)
    return app


app = create_app()

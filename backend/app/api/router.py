"""Aggregates every versioned route under /api."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.routes import (
    analytics,
    assistant,
    datasets,
    forecasts,
    health,
    inventory,
    mappings,
    models,
    operations,
    panel,
    training,
)

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router)
api_router.include_router(models.router)
api_router.include_router(datasets.router)
api_router.include_router(mappings.router)
api_router.include_router(panel.router)
api_router.include_router(training.router)
api_router.include_router(forecasts.router)
api_router.include_router(inventory.router)
api_router.include_router(operations.monitoring_router)
api_router.include_router(operations.scenario_router)
api_router.include_router(operations.export_router)
api_router.include_router(operations.settings_router)
api_router.include_router(analytics.router)
api_router.include_router(assistant.router)

"""Inventory recommendations and the supply picture.

Every recommendation row exposes its own calculation and is labelled a
current-snapshot estimate. A branch x SKU that cannot be recommended for comes
back with a reason rather than being dropped or zeroed.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.domain.ais.inventory import SERVICE_LEVELS
from app.schemas.inventory import (
    RecommendationsResponse,
    SupplyOverviewResponse,
    TransferableStockResponse,
)
from app.services import inventory_service

router = APIRouter(prefix="/inventory", tags=["inventory"])


@router.get(
    "/recommendations",
    response_model=RecommendationsResponse,
    summary="Per branch x SKU order recommendations, with the calculation shown",
)
def recommendations(
    forecast_run_id: str | None = Query(None),
    period: str | None = Query(
        None, description="Defaults to the first forecast period of the run."
    ),
    service_level: int = Query(
        95, description=f"One of {list(SERVICE_LEVELS)}."
    ),
    scope_level: str = Query(
        "series",
        description=(
            "A replenishment order is placed per branch x SKU, so `series` is "
            "the meaningful level. Other levels return a stated reason rather "
            "than an aggregate dressed as a line item."
        ),
    ),
    branch: str | None = Query(None),
    sku: str | None = Query(None),
    include_unavailable: bool = Query(
        True,
        description=(
            "Rows that cannot be recommended for carry a reason. Excluding them "
            "hides positions a planner needs to know about."
        ),
    ),
    only_actionable: bool = Query(
        False, description="Only rows with a recommended order above zero."
    ),
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> RecommendationsResponse:
    return RecommendationsResponse.model_validate(
        inventory_service.recommendations(
            db,
            forecast_run_id=forecast_run_id,
            period=period,
            service_level=service_level,
            scope_level=scope_level,
            branch=branch,
            sku=sku,
            include_unavailable=include_unavailable,
            only_actionable=only_actionable,
            offset=offset,
            limit=limit,
        )
    )


@router.get(
    "/overview",
    response_model=SupplyOverviewResponse,
    summary="Cover, dead stock and zero-stock-against-live-demand positions",
)
def overview(
    forecast_run_id: str | None = Query(None),
    period: str | None = Query(None),
    branch: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
) -> SupplyOverviewResponse:
    return SupplyOverviewResponse.model_validate(
        inventory_service.supply_overview(
            db,
            forecast_run_id=forecast_run_id,
            period=period,
            branch=branch,
            limit=limit,
        )
    )


@router.get(
    "/transferable",
    response_model=TransferableStockResponse,
    summary="Which other branches hold this SKU (holdings, not a transfer plan)",
)
def transferable(
    canonical_sku: str = Query(...),
    exclude_branch: str | None = Query(None),
    forecast_run_id: str | None = Query(None),
    limit: int = Query(25, ge=1, le=200),
    db: Session = Depends(get_db),
) -> TransferableStockResponse:
    return TransferableStockResponse.model_validate(
        inventory_service.transferable_stock(
            db,
            canonical_sku=canonical_sku,
            exclude_branch=exclude_branch,
            forecast_run_id=forecast_run_id,
            limit=limit,
        )
    )

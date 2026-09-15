"""Inventory payloads.

Each row returns the **inputs**, not just the answer: order-up-to level, usable
stock, confirmed stock on order, backorders, lead time, review period,
protection period, service level and recommended order, plus `warnings[]` and
`unavailable_reason`. Every row is labelled a current-snapshot estimate.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from app.schemas.common import ApiModel


class RecommendationOut(ApiModel):
    scope_key: str
    canonical_branch: str | None = None
    canonical_sku: str | None = None
    service_level: int
    forecast_period: str | None = None
    forecast_model_id: str | None = None
    demand_segment: str | None = None
    stock_class: str | None = None

    monthly_point_forecast: float | None = None
    monthly_quantile_forecast: float | None = None

    review_period_days: int
    lead_time_days: float | None = None
    lead_time_source: str | None = None
    lead_time_p95_days: float | None = None
    protection_period_days: float | None = None
    protection_months: float | None = None

    usable_stock_on_hand: float | None = None
    closing_stock_on_hand: float | None = None
    negative_stock_rows: int = 0
    confirmed_stock_on_order: float = 0.0
    backorders: float = 0.0

    order_up_to_level: float | None = None
    #: Before MOQ / case-pack / truck rounding, so the rounding is visible.
    raw_recommended_order: float | None = None
    recommended_order: float | None = None
    days_of_cover: float | None = None

    moq: float | None = None
    truck_quantity: float | None = None
    case_pack: float | None = None
    substitute_skus: list[str] = Field(default_factory=list)

    target_source: str | None = None
    is_censored: bool | None = None
    unavailable_reason: str | None = None
    warnings: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    is_current_snapshot_estimate: bool = True


class RecommendationsResponse(ApiModel):
    #: What this deployment reports on. Carried so a two-branch figure can
    #: never read as a national one - the restriction is applied upstream, and
    #: this is what states it (docs/DECISIONS.md D-049).
    workspace_scope: dict[str, Any] | None = None
    forecast_run_id: str
    period: str
    service_level: int
    scope_level: str
    items: list[RecommendationOut]
    total: int
    offset: int
    limit: int
    #: Set when the run produced no rows at the requested level - a
    #: replenishment order needs branch x SKU forecasts.
    unavailable_reason: str | None = None
    notes: list[str] = Field(default_factory=list)


class SupplyTotals(ApiModel):
    positions: int
    positions_with_stock: int
    dead_or_slow_positions: int
    dead_stock_units: float
    dead_stock_value: float | None = None
    zero_stock_live_demand_positions: int
    unfilled_recent_demand_units: float
    negative_stock_rows: int = 0


class DeadStockRow(ApiModel):
    canonical_branch: str | None = None
    canonical_sku: str | None = None
    usable_qty: float
    closing_value: float | None = None
    recent_demand: float
    stock_class: str | None = None


class ZeroStockRow(ApiModel):
    canonical_branch: str | None = None
    canonical_sku: str | None = None
    usable_qty: float
    recent_demand: float


class SupplyOverviewResponse(ApiModel):
    #: What this deployment reports on. Carried so a two-branch figure can
    #: never read as a national one - the restriction is applied upstream, and
    #: this is what states it (docs/DECISIONS.md D-049).
    workspace_scope: dict[str, Any] | None = None
    forecast_run_id: str
    period: str | None = None
    branch: str | None = None
    stock_snapshot_date: str
    totals: SupplyTotals
    dead_stock: list[DeadStockRow] = Field(default_factory=list)
    zero_stock_live_demand: list[ZeroStockRow] = Field(default_factory=list)
    lead_time_assumptions: dict[str, Any] = Field(default_factory=dict)
    review_period_days: int
    caveats: list[str] = Field(default_factory=list)


class HolderRow(ApiModel):
    canonical_branch: str
    usable_qty: float
    closing_qty: float
    stock_class: str | None = None


class TransferableStockResponse(ApiModel):
    canonical_sku: str
    excluded_branch: str | None = None
    holders: list[HolderRow] = Field(default_factory=list)
    total_holders: int
    total_usable_units: float
    #: Holdings only - the source set has no lane, cost or transit time, so
    #: this is deliberately not a transfer plan.
    caveat: str

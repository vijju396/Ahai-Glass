"""Forecast payloads.

Every row carries its lineage (`training_run_id` through `model_run_id` and
`champion_selection_id`), the reconciliation adjustment as a separate field
rather than folded into the number, and the provenance of its interval.

A row with `unavailable_reason` set has a **null** point forecast, never a zero.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from app.schemas.common import ApiModel

PERIOD_PATTERN = r"^\d{4}-\d{2}$"


class ForecastRunRequest(ApiModel):
    training_run_id: str | None = Field(
        default=None,
        description="Defaults to the newest training run with an active champion.",
    )
    reconciliation: str = Field(
        default="mint_shrinkage",
        description=(
            "mint_shrinkage | mint_variance | bottom_up | proportional | none. "
            "A method whose covariance cannot be estimated falls back and the "
            "run records what it fell back from."
        ),
    )
    horizons: list[int] = Field(default_factory=lambda: [1, 2, 3, 4, 5, 6])


class ForecastRunOut(ApiModel):
    id: str
    training_run_id: str
    panel_build_id: str
    status: str
    stage_detail: str | None = None
    progress_pct: float = 0.0
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_seconds: float | None = None
    failure_reason: str | None = None

    origin_period: str
    horizons: str

    requested_reconciliation: str | None = None
    reconciliation_method: str | None = None
    reconciliation_fallback_from: str | None = None
    reconciliation_fallback_reason: str | None = None
    shrinkage_intensity: float | None = None

    coherent: bool = False
    max_incoherence: float | None = None
    negatives_clipped: int = 0
    quantile_crossings_corrected: int = 0

    series_forecast: int = 0
    rows_written: int = 0
    rows_unavailable: int = 0

    summary: dict[str, Any] | None = Field(
        default=None, validation_alias="summary_json"
    )
    warnings: list[Any] | None = Field(default=None, validation_alias="warnings_json")


class ForecastRowOut(ApiModel):
    id: str
    forecast_run_id: str
    scope_level: str
    scope_key: str
    canonical_branch: str | None = None
    canonical_sku: str | None = None
    region: str | None = None
    demand_segment: str | None = None
    value_class: str | None = None

    period: str
    horizon: int

    model_id: str | None = None
    model_display_name: str | None = None
    model_run_id: str | None = None
    champion_selection_id: str | None = None
    forecast_source: str | None = None

    point_forecast: float | None = None
    q80: float | None = None
    q90: float | None = None
    q95: float | None = None

    base_forecast: float | None = None
    reconciliation_adjustment: float | None = None
    reconciliation_method: str | None = None

    quantile_method: str | None = None
    quantile_pooling_level: str | None = None
    quantile_residual_count: int = 0

    target_source: str | None = None
    is_censored: bool | None = None
    unavailable_reason: str | None = None
    drivers: dict[str, Any] | None = Field(
        default=None, validation_alias="drivers_json"
    )


class HistoryPoint(ApiModel):
    period: str
    actual: float
    is_censored: bool = False
    target_source: str | None = None


class ValidationMetrics(ApiModel):
    model_id: str
    display_name: str
    wape: float | None = None
    mae: float | None = None
    rmse: float | None = None
    mape: float | None = None
    smape: float | None = None
    mase: float | None = None
    bias: float | None = None
    validation_points: int = 0
    evaluation_mode: str | None = None


class SeriesForecastResponse(ApiModel):
    forecast_run_id: str
    training_run_id: str
    scope_level: str
    scope_key: str
    origin_period: str
    history: list[HistoryPoint]
    #: Why the history is empty, when it is. The forecast rows are unaffected
    #: by an unreadable panel artifact, so this degrades rather than 500s.
    history_unavailable_reason: str | None = None
    forecasts: list[ForecastRowOut]
    validation_metrics: ValidationMetrics | None = None
    drivers: dict[str, Any] | None = None
    reconciliation_method: str | None = None
    coherent: bool = False
    snapshot_caveat: str


class LevelTotals(ApiModel):
    scope_level: str
    nodes: int
    point_total: float
    base_total: float
    adjustment_total: float
    q95_total: float


class LevelGap(ApiModel):
    from_level: str
    to_level: str
    difference: float
    coherent: bool
    #: False where the lower level is a deliberate subset of the network, so
    #: the two totals were never expected to agree. Without this a run that
    #: includes the top-N local tier would report a false coherence failure.
    expected_coherent: bool = True
    reason: str | None = None


class HierarchyResponse(ApiModel):
    forecast_run_id: str
    origin_period: str
    period: str | None = None
    levels: list[LevelTotals]
    #: Coherence re-checked from the persisted rows, not taken from the run's
    #: own flag.
    level_gaps: list[LevelGap]
    reconciliation_base_level: str | None = None
    #: Levels finer than the base, which are a subset of the network.
    partial_levels: list[str] = Field(default_factory=list)
    reconciliation_method: str | None = None
    reconciliation_fallback_from: str | None = None
    reconciliation_fallback_reason: str | None = None
    coherent: bool = False
    max_incoherence: float | None = None
    quantile_crossings_corrected: int = 0

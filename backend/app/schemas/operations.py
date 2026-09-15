"""Monitoring, scenario and settings payloads.

Every monitoring measure is `available`/`computable` plus a `reason`, never a
bare number that might be a default. "Not yet computable" and "no problem
detected" are different answers, and the schema forces the distinction.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field, field_validator

from app.domain.ais.inventory import SERVICE_LEVELS
from app.schemas.common import ApiModel


class FreshnessOut(ApiModel):
    demand_history_end: str | None = None
    demand_history_age_months: int | None = None
    stock_snapshot_date: str
    stock_snapshot_age_months: int | None = None
    panel_built_at: datetime | None = None
    panel_rows: int = 0
    dataset_ingested_at: datetime | None = None
    note: str


class DriftRow(ApiModel):
    scope_level: str
    scope_key: str
    earlier_mean_monthly_demand: float | None = None
    recent_mean_monthly_demand: float | None = None
    shift_pct: float | None = None


class DriftWindow(ApiModel):
    months: int
    mean_monthly_demand: float | None = None
    rows: int


class DriftComparison(ApiModel):
    earlier: DriftWindow
    recent: DriftWindow
    shift_pct: float | None = None


class DriftOut(ApiModel):
    available: bool
    reason: str | None = None
    window_months: int
    recent_periods: list[str] = Field(default_factory=list)
    national: DriftComparison | None = None
    target_sources_recent: list[str] = Field(default_factory=list)
    target_sources_earlier: list[str] = Field(default_factory=list)
    target_source_changed: bool = False
    rows: list[DriftRow] = Field(default_factory=list)
    note: str | None = None


class ChampionAgeRow(ApiModel):
    scope_kind: str
    scope_key: str
    champion_model_id: str
    selection_source: str
    selected_at: datetime | None = None
    age_days: float | None = None
    training_run_id: str
    from_newest_training_run: bool
    beaten_by_baseline: bool


class ChampionAgeOut(ApiModel):
    active_champions: int
    newest_training_run_id: str | None = None
    champions_from_older_runs: int
    champions_beaten_by_a_baseline: int
    rows: list[ChampionAgeRow] = Field(default_factory=list)
    note: str


class DeteriorationRow(ApiModel):
    scope_level: str
    scope_key: str
    period: str
    model_id: str | None = None
    actual: float
    point_forecast: float
    absolute_error: float
    accrued_wape: float | None = None
    backtest_wape: float | None = None
    deterioration_pct: float | None = None


class DeteriorationOut(ApiModel):
    #: False means it has not been checked, which is not the same as "no
    #: deterioration". The reason says which.
    computable: bool
    reason: str | None = None
    origin_period: str | None = None
    forecast_periods: list[str] = Field(default_factory=list)
    observed_forecast_periods: list[str] = Field(default_factory=list)
    rows: list[DeteriorationRow] = Field(default_factory=list)
    note: str | None = None


class MonitoringResponse(ApiModel):
    generated_at: datetime
    #: What this deployment reports on. Carried so a two-branch figure can
    #: never read as a national one - the restriction is applied upstream, and
    #: this is what states it (docs/DECISIONS.md D-049).
    workspace_scope: dict[str, Any] | None = None
    freshness: FreshnessOut
    drift: DriftOut
    champions: ChampionAgeOut
    deterioration: DeteriorationOut
    note: str


class ScenarioRequest(ApiModel):
    name: str = Field(default="Scenario", max_length=120)
    baseline_forecast_run_id: str | None = Field(
        default=None, description="Defaults to the newest completed forecast run."
    )
    demand_multiplier: float = Field(default=1.0, gt=0)
    service_level: int = 95
    lead_time_days: float | None = Field(default=None, ge=0)
    review_period_days: int | None = Field(default=None, ge=1)
    scope_level: str = "branch"
    scope_keys: list[str] | None = None
    period: str | None = None
    limit: int = Field(default=200, ge=1, le=5000)

    @field_validator("service_level")
    @classmethod
    def _known_level(cls, value: int) -> int:
        if value not in SERVICE_LEVELS:
            raise ValueError(
                f"Service level {value} is not offered. Valid: {list(SERVICE_LEVELS)}."
            )
        return value


class ScenarioRow(ApiModel):
    scope_key: str
    period: str
    horizon: int
    model_id: str | None = None
    baseline_point: float | None = None
    scenario_point: float | None = None
    baseline_quantile: float | None = None
    scenario_quantile: float | None = None
    baseline_recommended_order: float | None = None
    scenario_recommended_order: float | None = None
    unavailable_reason: str | None = None


class ScenarioLevers(ApiModel):
    demand_multiplier: float
    service_level: int
    lead_time_days: float | None = None
    baseline_lead_time_days: float
    review_period_days: int
    baseline_review_period_days: int


class ScenarioTotals(ApiModel):
    baseline_demand: float
    scenario_demand: float
    demand_delta: float
    demand_delta_pct: float | None = None
    baseline_order_quantity: float
    scenario_order_quantity: float
    order_delta: float
    order_delta_pct: float | None = None


class ScenarioResponse(ApiModel):
    name: str
    generated_at: datetime
    baseline_forecast_run_id: str
    baseline_origin_period: str
    scope_level: str
    period: str | None = None
    levers: ScenarioLevers
    totals: ScenarioTotals
    rows: list[ScenarioRow]
    rows_returned: int
    rows_without_baseline: int
    caveats: list[str]


class SettingsResponse(ApiModel):
    app_name: str
    app_version: str
    environment: str
    official_model_count: int
    registered_model_ids: list[str]
    baseline_method_ids: list[str]
    min_history_profile: str
    xgboost_training_profile: str
    forecast_horizon_months: int
    service_levels: list[int]
    random_seed: int
    max_local_series: int
    local_series_selection: str
    per_model_timeout_seconds: float
    lstm_timeout_seconds: float
    max_training_workers: int
    review_period_days: int
    default_lead_time_days: float
    stock_snapshot_date: str
    mlflow_enabled: bool
    mlflow_tracking_uri: str
    #: Dialect only. A settings page is not a place to publish a connection
    #: string or a filesystem layout.
    database_dialect: str
    expected_controls: dict[str, int]
    notes: list[str]

"""Training run payloads.

Two things this module is deliberately strict about:

**Every model appears.** `TrainingRunDetail.model_runs` is built from the
`model_run` rows without a status filter, and `models_missing` is computed by
subtracting what is present from the canonical thirteen. If that list is ever
non-empty the response says so rather than letting the omission pass silently.

**The estimate is part of the submission response**, not a separate endpoint
nobody calls. `POST /api/training` returns 202 with the estimate that was
stored on the run, so the number the user saw is the number that was recorded.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field, field_validator

from app.schemas.common import ApiModel

#: The tiers a run may request, in execution order.
TIER_VALUES: tuple[str, ...] = ("aggregate", "local", "pooled")


class TrainingRunRequest(ApiModel):
    """Submit a run. Everything except the panel build has a settings default."""

    panel_build_id: str | None = Field(
        default=None,
        description="Defaults to the most recent completed panel build.",
    )
    tiers: list[str] = Field(
        default_factory=lambda: list(TIER_VALUES),
        description=(
            "aggregate = national/region/branch totals; local = per-series for "
            "the top-N series; pooled = the global XGBoost panel over the whole "
            "network. Executed in that order so a cancelled run still produced "
            "its cheapest, most aggregated results."
        ),
    )
    min_history_profile: str | None = Field(
        default=None, description="reference | conservative"
    )
    xgboost_training_profile: str | None = Field(
        default=None, description="fast | thorough"
    )
    max_local_series: int | None = Field(default=None, ge=0, le=100_000)
    local_series_selection: str | None = Field(
        default=None, description="value | volume | shortfall"
    )
    branches: list[str] | None = Field(
        default=None,
        max_length=60,
        description=(
            "Restrict the whole run to these branches. A full run covers all 53 "
            "and takes tens of minutes; naming two makes iteration practical. "
            "The run records what it covered, and a restricted run's results "
            "describe that slice rather than the network."
        ),
    )
    skus: list[str] | None = Field(
        default=None,
        max_length=5000,
        description=(
            "Train on exactly these SKUs. Takes precedence over `max_skus`, which "
            "picks a top-N by value - when the caller has already chosen a "
            "stratified set, ranking would substitute a different one."
        ),
    )
    max_skus: int | None = Field(
        default=None,
        ge=1,
        le=100_000,
        description=(
            "Keep only the top-N SKUs by the selection measure, ranked *within* "
            "the chosen branches. Omit for every SKU."
        ),
    )
    total_budget_seconds: float | None = Field(default=None, gt=0)
    per_model_timeout_seconds: float | None = Field(default=None, gt=0)
    hard_timeout_models: list[str] | None = None

    @field_validator("tiers")
    @classmethod
    def _known_tiers(cls, value: list[str]) -> list[str]:
        unknown = [tier for tier in value if tier not in TIER_VALUES]
        if unknown:
            raise ValueError(
                f"Unknown tier(s) {unknown}. Valid tiers: {list(TIER_VALUES)}."
            )
        return value


class TierEstimateOut(ApiModel):
    tier: str
    series: int
    origins: int
    models: list[str]
    fits: int
    seconds: float
    seconds_upper: float
    notes: list[str]


class RunEstimateOut(ApiModel):
    """The cost of a run, shown before it is allowed to start."""

    tiers: list[TierEstimateOut]
    workers: int
    total_fits: int
    estimated_seconds: float
    estimated_seconds_upper: float
    estimated_human: str
    estimated_human_upper: str
    provenance: str
    hard_timeout_models: list[str] = Field(default_factory=list)


class TrainingRunSummary(ApiModel):
    """One run, without its per-model rows."""

    id: str
    panel_build_id: str
    status: str
    stage_detail: str | None
    progress_pct: float
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    duration_seconds: float | None
    failure_reason: str | None
    cancelled_at: datetime | None

    tiers: str
    min_history_profile: str
    xgboost_training_profile: str
    max_local_series: int
    local_series_selection: str | None
    #: Null on an unrestricted run. On a scoped run it carries the requested
    #: branches and SKU cap plus, once measured, what they actually matched -
    #: so a reader can tell a two-branch run from a network one.
    restriction: dict[str, Any] | None = Field(
        default=None, validation_alias="restriction_json"
    )

    estimated_seconds: float | None
    total_budget_seconds: float | None
    per_model_timeout_seconds: float | None
    lstm_timeout_seconds: float | None

    series_requested: int
    series_evaluated: int
    model_runs_total: int
    model_runs_completed: int
    model_runs_ineligible: int
    model_runs_failed: int
    model_runs_timed_out: int
    model_runs_not_evaluated: int
    residuals_recorded: int
    mlflow_run_id: str | None

    estimate: dict[str, Any] | None = Field(
        default=None, validation_alias="estimate_json"
    )
    origins: dict[str, Any] | None = Field(
        default=None, validation_alias="origins_json"
    )
    summary: dict[str, Any] | None = Field(
        default=None, validation_alias="summary_json"
    )
    warnings: list[Any] | None = Field(default=None, validation_alias="warnings_json")


class ModelRunOut(ApiModel):
    """One (scope, model) evaluation, whatever its outcome."""

    id: str
    training_run_id: str
    tier: str
    scope_level: str
    scope_key: str
    segment: str | None

    model_id: str
    display_name: str
    is_baseline: bool

    status: str
    evaluation_mode: str | None
    failure_reason: str | None
    eligibility: dict[str, Any] | None = Field(
        default=None, validation_alias="eligibility_json"
    )

    seasonal_period: int | None
    origins_completed: int
    origins_total: int
    validation_points: int
    total_test_points: int
    duplicate_test_points: int

    mae: float | None
    rmse: float | None
    wape: float | None
    mape: float | None
    accuracy: float | None
    smape: float | None
    mase: float | None
    bias: float | None
    bias_abs: float | None
    naive_mae: float | None

    legacy_mape: float | None
    legacy_wape: float | None
    legacy_mae: float | None
    legacy_valid: bool

    zero_actual_points: int
    censored_points: int
    negative_predictions: int
    max_abs_prediction: float | None

    fit_seconds: float | None
    predict_seconds: float | None
    artifact_path: str | None
    mlflow_run_id: str | None
    parameters: dict[str, Any] | None = Field(
        default=None, validation_alias="parameters_json"
    )
    features: list[Any] | None = Field(default=None, validation_alias="features_json")
    origins: list[Any] | None = Field(default=None, validation_alias="origins_json")


class ModelStatusCount(ApiModel):
    status: str
    count: int


class TrainingRunDetail(ApiModel):
    """A run plus enough of its per-model rows to answer "what happened"."""

    run: TrainingRunSummary
    status_counts: list[ModelStatusCount]
    #: Registry models with no row in this run. Non-empty means a defect, and
    #: the field exists so it cannot be invisible.
    models_missing: list[str] = Field(default_factory=list)
    model_runs: list[ModelRunOut] = Field(default_factory=list)
    model_runs_returned: int = 0
    model_runs_matching: int = 0
    offset: int = 0
    limit: int = 0


class QuantileCalibrationOut(ApiModel):
    """One (model, horizon, segment) calibration cell."""

    model_id: str
    horizon: int
    segment: str
    residual_count: int
    offsets: dict[str, Any] = Field(validation_alias="offsets_json")
    pooling_level: str | None
    method: str | None


class TrainingEvent(ApiModel):
    """One progress tick on the SSE stream."""

    run_id: str
    status: str
    stage_detail: str | None
    progress_pct: float
    model_runs_total: int
    model_runs_completed: int
    model_runs_ineligible: int
    model_runs_failed: int
    model_runs_timed_out: int
    model_runs_not_evaluated: int
    emitted_at: datetime

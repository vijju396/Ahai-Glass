"""Leaderboard, champion and diagnostics payloads.

The leaderboard row carries **both rankings side by side** - `rank` (the AIS
operational ranking: WAPE, absolute bias, MAE, model id) and `legacy_rank` (the
references' lowest-valid-MAPE rule) - and never a blended one
(`docs/DECISIONS.md` D-011).

Every metric is optional, and `None` means undefined rather than zero. A row
whose `ranked` is false still appears, with `exclusion` and `exclusion_reason`
saying why it is not in the order.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field, field_validator

from app.models.champions import MIN_OVERRIDE_REASON_CHARS, SCOPE_KINDS
from app.schemas.common import ApiModel


class LeaderboardRow(ApiModel):
    model_id: str
    display_name: str
    status: str
    is_baseline: bool
    evaluation_mode: str | None = None

    rank: int | None = None
    legacy_rank: int | None = None
    is_champion: bool = False
    is_challenger: bool = False
    ranked: bool = False
    exclusion: str | None = None
    exclusion_reason: str | None = None
    comparability_note: str | None = None

    wape: float | None = None
    mae: float | None = None
    rmse: float | None = None
    mape: float | None = None
    accuracy: float | None = None
    smape: float | None = None
    mase: float | None = None
    bias: float | None = None
    bias_abs: float | None = None
    legacy_mape: float | None = None
    legacy_valid: bool = False

    validation_points: int = 0
    distinct_test_points: int = 0
    origins_completed: int = 0
    origins_total: int = 0
    failure_reason: str | None = None
    model_run_id: str | None = None


class SkillScore(ApiModel):
    """Champion versus the best non-registry baseline.

    Positive `improvement_pct` means the champion is better. `None` where either
    WAPE is undefined - never 0, which would read as "no difference".
    """

    improvement_pct: float | None = None
    champion_better: bool | None = None
    reason: str | None = None


class ChampionSelectionOut(ApiModel):
    id: str
    training_run_id: str
    scope_kind: str
    scope_key: str
    evaluated_scope_level: str | None = None

    champion_model_id: str
    champion_display_name: str
    challenger_model_id: str | None = None
    legacy_champion_model_id: str | None = None

    champion_wape: float | None = None
    champion_mae: float | None = None
    champion_bias: float | None = None
    champion_validation_points: int = 0
    champion_evaluation_mode: str | None = None

    best_baseline_model_id: str | None = None
    best_baseline_wape: float | None = None
    beaten_by_baseline: bool = False

    selection_source: str
    reason: str | None = None
    actor: str | None = None
    is_active: bool
    superseded_at: datetime | None = None
    supersedes_id: str | None = None
    restored_from_id: str | None = None

    ranked_count: int = 0
    excluded_count: int = 0
    notes: list[Any] | None = Field(default=None, validation_alias="notes_json")
    created_at: datetime


class LeaderboardResponse(ApiModel):
    training_run_id: str
    panel_build_id: str | None = None
    scope_level: str
    scope_key: str

    rows: list[LeaderboardRow]
    champion_model_id: str | None = None
    challenger_model_id: str | None = None
    legacy_champion_model_id: str | None = None
    best_baseline_model_id: str | None = None
    best_baseline_wape: float | None = None
    beaten_by_baseline: bool = False
    skill_vs_best_baseline: SkillScore

    ranked_count: int = 0
    excluded_count: int = 0
    #: Registry models with no row in this scope. Non-empty means a defect.
    models_missing: list[str] = Field(default_factory=list)
    baselines_present: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    #: The window composition behind these metrics, so the sales-proxy caveat
    #: (D-040) travels with the numbers.
    origins: dict[str, Any] | None = None
    active_selection: ChampionSelectionOut | None = None
    #: "as_selected" when these rows are the board the champion was chosen on,
    #: "recomputed" when they are a fresh sort of the stored metrics with no
    #: selection behind them. The two can name different winners, and which one
    #: a reader is looking at is not something to leave them guessing at.
    ranking_source: str = "recomputed"
    ranking_note: str | None = None


class ComparisonPoint(ApiModel):
    """One bar of the models-on-x, WAPE-on-y chart."""

    model_id: str
    display_name: str
    wape: float | None = None
    #: WAPE is already a percentage at source; this is the same number, named
    #: for the axis it is drawn on.
    wape_pct: float | None = None
    status: str
    is_baseline: bool
    is_champion: bool
    exclusion: str | None = None
    exclusion_reason: str | None = None


class ScopeRef(ApiModel):
    scope_level: str
    scope_key: str


class FoldOut(ApiModel):
    origin_name: str | None = None
    fold_index: int | None = None
    train_end_period: str | None = None
    train_rows: int | None = None
    status: str | None = None
    seasonal_period: int | None = None
    failure_reason: str | None = None
    eligibility: dict[str, Any] | None = None
    fit_seconds: float | None = None
    predict_seconds: float | None = None
    validation_periods: list[str] = Field(default_factory=list)
    metrics: dict[str, Any] | None = None
    legacy_metrics: dict[str, Any] | None = None
    negative_predictions: int | None = None
    point_count: int = 0


class DiagnosticPoint(ApiModel):
    origin_name: str | None = None
    fold_index: int | None = None
    period: str | None = None
    horizon: int | None = None
    actual: float
    predicted: float
    residual: float


class HorizonPerformance(ApiModel):
    horizon: int | None = None
    points: int
    mae: float | None = None
    wape: float | None = None
    bias: float | None = None
    zero_actual_points: int = 0


class DiagnosticsResponse(ApiModel):
    training_run_id: str
    model_id: str
    display_name: str
    is_baseline: bool
    scope_level: str
    scope_key: str
    status: str
    evaluation_mode: str | None = None
    failure_reason: str | None = None
    eligibility: dict[str, Any] | None = None
    metrics: dict[str, Any]
    parameters: dict[str, Any] | None = None
    features: list[Any] | None = None
    fit_seconds: float | None = None
    predict_seconds: float | None = None
    folds: list[FoldOut] = Field(default_factory=list)
    points: list[DiagnosticPoint] = Field(default_factory=list)
    horizon_performance: list[HorizonPerformance] = Field(default_factory=list)
    diagnostics_available: bool
    unavailable_reason: str | None = None


class SelectChampionsRequest(ApiModel):
    training_run_id: str | None = None
    scope_kinds: list[str] = Field(
        default_factory=lambda: [
            "overall",
            "region",
            "branch",
            "value_class",
            "product_group",
        ]
    )
    actor: str | None = None

    @field_validator("scope_kinds")
    @classmethod
    def _known_kinds(cls, value: list[str]) -> list[str]:
        unknown = [kind for kind in value if kind not in SCOPE_KINDS]
        if unknown:
            raise ValueError(
                f"Unknown scope kind(s) {unknown}. Valid kinds: {list(SCOPE_KINDS)}."
            )
        return value


class SkippedScope(ApiModel):
    scope_kind: str
    scope_key: str
    reason: str
    excluded_count: int = 0


class DemotedChampion(ApiModel):
    """A model that won its backtest and could not be fitted on the full history.

    Every field is here so the demotion can be read without re-running
    anything: which model was refused, how it had scored, what took the crown
    instead, and the adapter's own words for the requirement it missed.
    """

    scope_kind: str
    scope_key: str
    refused_model_id: str
    refused_wape: float | None = None
    champion_model_id: str
    reason: str


class UncheckedScope(ApiModel):
    scope_kind: str
    scope_key: str
    reason: str


class SelectChampionsResponse(ApiModel):
    training_run_id: str
    selected: list[ChampionSelectionOut]
    #: Scopes where no registered model was rankable. Reported, never given an
    #: arbitrary champion.
    skipped: list[SkippedScope]
    selected_count: int
    skipped_count: int
    #: Whether each candidate was also checked against the scope's full
    #: history, not only its backtest window.
    deployability_checked: bool = False
    #: Why that check could not run, when it could not. Never silent.
    deployability_note: str | None = None
    demoted: list[DemotedChampion] = Field(default_factory=list)
    demoted_count: int = 0
    unchecked_scopes: list[UncheckedScope] = Field(default_factory=list)


class OverrideRequest(ApiModel):
    scope_kind: str = "overall"
    scope_key: str = "NATIONAL"
    model_id: str
    reason: str = Field(
        min_length=MIN_OVERRIDE_REASON_CHARS,
        description=(
            "Why the automatic champion is being replaced. Recorded in the "
            "audit history and required."
        ),
    )
    actor: str | None = None
    training_run_id: str | None = None

    @field_validator("scope_kind")
    @classmethod
    def _known_kind(cls, value: str) -> str:
        if value not in SCOPE_KINDS:
            raise ValueError(
                f"Unknown scope kind {value!r}. Valid kinds: {list(SCOPE_KINDS)}."
            )
        return value


class RollbackRequest(ApiModel):
    scope_kind: str = "overall"
    scope_key: str = "NATIONAL"
    reason: str | None = None
    actor: str | None = None

    @field_validator("scope_kind")
    @classmethod
    def _known_kind(cls, value: str) -> str:
        if value not in SCOPE_KINDS:
            raise ValueError(
                f"Unknown scope kind {value!r}. Valid kinds: {list(SCOPE_KINDS)}."
            )
        return value


class ChampionHistoryResponse(ApiModel):
    scope_kind: str
    scope_key: str
    entries: list[ChampionSelectionOut]
    total: int

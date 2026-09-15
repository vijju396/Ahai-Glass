"""Training run records.

Three tables, and the shape of them is load-bearing:

**`TrainingRun`** — one row per submitted run. Never overwritten; a re-run is a
new row, so a forecast's lineage back through panel, mapping and dataset stays
resolvable.

**`ModelRun`** — one row per (scope, model) the run *asked about*, not per model
that succeeded. A model that was ineligible, failed, timed out or was never
reached still gets a row carrying its status and reason. That is what makes
"a model never disappears from the leaderboard" a property of the schema rather
than a convention the query layer has to remember.

**`QuantileCalibration`** — one row per (model, horizon, segment) cell, with the
offsets, the residual count, the method and the pooling level that produced it.
Persisted rather than recomputed because a forecast served in Phase 9 must be
able to say which population its interval came from, months after the run.

Metrics are stored as nullable floats, never as sentinels. A `NULL` WAPE means
the metric was undefined for that window - which on this dataset is the common
case, not an error - and a query that wants "models with a defined WAPE" says
so explicitly instead of filtering out a magic number.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UuidPkMixin


class TrainingRun(Base, UuidPkMixin, TimestampMixin):
    """One submitted training run over one panel build."""

    __tablename__ = "training_run"

    panel_build_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("panel_build.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    status: Mapped[str] = mapped_column(String(30), default="queued", nullable=False)
    stage_detail: Mapped[str | None] = mapped_column(String(300))
    progress_pct: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    failure_reason: Mapped[str | None] = mapped_column(Text)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    #: Which tiers were requested, comma-separated in execution order.
    tiers: Mapped[str] = mapped_column(String(120), nullable=False)
    min_history_profile: Mapped[str] = mapped_column(String(30), nullable=False)
    xgboost_training_profile: Mapped[str] = mapped_column(String(20), nullable=False)
    max_local_series: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    local_series_selection: Mapped[str | None] = mapped_column(String(20))

    #: What the run was restricted to, and what that restriction actually
    #: matched: requested branches, unknown ones, SKU cap, and the resulting
    #: branch/SKU/series counts. Null on an unrestricted run. Kept so a
    #: leaderboard built from a two-branch run can never be read as a network
    #: result.
    restriction_json: Mapped[dict | None] = mapped_column(JSON)

    #: The cost shown to the user before the run was allowed to start, and what
    #: it actually cost. Kept side by side so the estimate can be audited
    #: against reality rather than quietly forgotten.
    estimated_seconds: Mapped[float | None] = mapped_column(Float)
    estimate_json: Mapped[dict | None] = mapped_column(JSON)

    #: Budget as configured for this run.
    total_budget_seconds: Mapped[float | None] = mapped_column(Float)
    per_model_timeout_seconds: Mapped[float | None] = mapped_column(Float)
    lstm_timeout_seconds: Mapped[float | None] = mapped_column(Float)

    series_requested: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    series_evaluated: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    model_runs_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    model_runs_completed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    model_runs_ineligible: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    model_runs_failed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    model_runs_timed_out: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    model_runs_not_evaluated: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )

    residuals_recorded: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    mlflow_run_id: Mapped[str | None] = mapped_column(String(64))
    artifact_dir: Mapped[str | None] = mapped_column(String(600))

    #: Window composition (order vs sales_proxy, censored counts) per origin,
    #: so a leaderboard built from this run carries the D-040 caveat with it.
    origins_json: Mapped[dict | None] = mapped_column(JSON)
    summary_json: Mapped[dict | None] = mapped_column(JSON)
    warnings_json: Mapped[list | None] = mapped_column(JSON)

    panel_build: Mapped["PanelBuild"] = relationship(  # noqa: F821
        back_populates="training_runs"
    )
    model_runs: Mapped[list["ModelRun"]] = relationship(
        back_populates="training_run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    calibrations: Mapped[list["QuantileCalibration"]] = relationship(
        back_populates="training_run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    champion_selections: Mapped[list["ChampionSelection"]] = relationship(  # noqa: F821
        back_populates="training_run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class ModelRun(Base, UuidPkMixin, TimestampMixin):
    """One (scope, model) evaluation. Present whatever the outcome."""

    __tablename__ = "model_run"
    __table_args__ = (
        UniqueConstraint(
            "training_run_id",
            "tier",
            "scope_level",
            "scope_key",
            "model_id",
            name="uq_model_run_scope",
        ),
        Index("ix_model_run_leaderboard", "training_run_id", "scope_level", "wape"),
        Index("ix_model_run_model", "training_run_id", "model_id", "status"),
    )

    training_run_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("training_run.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    tier: Mapped[str] = mapped_column(String(30), nullable=False)
    #: `national` | `region` | `branch` | `series`. A branch-level row and a
    #: series-level row are not comparable, so the level is part of the key.
    scope_level: Mapped[str] = mapped_column(String(20), nullable=False)
    scope_key: Mapped[str] = mapped_column(String(300), nullable=False)
    segment: Mapped[str | None] = mapped_column(String(20))

    model_id: Mapped[str] = mapped_column(String(40), nullable=False)
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    #: True for `naive`/`seasonal_naive`/`ma3`/`ma6`. A baseline is reported
    #: beside the leaderboard and can never be champion, so the flag lives on
    #: the row rather than being re-derived from the id every time.
    is_baseline: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    status: Mapped[str] = mapped_column(String(30), nullable=False)
    evaluation_mode: Mapped[str | None] = mapped_column(String(30))
    failure_reason: Mapped[str | None] = mapped_column(Text)
    eligibility_json: Mapped[dict | None] = mapped_column(JSON)

    seasonal_period: Mapped[int | None] = mapped_column(Integer)
    origins_completed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    origins_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    validation_points: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_test_points: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duplicate_test_points: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )

    # The AIS metric set. Nullable because undefined is a real value here.
    mae: Mapped[float | None] = mapped_column(Float)
    rmse: Mapped[float | None] = mapped_column(Float)
    wape: Mapped[float | None] = mapped_column(Float)
    mape: Mapped[float | None] = mapped_column(Float)
    accuracy: Mapped[float | None] = mapped_column(Float)
    smape: Mapped[float | None] = mapped_column(Float)
    mase: Mapped[float | None] = mapped_column(Float)
    bias: Mapped[float | None] = mapped_column(Float)
    bias_abs: Mapped[float | None] = mapped_column(Float)
    naive_mae: Mapped[float | None] = mapped_column(Float)

    #: The reference projects' own six values, computed by the parity port.
    #: Stored separately so the legacy ranking is never confused with the AIS
    #: one (docs/DECISIONS.md D-011).
    legacy_mape: Mapped[float | None] = mapped_column(Float)
    legacy_wape: Mapped[float | None] = mapped_column(Float)
    legacy_mae: Mapped[float | None] = mapped_column(Float)
    legacy_valid: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    zero_actual_points: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    censored_points: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    negative_predictions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_abs_prediction: Mapped[float | None] = mapped_column(Float)

    fit_seconds: Mapped[float | None] = mapped_column(Float)
    predict_seconds: Mapped[float | None] = mapped_column(Float)

    artifact_path: Mapped[str | None] = mapped_column(String(600))
    mlflow_run_id: Mapped[str | None] = mapped_column(String(64))
    parameters_json: Mapped[dict | None] = mapped_column(JSON)
    features_json: Mapped[list | None] = mapped_column(JSON)
    origins_json: Mapped[list | None] = mapped_column(JSON)

    training_run: Mapped["TrainingRun"] = relationship(back_populates="model_runs")


class QuantileCalibration(Base, UuidPkMixin, TimestampMixin):
    """One (model, horizon, segment) calibration cell.

    Persisted so a forecast can state, later, how its interval was produced -
    which pooling level, how many residuals, conformal or interpolated. An
    interval whose provenance cannot be recovered is not much better than one
    that was made up.
    """

    __tablename__ = "quantile_calibration"
    __table_args__ = (
        UniqueConstraint(
            "training_run_id",
            "model_id",
            "horizon",
            "segment",
            name="uq_quantile_cell",
        ),
    )

    training_run_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("training_run.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    model_id: Mapped[str] = mapped_column(String(40), nullable=False)
    horizon: Mapped[int] = mapped_column(Integer, nullable=False)
    segment: Mapped[str] = mapped_column(String(20), nullable=False)

    residual_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    #: `{"q80": {"offset": ..., "method": ..., "residual_count": ...,
    #:   "pooling_level": ..., "note": ...}, ...}`
    offsets_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    #: The coarsest pooling level any level in this cell had to fall back to.
    pooling_level: Mapped[str | None] = mapped_column(String(30))
    method: Mapped[str | None] = mapped_column(String(20))

    training_run: Mapped["TrainingRun"] = relationship(back_populates="calibrations")

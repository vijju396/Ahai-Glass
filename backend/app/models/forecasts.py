"""Generated forecasts, and the lineage that makes them auditable.

**`ForecastRun`** — one row per generation. Holds which champion selection and
training run it drew on, the reconciliation method that actually ran, the
coherence verdict and the quantile-crossing count. A re-generation is a new
row, never an overwrite.

**`ForecastRow`** — one row per (scope, period, horizon). Carries the point
forecast, q80/q90/q95, the base (pre-reconciliation) value, the reconciliation
adjustment, and the provenance of the interval: which pooling level and method
the calibration came from. So a planner asking "why is q95 this number" gets an
answer from the row rather than from a re-derivation that may no longer match.

Two data-honesty properties are schema-level here:

- `target_source` and `is_censored` travel on every row, because a forecast
  trained through a sales-proxy window is not the same claim as one trained on
  ordered quantity (`docs/DECISIONS.md` D-040).
- `unavailable_reason` exists so a scope with no forecast is a row that says why,
  not a row of zeros. A zero forecast and "we could not forecast this" are
  different facts.
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

#: The levels a forecast row can be written at.
FORECAST_LEVELS: tuple[str, ...] = ("series", "branch", "region", "national")


class ForecastRun(Base, UuidPkMixin, TimestampMixin):
    """One forecast generation over one training run."""

    __tablename__ = "forecast_run"

    training_run_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("training_run.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
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

    #: The last period of actuals, and the first period forecast. Stored rather
    #: than inferred, so a forecast's origin survives a later panel rebuild.
    origin_period: Mapped[str] = mapped_column(String(7), nullable=False)
    horizons: Mapped[str] = mapped_column(String(40), default="1,2,3,4,5,6", nullable=False)

    #: What was requested, and what actually ran - they differ whenever a
    #: covariance could not be estimated.
    requested_reconciliation: Mapped[str | None] = mapped_column(String(30))
    reconciliation_method: Mapped[str | None] = mapped_column(String(30))
    reconciliation_fallback_from: Mapped[str | None] = mapped_column(String(30))
    reconciliation_fallback_reason: Mapped[str | None] = mapped_column(Text)
    shrinkage_intensity: Mapped[float | None] = mapped_column(Float)

    coherent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    max_incoherence: Mapped[float | None] = mapped_column(Float)
    negatives_clipped: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    quantile_crossings_corrected: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )

    series_forecast: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rows_written: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rows_unavailable: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    summary_json: Mapped[dict | None] = mapped_column(JSON)
    warnings_json: Mapped[list | None] = mapped_column(JSON)

    rows: Mapped[list["ForecastRow"]] = relationship(
        back_populates="forecast_run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class ForecastRow(Base, UuidPkMixin, TimestampMixin):
    """One forecast for one scope, period and horizon."""

    __tablename__ = "forecast_row"
    __table_args__ = (
        UniqueConstraint(
            "forecast_run_id",
            "scope_level",
            "scope_key",
            "period",
            name="uq_forecast_scope_period",
        ),
        Index("ix_forecast_lookup", "forecast_run_id", "scope_level", "scope_key"),
        Index("ix_forecast_period", "forecast_run_id", "period"),
    )

    forecast_run_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("forecast_run.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    scope_level: Mapped[str] = mapped_column(String(20), nullable=False)
    scope_key: Mapped[str] = mapped_column(String(300), nullable=False)
    #: Denormalised so Forecast Explorer can filter without joining the panel.
    canonical_branch: Mapped[str | None] = mapped_column(String(120))
    canonical_sku: Mapped[str | None] = mapped_column(String(120))
    region: Mapped[str | None] = mapped_column(String(120))
    demand_segment: Mapped[str | None] = mapped_column(String(20))
    value_class: Mapped[str | None] = mapped_column(String(20))

    period: Mapped[str] = mapped_column(String(7), nullable=False)
    horizon: Mapped[int] = mapped_column(Integer, nullable=False)

    #: Which model produced it, and under which champion decision.
    model_id: Mapped[str | None] = mapped_column(String(40))
    model_display_name: Mapped[str | None] = mapped_column(String(80))
    model_run_id: Mapped[str | None] = mapped_column(String(32))
    champion_selection_id: Mapped[str | None] = mapped_column(String(32))
    #: `champion`, `segment_champion`, `pooled_fallback`, `baseline_fallback`.
    #: A fallback is never presented as the champion's own forecast.
    forecast_source: Mapped[str | None] = mapped_column(String(30))

    point_forecast: Mapped[float | None] = mapped_column(Float)
    q80: Mapped[float | None] = mapped_column(Float)
    q90: Mapped[float | None] = mapped_column(Float)
    q95: Mapped[float | None] = mapped_column(Float)

    #: Pre-reconciliation value and the adjustment, so the change is visible
    #: rather than folded into the number.
    base_forecast: Mapped[float | None] = mapped_column(Float)
    reconciliation_adjustment: Mapped[float | None] = mapped_column(Float)
    reconciliation_method: Mapped[str | None] = mapped_column(String(30))

    #: Where the interval came from. An interval whose provenance cannot be
    #: recovered is barely better than one that was made up.
    quantile_method: Mapped[str | None] = mapped_column(String(20))
    quantile_pooling_level: Mapped[str | None] = mapped_column(String(30))
    quantile_residual_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )

    #: The training window's composition, carried onto the forecast it produced.
    target_source: Mapped[str | None] = mapped_column(String(20))
    is_censored: Mapped[bool | None] = mapped_column(Boolean)

    #: Set when no forecast could be produced. A row with this set has a null
    #: point forecast, never a zero.
    unavailable_reason: Mapped[str | None] = mapped_column(Text)

    drivers_json: Mapped[dict | None] = mapped_column(JSON)

    forecast_run: Mapped["ForecastRun"] = relationship(back_populates="rows")

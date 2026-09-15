"""Panel build records.

One row per attempt to build the modelling panel from a preprocessing run.
Never overwritten: a rebuild is a new row, so a training run's panel lineage
stays resolvable.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UuidPkMixin


class PanelBuild(Base, UuidPkMixin, TimestampMixin):
    __tablename__ = "panel_build"

    preprocessing_run_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("preprocessing_run.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    status: Mapped[str] = mapped_column(String(30), default="pending", nullable=False)
    stage_detail: Mapped[str | None] = mapped_column(String(300))
    progress_pct: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    failure_reason: Mapped[str | None] = mapped_column(Text)

    #: The training cut. Origins after it are excluded, and so is any row whose
    #: target period falls after it.
    training_cut_period: Mapped[str | None] = mapped_column(String(7))
    horizons: Mapped[str] = mapped_column(String(40), default="1,2,3,4,5,6", nullable=False)

    panel_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    series_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    period_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    observed_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    materialised_zero_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    censored_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    training_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    scoring_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    feature_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    manifest_path: Mapped[str | None] = mapped_column(String(600))
    artifacts_json: Mapped[dict | None] = mapped_column(JSON)
    summary_json: Mapped[dict | None] = mapped_column(JSON)

    preprocessing_run: Mapped["PreprocessingRun"] = relationship(  # noqa: F821
        back_populates="panel_builds"
    )
    training_runs: Mapped[list["TrainingRun"]] = relationship(  # noqa: F821
        back_populates="panel_build",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

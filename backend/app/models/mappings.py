"""Mapping versions, role assignments, validation results, and the
preprocessed dimension tables.

A confirmed mapping is immutable: re-mapping the same dataset version produces
a new mapping version and marks the previous one superseded. Nothing overwrites
a mapping a training run may already have used.
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


class MappingVersion(Base, UuidPkMixin, TimestampMixin):
    __tablename__ = "mapping_version"
    __table_args__ = (
        UniqueConstraint(
            "dataset_version_id", "version_number", name="uq_mapping_version_number"
        ),
    )

    dataset_version_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("dataset_version.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)

    # Mapping-level configuration (app.ml.features.roles.MappingConfig)
    frequency: Mapped[str] = mapped_column(String(20), default="monthly", nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata", nullable=False)
    forecast_horizon: Mapped[int] = mapped_column(Integer, default=6, nullable=False)
    aggregation_method: Mapped[str] = mapped_column(String(20), default="sum", nullable=False)
    duplicate_handling: Mapped[str] = mapped_column(String(20), default="aggregate", nullable=False)
    missing_timestamp_policy: Mapped[str] = mapped_column(
        String(20), default="explicit_zero", nullable=False
    )
    target_imputation_policy: Mapped[str] = mapped_column(
        String(20), default="leave_missing", nullable=False
    )
    driver_imputation_policy: Mapped[str] = mapped_column(
        String(20), default="leave_missing", nullable=False
    )

    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_by: Mapped[str | None] = mapped_column(String(120))
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    superseded_by_id: Mapped[str | None] = mapped_column(String(32))
    notes: Mapped[str | None] = mapped_column(Text)

    assignments: Mapped[list[ColumnRoleAssignment]] = relationship(
        back_populates="mapping", cascade="all, delete-orphan",
        order_by="ColumnRoleAssignment.ordinal",
    )
    rule_results: Mapped[list[MappingRuleResult]] = relationship(
        back_populates="mapping", cascade="all, delete-orphan"
    )
    preprocessing_runs: Mapped[list[PreprocessingRun]] = relationship(
        back_populates="mapping", cascade="all, delete-orphan"
    )

    @property
    def is_confirmed(self) -> bool:
        return self.state == "confirmed"


class ColumnRoleAssignment(Base, UuidPkMixin):
    __tablename__ = "column_role_assignment"
    __table_args__ = (
        UniqueConstraint(
            "mapping_id", "source_role", "column_name", name="uq_role_per_column"
        ),
        Index("ix_role_assignment_role", "mapping_id", "role"),
    )

    mapping_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("mapping_version.id", ondelete="CASCADE"), nullable=False
    )
    source_role: Mapped[str] = mapped_column(String(40), nullable=False)
    column_name: Mapped[str] = mapped_column(String(300), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    role: Mapped[str] = mapped_column(String(40), nullable=False)

    #: True until a person has reviewed it. A mapping cannot be confirmed while
    #: any required role is still only a suggestion.
    is_suggested: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float)
    rationale: Mapped[str | None] = mapped_column(Text)
    aggregation: Mapped[str | None] = mapped_column(String(20))
    imputation: Mapped[str | None] = mapped_column(String(20))
    notes: Mapped[str | None] = mapped_column(Text)

    mapping: Mapped[MappingVersion] = relationship(back_populates="assignments")


class MappingRuleResult(Base, UuidPkMixin):
    """One validation rule outcome (app.ml.features.roles.validate_mapping)."""

    __tablename__ = "mapping_rule_result"

    mapping_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("mapping_version.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    rule_code: Mapped[str] = mapped_column(String(20), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    columns_json: Mapped[list | None] = mapped_column(JSON)
    remediation: Mapped[str | None] = mapped_column(Text)

    mapping: Mapped[MappingVersion] = relationship(back_populates="rule_results")


class PreprocessingRun(Base, UuidPkMixin, TimestampMixin):
    """One preprocessing pass over a confirmed mapping.

    Produces the branch and product dimension tables plus a normalised monthly
    fact table, written as Parquet with a versioned manifest. Phase 4 builds
    the modelling panel on top of these.
    """

    __tablename__ = "preprocessing_run"

    mapping_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("mapping_version.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    status: Mapped[str] = mapped_column(String(30), default="pending", nullable=False)
    stage_detail: Mapped[str | None] = mapped_column(String(300))
    progress_pct: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    failure_reason: Mapped[str | None] = mapped_column(Text)

    # Row counts of what was produced
    branch_dim_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    product_dim_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    fact_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    order_fact_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sales_fact_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    stock_position_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    distinct_series: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    distinct_periods: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    manifest_path: Mapped[str | None] = mapped_column(String(600))
    artifacts_json: Mapped[dict | None] = mapped_column(JSON)
    summary_json: Mapped[dict | None] = mapped_column(JSON)

    mapping: Mapped[MappingVersion] = relationship(back_populates="preprocessing_runs")
    panel_builds: Mapped[list["PanelBuild"]] = relationship(  # noqa: F821
        back_populates="preprocessing_run", cascade="all, delete-orphan"
    )

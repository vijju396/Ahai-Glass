"""Dataset, ingestion and validation records.

Portable SQLAlchemy types only - no SQLite-specific affinity, no AUTOINCREMENT,
no rowid dependence - so the same models run unchanged on PostgreSQL
(docs/DECISIONS.md D-006).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

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


class IngestionStatus(StrEnum):
    PENDING = "pending"
    READING = "reading"
    CLEANING = "cleaning"
    VALIDATING = "validating"
    COMPLETED = "completed"
    COMPLETED_WITH_FAILURES = "completed_with_failures"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ControlOutcome(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"
    NOT_EVALUATED = "not_evaluated"


class DefectSeverity(StrEnum):
    BLOCKING = "blocking"
    CORRECTED = "corrected"
    RECORDED = "recorded"


class Dataset(Base, UuidPkMixin, TimestampMixin):
    """A logical collection of source files ingested together."""

    __tablename__ = "dataset"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    source_label: Mapped[str] = mapped_column(String(200), nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    versions: Mapped[list[DatasetVersion]] = relationship(
        back_populates="dataset", cascade="all, delete-orphan", order_by="DatasetVersion.version_number"
    )


class DatasetVersion(Base, UuidPkMixin, TimestampMixin):
    """One ingestion attempt. Never overwritten - a re-ingest is a new version."""

    __tablename__ = "dataset_version"
    __table_args__ = (
        UniqueConstraint("dataset_id", "version_number", name="uq_dataset_version_number"),
    )

    dataset_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("dataset.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default=IngestionStatus.PENDING, nullable=False)
    stage_detail: Mapped[str | None] = mapped_column(String(300))
    progress_pct: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_seconds: Mapped[float | None] = mapped_column(Float)

    # Outcome summary
    controls_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    controls_failed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    defects_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failure_reason: Mapped[str | None] = mapped_column(Text)

    # Where the cleaned artefacts landed
    manifest_path: Mapped[str | None] = mapped_column(String(600))

    dataset: Mapped[Dataset] = relationship(back_populates="versions")
    source_files: Mapped[list[SourceFile]] = relationship(
        back_populates="version", cascade="all, delete-orphan"
    )
    controls: Mapped[list[ValidationControl]] = relationship(
        back_populates="version", cascade="all, delete-orphan"
    )
    defects: Mapped[list[DefectRecord]] = relationship(
        back_populates="version", cascade="all, delete-orphan"
    )
    reconciliations: Mapped[list[KeyReconciliation]] = relationship(
        back_populates="version", cascade="all, delete-orphan"
    )


class SourceFile(Base, UuidPkMixin, TimestampMixin):
    """One physical source file as read. The originals are never modified."""

    __tablename__ = "source_file"

    version_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("dataset_version.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(40), nullable=False)
    filename: Mapped[str] = mapped_column(String(400), nullable=False)
    sheet_name: Mapped[str | None] = mapped_column(String(200))
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    column_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    read_seconds: Mapped[float | None] = mapped_column(Float)
    columns_json: Mapped[list | None] = mapped_column(JSON)

    version: Mapped[DatasetVersion] = relationship(back_populates="source_files")
    column_profiles: Mapped[list[ColumnProfile]] = relationship(
        back_populates="source_file", cascade="all, delete-orphan"
    )


class ColumnProfile(Base, UuidPkMixin):
    """Per-column profiling. `is_pii` columns are profiled by name only - their
    values are never read into the profile or any payload (rule C13)."""

    __tablename__ = "column_profile"
    __table_args__ = (Index("ix_column_profile_file_col", "source_file_id", "column_name"),)

    source_file_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("source_file.id", ondelete="CASCADE"), nullable=False
    )
    column_name: Mapped[str] = mapped_column(String(300), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    detected_type: Mapped[str] = mapped_column(String(40), nullable=False)
    non_null_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    null_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    distinct_count: Mapped[int | None] = mapped_column(Integer)
    is_constant: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_pii: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    min_value: Mapped[str | None] = mapped_column(String(200))
    max_value: Mapped[str | None] = mapped_column(String(200))
    mean_value: Mapped[float | None] = mapped_column(Float)
    sample_values_json: Mapped[list | None] = mapped_column(JSON)
    note: Mapped[str | None] = mapped_column(Text)

    source_file: Mapped[SourceFile] = relationship(back_populates="column_profiles")


class ValidationControl(Base, UuidPkMixin):
    """One structural control from docs/VALIDATION_REPORT.md section 1.

    A FAIL is recorded and surfaced, never swallowed: ingestion marks the
    version COMPLETED_WITH_FAILURES so nothing downstream can treat the data as
    clean by default.
    """

    __tablename__ = "validation_control"
    __table_args__ = (
        UniqueConstraint("version_id", "control_code", name="uq_control_per_version"),
    )

    version_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("dataset_version.id", ondelete="CASCADE"), nullable=False, index=True
    )
    control_code: Mapped[str] = mapped_column(String(20), nullable=False)
    description: Mapped[str] = mapped_column(String(400), nullable=False)
    expected: Mapped[str | None] = mapped_column(String(200))
    measured: Mapped[str | None] = mapped_column(String(200))
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    difference: Mapped[str | None] = mapped_column(String(200))
    tolerance_pct: Mapped[float | None] = mapped_column(Float)
    remediation: Mapped[str | None] = mapped_column(Text)

    version: Mapped[DatasetVersion] = relationship(back_populates="controls")


class DefectRecord(Base, UuidPkMixin):
    """A catalogued data defect and the rule that handled it (D1-D14)."""

    __tablename__ = "defect_record"

    version_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("dataset_version.id", ondelete="CASCADE"), nullable=False, index=True
    )
    defect_code: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    extent: Mapped[str | None] = mapped_column(String(200))
    affected_rows: Mapped[int | None] = mapped_column(Integer)
    source_role: Mapped[str | None] = mapped_column(String(40))
    rule_applied: Mapped[str | None] = mapped_column(String(20))
    fix_description: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_json: Mapped[dict | None] = mapped_column(JSON)

    version: Mapped[DatasetVersion] = relationship(back_populates="defects")


class KeyReconciliation(Base, UuidPkMixin):
    """Canonical Product Code reconciled against Oracle No (rule C9).

    Rows are the reconciliation findings themselves: missing Oracle numbers,
    disagreements, duplicate mappings and collisions.
    """

    __tablename__ = "key_reconciliation"

    version_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("dataset_version.id", ondelete="CASCADE"), nullable=False, index=True
    )
    finding_type: Mapped[str] = mapped_column(String(40), nullable=False)
    key_value: Mapped[str] = mapped_column(String(200), nullable=False)
    related_values_json: Mapped[list | None] = mapped_column(JSON)
    occurrence_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)

    version: Mapped[DatasetVersion] = relationship(back_populates="reconciliations")

"""Dataset, profile and validation payloads.

No field here can carry a PII value: `ColumnProfileOut` exposes `is_pii` plus
counts, and its value-bearing fields are null for a PII column by construction
in the ingestion accumulator (rule C13).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from app.schemas.common import ApiModel


class DatasetCreateRequest(ApiModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)


class DatasetVersionSummary(ApiModel):
    id: str
    version_number: int
    status: str
    stage_detail: str | None
    progress_pct: float
    started_at: datetime | None
    finished_at: datetime | None
    duration_seconds: float | None
    controls_total: int
    controls_failed: int
    defects_total: int
    failure_reason: str | None


class DatasetOut(ApiModel):
    id: str
    name: str
    description: str | None
    source_label: str
    created_at: datetime
    latest_version: DatasetVersionSummary | None = None


class DatasetCreateResponse(ApiModel):
    dataset: DatasetOut
    version_id: str
    message: str


class ColumnProfileOut(ApiModel):
    column_name: str
    ordinal: int
    detected_type: str
    non_null_count: int
    null_count: int
    distinct_count: int | None
    is_constant: bool
    is_pii: bool
    min_value: str | None
    max_value: str | None
    mean_value: float | None
    sample_values: list[str] | None = Field(default=None, validation_alias="sample_values_json")
    note: str | None


class SourceFileOut(ApiModel):
    role: str
    filename: str
    sheet_name: str | None
    size_bytes: int
    content_hash_sha256: str
    row_count: int
    column_count: int
    read_seconds: float | None
    columns: list[str] | None = Field(default=None, validation_alias="columns_json")


class SourceFileProfileOut(SourceFileOut):
    column_profiles: list[ColumnProfileOut] = Field(default_factory=list)


class DatasetProfileResponse(ApiModel):
    version: DatasetVersionSummary
    source_files: list[SourceFileProfileOut]
    pii_columns_excluded: list[str]
    total_rows_read: int


class ValidationControlOut(ApiModel):
    control_code: str
    description: str
    expected: str | None
    measured: str | None
    outcome: str
    difference: str | None
    tolerance_pct: float | None
    remediation: str | None


class DefectRecordOut(ApiModel):
    defect_code: str
    title: str
    severity: str
    extent: str | None
    affected_rows: int | None
    source_role: str | None
    rule_applied: str | None
    fix_description: str
    evidence: dict[str, Any] | None = Field(default=None, validation_alias="evidence_json")


class ServiceMeasuresOut(ApiModel):
    """Net and gross shortfall are separate fields, deliberately. They differ
    because some lines despatched more than was ordered."""

    total_ordered: int
    total_despatched: int
    net_shortfall: int
    gross_positive_shortfall: int
    over_delivered_qty: int
    net_fill_rate: float | None
    gross_shortfall_pct: float | None
    lines_total: int
    lines_fully_unserved: int
    lines_with_shortfall: int
    lines_over_delivered: int


class LeadTimeOut(ApiModel):
    count: int
    median_days: float | None
    p95_days: float | None
    max_days: int | None
    unparseable_dates: int
    negative_excluded: int


class ValidationResponse(ApiModel):
    version: DatasetVersionSummary
    passed: bool
    controls: list[ValidationControlOut]
    defects: list[DefectRecordOut]
    service_measures: ServiceMeasuresOut | None
    lead_time: LeadTimeOut | None
    summary: dict[str, Any]
    blocking_message: str | None = None


class ReconciliationFindingOut(ApiModel):
    finding_type: str
    key_value: str
    related_values: list[str] | None = Field(default=None, validation_alias="related_values_json")
    occurrence_count: int
    note: str | None


class MappingResponse(ApiModel):
    """Canonical Product Code reconciled against Oracle No (rule C9)."""

    version: DatasetVersionSummary
    canonical_sku_count: int
    oracle_no_count: int
    oracle_collision_count: int
    canonical_disagreement_count: int
    rows_missing_oracle: int
    sku_prefixes: dict[str, int]
    branch_universes: dict[str, int]
    sku_universes: dict[str, int]
    findings: list[ReconciliationFindingOut]
    findings_total: int
    canonical_key_rule: str
    why_not_oracle_no: str

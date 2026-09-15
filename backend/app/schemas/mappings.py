"""Role-mapping payloads."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from app.ml.features.roles import (
    AggregationMethod,
    DuplicateHandling,
    ImputationPolicy,
    MissingTimestampPolicy,
    SemanticRole,
)
from app.schemas.common import ApiModel


class RoleAssignmentOut(ApiModel):
    source_role: str
    column_name: str
    ordinal: int
    role: SemanticRole
    #: True while the role is still only a suggestion. A target or time column
    #: that is still suggested blocks confirmation.
    is_suggested: bool
    confidence: float | None
    rationale: str | None
    aggregation: str | None
    imputation: str | None
    notes: str | None


class RoleAssignmentUpdate(ApiModel):
    source_role: str
    column_name: str
    role: SemanticRole
    rationale: str | None = Field(default=None, max_length=1000)
    aggregation: AggregationMethod | None = None
    imputation: ImputationPolicy | None = None


class MappingConfigUpdate(ApiModel):
    frequency: str | None = None
    timezone: str | None = None
    forecast_horizon: int | None = Field(default=None, ge=1, le=24)
    aggregation_method: AggregationMethod | None = None
    duplicate_handling: DuplicateHandling | None = None
    missing_timestamp_policy: MissingTimestampPolicy | None = None
    target_imputation_policy: ImputationPolicy | None = None
    driver_imputation_policy: ImputationPolicy | None = None


class RuleResultOut(ApiModel):
    rule_code: str
    severity: str
    message: str
    columns: list[str] | None = Field(default=None, validation_alias="columns_json")
    remediation: str | None


class PreprocessingRunOut(ApiModel):
    id: str
    status: str
    stage_detail: str | None
    progress_pct: float
    started_at: datetime | None
    finished_at: datetime | None
    duration_seconds: float | None
    failure_reason: str | None
    branch_dim_rows: int
    product_dim_rows: int
    order_fact_rows: int
    sales_fact_rows: int
    fact_rows: int
    stock_position_rows: int
    distinct_series: int
    distinct_periods: int
    artifacts: dict[str, str] | None = Field(default=None, validation_alias="artifacts_json")
    summary: dict[str, Any] | None = Field(default=None, validation_alias="summary_json")


class MappingSummary(ApiModel):
    id: str
    dataset_version_id: str
    version_number: int
    state: str
    frequency: str
    timezone: str
    forecast_horizon: int
    aggregation_method: str
    duplicate_handling: str
    missing_timestamp_policy: str
    target_imputation_policy: str
    driver_imputation_policy: str
    confirmed_at: datetime | None
    confirmed_by: str | None
    superseded_at: datetime | None
    notes: str | None
    created_at: datetime


class MappingDetail(MappingSummary):
    assignments: list[RoleAssignmentOut] = Field(default_factory=list)
    rule_results: list[RuleResultOut] = Field(default_factory=list)
    role_counts: dict[str, int] = Field(default_factory=dict)
    unreviewed_count: int = 0
    blocking_count: int = 0
    warning_count: int = 0
    can_confirm: bool = False
    future_known_columns: list[str] = Field(default_factory=list)
    not_future_known_reasons: dict[str, str] = Field(default_factory=dict)


class MappingCreateRequest(ApiModel):
    notes: str | None = Field(default=None, max_length=2000)


class MappingUpdateRequest(ApiModel):
    assignments: list[RoleAssignmentUpdate] = Field(default_factory=list)
    config: MappingConfigUpdate | None = None


class MappingConfirmRequest(ApiModel):
    confirmed_by: str = Field(min_length=2, max_length=120)


class SuggestionOut(ApiModel):
    source_role: str
    column_name: str
    role: str
    confidence: float
    rationale: str
    #: Always false. Suggestions are advisory and must survive human review.
    is_authoritative: bool = False


class SuggestionsResponse(ApiModel):
    suggestions: list[SuggestionOut]
    total: int
    note: str

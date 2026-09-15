"""Shared response envelopes and enums.

`ModelRunStatus` is the vocabulary the leaderboard renders. The distinction
between INELIGIBLE, FAILED, TIMED_OUT and NOT_EVALUATED_BUDGET is load-bearing:
a model that did not run must say which of those it was, and must never be
replaced by a zero forecast.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class Page(ApiModel, Generic[T]):
    items: list[T]
    total: int
    offset: int
    limit: int


class ModelRunStatus(StrEnum):
    QUEUED = "queued"
    PREPARING_DATA = "preparing_data"
    VALIDATING_ELIGIBILITY = "validating_eligibility"
    TRAINING = "training"
    CROSS_VALIDATING = "cross_validating"
    GENERATING_FORECAST = "generating_forecast"
    SAVING_ARTIFACTS = "saving_artifacts"
    COMPLETED = "completed"
    FAILED = "failed"
    INELIGIBLE = "ineligible"
    TIMED_OUT = "timed_out"
    NOT_EVALUATED_BUDGET = "not_evaluated_budget"
    CANCELLED = "cancelled"


TERMINAL_STATUSES: frozenset[ModelRunStatus] = frozenset(
    {
        ModelRunStatus.COMPLETED,
        ModelRunStatus.FAILED,
        ModelRunStatus.INELIGIBLE,
        ModelRunStatus.TIMED_OUT,
        ModelRunStatus.NOT_EVALUATED_BUDGET,
        ModelRunStatus.CANCELLED,
    }
)


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    FAILED = "failed"
    CANCELLED = "cancelled"


class EvaluationMode(StrEnum):
    ROLLING_ORIGIN = "rolling_origin"
    HOLDOUT_FALLBACK = "holdout_fallback"
    HOLDOUT_FAST = "holdout_fast"


class TargetSource(StrEnum):
    """Ordered quantity is the primary target. `SALES_PROXY` is a labelled
    substitute used only where order history does not exist. The two are never
    described as equivalent."""

    ORDER = "order"
    SALES_PROXY = "sales_proxy"


class ValueUnavailableReason(StrEnum):
    """Why a value is absent. `TRUE_ZERO` is a real observation, not a gap -
    conflating the two is the single most damaging mistake available on this
    dataset (62% of series are intermittent)."""

    TRUE_ZERO = "true_zero"
    MISSING_DATA = "missing_data"
    ZERO_STOCK = "zero_stock"
    NOT_APPLICABLE = "not_applicable"
    MODEL_INELIGIBLE = "model_ineligible"
    MODEL_FAILED = "model_failed"
    OUT_OF_BUDGET = "out_of_budget"


class HealthComponent(ApiModel):
    name: str
    status: str
    detail: str | None = None


class HealthResponse(ApiModel):
    status: str = Field(description="ok | degraded | error")
    app_name: str
    version: str
    environment: str
    components: list[HealthComponent]

"""Panel build payloads."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from app.schemas.common import ApiModel

PERIOD_PATTERN = r"^\d{4}-\d{2}$"


class PanelBuildRequest(ApiModel):
    preprocessing_run_id: str | None = None
    #: The training cut, as YYYY-MM. Origins after it are excluded, and so is
    #: any row whose target period falls after it.
    training_cut_period: str | None = Field(default=None, pattern=PERIOD_PATTERN)
    horizons: list[int] = Field(default_factory=lambda: [1, 2, 3, 4, 5, 6])


class PanelBuildOut(ApiModel):
    id: str
    preprocessing_run_id: str
    status: str
    stage_detail: str | None
    progress_pct: float
    started_at: datetime | None
    finished_at: datetime | None
    duration_seconds: float | None
    failure_reason: str | None
    training_cut_period: str | None
    horizons: str
    panel_rows: int
    series_count: int
    period_count: int
    observed_rows: int
    materialised_zero_rows: int
    censored_rows: int
    training_rows: int
    scoring_rows: int
    feature_count: int
    artifacts: dict[str, str] | None = Field(
        default=None, validation_alias="artifacts_json"
    )
    summary: dict[str, Any] | None = Field(default=None, validation_alias="summary_json")

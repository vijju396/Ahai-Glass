"""Panel build payloads."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from app.schemas.common import ApiModel
from app.core.config import get_settings
from app.ml.features.feature_builder import horizons_for

PERIOD_PATTERN = r"^\d{4}-\d{2}$"


class PanelBuildRequest(ApiModel):
    preprocessing_run_id: str | None = None
    #: The training cut, as YYYY-MM. Origins after it are excluded, and so is
    #: any row whose target period falls after it.
    training_cut_period: str | None = Field(default=None, pattern=PERIOD_PATTERN)
    #: Defaults to every horizon the configured grain covers - 1..6 monthly,
    #: 1..26 weekly - so a request that names none still plans six months.
    horizons: list[int] = Field(
        default_factory=lambda: list(horizons_for(get_settings().panel_grain))
    )


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

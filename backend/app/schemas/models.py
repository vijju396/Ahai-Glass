"""The model-contract payloads the frontend consumes.

`GET /api/models` is the only place the React app learns model IDs and labels.
The frontend never carries a second registry, and a test asserts it
(`frontend/src/features/leaderboard/__tests__`). This mirrors the
no-drift property verified in both reference projects.
"""

from __future__ import annotations

from app.schemas.common import ApiModel


class ModelDescriptor(ApiModel):
    model_id: str
    display_name: str
    rank: int
    dependency_module: str
    requires_exogenous: bool
    supports_pooled_training: bool
    uses_fast_holdout: bool
    min_required_history: int
    min_history_reason: str | None = None
    family: str


class BaselineDescriptor(ApiModel):
    """Non-registry comparison baselines. Never part of the official 13."""

    method_id: str
    display_name: str


class ModelRegistryResponse(ApiModel):
    models: list[ModelDescriptor]
    baselines: list[BaselineDescriptor]
    official_model_count: int
    min_history_profile: str
    xgboost_training_profile: str
    notes: list[str]

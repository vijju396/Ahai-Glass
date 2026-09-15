"""Builds the model contract served to the frontend.

Identity comes from `app.ml.registry.canonical_models` and every enforced
threshold from the bound adapter itself, so the API cannot advertise a
requirement the model does not check. The reference citations behind those
thresholds are in docs/MODEL_INVENTORY.md SS2.
"""

from __future__ import annotations

from app.core.config import get_settings
from app.ml.adapters.base import ModelContext
from app.ml.registry.canonical_models import (
    BASELINE_DISPLAY_NAMES,
    BASELINE_METHOD_IDS,
    CANONICAL_MODEL_IDS,
    EXOGENOUS_MODEL_IDS,
    FAST_HOLDOUT_MODEL_IDS,
    MODEL_DEPENDENCY_MODULES,
    MODEL_DISPLAY_NAMES,
    POOLED_CAPABLE_MODEL_IDS,
    REQUIRED_MODEL_COUNT,
)
from app.schemas.models import (
    BaselineDescriptor,
    ModelDescriptor,
    ModelRegistryResponse,
)

_MIN_HISTORY_REASON: dict[str, str] = {
    "sarimax": "12 rows (Sodexo models.py:92, Meriton training_service.py:1037).",
    "sarimax_exog": "12 rows, plus at least one independently varying exogenous column.",
    "auto_arima": (
        "24 rows (Sodexo models.py:118, Meriton training_service.py:1063). "
        "AIS's monthly panel offers at most 22 before a 6-month holdout, so this "
        "model is Ineligible under the 'reference' profile."
    ),
    "auto_arima_exog": (
        "24 rows, plus a usable exogenous matrix. Same 22-row ceiling as auto_arima."
    ),
    "xgboost": "At least 5 lagged training rows (both references).",
    "xgboost_exog": "At least 5 lagged rows; exogenous features appended raw.",
    "exp_additive": (
        "24 rows AND two complete seasonal cycles inside the smallest CV fold "
        "(Sodexo models.py:222-227). At period 12 that needs 24 training rows; "
        "AIS's ceiling is 22."
    ),
    "exp_additive_damped": "As exp_additive.",
    "exp_multiplicative": (
        "As exp_additive, and every target value must be strictly positive - "
        "which 62% of AIS series violate."
    ),
    "exp_multiplicative_damped": "As exp_multiplicative.",
    "var": (
        "10 rows and at least two non-constant aligned endogenous series "
        "(Meriton _prepare_var_endog:1964-1977). AIS pairs ordered with "
        "despatched quantity."
    ),
    "var_exog": "As var, plus at least one varying exogenous column.",
    "lstm": (
        "More rows than the sequence window plus 2 (both references); the window "
        "is auto-sized from available history."
    ),
}

_FAMILY: dict[str, str] = {
    "sarimax": "state_space",
    "sarimax_exog": "state_space",
    "auto_arima": "state_space",
    "auto_arima_exog": "state_space",
    "xgboost": "gradient_boosting",
    "xgboost_exog": "gradient_boosting",
    "exp_additive": "exponential_smoothing",
    "exp_additive_damped": "exponential_smoothing",
    "exp_multiplicative": "exponential_smoothing",
    "exp_multiplicative_damped": "exponential_smoothing",
    "var": "vector_autoregression",
    "var_exog": "vector_autoregression",
    "lstm": "neural_network",
}

_NOTES: tuple[str, ...] = (
    "q80/q90/q95 are forecast outputs calibrated from out-of-sample residuals, "
    "not additional models. They never appear on the leaderboard as models.",
    "Naive, seasonal-naive, MA3 and MA6 are non-registry baselines. They are "
    "reported for comparison and used as the MASE denominator, but are never "
    "counted among the official 13 and can never be champion.",
    "Under the 'reference' history profile, auto_arima, auto_arima_exog and the "
    "four exponential-smoothing variants are Ineligible at AIS's monthly grain: "
    "they need 24 training rows and the panel offers at most 22 before a "
    "6-month holdout. Switch to 'monthly_relaxed' to compare all 13.",
)


def build_model_contract() -> ModelRegistryResponse:
    """Built from the bound adapters, so the API cannot drift from them.

    Minimum-history values come from each adapter's own threshold table rather
    than a second copy here - that duplication is exactly how an API ends up
    advertising a requirement the model does not enforce.
    """
    from app.ml.registry.model_registry import MODEL_REGISTRY

    settings = get_settings()
    profile = settings.min_history_profile
    models = [
        ModelDescriptor(
            model_id=model_id,
            display_name=MODEL_DISPLAY_NAMES[model_id],
            rank=index,
            dependency_module=MODEL_DEPENDENCY_MODULES[model_id],
            requires_exogenous=model_id in EXOGENOUS_MODEL_IDS,
            supports_pooled_training=model_id in POOLED_CAPABLE_MODEL_IDS,
            uses_fast_holdout=model_id in FAST_HOLDOUT_MODEL_IDS,
            min_required_history=MODEL_REGISTRY[model_id](
                ModelContext(min_history_profile=profile)
            ).min_required_history(),
            min_history_reason=_MIN_HISTORY_REASON[model_id],
            family=_FAMILY[model_id],
        )
        for index, model_id in enumerate(CANONICAL_MODEL_IDS, start=1)
    ]
    baselines = [
        BaselineDescriptor(
            method_id=method_id, display_name=BASELINE_DISPLAY_NAMES[method_id]
        )
        for method_id in BASELINE_METHOD_IDS
    ]
    return ModelRegistryResponse(
        models=models,
        baselines=baselines,
        official_model_count=REQUIRED_MODEL_COUNT,
        min_history_profile=profile,
        xgboost_training_profile=settings.xgboost_training_profile,
        notes=list(_NOTES),
    )


def min_required_history(model_id: str, profile: str | None = None) -> int:
    """Delegates to the adapter that enforces it.

    A second table here would be free to drift from what the model actually
    checks, which is how an API ends up advertising a requirement nothing
    enforces.
    """
    from app.ml.registry.model_registry import MODEL_REGISTRY

    resolved = profile or get_settings().min_history_profile
    return MODEL_REGISTRY[model_id](
        ModelContext(min_history_profile=resolved)
    ).min_required_history()

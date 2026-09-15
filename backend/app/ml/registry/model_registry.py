"""The central model registry: the 13 canonical IDs bound to real adapters.

`canonical_models.py` owns the IDs and display names and is deliberately
dependency-light. This module is the one place those IDs are bound to
importable implementations, and it re-asserts agreement **at import time** -
so a drift in count, order, or naming stops the process rather than serving a
quietly wrong leaderboard.

The same guarantee Meriton's own `test_exact_model_manifest_parity`
(`tests/test_meriton_features.py:13-20`) enforces, plus the display-name check
that Meriton's manifest-vs-registry identity test does not cover.
"""

from __future__ import annotations

from app.ml.adapters.auto_arima_adapter import AutoArimaAdapter, AutoArimaExogAdapter
from app.ml.adapters.base import ForecastModelAdapter, ModelContext
from app.ml.adapters.exp_smoothing_adapter import (
    ExpAdditiveAdapter,
    ExpAdditiveDampedAdapter,
    ExpMultiplicativeAdapter,
    ExpMultiplicativeDampedAdapter,
)
from app.ml.adapters.lstm_adapter import LstmAdapter
from app.ml.adapters.sarimax_adapter import SarimaxAdapter, SarimaxExogAdapter
from app.ml.adapters.var_adapter import VarAdapter, VarExogAdapter
from app.ml.adapters.xgboost_adapter import XGBoostAdapter, XGBoostExogAdapter
from app.ml.registry.canonical_models import (
    CANONICAL_MODEL_IDS,
    EXOGENOUS_MODEL_IDS,
    FAST_HOLDOUT_MODEL_IDS,
    MODEL_DEPENDENCY_MODULES,
    MODEL_DISPLAY_NAMES,
    POOLED_CAPABLE_MODEL_IDS,
    REQUIRED_MODEL_COUNT,
)

#: Insertion order IS the display order. Do not reorder.
MODEL_REGISTRY: dict[str, type[ForecastModelAdapter]] = {
    "sarimax": SarimaxAdapter,
    "sarimax_exog": SarimaxExogAdapter,
    "auto_arima": AutoArimaAdapter,
    "auto_arima_exog": AutoArimaExogAdapter,
    "xgboost": XGBoostAdapter,
    "xgboost_exog": XGBoostExogAdapter,
    "exp_additive": ExpAdditiveAdapter,
    "exp_additive_damped": ExpAdditiveDampedAdapter,
    "exp_multiplicative": ExpMultiplicativeAdapter,
    "exp_multiplicative_damped": ExpMultiplicativeDampedAdapter,
    "var": VarAdapter,
    "var_exog": VarExogAdapter,
    "lstm": LstmAdapter,
}


def assert_registry_bound() -> None:
    """Fail loudly if the bound adapters have drifted from the canonical list."""
    if tuple(MODEL_REGISTRY) != CANONICAL_MODEL_IDS:
        raise AssertionError(
            "MODEL_REGISTRY must contain exactly the canonical model ids, in "
            f"order. Got {tuple(MODEL_REGISTRY)!r}."
        )
    if len(MODEL_REGISTRY) != REQUIRED_MODEL_COUNT:
        raise AssertionError(
            f"The registry must hold exactly {REQUIRED_MODEL_COUNT} models."
        )
    for model_id, adapter in MODEL_REGISTRY.items():
        if adapter.model_id != model_id:
            raise AssertionError(
                f"{adapter.__name__}.model_id is {adapter.model_id!r} but is "
                f"registered under {model_id!r}."
            )
        if adapter.display_name != MODEL_DISPLAY_NAMES[model_id]:
            raise AssertionError(
                f"{adapter.__name__}.display_name is {adapter.display_name!r}, "
                f"expected {MODEL_DISPLAY_NAMES[model_id]!r}. Display names are "
                "preserved verbatim from the reference projects."
            )
        if adapter.dependency_module != MODEL_DEPENDENCY_MODULES[model_id]:
            raise AssertionError(
                f"{adapter.__name__}.dependency_module is "
                f"{adapter.dependency_module!r}, expected "
                f"{MODEL_DEPENDENCY_MODULES[model_id]!r}."
            )
        if adapter.requires_exogenous != (model_id in EXOGENOUS_MODEL_IDS):
            raise AssertionError(
                f"{adapter.__name__}.requires_exogenous disagrees with "
                "EXOGENOUS_MODEL_IDS."
            )
        if adapter.uses_fast_holdout != (model_id in FAST_HOLDOUT_MODEL_IDS):
            raise AssertionError(
                f"{adapter.__name__}.uses_fast_holdout disagrees with "
                "FAST_HOLDOUT_MODEL_IDS."
            )
        if adapter.supports_pooled_training != (model_id in POOLED_CAPABLE_MODEL_IDS):
            raise AssertionError(
                f"{adapter.__name__}.supports_pooled_training disagrees with "
                "POOLED_CAPABLE_MODEL_IDS."
            )


assert_registry_bound()


def get_adapter_class(model_id: str) -> type[ForecastModelAdapter]:
    try:
        return MODEL_REGISTRY[model_id]
    except KeyError as exc:
        raise KeyError(
            f"Unknown model_id {model_id!r}. Valid ids: {list(MODEL_REGISTRY)}"
        ) from exc


def create_adapter(
    model_id: str, context: ModelContext | None = None
) -> ForecastModelAdapter:
    return get_adapter_class(model_id)(context)


def ordered_adapter_classes() -> list[type[ForecastModelAdapter]]:
    """The 13 classes in display order - what a leaderboard loop iterates."""
    return [MODEL_REGISTRY[model_id] for model_id in CANONICAL_MODEL_IDS]


def create_all_adapters(
    context: ModelContext | None = None,
) -> list[ForecastModelAdapter]:
    """One instance of every model, in display order.

    A training run creates all 13 and records a terminal status for each, so
    none can silently vanish from the leaderboard.
    """
    return [adapter(context) for adapter in ordered_adapter_classes()]

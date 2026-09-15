"""The single source of truth for the official 13-model registry.

This module is deliberately dependency-light: it imports nothing from the ML
stack, so API schemas, the frontend contract endpoint, and tests can all assert
against the same IDs without pulling statsmodels/xgboost/tensorflow into the
process. `app.ml.registry.model_registry` binds these IDs to real adapter
classes and re-asserts agreement with this list at import time.

The IDs, display names, and their order are verified against the actual source
of both reference projects (not their documentation):

- Meriton  `D:\\Meriton forecast\\services\\training_service.py:27-40` MODEL_SPECS
- Sodexo   `D:\\Labour_AI forecast\\backend_sodexo\\app\\services\\forecasting\\contract.py:96-110` MODEL_SPECS
- Sodexo   `...\\forecasting\\models.py:333-347` FITTERS

Both reference projects carry the same 13 models with identical display names.
Meriton suffixes its IDs with `_Predictions`; Sodexo uses the clean snake_case
form reproduced here. See docs/MODEL_INVENTORY.md and docs/DECISIONS.md-001.

Nothing may be added to or removed from these tuples. Naive, seasonal-naive,
MA3 and MA6 exist separately as non-registry baselines
(`BASELINE_METHOD_IDS`) and are never counted among the 13.
"""

from __future__ import annotations

from types import MappingProxyType

REQUIRED_MODEL_COUNT = 13

#: The official 13 model IDs, in the approved display order.
CANONICAL_MODEL_IDS: tuple[str, ...] = (
    "sarimax",
    "sarimax_exog",
    "auto_arima",
    "auto_arima_exog",
    "xgboost",
    "xgboost_exog",
    "exp_additive",
    "exp_additive_damped",
    "exp_multiplicative",
    "exp_multiplicative_damped",
    "var",
    "var_exog",
    "lstm",
)

#: User-visible names, preserved verbatim from both reference projects.
MODEL_DISPLAY_NAMES: MappingProxyType[str, str] = MappingProxyType(
    {
        "sarimax": "SARIMAX",
        "sarimax_exog": "SARIMAX with exogenous variables",
        "auto_arima": "Auto ARIMA",
        "auto_arima_exog": "Auto ARIMA with exogenous variables",
        "xgboost": "XGBoost",
        "xgboost_exog": "XGBoost with exogenous variables",
        "exp_additive": "Exponential Smoothing Additive",
        "exp_additive_damped": "Exponential Smoothing Additive Damped",
        "exp_multiplicative": "Exponential Smoothing Multiplicative",
        "exp_multiplicative_damped": "Exponential Smoothing Multiplicative Damped",
        "var": "VAR",
        "var_exog": "VAR with exogenous variables",
        "lstm": "LSTM",
    }
)

#: Third-party module each model needs, for dependency-availability checks.
#: Mirrors Sodexo's `MODEL_SPECS` third tuple element and its
#: `eligibility.dependency_available` gate.
MODEL_DEPENDENCY_MODULES: MappingProxyType[str, str] = MappingProxyType(
    {
        "sarimax": "statsmodels",
        "sarimax_exog": "statsmodels",
        "auto_arima": "pmdarima",
        "auto_arima_exog": "pmdarima",
        "xgboost": "xgboost",
        "xgboost_exog": "xgboost",
        "exp_additive": "statsmodels",
        "exp_additive_damped": "statsmodels",
        "exp_multiplicative": "statsmodels",
        "exp_multiplicative_damped": "statsmodels",
        "var": "statsmodels",
        "var_exog": "statsmodels",
        "lstm": "tensorflow",
    }
)

#: Models that consume an exogenous design matrix.
EXOGENOUS_MODEL_IDS: frozenset[str] = frozenset(
    {"sarimax_exog", "auto_arima_exog", "xgboost_exog", "var_exog"}
)

#: Expensive models evaluated by a single chronological holdout instead of
#: rolling-origin CV, sized to the same total test rows the folds would use.
#: Ported from Sodexo's `FAST_HOLDOUT_MODEL_IDS` (docs/DECISIONS.md-003).
FAST_HOLDOUT_MODEL_IDS: frozenset[str] = frozenset(
    {"auto_arima", "auto_arima_exog", "lstm"}
)

#: Models trainable in pooled/global mode over the whole branch x SKU panel.
#: Everything else is a per-series local fit. See docs/DECISIONS.md-034.
POOLED_CAPABLE_MODEL_IDS: frozenset[str] = frozenset({"xgboost", "xgboost_exog"})

#: Non-registry comparison baselines. Reported alongside the leaderboard and
#: used as the MASE denominator, but NEVER counted among the official 13 and
#: never eligible to be champion.
BASELINE_METHOD_IDS: tuple[str, ...] = ("naive", "seasonal_naive", "ma3", "ma6")

BASELINE_DISPLAY_NAMES: MappingProxyType[str, str] = MappingProxyType(
    {
        "naive": "Naive (last value)",
        "seasonal_naive": "Seasonal naive",
        "ma3": "Moving average (3)",
        "ma6": "Moving average (6)",
    }
)


def assert_canonical_registry() -> None:
    """Fail loudly if the canonical registry has drifted.

    Called at application startup (`app.main`) and asserted independently by
    `tests/test_model_registry.py`, so a drift is caught by both a running
    server and CI.
    """
    if len(CANONICAL_MODEL_IDS) != REQUIRED_MODEL_COUNT:
        raise AssertionError(
            f"The official registry must contain exactly {REQUIRED_MODEL_COUNT} "
            f"models, found {len(CANONICAL_MODEL_IDS)}."
        )
    if len(set(CANONICAL_MODEL_IDS)) != REQUIRED_MODEL_COUNT:
        raise AssertionError("CANONICAL_MODEL_IDS contains a duplicate model_id.")
    # Checked before the coverage/count assertions below: a baseline quietly
    # promoted into the 13 is the most damaging drift available here, so it must
    # be reported as itself rather than as a downstream count mismatch.
    overlap = set(CANONICAL_MODEL_IDS) & set(BASELINE_METHOD_IDS)
    if overlap:
        raise AssertionError(
            f"Baselines must never be part of the official 13: {sorted(overlap)}."
        )
    missing_names = [m for m in CANONICAL_MODEL_IDS if m not in MODEL_DISPLAY_NAMES]
    if missing_names:
        raise AssertionError(f"Models without a display name: {missing_names}.")
    if len(MODEL_DISPLAY_NAMES) != REQUIRED_MODEL_COUNT:
        raise AssertionError(
            "MODEL_DISPLAY_NAMES must describe exactly the canonical models."
        )
    missing_deps = [
        m for m in CANONICAL_MODEL_IDS if m not in MODEL_DEPENDENCY_MODULES
    ]
    if missing_deps:
        raise AssertionError(f"Models without a dependency module: {missing_deps}.")
    unknown_flagged = (
        (EXOGENOUS_MODEL_IDS | FAST_HOLDOUT_MODEL_IDS | POOLED_CAPABLE_MODEL_IDS)
        - set(CANONICAL_MODEL_IDS)
    )
    if unknown_flagged:
        raise AssertionError(
            f"Capability sets reference unknown model ids: {sorted(unknown_flagged)}."
        )


assert_canonical_registry()

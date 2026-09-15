"""The registry is a contract, so it gets a hard test.

`EXPECTED` below is written out literally rather than imported from the code
under test. Importing it would make the test tautological: it would pass even
if a model were renamed or reordered in the source. This list is transcribed
from the build specification and cross-checked against
`D:\\Meriton forecast\\services\\training_service.py:27-40` and
`D:\\Labour_AI forecast\\backend_sodexo\\app\\services\\forecasting\\contract.py:96-110`.
"""

from __future__ import annotations

import pytest

from app.ml.registry import canonical_models as cm

#: (model_id, display_name), in required order. Do not import this.
EXPECTED: tuple[tuple[str, str], ...] = (
    ("sarimax", "SARIMAX"),
    ("sarimax_exog", "SARIMAX with exogenous variables"),
    ("auto_arima", "Auto ARIMA"),
    ("auto_arima_exog", "Auto ARIMA with exogenous variables"),
    ("xgboost", "XGBoost"),
    ("xgboost_exog", "XGBoost with exogenous variables"),
    ("exp_additive", "Exponential Smoothing Additive"),
    ("exp_additive_damped", "Exponential Smoothing Additive Damped"),
    ("exp_multiplicative", "Exponential Smoothing Multiplicative"),
    ("exp_multiplicative_damped", "Exponential Smoothing Multiplicative Damped"),
    ("var", "VAR"),
    ("var_exog", "VAR with exogenous variables"),
    ("lstm", "LSTM"),
)

FORBIDDEN_SUBSTITUTES = (
    "prophet", "random_forest", "randomforest", "lightgbm", "lgbm",
    "croston", "sba", "tsb", "moving_average", "theta", "ets_auto",
)


def test_registry_contains_exactly_thirteen_models() -> None:
    assert len(cm.CANONICAL_MODEL_IDS) == 13
    assert cm.REQUIRED_MODEL_COUNT == 13


def test_registry_ids_match_specification_in_exact_order() -> None:
    assert cm.CANONICAL_MODEL_IDS == tuple(model_id for model_id, _ in EXPECTED)


def test_display_names_match_reference_projects_verbatim() -> None:
    for model_id, display_name in EXPECTED:
        assert cm.MODEL_DISPLAY_NAMES[model_id] == display_name


def test_no_duplicate_model_ids() -> None:
    assert len(set(cm.CANONICAL_MODEL_IDS)) == len(cm.CANONICAL_MODEL_IDS)


def test_every_model_declares_a_dependency_module() -> None:
    for model_id in cm.CANONICAL_MODEL_IDS:
        assert cm.MODEL_DEPENDENCY_MODULES[model_id] in {
            "statsmodels", "pmdarima", "xgboost", "tensorflow"
        }


def test_no_forbidden_algorithm_is_registered() -> None:
    """Prophet, Random Forest, LightGBM, Croston, SBA and TSB must never be
    substituted for one of the 13, however plausible they look for
    intermittent demand."""
    joined = " ".join(cm.CANONICAL_MODEL_IDS).lower()
    for forbidden in FORBIDDEN_SUBSTITUTES:
        assert forbidden not in joined, f"{forbidden} must not be in the registry"


def test_baselines_are_not_part_of_the_official_thirteen() -> None:
    assert not set(cm.BASELINE_METHOD_IDS) & set(cm.CANONICAL_MODEL_IDS)
    assert cm.BASELINE_METHOD_IDS == ("naive", "seasonal_naive", "ma3", "ma6")
    for method_id in cm.BASELINE_METHOD_IDS:
        assert method_id in cm.BASELINE_DISPLAY_NAMES


def test_capability_sets_only_reference_known_models() -> None:
    known = set(cm.CANONICAL_MODEL_IDS)
    assert cm.EXOGENOUS_MODEL_IDS <= known
    assert cm.FAST_HOLDOUT_MODEL_IDS <= known
    assert cm.POOLED_CAPABLE_MODEL_IDS <= known


def test_exogenous_models_are_exactly_the_four_exog_variants() -> None:
    assert cm.EXOGENOUS_MODEL_IDS == {
        "sarimax_exog", "auto_arima_exog", "xgboost_exog", "var_exog"
    }


def test_fast_holdout_policy_matches_sodexo() -> None:
    """Sodexo forces a single chronological holdout for its three expensive
    models. Verified at
    D:\\Labour_AI forecast\\backend_sodexo\\app\\services\\forecasting\\contract.py
    FAST_HOLDOUT_MODEL_IDS."""
    assert cm.FAST_HOLDOUT_MODEL_IDS == {"auto_arima", "auto_arima_exog", "lstm"}


def test_lstm_has_no_exogenous_sibling() -> None:
    """LSTM is the only one of the 13 without an `_exog` variant in either
    reference project. Inventing one would make it 14 models."""
    assert "lstm_exog" not in cm.CANONICAL_MODEL_IDS
    assert "lstm" not in cm.EXOGENOUS_MODEL_IDS


def test_startup_assertion_passes() -> None:
    cm.assert_canonical_registry()


def test_startup_assertion_rejects_a_missing_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cm, "CANONICAL_MODEL_IDS", cm.CANONICAL_MODEL_IDS[:12])
    with pytest.raises(AssertionError, match="exactly 13"):
        cm.assert_canonical_registry()


def test_startup_assertion_rejects_a_duplicate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cm, "CANONICAL_MODEL_IDS", cm.CANONICAL_MODEL_IDS[:12] + ("sarimax",)
    )
    with pytest.raises(AssertionError, match="duplicate"):
        cm.assert_canonical_registry()


def test_startup_assertion_rejects_a_fourteenth_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cm, "CANONICAL_MODEL_IDS", cm.CANONICAL_MODEL_IDS + ("prophet",)
    )
    with pytest.raises(AssertionError, match="exactly 13"):
        cm.assert_canonical_registry()


def test_startup_assertion_rejects_baseline_promotion(monkeypatch: pytest.MonkeyPatch) -> None:
    """A baseline must never be quietly counted as one of the 13."""
    monkeypatch.setattr(
        cm, "CANONICAL_MODEL_IDS", cm.CANONICAL_MODEL_IDS[:12] + ("naive",)
    )
    monkeypatch.setattr(
        cm,
        "MODEL_DISPLAY_NAMES",
        {**dict(cm.MODEL_DISPLAY_NAMES), "naive": "Naive (last value)"},
    )
    monkeypatch.setattr(
        cm,
        "MODEL_DEPENDENCY_MODULES",
        {**dict(cm.MODEL_DEPENDENCY_MODULES), "naive": "statsmodels"},
    )
    with pytest.raises(AssertionError, match="never be part of the official 13"):
        cm.assert_canonical_registry()

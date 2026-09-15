"""The common `ForecastModelAdapter` contract for all 13 models.

Every model is reached through this interface, so the training orchestrator,
the leaderboard and the forecast service never branch on model identity.

Three properties are load-bearing and are enforced here rather than left to
each adapter:

**Ineligible is not Failed.** `validate_eligibility` returns a verdict; it
never raises. A model whose validated data requirement is unmet reports
`Ineligible` with the exact requirement and its remediation, and stays on the
leaderboard. A model whose fit raises reports `Failed` with the reason. The two
render differently and mean different things.

**One model's failure never stops the others.** Adapters raise; the
orchestrator catches per model. Both reference projects do the same
(Meriton `training_service.py:441-451`, Sodexo `engine.py:106-123`).

**Prediction intervals are never model-native.** Neither reference uses a
model's analytic CI. Both compute empirical percentiles of backtest residuals,
and AIS keeps that uniformly across all 13 rather than per model
(docs/MODEL_INVENTORY.md SS1, SS3).
"""

from __future__ import annotations

import random
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


class ModelNotFittedError(RuntimeError):
    """Raised when `predict` is called before `fit`."""


class ModelTimeoutError(RuntimeError):
    """Raised when a fit exceeds its per-model budget."""


class EligibilityCode(StrEnum):
    ELIGIBLE = "eligible"
    DEPENDENCY_MISSING = "dependency_missing"
    INSUFFICIENT_HISTORY = "insufficient_history"
    INSUFFICIENT_SEASONAL_CYCLES = "insufficient_seasonal_cycles"
    NON_POSITIVE_TARGET = "non_positive_target"
    CONSTANT_TARGET = "constant_target"
    NO_VARYING_EXOGENOUS = "no_varying_exogenous"
    INSUFFICIENT_ENDOGENOUS = "insufficient_endogenous"
    NO_VALID_TARGET = "no_valid_target"


@dataclass
class Eligibility:
    """A verdict, never an exception.

    `remediation` says what would make the model eligible, so a leaderboard row
    explains itself without anyone reading the model code.
    """

    eligible: bool
    code: EligibilityCode = EligibilityCode.ELIGIBLE
    reason: str | None = None
    remediation: str | None = None
    required_history: int | None = None
    observed_history: int | None = None

    @classmethod
    def ok(cls) -> Eligibility:
        return cls(eligible=True)

    def as_dict(self) -> dict[str, Any]:
        return {
            "eligible": self.eligible,
            "code": self.code.value,
            "reason": self.reason,
            "remediation": self.remediation,
            "required_history": self.required_history,
            "observed_history": self.observed_history,
        }


@dataclass
class ModelContext:
    """Everything an adapter needs that is not the data itself.

    Mirrors Sodexo's `ModelContext` (seasonal period + exogenous columns) and
    extends it with the settings AIS needs: the history profile that decides
    eligibility thresholds, the XGBoost training profile, and the recursion
    policy below.
    """

    seasonal_period: int | None = None
    exog_columns: tuple[str, ...] = ()
    horizons: tuple[int, ...] = (1, 2, 3, 4, 5, 6)
    random_seed: int = 42
    min_history_profile: str = "reference"
    xgboost_training_profile: str = "thorough"
    timeout_seconds: float | None = None
    #: Second endogenous series for VAR (docs/DECISIONS.md D-004).
    var_pair_column: str = "despatched_qty"

    #: Whether a recursive model may consume actual values from the output
    #: window as it walks forward.
    #:
    #: BOTH reference projects do this (Meriton `training_service.py:1130`,
    #: `:1257`; Sodexo `models.py:211`, `:327`): `history.append(row["target"]
    #: if notna else prediction)`. On a validation fold the actuals ARE
    #: present, so every step becomes effectively one-step-ahead and the fold
    #: flatters the model relative to a genuine six-month plan.
    #:
    #: AIS defaults to False - a forecast six months out cannot see months two
    #: through five. True reproduces the reference exactly and exists for the
    #: parity tests (docs/DECISIONS.md D-031).
    allow_actuals_in_recursion: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "seasonal_period": self.seasonal_period,
            "exog_columns": list(self.exog_columns),
            "horizons": list(self.horizons),
            "random_seed": self.random_seed,
            "min_history_profile": self.min_history_profile,
            "xgboost_training_profile": self.xgboost_training_profile,
            "var_pair_column": self.var_pair_column,
            "allow_actuals_in_recursion": self.allow_actuals_in_recursion,
        }


@dataclass
class AdapterDiagnostics:
    """What the adapter actually did, for the leaderboard and diagnostics."""

    model_id: str
    display_name: str
    fitted: bool = False
    failure_reason: str | None = None
    training_duration_ms: float | None = None
    inference_duration_ms: float | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    features: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    training_rows: int | None = None
    exogenous_columns_used: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "display_name": self.display_name,
            "fitted": self.fitted,
            "failure_reason": self.failure_reason,
            "training_duration_ms": self.training_duration_ms,
            "inference_duration_ms": self.inference_duration_ms,
            "parameters": self.parameters,
            "features": self.features,
            "warnings": self.warnings,
            "training_rows": self.training_rows,
            "exogenous_columns_used": self.exogenous_columns_used,
        }


def seed_everything(seed: int) -> None:
    """Deterministic seeding, best-effort per library.

    TensorFlow is seeded inside the LSTM adapter, because importing it here
    would cost every adapter several seconds.
    """
    random.seed(seed)
    np.random.seed(seed)


def dependency_available(module_name: str | None) -> tuple[bool, str | None]:
    """Mirrors Sodexo's `eligibility.dependency_available`."""
    import importlib.util

    if module_name is None:
        return True, None
    if importlib.util.find_spec(module_name) is not None:
        return True, None
    return False, f"{module_name} is not installed in this environment."


class ForecastModelAdapter(ABC):
    """One stable contract for training, evaluation, persistence and forecasting."""

    #: Registry key. Must equal the key in `MODEL_REGISTRY`.
    model_id: str = ""
    #: User-visible name, preserved verbatim from the reference projects.
    display_name: str = ""
    #: Third-party module required to run.
    dependency_module: str | None = None
    #: Whether this model consumes an exogenous design matrix.
    requires_exogenous: bool = False
    #: Whether a single fit can score the whole panel (pooled/global mode).
    supports_pooled_training: bool = False
    #: Whether the evaluator forces a single chronological holdout instead of
    #: rolling-origin CV. Sodexo's expensive-model policy.
    uses_fast_holdout: bool = False
    #: Family, for grouping on the leaderboard.
    family: str = ""

    #: Label column names this adapter accepts, in preference order. The direct
    #: multi-horizon frame labels its target `y` (one row per series x origin x
    #: horizon), while a per-series frame labels it `target`. An adapter that
    #: reads both must say so, or eligibility rejects a perfectly good frame.
    label_columns: tuple[str, ...] = ("target",)

    def __init__(self, context: ModelContext | None = None) -> None:
        self.context = context or ModelContext()
        self._fitted = False
        self.diagnostics = AdapterDiagnostics(
            model_id=self.model_id, display_name=self.display_name
        )

    # ------------------------------------------------------------------
    # Eligibility
    # ------------------------------------------------------------------

    def min_required_history(self, context: ModelContext | None = None) -> int:
        """Minimum training rows, per the resolved history profile."""
        resolved = context or self.context
        thresholds = self._history_thresholds()
        return thresholds.get(resolved.min_history_profile, thresholds["reference"])

    def _history_thresholds(self) -> dict[str, int]:
        """Override per model. Values verified in the reference source."""
        return {"reference": 1, "monthly_relaxed": 1}

    def validate_eligibility(
        self, train_df: pd.DataFrame, context: ModelContext | None = None
    ) -> Eligibility:
        """Never raises. Returns a verdict with a reason and a remediation."""
        resolved = context or self.context

        available, detail = dependency_available(self.dependency_module)
        if not available:
            return Eligibility(
                eligible=False,
                code=EligibilityCode.DEPENDENCY_MISSING,
                reason=detail,
                remediation=(
                    f"Install {self.dependency_module} in the backend environment. "
                    "Until then this model cannot be evaluated."
                ),
            )

        label = self.resolve_label_column(train_df)
        if label is None:
            return Eligibility(
                eligible=False,
                code=EligibilityCode.NO_VALID_TARGET,
                reason=(
                    "The training frame carries none of this model's label columns "
                    f"{list(self.label_columns)}."
                ),
                remediation="Map a target column before training.",
            )

        values = pd.to_numeric(train_df[label], errors="coerce").dropna()
        if values.empty:
            return Eligibility(
                eligible=False,
                code=EligibilityCode.NO_VALID_TARGET,
                reason="The training window contains no valid target values.",
                remediation="Check the panel for this series; every value is missing.",
            )

        required = self.min_required_history(resolved)
        if len(values) < required:
            return Eligibility(
                eligible=False,
                code=EligibilityCode.INSUFFICIENT_HISTORY,
                reason=(
                    f"{self.display_name} needs at least {required} training "
                    f"observations; this window has {len(values)}."
                ),
                remediation=(
                    f"This series needs {required - len(values)} more month(s) of "
                    "history before the origin. Under the 'monthly_relaxed' history "
                    "profile the threshold is lower - see docs/DECISIONS.md D-001."
                ),
                required_history=required,
                observed_history=len(values),
            )

        return self._validate_model_specific(values, train_df, resolved)

    def resolve_label_column(self, frame: pd.DataFrame) -> str | None:
        """The first accepted label column present on this frame."""
        for column in self.label_columns:
            if column in frame.columns:
                return column
        return None

    def _validate_model_specific(
        self, values: pd.Series, train_df: pd.DataFrame, context: ModelContext
    ) -> Eligibility:
        """Override for per-model gates: seasonal cycles, positivity, endogenous
        variation, exogenous variation."""
        return Eligibility.ok()

    # ------------------------------------------------------------------
    # Fit and predict
    # ------------------------------------------------------------------

    def fit(self, train_df: pd.DataFrame, context: ModelContext | None = None) -> None:
        resolved = context or self.context
        seed_everything(resolved.random_seed)
        started = time.perf_counter()
        try:
            self._fit(train_df, resolved)
        except Exception as exc:
            self.diagnostics.failure_reason = f"{type(exc).__name__}: {exc}"[:500]
            self.diagnostics.training_duration_ms = (
                time.perf_counter() - started
            ) * 1000
            raise
        self._fitted = True
        self.diagnostics.fitted = True
        self.diagnostics.training_rows = len(train_df)
        self.diagnostics.training_duration_ms = (time.perf_counter() - started) * 1000
        self.diagnostics.parameters = self.parameter_metadata()
        self.diagnostics.features = self.feature_metadata()

    def predict(
        self, horizon_df: pd.DataFrame, context: ModelContext | None = None
    ) -> pd.Series:
        if not self._fitted:
            raise ModelNotFittedError(
                f"{self.display_name} must be fitted before predicting."
            )
        resolved = context or self.context
        started = time.perf_counter()
        raw = self._predict(horizon_df, resolved)
        self.diagnostics.inference_duration_ms = (time.perf_counter() - started) * 1000
        return clean_predictions(raw, len(horizon_df))

    @abstractmethod
    def _fit(self, train_df: pd.DataFrame, context: ModelContext) -> None:
        """Fit and store whatever `_predict` and `save` need."""

    @abstractmethod
    def _predict(self, horizon_df: pd.DataFrame, context: ModelContext) -> Any:
        """Return a sequence of length `len(horizon_df)`."""

    # ------------------------------------------------------------------
    # Metadata
    # ------------------------------------------------------------------

    def parameter_metadata(self) -> dict[str, Any]:
        """The hyperparameters actually used, not the ones requested."""
        return {}

    def feature_metadata(self) -> list[str]:
        """The feature names actually fed to the model."""
        return []

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    @abstractmethod
    def save(self, destination: Path) -> None:
        """Persist the fitted model. Neither reference project does this."""

    @abstractmethod
    def load(self, source: Path) -> None:
        """Restore a fitted model saved by `save`."""

    def __repr__(self) -> str:
        state = "fitted" if self._fitted else "unfitted"
        return f"<{type(self).__name__} {self.model_id!r} {state}>"


def clean_predictions(values: Any, expected_length: int) -> pd.Series:
    """Length-check and sanitise, exactly as Sodexo's `_clean_predictions`.

    A length mismatch raises rather than being padded: a model returning the
    wrong number of predictions is broken, and silently reshaping would hide it
    (Sodexo `models.py:80-84`).
    """
    series = pd.Series(np.asarray(values, dtype="float64").reshape(-1)).reset_index(
        drop=True
    )
    if len(series) != expected_length:
        raise ValueError(
            f"Expected {expected_length} predictions, got {len(series)}."
        )
    return series.replace([np.inf, -np.inf], np.nan)

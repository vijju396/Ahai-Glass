"""The four Exponential Smoothing variants.

Additive / Additive Damped / Multiplicative / Multiplicative Damped. The model
code is functionally **identical** in both references
(Meriton `training_service.py:1150-1178`, Sodexo `models.py:217-233`), so there
was nothing to arbitrate (docs/MODEL_INVENTORY.md SS2.7-2.10):

- `trend="add"` always, `initialization_method="estimated"`, `optimized=True`.
- A `TypeError` fallback from the modern `damped_trend=` kwarg to the legacy
  `damped=`, for older statsmodels.
- Minimum **24** rows, **and** at least two complete seasonal cycles.
- Multiplicative variants reject any `target <= 0`.

Two AIS-specific points, both deliberate:

**The seasonal-cycle check is against the smallest CV fold, not the full
window.** Sodexo's `smallest_fold_train_size` exists because a period that only
fits the full series makes every individual fold's fit fail at runtime. The
caller supplies the reference length.

**No positive floor is ever introduced.** 62% of AIS series are intermittent,
so the multiplicative variants are legitimately ineligible on most of them.
Shifting the target, adding an epsilon, or clipping to a small positive number
would manufacture eligibility and quietly change what is being forecast.
"""

from __future__ import annotations

import pickle
from pathlib import Path
from typing import Any

import pandas as pd

from app.ml.adapters.base import (
    Eligibility,
    EligibilityCode,
    ForecastModelAdapter,
    ModelContext,
)


class _ExpSmoothingBase(ForecastModelAdapter):
    dependency_module = "statsmodels"
    family = "exponential_smoothing"

    #: Set per subclass.
    seasonal: str = "add"
    damped: bool = False

    def _history_thresholds(self) -> dict[str, int]:
        # 24 in both references. The relaxed value is the documented AIS
        # deviation (docs/DECISIONS.md D-001), not a reference threshold.
        return {"reference": 24, "monthly_relaxed": 18}

    def __init__(self, context: ModelContext | None = None) -> None:
        super().__init__(context)
        self._results: Any = None
        self._period: int | None = None
        self._used_legacy_kwarg = False

    def _validate_model_specific(
        self, values: pd.Series, train_df: pd.DataFrame, context: ModelContext
    ) -> Eligibility:
        period = context.seasonal_period
        # Checked against the reference length the caller supplies, which for a
        # rolling-origin evaluation is the SMALLEST fold's training size.
        if not period:
            return Eligibility(
                eligible=False,
                code=EligibilityCode.INSUFFICIENT_SEASONAL_CYCLES,
                reason=(
                    "No seasonal period could be resolved, and every Exponential "
                    "Smoothing variant here is seasonal."
                ),
                remediation=(
                    "A seasonal period needs two complete cycles of history to "
                    "resolve. At monthly grain with a period of 12 that is 24 "
                    "months."
                ),
            )
        if len(values) < period * 2:
            return Eligibility(
                eligible=False,
                code=EligibilityCode.INSUFFICIENT_SEASONAL_CYCLES,
                reason=(
                    f"Exponential Smoothing needs two complete seasonal cycles "
                    f"({period * 2} months at period {period}); this window has "
                    f"{len(values)}."
                ),
                remediation=(
                    "This must hold in every rolling-origin fold, not just the "
                    "full window - a period that only fits the full series makes "
                    "each fold's fit fail at runtime. At AIS's monthly grain the "
                    "panel offers at most 22 training months before a 6-month "
                    "holdout, so period 12 cannot be satisfied."
                ),
                required_history=period * 2,
                observed_history=len(values),
            )
        if "multiplicative" in self.model_id and (values <= 0).any():
            zeros = int((values == 0).sum())
            negatives = int((values < 0).sum())
            return Eligibility(
                eligible=False,
                code=EligibilityCode.NON_POSITIVE_TARGET,
                reason=(
                    "Multiplicative smoothing requires strictly positive values; "
                    f"this series has {zeros} zero and {negatives} negative month(s)."
                ),
                remediation=(
                    "Nothing to remediate on this series - 62% of AIS series are "
                    "intermittent, and a zero month is a real observation. No "
                    "positive floor is introduced to force eligibility, because "
                    "that would change what is being forecast."
                ),
            )
        return Eligibility.ok()

    def _fit(self, train_df: pd.DataFrame, context: ModelContext) -> None:
        from statsmodels.tsa.api import ExponentialSmoothing

        values = pd.Series(
            pd.to_numeric(train_df["target"], errors="coerce").astype(float).to_numpy()
        )
        self._period = context.seasonal_period
        try:
            self._results = ExponentialSmoothing(
                values,
                seasonal_periods=self._period,
                trend="add",
                seasonal=self.seasonal,
                damped_trend=self.damped,
                initialization_method="estimated",
            ).fit(optimized=True)
        except TypeError:
            # Older statsmodels used `damped=`. Both references carry this
            # exact fallback.
            self._used_legacy_kwarg = True
            self._results = ExponentialSmoothing(
                values,
                seasonal_periods=self._period,
                trend="add",
                seasonal=self.seasonal,
                damped=self.damped,
            ).fit(optimized=True)

    def _predict(self, horizon_df: pd.DataFrame, context: ModelContext) -> Any:
        return self._results.forecast(len(horizon_df))

    def parameter_metadata(self) -> dict[str, Any]:
        return {
            "trend": "add",
            "seasonal": self.seasonal,
            "damped_trend": self.damped,
            "seasonal_periods": self._period,
            "initialization_method": "estimated",
            "optimized": True,
            "used_legacy_damped_kwarg": self._used_legacy_kwarg,
            "ported_from": "Sodexo models.py:217-233 (identical to Meriton :1150-1178)",
        }

    def save(self, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("wb") as handle:
            pickle.dump(
                {"results": self._results, "period": self._period}, handle
            )

    def load(self, source: Path) -> None:
        with source.open("rb") as handle:
            state = pickle.load(handle)
        self._results = state["results"]
        self._period = state["period"]
        self._fitted = True
        self.diagnostics.fitted = True


class ExpAdditiveAdapter(_ExpSmoothingBase):
    model_id = "exp_additive"
    display_name = "Exponential Smoothing Additive"
    seasonal = "add"
    damped = False


class ExpAdditiveDampedAdapter(_ExpSmoothingBase):
    model_id = "exp_additive_damped"
    display_name = "Exponential Smoothing Additive Damped"
    seasonal = "add"
    damped = True


class ExpMultiplicativeAdapter(_ExpSmoothingBase):
    model_id = "exp_multiplicative"
    display_name = "Exponential Smoothing Multiplicative"
    seasonal = "mul"
    damped = False


class ExpMultiplicativeDampedAdapter(_ExpSmoothingBase):
    model_id = "exp_multiplicative_damped"
    display_name = "Exponential Smoothing Multiplicative Damped"
    seasonal = "mul"
    damped = True

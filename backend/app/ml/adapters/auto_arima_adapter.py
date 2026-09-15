"""Auto ARIMA and Auto ARIMA with exogenous variables.

Ported from **Sodexo** `models.py:115-131` (docs/MODEL_INVENTORY.md SS2.3):

- `information_criterion="aicc"`. Meriton leaves the default (AIC); AICc is
  bias-corrected for small samples, which is exactly AIS's situation at 18-22
  monthly observations.
- Wider seasonal search: `max_P=2, max_D=1, max_Q=2` against Meriton's
  `1/1/1`.
- Shared with Meriton: `start_p=start_q=1, max_p=max_q=3, max_d=2,
  max_order=8, stepwise=True, error_action="ignore", suppress_warnings=True`.
- Minimum **24** rows in both references.

`uses_fast_holdout` is True: Sodexo forces a single chronological holdout for
this model rather than 3-fold CV, to bound runtime. AIS keeps that policy and
the leaderboard labels it, so its metrics are never silently compared against a
CV-evaluated model's (docs/DECISIONS.md D-003).

**At AIS's monthly grain this model is usually Ineligible.** The panel offers
at most 22 training rows before a 6-month holdout, against the 24 required. The
verdict says so with its remediation rather than the model quietly vanishing
(docs/DECISIONS.md D-001).
"""

from __future__ import annotations

import pickle
import warnings
from pathlib import Path
from typing import Any

import pandas as pd

from app.ml.adapters.base import ForecastModelAdapter, ModelContext
from app.ml.adapters.sarimax_adapter import SarimaxExogAdapter
from app.ml.legacy_models.exog import build_exog_pair

#: Sodexo's `AUTO_ARIMA_MAX_SEASONAL_PERIOD` guard: a very long seasonal period
#: makes the stepwise search explode. 12 is fine at monthly grain.
MAX_SEASONAL_PERIOD = 24


class _AutoArimaBase(ForecastModelAdapter):
    dependency_module = "pmdarima"
    family = "state_space"
    uses_fast_holdout = True

    def _history_thresholds(self) -> dict[str, int]:
        # 24 in both references (Sodexo models.py:118, Meriton :1063). The
        # relaxed profile is the documented AIS deviation, not a reference value.
        return {"reference": 24, "monthly_relaxed": 18}

    def __init__(self, context: ModelContext | None = None) -> None:
        super().__init__(context)
        self._model: Any = None
        self._exog_used: list[str] = []
        self._train_df: pd.DataFrame | None = None
        self._seasonal = False

    def _fit(self, train_df: pd.DataFrame, context: ModelContext) -> None:
        import pmdarima as pm

        target = pd.to_numeric(train_df["target"], errors="coerce").astype(float)
        exog_train = None
        if self.requires_exogenous:
            exog_train, _, self._exog_used = build_exog_pair(
                train_df, train_df, context.exog_columns
            )
            self.diagnostics.exogenous_columns_used = list(self._exog_used)

        period = context.seasonal_period
        self._seasonal = bool(
            period and period <= MAX_SEASONAL_PERIOD and len(target) >= period * 2
        )
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self._model = pm.auto_arima(
                target,
                X=exog_train,
                start_p=1,
                start_q=1,
                max_p=3,
                max_q=3,
                max_d=2,
                m=period if self._seasonal else 1,
                seasonal=self._seasonal,
                D=0 if self._seasonal else None,
                max_P=2,
                max_D=1,
                max_Q=2,
                max_order=8,
                information_criterion="aicc",
                error_action="ignore",
                suppress_warnings=True,
                stepwise=True,
                trace=False,
            )
        self._train_df = train_df

    def _predict(self, horizon_df: pd.DataFrame, context: ModelContext) -> Any:
        exog_future = None
        if self.requires_exogenous:
            _, exog_future, _ = build_exog_pair(
                self._train_df,
                horizon_df,
                context.exog_columns,
                require_future_values=True,
            )
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return self._model.predict(n_periods=len(horizon_df), X=exog_future)

    def parameter_metadata(self) -> dict[str, Any]:
        selected = None
        seasonal_selected = None
        if self._model is not None:
            try:
                selected = list(self._model.order)
                seasonal_selected = list(self._model.seasonal_order)
            except AttributeError:
                pass
        return {
            "information_criterion": "aicc",
            "search_space": {
                "max_p": 3, "max_q": 3, "max_d": 2,
                "max_P": 2, "max_D": 1, "max_Q": 2, "max_order": 8,
            },
            "stepwise": True,
            "seasonal": self._seasonal,
            "selected_order": selected,
            "selected_seasonal_order": seasonal_selected,
            "evaluation_policy": "single chronological holdout (expensive-model policy)",
            "ported_from": "Sodexo models.py:115-131 (aicc, wider seasonal search)",
        }

    def feature_metadata(self) -> list[str]:
        return list(self._exog_used)

    def save(self, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("wb") as handle:
            pickle.dump(
                {
                    "model": self._model,
                    "exog_used": self._exog_used,
                    "train_df": self._train_df,
                    "seasonal": self._seasonal,
                },
                handle,
            )

    def load(self, source: Path) -> None:
        with source.open("rb") as handle:
            state = pickle.load(handle)
        self._model = state["model"]
        self._exog_used = state["exog_used"]
        self._train_df = state["train_df"]
        self._seasonal = state["seasonal"]
        self._fitted = True
        self.diagnostics.fitted = True


class AutoArimaAdapter(_AutoArimaBase):
    model_id = "auto_arima"
    display_name = "Auto ARIMA"
    requires_exogenous = False


class AutoArimaExogAdapter(_AutoArimaBase):
    model_id = "auto_arima_exog"
    display_name = "Auto ARIMA with exogenous variables"
    requires_exogenous = True

    # The exogenous gate is identical to SARIMAX-exog's, so it is reused rather
    # than duplicated.
    _validate_model_specific = SarimaxExogAdapter._validate_model_specific

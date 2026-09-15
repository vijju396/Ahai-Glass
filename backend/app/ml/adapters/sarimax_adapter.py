"""SARIMAX and SARIMAX with exogenous variables.

Ported from **Sodexo** `models.py:89-110`, which is the safer of the two
reference implementations (docs/MODEL_INVENTORY.md SS2.1):

- `ar_order = 1 if use_seasonal and period <= 2 else 2`. statsmodels rejects a
  model whose non-seasonal AR lag coincides with a seasonal one, which happens
  at period 2. Meriton's fixed `(2,1,1)` has no such guard and raises there.
- `seasonal_order = (1,0,1,period)` when `len >= period*3`, else `(0,0,0,0)`.
  Meriton uses `(0,0,0,period)` gated on `period*2` - every seasonal term zero,
  which makes "SARIMAX" a plain ARIMA(2,1,1) with no seasonal structure at all.
  Sodexo's own comment records that this was a real defect it fixed.
- `enforce_stationarity=False`, `enforce_invertibility=False` in both.
- Minimum 12 rows in both.
"""

from __future__ import annotations

import pickle
import warnings
from pathlib import Path
from typing import Any

import pandas as pd

from app.ml.adapters.base import (
    Eligibility,
    EligibilityCode,
    ForecastModelAdapter,
    ModelContext,
)
from app.ml.legacy_models.exog import build_exog_pair


class _SarimaxBase(ForecastModelAdapter):
    dependency_module = "statsmodels"
    family = "state_space"

    def _history_thresholds(self) -> dict[str, int]:
        # 12 in both references (Sodexo models.py:92, Meriton :1037).
        return {"reference": 12, "monthly_relaxed": 12}

    def __init__(self, context: ModelContext | None = None) -> None:
        super().__init__(context)
        self._results: Any = None
        self._order: tuple[int, int, int] | None = None
        self._seasonal_order: tuple[int, int, int, int] | None = None
        self._exog_used: list[str] = []

    def _resolve_orders(
        self, observations: int, context: ModelContext
    ) -> tuple[tuple[int, int, int], tuple[int, int, int, int]]:
        period = context.seasonal_period
        use_seasonal = bool(period and observations >= period * 3)
        seasonal_order = (1, 0, 1, period) if use_seasonal and period else (0, 0, 0, 0)
        ar_order = 1 if use_seasonal and period is not None and period <= 2 else 2
        return (ar_order, 1, 1), seasonal_order

    def _fit(self, train_df: pd.DataFrame, context: ModelContext) -> None:
        from statsmodels.tsa.statespace.sarimax import SARIMAX

        target = pd.to_numeric(train_df["target"], errors="coerce").astype(float)
        exog_train = None
        if self.requires_exogenous:
            exog_train, _, self._exog_used = build_exog_pair(
                train_df, train_df, context.exog_columns
            )
            self.diagnostics.exogenous_columns_used = list(self._exog_used)

        self._order, self._seasonal_order = self._resolve_orders(len(target), context)
        with warnings.catch_warnings():
            # Convergence chatter is suppressed in both references (disp=False).
            warnings.simplefilter("ignore")
            self._results = SARIMAX(
                target,
                exog=exog_train,
                order=self._order,
                seasonal_order=self._seasonal_order,
                enforce_stationarity=False,
                enforce_invertibility=False,
            ).fit(disp=False)
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
            return self._results.forecast(steps=len(horizon_df), exog=exog_future)

    def parameter_metadata(self) -> dict[str, Any]:
        return {
            "order": list(self._order) if self._order else None,
            "seasonal_order": list(self._seasonal_order) if self._seasonal_order else None,
            "enforce_stationarity": False,
            "enforce_invertibility": False,
            "seasonal_terms_active": bool(
                self._seasonal_order and self._seasonal_order[3]
            ),
            "ported_from": "Sodexo models.py:89-110 (AR-collision guard)",
        }

    def feature_metadata(self) -> list[str]:
        return list(self._exog_used)

    def save(self, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("wb") as handle:
            pickle.dump(
                {
                    "results": self._results,
                    "order": self._order,
                    "seasonal_order": self._seasonal_order,
                    "exog_used": self._exog_used,
                    "train_df": self._train_df,
                },
                handle,
            )

    def load(self, source: Path) -> None:
        with source.open("rb") as handle:
            state = pickle.load(handle)
        self._results = state["results"]
        self._order = state["order"]
        self._seasonal_order = state["seasonal_order"]
        self._exog_used = state["exog_used"]
        self._train_df = state["train_df"]
        self._fitted = True
        self.diagnostics.fitted = True


class SarimaxAdapter(_SarimaxBase):
    model_id = "sarimax"
    display_name = "SARIMAX"
    requires_exogenous = False


class SarimaxExogAdapter(_SarimaxBase):
    model_id = "sarimax_exog"
    display_name = "SARIMAX with exogenous variables"
    requires_exogenous = True

    def _validate_model_specific(
        self, values: pd.Series, train_df: pd.DataFrame, context: ModelContext
    ) -> Eligibility:
        if not context.exog_columns:
            return Eligibility(
                eligible=False,
                code=EligibilityCode.NO_VARYING_EXOGENOUS,
                reason="No exogenous drivers are enabled for this series.",
                remediation=(
                    "Map at least one future-known driver in Mapping & Validation. "
                    "Only genuinely future-known columns qualify - a price is not "
                    "one."
                ),
            )
        present = [c for c in context.exog_columns if c in train_df.columns]
        if not present:
            return Eligibility(
                eligible=False,
                code=EligibilityCode.NO_VARYING_EXOGENOUS,
                reason="None of the mapped exogenous columns is present in this frame.",
                remediation="Rebuild the panel so the mapped drivers are carried.",
            )
        if not any(train_df[c].nunique(dropna=False) > 1 for c in present):
            return Eligibility(
                eligible=False,
                code=EligibilityCode.NO_VARYING_EXOGENOUS,
                reason=(
                    "Every mapped exogenous driver is constant in this training "
                    "window, so there is nothing to regress on."
                ),
                remediation=(
                    "A constant driver carries no information. Either widen the "
                    "window or enable a driver that varies."
                ),
            )
        return Eligibility.ok()

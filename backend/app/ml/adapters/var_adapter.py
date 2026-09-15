"""VAR and VAR with exogenous variables.

Ported from **Meriton**'s generalized multi-endogenous design
(`training_service.py:1181-1204`, `_prepare_var_endog` `:1964-1977`), which is
the more general of the two: it treats VAR as genuinely multivariate across
several endogenous columns, where Sodexo's is a narrower bivariate
`target + var_pair` tailored to its four fixed series
(docs/MODEL_INVENTORY.md SS2.11).

Behaviour preserved from Meriton:

- Constant endogenous columns are **dropped**, and their last value carried as
  an additive `constant_total` offset added back to the forecast.
- At least **two** non-constant aligned endogenous columns are required, else
  the model is **Ineligible** - not Failed. Both references gate rather than
  raise, and that distinction is the whole point of the two statuses.
- Non-finite endogenous values raise.
- Lag order `min(7, len // 10)`, bounded by solvability
  `(len - exog_count - 2) // (k + 1)`; `ic=None` for a deterministic bounded
  lag rather than an IC search; `trend="c"`.

**AIS's second endogenous series is `despatched_qty`** (docs/DECISIONS.md
D-004). It genuinely co-evolves with ordered quantity and exists at the same
grain. It is also supply-censored, which is recorded in `parameter_metadata`
and surfaced in the UI: it is a co-movement signal, not a second demand truth.
Most sparse series have a constant pair, and VAR is then Ineligible with that
reason.
"""

from __future__ import annotations

import pickle
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from app.ml.adapters.base import (
    Eligibility,
    EligibilityCode,
    ForecastModelAdapter,
    ModelContext,
)
from app.ml.legacy_models.exog import build_exog_pair

#: Meriton's `_var_lag_order` ceiling.
MAX_LAG = 7


def candidate_endogenous(
    train_df: pd.DataFrame, context: ModelContext
) -> list[str]:
    """`target` plus whatever co-evolving columns this frame actually carries.

    Ordered so the target is always column 0, because the forecast is read from
    that position.
    """
    columns = ["target"]
    for candidate in (context.var_pair_column, "shortfall_qty", "mean_mrp"):
        if candidate in train_df.columns and candidate not in columns:
            columns.append(candidate)
    return columns


class _VarBase(ForecastModelAdapter):
    dependency_module = "statsmodels"
    family = "vector_autoregression"

    def _history_thresholds(self) -> dict[str, int]:
        return {"reference": 10, "monthly_relaxed": 10}

    def __init__(self, context: ModelContext | None = None) -> None:
        super().__init__(context)
        self._results: Any = None
        self._endog_columns: list[str] = []
        self._constant_total = 0.0
        self._endog_tail: np.ndarray | None = None
        self._lag_order = 0
        self._exog_used: list[str] = []
        self._train_df: pd.DataFrame | None = None

    def _prepare_endog(
        self, train_df: pd.DataFrame, context: ModelContext
    ) -> tuple[pd.DataFrame, float]:
        """Meriton's `_prepare_var_endog`, with its constant-column offset."""
        columns = candidate_endogenous(train_df, context)
        frame = train_df[columns].apply(pd.to_numeric, errors="coerce")
        # A null in a co-evolving column is not zero demand - it is an unknown,
        # and for a sales_proxy row that is exactly what despatched_qty is. Rows
        # cannot be dropped without breaking alignment, so the column is.
        frame = frame.loc[:, frame.notna().all(axis=0)]
        frame = frame.astype(float).reset_index(drop=True)

        values = frame.to_numpy(dtype=float)
        if not np.isfinite(values).all():
            raise ValueError(
                "VAR requires finite, aligned values for every endogenous series."
            )
        constant_columns = [c for c in frame.columns if frame[c].nunique(dropna=False) <= 1]
        constant_total = (
            float(frame[constant_columns].iloc[-1].sum()) if constant_columns else 0.0
        )
        dynamic = frame.drop(columns=constant_columns)
        if dynamic.shape[1] < 2:
            raise ValueError(
                "VAR requires at least two non-constant aligned endogenous series."
            )
        return dynamic, constant_total

    def _lag_order_for(self, endog: pd.DataFrame, exog_count: int = 0) -> int:
        """Meriton's `_var_lag_order`, bounded by solvability."""
        preferred = min(MAX_LAG, max(1, len(endog) // 10))
        max_supported = (len(endog) - exog_count - 2) // (endog.shape[1] + 1)
        if max_supported < 1:
            raise ValueError(
                "VAR does not have enough observations for the number of series "
                "and features available."
            )
        return min(preferred, max_supported)

    def _validate_model_specific(
        self, values: pd.Series, train_df: pd.DataFrame, context: ModelContext
    ) -> Eligibility:
        columns = candidate_endogenous(train_df, context)
        available = [c for c in columns if c in train_df.columns]
        usable: list[str] = []
        for column in available:
            series = pd.to_numeric(train_df[column], errors="coerce")
            if series.notna().all() and series.nunique(dropna=False) > 1:
                usable.append(column)

        if len(usable) < 2:
            constant = [c for c in available if c not in usable]
            return Eligibility(
                eligible=False,
                code=EligibilityCode.INSUFFICIENT_ENDOGENOUS,
                reason=(
                    "VAR requires two non-constant, co-evolving series; only "
                    f"{len(usable)} of {len(available)} qualify here "
                    f"(constant or incomplete: {constant})."
                ),
                remediation=(
                    "This is the normal outcome on a sparse series: if ordered "
                    "quantity or its paired despatched quantity is flat across the "
                    "window, there is no co-movement to model. The series is "
                    "Ineligible for VAR, not failed - other models still run."
                ),
            )

        if self.requires_exogenous:
            if not context.exog_columns:
                return Eligibility(
                    eligible=False,
                    code=EligibilityCode.NO_VARYING_EXOGENOUS,
                    reason="No exogenous drivers are enabled for this series.",
                    remediation="Map at least one genuinely future-known driver.",
                )
            present = [c for c in context.exog_columns if c in train_df.columns]
            if not any(train_df[c].nunique(dropna=False) > 1 for c in present):
                return Eligibility(
                    eligible=False,
                    code=EligibilityCode.NO_VARYING_EXOGENOUS,
                    reason=(
                        "VAR with exogenous variables needs at least one driver "
                        "that actually varies in this window."
                    ),
                    remediation=(
                        "Every mapped driver is constant here - for example no "
                        "holiday fell inside the window."
                    ),
                )
        return Eligibility.ok()

    def _fit(self, train_df: pd.DataFrame, context: ModelContext) -> None:
        from statsmodels.tsa.api import VAR

        endog, self._constant_total = self._prepare_endog(train_df, context)
        self._endog_columns = list(endog.columns)

        exog_train = None
        exog_count = 0
        if self.requires_exogenous:
            exog_train, _, self._exog_used = build_exog_pair(
                train_df, train_df, context.exog_columns
            )
            varying = [
                c for c in exog_train.columns if exog_train[c].nunique(dropna=False) > 1
            ]
            if not varying:
                raise ValueError(
                    "VAR with exogenous variables requires at least one varying "
                    "exogenous feature."
                )
            exog_train = exog_train[varying]
            self._exog_used = varying
            exog_count = exog_train.shape[1]
            self.diagnostics.exogenous_columns_used = list(varying)
            # `_prepare_endog` resets its index while `build_exog_pair` keeps
            # the caller's - a panel slice carries the parquet row numbers, so
            # the two frames disagree and statsmodels raises "The indices for
            # endog and exog are not aligned". Aligning positionally is correct
            # here precisely because `_prepare_endog` drops columns, never rows;
            # the assertion below is what keeps that a fact rather than an
            # assumption, since a silent length mismatch would shift every
            # driver against its own month.
            if len(exog_train) != len(endog):
                raise ValueError(
                    f"exogenous matrix has {len(exog_train)} rows for "
                    f"{len(endog)} endogenous rows; VAR cannot align them."
                )
            exog_train = exog_train.reset_index(drop=True)

        maxlags = self._lag_order_for(endog, exog_count)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model = VAR(endog, exog=exog_train) if exog_train is not None else VAR(endog)
            self._results = model.fit(maxlags=maxlags, ic=None, trend="c")
        self._lag_order = int(self._results.k_ar)
        tail = self._lag_order if self._lag_order else 1
        self._endog_tail = endog.to_numpy(dtype=float)[-tail:]
        self._train_df = train_df

    def _predict(self, horizon_df: pd.DataFrame, context: ModelContext) -> Any:
        exog_future = None
        if self.requires_exogenous and self._train_df is not None:
            _, exog_future, _ = build_exog_pair(
                self._train_df,
                horizon_df,
                context.exog_columns,
                require_future_values=True,
            )
            exog_future = exog_future[self._exog_used].to_numpy()

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            if exog_future is not None:
                forecast = self._results.forecast(
                    self._endog_tail, steps=len(horizon_df), exog_future=exog_future
                )
            else:
                forecast = self._results.forecast(
                    self._endog_tail, steps=len(horizon_df)
                )
        # Meriton sums the endogenous forecasts and adds the constant offset;
        # that is correct when the columns are dimension-pivoted slices of one
        # target. Here the columns are DIFFERENT quantities - ordered versus
        # despatched - so summing them would forecast their total. The target
        # is column 0 by construction.
        return np.asarray(forecast)[:, 0] + self._constant_total

    def parameter_metadata(self) -> dict[str, Any]:
        return {
            "endogenous_columns": list(self._endog_columns),
            "lag_order": self._lag_order,
            "ic": None,
            "trend": "c",
            "constant_column_offset": self._constant_total,
            "target_read_from_column": 0,
            "paired_series_note": (
                "The paired endogenous series is despatched quantity, which is "
                "supply-censored. It is a co-movement signal, not a second demand "
                "truth (docs/DECISIONS.md D-004)."
            ),
            "ported_from": (
                "Meriton training_service.py:1181-1204, _prepare_var_endog:1964-1977"
            ),
        }

    def feature_metadata(self) -> list[str]:
        return [*self._endog_columns, *self._exog_used]

    def save(self, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("wb") as handle:
            pickle.dump(
                {
                    "results": self._results,
                    "endog_columns": self._endog_columns,
                    "constant_total": self._constant_total,
                    "endog_tail": self._endog_tail,
                    "lag_order": self._lag_order,
                    "exog_used": self._exog_used,
                    "train_df": self._train_df,
                },
                handle,
            )

    def load(self, source: Path) -> None:
        with source.open("rb") as handle:
            state = pickle.load(handle)
        self._results = state["results"]
        self._endog_columns = state["endog_columns"]
        self._constant_total = state["constant_total"]
        self._endog_tail = state["endog_tail"]
        self._lag_order = state["lag_order"]
        self._exog_used = state["exog_used"]
        self._train_df = state["train_df"]
        self._fitted = True
        self.diagnostics.fitted = True


class VarAdapter(_VarBase):
    model_id = "var"
    display_name = "VAR"
    requires_exogenous = False


class VarExogAdapter(_VarBase):
    model_id = "var_exog"
    display_name = "VAR with exogenous variables"
    requires_exogenous = True

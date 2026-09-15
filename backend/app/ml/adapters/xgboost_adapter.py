"""XGBoost and XGBoost with exogenous variables.

Hyperparameters from **Meriton** `training_service.py:1099-1131`
(`GridSearchCV`, `cv=2`, `random_state=42`), with **Sodexo**'s fixed-parameter
set (`models.py:196-199`) available as the `fast` training profile. Both are
exposed as a profile rather than hardcoded either way
(docs/MODEL_INVENTORY.md SS2.5).

**Two forecasting modes, and the default is not the references'.**

The references forecast **recursively**: predict one step, append it to the
history, repeat. Their loops append the *actual* value when the output frame
carries one (`Meriton :1130`, `Sodexo :211`), which on a validation fold makes
every step effectively one-step-ahead and flatters the fold against a genuine
six-month plan.

AIS defaults to **direct multi-horizon**: `horizon` is a feature, the Phase 4
training frame already carries one row per (series, origin, horizon), and a
single fit answers all six horizons with no recursion and nothing to leak. The
analysis document specifies exactly this - "rather than chaining a one-month
model into itself six times, which compounds its own errors".

The recursive path is retained for parity against the references and is
selected by passing a frame without a `horizon` column. Even then,
`context.allow_actuals_in_recursion` defaults to False, so the walk feeds its
own predictions (docs/DECISIONS.md D-031).

**Dtype stability.** Feature frames are built once, reindexed to a stored
column order, and cast to a single dtype. Mixed or shifting dtypes change
XGBoost's `hist` binning and move predictions silently; Oxea found and fixed a
real bug of exactly this kind.
"""

from __future__ import annotations

import json
import statistics
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
from app.ml.adapters.sarimax_adapter import SarimaxExogAdapter
from app.ml.legacy_models.exog import build_exog_pair

#: Meriton's grid (`training_service.py:1105-1112`).
THOROUGH_GRID: dict[str, list[Any]] = {
    "learning_rate": [0.05, 0.1],
    "max_depth": [3, 5],
    "min_child_weight": [1],
    "subsample": [0.8],
    "colsample_bytree": [0.8],
    "n_estimators": [100, 200],
}

#: Sodexo's fixed parameters (`models.py:196-199`).
FAST_PARAMS: dict[str, Any] = {
    "learning_rate": 0.1,
    "max_depth": 4,
    "n_estimators": 100,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
}

#: The single dtype every feature matrix is cast to, so `hist` binning is stable.
FEATURE_DTYPE = "float32"

#: Both references require at least 5 lagged rows.
MIN_LAGGED_ROWS = 5

_RECURSIVE_LAGS = (1, 7, 14, 28)
_RECURSIVE_ROLLINGS = (7, 28)


class _XGBoostBase(ForecastModelAdapter):
    dependency_module = "xgboost"
    family = "gradient_boosting"
    supports_pooled_training = True
    # The direct multi-horizon frame labels its target `y`; a per-series frame
    # labels it `target`. Both are valid inputs to this model.
    label_columns = ("y", "target")

    def _history_thresholds(self) -> dict[str, int]:
        # 5 lagged rows means 6 observations.
        return {"reference": 6, "monthly_relaxed": 6}

    def __init__(self, context: ModelContext | None = None) -> None:
        super().__init__(context)
        self._model: Any = None
        self._feature_columns: list[str] = []
        self._categorical_maps: dict[str, list[str]] = {}
        self._resolved_params: dict[str, Any] = {}
        self._mode = "direct"
        self._exog_used: list[str] = []
        self._history: list[float] = []
        self._train_df: pd.DataFrame | None = None

    # ------------------------------------------------------------------
    # Feature matrices
    # ------------------------------------------------------------------

    def _direct_matrix(
        self, frame: pd.DataFrame, *, fitting: bool
    ) -> tuple[pd.DataFrame, pd.Series | None]:
        """Use the Phase 4 direct multi-horizon frame as-is.

        Categorical columns are integer-coded against a map fitted at training
        time, so an unseen category at scoring time becomes -1 rather than
        shifting every other code.
        """
        exclude = {
            "series_id", "y", "target", "target_period", "period_index",
            "canonical_branch", "canonical_sku", "period", "is_materialised",
            "value_unavailable_reason",
        }
        if fitting:
            candidates = [c for c in frame.columns if c not in exclude]
            self._categorical_maps = {}
            numeric: list[str] = []
            for column in candidates:
                series = frame[column]
                if series.dtype.name in {"object", "string", "category", "boolean"}:
                    categories = sorted(
                        str(v) for v in series.dropna().astype(str).unique()
                    )
                    self._categorical_maps[column] = categories
                numeric.append(column)
            self._feature_columns = numeric

        matrix = pd.DataFrame(index=frame.index)
        for column in self._feature_columns:
            if column in self._categorical_maps:
                lookup = {name: index for index, name in enumerate(self._categorical_maps[column])}
                source = frame[column] if column in frame.columns else pd.Series(index=frame.index)
                matrix[column] = (
                    source.astype("string").map(lookup).fillna(-1).astype(FEATURE_DTYPE)
                )
            else:
                source = (
                    frame[column] if column in frame.columns else pd.Series(index=frame.index)
                )
                matrix[column] = pd.to_numeric(source, errors="coerce").astype(FEATURE_DTYPE)

        target = None
        if fitting:
            label = "y" if "y" in frame.columns else "target"
            target = pd.to_numeric(frame[label], errors="coerce").astype("float64")
        return matrix, target

    # -- the reference's recursive path, kept for parity ----------------

    @staticmethod
    def _lag(history: list[float], steps: int) -> float:
        if not history:
            return 0.0
        if len(history) >= steps:
            return history[-steps]
        return _XGBoostBase._rolling(history, min(len(history), steps))

    @staticmethod
    def _rolling(history: list[float], window: int) -> float:
        if not history:
            return 0.0
        tail = history[-window:] if len(history) >= window else history
        return sum(tail) / len(tail)

    @staticmethod
    def _rolling_median(history: list[float], window: int) -> float:
        if not history:
            return 0.0
        return float(statistics.median(history[-window:]))

    @staticmethod
    def _rolling_std(history: list[float], window: int) -> float:
        tail = history[-window:]
        return float(statistics.pstdev(tail)) if len(tail) > 1 else 0.0

    def _recursive_features(
        self, period_index: int, history: list[float], exog_row: pd.Series | None
    ) -> dict[str, float]:
        features: dict[str, float] = {
            "month": float((period_index % 12) + 1),
            "trend_index": float(len(history)),
        }
        for lag in _RECURSIVE_LAGS:
            features[f"lag_{lag}"] = self._lag(history, lag)
        for window in _RECURSIVE_ROLLINGS:
            features[f"rolling_{window}"] = self._rolling(history, window)
        features["rolling_median_7"] = self._rolling_median(history, 7)
        features["rolling_std_7"] = self._rolling_std(history, 7)
        if self.requires_exogenous and exog_row is not None:
            for column in self._exog_used:
                features[column] = float(exog_row.get(column, 0.0))
        return features

    def _recursive_matrix(self, train_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
        target = pd.to_numeric(train_df["target"], errors="coerce").astype(float)
        history = target.tolist()
        periods = train_df["period_index"].tolist()
        exog = None
        if self.requires_exogenous:
            exog, _, self._exog_used = build_exog_pair(
                train_df, train_df, self.context.exog_columns, standardise=False
            )
        rows: list[dict[str, float]] = []
        labels: list[float] = []
        for index in range(1, len(train_df)):
            rows.append(
                self._recursive_features(
                    int(periods[index]),
                    history[:index],
                    exog.iloc[index] if exog is not None else None,
                )
            )
            labels.append(history[index])
        return pd.DataFrame(rows), pd.Series(labels)

    # ------------------------------------------------------------------
    # Fit and predict
    # ------------------------------------------------------------------

    def _make_estimator(self, context: ModelContext):  # noqa: ANN202
        from xgboost import XGBRegressor

        return XGBRegressor(
            objective="reg:squarederror",
            random_state=context.random_seed,
            n_jobs=1,
            tree_method="hist",
        )

    def _fit(self, train_df: pd.DataFrame, context: ModelContext) -> None:
        from sklearn.model_selection import GridSearchCV

        self._mode = "direct" if "horizon" in train_df.columns else "recursive"

        if self._mode == "direct":
            matrix, labels = self._direct_matrix(train_df, fitting=True)
        else:
            matrix, labels = self._recursive_matrix(train_df)
            if len(matrix) < MIN_LAGGED_ROWS:
                raise ValueError(
                    f"Not enough lagged rows for XGBoost: {len(matrix)} < {MIN_LAGGED_ROWS}."
                )
            self._feature_columns = list(matrix.columns)
            matrix = matrix.astype(FEATURE_DTYPE)
            self._history = pd.to_numeric(train_df["target"], errors="coerce").astype(float).tolist()

        self.diagnostics.exogenous_columns_used = list(self._exog_used)
        estimator = self._make_estimator(context)

        if context.xgboost_training_profile == "thorough":
            search = GridSearchCV(
                estimator, THOROUGH_GRID, cv=2, n_jobs=1, verbose=0
            )
            search.fit(matrix, labels)
            self._model = search.best_estimator_
            self._resolved_params = dict(search.best_params_)
            self._resolved_params["selection"] = "GridSearchCV(cv=2)"
        else:
            estimator.set_params(**FAST_PARAMS)
            estimator.fit(matrix, labels)
            self._model = estimator
            self._resolved_params = dict(FAST_PARAMS)
            self._resolved_params["selection"] = "fixed"

        self._train_df = train_df

    def _predict(self, horizon_df: pd.DataFrame, context: ModelContext) -> Any:
        if self._mode == "direct":
            matrix, _ = self._direct_matrix(horizon_df, fitting=False)
            return self._model.predict(matrix)

        # The reference's recursive walk, retained for parity.
        history = list(self._history)
        exog_future = None
        if self.requires_exogenous and self._train_df is not None:
            _, exog_future, _ = build_exog_pair(
                self._train_df, horizon_df, context.exog_columns, standardise=False
            )
        predictions: list[float] = []
        for position, (_, row) in enumerate(horizon_df.iterrows()):
            features = pd.DataFrame(
                [
                    self._recursive_features(
                        int(row.get("period_index", position)),
                        history,
                        exog_future.iloc[position] if exog_future is not None else None,
                    )
                ]
            )
            features = features.reindex(
                columns=self._feature_columns, fill_value=0.0
            ).astype(FEATURE_DTYPE)
            predicted = float(self._model.predict(features)[0])
            predictions.append(predicted)
            actual = row.get("target")
            if (
                context.allow_actuals_in_recursion
                and actual is not None
                and not pd.isna(actual)
            ):
                history.append(float(actual))
            else:
                history.append(predicted)
        return predictions

    def parameter_metadata(self) -> dict[str, Any]:
        return {
            **self._resolved_params,
            "random_state": self.context.random_seed,
            "tree_method": "hist",
            "feature_dtype": FEATURE_DTYPE,
            "forecast_mode": self._mode,
            "profile": self.context.xgboost_training_profile,
            "allow_actuals_in_recursion": self.context.allow_actuals_in_recursion,
            "ported_from": (
                "Meriton training_service.py:1099-1131 (GridSearchCV); "
                "Sodexo models.py:196-199 (fast profile)"
            ),
        }

    def feature_metadata(self) -> list[str]:
        return list(self._feature_columns)

    def save(self, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        # XGBoost's own JSON format, not pickle: it is version-portable and is
        # what Oxea uses for these two adapters.
        self._model.save_model(str(destination.with_suffix(".json")))
        destination.with_suffix(".meta.json").write_text(
            json.dumps(
                {
                    "feature_columns": self._feature_columns,
                    "categorical_maps": self._categorical_maps,
                    "resolved_params": self._resolved_params,
                    "mode": self._mode,
                    "exog_used": self._exog_used,
                    "history": self._history,
                },
                default=str,
            ),
            encoding="utf-8",
        )

    def load(self, source: Path) -> None:
        from xgboost import XGBRegressor

        self._model = XGBRegressor()
        self._model.load_model(str(source.with_suffix(".json")))
        meta = json.loads(source.with_suffix(".meta.json").read_text(encoding="utf-8"))
        self._feature_columns = meta["feature_columns"]
        self._categorical_maps = meta["categorical_maps"]
        self._resolved_params = meta["resolved_params"]
        self._mode = meta["mode"]
        self._exog_used = meta["exog_used"]
        self._history = [float(v) for v in meta["history"]]
        self._fitted = True
        self.diagnostics.fitted = True


class XGBoostAdapter(_XGBoostBase):
    model_id = "xgboost"
    display_name = "XGBoost"
    requires_exogenous = False


class XGBoostExogAdapter(_XGBoostBase):
    model_id = "xgboost_exog"
    display_name = "XGBoost with exogenous variables"
    requires_exogenous = True

    def _validate_model_specific(
        self, values: pd.Series, train_df: pd.DataFrame, context: ModelContext
    ) -> Eligibility:
        # In direct mode the exogenous columns are already features of the
        # training frame, so the separate exogenous gate does not apply.
        if "horizon" in train_df.columns:
            return Eligibility.ok()
        return SarimaxExogAdapter._validate_model_specific(
            self, values, train_df, context
        )

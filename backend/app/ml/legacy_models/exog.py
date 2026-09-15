"""Exogenous design-matrix construction, ported from both references.

Additive combination of two implementations, neither of which conflicts with
the other (docs/MODEL_INVENTORY.md SS2):

- **Sodexo** `_exog_pair` (`models.py:65-77`) and `_independent_exog_columns`
  (`models.py:34-62`): fold-fitted z-score standardisation, then a greedy drop
  of columns that do not vary, are near-duplicate of a kept column, or fail to
  raise the rank of `[intercept | kept...]`. The intercept sits inside the rank
  test precisely so the dummy-variable trap is caught - the dummies are
  independent of each other, and only collinear once statsmodels adds its own
  constant.
- **Meriton** `_fit_source_exog_schema` (`training_service.py:1915-1937`):
  one-hot encoding of categoricals with a cardinality cap, and a hard error
  rather than silent truncation when the cap is exceeded.

**Standardisation is fitted on the training fold only.** Both references do
this, and it is the difference between a leakage-free fold and a flattering
one.

XGBoost is the deliberate exception: both references pass its exogenous
features **raw and unstandardised**. Sodexo's own audit flags the asymmetry as
"observed but unexplained, not a bug". It is preserved rather than tidied,
because tree splits are scale-invariant and changing it would break parity for
no gain.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

#: Sodexo's `_MAX_EXOG_CORRELATION` (`models.py:31`).
MAX_EXOG_CORRELATION = 0.95

#: Meriton's `FORECAST_MAX_EXOG_CATEGORIES` default (`training_service.py:1918`).
DEFAULT_MAX_EXOG_CATEGORIES = 50


class FutureExogenousUnavailable(RuntimeError):
    """A future-known driver has no value for a horizon row.

    Meriton raises this by the same name. AIS's mapping-confirmation gate (rule
    R5) is meant to catch it earlier, so reaching here means a driver slipped
    through as future-known when it is not.
    """


@dataclass
class ExogSchema:
    """How each source column becomes one or more model features."""

    entries: list[dict[str, Any]] = field(default_factory=list)

    @property
    def feature_names(self) -> list[str]:
        names: list[str] = []
        for entry in self.entries:
            names.extend(entry["features"])
        return names


def max_exog_categories() -> int:
    return max(2, int(os.getenv("FORECAST_MAX_EXOG_CATEGORIES", str(DEFAULT_MAX_EXOG_CATEGORIES))))


def fit_exog_schema(train_df: pd.DataFrame, exog_columns: tuple[str, ...]) -> ExogSchema:
    """Decide per column whether it is numeric or categorical, on the training
    fold only.

    Meriton's rule: a column is numeric when at least 80% of its values parse
    as numbers; its fill value is the training median. Otherwise it is
    one-hot encoded over the categories present in the training fold.
    """
    schema = ExogSchema()
    cap = max_exog_categories()
    for column in exog_columns:
        if column not in train_df.columns:
            continue
        values = train_df[column]
        numeric = pd.to_numeric(values, errors="coerce")
        if numeric.notna().mean() >= 0.8:
            fill = float(numeric.median()) if numeric.notna().any() else 0.0
            schema.entries.append(
                {"column": column, "kind": "numeric", "fill": fill, "features": [column]}
            )
            continue
        categories = sorted(values.dropna().astype(str).unique().tolist())
        if len(categories) > cap:
            raise ValueError(
                f"Exogenous feature {column!r} has {len(categories)} categories, "
                f"above the configured limit of {cap}. Raise "
                "FORECAST_MAX_EXOG_CATEGORIES or drop the column - silently "
                "truncating the categories would change what the model sees."
            )
        schema.entries.append(
            {
                "column": column,
                "kind": "categorical",
                "categories": categories,
                "features": [f"{column}__{index}" for index in range(len(categories))],
            }
        )
    return schema


def encode_exog(
    frame: pd.DataFrame, schema: ExogSchema, *, require_values: bool = False
) -> pd.DataFrame:
    """Apply a fitted schema. `require_values` is for horizon rows.

    With `require_values=True` a missing value raises
    `FutureExogenousUnavailable` rather than being filled: a future-known
    driver with no future value is a contradiction, and filling it would
    fabricate the very thing that makes it future-known.
    """
    encoded: dict[str, list[float]] = {name: [] for name in schema.feature_names}
    for _, row in frame.iterrows():
        for entry in schema.entries:
            column = entry["column"]
            raw = row.get(column)
            missing = raw is None or (not isinstance(raw, str) and pd.isna(raw))
            if missing and require_values:
                raise FutureExogenousUnavailable(
                    f"Future forecasting is unavailable because the future-known "
                    f"driver {column!r} has no value for a horizon row. Historical "
                    "backtesting remains valid."
                )
            if entry["kind"] == "numeric":
                parsed = pd.to_numeric(pd.Series([raw]), errors="coerce").iloc[0]
                encoded[column].append(
                    float(entry["fill"]) if pd.isna(parsed) else float(parsed)
                )
            else:
                text = None if missing else str(raw)
                for index, category in enumerate(entry["categories"]):
                    encoded[f"{column}__{index}"].append(1.0 if text == category else 0.0)
    return pd.DataFrame(encoded, index=frame.index)


def independent_exog_columns(train: pd.DataFrame) -> list[str]:
    """Sodexo's rank and collinearity guard, in the caller's column order.

    Keeps a column only if it varies, is not near-duplicate of a column already
    kept, and genuinely raises the rank of `[intercept | kept...]`. Without the
    intercept in that test the classic dummy-variable trap slips through: a set
    of one-hot columns summing to 1 is independent on its own, and only
    collinear once statsmodels adds its constant. Left in, the condition number
    explodes and the exogenous variants score *worse* than their plain
    counterparts.
    """
    kept: list[str] = []
    for column in train.columns:
        values = train[column].to_numpy(dtype=float)
        if not np.isfinite(values).all() or np.allclose(values, values[0]):
            continue
        if kept:
            correlations = [
                abs(np.corrcoef(values, train[other].to_numpy(dtype=float))[0, 1])
                for other in kept
            ]
            correlations = [c for c in correlations if not np.isnan(c)]
            if correlations and max(correlations) > MAX_EXOG_CORRELATION:
                continue
        candidate = np.column_stack(
            [np.ones(len(train)), train[[*kept, column]].to_numpy(dtype=float)]
        )
        if np.linalg.matrix_rank(candidate) < candidate.shape[1]:
            continue
        kept.append(column)
    return kept


def build_exog_pair(
    train_df: pd.DataFrame,
    output_df: pd.DataFrame,
    exog_columns: tuple[str, ...],
    *,
    standardise: bool = True,
    require_future_values: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    """Train and output exogenous matrices, plus the columns actually kept.

    `standardise=False` is XGBoost's path: both references feed it raw
    exogenous features, and tree splits do not care about scale.
    """
    if not exog_columns:
        raise ValueError("No exogenous columns were supplied.")

    schema = fit_exog_schema(train_df, exog_columns)
    if not schema.entries:
        raise ValueError(
            "None of the supplied exogenous columns is present in the training frame."
        )

    train = encode_exog(train_df, schema).astype(float)
    output = encode_exog(output_df, schema, require_values=require_future_values).astype(float)
    output = output.reindex(columns=train.columns, fill_value=0.0)

    if standardise:
        # Fitted on the training fold only - never on the validation or
        # horizon rows.
        center = train.mean(axis=0)
        scale = train.std(axis=0, ddof=0).replace(0, 1.0)
        train = (train - center) / scale
        output = (output - center) / scale
        if not np.isfinite(train.to_numpy()).all() or not np.isfinite(output.to_numpy()).all():
            raise ValueError(
                "The exogenous matrix contains non-finite values after "
                "fold-fitted standardisation."
            )
        usable = independent_exog_columns(train)
        if not usable:
            raise ValueError(
                "No exogenous driver in this window varies independently enough "
                "to regress on."
            )
        return train[usable], output[usable], usable

    return train, output, list(train.columns)

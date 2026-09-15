"""The pooled global tier: one fit that covers every series.

The per-series tiers above this one reach 69 aggregate scopes and 500 local
series. The remaining ~68,000 series are covered here, by a single XGBoost fit
on the direct multi-horizon frame - `horizon` is a feature, so one model
answers all six horizons at once.

**Why the pooled tier can even exist.** Phase 4 built a frame with one row per
(series, origin, horizon) and features that are all computable at forecast
time. A gradient-boosted tree does not care that row 3,000,000 belongs to a
different series than row 1; the series' identity enters through its own lag
and rolling features. That is what turns 68,000 fits into one.

**Where its evaluation comes from.** The persisted training frame was built with
the training cut bounding *both* origin and target, so it contains no row whose
target falls in a validation window - by construction, since that is what makes
it leakage-safe. Evaluating the pooled model therefore needs a frame built at
each origin. Rather than rebuild features (126 s for the panel), this reuses the
persisted `origin_features` artifact, which is origin-only and strictly
backward-looking, and re-derives the labels by joining the panel's actuals.

**What it is honest about.** A pooled model is a different claim from a local
one: it says "given this series' recent shape and its attributes, here is what
a series like it does next". `scope_level` is `pooled` on every row it writes,
and Phase 8 must not rank a pooled row against a per-series row as though they
were the same measurement.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandas as pd

from app.core.logging import get_logger
from app.jobs.runner import CancellationToken
from app.ml.evaluation.folds import Origin
from app.ml.evaluation.metrics import evaluate, reference_metrics
from app.ml.evaluation.quantiles import ResidualStore
from app.schemas.common import EvaluationMode, ModelRunStatus

logger = get_logger(__name__)

#: Features the pooled model reads. Everything here is known at forecast time:
#: lags and rolling statistics computed strictly before the origin, the horizon
#: itself, calendar position, and static attributes.
#:
#: `mean_mrp` is deliberately absent. It is a historical column whose future
#: value is unknown, and mapping rule R5 exists to stop exactly this promotion.
NUMERIC_FEATURES: tuple[str, ...] = (
    "lag_1", "lag_2", "lag_3", "lag_4", "lag_5", "lag_6", "lag_9", "lag_12",
    "rolling_mean_3", "rolling_std_3",
    "rolling_mean_6", "rolling_std_6",
    "rolling_mean_12", "rolling_std_12",
    "nonzero_count_6", "nonzero_count_12",
    "consecutive_zero_months", "trend_3_minus_6",
    "series_age_months", "horizon", "calendar_month", "same_month_last_year",
)

CATEGORICAL_FEATURES: tuple[str, ...] = (
    "region", "zone", "supply_hub", "tier", "product_group",
    "vehicle_category", "vehicle_age_category", "glass_type", "oem_status",
    "value_class",
)

#: Quantile levels fitted as separate objectives. These are forecast outputs,
#: never leaderboard models.
QUANTILE_ALPHAS: tuple[float, ...] = (0.80, 0.90, 0.95)


@dataclass
class PooledResult:
    model_rows: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metrics: dict[str, float | None] = field(default_factory=dict)
    summary: dict[str, Any] = field(default_factory=dict)


def run_pooled_tier(
    *,
    artifacts: dict[str, str],
    origins: Sequence[Origin],
    run_id: str,
    profile: str,
    xgboost_profile: str,
    artifact_dir: Path,
    store: ResidualStore,
    token: CancellationToken | None = None,
    max_rows: int | None = None,
) -> PooledResult:
    """Fit and evaluate the pooled model at every origin."""
    result = PooledResult()
    panel_path = artifacts.get("panel")
    features_path = artifacts.get("origin_features")
    if not panel_path or not features_path:
        result.warnings.append(
            "the panel build recorded no origin_features artifact, so the pooled "
            "tier was skipped; per-series tiers are unaffected"
        )
        return result

    try:
        import xgboost  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        result.warnings.append(
            f"xgboost is not importable ({type(exc).__name__}), so the pooled tier "
            "was skipped"
        )
        return result

    started = time.perf_counter()
    labels = pd.read_parquet(
        panel_path, columns=["series_id", "period_index", "target"]
    )
    origin_features = pd.read_parquet(features_path)
    if max_rows:
        origin_features = origin_features.head(max_rows)

    result.summary["origin_feature_rows"] = int(len(origin_features))
    result.summary["load_seconds"] = round(time.perf_counter() - started, 2)

    for origin in origins:
        if token is not None:
            token.raise_if_cancelled()
        try:
            rows = _evaluate_origin(
                origin=origin,
                origin_features=origin_features,
                labels=labels,
                xgboost_profile=xgboost_profile,
                artifact_dir=artifact_dir,
                store=store,
            )
            result.model_rows.extend(rows)
        except Exception as exc:  # noqa: BLE001 - one origin must not stop the other
            result.warnings.append(
                f"pooled origin {origin.name}: {type(exc).__name__}: {exc}"[:300]
            )
            logger.exception("pooled_origin_failed", extra={"origin": origin.name})
            result.model_rows.append(
                _row(
                    origin=origin,
                    model_id="xgboost",
                    display_name="XGBoost",
                    status=ModelRunStatus.FAILED,
                    failure_reason=f"{type(exc).__name__}: {exc}"[:500],
                )
            )

    completed = [row for row in result.model_rows if row["status"] == "completed"]
    if completed:
        result.metrics = {
            "wape": completed[0].get("wape"),
            "mae": completed[0].get("mae"),
        }
    result.summary["total_seconds"] = round(time.perf_counter() - started, 2)
    return result


def _evaluate_origin(
    *,
    origin: Origin,
    origin_features: pd.DataFrame,
    labels: pd.DataFrame,
    xgboost_profile: str,
    artifact_dir: Path,
    store: ResidualStore,
) -> list[dict[str, Any]]:
    """Train through the origin, predict its validation window, score it."""
    import xgboost as xgb

    train = _labelled_frame(
        origin_features[origin_features["period_index"] <= origin.train_end_index],
        labels=labels,
        horizons=range(1, origin.horizon + 1),
        max_target_index=origin.train_end_index,
    )
    validate = _labelled_frame(
        origin_features[origin_features["period_index"] == origin.train_end_index],
        labels=labels,
        horizons=range(1, origin.horizon + 1),
        min_target_index=origin.validation_start_index,
        max_target_index=origin.validation_end_index,
    )
    if train.empty or validate.empty:
        return [
            _row(
                origin=origin,
                model_id="xgboost",
                display_name="XGBoost",
                status=ModelRunStatus.INELIGIBLE,
                failure_reason=(
                    f"the pooled frame has {len(train)} training and "
                    f"{len(validate)} validation rows at this origin, so there is "
                    "nothing to fit or nothing to score"
                ),
            )
        ]

    x_train, encoders = _design_matrix(train, encoders=None)
    y_train = train["y"].to_numpy(dtype="float32")
    x_validate, _ = _design_matrix(validate, encoders=encoders)
    y_validate = validate["y"].to_numpy(dtype="float64")

    params = _params(xgboost_profile)
    fit_started = time.perf_counter()
    point = xgb.XGBRegressor(objective="reg:squarederror", **params)
    point.fit(x_train, y_train)
    fit_seconds = time.perf_counter() - fit_started

    predict_started = time.perf_counter()
    predictions = np.asarray(point.predict(x_validate), dtype="float64")
    predict_seconds = time.perf_counter() - predict_started

    artifact = artifact_dir / f"pooled_xgboost_{origin.name}.json"
    point.save_model(str(artifact))

    metrics = evaluate(
        y_validate.tolist(),
        predictions.tolist(),
        insample_actuals=y_train.tolist(),
    )
    legacy = reference_metrics(y_validate.tolist(), predictions.tolist())

    # Residuals feed the same store the per-series tiers use, keyed by horizon
    # and by `pooled` as the segment - a pooled model's errors are not
    # interchangeable with a local model's, so they must not pool together.
    for horizon in sorted(validate["horizon"].unique()):
        mask = validate["horizon"].to_numpy() == horizon
        store.add(
            "xgboost", int(horizon), "pooled", y_validate[mask], predictions[mask]
        )

    row = _row(
        origin=origin,
        model_id="xgboost",
        display_name="XGBoost",
        status=ModelRunStatus.COMPLETED,
    )
    row.update(
        {
            "validation_points": metrics.points,
            "total_test_points": metrics.points,
            "mae": metrics.mae,
            "rmse": metrics.rmse,
            "wape": metrics.wape,
            "mape": metrics.mape,
            "accuracy": metrics.accuracy,
            "smape": metrics.smape,
            "mase": metrics.mase,
            "bias": metrics.bias,
            "bias_abs": metrics.bias_abs,
            "naive_mae": metrics.naive_mae,
            "legacy_mape": legacy.get("mape"),
            "legacy_wape": legacy.get("wape"),
            "legacy_mae": legacy.get("mae"),
            "zero_actual_points": metrics.zero_actual_points,
            "negative_predictions": int((predictions < 0).sum()),
            "max_abs_prediction": float(np.abs(predictions).max()),
            "fit_seconds": fit_seconds,
            "predict_seconds": predict_seconds,
            "artifact_path": str(artifact),
            "parameters_json": {**params, "profile": xgboost_profile},
            "features_json": list(x_train.columns),
            "origins_json": [
                {
                    **origin.as_dict(),
                    "train_rows": int(len(train)),
                    "validation_rows": int(len(validate)),
                }
            ],
        }
    )
    return [row]


def _labelled_frame(
    frame: pd.DataFrame,
    *,
    labels: pd.DataFrame,
    horizons: Any,
    min_target_index: int | None = None,
    max_target_index: int | None = None,
) -> pd.DataFrame:
    """Expand origins to (origin, horizon) rows and attach the actual.

    The label is joined on `(series_id, origin + horizon)`, so a row's `y` is
    by construction the value of the month it claims to forecast. Bounding by
    `max_target_index` is what keeps a training row from carrying a target the
    origin could not have known.
    """
    if frame.empty:
        return pd.DataFrame()

    expanded = frame.loc[frame.index.repeat(len(list(horizons)))].copy()
    expanded["horizon"] = list(horizons) * len(frame)
    expanded["_target_index"] = expanded["period_index"] + expanded["horizon"]

    if min_target_index is not None:
        expanded = expanded[expanded["_target_index"] >= min_target_index]
    if max_target_index is not None:
        expanded = expanded[expanded["_target_index"] <= max_target_index]
    if expanded.empty:
        return pd.DataFrame()

    merged = expanded.merge(
        labels.rename(columns={"period_index": "_target_index", "target": "y"}),
        on=["series_id", "_target_index"],
        how="inner",
    )
    return merged


def _design_matrix(
    frame: pd.DataFrame, *, encoders: dict[str, dict[Any, int]] | None
) -> tuple[pd.DataFrame, dict[str, dict[Any, int]]]:
    """Numeric features plus integer-coded categoricals.

    Categoricals are coded from the **training** fold's vocabulary and an
    unseen level at scoring time becomes `-1`, a value the tree can split on.
    Re-fitting the encoding on the validation fold would leak the fold's
    composition into its own features.
    """
    resolved: dict[str, dict[Any, int]] = {} if encoders is None else encoders
    columns: dict[str, Any] = {}

    for name in NUMERIC_FEATURES:
        if name in frame.columns:
            columns[name] = pd.to_numeric(frame[name], errors="coerce").astype("float32")

    for name in CATEGORICAL_FEATURES:
        if name not in frame.columns:
            continue
        values = frame[name].astype("object")
        if encoders is None:
            vocabulary = {
                level: index
                for index, level in enumerate(sorted(map(str, values.dropna().unique())))
            }
            resolved[name] = vocabulary
        else:
            vocabulary = resolved.get(name, {})
        columns[name] = (
            values.map(lambda level: vocabulary.get(str(level), -1))
            .fillna(-1)
            .astype("int32")
        )

    return pd.DataFrame(columns, index=frame.index), resolved


def _params(profile: str) -> dict[str, Any]:
    """Sodexo's fast profile, or Meriton's thorough one scaled for pooled size.

    A `GridSearchCV` over 3.9 M rows is not affordable and is not what Meriton
    was doing either - its grid ran on a few hundred rows. So `thorough` here
    means more trees and a deeper interaction, not a search: claiming a grid
    search that never ran would be worse than saying which fixed parameters
    were used.
    """
    if profile == "fast":
        return {
            "n_estimators": 120,
            "max_depth": 5,
            "learning_rate": 0.1,
            "tree_method": "hist",
            "n_jobs": 8,
            "random_state": 42,
        }
    return {
        "n_estimators": 300,
        "max_depth": 7,
        "learning_rate": 0.07,
        "subsample": 0.9,
        "colsample_bytree": 0.9,
        "min_child_weight": 5,
        "tree_method": "hist",
        "n_jobs": 8,
        "random_state": 42,
    }


def _row(
    *,
    origin: Origin,
    model_id: str,
    display_name: str,
    status: ModelRunStatus,
    failure_reason: str | None = None,
) -> dict[str, Any]:
    return {
        "tier": "pooled",
        "scope_level": "pooled",
        "scope_key": f"ALL_SERIES@{origin.name}",
        "segment": "pooled",
        "model_id": model_id,
        "display_name": display_name,
        "is_baseline": False,
        "status": status.value,
        "evaluation_mode": EvaluationMode.HOLDOUT_FALLBACK.value,
        "failure_reason": failure_reason,
        "origins_completed": 1 if status is ModelRunStatus.COMPLETED else 0,
        "origins_total": 1,
    }

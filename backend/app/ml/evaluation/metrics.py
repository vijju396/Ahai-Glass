"""Forecast accuracy metrics.

Two functions compute point-forecast error, and they are deliberately separate:

- `reference_metrics` is a **parity port**. Meriton's `metrics_service.py:7-41`
  and Sodexo's `metrics.py:9-43` are byte-identical to each other; this
  reproduces their six values, their `None` semantics, their `* 100` scaling and
  their `round(..., 2)`. It exists so the "legacy parity result" on the
  leaderboard (`docs/DECISIONS.md` D-011) is genuinely what the references would
  have reported, not a lookalike.
- `evaluate` is the **AIS metric set**: the reference six plus sMAPE, MASE,
  pinball loss and interval coverage, which neither reference implements
  (D-012). It does not round, because rounding belongs at the presentation
  boundary, and it returns `None` rather than a sentinel wherever a metric is
  genuinely undefined.

**Why `None` and not zero.** 62% of AIS series are intermittent. A validation
window in which every actual is zero has no defined WAPE - the denominator is
zero - and reporting `0.0` there would read as a perfect forecast while
reporting `100.0` would read as a total miss. Both are lies about a window that
simply cannot discriminate. The same applies to MAPE (which drops zero actuals
entirely, so it is frequently undefined here) and to MASE when the naive
benchmark makes no error at all.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from statistics import mean
from typing import Any, Iterable, Sequence

import numpy as np

#: Quantile levels AIS reports. Outputs, never models.
QUANTILE_LEVELS: tuple[float, ...] = (0.80, 0.90, 0.95)

#: The six values both reference projects report, in their order.
REFERENCE_METRIC_KEYS: tuple[str, ...] = (
    "mape",
    "accuracy",
    "mae",
    "rmse",
    "wape",
    "bias",
)


# ----------------------------------------------------------------------
# Reference parity
# ----------------------------------------------------------------------


def reference_metrics(
    actuals: Iterable[Any], predictions: Iterable[Any]
) -> dict[str, float | None]:
    """Exactly what Meriton and Sodexo compute, including their quirks.

    Ported from Meriton `services/metrics_service.py:7-41` and Sodexo
    `backend_sodexo/app/services/forecasting/metrics.py:9-43`, which are
    identical to each other. Verified line by line, and
    `tests/test_metrics.py` re-checks it against an independent transcription
    rather than against this implementation.

    Quirks preserved on purpose, because parity is the point:

    - MAPE drops zero actuals and is `None` if every actual is zero.
    - `accuracy` is `max(100 - mape, 0)`. It is a MAPE restatement, not an
      accuracy in any general sense, and is labelled as such wherever shown.
    - WAPE and bias divide by the **signed** sum of actuals and are `None` when
      that sum is zero.
    - Every value is rounded to 2 decimal places.
    - Pairs where either side is None or NaN are dropped, silently, as both
      references do.
    """
    pairs: list[tuple[float, float]] = []
    for actual, predicted in zip(actuals, predictions):
        actual_value = _reference_to_float(actual)
        predicted_value = _reference_to_float(predicted)
        if actual_value is not None and predicted_value is not None:
            pairs.append((actual_value, predicted_value))

    if not pairs:
        return dict.fromkeys(REFERENCE_METRIC_KEYS, None)

    abs_errors = [abs(actual - predicted) for actual, predicted in pairs]
    squared_errors = [(actual - predicted) ** 2 for actual, predicted in pairs]
    nonzero_pairs = [(a, p) for a, p in pairs if a != 0]
    total_actual = sum(actual for actual, _ in pairs)

    mape = (
        mean(abs((a - p) / a) for a, p in nonzero_pairs) * 100 if nonzero_pairs else None
    )
    mae = mean(abs_errors)
    rmse = math.sqrt(mean(squared_errors))
    wape = (sum(abs_errors) / total_actual * 100) if total_actual else None
    bias = (sum(p - a for a, p in pairs) / total_actual * 100) if total_actual else None
    accuracy = max(100 - mape, 0) if mape is not None else None

    return {
        "mape": _round_or_none(mape),
        "accuracy": _round_or_none(accuracy),
        "mae": _round_or_none(mae),
        "rmse": _round_or_none(rmse),
        "wape": _round_or_none(wape),
        "bias": _round_or_none(bias),
    }


def is_valid_metric(row: dict[str, Any]) -> bool:
    """Sodexo `metrics.py:46-53` / Meriton `metrics_service.py:49-56`, verbatim.

    Governs eligibility for the **legacy parity ranking only**. It requires a
    finite MAPE, so on AIS data it rejects most intermittent series - which is
    precisely why WAPE is the primary metric and this ranking is labelled
    separately (D-011).
    """
    if not isinstance(row, dict) or str(row.get("status", "")).lower() == "failed":
        return False
    values = [_reference_to_float(row.get(key)) for key in ("mape", "mae", "rmse")]
    if any(value is None or not math.isfinite(value) for value in values):
        return False
    mape, mae, rmse = values
    return 0 <= mape <= 1000 and 0 <= mae <= 1e12 and 0 <= rmse <= 1e12


# ----------------------------------------------------------------------
# The AIS metric set
# ----------------------------------------------------------------------


@dataclass
class MetricSet:
    """Every metric AIS reports, plus the counts needed to interpret them.

    `points` is the number of usable actual/prediction pairs. A metric computed
    on two points is not comparable with one computed on twelve, so the count
    travels with the values rather than being reconstructed later.
    """

    points: int = 0
    dropped_points: int = 0
    zero_actual_points: int = 0
    censored_points: int = 0
    sum_actual: float | None = None

    mae: float | None = None
    rmse: float | None = None
    wape: float | None = None
    mape: float | None = None
    accuracy: float | None = None
    smape: float | None = None
    mase: float | None = None
    bias: float | None = None
    bias_abs: float | None = None

    naive_mae: float | None = None
    pinball: dict[str, float | None] = field(default_factory=dict)
    coverage: dict[str, float | None] = field(default_factory=dict)

    undefined: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "points": self.points,
            "dropped_points": self.dropped_points,
            "zero_actual_points": self.zero_actual_points,
            "censored_points": self.censored_points,
            "sum_actual": self.sum_actual,
            "mae": self.mae,
            "rmse": self.rmse,
            "wape": self.wape,
            "mape": self.mape,
            "accuracy": self.accuracy,
            "smape": self.smape,
            "mase": self.mase,
            "bias": self.bias,
            "bias_abs": self.bias_abs,
            "naive_mae": self.naive_mae,
            "pinball": dict(self.pinball),
            "coverage": dict(self.coverage),
            "undefined": dict(self.undefined),
        }


def evaluate(
    actuals: Sequence[Any],
    predictions: Sequence[Any],
    *,
    insample_actuals: Sequence[Any] | None = None,
    seasonal_period: int | None = None,
    quantile_predictions: dict[float, Sequence[Any]] | None = None,
    censored: Sequence[Any] | None = None,
) -> MetricSet:
    """The AIS metric set for one model on one validation window.

    `insample_actuals` is the **training** target of the same fold and is what
    MASE's denominator is computed from. Passing the validation actuals instead
    would make MASE self-referential, so the argument is separate and named for
    what it is.

    `censored` marks actuals that are lower bounds rather than observations
    (an order line despatched short). Those points are still scored - excluding
    them would bias the metric toward easy months - but they are counted, so a
    window whose actuals are largely censored can be read with that in mind.
    """
    a_raw = [_to_float(v) for v in actuals]
    p_raw = [_to_float(v) for v in predictions]
    keep = [i for i, (a, p) in enumerate(zip(a_raw, p_raw)) if a is not None and p is not None]

    result = MetricSet(
        points=len(keep),
        dropped_points=max(len(a_raw), len(p_raw)) - len(keep),
    )
    if not keep:
        result.undefined["all"] = "no actual/prediction pair was usable"
        return result

    a = np.asarray([a_raw[i] for i in keep], dtype=float)
    p = np.asarray([p_raw[i] for i in keep], dtype=float)
    errors = p - a
    abs_errors = np.abs(errors)

    result.zero_actual_points = int((a == 0).sum())
    if censored is not None:
        flags = list(censored)
        result.censored_points = int(
            sum(1 for i in keep if i < len(flags) and bool(flags[i]))
        )

    # Scale for the weighted metrics. `abs` rather than the references' signed
    # sum: a signed denominator can be driven toward zero by cancellation and
    # produce an absurd percentage. The two agree exactly whenever actuals are
    # non-negative, which ordered quantity is - so this is a robustness change,
    # not a different measurement, and `reference_metrics` keeps the signed form
    # for parity.
    scale = float(np.abs(a).sum())
    result.sum_actual = float(a.sum())

    result.mae = float(abs_errors.mean())
    result.rmse = float(math.sqrt(float((errors**2).mean())))

    if scale > 0:
        result.wape = float(abs_errors.sum() / scale * 100)
        result.bias = float(errors.sum() / scale * 100)
        result.bias_abs = abs(result.bias)
    else:
        result.undefined["wape"] = (
            "every actual in the window is zero, so there is no scale to divide "
            "by; a percentage error is undefined rather than 0 or 100"
        )
        result.undefined["bias"] = result.undefined["wape"]

    nonzero = a != 0
    if nonzero.any():
        result.mape = float((abs_errors[nonzero] / np.abs(a[nonzero])).mean() * 100)
        result.accuracy = max(100.0 - result.mape, 0.0)
    else:
        result.undefined["mape"] = (
            "MAPE drops zero actuals and every actual here is zero"
        )
        result.undefined["accuracy"] = result.undefined["mape"]

    result.smape = _smape(a, p)
    result.mase, result.naive_mae, mase_note = _mase(
        result.mae, insample_actuals, seasonal_period
    )
    if mase_note:
        result.undefined["mase"] = mase_note

    if quantile_predictions:
        for level, values in sorted(quantile_predictions.items()):
            q = np.asarray([_to_float(v) for v in values], dtype=float)
            if len(q) != len(a_raw):
                result.undefined[f"q{int(level * 100)}"] = (
                    f"quantile series has {len(q)} values for {len(a_raw)} actuals"
                )
                continue
            q = q[keep]
            usable = ~np.isnan(q)
            key = f"q{int(level * 100)}"
            if not usable.any():
                result.pinball[key] = None
                result.coverage[key] = None
                continue
            result.pinball[key] = _pinball(a[usable], q[usable], level)
            result.coverage[key] = float((a[usable] <= q[usable]).mean() * 100)

    return result


def _smape(a: np.ndarray, p: np.ndarray) -> float | None:
    """Symmetric MAPE, as a percentage.

    Where `|a| + |p| == 0` the term is 0: a zero actual forecast as exactly
    zero is a correct forecast, and dropping the point instead would quietly
    exclude the majority of an intermittent series' months. The convention is
    stated here because implementations differ on it.
    """
    denominator = np.abs(a) + np.abs(p)
    terms = np.zeros_like(denominator, dtype=float)
    nonzero = denominator > 0
    terms[nonzero] = 2.0 * np.abs(a[nonzero] - p[nonzero]) / denominator[nonzero]
    if not len(terms):
        return None
    return float(terms.mean() * 100)


def _mase(
    mae: float | None,
    insample_actuals: Sequence[Any] | None,
    seasonal_period: int | None,
) -> tuple[float | None, float | None, str | None]:
    """MASE against a naive benchmark fitted on the training fold only.

    The denominator is the in-sample MAE of a one-step naive forecast - the
    seasonal naive when a period is supplied and the training window is long
    enough for it. Computing it from the *training* fold is what keeps MASE
    leakage-safe; computing it from the validation window would compare a model
    against a benchmark that had seen the answers.
    """
    if mae is None:
        return None, None, "MAE is undefined, so MASE is too"
    if insample_actuals is None:
        return None, None, "no in-sample window was supplied for the benchmark"

    values = np.asarray(
        [v for v in (_to_float(x) for x in insample_actuals) if v is not None],
        dtype=float,
    )
    lag = seasonal_period if seasonal_period and len(values) > seasonal_period else 1
    if len(values) <= lag:
        return None, None, (
            f"the in-sample window has {len(values)} usable months, too few for a "
            f"lag-{lag} naive benchmark"
        )

    naive_mae = float(np.abs(values[lag:] - values[:-lag]).mean())
    if naive_mae <= 0:
        return None, naive_mae, (
            "the naive benchmark makes no error on the training window (a "
            "constant series), so a ratio to it is undefined rather than infinite"
        )
    return float(mae / naive_mae), naive_mae, None


def _pinball(a: np.ndarray, q: np.ndarray, level: float) -> float:
    """Mean pinball (quantile) loss at `level`.

    Under-forecasting is penalised by `level` and over-forecasting by
    `1 - level`, so at q95 a shortfall costs nineteen times an equivalent
    excess - which is the asymmetry a service-level target is asking for.
    """
    difference = a - q
    return float(np.mean(np.maximum(level * difference, (level - 1.0) * difference)))


def _reference_to_float(value: Any) -> float | None:
    """The references' own coercion, quirk included.

    Meriton `metrics_service.py:_to_float` / Sodexo `metrics.py:64-72` reject
    NaN but let `±inf` through, so an infinite prediction propagates into their
    MAE. AIS's own `_to_float` rejects both - but the parity function must use
    this one, or it is not parity. In practice the adapters map `±inf` to NaN
    before metrics are computed (`base.py` output cleaning, Sodexo
    `models.py:80-84`), so the difference is a contract detail rather than a
    live divergence.
    """
    if value is None:
        return None
    try:
        if math.isnan(float(value)):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_float(value: Any) -> float | None:
    """AIS's coercion: NaN *and* infinity are unusable, not merely NaN."""
    if value is None:
        return None
    try:
        as_float = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(as_float) or math.isinf(as_float):
        return None
    return as_float


def _round_or_none(value: float | None) -> float | None:
    return round(value, 2) if value is not None else None

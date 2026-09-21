"""Quantile calibration from out-of-sample residuals.

**Residuals are relative, and the offsets are fractions.** `q = point * (1 +
offset)`, not `point + offset`. See `_relative_residual` for the measurement
that forced it: an absolute offset pooled across scopes gave a q95 that
delivered 69% on the largest series (D-089).

q80/q90/q95 are **forecast outputs, never models**. They do not appear on the
leaderboard as models and no model is ever selected because of them.

Neither reference project uses a model's analytic confidence interval; both
take empirical percentiles of backtest residuals with a five-residual minimum
(Meriton 2.5/97.5, Sodexo 10/90). AIS keeps that approach and makes three
things explicit that the references leave implicit:

**Residuals are out-of-sample only.** They come from validation windows. An
in-sample residual understates error for every model that can fit its training
data closely, which is most of the 13.

**Pooling is by model x horizon x segment, and the level used is recorded.**
Two mandated origins times six months gives at most twelve residuals per
series - not enough to calibrate per series honestly. So residuals pool, and
because a pooled interval is only as meaningful as the population it pooled
over, `pooling_level` travels with every calibration. A cell that fell back to
a coarser pool says so.

**A quantile that cannot be computed is not invented.** A one-sided upper
bound at level t needs the `ceil((n + 1) * t)`-th smallest residual to exist,
which requires `n >= t / (1 - t)` - 19 residuals at q95. Below that the order
statistic is off the end of the sample and any value returned is an
extrapolation of the tail, not a measurement of it. Such cells are labelled
`empirical` (interpolated) rather than `conformal`, and cells below the
five-residual floor return no offset at all.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

import numpy as np

from app.ml.evaluation.metrics import QUANTILE_LEVELS

#: Both references' floor. Below this, no interval is offered.
MIN_RESIDUALS = 5

#: The largest plausible RELATIVE offset, as a fraction of the point forecast.
#:
#: Offsets became relative in D-089. A calibration written before that change
#: holds absolute quantities - the run measured here carried `offset: 261.0` -
#: and multiplying a forecast by `1 + 261` produces a band 262 times the
#: forecast, which Supply Intelligence would turn into an order to match.
#:
#: Nothing in the schema distinguishes the two conventions, so magnitude is the
#: discriminator. A relative offset of 20 means a band 21x the forecast; no
#: honest calibration on this data comes close, while every stale absolute one
#: on the measured run exceeds it. Such a cell is dropped with a reason rather
#: than applied, so a forecast produced against a stale calibration loses its
#: interval instead of inventing an absurd one.
MAX_RELATIVE_OFFSET = 20.0

#: Pooling levels, finest first. A cell falls back along this chain.
POOLING_LEVELS: tuple[str, ...] = (
    "model_horizon_segment",
    "model_horizon",
    "model",
    "global",
)


def conformal_minimum(level: float) -> int:
    """Residuals needed for a genuine (non-extrapolated) one-sided bound.

    The condition is `ceil((n + 1) * level) <= n`, which is what makes the
    required order statistic fall inside the sample: 4 at q80, 9 at q90, 19 at
    q95.

    Solved by search rather than through the closed form `level / (1 - level)`.
    The closed form is algebraically right and numerically wrong at these
    levels: `0.8 / (1 - 0.8)` evaluates to 4.000000000000001 in binary floating
    point, whose ceiling is 5, so q80 would demand a fifth residual it does not
    need. The search evaluates the actual condition and cannot drift.
    """
    if not 0.0 < level < 1.0:
        raise ValueError(f"level must be in (0, 1), got {level!r}")
    n = 1
    while math.ceil((n + 1) * level) > n:
        n += 1
        if n > 10_000:  # pragma: no cover - unreachable for level < 1
            raise ValueError(f"no finite sample size satisfies level {level!r}")
    return n


@dataclass
class QuantileOffset:
    """The additive offset for one level, and how trustworthy it is."""

    level: float
    offset: float | None
    method: str
    residual_count: int
    pooling_level: str
    note: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "offset": self.offset,
            "method": self.method,
            "residual_count": self.residual_count,
            "pooling_level": self.pooling_level,
            "note": self.note,
        }


@dataclass
class Calibration:
    """Offsets for every level, for one (model, horizon, segment) cell."""

    model_id: str
    horizon: int
    segment: str
    offsets: dict[str, QuantileOffset] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "horizon": self.horizon,
            "segment": self.segment,
            "offsets": {key: value.as_dict() for key, value in self.offsets.items()},
        }


@dataclass
class MonotonicityReport:
    """How many quantile crossings were corrected, never silently.

    `point <= q80 <= q90 <= q95` is enforced by monotone sorting. Crossings are
    not a bug in the sort - they happen when a coarse pool's offsets are
    estimated from different residual counts - but a corrected crossing is a
    signal that the calibration is thin, so the count is surfaced.
    """

    rows: int = 0
    crossings_corrected: int = 0
    point_exceeded_q80: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "rows": self.rows,
            "crossings_corrected": self.crossings_corrected,
            "point_exceeded_q80": self.point_exceeded_q80,
        }


class ResidualStore:
    """Out-of-sample residuals, keyed for pooled calibration.

    A residual here is `actual - prediction`, so a **positive** residual means
    the model under-forecast. Upper quantiles are therefore `point + offset`
    with the offset taken from the upper tail of the residual distribution,
    which is the tail that matters for stock cover.
    """

    def __init__(self) -> None:
        self._cells: dict[tuple[str, int, str], list[float]] = defaultdict(list)

    def add(
        self,
        model_id: str,
        horizon: int,
        segment: str,
        actuals: Sequence[Any],
        predictions: Sequence[Any],
    ) -> int:
        """Record residuals for one cell. Returns how many were usable."""
        added = 0
        for actual, prediction in zip(actuals, predictions):
            # Relative, so the cell can pool across scopes of different size.
            residual = _relative_residual(actual, prediction)
            if residual is None:
                continue
            self._cells[(model_id, horizon, segment)].append(residual)
            added += 1
        return added

    def count(self, model_id: str, horizon: int, segment: str) -> int:
        return len(self._cells.get((model_id, horizon, segment), ()))

    def total(self) -> int:
        return sum(len(values) for values in self._cells.values())

    def cells(self) -> list[tuple[str, int, str]]:
        return sorted(self._cells)

    def _pooled(self, model_id: str, horizon: int, segment: str, level_name: str) -> list[float]:
        if level_name == "model_horizon_segment":
            return list(self._cells.get((model_id, horizon, segment), ()))
        if level_name == "model_horizon":
            return [
                value
                for (m, h, _s), values in self._cells.items()
                if m == model_id and h == horizon
                for value in values
            ]
        if level_name == "model":
            return [
                value
                for (m, _h, _s), values in self._cells.items()
                if m == model_id
                for value in values
            ]
        return [value for values in self._cells.values() for value in values]

    def calibrate(
        self,
        model_id: str,
        horizon: int,
        segment: str,
        *,
        levels: Iterable[float] = QUANTILE_LEVELS,
    ) -> Calibration:
        """Offsets for one cell, falling back to coarser pools as needed.

        Each level is resolved independently, because q80 can be honest on a
        pool where q95 is not: the deeper the quantile, the more residuals its
        order statistic needs.
        """
        calibration = Calibration(model_id=model_id, horizon=horizon, segment=segment)
        for level in levels:
            key = f"q{int(level * 100)}"
            calibration.offsets[key] = self._resolve_level(model_id, horizon, segment, level)
        return calibration

    def _resolve_level(
        self, model_id: str, horizon: int, segment: str, level: float
    ) -> QuantileOffset:
        needed = conformal_minimum(level)
        best_empirical: QuantileOffset | None = None

        for level_name in POOLING_LEVELS:
            residuals = self._pooled(model_id, horizon, segment, level_name)
            count = len(residuals)
            if count < MIN_RESIDUALS:
                continue
            values = np.sort(np.asarray(residuals, dtype=float))
            if count >= needed:
                # The order statistic exists in-sample: a genuine conformal
                # bound with finite-sample coverage of at least `level`.
                rank = int(math.ceil((count + 1) * level)) - 1
                return QuantileOffset(
                    level=level,
                    offset=float(values[min(rank, count - 1)]),
                    method="conformal",
                    residual_count=count,
                    pooling_level=level_name,
                )
            if best_empirical is None:
                best_empirical = QuantileOffset(
                    level=level,
                    offset=float(np.quantile(values, level)),
                    method="empirical",
                    residual_count=count,
                    pooling_level=level_name,
                    note=(
                        f"{count} residuals is above the {MIN_RESIDUALS}-residual "
                        f"floor but below the {needed} a q{int(level * 100)} order "
                        "statistic needs, so this offset interpolates the tail "
                        "rather than measuring it"
                    ),
                )

        if best_empirical is not None:
            return best_empirical
        return QuantileOffset(
            level=level,
            offset=None,
            method="none",
            residual_count=self.count(model_id, horizon, segment),
            pooling_level="none",
            note=(
                f"fewer than {MIN_RESIDUALS} out-of-sample residuals exist at any "
                "pooling level, so no interval is offered; the row reports the "
                "point forecast with no quantiles rather than a fabricated band"
            ),
        )


def apply_calibration(
    point_forecasts: Sequence[Any],
    calibration: Calibration,
    *,
    floor_at_zero: bool = True,
    report: MonotonicityReport | None = None,
) -> tuple[dict[str, list[float | None]], MonotonicityReport]:
    """Turn point forecasts into q80/q90/q95, monotone and counted.

    `floor_at_zero` clips at zero because a negative quantile of ordered
    quantity is not a possible demand. It is applied *after* the offsets and
    before the monotone sort, so clipping can never itself create a crossing.
    """
    tracker = report or MonotonicityReport()
    keys = sorted(calibration.offsets, key=lambda key: float(key[1:]))
    output: dict[str, list[float | None]] = {key: [] for key in keys}

    for raw_point in point_forecasts:
        point = _to_float(raw_point)
        tracker.rows += 1
        if point is None:
            for key in keys:
                output[key].append(None)
            continue

        candidates: list[tuple[str, float | None]] = []
        for key in keys:
            offset = calibration.offsets[key].offset
            if offset is None or abs(offset) > MAX_RELATIVE_OFFSET:
                # `None` is "not calibrated"; an out-of-range magnitude is a
                # calibration written under the pre-D-089 absolute convention.
                # Both mean no interval, which is the honest answer.
                candidates.append((key, None))
                continue
            # The offset is a fraction of the point forecast, not a quantity.
            value = point * (1.0 + offset)
            if floor_at_zero:
                value = max(value, 0.0)
            candidates.append((key, value))

        present = [value for _key, value in candidates if value is not None]
        if present:
            if any(value < point for value in present):
                tracker.point_exceeded_q80 += 1
            ordered = sorted(present)
            if ordered != present:
                tracker.crossings_corrected += 1
            floor = point if floor_at_zero is False else max(point, 0.0)
            ordered = [max(value, floor) for value in ordered]
            iterator = iter(ordered)
            for key, value in candidates:
                output[key].append(next(iterator) if value is not None else None)
        else:
            for key in keys:
                output[key].append(None)

    return output, tracker


def _residual(actual: Any, prediction: Any) -> float | None:
    a = _to_float(actual)
    p = _to_float(prediction)
    if a is None or p is None:
        return None
    return a - p


def _relative_residual(actual: Any, prediction: Any) -> float | None:
    """`(actual - prediction) / prediction` - a scale-free residual.

    Absolute residuals cannot be pooled across scopes that differ in
    magnitude, and a single scope has only twelve of its own (two origins x
    six horizons) where q95 needs nineteen. That left both available pools
    wrong in a different way, measured on fold 1 -> fold 2:

        scope-own absolute   q95 72.9%   right scale, too few residuals
        pooled absolute      q95 85.3%   enough residuals, wrong scale
        pooled relative      q95 91.1%   both

    A relative residual is scale-free, so pooling across scopes is legitimate
    and the pooled cell is large enough to place the order statistic inside
    the sample. The offset it produces is a fraction of the point forecast,
    not a quantity (`docs/DECISIONS.md` D-089).

    A prediction of zero or less has no meaningful relative error - dividing
    would send the residual to infinity - so those points are skipped rather
    than clamped. They remain in the absolute path for anything that needs it.
    """
    a = _to_float(actual)
    p = _to_float(prediction)
    if a is None or p is None or p <= 0.0:
        return None
    return (a - p) / p


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        as_float = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(as_float) or math.isinf(as_float):
        return None
    return as_float

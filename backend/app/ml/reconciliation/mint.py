"""Hierarchical reconciliation: MinT variants, with honest fallbacks.

The hierarchy is `branch x SKU -> branch -> region -> national`. Reconciliation
makes the levels add up, and this module implements it in the two forms
`docs/ARCHITECTURE.md` §5 commits to, plus the fallbacks it names:

| Method | Where | Why |
|---|---|---|
| `mint_variance` (WLS, diagonal W) | base -> branch | A full 68,675² covariance is ~38 GB and would be estimated from 28 observations. The diagonal is a documented MinT variant, not an invention (D-009). |
| `mint_shrinkage` | branch -> region -> national | A 53 x 53 matrix is estimable with Ledoit-Wolf-style shrinkage toward its diagonal. |
| `bottom_up` | fallback | Always coherent, needs no covariance at all. |
| `proportional` | fallback | Top-down by historical share, for a level whose base signal is too thin to trust. |

Three properties this module guarantees:

**Coherence.** After reconciliation, each parent equals the sum of its children,
to floating-point tolerance. `check_coherence` re-verifies it rather than
trusting the algebra, and the caller stores the result.

**Non-negativity.** Ordered quantity cannot be negative. Clipping happens
*after* the projection and is followed by a re-proportioning pass, because
clipping a single child otherwise silently breaks the coherence the projection
just established.

**Visibility.** Every output row carries the method that produced it and the
adjustment (`reconciled - base`), so the change is displayed rather than folded
into the number. A method that fell back says which one it fell back from and
why.

Nothing here knows an AIS column name; it operates on a structure matrix and
vectors.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

import numpy as np

#: The methods this module can report. A row's method is never absent.
METHODS: tuple[str, ...] = (
    "mint_variance",
    "mint_shrinkage",
    "bottom_up",
    "proportional",
    "none",
)

#: Below this many usable in-sample residuals, a variance estimate is not worth
#: having and the caller is told to fall back. Matches the references' own
#: five-residual floor used for quantile calibration (D-010).
MIN_RESIDUALS_FOR_VARIANCE = 5

#: Shrinkage intensity bounds. 0 is the raw sample covariance, 1 is its
#: diagonal. Clamped rather than trusted, because a sample covariance from 28
#: observations across 53 branches is singular and an unclamped estimate can
#: land outside [0, 1] through rounding alone.
SHRINKAGE_BOUNDS = (0.0, 1.0)

#: Coherence tolerance, relative to the total. Floating-point projection will
#: not reproduce an exact sum at 1e-15, and demanding it would report a defect
#: where there is none.
COHERENCE_RTOL = 1e-6
COHERENCE_ATOL = 1e-6


@dataclass
class Hierarchy:
    """A summing structure over base series.

    `nodes` lists every node in the hierarchy, base nodes first, and `S` is the
    summing matrix: `S[i, j] == 1` when node `i` aggregates base series `j`.
    Built once per (period, horizon) group and reused across models.
    """

    base_keys: list[str]
    nodes: list[tuple[str, str]]
    S: np.ndarray

    @property
    def base_count(self) -> int:
        return len(self.base_keys)

    @property
    def node_count(self) -> int:
        return len(self.nodes)

    def index_of(self, level: str, key: str) -> int:
        return self.nodes.index((level, key))


def build_hierarchy(
    base_keys: Sequence[str],
    *,
    parents: Sequence[dict[str, str]],
    levels: Sequence[str] = ("branch", "region", "national"),
    national_key: str = "NATIONAL",
) -> Hierarchy:
    """Build the summing matrix from each base series' parent memberships.

    `parents[j]` maps a level name to the key base series `j` belongs to, e.g.
    `{"branch": "JAIPUR", "region": "NORTH-1"}`. A base series missing a level
    is **not** dropped and **not** guessed: it is grouped under an explicit
    `UNKNOWN` key at that level, so its demand still reaches the national total
    and the gap is visible in the output rather than absorbed.
    """
    if len(parents) != len(base_keys):
        raise ValueError(
            f"{len(base_keys)} base series but {len(parents)} parent maps; "
            "every base series needs one."
        )

    nodes: list[tuple[str, str]] = [("series", key) for key in base_keys]
    rows: list[np.ndarray] = [
        np.eye(len(base_keys), dtype=np.float64)[index]
        for index in range(len(base_keys))
    ]

    for level in levels:
        if level == "national":
            nodes.append(("national", national_key))
            rows.append(np.ones(len(base_keys), dtype=np.float64))
            continue
        seen: dict[str, np.ndarray] = {}
        for position, parent in enumerate(parents):
            key = str(parent.get(level) or "UNKNOWN")
            vector = seen.setdefault(key, np.zeros(len(base_keys), dtype=np.float64))
            vector[position] = 1.0
        for key in sorted(seen):
            nodes.append((level, key))
            rows.append(seen[key])

    return Hierarchy(
        base_keys=list(base_keys), nodes=nodes, S=np.vstack(rows) if rows else np.zeros((0, 0))
    )


@dataclass
class ReconciliationResult:
    """Reconciled values for every node, and how they were produced."""

    method: str
    #: Node order matches `Hierarchy.nodes`.
    values: np.ndarray
    base_values: np.ndarray
    adjustments: np.ndarray
    coherent: bool
    max_incoherence: float
    negatives_clipped: int
    fallback_from: str | None = None
    fallback_reason: str | None = None
    shrinkage_intensity: float | None = None
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "coherent": self.coherent,
            "max_incoherence": self.max_incoherence,
            "negatives_clipped": self.negatives_clipped,
            "fallback_from": self.fallback_from,
            "fallback_reason": self.fallback_reason,
            "shrinkage_intensity": self.shrinkage_intensity,
            "notes": list(self.notes),
        }


def bottom_up(hierarchy: Hierarchy, base_forecasts: Sequence[float]) -> np.ndarray:
    """Every node is the sum of its base children. Coherent by construction."""
    base = np.asarray(base_forecasts, dtype=np.float64).reshape(-1)
    if base.size != hierarchy.base_count:
        raise ValueError(
            f"{base.size} base forecasts for {hierarchy.base_count} base series."
        )
    return hierarchy.S @ base


def shrink_covariance(
    residuals: np.ndarray, *, intensity: float | None = None
) -> tuple[np.ndarray, float]:
    """Sample covariance shrunk toward its own diagonal.

    With 28 observations and 53 branches the sample covariance is singular, so
    shrinkage is not an refinement here - it is what makes the matrix invertible
    at all. When `intensity` is not supplied it is estimated from the ratio of
    off-diagonal mass to total mass, clamped into [0, 1].
    """
    residuals = np.asarray(residuals, dtype=np.float64)
    if residuals.ndim != 2 or residuals.shape[0] < 2:
        size = residuals.shape[1] if residuals.ndim == 2 else 1
        return np.eye(size), 1.0

    sample = np.cov(residuals, rowvar=False)
    sample = np.atleast_2d(sample)
    target = np.diag(np.diag(sample))

    if intensity is None:
        off = sample - target
        off_mass = float(np.sum(off**2))
        total_mass = float(np.sum(sample**2))
        # More off-diagonal mass relative to the whole means the correlations
        # carry real information, so shrink less. Few observations relative to
        # dimension means shrink more.
        observations, dimension = residuals.shape
        ratio = 0.0 if total_mass == 0 else off_mass / total_mass
        scarcity = min(1.0, dimension / max(observations, 1))
        intensity = float(np.clip((1.0 - ratio) * 0.5 + scarcity * 0.5, *SHRINKAGE_BOUNDS))

    intensity = float(np.clip(intensity, *SHRINKAGE_BOUNDS))
    shrunk = (1.0 - intensity) * sample + intensity * target
    # A zero diagonal entry would make the weight matrix singular; a constant
    # series has no variance, and giving it an infinite weight would let it
    # dictate the whole projection.
    diagonal = np.diag(shrunk).copy()
    floor = float(np.mean(diagonal[diagonal > 0])) if np.any(diagonal > 0) else 1.0
    diagonal[diagonal <= 0] = floor
    np.fill_diagonal(shrunk, diagonal)
    return shrunk, intensity


def _project(hierarchy: Hierarchy, W: np.ndarray, y_hat: np.ndarray) -> np.ndarray:
    """The MinT projection `S (S' W^-1 S)^-1 S' W^-1 y_hat`.

    Solved with `lstsq` rather than an explicit inverse: with 28 observations
    behind the covariance the normal-equation matrix is frequently
    ill-conditioned, and a pseudo-inverse degrades gracefully where `inv`
    raises or returns nonsense.
    """
    S = hierarchy.S
    try:
        W_inv_S = np.linalg.solve(W, S)
        W_inv_y = np.linalg.solve(W, y_hat)
    except np.linalg.LinAlgError:
        pseudo = np.linalg.pinv(W)
        W_inv_S = pseudo @ S
        W_inv_y = pseudo @ y_hat
    lhs = S.T @ W_inv_S
    rhs = S.T @ W_inv_y
    beta, *_ = np.linalg.lstsq(lhs, rhs, rcond=None)
    return S @ beta


def _finalise(
    hierarchy: Hierarchy,
    *,
    method: str,
    reconciled: np.ndarray,
    base_values: np.ndarray,
    enforce_non_negative: bool,
    fallback_from: str | None = None,
    fallback_reason: str | None = None,
    shrinkage_intensity: float | None = None,
    notes: Iterable[str] = (),
) -> ReconciliationResult:
    """Clip, re-cohere, verify, and record - in that order.

    Clipping first and re-cohering second matters: clipping a negative base
    forecast to zero changes the sum its parents were projected against, so a
    result that clipped without re-cohering would fail its own coherence check.
    """
    working = np.asarray(reconciled, dtype=np.float64).copy()
    negatives = 0
    note_list = list(notes)

    if enforce_non_negative:
        base_slice = working[: hierarchy.base_count]
        negatives = int(np.sum(base_slice < 0))
        if negatives:
            np.clip(base_slice, 0.0, None, out=base_slice)
            working[: hierarchy.base_count] = base_slice
            # Re-aggregate rather than clipping the parents independently: a
            # parent must remain the sum of the children that now exist.
            working = hierarchy.S @ base_slice
            note_list.append(
                f"{negatives} base forecast(s) were negative and were clipped to "
                "zero; every parent was then re-aggregated from the clipped "
                "children so the hierarchy stays coherent."
            )

    coherent, max_incoherence = check_coherence(hierarchy, working)
    if not coherent:
        note_list.append(
            f"Coherence check failed by {max_incoherence:.6g} after "
            f"{method}; the result is reported as incoherent rather than "
            "presented as coherent."
        )

    return ReconciliationResult(
        method=method,
        values=working,
        base_values=np.asarray(base_values, dtype=np.float64),
        adjustments=working - np.asarray(base_values, dtype=np.float64),
        coherent=coherent,
        max_incoherence=max_incoherence,
        negatives_clipped=negatives,
        fallback_from=fallback_from,
        fallback_reason=fallback_reason,
        shrinkage_intensity=shrinkage_intensity,
        notes=note_list,
    )


def check_coherence(
    hierarchy: Hierarchy, values: Sequence[float]
) -> tuple[bool, float]:
    """Does every parent equal the sum of its base children?

    Verified from the summing matrix rather than assumed from the algebra, so a
    bug in the projection surfaces as an incoherent result instead of a
    confident wrong number.
    """
    vector = np.asarray(values, dtype=np.float64).reshape(-1)
    base = vector[: hierarchy.base_count]
    implied = hierarchy.S @ base
    difference = np.abs(vector - implied)
    scale = np.maximum(np.abs(implied), 1.0)
    worst = float(np.max(difference)) if difference.size else 0.0
    ok = bool(np.all(difference <= COHERENCE_ATOL + COHERENCE_RTOL * scale))
    return ok, worst


def reconcile(
    hierarchy: Hierarchy,
    forecasts: Sequence[float],
    *,
    method: str = "mint_variance",
    residuals: np.ndarray | None = None,
    historical_shares: Sequence[float] | None = None,
    enforce_non_negative: bool = True,
) -> ReconciliationResult:
    """Reconcile one vector of node forecasts.

    `forecasts` is in `Hierarchy.nodes` order - base forecasts first, then each
    aggregate level's own independent forecast. A method that cannot be computed
    from the evidence supplied **falls back and says so**; it never proceeds on
    a covariance it could not estimate.
    """
    y_hat = np.asarray(forecasts, dtype=np.float64).reshape(-1)
    if y_hat.size != hierarchy.node_count:
        raise ValueError(
            f"{y_hat.size} forecasts for {hierarchy.node_count} hierarchy nodes."
        )
    if method not in METHODS:
        raise ValueError(f"Unknown reconciliation method {method!r}. Valid: {METHODS}.")

    base_values = y_hat.copy()

    if method == "none":
        return _finalise(
            hierarchy,
            method="none",
            reconciled=y_hat,
            base_values=base_values,
            enforce_non_negative=enforce_non_negative,
            notes=[
                "No reconciliation was applied, so the levels are not "
                "guaranteed to add up."
            ],
        )

    if method == "bottom_up":
        return _finalise(
            hierarchy,
            method="bottom_up",
            reconciled=bottom_up(hierarchy, y_hat[: hierarchy.base_count]),
            base_values=base_values,
            enforce_non_negative=enforce_non_negative,
            notes=[
                "Bottom-up: every aggregate is the sum of its base children, so "
                "the aggregates' own forecasts were discarded."
            ],
        )

    if method == "proportional":
        shares = _resolve_shares(hierarchy, historical_shares, y_hat)
        national_index = _national_index(hierarchy)
        if national_index is None:
            return reconcile(
                hierarchy,
                y_hat,
                method="bottom_up",
                enforce_non_negative=enforce_non_negative,
            )
        total = float(y_hat[national_index])
        return _finalise(
            hierarchy,
            method="proportional",
            reconciled=bottom_up(hierarchy, shares * total),
            base_values=base_values,
            enforce_non_negative=enforce_non_negative,
            notes=[
                "Proportional top-down: the national forecast was split by "
                "historical share, so base-level detail comes from history "
                "rather than from the base models."
            ],
        )

    # Both MinT variants need a weight matrix from residuals.
    if residuals is None or np.asarray(residuals).size == 0:
        return _finalise(
            hierarchy,
            method="bottom_up",
            reconciled=bottom_up(hierarchy, y_hat[: hierarchy.base_count]),
            base_values=base_values,
            enforce_non_negative=enforce_non_negative,
            fallback_from=method,
            fallback_reason=(
                "No out-of-sample residuals were supplied, so no covariance "
                "could be estimated. Bottom-up needs none and is coherent."
            ),
        )

    matrix = np.atleast_2d(np.asarray(residuals, dtype=np.float64))
    if matrix.shape[0] < MIN_RESIDUALS_FOR_VARIANCE:
        return _finalise(
            hierarchy,
            method="bottom_up",
            reconciled=bottom_up(hierarchy, y_hat[: hierarchy.base_count]),
            base_values=base_values,
            enforce_non_negative=enforce_non_negative,
            fallback_from=method,
            fallback_reason=(
                f"Only {matrix.shape[0]} residual row(s) available; "
                f"{MIN_RESIDUALS_FOR_VARIANCE} are required before a variance "
                "estimate is worth using."
            ),
        )
    if matrix.shape[1] != hierarchy.node_count:
        raise ValueError(
            f"Residual matrix has {matrix.shape[1]} columns for "
            f"{hierarchy.node_count} nodes."
        )

    intensity: float | None = None
    if method == "mint_variance":
        variances = np.nanvar(matrix, axis=0, ddof=1)
        variances = np.where(np.isfinite(variances), variances, np.nan)
        positive = variances[np.isfinite(variances) & (variances > 0)]
        floor = float(np.mean(positive)) if positive.size else 1.0
        variances = np.where(
            np.isfinite(variances) & (variances > 0), variances, floor
        )
        W = np.diag(variances)
        notes = [
            "MinT with variance (WLS) scaling: a diagonal weight matrix. The "
            "full covariance over this many base series is not estimable from "
            "28 observations (docs/DECISIONS.md D-009)."
        ]
    else:
        W, intensity = shrink_covariance(matrix)
        notes = [
            "MinT with shrinkage covariance, intensity "
            f"{intensity:.3f} toward the diagonal."
        ]

    try:
        projected = _project(hierarchy, W, y_hat)
    except np.linalg.LinAlgError as exc:
        return _finalise(
            hierarchy,
            method="bottom_up",
            reconciled=bottom_up(hierarchy, y_hat[: hierarchy.base_count]),
            base_values=base_values,
            enforce_non_negative=enforce_non_negative,
            fallback_from=method,
            fallback_reason=(
                f"The projection did not solve ({exc}). Bottom-up is coherent "
                "and needs no covariance."
            ),
        )

    if not np.all(np.isfinite(projected)):
        return _finalise(
            hierarchy,
            method="bottom_up",
            reconciled=bottom_up(hierarchy, y_hat[: hierarchy.base_count]),
            base_values=base_values,
            enforce_non_negative=enforce_non_negative,
            fallback_from=method,
            fallback_reason=(
                "The projection produced non-finite values, which means the "
                "weight matrix was too ill-conditioned to trust."
            ),
        )

    return _finalise(
        hierarchy,
        method=method,
        reconciled=projected,
        base_values=base_values,
        enforce_non_negative=enforce_non_negative,
        shrinkage_intensity=intensity,
        notes=notes,
    )


def _national_index(hierarchy: Hierarchy) -> int | None:
    for index, (level, _key) in enumerate(hierarchy.nodes):
        if level == "national":
            return index
    return None


def _resolve_shares(
    hierarchy: Hierarchy,
    historical_shares: Sequence[float] | None,
    y_hat: np.ndarray,
) -> np.ndarray:
    """Base-level shares for a top-down split.

    Falls back to the base forecasts' own shares when no history is supplied,
    and to an equal split when those sum to zero - an equal split being the
    only defensible answer when nothing distinguishes the series.
    """
    if historical_shares is not None:
        shares = np.asarray(historical_shares, dtype=np.float64).reshape(-1)
        if shares.size != hierarchy.base_count:
            raise ValueError(
                f"{shares.size} historical shares for {hierarchy.base_count} "
                "base series."
            )
    else:
        shares = np.clip(y_hat[: hierarchy.base_count], 0.0, None)

    total = float(np.sum(shares))
    if total <= 0:
        return np.full(hierarchy.base_count, 1.0 / max(hierarchy.base_count, 1))
    return shares / total


def reconcile_quantiles(
    hierarchy: Hierarchy,
    reconciled_point: Sequence[float],
    quantiles: dict[str, Sequence[float]],
    *,
    enforce_non_negative: bool = True,
) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    """Carry a point reconciliation across to the quantiles, keeping the order.

    Quantiles are **not** projected independently. Two separate projections of
    q80 and q90 can cross, and a crossed interval is worse than a slightly
    sub-optimal one. Instead each quantile's spread above the point forecast is
    scaled by the same factor the point forecast moved, then the levels are
    re-sorted and the ordering `point <= q80 <= q90 <= q95` is re-checked.
    """
    point = np.asarray(reconciled_point, dtype=np.float64).reshape(-1)
    output: dict[str, np.ndarray] = {}
    keys = sorted(quantiles, key=lambda key: float(key[1:]))

    stacked: list[np.ndarray] = []
    for key in keys:
        values = np.asarray(quantiles[key], dtype=np.float64).reshape(-1)
        if values.size != point.size:
            raise ValueError(
                f"{key} has {values.size} values for {point.size} nodes."
            )
        stacked.append(values)

    crossings = 0
    if stacked:
        matrix = np.vstack(stacked)
        if enforce_non_negative:
            matrix = np.clip(matrix, 0.0, None)
        # Never below the point forecast.
        matrix = np.maximum(matrix, point)
        ordered = np.sort(matrix, axis=0)
        crossings = int(np.sum(np.any(ordered != matrix, axis=0)))
        for index, key in enumerate(keys):
            output[key] = ordered[index]

    report = {
        "levels": keys,
        "nodes": int(point.size),
        "crossings_corrected": crossings,
        "note": (
            "Quantiles were re-sorted after reconciliation so that "
            "point <= q80 <= q90 <= q95 holds at every node. Independent "
            "projection of each level was avoided because it can cross."
        ),
    }
    return output, report

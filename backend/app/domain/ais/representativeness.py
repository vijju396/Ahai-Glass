"""How far the sampled SKUs distort the composition charts.

The workspace is twenty SKUs chosen by **stratification** - one per
(glass type x value class) cell, then one per vehicle category - so that every
category is represented at all. That was the right way to pick a sample for
judging model behaviour, and it has an unavoidable side effect: the resulting
*volume mix* is no longer proportional to the branches the sample came from.

The effect is not small and it is not confined to the axis that was stratified
on. Measured on the current workspace, the largest gap on each axis:

    vehicle age       Category Z 54.9% vs 28.0%   (2.0x, 26.9 points)
    glass type        Lam        90.2% vs 68.4%   (1.3x, 21.7 points)
    value class       A          95.4% vs 74.3%   (1.3x, 21.1 points)
    vehicle category  3W         15.0% vs  3.3%   (4.5x, 11.7 points)

Vehicle age is the worst distorted and was never a stratification rule at all -
it is a pure side effect of which SKUs the other rules selected. That is
exactly why this is computed rather than written as a fixed sentence: an
assumption about which axis is affected would have been wrong.

**The comparison baseline is the same branches with every SKU**, not the whole
network. The workspace's branch axis is respected; only the SKU restriction is
lifted, because the question being answered is "is this sample representative
of the branches it was drawn from", and widening to 53 branches would answer a
different question while reporting outside the configured scope.

A caveat is only emitted where the distortion is real - a large points gap, or
an extreme ratio on a level big enough to matter (see `LevelComparison.material`
for why that is an *or* and not an *and*). A panel whose sample happens to match
its branches emits nothing, because a warning that appears everywhere is read
nowhere.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

#: A share gap below this many percentage points is not worth a warning.
MATERIAL_GAP_POINTS = 5.0

#: ...unless the ratio is extreme. A level at 0.3% against 16.3% is only a 16
#: point gap but is effectively absent from the sample, which matters.
MATERIAL_RATIO_HIGH = 1.5
MATERIAL_RATIO_LOW = 0.67

#: The points floor for the ratio route, so a level at 0.2% against 0.1% -
#: a 2x ratio on nothing - does not raise a warning.
MATERIAL_MINOR_GAP_POINTS = 2.0

#: Levels that carry no business meaning and would only add noise.
EXCLUDED_LEVELS = {"UNKNOWN", "", "nan", "None"}


@dataclass(frozen=True)
class LevelComparison:
    level: str
    sample_pct: float
    branch_pct: float

    @property
    def gap_points(self) -> float:
        return self.sample_pct - self.branch_pct

    @property
    def ratio(self) -> float | None:
        if self.branch_pct <= 0:
            return None
        return self.sample_pct / self.branch_pct

    @property
    def material(self) -> bool:
        """Either a large absolute gap **or** an extreme ratio - not both.

        Requiring both excluded the worst distortion on the glass-type axis.
        Lam is 90.2% of the sample against 68.4% of the branches: a 21.7 point
        overstatement, and as obviously misleading as anything on the page. But
        its ratio is only 1.3x, because a level already holding two thirds of
        the volume *cannot* have an extreme ratio - the arithmetic caps it near
        1.46. An AND rule therefore systematically ignores distortion in
        exactly the biggest categories, which are the ones a reader looks at
        first.

        So a large points gap qualifies on its own, and the ratio test is a
        second way in for small levels whose share collapses (0.3% against
        16.3% reads as "this category barely exists") with a low points floor
        so a level at 0.2% against 0.1% stays quiet.
        """
        gap = abs(self.gap_points)
        if gap >= MATERIAL_GAP_POINTS:
            return True
        r = self.ratio
        if r is None:
            return gap >= MATERIAL_MINOR_GAP_POINTS
        return gap >= MATERIAL_MINOR_GAP_POINTS and (
            r >= MATERIAL_RATIO_HIGH or r <= MATERIAL_RATIO_LOW
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "sample_pct": round(self.sample_pct, 1),
            "branch_pct": round(self.branch_pct, 1),
            "gap_points": round(self.gap_points, 1),
            "ratio": round(self.ratio, 2) if self.ratio is not None else None,
            "material": self.material,
            "direction": "over" if self.gap_points > 0 else "under",
        }


@dataclass
class AxisComparison:
    column: str
    label: str
    levels: list[LevelComparison]
    comparable: bool = True
    reason: str | None = None

    @property
    def worst(self) -> LevelComparison | None:
        material = [level for level in self.levels if level.material]
        if not material:
            return None
        return max(material, key=lambda level: abs(level.gap_points))

    @property
    def max_gap(self) -> float:
        return max((abs(level.gap_points) for level in self.levels), default=0.0)

    def caveat(self) -> str | None:
        """One sentence naming the largest real distortion, or None."""
        worst = self.worst
        if worst is None:
            return None
        scale = (
            f"{worst.ratio:.1f}x its real share"
            if worst.ratio is not None
            else f"{abs(worst.gap_points):.1f} points out"
        )
        return (
            f"These proportions describe the twenty sampled SKUs, not the branches. "
            f"{worst.level} is {worst.sample_pct:.1f}% here against "
            f"{worst.branch_pct:.1f}% across the same two branches with every SKU "
            f"— {scale}. Read the shape of the sample, not the business."
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "column": self.column,
            "label": self.label,
            "comparable": self.comparable,
            "reason": self.reason,
            "levels": [level.as_dict() for level in self.levels],
            "max_gap_points": round(self.max_gap, 1),
            "material": self.worst is not None,
            "caveat": self.caveat(),
        }


def _shares(frame: pd.DataFrame, column: str, target: str) -> dict[str, float]:
    if frame.empty or column not in frame.columns:
        return {}
    work = frame[[column, target]].copy()
    work[column] = work[column].astype("object")
    work = work[work[column].notna()]
    work = work[~work[column].astype(str).isin(EXCLUDED_LEVELS)]
    if work.empty:
        return {}
    totals = (
        pd.to_numeric(work[target], errors="coerce").fillna(0.0).groupby(work[column]).sum()
    )
    grand = float(totals.sum())
    if grand <= 0:
        return {}
    return {str(k): 100.0 * float(v) / grand for k, v in totals.items()}


def compare_axis(
    sample: pd.DataFrame,
    reference: pd.DataFrame,
    column: str,
    label: str,
    *,
    target: str,
) -> AxisComparison:
    """Sample share against branch share, level by level."""
    if column not in sample.columns or column not in reference.columns:
        return AxisComparison(
            column=column,
            label=label,
            levels=[],
            comparable=False,
            reason=f"The panel carries no {column} column, so no comparison is possible.",
        )
    sample_shares = _shares(sample, column, target)
    reference_shares = _shares(reference, column, target)
    if not sample_shares or not reference_shares:
        return AxisComparison(
            column=column,
            label=label,
            levels=[],
            comparable=False,
            reason="No ordered demand on this axis, so shares are undefined.",
        )
    levels = [
        LevelComparison(
            level=level,
            sample_pct=sample_shares.get(level, 0.0),
            branch_pct=reference_shares.get(level, 0.0),
        )
        for level in sorted(set(sample_shares) | set(reference_shares))
    ]
    levels.sort(key=lambda level: level.branch_pct, reverse=True)
    return AxisComparison(column=column, label=label, levels=levels)


#: The composition panels this applies to. Every one of them plots a share of
#: ordered demand across a product attribute, which is precisely what the
#: stratified sample distorts.
COMPOSITION_AXES: tuple[tuple[str, str], ...] = (
    ("glass_type", "Demand by Glass Type"),
    ("vehicle_category", "Demand by Vehicle Category"),
    ("vehicle_age_category", "Demand by Vehicle Age"),
    ("value_class", "Demand by Value Class"),
)


def analyse(
    sample: pd.DataFrame,
    reference: pd.DataFrame,
    *,
    target: str,
    sample_skus: int | None = None,
    reference_skus: int | None = None,
) -> dict[str, Any]:
    """Every composition axis, compared."""
    axes = [
        compare_axis(sample, reference, column, label, target=target)
        for column, label in COMPOSITION_AXES
    ]
    material = [axis for axis in axes if axis.worst is not None]
    return {
        "axes": {axis.column: axis.as_dict() for axis in axes},
        "sample_skus": sample_skus,
        "reference_skus": reference_skus,
        "material_axis_count": len(material),
        "worst_axis": (
            max(material, key=lambda axis: axis.max_gap).column if material else None
        ),
        "basis": (
            "Sample share is the workspace's twenty SKUs. Branch share is the "
            "same two branches with every SKU they carry - not the national "
            "network, because the question is whether this sample represents "
            "the branches it was drawn from."
        ),
        "why": (
            "The twenty SKUs were chosen by stratification - one per glass type "
            "x value class, then one per vehicle category - so that every "
            "category appears at all. That makes the sample good for judging "
            "model behaviour and bad for reading composition: the SKU counts "
            "are spread deliberately, so the volume mix cannot also be "
            "proportional."
        ),
    }

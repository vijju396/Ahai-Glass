"""Training scopes: what each tier actually forecasts.

A naive "all 13 models on all 68,675 series" run costs well over 100 hours
(`docs/ARCHITECTURE.md` §6), so training is tiered. This module builds the
series each tier operates on, and it is deliberately the only place that knows
the AIS hierarchy column names.

Three things are kept honest here:

**An aggregate series is a real sum, not a sample.** The national series is the
sum of every branch x SKU cell for that month, so its total is the network's
total. It is not one representative series standing in for the network.

**Aggregating hides intermittency.** A branch x SKU cell is zero in most
months; a branch total almost never is. That makes aggregate series much easier
to forecast, and a model's aggregate-tier accuracy says nothing about its
accuracy on the cells underneath. `scope_level` travels with every row so the
two can never be averaged together.

**Selection is by a stated measure.** The high-value local tier takes the top N
series by value, volume or shortfall - whichever was configured - and the
measure used is recorded on the run. "Top 500" without saying "by what" is not
a reproducible selection.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

import pandas as pd

SERIES_COL = "series_id"
PERIOD_COL = "period_index"
TARGET_COL = "target"
BRANCH_COL = "canonical_branch"
SKU_COL = "canonical_sku"
REGION_COL = "region"
ZONE_COL = "zone"

#: Columns summed alongside the target so an aggregate series can still feed
#: VAR (which needs a second endogenous series) and carry its censoring flag.
SUMMED_COLUMNS: tuple[str, ...] = (
    TARGET_COL,
    "despatched_qty",
    "shortfall_qty",
)

#: The second endogenous series an aggregate scope offers VAR.
#:
#: `despatched_qty` cannot serve here: it is null on every sales-proxy row, so
#: strict null propagation in `_aggregate` makes it null for every aggregate
#: month, and VAR would be ineligible across the entire aggregate tier.
#:
#: `active_cells` - how many member branch x SKU cells had non-zero demand that
#: month - is a genuine co-evolving series with no nulls at all, because it is
#: counted from the target rather than joined from another source. It measures
#: the *breadth* of demand where the target measures its size, and the two move
#: differently: a month can hold flat volume while demand spreads across more
#: SKUs. That is exactly the kind of second series VAR exists to exploit
#: (docs/DECISIONS.md D-042).
AGGREGATE_VAR_PAIR_COLUMN = "active_cells"

#: Segment dimensions the aggregate tier rolls up over, in addition to the
#: geographic hierarchy.
SEGMENT_COLUMNS: tuple[str, ...] = ("value_class", "product_group")

#: How the high-value local tier ranks series.
SELECTION_MEASURES: tuple[str, ...] = ("value", "volume", "shortfall")


@dataclass
class ScopeSeries:
    """One series a tier will train on, with the label it is reported under."""

    scope_level: str
    scope_key: str
    frame: pd.DataFrame
    member_series: int = 1
    measure_value: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "scope_level": self.scope_level,
            "scope_key": self.scope_key,
            "rows": len(self.frame),
            "member_series": self.member_series,
            "measure_value": self.measure_value,
        }


@dataclass
class ScopePlan:
    """What a tier resolved to, and how big it is."""

    tier: str
    series: list[ScopeSeries] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.series)

    def level_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in self.series:
            counts[item.scope_level] = counts.get(item.scope_level, 0) + 1
        return counts

    def as_dict(self) -> dict[str, Any]:
        return {
            "tier": self.tier,
            "count": self.count,
            "level_counts": self.level_counts(),
            "notes": list(self.notes),
        }



def restrict_panel(
    panel: pd.DataFrame,
    *,
    branches: Sequence[str] | None = None,
    skus: Sequence[str] | None = None,
    max_skus: int | None = None,
    measure: str = "value",
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Cut the panel down to named branches and the top-N SKUs within them.

    A full run covers 69 aggregate scopes plus the top 500 local series and
    takes tens of minutes. A two-branch, twenty-SKU slice takes a fraction of
    that, which is what makes iterating on the models practical at all.

    Two properties this is careful about.

    **The SKU cut happens after the branch cut.** The top twenty SKUs *of the
    chosen branches* is a coherent slice; the top twenty nationally may barely
    appear in them. Ranking inside the restriction is what makes the run
    representative of the branches it claims to cover.

    **The restriction is returned, not merely applied.** Every count comes back
    so the run records what it actually covered. A run over 2 of 53 branches
    must never be readable as a run over the network.
    """
    if measure not in SELECTION_MEASURES:
        raise ValueError(
            f"{measure!r} is not a selection measure. Valid: {list(SELECTION_MEASURES)}"
        )

    empty = panel.empty
    applied: dict[str, Any] = {
        "branches_requested": [str(b) for b in branches] if branches else None,
        "max_skus": max_skus,
        "measure": measure,
        "panel_branches": 0 if empty else int(panel[BRANCH_COL].nunique()),
        "panel_skus": 0 if empty else int(panel[SKU_COL].nunique()),
        "panel_series": 0 if empty else int(panel[SERIES_COL].nunique()),
        "notes": [],
    }
    frame = panel

    if branches and not empty:
        wanted = {str(b).strip().upper() for b in branches if str(b).strip()}
        upper = frame[BRANCH_COL].astype("string").str.upper()
        available = set(upper.dropna().unique())
        matched = sorted(wanted & available)
        unknown = sorted(wanted - available)
        applied["branches_matched"] = matched
        applied["branches_unknown"] = unknown
        if unknown:
            # Named but absent, reported rather than dropped silently: a typo
            # would otherwise train a narrower run than was asked for and
            # nothing would say so.
            applied["notes"].append(
                f"{len(unknown)} requested branch(es) are not in this panel and were "
                f"ignored: {', '.join(unknown)}."
            )
        if matched:
            frame = frame[upper.isin(matched)]
        else:
            applied["notes"].append(
                "None of the requested branches exists in this panel, so the branch "
                "restriction was not applied. The run covers every branch."
            )

    if skus:
        # An explicit list beats a top-N cut: when the caller has already
        # chosen which products matter - stratified across glass type, value
        # class and vehicle category - ranking by value would silently
        # substitute a different twenty (docs/DECISIONS.md D-056).
        wanted_skus = {str(x).strip().upper() for x in skus if str(x).strip()}
        upper_sku = frame[SKU_COL].astype("string").str.upper()
        available = set(upper_sku.dropna().unique())
        matched_skus = sorted(wanted_skus & available)
        applied["skus_requested"] = sorted(wanted_skus)
        applied["skus_unknown"] = sorted(wanted_skus - available)
        if applied["skus_unknown"]:
            applied["notes"].append(
                f"{len(applied['skus_unknown'])} requested SKU(s) are not in this panel "
                "and were ignored."
            )
        if matched_skus:
            frame = frame[upper_sku.isin(matched_skus)]
            applied["skus_kept"] = matched_skus
        else:
            applied["notes"].append(
                "None of the requested SKUs exists in this panel, so the SKU restriction "
                "was not applied."
            )
    elif max_skus and max_skus > 0 and not frame.empty:
        # Ranked with the same measure the local tier ranks series by, so the
        # SKUs kept here are the ones that tier would have reached anyway.
        target = pd.to_numeric(frame[TARGET_COL], errors="coerce").fillna(0.0)
        if measure == "volume":
            weight = target
        elif measure == "value":
            mrp = pd.to_numeric(frame.get("mean_mrp"), errors="coerce").fillna(0.0)
            weight = target * mrp
        else:
            shortfall = pd.to_numeric(frame.get("shortfall_qty"), errors="coerce")
            weight = shortfall.fillna(0.0).clip(lower=0.0)
        ranked = (
            frame.assign(_measure=weight.to_numpy())
            .groupby(SKU_COL, observed=True)["_measure"]
            .sum()
            .sort_values(ascending=False)
        )
        keep = list(ranked.head(int(max_skus)).index)
        frame = frame[frame[SKU_COL].isin(keep)]
        applied["skus_requested"] = int(max_skus)

    after_empty = frame.empty
    applied["rows_before"] = int(len(panel))
    applied["rows_after"] = int(len(frame))
    applied["branches_after"] = 0 if after_empty else int(frame[BRANCH_COL].nunique())
    applied["skus_after"] = 0 if after_empty else int(frame[SKU_COL].nunique())
    applied["series_after"] = 0 if after_empty else int(frame[SERIES_COL].nunique())
    applied["is_restricted"] = applied["rows_after"] < applied["rows_before"]
    if applied["is_restricted"]:
        applied["scope_warning"] = (
            f"This run covers {applied['branches_after']} of "
            f"{applied['panel_branches']} branches and {applied['skus_after']} of "
            f"{applied['panel_skus']} SKUs ({applied['series_after']} of "
            f"{applied['panel_series']} series). Its results describe that slice, "
            "not the network."
        )
    return frame, applied


def build_aggregate_plan(
    panel: pd.DataFrame,
    *,
    include_segments: bool = True,
) -> ScopePlan:
    """National, per region, per branch, and per segment.

    Measured on the real panel: 1 national + 6 regions + 53 branches = 60, plus
    6 `value_class` and 3 `product_group` segments = 69 series. The
    architecture document estimated ~63 from 51 branches; the panel has 53, and
    the measured number is the one used.
    """
    plan = ScopePlan(tier="aggregate")
    if panel.empty:
        plan.notes.append("the panel is empty, so no aggregate series exist")
        return plan

    plan.series.append(
        ScopeSeries(
            scope_level="national",
            scope_key="NATIONAL",
            frame=_aggregate(panel, []),
            member_series=int(panel[SERIES_COL].nunique()),
        )
    )
    for level, column in (("region", REGION_COL), ("branch", BRANCH_COL)):
        if column not in panel.columns:
            plan.notes.append(f"{column!r} is absent, so no {level} series were built")
            continue
        for key, group in panel.groupby(column, observed=True, sort=True):
            if pd.isna(key):
                continue
            plan.series.append(
                ScopeSeries(
                    scope_level=level,
                    scope_key=str(key),
                    frame=_aggregate(group, []),
                    member_series=int(group[SERIES_COL].nunique()),
                )
            )
    if include_segments:
        for column in SEGMENT_COLUMNS:
            if column not in panel.columns:
                continue
            for key, group in panel.groupby(column, observed=True, sort=True):
                if pd.isna(key):
                    continue
                plan.series.append(
                    ScopeSeries(
                        scope_level="segment",
                        scope_key=f"{column}={key}",
                        frame=_aggregate(group, []),
                        member_series=int(group[SERIES_COL].nunique()),
                    )
                )

    plan.notes.append(
        "aggregate series are real sums over their members, not samples; an "
        "aggregate is far less intermittent than the cells beneath it, so its "
        "accuracy does not transfer to them"
    )
    return plan


def build_local_plan(
    panel: pd.DataFrame,
    *,
    max_series: int,
    measure: str = "value",
    min_observed_months: int = 12,
) -> ScopePlan:
    """The top `max_series` branch x SKU series by the stated measure.

    `min_observed_months` excludes series too short for any origin to be
    honest. Excluded series are **not** silently dropped from the run: the
    pooled tier covers every series, and the count excluded here is reported.
    """
    if measure not in SELECTION_MEASURES:
        raise ValueError(
            f"{measure!r} is not a selection measure. Valid: {list(SELECTION_MEASURES)}"
        )
    plan = ScopePlan(tier="local")
    if panel.empty or max_series <= 0:
        plan.notes.append("no local series were requested")
        return plan

    ranked = rank_series(panel, measure=measure)
    eligible = ranked[ranked["observed_months"] >= min_observed_months]
    excluded = len(ranked) - len(eligible)
    chosen = eligible.head(max_series)

    grouped = dict(tuple(panel.groupby(SERIES_COL, observed=True)))
    for row in chosen.itertuples():
        frame = grouped.get(row.series_id)
        if frame is None:
            continue
        plan.series.append(
            ScopeSeries(
                scope_level="series",
                scope_key=str(row.series_id),
                frame=frame.sort_values(PERIOD_COL),
                member_series=1,
                measure_value=float(row.measure),
            )
        )
    plan.notes.append(
        f"selected the top {len(plan.series)} of {len(eligible)} eligible series "
        f"by {measure}; {excluded} series were excluded for having fewer than "
        f"{min_observed_months} observed months, and are covered by the pooled tier"
    )
    if plan.series:
        covered = chosen["measure"].sum()
        total = ranked["measure"].sum()
        if total:
            plan.notes.append(
                f"these series carry {covered / total * 100:.1f}% of total {measure}"
            )
    return plan


def rank_series(panel: pd.DataFrame, *, measure: str = "value") -> pd.DataFrame:
    """One row per series with its ranking measure, largest first.

    - `volume` - total ordered quantity.
    - `value`  - ordered quantity x that month's mean MRP, summed. MRP is a
      historical column and is used here only to *rank*, never as a forecast
      feature (mapping rule R5), so this does not smuggle a non-future-known
      driver into the model.
    - `shortfall` - total positive shortfall, which ranks by service failure
      rather than by size.
    """
    if measure not in SELECTION_MEASURES:
        raise ValueError(
            f"{measure!r} is not a selection measure. Valid: {list(SELECTION_MEASURES)}"
        )
    frame = panel.copy()
    target = pd.to_numeric(frame[TARGET_COL], errors="coerce").fillna(0.0)

    if measure == "volume":
        frame["_measure"] = target
    elif measure == "value":
        mrp = pd.to_numeric(frame.get("mean_mrp"), errors="coerce").fillna(0.0)
        frame["_measure"] = target * mrp
    else:
        shortfall = pd.to_numeric(frame.get("shortfall_qty"), errors="coerce").fillna(0.0)
        # Positive shortfall only. Net shortfall would let an over-despatched
        # month cancel a stockout, which is the opposite of ranking by service
        # failure (docs/AIS_DOMAIN_RULES.md).
        frame["_measure"] = shortfall.clip(lower=0.0)

    grouped = frame.groupby(SERIES_COL, observed=True)
    ranked = pd.DataFrame(
        {
            "series_id": grouped.size().index,
            "measure": grouped["_measure"].sum().to_numpy(),
            "observed_months": grouped.size().to_numpy(),
            "nonzero_months": grouped[TARGET_COL]
            .apply(lambda values: int((pd.to_numeric(values, errors="coerce") != 0).sum()))
            .to_numpy(),
        }
    )
    return ranked.sort_values(
        ["measure", "series_id"], ascending=[False, True]
    ).reset_index(drop=True)


def _aggregate(frame: pd.DataFrame, extra_keys: Sequence[str]) -> pd.DataFrame:
    """Sum the panel to one row per period.

    Censoring is aggregated as **any**: if any member line was despatched
    short, the aggregate is a lower bound too. Summing the flag or averaging it
    would produce a number that is neither a count nor a boolean.
    """
    keys = [*extra_keys, PERIOD_COL]
    present = [column for column in SUMMED_COLUMNS if column in frame.columns]
    grouped = frame.groupby(keys, observed=True, sort=True)
    aggregated = grouped[present].sum().reset_index()

    # Unknown does not aggregate to zero. `despatched_qty` is null on every
    # sales-proxy row - the despatch simply is not recorded - and pandas' `sum`
    # treats null as 0, which would report "nothing was despatched" for a month
    # where the truth is unknown. VAR would then fit against a fabricated
    # constant-zero series.
    #
    # So a column with ANY null member propagates to null for that month. That
    # is stricter than summing the known part, deliberately: a partial sum
    # presented as a total is a lower bound wearing a total's clothes, and
    # nothing downstream would know to treat it as one. The target itself is
    # exempt - it is never null in the panel, every cell is either an
    # observation or an explicit materialised zero (D-023).
    for column in present:
        if column == TARGET_COL:
            continue
        any_missing = grouped[column].apply(lambda values: bool(values.isna().any()))
        aggregated.loc[any_missing.to_numpy(), column] = float("nan")
    if "is_censored" in frame.columns:
        censored = (
            frame.assign(_c=frame["is_censored"].fillna(False).astype(bool))
            .groupby(keys, observed=True, sort=True)["_c"]
            .any()
            .reset_index()
            .rename(columns={"_c": "is_censored"})
        )
        aggregated = aggregated.merge(censored, on=keys, how="left")
    if "target_source" in frame.columns:
        # An aggregate month is `order` only if every member row was; otherwise
        # it is a mixture, and calling it `order` would overstate the signal.
        sources = (
            frame.groupby(keys, observed=True, sort=True)["target_source"]
            .agg(lambda values: "order" if set(values.dropna()) == {"order"} else "mixed")
            .reset_index()
        )
        aggregated = aggregated.merge(sources, on=keys, how="left")

    # Breadth of demand: how many member cells were active, and how many
    # existed. Counted from the target, so neither can be null.
    breadth = (
        frame.assign(
            _active=pd.to_numeric(frame[TARGET_COL], errors="coerce").fillna(0.0) != 0
        )
        .groupby(keys, observed=True, sort=True)
        .agg(active_cells=("_active", "sum"), member_cells=("_active", "size"))
        .reset_index()
    )
    aggregated = aggregated.merge(breadth, on=keys, how="left")
    aggregated["active_cells"] = aggregated["active_cells"].astype("float64")
    aggregated["member_cells"] = aggregated["member_cells"].astype("float64")

    aggregated["mean_mrp"] = float("nan")
    return aggregated.sort_values(PERIOD_COL).reset_index(drop=True)


def summarise_plans(plans: Iterable[ScopePlan]) -> dict[str, Any]:
    """A run-level view of every tier's scope."""
    resolved = list(plans)
    return {
        "tiers": [plan.as_dict() for plan in resolved],
        "total_series": sum(plan.count for plan in resolved),
    }

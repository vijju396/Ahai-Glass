"""Demand-analytics aggregations for the reference-parity dashboard pages.

The reference's Labor Analytics page is driven by one `analytics/summary`
response carrying every panel's data at once, filtered server-side. This is the
AIS equivalent, and the mapping is deliberate rather than cosmetic:

| Reference | AIS | Definition and unit |
|---|---|---|
| location / site | `canonical_branch` | the 53 depots in the panel |
| department | `value_class` (primary), `product_group` (also returned) | documented AIS dimensions. `value_class` has six populated levels; `product_group` has three, one holding 99.7% of demand, so it makes a one-bar chart |
| labour cost | **ordered demand value** | `target x mean_mrp`, rupees |
| scheduled hours | **ordered quantity** | `target`, units |
| actual hours | **despatched quantity** | `despatched_qty`, units |
| overtime | **unfilled demand** | positive `shortfall_qty`, units |
| attendance rate | **fill rate** | `despatched_qty / target`, per cent |
| utilization | **ordered-demand share** | rows sourced from orders, per cent |

Two rules constrain everything here.

**No grain the data does not have.** The panel is monthly. The reference offers
daily/weekly/monthly; this offers monthly and quarterly, because a quarterly
roll-up of monthly rows is a real aggregation and a daily split of them is an
invention. `available_grains` tells the UI which to render.

**Unknown is not zero.** `despatched_qty` is null on every sales-proxy row, so
a fill rate over a proxy month would divide by a number that was never
recorded. Those months are excluded from fill-rate aggregates and the excluded
count is reported, rather than being silently counted as zero despatch.
"""

from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Iterable

import numpy as np
import pandas as pd

from app.ml.features.panel import index_to_period, month_index

SERIES_COL = "series_id"
PERIOD_COL = "period_index"
TARGET_COL = "target"
BRANCH_COL = "canonical_branch"
SKU_COL = "canonical_sku"
GROUP_COL = "product_group"

#: Columns the analytics path reads. Nothing here is PII-adjacent: the panel
#: carries no customer, GSTIN, PAN, address, email or mobile column at all, and
#: this explicit list is where that stays true.
ANALYTICS_COLUMNS: tuple[str, ...] = (
    SERIES_COL,
    PERIOD_COL,
    TARGET_COL,
    BRANCH_COL,
    SKU_COL,
    GROUP_COL,
    "despatched_qty",
    "shortfall_qty",
    "over_delivered_qty",
    "mean_mrp",
    "is_censored",
    "target_source",
    "is_materialised",
    "region",
    "value_class",
    # The two product axes the workspace was actually selected on, and which
    # nothing in the UI showed: the 20 SKUs span three glass types and four
    # vehicle categories, so a page with neither was missing the shape of its
    # own sample (docs/DECISIONS.md D-070).
    "glass_type",
    "vehicle_category",
    "vehicle_age_category",
    "in_product_master",
    "is_non_glass",
    "closing_qty",
    "usable_qty",
    "closing_value",
    "stock_class",
    "has_negative_row",
)

AVAILABLE_GRAINS: tuple[str, ...] = ("monthly", "quarterly")

#: Why `daily` and `weekly` are absent, surfaced in the payload so the UI can
#: explain the missing control instead of just not having it.
GRAIN_NOTE = (
    "AIS demand history is monthly (one row per branch x SKU x month), so only "
    "monthly and a real quarterly roll-up are offered. A daily or weekly view "
    "would have to invent values the source data does not contain."
)


@dataclass
class AnalyticsScope:
    branch: str | None = None
    #: A single canonical SKU. With `branch` this addresses one series, which
    #: is what the per-SKU/branch analysis is built on.
    sku: str | None = None
    product_group: str | None = None
    value_class: str | None = None
    start_period: str | None = None
    end_period: str | None = None
    grain: str = "monthly"

    def normalised(self) -> AnalyticsScope:
        grain = self.grain if self.grain in AVAILABLE_GRAINS else "monthly"
        return AnalyticsScope(
            branch=self.branch or None,
            sku=self.sku or None,
            product_group=self.product_group or None,
            value_class=self.value_class or None,
            start_period=self.start_period or None,
            end_period=self.end_period or None,
            grain=grain,
        )


@lru_cache(maxsize=2)
def load_panel(panel_path: str) -> pd.DataFrame:
    """The panel, once per process, with only the analytics columns.

    Cached because every panel on this dataset is 1.5 M rows and an
    un-cached read would put a multi-second parquet load inside a request.
    Keyed on the artifact path, so a rebuilt panel is a different key rather
    than a stale hit.
    """
    available = set(pd.read_parquet(panel_path, columns=[SERIES_COL]).columns)  # cheap probe
    del available
    frame = pd.read_parquet(panel_path, columns=list(ANALYTICS_COLUMNS))
    frame["period"] = frame[PERIOD_COL].map(index_to_period)
    frame["demand_value"] = pd.to_numeric(frame[TARGET_COL], errors="coerce").fillna(0.0) * pd.to_numeric(
        frame["mean_mrp"], errors="coerce"
    ).fillna(0.0)
    frame["shortfall_positive"] = pd.to_numeric(frame["shortfall_qty"], errors="coerce").clip(lower=0.0)
    return frame


def filters(panel: pd.DataFrame) -> dict[str, Any]:
    """Filter options, each with its own row count so a planner can see how
    much data sits behind an option before choosing it."""
    def options(column: str) -> list[dict[str, Any]]:
        if column not in panel.columns:
            return []
        counts = panel.groupby(column, observed=True)[TARGET_COL].agg(["size", "sum"])
        return [
            {"value": str(key), "label": str(key), "rows": int(row["size"]), "units": float(row["sum"])}
            for key, row in counts.sort_values("sum", ascending=False).iterrows()
            if not pd.isna(key)
        ]

    periods = sorted(panel["period"].unique())
    return {
        "branches": options(BRANCH_COL),
        "product_groups": options(GROUP_COL),
        "value_classes": options("value_class"),
        "regions": options("region"),
        "period_range": {"min": periods[0], "max": periods[-1]} if periods else None,
        "periods": periods,
        "available_grains": list(AVAILABLE_GRAINS),
        "grain_note": GRAIN_NOTE,
        "series_count": int(panel[SERIES_COL].nunique()),
    }


def _apply_scope(panel: pd.DataFrame, scope: AnalyticsScope) -> pd.DataFrame:
    frame = panel
    if scope.branch:
        frame = frame[frame[BRANCH_COL] == scope.branch]
    if scope.sku:
        frame = frame[frame[SKU_COL] == scope.sku]
    if scope.product_group:
        frame = frame[frame[GROUP_COL] == scope.product_group]
    if scope.value_class:
        frame = frame[frame["value_class"] == scope.value_class]
    if scope.start_period:
        frame = frame[frame[PERIOD_COL] >= month_index(scope.start_period)]
    if scope.end_period:
        frame = frame[frame[PERIOD_COL] <= month_index(scope.end_period)]
    return frame


def _bucket(frame: pd.DataFrame, grain: str) -> pd.Series:
    """The period label each row aggregates into."""
    if grain == "quarterly":
        year = frame[PERIOD_COL] // 12
        quarter = (frame[PERIOD_COL] % 12) // 3 + 1
        return year.astype(str) + "-Q" + quarter.astype(str)
    return frame["period"]


def _safe(value: Any) -> float | None:
    if value is None:
        return None
    try:
        as_float = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(as_float) or math.isinf(as_float) else as_float


def _ratio(numerator: float, denominator: float) -> float | None:
    return None if not denominator else round(numerator / denominator * 100, 2)


def _trend(frame: pd.DataFrame, grain: str) -> list[dict[str, Any]]:
    """One row per period bucket, carrying every trend panel's series.

    `fill_rate_pct` is computed only over months where despatch was actually
    recorded. A sales-proxy month has no despatch figure at all, so including
    it would report a fill rate against a denominator that does not exist.

    Vectorised rather than looping the groups: at 1.5 M rows the per-group
    Python body dominated the whole page and put ~9 s inside one request.
    """
    if frame.empty:
        return []
    despatched = pd.to_numeric(frame["despatched_qty"], errors="coerce")
    ordered = pd.to_numeric(frame[TARGET_COL], errors="coerce").fillna(0.0)
    work = pd.DataFrame(
        {
            "bucket": _bucket(frame, grain),
            "ordered": ordered,
            "value": frame["demand_value"].astype("float64"),
            "shortfall": frame["shortfall_positive"].fillna(0.0).astype("float64"),
            "is_order": (frame["target_source"] == "order").astype("int8"),
            "censored": frame["is_censored"].fillna(False).astype(bool).astype("int8"),
            "known": despatched.notna().astype("int8"),
            "despatched": despatched.fillna(0.0),
            # Ordered quantity restricted to rows that actually carry a despatch
            # figure, so the fill-rate denominator matches its numerator row for
            # row instead of counting proxy months as zero despatch.
            "ordered_known": ordered.where(despatched.notna(), 0.0),
        }
    )
    agg = work.groupby("bucket", observed=True, sort=True).agg(
        ordered=("ordered", "sum"),
        value=("value", "sum"),
        shortfall=("shortfall", "sum"),
        despatched=("despatched", "sum"),
        ordered_known=("ordered_known", "sum"),
        order_rows=("is_order", "sum"),
        censored=("censored", "sum"),
        known_rows=("known", "sum"),
        rows=("ordered", "size"),
    )

    out: list[dict[str, Any]] = []
    for bucket, r in agg.iterrows():
        rows = int(r["rows"])
        known_rows = int(r["known_rows"])
        total = float(r["ordered"])
        value = float(r["value"])
        out.append(
            {
                "period": str(bucket),
                "demand_units": round(total, 2),
                "demand_value": round(value, 2),
                "despatched_units": round(float(r["despatched"]), 2) if known_rows else None,
                "shortfall_units": round(float(r["shortfall"]), 2),
                "fill_rate_pct": _ratio(float(r["despatched"]), float(r["ordered_known"])) if known_rows else None,
                "order_share_pct": _ratio(float(r["order_rows"]), rows),
                "proxy_share_pct": _ratio(rows - float(r["order_rows"]), rows),
                "censored_share_pct": _ratio(float(r["censored"]), rows),
                "price_per_unit": round(value / total, 2) if total else None,
                "rows": rows,
                "despatch_rows_excluded": rows - known_rows,
            }
        )
    return out


def _by_dimension(frame: pd.DataFrame, column: str, label: str) -> list[dict[str, Any]]:
    """Totals per level of one dimension. Vectorised, for the same reason
    `_trend` is."""
    if frame.empty or column not in frame.columns:
        return []
    despatched = pd.to_numeric(frame["despatched_qty"], errors="coerce")
    work = pd.DataFrame(
        {
            "key": frame[column].astype("object"),
            "ordered": pd.to_numeric(frame[TARGET_COL], errors="coerce").fillna(0.0),
            "value": frame["demand_value"].astype("float64"),
            "shortfall": frame["shortfall_positive"].fillna(0.0).astype("float64"),
            "despatched": despatched.fillna(0.0),
            "known": despatched.notna().astype("int8"),
            "sku": frame[SKU_COL].astype("object"),
            "series": frame[SERIES_COL].astype("object"),
        }
    ).dropna(subset=["key"])
    if work.empty:
        return []
    agg = work.groupby("key", observed=True).agg(
        ordered=("ordered", "sum"),
        value=("value", "sum"),
        shortfall=("shortfall", "sum"),
        despatched=("despatched", "sum"),
        known=("known", "sum"),
        sku_count=("sku", "nunique"),
        series_count=("series", "nunique"),
    )
    rows = [
        {
            label: str(key),
            "name": str(key),
            "demand_units": round(float(r["ordered"]), 2),
            "demand_value": round(float(r["value"]), 2),
            "despatched_units": round(float(r["despatched"]), 2) if int(r["known"]) else None,
            "shortfall_units": round(float(r["shortfall"]), 2),
            "sku_count": int(r["sku_count"]),
            "series_count": int(r["series_count"]),
        }
        for key, r in agg.iterrows()
    ]
    return sorted(rows, key=lambda row: row["demand_value"], reverse=True)


def _cross_tab(
    frame: pd.DataFrame, column: str = "value_class", *, limit: int = 8
) -> dict[str, Any]:
    """Branch x value class - the stacked-bar panel's data.

    Split by `value_class`, not `product_group`: the panel is titled by value
    class and the two are different dimensions. It was product_group first,
    which put an "AIS GLASS / HIGH END" legend under a "by Value Class" title -
    a chart disagreeing with its own heading.

    Capped at the top `limit` branches by value, and `total_branches` is
    returned so the panel can say what it is showing. The reference's
    equivalent has two sites on the axis; AIS has 53, and twenty rotated depot
    names in a quarter-width panel collide into an unreadable band. Showing
    eight and naming the cap is honest; showing twenty illegibly is not.
    """
    if frame.empty or column not in frame.columns:
        return {"groups": [], "data": [], "limit": limit, "total_branches": 0}
    pivot = (
        frame.pivot_table(
            index=BRANCH_COL, columns=column, values="demand_value", aggfunc="sum", observed=True
        )
        .fillna(0.0)
        .round(2)
    )
    groups = [str(c) for c in pivot.columns]
    data = [{"name": str(idx), **{str(c): float(row[c]) for c in pivot.columns}} for idx, row in pivot.iterrows()]
    data.sort(key=lambda r: sum(v for k, v in r.items() if k != "name"), reverse=True)
    return {
        "groups": groups,
        "data": data[:limit],
        "limit": limit,
        "total_branches": len(data),
    }


def _branch_over_time(frame: pd.DataFrame, grain: str, limit: int = 6) -> dict[str, Any]:
    """One line per branch, for the top `limit` branches by demand value.

    Capped because 53 lines on one axis is unreadable; the cap is reported so
    the panel can say it is showing the top six rather than everything.
    """
    if frame.empty:
        return {"names": [], "data": [], "limit": limit, "total_branches": 0}
    totals = frame.groupby(BRANCH_COL, observed=True)["demand_value"].sum().sort_values(ascending=False)
    names = [str(n) for n in totals.head(limit).index]
    work = frame[frame[BRANCH_COL].isin(names)].assign(_bucket=_bucket(frame[frame[BRANCH_COL].isin(names)], grain))
    pivot = (
        work.pivot_table(index="_bucket", columns=BRANCH_COL, values="demand_value", aggfunc="sum", observed=True)
        .fillna(0.0)
        .round(2)
    )
    data = [{"period": str(idx), **{str(c): float(row[c]) for c in pivot.columns}} for idx, row in pivot.iterrows()]
    return {"names": names, "data": data, "limit": limit, "total_branches": int(totals.size)}


def _seasonality(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """Mean demand per calendar month across the window.

    A real seasonal profile from the months present, not a fitted curve. With
    28 months the panel gives at most three observations per calendar month, so
    `observations` travels with each point — a mean of one month is not a
    seasonal estimate and the panel says so.
    """
    if frame.empty:
        return []
    work = frame.assign(month=(frame[PERIOD_COL] % 12) + 1)
    by_month = work.groupby(["month", "period"], observed=True)[TARGET_COL].sum().reset_index()
    out = []
    names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    for month, group in by_month.groupby("month"):
        out.append(
            {
                "month": int(month),
                "name": names[int(month) - 1],
                "mean_demand_units": round(float(group[TARGET_COL].mean()), 2),
                "observations": int(len(group)),
            }
        )
    return sorted(out, key=lambda r: r["month"])


def _concentration(frame: pd.DataFrame, top: int = 8) -> list[dict[str, Any]]:
    """Top-SKU share of a branch's demand - the reference's Productivity slot.

    Demand concentration is the AIS question that panel shape actually
    answers: how much of a branch's volume sits in a handful of SKUs.
    """
    if frame.empty:
        return []
    by_sku = frame.groupby([BRANCH_COL, SKU_COL], observed=True)[TARGET_COL].sum().reset_index(name="units")
    by_sku = by_sku[by_sku["units"] > 0]
    if by_sku.empty:
        return []
    by_sku["rank"] = by_sku.groupby(BRANCH_COL, observed=True)["units"].rank(method="first", ascending=False)
    totals = by_sku.groupby(BRANCH_COL, observed=True)["units"].agg(["sum", "size"])
    top5 = by_sku[by_sku["rank"] <= 5].groupby(BRANCH_COL, observed=True)["units"].sum()
    rows = [
        {
            "branch": str(branch),
            "sku_count": int(r["size"]),
            "top5_share_pct": round(float(top5.get(branch, 0.0)) / float(r["sum"]) * 100, 1),
            "demand_units": round(float(r["sum"]), 2),
        }
        for branch, r in totals.iterrows()
        if float(r["sum"])
    ]
    return sorted(rows, key=lambda row: row["demand_units"], reverse=True)[:top]


def _coverage(frame: pd.DataFrame, top: int = 8) -> list[dict[str, Any]]:
    """Months observed against months in the window, per branch."""
    if frame.empty:
        return []
    window = int(frame[PERIOD_COL].nunique())
    observed_mask = ~frame["is_materialised"].fillna(False).astype(bool)
    work = pd.DataFrame(
        {
            "branch": frame[BRANCH_COL].astype("object"),
            "ordered": pd.to_numeric(frame[TARGET_COL], errors="coerce").fillna(0.0),
            "observed_period": frame[PERIOD_COL].where(observed_mask),
        }
    )
    agg = work.groupby("branch", observed=True).agg(observed=("observed_period", "nunique"), units=("ordered", "sum"))
    rows = [
        {
            "branch": str(branch),
            "observed_months": int(r["observed"]),
            "window_months": window,
            "coverage_pct": _ratio(float(r["observed"]), window),
            "demand_units": round(float(r["units"]), 2),
        }
        for branch, r in agg.iterrows()
    ]
    return sorted(rows, key=lambda row: row["demand_units"], reverse=True)[:top]


def summary(panel: pd.DataFrame, scope: AnalyticsScope) -> dict[str, Any]:
    """Everything the Demand Analytics page renders, in one response."""
    resolved = scope.normalised()
    frame = _apply_scope(panel, resolved)

    if frame.empty:
        return {
            "scope": resolved.__dict__,
            "empty": True,
            "reason": "No panel row matches this combination of branch, product group, value class and period.",
            "available_grains": list(AVAILABLE_GRAINS),
            "grain_note": GRAIN_NOTE,
        }

    ordered = float(pd.to_numeric(frame[TARGET_COL], errors="coerce").fillna(0.0).sum())
    known = frame[frame["despatched_qty"].notna()]
    despatched = float(pd.to_numeric(known["despatched_qty"], errors="coerce").fillna(0.0).sum())
    ordered_known = float(pd.to_numeric(known[TARGET_COL], errors="coerce").fillna(0.0).sum())
    order_rows = int((frame["target_source"] == "order").sum())
    periods = sorted(frame["period"].unique())

    return {
        "scope": resolved.__dict__,
        "empty": False,
        "window": {"start": periods[0], "end": periods[-1], "periods": len(periods)},
        "available_grains": list(AVAILABLE_GRAINS),
        "grain_note": GRAIN_NOTE,
        "kpis": {
            "demand_value": round(float(frame["demand_value"].sum()), 2),
            "demand_units": round(ordered, 2),
            "shortfall_units": round(float(frame["shortfall_positive"].fillna(0.0).sum()), 2),
            "fill_rate_pct": _ratio(despatched, ordered_known),
            "order_share_pct": _ratio(order_rows, len(frame)),
            "censored_rows": int(frame["is_censored"].fillna(False).astype(bool).sum()),
            "series_count": int(frame[SERIES_COL].nunique()),
            "branch_count": int(frame[BRANCH_COL].nunique()),
            "sku_count": int(frame[SKU_COL].nunique()),
            "rows": int(len(frame)),
            "despatch_rows_excluded_from_fill_rate": int(len(frame) - len(known)),
        },
        "trend": _trend(frame, resolved.grain),
        "by_branch": _by_dimension(frame, BRANCH_COL, "branch"),
        "by_product_group": _by_dimension(frame, GROUP_COL, "product_group"),
        "by_value_class": _by_dimension(frame, "value_class", "value_class"),
        # Per SKU, which nothing else in the payload carried. On a
        # twenty-product workspace a page with no SKU breakdown is missing
        # the axis the whole scope is defined on.
        "by_sku": _by_dimension(frame, SKU_COL, "sku"),
        "by_glass_type": _by_dimension(frame, "glass_type", "glass_type"),
        "by_vehicle_category": _by_dimension(frame, "vehicle_category", "vehicle_category"),
        "by_vehicle_age": _by_dimension(frame, "vehicle_age_category", "vehicle_age"),
        "branch_by_group": _cross_tab(frame),
        "branch_over_time": _branch_over_time(frame, resolved.grain),
        "seasonality": _seasonality(frame),
        "concentration": _concentration(frame),
        "coverage": _coverage(frame),
        "notes": [
            "Demand value is ordered quantity x that month's mean MRP, in rupees. "
            "MRP is a historical column: it is used here to value past demand and "
            "is never fed to a model as a future-known driver.",
            "Fill rate is despatched / ordered, computed only over months where a "
            f"despatch figure exists. {int(len(frame) - len(known)):,} row(s) in this "
            "selection are sales-proxy months with no recorded despatch and are "
            "excluded from that ratio rather than counted as zero.",
            "Ordered quantity is the demand target. A sales-proxy row is a labelled "
            "substitute, never the same measurement as an order.",
        ],
    }


# ----------------------------------------------------------------------
# Operational exceptions
# ----------------------------------------------------------------------

#: Each exception is a real, checkable condition on a panel or stock row, with
#: the definition the UI displays verbatim. Severity is assigned by how
#: directly the condition blocks a despatch, not by size.
EXCEPTION_TYPES: dict[str, dict[str, str]] = {
    "censored_line": {
        "label": "Short despatch",
        "severity": "critical",
        "definition": "Despatched quantity is below ordered quantity, so the ordered figure is a lower bound on true demand.",
        "measure": "units short",
    },
    "zero_stock_live_demand": {
        "label": "Zero stock, live demand",
        "severity": "critical",
        "definition": "No usable stock at this branch x SKU while demand was ordered in the last six months of history.",
        "measure": "recent demand units",
    },
    "over_despatch": {
        "label": "Over-despatch",
        "severity": "high",
        "definition": "Despatched quantity exceeds ordered quantity. Net and gross shortfall differ because of these lines.",
        "measure": "units over",
    },
    "negative_stock_row": {
        "label": "Negative stock row",
        "severity": "high",
        "definition": "The stock snapshot carries a negative quantity for this position. Surfaced, never clamped to zero.",
        "measure": "rows",
    },
    "unmapped_sku": {
        "label": "SKU not in product master",
        "severity": "medium",
        "definition": "The SKU appears in demand or stock but has no product-master row, so its attributes are unknown.",
        "measure": "demand units",
    },
    "non_glass_stock": {
        "label": "Non-glass SKU holding stock",
        "severity": "medium",
        "definition": "Usable stock is held against a SKU the product master classifies as non-glass.",
        "measure": "stock units",
    },
}



#: The collection keys an exceptions payload always carries, even when nothing
#: was found. A payload that changes shape when it is empty forces every
#: caller to branch on `empty` before it can read `rows` - and a caller that
#: forgets is a crash rather than an empty table.
_EMPTY_EXCEPTION_COLLECTIONS: dict[str, Any] = {
    "by_severity": [],
    "by_type": [],
    "by_branch": [],
    "by_product_group": [],
    "top_lines": [],
    "rows": [],
    "total_rows": 0,
}

def exceptions(panel: pd.DataFrame, scope: AnalyticsScope, *, recent_months: int = 6) -> dict[str, Any]:
    """The Operational Exceptions page payload.

    The reference page ranks employees by punch exceptions. AIS holds no
    employee data and must never acquire any, so the ranked entity is the
    branch x SKU line and every exception is a supply or data condition.

    Built with vectorised group-bys and one concat rather than a loop over
    series: the loop form took 25 s on the real panel because it touched
    ~68,000 series individually.
    """
    resolved = scope.normalised()
    frame = _apply_scope(panel, resolved)
    if frame.empty:
        return {
            "scope": resolved.__dict__,
            "empty": True,
            "reason": "No panel row matches this selection.",
            "types": EXCEPTION_TYPES,
            "kpis": {"total_lines": 0},
            **_EMPTY_EXCEPTION_COLLECTIONS,
        }

    max_period = int(panel[PERIOD_COL].max())
    recent_cut = max_period - recent_months + 1

    dims = [SERIES_COL, BRANCH_COL, SKU_COL, GROUP_COL, "value_class"]
    parts: list[pd.DataFrame] = []

    def emit(kind: str, grouped: pd.DataFrame, units_col: str) -> None:
        if grouped.empty:
            return
        block = grouped.rename(columns={units_col: "units"}).copy()
        block["type"] = kind
        parts.append(block)

    # Short despatch: positive shortfall on a censored row.
    censored = frame[frame["is_censored"].fillna(False).astype(bool)]
    if not censored.empty:
        agg = (
            censored.groupby(dims, observed=True)
            .agg(units=("shortfall_positive", "sum"), occurrences=(TARGET_COL, "size"))
            .reset_index()
        )
        emit("censored_line", agg[agg["units"] > 0], "units")

    # Over-despatch.
    over_qty = pd.to_numeric(frame["over_delivered_qty"], errors="coerce").fillna(0.0)
    over = frame[over_qty > 0].assign(_over=over_qty[over_qty > 0])
    if not over.empty:
        agg = (
            over.groupby(dims, observed=True)
            .agg(units=("_over", "sum"), occurrences=(TARGET_COL, "size"))
            .reset_index()
        )
        emit("over_despatch", agg, "units")

    # Stock-snapshot conditions are properties of the series, so they are read
    # from its latest row rather than counted per month.
    latest = frame.sort_values(PERIOD_COL).drop_duplicates(SERIES_COL, keep="last")
    recent_demand = (
        frame[frame[PERIOD_COL] >= recent_cut]
        .groupby(SERIES_COL, observed=True)[TARGET_COL]
        .sum()
        .rename("recent_units")
    )
    latest = latest.merge(recent_demand, on=SERIES_COL, how="left")
    latest["recent_units"] = latest["recent_units"].fillna(0.0)
    usable = pd.to_numeric(latest["usable_qty"], errors="coerce").fillna(0.0)

    zero_stock = latest[(usable <= 0) & (latest["recent_units"] > 0)]
    if not zero_stock.empty:
        block = zero_stock[dims + ["recent_units"]].copy()
        block["occurrences"] = 1
        emit("zero_stock_live_demand", block, "recent_units")

    negative = latest[latest["has_negative_row"].fillna(False).astype(bool)]
    if not negative.empty:
        block = negative[dims].copy()
        block["units"] = 1.0
        block["occurrences"] = 1
        emit("negative_stock_row", block, "units")

    unmapped_series = latest.loc[~latest["in_product_master"].fillna(True).astype(bool), SERIES_COL]
    if len(unmapped_series):
        totals = (
            frame[frame[SERIES_COL].isin(set(unmapped_series))]
            .groupby(dims, observed=True)
            .agg(units=(TARGET_COL, "sum"), occurrences=(TARGET_COL, "size"))
            .reset_index()
        )
        emit("unmapped_sku", totals, "units")

    non_glass = latest[latest["is_non_glass"].fillna(False).astype(bool) & (usable > 0)]
    if not non_glass.empty:
        block = non_glass[dims].copy()
        block["units"] = pd.to_numeric(non_glass["usable_qty"], errors="coerce").fillna(0.0).to_numpy()
        block["occurrences"] = 1
        emit("non_glass_stock", block, "units")

    if not parts:
        return {
            "scope": resolved.__dict__,
            "empty": True,
            "reason": "No exception condition is present in this selection.",
            "types": EXCEPTION_TYPES,
            "kpis": {"total_lines": 0},
            **_EMPTY_EXCEPTION_COLLECTIONS,
        }

    combined = pd.concat(parts, ignore_index=True)
    combined["severity"] = combined["type"].map(lambda k: EXCEPTION_TYPES[k]["severity"])
    combined["label"] = combined["type"].map(lambda k: EXCEPTION_TYPES[k]["label"])
    combined["units"] = pd.to_numeric(combined["units"], errors="coerce").fillna(0.0).round(2)
    combined["occurrences"] = pd.to_numeric(combined["occurrences"], errors="coerce").fillna(1).astype(int)

    def rows_for(frame_slice: pd.DataFrame) -> list[dict[str, Any]]:
        return [
            {
                "type": r["type"],
                "label": r["label"],
                "severity": r["severity"],
                "definition": EXCEPTION_TYPES[r["type"]]["definition"],
                "measure": EXCEPTION_TYPES[r["type"]]["measure"],
                "series_id": str(r[SERIES_COL]),
                "branch": str(r[BRANCH_COL]),
                "sku": str(r[SKU_COL]),
                "product_group": str(r[GROUP_COL]),
                "value_class": str(r["value_class"]),
                "units": float(r["units"]),
                "occurrences": int(r["occurrences"]),
            }
            for _, r in frame_slice.iterrows()
        ]

    by_type = [
        {
            "type": str(kind),
            "name": EXCEPTION_TYPES[str(kind)]["label"],
            "severity": EXCEPTION_TYPES[str(kind)]["severity"],
            "lines": int(group["units"].size),
            "units": round(float(group["units"].sum()), 2),
        }
        for kind, group in combined.groupby("type", observed=True)
    ]
    by_type.sort(key=lambda r: r["lines"], reverse=True)

    def group_count(column: str, key: str) -> list[dict[str, Any]]:
        agg = combined.groupby(column, observed=True).agg(lines=("units", "size"), units=("units", "sum"))
        rows = [
            {"name": str(idx), key: str(idx), "lines": int(r["lines"]), "units": round(float(r["units"]), 2)}
            for idx, r in agg.iterrows()
        ]
        return sorted(rows, key=lambda r: r["lines"], reverse=True)

    severity_counts = combined["severity"].value_counts().to_dict()
    ranked = combined.sort_values("units", ascending=False)
    severity_order = combined["severity"].map({"critical": 0, "high": 1, "medium": 2}).fillna(3)
    detail = combined.assign(_order=severity_order).sort_values(["_order", "units"], ascending=[True, False])

    return {
        "scope": resolved.__dict__,
        "empty": False,
        "types": EXCEPTION_TYPES,
        "recent_window_months": recent_months,
        "kpis": {
            "total_lines": int(len(combined)),
            "critical_lines": int(severity_counts.get("critical", 0)),
            "high_lines": int(severity_counts.get("high", 0)),
            "medium_lines": int(severity_counts.get("medium", 0)),
            "short_despatch_lines": int((combined["type"] == "censored_line").sum()),
            "zero_stock_live_demand_lines": int((combined["type"] == "zero_stock_live_demand").sum()),
            "units_affected": round(float(combined["units"].sum()), 2),
        },
        "by_severity": [
            {"name": str(name), "severity": str(name), "lines": int(count)}
            for name, count in sorted(severity_counts.items(), key=lambda kv: -kv[1])
        ],
        "by_type": by_type,
        "by_branch": group_count(BRANCH_COL, "branch"),
        "by_product_group": group_count("value_class", "product_group"),
        "top_lines": rows_for(ranked.head(25)),
        "rows": rows_for(detail.head(200)),
        "total_rows": int(len(combined)),
        "notes": [
            "Every exception here is a checkable condition on a real panel or stock row. "
            "The definition of each is shown with it.",
            "The ranked entity is a branch x SKU line. AIS holds no employee, attendance "
            "or payroll data, and the reference's employee ranking has no AIS equivalent "
            "by design.",
            "Stock conditions come from a single snapshot dated 2026-08-01 while demand "
            "history ends 2026-07, so they are current-snapshot findings, not a trend.",
            "The detail table shows the 200 most severe lines of "
            f"{int(len(combined)):,}; the breakdown charts above count all of them.",
        ],
    }


# ----------------------------------------------------------------------
# Branch scorecard
# ----------------------------------------------------------------------

#: The reference's Manager Scorecard rates a site out of 100 on four measures,
#: each with a target and a good/poor scale. Same structure, AIS measures. Every
#: one is an operational property of a branch, never of a person.
SCORECARD_SCALES: dict[str, dict[str, Any]] = {
    "fill_rate": {"good": 100.0, "poor": 70.0, "target": 95.0, "higher_is_better": True, "unit": "%"},
    "short_despatch_share": {"good": 0.0, "poor": 25.0, "target": 5.0, "higher_is_better": False, "unit": "%"},
    "demand_stability": {"good": 0.0, "poor": 80.0, "target": 35.0, "higher_is_better": False, "unit": "%"},
    "coverage": {"good": 100.0, "poor": 40.0, "target": 80.0, "higher_is_better": True, "unit": "%"},
}

SCORECARD_LABELS = {
    "fill_rate": "Fill rate",
    "short_despatch_share": "Short-despatch share",
    "demand_stability": "Demand variability",
    "coverage": "Months with demand",
}


def branch_scorecard(panel: pd.DataFrame, scope: AnalyticsScope, *, limit: int = 8) -> dict[str, Any]:
    """Per-branch operational scorecard, ranked.

    Deliberately rates how a branch is running and never an individual — the
    reference makes the same point in its own note, and it matters more here
    because AIS has no personnel data at all.
    """
    resolved = scope.normalised()
    frame = _apply_scope(panel, resolved)
    if frame.empty:
        return {"scales": SCORECARD_SCALES, "labels": SCORECARD_LABELS, "branches": [], "empty": True}

    window_periods = int(frame[PERIOD_COL].nunique())
    branches: list[dict[str, Any]] = []

    for branch, group in frame.groupby(BRANCH_COL, observed=True):
        known = group[group["despatched_qty"].notna()]
        ordered_known = float(pd.to_numeric(known[TARGET_COL], errors="coerce").fillna(0.0).sum())
        despatched = float(pd.to_numeric(known["despatched_qty"], errors="coerce").fillna(0.0).sum())
        ordered = float(pd.to_numeric(group[TARGET_COL], errors="coerce").fillna(0.0).sum())

        monthly = group.groupby(PERIOD_COL, observed=True)[TARGET_COL].sum()
        mean = float(monthly.mean()) if len(monthly) else 0.0
        variability = round(float(monthly.std(ddof=0)) / mean * 100, 1) if mean else None
        observed = int(group.loc[~group["is_materialised"].fillna(False).astype(bool), PERIOD_COL].nunique())

        values = {
            "fill_rate": _ratio(despatched, ordered_known),
            "short_despatch_share": _ratio(float(group["shortfall_positive"].fillna(0).sum()), ordered),
            "demand_stability": variability,
            "coverage": _ratio(observed, window_periods),
        }
        components = {k: _score(v, SCORECARD_SCALES[k]) for k, v in values.items()}
        scored = [v for v in components.values() if v is not None]
        overall = round(sum(scored) / len(scored)) if scored else None
        off_target = [
            k
            for k, v in values.items()
            if v is not None
            and (
                v < SCORECARD_SCALES[k]["target"]
                if SCORECARD_SCALES[k]["higher_is_better"]
                else v > SCORECARD_SCALES[k]["target"]
            )
        ]
        worst = min(
            (k for k, v in components.items() if v is not None), key=lambda k: components[k], default=None
        )
        branches.append(
            {
                "branch": str(branch),
                "score": overall,
                "metric_values": values,
                "score_components": components,
                "off_target": off_target,
                "worst_metric": worst,
                "demand_units": round(ordered, 2),
                "demand_value": round(float(group["demand_value"].sum()), 2),
                "sku_count": int(group[SKU_COL].nunique()),
            }
        )

    branches.sort(key=lambda b: (b["score"] is None, -(b["score"] or 0)))
    for rank, branch in enumerate(branches, start=1):
        branch["rank"] = rank

    return {
        "scales": SCORECARD_SCALES,
        "labels": SCORECARD_LABELS,
        "branches": branches[:limit],
        "total_branches": len(branches),
        "empty": False,
        "note": (
            "Each branch scores out of 100 across four operational measures, with the "
            "target marked on every bar. This rates how a branch is running, never an "
            "individual — AIS holds no personnel data."
        ),
    }


def _score(value: float | None, scale: dict[str, Any]) -> int | None:
    """Linear 0-100 score between the scale's poor and good ends."""
    if value is None:
        return None
    good, poor = float(scale["good"]), float(scale["poor"])
    if good == poor:
        return None
    raw = (value - poor) / (good - poor)
    return int(round(max(0.0, min(1.0, raw)) * 100))


def series_options(panel: pd.DataFrame, *, branch: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    """Branch x SKU options for the assistant and explorer scope pickers."""
    frame = panel if not branch else panel[panel[BRANCH_COL] == branch]
    if frame.empty:
        return []
    totals = (
        frame.groupby([SERIES_COL, BRANCH_COL, SKU_COL], observed=True)[TARGET_COL]
        .sum()
        .sort_values(ascending=False)
        .head(limit)
    )
    return [
        {
            "series_id": str(series_id),
            "branch": str(branch_key),
            "sku": str(sku),
            "demand_units": round(float(units), 2),
            "label": f"{branch_key} · {sku}",
        }
        for (series_id, branch_key, sku), units in totals.items()
    ]


# ----------------------------------------------------------------------
# Lead time
# ----------------------------------------------------------------------
#
# The lead-time file is one of the five client sources, and until now the only
# place its figures surfaced was a single column in the replenishment table and
# the ingestion controls in Data Studio. Two of the three computed columns -
# `std_lead_time_days` and `transit_lead_time_days` - reached no screen at all.
#
# This exposes them, and it is careful about three things the raw columns will
# mislead a reader about:
#
# **`std` of zero is ambiguous.** It means either that every observed receipt
# for that branch had an identical lead time, or that there was only one
# observation. `branch_dim` carries no observation count, so the two cannot be
# told apart here, and the payload says so rather than presenting zero
# variability as a reliability finding.
#
# **Transit can exceed total.** BAWAL carries a 0-day average lead time against
# a 44-day transit time, which cannot both be right. Those rows are reported as
# anomalies instead of being plotted as a negative gap.
#
# **This is a per-branch average, not the line-level distribution.** The
# ingestion control reports a median across order lines; these are means per
# branch. Different populations, and quoting one as the other would be wrong.

#: A branch whose average lead time is this or below is treated as suspicious
#: rather than fast: a same-day replenishment across this network is not
#: credible, and the control totals show the column has unparseable rows.
IMPLAUSIBLE_LEAD_TIME_DAYS = 0.0


def lead_time(branch_dim: pd.DataFrame, *, worst: int = 8) -> dict[str, Any]:
    """Per-branch lead time, its variability, and what looks wrong.

    Reads `branch_dim` (57 rows), so this is cheap enough to compute per
    request without the caching the panel aggregations need.
    """
    if branch_dim.empty:
        return {"empty": True, "reason": "Preprocessing produced no branch dimension."}

    frame = branch_dim.copy()
    avg = pd.to_numeric(frame.get("avg_lead_time_days"), errors="coerce")
    std = pd.to_numeric(frame.get("std_lead_time_days"), errors="coerce")
    transit = pd.to_numeric(frame.get("transit_lead_time_days"), errors="coerce")

    frame["avg_days"] = avg
    frame["std_days"] = std
    frame["transit_days"] = transit
    # Coefficient of variation: spread relative to the mean, which is what makes
    # a 2-day spread on a 3-day lead time worse than the same spread on 12 days.
    frame["cv_pct"] = (std / avg.where(avg > 0) * 100).round(1)
    frame["handling_days"] = (avg - transit).round(2)

    rows = [
        {
            "branch": str(row.get("canonical_branch")),
            "region": str(row.get("region") or "UNKNOWN"),
            "avg_days": _safe(row.get("avg_days")),
            "std_days": _safe(row.get("std_days")),
            "transit_days": _safe(row.get("transit_days")),
            "cv_pct": _safe(row.get("cv_pct")),
            # Total minus transit: the part of the wait that is not the journey.
            # Negative means the two columns disagree, which is an anomaly, not
            # a negative duration.
            "handling_days": _safe(row.get("handling_days")),
            "holds_stock": bool(row.get("holds_stock", False)),
        }
        for _, row in frame.iterrows()
    ]

    measured = [r for r in rows if r["avg_days"] is not None and r["avg_days"] > IMPLAUSIBLE_LEAD_TIME_DAYS]
    averages = sorted(r["avg_days"] for r in measured)
    spreads = sorted(r["std_days"] for r in measured if r["std_days"] is not None)

    def quantile(values: list[float], q: float) -> float | None:
        if not values:
            return None
        return round(float(np.quantile(values, q)), 2)

    anomalies: list[dict[str, Any]] = []
    for row in rows:
        if row["avg_days"] is None:
            anomalies.append({**row, "reason": "No average lead time was computed for this branch."})
        elif row["avg_days"] <= IMPLAUSIBLE_LEAD_TIME_DAYS:
            anomalies.append(
                {
                    **row,
                    "reason": (
                        "Average lead time is zero days. A same-day replenishment is not "
                        "credible across this network, so this reads as a gap in the source "
                        "rather than a fast branch."
                    ),
                }
            )
        if row["handling_days"] is not None and row["handling_days"] < 0:
            anomalies.append(
                {
                    **row,
                    "reason": (
                        f"Transit time ({row['transit_days']}d) exceeds the total lead time "
                        f"({row['avg_days']}d). Both cannot be right; the journey cannot be "
                        "longer than the wait that contains it."
                    ),
                }
            )

    zero_variability = [r["branch"] for r in measured if r["std_days"] == 0]

    # Distribution of the per-branch averages, in whole-day buckets.
    buckets: dict[str, int] = {}
    for row in measured:
        days = row["avg_days"] or 0
        label = f"{int(days)}d" if days < 8 else "8d+"
        buckets[label] = buckets.get(label, 0) + 1
    order = [f"{d}d" for d in range(0, 8)] + ["8d+"]
    distribution = [{"bucket": b, "branches": buckets[b]} for b in order if b in buckets]

    return {
        "empty": False,
        "kpis": {
            "branches": len(rows),
            "branches_with_a_usable_lead_time": len(measured),
            "median_avg_days": quantile(averages, 0.5),
            "p95_avg_days": quantile(averages, 0.95),
            "max_avg_days": max(averages) if averages else None,
            "median_std_days": quantile(spreads, 0.5),
            "branches_zero_variability": len(zero_variability),
            "anomaly_count": len(anomalies),
        },
        "by_branch": sorted(measured, key=lambda r: (r["avg_days"] or 0), reverse=True),
        "least_reliable": sorted(
            [r for r in measured if r["cv_pct"] is not None],
            key=lambda r: r["cv_pct"],
            reverse=True,
        )[:worst],
        "distribution": distribution,
        "anomalies": anomalies,
        "zero_variability_branches": zero_variability,
        "notes": [
            "These are per-branch averages from the lead-time source file. The "
            "line-level median reported by the ingestion controls in Data Studio is a "
            "different population and the two are not interchangeable.",
            "Variability is shown as the coefficient of variation - the spread relative "
            "to the mean - because a 2-day spread matters far more on a 3-day lead time "
            "than on a 12-day one.",
            "Handling days is total lead time minus transit time: the part of the wait "
            "that is not the journey itself.",
            f"A standard deviation of zero ({len(zero_variability)} branch(es)) is "
            "ambiguous: it means either that every observed receipt took the same time, "
            "or that there was only one observation. The branch dimension carries no "
            "observation count, so the two cannot be distinguished here.",
            "**Lead-time variability does not currently affect any recommendation.** The "
            "protection period is review period + average lead time, so a branch with a "
            "volatile lead time is given the same cover as a stable one with the same "
            "mean. Surfacing that is the point of this panel; changing the calculation "
            "would change every recommended order quantity and is a separate decision.",
        ],
    }


# ----------------------------------------------------------------------
# Result cache
# ----------------------------------------------------------------------
#
# A full summary is a ~5 s pass over 1.5 M rows and the exceptions payload
# touches the stock snapshot as well. Both are pure functions of (panel,
# scope), and the panel only changes when a new build is published - so the
# result is cached per scope and the first request pays the cost once.
#
# Keyed on the panel path so a rebuilt panel is a different key rather than a
# stale hit, exactly as `load_panel` is.

_SUMMARY_CACHE: dict[tuple, dict[str, Any]] = {}
_EXCEPTIONS_CACHE: dict[tuple, dict[str, Any]] = {}
_SCORECARD_CACHE: dict[tuple, dict[str, Any]] = {}
#: Bounded so a caller cycling through every branch cannot grow it without end.
_CACHE_LIMIT = 64


def _key(panel_path: str, scope: AnalyticsScope, *extra: Any) -> tuple:
    """Every scope field, derived rather than listed.

    This used to name the fields by hand, and adding `sku` to the scope
    without adding it here meant one SKU's answer was served for every other
    one - a filter that silently did nothing. `astuple` cannot forget a field
    that exists, so the next filter added to the scope is keyed correctly
    without anyone remembering to come here.
    """
    return (panel_path, *dataclasses.astuple(scope.normalised()), *extra)


def _cached(store: dict[tuple, dict[str, Any]], key: tuple, build: Any) -> dict[str, Any]:
    hit = store.get(key)
    if hit is not None:
        return hit
    value = build()
    if len(store) >= _CACHE_LIMIT:
        store.clear()
    store[key] = value
    return value


def cached_summary(panel: pd.DataFrame, panel_path: str, scope: AnalyticsScope) -> dict[str, Any]:
    return _cached(_SUMMARY_CACHE, _key(panel_path, scope), lambda: summary(panel, scope))


def cached_exceptions(panel: pd.DataFrame, panel_path: str, scope: AnalyticsScope) -> dict[str, Any]:
    return _cached(_EXCEPTIONS_CACHE, _key(panel_path, scope), lambda: exceptions(panel, scope))


def cached_branch_scorecard(
    panel: pd.DataFrame, panel_path: str, scope: AnalyticsScope, limit: int
) -> dict[str, Any]:
    return _cached(
        _SCORECARD_CACHE,
        _key(panel_path, scope, limit),
        lambda: branch_scorecard(panel, scope, limit=limit),
    )


def clear_caches() -> None:
    """Drop every cached result. Used by tests, which build small panels."""
    _SUMMARY_CACHE.clear()
    _EXCEPTIONS_CACHE.clear()
    _SCORECARD_CACHE.clear()
    load_panel.cache_clear()

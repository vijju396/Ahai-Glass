"""Stated lead time against what the order dates actually show, per branch.

Both halves of this already exist in the client's own files and neither is
edited to produce it (D-105):

- **Location Master** carries `Avg Lead Time`, `Std. LeadTime`,
  `Transit Lead Time`, `Service Factor` and `Truck (MoQ)` per branch - static
  values someone on the client side computed and typed in.
- **Orders & Receipts** carries `Order Date`, `Despatch Date` and
  `Invoice Date` per order line - raw timestamps.

Subtracting one existing date column from another is the same kind of derived
view `MRP Value` already is in that file (Quantity x MRP Rate). It reads two
columns together; it changes neither.

**This is a monitoring view, not a correction.** Nothing here rewrites the
master's numbers, drops an order line, or feeds a recommendation. It puts the
stated figure beside the observed one and leaves the difference for the client
to judge - which is the only honest thing to do, because the master value may
be a deliberate planning allowance rather than a claim about observed timing.

Three measured facts shape what this module will and will not report.

**Order -> Despatch is usable.** 775,628 of 775,912 lines produce a
non-negative duration of 90 days or less. The 284 excluded are reported, not
silently dropped; the worst carries a despatch date of 2002-05-26 against a
2025 order.

**Despatch -> Invoice is not a sequential leg.** 285,995 of 708,317 lines -
40% - have an invoice dated *before* the despatch, and the negatives cluster at
exactly -1 and -2 days rather than scattering. That is a billing practice, not
corruption, so this module reports the leg's *shape* and refuses to present it
as a duration. Calling it "the invoicing leg" and averaging it would produce a
number that means nothing.

**The master's own file has a totals row.** The last row of Location Master
carries no branch name and holds `Std. LeadTime` 188, `Service Factor` 225 and
`Truck (MoQ)` 61.25 - a column sum, not a branch. It is excluded by requiring a
branch name, and a `Service Factor` of 225 would otherwise have gone into a
safety-stock formula as a z-score.
"""

from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Any

import pandas as pd

from app.domain.ais import cleaning

logger = logging.getLogger(__name__)

#: Durations outside this are excluded from every aggregate and counted
#: separately. 90 days is not a business rule - it is wide enough that no
#: plausible replenishment falls outside it, so anything beyond is a date
#: error rather than a slow delivery.
MAX_PLAUSIBLE_DAYS = 90

#: Columns read from Location Master. Nothing else is touched.
MASTER_FIELDS = (
    "Avg Lead Time",
    "Std. LeadTime",
    "Transit Lead Time",
    "Service Factor",
    "Truck (MoQ)",
)

#: A service factor is a z-score: 1.0 is about 84% service, 1.65 about 95%.
#: Anything outside this cannot be one, and the file contains a 225.
SERVICE_FACTOR_MAX = 5.0


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def read_master(path: Path) -> pd.DataFrame:
    """Location Master's lead-time fields, one row per named branch.

    The file's first line is the title `Branch Master`, so the header is the
    second. Rows without a branch name are dropped - that is what excludes the
    totals row at the bottom, whose `Service Factor` of 225 is a column sum.
    """
    frame = pd.read_csv(path, skiprows=1)
    frame = frame[frame["Branch Name"].notna()].copy()
    frame["branch"] = frame["Branch Name"].map(cleaning.canonical_branch)
    out = pd.DataFrame({"branch": frame["branch"]})
    for field in MASTER_FIELDS:
        out[field] = pd.to_numeric(frame.get(field), errors="coerce")
    return out[out["branch"] != ""].drop_duplicates("branch").reset_index(drop=True)


def read_durations(path: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Per-line durations from the three existing date columns.

    Returns the usable lines and a dict of what was excluded and why. The
    exclusions are part of the answer: a view that reported 775,628 lines
    without saying 284 were dropped would be overstating its own coverage.
    """
    frame = pd.read_excel(path)
    total = len(frame)
    branch = frame["Depo"].map(cleaning.canonical_branch)
    ordered = pd.to_datetime(frame["Order Date"], errors="coerce")
    despatched = pd.to_datetime(frame["Despatch Date"], errors="coerce")
    invoiced = pd.to_datetime(frame["Invoice Date"], errors="coerce")

    order_to_despatch = (despatched - ordered).dt.days
    despatch_to_invoice = (invoiced - despatched).dt.days

    usable = (
        order_to_despatch.notna()
        & (order_to_despatch >= 0)
        & (order_to_despatch <= MAX_PLAUSIBLE_DAYS)
    )
    rejected = order_to_despatch.notna() & ~usable
    notes = {
        "lines_total": int(total),
        "lines_usable": int(usable.sum()),
        "lines_missing_a_date": int(order_to_despatch.isna().sum()),
        "lines_out_of_range": int(rejected.sum()),
        "worst_excluded_days": (
            _number(order_to_despatch[rejected].min()) if rejected.any() else None
        ),
        # Reported as a shape, never averaged into a duration.
        "invoice_rows": int(despatch_to_invoice.notna().sum()),
        "invoice_before_despatch": int((despatch_to_invoice < 0).sum()),
        "invoice_same_day": int((despatch_to_invoice == 0).sum()),
        "invoice_after_despatch": int((despatch_to_invoice > 0).sum()),
    }
    lines = pd.DataFrame(
        {
            "branch": branch[usable],
            # Joined on `Oracle No`, which is the order file's master key
            # (D-017). `Material Code` does not reproduce the canonical SKU.
            "sku": frame["Oracle No"].map(cleaning.canonical_sku)[usable],
            "period": ordered[usable].dt.to_period("M").astype(str),
            "order_to_despatch": order_to_despatch[usable],
        }
    )
    return lines, notes


def restrict(
    lines: pd.DataFrame,
    *,
    branches: list[str] | None = None,
    skus: list[str] | None = None,
) -> pd.DataFrame:
    """Cut to a workspace before any aggregate is taken.

    Restricting after aggregating would produce figures computed over the whole
    network and then labelled with two branch names, which is the exact failure
    `workspace_scope` exists to prevent (D-049).
    """
    out = lines
    if branches:
        wanted = {b.strip().upper() for b in branches if b.strip()}
        out = out[out["branch"].isin(wanted)]
    if skus:
        wanted_skus = {s.strip().upper() for s in skus if s.strip()}
        out = out[out["sku"].isin(wanted_skus)]
    return out


def by_sku(lines: pd.DataFrame, *, limit: int = 40) -> list[dict[str, Any]]:
    """Observed duration per SKU, busiest first.

    There is no stated per-SKU lead time to compare against - Location Master
    is branch-grained - so this side stands alone and the payload does not
    invent a counterpart for it.
    """
    if lines.empty:
        return []
    grouped = lines.groupby("sku")["order_to_despatch"]
    frame = pd.DataFrame(
        {
            "lines": grouped.size(),
            "mean": grouped.mean().round(2),
            "median": grouped.median().round(2),
            "p95": grouped.quantile(0.95).round(2),
            "max": grouped.max().round(2),
        }
    ).reset_index().sort_values("lines", ascending=False)
    return frame.head(limit).to_dict("records")


def by_month(lines: pd.DataFrame) -> list[dict[str, Any]]:
    """Mean duration per order month, overall and per branch.

    Monthly rather than smoothed: this is a description of what happened, and a
    rolling mean would blur the month a change started.
    """
    if lines.empty:
        return []
    overall = lines.groupby("period")["order_to_despatch"].agg(["size", "mean"])
    per_branch = lines.pivot_table(
        index="period", columns="branch", values="order_to_despatch", aggfunc="mean"
    ).round(2)
    rows: list[dict[str, Any]] = []
    for period, row in overall.iterrows():
        entry: dict[str, Any] = {
            "period": str(period),
            "lines": int(row["size"]),
            "mean": round(float(row["mean"]), 2),
        }
        if period in per_branch.index:
            for branch_name, value in per_branch.loc[period].items():
                entry[str(branch_name)] = None if pd.isna(value) else float(value)
        rows.append(entry)
    return rows


def distribution(lines: pd.DataFrame, *, cap: int = 14) -> list[dict[str, Any]]:
    """How many lines took each whole number of days.

    Capped with a final bucket rather than truncated, so the tail is visible as
    a tail instead of disappearing off the end of the axis.
    """
    if lines.empty:
        return []
    days = lines["order_to_despatch"].astype(int)
    counts = days.where(days <= cap, cap + 1).value_counts().sort_index()
    total = int(counts.sum())
    return [
        {
            "days": int(day) if int(day) <= cap else cap + 1,
            "label": f"{int(day)}" if int(day) <= cap else f"{cap + 1}+",
            "lines": int(count),
            "share_pct": round(100.0 * int(count) / total, 2),
        }
        for day, count in counts.items()
    ]


def trend(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """First third against last third of the observed months.

    Reported as a measured change between two windows, not a fitted slope: a
    slope would imply a model of how lead time moves, and there is none here.
    """
    if len(rows) < 6:
        return None
    window = max(3, len(rows) // 3)
    early = rows[:window]
    late = rows[-window:]

    def weighted(subset: list[dict[str, Any]]) -> float | None:
        total = sum(r["lines"] for r in subset)
        if not total:
            return None
        return sum(r["mean"] * r["lines"] for r in subset) / total

    first, last = weighted(early), weighted(late)
    if first is None or last is None or first == 0:
        return None
    return {
        "early_periods": [early[0]["period"], early[-1]["period"]],
        "late_periods": [late[0]["period"], late[-1]["period"]],
        "early_mean": round(first, 2),
        "late_mean": round(last, 2),
        "change_days": round(last - first, 2),
        "change_pct": round(100.0 * (last - first) / first, 1),
    }


def aggregate(lines: pd.DataFrame) -> pd.DataFrame:
    """Per-branch observed duration, described rather than reduced to a mean.

    The median and p95 are here because the mean alone hides the tail, and the
    tail is what a planner is exposed to: a branch averaging 3 days with a p95
    of 10 stocks out on the p95 days, not the average ones.
    """
    if lines.empty:
        return pd.DataFrame(
            columns=["branch", "lines", "observed_mean", "observed_median",
                     "observed_std", "observed_p95", "observed_max"]
        )
    grouped = lines.groupby("branch")["order_to_despatch"]
    out = pd.DataFrame(
        {
            "lines": grouped.size(),
            "observed_mean": grouped.mean().round(2),
            "observed_median": grouped.median().round(2),
            "observed_std": grouped.std().round(2),
            "observed_p95": grouped.quantile(0.95).round(2),
            "observed_max": grouped.max().round(2),
        }
    ).reset_index()
    return out


def compare(master: pd.DataFrame, observed: pd.DataFrame) -> pd.DataFrame:
    """Stated beside observed. An outer join, so neither side can hide a gap.

    A branch in the master with no orders, and a branch with orders and no
    master row, are both real conditions worth seeing. An inner join would
    make either disappear.
    """
    joined = master.merge(observed, on="branch", how="outer")
    joined["stated_avg"] = joined["Avg Lead Time"]
    joined["stated_std"] = joined["Std. LeadTime"]
    joined["transit"] = joined["Transit Lead Time"]
    joined["service_factor"] = joined["Service Factor"]
    joined["truck_moq"] = joined["Truck (MoQ)"]
    joined["gap_mean"] = (joined["observed_mean"] - joined["stated_avg"]).round(2)
    joined["gap_p95"] = (joined["observed_p95"] - joined["stated_avg"]).round(2)

    def flag(row: pd.Series) -> str | None:
        if pd.isna(row.get("lines")):
            return "No order line matched this branch, so nothing is observed to compare."
        if pd.isna(row.get("stated_avg")):
            return "No stated average in the master, so there is nothing to compare against."
        if row["stated_avg"] <= 0 and (row.get("observed_mean") or 0) > 0:
            return (
                f"The master states a zero-day lead time while orders took "
                f"{row['observed_mean']:,.1f} days on average."
            )
        if (row.get("gap_mean") or 0) > 0:
            return (
                f"Orders took {row['gap_mean']:,.1f} days longer on average than the "
                "master states."
            )
        return None

    joined["review"] = joined.apply(flag, axis=1)
    joined["service_factor_usable"] = joined["service_factor"].between(
        0, SERVICE_FACTOR_MAX, inclusive="both"
    ) & joined["service_factor"].notna()
    return joined.sort_values(
        ["gap_mean", "branch"], ascending=[False, True], na_position="last"
    ).reset_index(drop=True)

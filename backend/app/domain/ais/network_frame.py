"""The whole client network as an analytics frame, without materialising a grid.

Overall Analysis describes demand: totals by branch, value class, glass type and
vehicle category, and those totals over time. The registered panel cannot serve
that question at network scale — it is a full branch x SKU x period grid, and an
unrestricted build materialises every series the extract holds. That was
attempted and **exhausted memory** at 68,675 series over 28 monthly periods
(`panel_service._scope_artifacts`); at the current weekly grain the same build
is 70,089 series over 122 periods, about 8.6 M rows.

So this module assembles the same columns from the preprocessed facts instead.
The facts are already unrestricted — 582,324 order rows and 975,275 sales rows
across all 53 branches and 2,063 SKUs — and a sum over observed rows equals a
sum over the materialised grid, because the rows the grid adds are zeros.

**What this frame is not.** It carries observed rows only. Any figure that
counts *rows*, or divides by a row count, means something different here than on
a panel-backed page: there is no `is_materialised` column and no zero-filled
cell. Totals, shares of a total, and movements over time are exact; row counts
and zero-share statistics are not comparable with the scoped pages. The caller
states this rather than letting a reader assume otherwise (D-138).

**The target rule is the panel's, not a new one.** Ordered quantity is the
target. The sales proxy contributes only periods *before* the order book opens,
as a period filter rather than a row-level preference — inside the order window
a series with no order row has genuinely zero ordered demand, and its invoiced
sales must not overwrite that (D-002). A proxy row's despatch, shortfall and
censoring stay null, never zero, because an invoice records what was sold and
nothing about what was asked for.
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

#: Dimension columns taken from the product master, in the panel's spelling.
PRODUCT_ATTRIBUTES = (
    "glass_type",
    "product_group",
    "value_class",
    "vehicle_category",
    "vehicle_age_category",
    "oem_status",
    "is_non_glass",
    "in_product_master",
    "has_substitute",
    "substitute_sku_1",
)

#: Dimension columns taken from the location master.
BRANCH_ATTRIBUTES = (
    "branch_name",
    "region",
    "zone",
    "supply_hub",
    "tier",
    "in_location_master",
    "avg_lead_time_days",
    "std_lead_time_days",
    "truck_moq",
)


def _to_index(period: pd.Series, grain: str) -> pd.Series:
    """Period label to an orderable integer, matching the panel's convention."""
    from app.ml.features.panel import period_index

    return period.map(lambda value: period_index(str(value), grain))


def build(
    order_fact: pd.DataFrame,
    sales_fact: pd.DataFrame,
    product_dim: pd.DataFrame,
    branch_dim: pd.DataFrame,
    *,
    grain: str = "weekly",
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """One row per observed branch x SKU x period, with the panel's columns.

    Returns the frame and a record of what it covers, so the page can state its
    own coverage instead of implying the panel's.
    """
    # An empty fact arrives with no columns at all, so every later reference
    # raises a KeyError on a name that is simply absent rather than empty. A
    # network with no sales history is a thin deployment, not a failure.
    order_columns = [
        "canonical_branch", "canonical_sku", "period", "ordered_qty", "despatched_qty",
        "shortfall_qty", "over_delivered_qty", "is_censored", "line_count", "mean_mrp",
    ]
    sales_columns = [
        "canonical_branch", "canonical_sku", "period", "invoiced_qty", "line_count",
        "mean_mrp",
    ]
    orders = order_fact.reindex(columns=order_columns).copy()
    sales = sales_fact.reindex(columns=sales_columns).copy()
    if orders.empty:
        raise ValueError(
            "The order fact is empty, so there is no demand to describe. "
            "Re-run preprocessing before reading the network view."
        )
    orders["period_index"] = _to_index(orders["period"], grain)
    sales["period_index"] = _to_index(sales["period"], grain)

    order_window = (int(orders["period_index"].min()), int(orders["period_index"].max()))


    orders["series_id"] = orders["canonical_branch"] + "|" + orders["canonical_sku"]
    sales["series_id"] = sales["canonical_branch"] + "|" + sales["canonical_sku"]

    kept = [
        "series_id", "canonical_branch", "canonical_sku", "period", "period_index",
        "target", "despatched_qty", "shortfall_qty", "over_delivered_qty",
        "is_censored", "line_count", "mean_mrp", "target_source",
    ]
    left = orders.rename(columns={"ordered_qty": "target"})
    left["target_source"] = "order"
    left["is_censored"] = left["is_censored"].astype("boolean")
    for column in ("despatched_qty", "shortfall_qty", "over_delivered_qty"):
        left[column] = left[column].astype("Float64")

    # Period filter, not a row-level preference (D-002).
    proxy = sales.loc[
        sales["period_index"].notna() & (sales["period_index"] < order_window[0])
    ].rename(columns={"invoiced_qty": "target"}).copy()
    proxy["target_source"] = "sales_proxy"
    for column in ("despatched_qty", "shortfall_qty", "over_delivered_qty"):
        proxy[column] = pd.Series([pd.NA] * len(proxy), dtype="Float64")
    proxy["is_censored"] = pd.Series([pd.NA] * len(proxy), dtype="boolean")

    frame = pd.concat(
        [left.reindex(columns=kept), proxy.reindex(columns=kept)], ignore_index=True
    )

    frame = frame.merge(
        product_dim.reindex(columns=["canonical_sku", *PRODUCT_ATTRIBUTES]),
        on="canonical_sku",
        how="left",
    ).merge(
        branch_dim.reindex(columns=["canonical_branch", *BRANCH_ATTRIBUTES]),
        on="canonical_branch",
        how="left",
    )

    # Columns the panel carries that no fact can supply. Present so the shared
    # analytics code finds them, and null rather than zero so nothing reads as
    # a measurement that was never taken.
    for column in ("closing_qty", "closing_value", "usable_qty"):
        frame[column] = pd.Series([pd.NA] * len(frame), dtype="Float64")
    for column in ("stock_row_present", "has_negative_row"):
        frame[column] = pd.Series([pd.NA] * len(frame), dtype="boolean")
    frame["stock_class"] = pd.Series([pd.NA] * len(frame), dtype="string")
    frame["value_unavailable_reason"] = pd.Series([pd.NA] * len(frame), dtype="string")
    # No grid, so nothing here was materialised.
    frame["is_materialised"] = False

    # The same derivation the panel path uses - `demand_value`,
    # `despatch_value`, `shortfall_positive`. `analytics.derive_columns` is
    # public for exactly this: a frame built by hand derives them the same way
    # rather than reimplementing the arithmetic and drifting from it.
    from app.domain.ais import analytics

    frame = analytics.derive_columns(frame)

    # Taken before the categorical conversion below: an unordered categorical
    # refuses min/max, and ordering these by label would be meaningless for
    # every column but this one.
    first = str(frame.loc[frame["period_index"].idxmin(), "period"])
    last = str(frame.loc[frame["period_index"].idxmax(), "period"])
    frame["period"] = frame["period"].astype("string")

    # 1.05 M rows of plain object strings cost 1,267 MB, which is not a frame
    # a request can hold. The dimension columns are low-cardinality by nature -
    # 53 branches, 6 regions, a handful of glass types - so categoricals cut it
    # to a fraction without changing a single value.
    # `period` is deliberately NOT in this list. The shared analytics code
    # takes min/max of it, and an unordered categorical refuses both; making it
    # ordered would work but would quietly impose a sort order on a column
    # other code treats as a plain label. The saving is in `series_id` and
    # `canonical_sku` anyway - 68,597 and 2,315 distinct values against a
    # million rows.
    for column in (
        "canonical_branch", "canonical_sku", "series_id", "target_source",
        *PRODUCT_ATTRIBUTES, *BRANCH_ATTRIBUTES,
    ):
        if column in frame.columns and frame[column].dtype == object:
            frame[column] = frame[column].astype("category")

    # Counted on the order book alone, which is the universe the scope
    # denominator counts (`_demand_universe` reads order_fact). The frame also
    # carries sales-proxy rows for periods before the order book opens, and
    # those bring SKUs that were never ordered - counting them made the banner
    # read "2,315 of 2,063", a numerator larger than its own denominator.
    ordered = frame.loc[frame["target_source"] == "order"]

    coverage = {
        "rows": int(len(frame)),
        "branches": int(ordered["canonical_branch"].nunique()),
        "skus": int(ordered["canonical_sku"].nunique()),
        "skus_including_proxy_only": int(frame["canonical_sku"].nunique()),
        "series": int(frame["series_id"].nunique()),
        "periods": int(frame["period"].nunique()),
        "period_range": [first, last],
        "target_source_rows": {
            str(k): int(v) for k, v in frame["target_source"].value_counts().items()
        },
        "observed_rows_only": True,
        "note": (
            "Assembled from the preprocessed order and sales facts across every "
            "branch and SKU, not from the modelling panel. It carries observed "
            "rows only: totals, shares and trends are exact, but there are no "
            "materialised zero cells, so row counts are not comparable with the "
            "workspace pages."
        ),
    }
    return frame, coverage

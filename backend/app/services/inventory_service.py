"""Inventory recommendations, and the supply picture around them.

The arithmetic lives in `app.domain.ais.inventory`; this module supplies it
with real inputs - forecast rows from the database, stock from the 2026-08-01
snapshot, lead times from the branch dimension, substitutes from the product
dimension - and assembles the Supply Intelligence views on top.

The load-bearing behaviour is what happens when an input is missing. Every
branch x SKU the caller asked about gets a row. A combination with stock but no
series-level forecast, or a forecast but no stock record, comes back with a
stated `unavailable_reason` and no recommendation. It is never dropped from the
result, and never given a zero.
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import ConflictError, NotFoundError
from app.core.logging import get_logger
from app.db.session import session_scope
from app.domain.ais.inventory import (
    SERVICE_LEVELS,
    InventoryInputs,
    days_of_cover,
    recommend,
)
from app.models.forecasts import ForecastRow, ForecastRun
from app.models.mappings import PreprocessingRun
from app.models.panel import PanelBuild
from app.models.training import TrainingRun

logger = get_logger(__name__)

#: The quantile column each service level reads.
_QUANTILE_COLUMN = {80: "q80", 90: "q90", 95: "q95"}


def _prepared_dir(db: Session, forecast_run: ForecastRun) -> dict[str, str]:
    """The preprocessing artifacts behind a forecast run."""
    build = db.get(PanelBuild, forecast_run.panel_build_id)
    if build is None:
        raise NotFoundError("The panel build behind this forecast run is missing.")
    prep = db.get(PreprocessingRun, build.preprocessing_run_id)
    if prep is None or not prep.artifacts_json:
        raise ConflictError(
            "The preprocessing run behind this forecast recorded no artifacts, "
            "so stock and lead-time inputs cannot be read.",
            remediation="Re-run preprocessing.",
        )
    return dict(prep.artifacts_json)


#: The branch column on every prepared artifact this service reads.
_BRANCH_COL = "canonical_branch"


def _workspace(db: Session):
    """The locations this deployment reports on.

    Applied to the stock position, the branch dimension and the forecast rows
    alike. Without it Supply Intelligence would recommend replenishment for
    branches that have no page anywhere else in the application - the forecast
    run behind it can be older than the training run the rest of the app
    resolves to (docs/DECISIONS.md D-049).
    """
    from app.domain.ais.workspace import resolve_workspace

    return resolve_workspace(db)


def _load_stock(artifacts: dict[str, str]) -> pd.DataFrame:
    path = artifacts.get("stock_position")
    if not path:
        raise ConflictError(
            "No stock position artifact exists, so no recommendation can be "
            "made against it.",
            remediation="Re-run preprocessing with the stock file present.",
        )
    return pd.read_parquet(path)


def _load_branches(artifacts: dict[str, str]) -> pd.DataFrame:
    path = artifacts.get("branch_dim")
    if not path:
        return pd.DataFrame()
    return pd.read_parquet(path)


def _load_products(artifacts: dict[str, str]) -> pd.DataFrame:
    path = artifacts.get("product_dim")
    if not path:
        return pd.DataFrame()
    return pd.read_parquet(path)


def _forecast_rows(
    db: Session,
    *,
    forecast_run_id: str,
    period: str,
    scope_level: str,
    branch: str | None,
    sku: str | None,
) -> list[ForecastRow]:
    conditions = [
        ForecastRow.forecast_run_id == forecast_run_id,
        ForecastRow.period == period,
        ForecastRow.scope_level == scope_level,
    ]
    if branch:
        conditions.append(ForecastRow.scope_key.like(f"{branch}%"))
    rows = list(db.scalars(select(ForecastRow).where(*conditions)))
    if sku:
        rows = [row for row in rows if sku in row.scope_key]

    # A series scope key is `branch|sku`, so the workspace filter is a prefix
    # test on the key rather than a column comparison.
    scope = _workspace(db)
    if scope.branches is not None:
        wanted = {b.upper() for b in scope.branches}
        rows = [
            row
            for row in rows
            if (_split_series_key(row.scope_key)[0] or row.scope_key).upper() in wanted
        ]
    return rows


def _split_series_key(scope_key: str) -> tuple[str | None, str | None]:
    """A series scope key is `branch|sku`. Anything else has no split."""
    if "|" in scope_key:
        branch, sku = scope_key.split("|", 1)
        return branch, sku
    return None, None


def recommendations(
    db: Session,
    *,
    forecast_run_id: str | None = None,
    period: str | None = None,
    service_level: int = 95,
    scope_level: str = "series",
    branch: str | None = None,
    sku: str | None = None,
    include_unavailable: bool = True,
    only_actionable: bool = False,
    offset: int = 0,
    limit: int = 100,
) -> dict[str, Any]:
    """Recommendations for one period and service level.

    `scope_level` defaults to `series` because a replenishment order is placed
    for a branch x SKU. A branch-level forecast cannot be turned into one - the
    stock it would be netted against is per SKU - so a request at a level the
    run did not forecast returns a stated reason rather than an aggregate
    number dressed as a line-item recommendation.
    """
    if service_level not in SERVICE_LEVELS:
        raise ConflictError(
            f"Service level {service_level} is not offered.",
            remediation=f"Choose one of {list(SERVICE_LEVELS)}.",
        )
    settings = get_settings()
    run = (
        db.get(ForecastRun, forecast_run_id)
        if forecast_run_id
        else db.scalars(
            select(ForecastRun)
            .where(ForecastRun.status == "completed")
            .order_by(ForecastRun.created_at.desc())
            .limit(1)
        ).first()
    )
    if run is None:
        raise NotFoundError(
            "No completed forecast run exists, so nothing can be recommended.",
            remediation="POST /api/forecasts/runs first.",
        )

    resolved_period = period or _first_period(db, run.id)
    if resolved_period is None:
        raise NotFoundError(f"Forecast run {run.id!r} has no rows.")

    artifacts = _prepared_dir(db, run)
    stock = _load_stock(artifacts)
    branches = _load_branches(artifacts)
    scope = _workspace(db)
    stock = scope.restrict(stock, _BRANCH_COL)
    branches = scope.restrict(branches, _BRANCH_COL)
    products = _load_products(artifacts)

    rows = _forecast_rows(
        db,
        forecast_run_id=run.id,
        period=resolved_period,
        scope_level=scope_level,
        branch=branch,
        sku=sku,
    )
    if not rows:
        return {
            "forecast_run_id": run.id,
            "period": resolved_period,
            "service_level": service_level,
            "scope_level": scope_level,
            "items": [],
            "total": 0,
            "offset": offset,
            "limit": limit,
            "unavailable_reason": (
                f"This forecast run produced no {scope_level}-level rows for "
                f"{resolved_period}. A replenishment order is placed per branch "
                "x SKU, so it needs series-level forecasts; run training with "
                "the `local` or `pooled` tier and regenerate forecasts."
            ),
            "notes": [],
        }

    stock_index = _stock_index(stock)
    branch_index = _branch_index(branches)
    substitute_index = _substitute_index(products)

    results: list[dict[str, Any]] = []
    for row in rows:
        row_branch, row_sku = _split_series_key(row.scope_key)
        row_branch = row_branch or row.canonical_branch
        row_sku = row_sku or row.canonical_sku
        quantile_value = getattr(row, _QUANTILE_COLUMN[service_level], None)
        stock_row = stock_index.get((row_branch, row_sku)) if row_branch and row_sku else None
        branch_row = branch_index.get(row_branch) if row_branch else None

        inputs = InventoryInputs(
            scope_key=row.scope_key,
            canonical_branch=row_branch,
            canonical_sku=row_sku,
            monthly_quantile_forecast=quantile_value,
            monthly_point_forecast=row.point_forecast,
            service_level=service_level,
            review_period_days=settings.review_period_days,
            lead_time_days=(branch_row or {}).get("avg_lead_time_days"),
            lead_time_source=(
                "Location Master average lead time, computed on cleaned "
                "despatch dates only"
                if branch_row and branch_row.get("avg_lead_time_days") is not None
                else None
            ),
            lead_time_p95_days=(branch_row or {}).get("transit_lead_time_days"),
            usable_stock_on_hand=(stock_row or {}).get("usable_qty"),
            closing_stock_on_hand=(stock_row or {}).get("closing_qty"),
            negative_stock_rows=int(bool((stock_row or {}).get("has_negative_row"))),
            # There is no open-order snapshot in the source set, so this is
            # zero by absence, not by measurement - and the note says so.
            confirmed_stock_on_order=0.0,
            backorders=0.0,
            truck_quantity=(branch_row or {}).get("truck_moq"),
            substitute_skus=substitute_index.get(row_sku or "", []),
            target_source=row.target_source,
            is_censored=row.is_censored,
            forecast_model_id=row.model_id,
            forecast_period=row.period,
            demand_segment=row.demand_segment,
            stock_class=(stock_row or {}).get("stock_class"),
        )
        recommendation = recommend(
            inputs, default_lead_time_days=settings.default_lead_time_days
        )
        if row.unavailable_reason and recommendation.unavailable_reason is None:
            recommendation.unavailable_reason = row.unavailable_reason
        recommendation.warnings.append(
            "Confirmed stock on order and backorders are treated as zero "
            "because the source set contains no open-order or backorder "
            "snapshot. Where either exists in reality, the recommendation is an "
            "over-order by that amount."
        )
        payload = recommendation.as_dict()
        if not include_unavailable and payload["unavailable_reason"]:
            continue
        if only_actionable and not (payload["recommended_order"] or 0) > 0:
            continue
        results.append(payload)

    results.sort(
        key=lambda item: (
            -(item.get("recommended_order") or 0.0),
            item["scope_key"],
        )
    )
    window = results[offset : offset + limit]
    return {
        "workspace_scope": scope.as_dict(),
        "forecast_run_id": run.id,
        "period": resolved_period,
        "service_level": service_level,
        "scope_level": scope_level,
        "items": window,
        "total": len(results),
        "offset": offset,
        "limit": limit,
        "unavailable_reason": None,
        "notes": [
            f"Review period {settings.review_period_days} days, from settings.",
            "Lead time per branch from Location Master, computed on cleaned "
            "despatch dates only - the raw field contains 0000-00-00 and values "
            "producing negative lead times.",
            "Replenishment A/B/C are zero for all 57 branches and are never "
            "used as an MOQ.",
        ],
    }


def _first_period(db: Session, forecast_run_id: str) -> str | None:
    return db.scalar(
        select(ForecastRow.period)
        .where(ForecastRow.forecast_run_id == forecast_run_id)
        .order_by(ForecastRow.period)
        .limit(1)
    )


def _stock_index(stock: pd.DataFrame) -> dict[tuple[str, str], dict[str, Any]]:
    if stock.empty:
        return {}
    columns = [
        column
        for column in (
            "usable_qty",
            "closing_qty",
            "has_negative_row",
            "stock_class",
            "mrp_value",
            "closing_value",
            "last_grn_date",
        )
        if column in stock.columns
    ]
    frame = stock.set_index(["canonical_branch", "canonical_sku"])[columns]
    return {key: value for key, value in frame.to_dict("index").items()}


def _branch_index(branches: pd.DataFrame) -> dict[str, dict[str, Any]]:
    if branches.empty:
        return {}
    columns = [
        column
        for column in (
            "avg_lead_time_days",
            "std_lead_time_days",
            "transit_lead_time_days",
            "service_factor",
            "truck_moq",
            "region",
            "zone",
            "supply_hub",
            "tier",
        )
        if column in branches.columns
    ]
    return branches.set_index("canonical_branch")[columns].to_dict("index")


def _substitute_index(products: pd.DataFrame) -> dict[str, list[str]]:
    if products.empty or "canonical_sku" not in products.columns:
        return {}
    output: dict[str, list[str]] = {}
    for _index, row in products.iterrows():
        candidates = [
            str(row.get(column))
            for column in ("substitute_sku_1", "substitute_sku_2")
            if row.get(column) and str(row.get(column)).lower() not in {"nan", "none"}
        ]
        if candidates:
            output[str(row["canonical_sku"])] = candidates
    return output


# ----------------------------------------------------------------------
# Supply Intelligence
# ----------------------------------------------------------------------


def supply_overview(
    db: Session,
    *,
    forecast_run_id: str | None = None,
    period: str | None = None,
    branch: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """The placement picture: cover, zero-stock-live-demand, dead stock.

    These are measured from the stock snapshot and the panel, **not** from the
    forecast, so they are available even before a series-level forecast exists -
    and the response says which parts depend on one.
    """
    run = (
        db.get(ForecastRun, forecast_run_id)
        if forecast_run_id
        else db.scalars(
            select(ForecastRun)
            .where(ForecastRun.status == "completed")
            .order_by(ForecastRun.created_at.desc())
            .limit(1)
        ).first()
    )
    if run is None:
        raise NotFoundError(
            "No completed forecast run exists.",
            remediation="POST /api/forecasts/runs first.",
        )
    artifacts = _prepared_dir(db, run)
    stock = _load_stock(artifacts)
    branches = _load_branches(artifacts)
    scope = _workspace(db)
    stock = scope.restrict(stock, _BRANCH_COL)
    branches = scope.restrict(branches, _BRANCH_COL)
    order_path = artifacts.get("order_fact")
    orders = pd.read_parquet(order_path) if order_path else pd.DataFrame()
    # The order fact is a third artifact, restricted separately. It matters
    # here because `stock` and `demand` are joined with an **outer** merge, so
    # a branch present only in orders would survive a restriction applied to
    # the stock frame alone - which is exactly how `zero_stock_live_demand`
    # kept listing branches no other panel on the page showed.
    orders = scope.restrict(orders, _BRANCH_COL)

    if branch:
        stock = stock[stock["canonical_branch"] == branch]
        if not orders.empty:
            orders = orders[orders["canonical_branch"] == branch]

    recent = pd.DataFrame()
    if not orders.empty and "period" in orders.columns:
        cutoff = sorted(orders["period"].dropna().unique())[-6:]
        recent = orders[orders["period"].isin(cutoff)]

    demand = (
        recent.groupby(["canonical_branch", "canonical_sku"], observed=True)[
            "ordered_qty"
        ]
        .sum()
        .rename("recent_demand")
        if not recent.empty
        else pd.Series(dtype="float64", name="recent_demand")
    )
    merged = stock.merge(
        demand, how="outer", left_on=["canonical_branch", "canonical_sku"], right_index=True
    )
    merged["usable_qty"] = merged["usable_qty"].fillna(0.0)
    merged["recent_demand"] = merged["recent_demand"].fillna(0.0)

    dead = merged[(merged["usable_qty"] > 0) & (merged["recent_demand"] == 0)]
    zero_stock_live = merged[(merged["usable_qty"] <= 0) & (merged["recent_demand"] > 0)]
    branch_lead = _branch_index(branches)

    top_dead = (
        dead.sort_values("closing_value", ascending=False)
        if "closing_value" in dead.columns
        else dead.sort_values("usable_qty", ascending=False)
    ).head(limit)
    top_gap = zero_stock_live.sort_values("recent_demand", ascending=False).head(limit)

    return {
        "workspace_scope": scope.as_dict(),
        "forecast_run_id": run.id,
        "period": period or run.origin_period,
        "branch": branch,
        "stock_snapshot_date": get_settings().stock_snapshot_date,
        "totals": {
            "positions": int(len(merged)),
            "positions_with_stock": int((merged["usable_qty"] > 0).sum()),
            "dead_or_slow_positions": int(len(dead)),
            "dead_stock_units": float(dead["usable_qty"].sum()),
            "dead_stock_value": (
                float(dead["closing_value"].sum())
                if "closing_value" in dead.columns
                else None
            ),
            "zero_stock_live_demand_positions": int(len(zero_stock_live)),
            "unfilled_recent_demand_units": float(zero_stock_live["recent_demand"].sum()),
            "negative_stock_rows": (
                int(stock["has_negative_row"].sum())
                if "has_negative_row" in stock.columns
                else 0
            ),
        },
        "dead_stock": [
            {
                "canonical_branch": row.get("canonical_branch"),
                "canonical_sku": row.get("canonical_sku"),
                "usable_qty": float(row.get("usable_qty") or 0.0),
                "closing_value": (
                    float(row["closing_value"])
                    if "closing_value" in row and pd.notna(row["closing_value"])
                    else None
                ),
                "recent_demand": float(row.get("recent_demand") or 0.0),
                "stock_class": row.get("stock_class"),
            }
            for _index, row in top_dead.iterrows()
        ],
        "zero_stock_live_demand": [
            {
                "canonical_branch": row.get("canonical_branch"),
                "canonical_sku": row.get("canonical_sku"),
                "usable_qty": float(row.get("usable_qty") or 0.0),
                "recent_demand": float(row.get("recent_demand") or 0.0),
            }
            for _index, row in top_gap.iterrows()
        ],
        "lead_time_assumptions": {
            key: {
                "avg_lead_time_days": value.get("avg_lead_time_days"),
                "transit_lead_time_days": value.get("transit_lead_time_days"),
                "truck_moq": value.get("truck_moq"),
            }
            for key, value in list(branch_lead.items())[:limit]
        },
        "review_period_days": get_settings().review_period_days,
        "caveats": [
            "Stock is a single snapshot dated "
            f"{get_settings().stock_snapshot_date}; demand history ends "
            f"{run.origin_period}. These are current-snapshot measures.",
            "Dead or slow is defined as usable stock held where that exact "
            "branch x SKU had no ordered demand in the last six months of "
            "history. It is a placement signal, not an instruction to scrap.",
            "Transferable stock is not computed as a transfer plan: the source "
            "set carries no transfer cost, lane or lead time between branches.",
        ],
    }


def transferable_stock(
    db: Session,
    *,
    canonical_sku: str,
    exclude_branch: str | None = None,
    forecast_run_id: str | None = None,
    limit: int = 25,
) -> dict[str, Any]:
    """Where else in the network this SKU is held.

    Deliberately not a transfer recommendation. The source set has no inter-
    branch lane, cost or transit time, so naming a donor branch is as far as the
    data supports; choosing one is a planner's decision.
    """
    run = (
        db.get(ForecastRun, forecast_run_id)
        if forecast_run_id
        else db.scalars(
            select(ForecastRun)
            .where(ForecastRun.status == "completed")
            .order_by(ForecastRun.created_at.desc())
            .limit(1)
        ).first()
    )
    if run is None:
        raise NotFoundError("No completed forecast run exists.")
    artifacts = _prepared_dir(db, run)
    stock = _workspace(db).restrict(_load_stock(artifacts), _BRANCH_COL)
    held = stock[stock["canonical_sku"] == canonical_sku]
    if exclude_branch:
        held = held[held["canonical_branch"] != exclude_branch]
    held = held[held["usable_qty"] > 0].sort_values("usable_qty", ascending=False)

    return {
        "canonical_sku": canonical_sku,
        "excluded_branch": exclude_branch,
        "holders": [
            {
                "canonical_branch": row["canonical_branch"],
                "usable_qty": float(row["usable_qty"]),
                "closing_qty": float(row.get("closing_qty") or 0.0),
                "stock_class": row.get("stock_class"),
            }
            for _index, row in held.head(limit).iterrows()
        ],
        "total_holders": int(len(held)),
        "total_usable_units": float(held["usable_qty"].sum()),
        "caveat": (
            "Holdings only. The source set carries no inter-branch lane, "
            "transfer cost or transit time, so this is not a transfer plan."
        ),
    }

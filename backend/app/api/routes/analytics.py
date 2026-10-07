"""Demand-analytics endpoints for the reference-parity dashboard pages.

One response per page, filtered server-side, exactly as the reference does it:
the client sends its filter state and gets every panel's data back in one
payload, so the panels on a page can never be showing different filters.

The aggregation itself is in `app.domain.ais.analytics` — this module only
resolves which panel build to read and turns query parameters into a scope.
"""

from __future__ import annotations

import logging

from functools import lru_cache
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.ml.features.grain import MONTHLY, is_period, period_month
from app.core.errors import ConflictError
from app.db.session import get_db
from app.domain.ais import analytics
from app.domain.ais import network_frame
from app.domain.ais.workspace import WorkspaceScope, resolve_workspace
from app.services import lead_time_service
from app.models.mappings import PreprocessingRun
from app.models.panel import PanelBuild

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/analytics", tags=["analytics"])


def _latest_build(db: Session) -> PanelBuild:
    """The newest completed panel build, or a structured conflict.

    Raises rather than returning None when no panel exists: a page showing
    zeros because the pipeline has not run yet is indistinguishable from a page
    showing a real zero, and the pipeline stage is the useful thing to say.
    """
    build = db.scalars(
        select(PanelBuild)
        .where(PanelBuild.status == "completed")
        .order_by(PanelBuild.created_at.desc())
        .limit(1)
    ).first()
    if build is None:
        raise ConflictError(
            "No completed panel build exists yet.",
            remediation=(
                "Run the pipeline through to the panel build first: register a "
                "dataset, confirm the mapping, preprocess, then build the panel."
            ),
        )
    return build


def _panel_path(build: PanelBuild) -> str:
    path = (build.artifacts_json or {}).get("panel")
    if not path:
        raise ConflictError(
            "The newest panel build recorded no panel artifact.",
            remediation="Rebuild the panel, then reload this page.",
        )
    return str(path)


@lru_cache(maxsize=4)
def _demand_universe_from(order_fact_path: str) -> tuple[int, int]:
    """How many branches and SKUs the *unrestricted* order book holds.

    Two columns of the order fact, so it costs 0.07 s over 582 K rows, and is
    cached per artifact path besides - a new preprocessing run writes to a new
    path, so the cache key invalidates itself.
    """
    import pandas as pd

    frame = pd.read_parquet(
        order_fact_path, columns=[analytics.BRANCH_COL, analytics.SKU_COL]
    )
    return (
        int(frame[analytics.BRANCH_COL].nunique()),
        int(frame[analytics.SKU_COL].nunique()),
    )


def _demand_universe(db: Session) -> tuple[int | None, int | None]:
    """The denominator for every scope banner, or `(None, None)` if unknowable.

    It cannot be counted from the panel. The panel *is* the workspace slice, so
    counting it gives "2 of 2 branches - 136 of 136 SKUs": a banner whose whole
    job is to say what the page hides, saying nothing. The preprocessing
    artifacts are never cut to the workspace, so they carry the real universe -
    53 branches and 2,063 SKUs against this extract.

    Never raises. A banner that cannot state its denominator drops the "of N"
    and still says which slice is shown; a banner that 500s takes the page with
    it.
    """
    try:
        run = db.scalars(
            select(PreprocessingRun)
            .where(PreprocessingRun.status == "completed")
            .order_by(PreprocessingRun.created_at.desc())
            .limit(1)
        ).first()
        path = (run.artifacts_json or {}).get("order_fact") if run else None
        if not path:
            return None, None
        return _demand_universe_from(str(path))
    except Exception:  # noqa: BLE001 - logged, and the banner degrades instead
        logger.warning("demand_universe_unavailable", exc_info=True)
        return None, None


def _panel(db: Session):
    """The newest completed panel build, cut to this workspace's locations.

    Returns the frame, the build, its path and the `WorkspaceScope` that was
    applied - the scope travels with the data so no caller can report a
    restricted figure without the sentence that qualifies it.
    """
    build = _latest_build(db)
    path = _panel_path(build)
    frame = analytics.load_panel(str(path))

    # One workspace scope for the whole application, applied at the single
    # place every panel-backed page loads its data. Restricting here rather
    # than in each endpoint is what makes the location list on Demand
    # Analytics, Operational Exceptions and the scorecard identical by
    # construction instead of by coincidence.
    #
    # The totals are the *unrestricted* universe, not this frame's. Counting
    # the frame reports "136 of 136 SKUs" for a workspace holding 136 of 2,063,
    # which reads as full coverage - see `_demand_universe`.
    total_branches, total_skus = _demand_universe(db)
    scope = resolve_workspace(db).with_total(total_branches, total_skus)
    return scope.restrict(frame, analytics.BRANCH_COL), build, str(path), scope


def _scope(
    branch: str | None,
    sku: str | None,
    product_group: str | None,
    value_class: str | None,
    start_period: str | None,
    end_period: str | None,
    grain: str,
    *,
    # Keyword-only and defaulted, so the routes that do not offer these three
    # axes keep their existing positional calls unchanged (D-141).
    glass_type: str | None = None,
    vehicle_category: str | None = None,
    vehicle_age_category: str | None = None,
) -> analytics.AnalyticsScope:
    return analytics.AnalyticsScope(
        branch=branch,
        sku=sku,
        product_group=product_group,
        value_class=value_class,
        glass_type=glass_type,
        vehicle_category=vehicle_category,
        vehicle_age_category=vehicle_age_category,
        start_period=start_period,
        end_period=end_period,
        grain=grain,
    )


def _stamp(payload: dict[str, Any], scope: WorkspaceScope) -> dict[str, Any]:
    """Return a copy of the payload carrying the workspace scope and its note.

    **A copy, not the payload.** `cached_summary` and friends hand back the
    dict they are holding, so stamping in place appended the scope note to the
    cached object on every request - the page grew one more identical note
    each time it was loaded, reaching fifteen. Anything this function touches
    has to be its own object, or the cache is poisoned by being read.

    Unconditional: an unrestricted workspace reports `restricted: false`, so a
    client can tell "everything" from "narrowed" rather than having to infer
    it from a missing key.

    `notes` is a list of sentences on every payload but one: the lead-time
    comparison uses it for a dict of line counts the page reads figures out of
    (`lines_usable`, `lines_out_of_range`, the invoice-ordering split). Writing
    a list over that dict emptied all seven figures, so a `notes` that is not a
    list is left exactly as it is — the scope sentence is already on
    `workspace_scope.note`, which is what `ScopeBanner` actually renders.
    """
    stamped = dict(payload)
    stamped["workspace_scope"] = scope.as_dict()
    note = scope.note()
    notes = payload.get("notes")
    if note and (notes is None or isinstance(notes, list)):
        existing = list(notes) if isinstance(notes, list) else []
        # Guard the content as well as the object: a payload that already
        # carries this note must not gain a second copy.
        if note not in existing:
            # First, because it qualifies every other note on the page.
            stamped["notes"] = [note, *existing]
        else:
            stamped["notes"] = existing
    return stamped


@router.get("/filters", summary="Filter options for the demand-analytics pages")
def get_filters(
    full_network: bool = Query(
        False,
        description=(
            "Options across the whole client network rather than the "
            "workspace. Paired with the same flag on `/summary` so a page "
            "cannot offer a branch its figures do not cover."
        ),
    ),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if full_network:
        frame, run, coverage = _network(db)
        payload = analytics.filters(frame)
        payload["preprocessing_run_id"] = run.id
        payload["network_coverage"] = coverage
        total_branches, total_skus = _demand_universe(db)
        payload["workspace_scope"] = {
            "restricted": False,
            "source": "full_network",
            "branches": None,
            "branch_count": coverage["branches"],
            "total_branches": total_branches,
            "skus": None,
            "sku_count": coverage["skus"],
            "total_skus": total_skus,
            "detail": "Every branch and SKU in the client's own order and sales data.",
            "note": coverage["note"],
        }
        return payload
    panel, build, _path, scope = _panel(db)
    payload = analytics.filters(panel)
    payload["panel_build_id"] = build.id
    payload["training_cut_period"] = build.training_cut_period
    return _stamp(payload, scope)


@lru_cache(maxsize=1)
def _network_frame_from(order: str, sales: str, product: str, branch: str, grain: str):
    """The whole client network, assembled once and held.

    Cached on the artifact paths, so a new preprocessing run invalidates it by
    writing elsewhere. One entry: the frame is 276 MB and there is only ever
    one network.
    """
    import pandas as pd

    return network_frame.build(
        pd.read_parquet(order), pd.read_parquet(sales),
        pd.read_parquet(product), pd.read_parquet(branch), grain=grain,
    )


def _network(db: Session):
    """Overall Analysis at full client scope: every branch, every SKU.

    Deliberately NOT workspace-restricted, and the only path in this file that
    is. Every other page stays on the workspace panel, so the one-scope rule
    (D-049) still holds everywhere a forecast or a model is involved. This page
    answers a different question - what the client's own data says - and says
    so in its own banner (D-138).

    The panel cannot serve it: an unrestricted grid is 8.6 M rows and the build
    exhausts memory. The preprocessed facts are already unrestricted, and a sum
    over observed rows equals a sum over the grid.
    """
    run = db.scalars(
        select(PreprocessingRun)
        .where(PreprocessingRun.status == "completed")
        .order_by(PreprocessingRun.created_at.desc())
        .limit(1)
    ).first()
    if run is None:
        raise ConflictError(
            "No completed preprocessing run exists yet.",
            remediation="Run ingestion and preprocessing, then reload this page.",
        )
    artifacts = dict(run.artifacts_json or {})
    missing = [k for k in ("order_fact", "sales_fact", "product_dim", "branch_dim")
               if not artifacts.get(k)]
    if missing:
        raise ConflictError(
            f"The newest preprocessing run recorded no {', '.join(missing)}.",
            remediation="Re-run preprocessing, then reload this page.",
        )
    frame, coverage = _network_frame_from(
        artifacts["order_fact"], artifacts["sales_fact"],
        artifacts["product_dim"], artifacts["branch_dim"],
        get_settings().panel_grain,
    )
    return frame, run, coverage


@router.get("/summary", summary="Every Demand Analytics panel, for one filter state")
def get_summary(
    branch: str | None = Query(None),
    sku: str | None = Query(None, description="A single canonical SKU. With `branch`, one series."),
    product_group: str | None = Query(None),
    value_class: str | None = Query(None),
    glass_type: str | None = Query(None, description="One glass type, e.g. Laminated Windscreen."),
    vehicle_category: str | None = Query(None, description="One vehicle category, e.g. CAR & MUV."),
    vehicle_age_category: str | None = Query(None, description="One vehicle age band."),
    start_period: str | None = Query(None, pattern=r"^\d{4}-\d{2}$"),
    end_period: str | None = Query(None, pattern=r"^\d{4}-\d{2}$"),
    grain: str = Query("monthly"),
    full_network: bool = Query(
        False,
        description=(
            "Read the whole client network - every branch and SKU - instead of "
            "the workspace. Overall Analysis uses it; no other page does. "
            "Observed rows only, so totals and trends are exact while row "
            "counts are not comparable with the workspace pages (D-138)."
        ),
    ),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    cut = _scope(
        branch, sku, product_group, value_class, start_period, end_period, grain,
        glass_type=glass_type,
        vehicle_category=vehicle_category,
        vehicle_age_category=vehicle_age_category,
    )
    if full_network:
        frame, run, coverage = _network(db)
        payload = analytics.cached_summary(frame, f"network:{run.id}", cut)
        payload["preprocessing_run_id"] = run.id
        payload["network_coverage"] = coverage
        total_branches, total_skus = _demand_universe(db)
        payload["workspace_scope"] = {
            "restricted": False,
            "source": "full_network",
            "branches": None,
            "branch_count": coverage["branches"],
            "total_branches": total_branches,
            "skus": None,
            "sku_count": coverage["skus"],
            "total_skus": total_skus,
            "detail": "Every branch and SKU in the client's own order and sales data.",
            "note": coverage["note"],
        }
        return payload
    panel, build, path, scope = _panel(db)
    payload = analytics.cached_summary(panel, path, cut)
    payload["panel_build_id"] = build.id
    return _stamp(payload, scope)


@router.get("/exceptions", summary="Operational and data exceptions per branch x SKU line")
def get_exceptions(
    branch: str | None = Query(None),
    sku: str | None = Query(None),
    product_group: str | None = Query(None),
    value_class: str | None = Query(None),
    start_period: str | None = Query(None, pattern=r"^\d{4}-\d{2}$"),
    end_period: str | None = Query(None, pattern=r"^\d{4}-\d{2}$"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    panel, build, path, scope = _panel(db)
    payload = analytics.cached_exceptions(
        panel, path, _scope(branch, sku, product_group, value_class, start_period, end_period, "monthly")
    )
    payload["panel_build_id"] = build.id
    return _stamp(payload, scope)


@router.get("/branch-scorecard", summary="Per-branch operational scorecard, ranked")
def get_branch_scorecard(
    product_group: str | None = Query(None),
    value_class: str | None = Query(None),
    start_period: str | None = Query(None, pattern=r"^\d{4}-\d{2}$"),
    end_period: str | None = Query(None, pattern=r"^\d{4}-\d{2}$"),
    limit: int = Query(8, ge=1, le=53),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    panel, build, path, scope = _panel(db)
    payload = analytics.cached_branch_scorecard(
        panel, path, _scope(None, None, product_group, value_class, start_period, end_period, "monthly"), limit=limit
    )
    payload["panel_build_id"] = build.id
    return _stamp(payload, scope)


@router.get("/series", summary="Branch x SKU options for scope pickers")
def get_series(
    branch: str | None = Query(None),
    sku: str | None = Query(
        None,
        description=(
            "One canonical SKU. The mirror of `branch`: it answers which "
            "branches carry this SKU, which is how a two-way picker narrows "
            "without listing every pair."
        ),
    ),
    limit: int = Query(200, ge=1, le=5000),
    full_network: bool = Query(
        False,
        description=(
            "Pairs across the whole client network rather than the workspace. "
            "Paired with the same flag on `/summary` and `/filters`, so a "
            "picker cannot offer a combination its figures do not cover "
            "(D-144). Unscoped the network holds 68,597 pairs, well past any "
            "`limit`; ask with `branch` or `sku` to get a complete answer."
        ),
    ),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if full_network:
        frame, run, coverage = _network(db)
        payload: dict[str, Any] = {
            "items": analytics.series_options(frame, branch=branch, sku=sku, limit=limit),
            "preprocessing_run_id": run.id,
            "total_series": coverage["series"],
        }
        # The caller has to be able to tell a complete answer from a cut one.
        payload["truncated"] = len(payload["items"]) >= limit
        return payload
    panel, _build, _path, scope = _panel(db)
    return _stamp(
        {"items": analytics.series_options(panel, branch=branch, sku=sku, limit=limit)},
        scope,
    )

def _branch_dim(db: Session) -> "pd.DataFrame":
    """The branch dimension from the newest completed preprocessing run.

    Read straight from the artifact rather than the panel: the panel repeats a
    branch's lead time on every one of its rows, and de-duplicating 1.5 M rows
    to recover 57 is wasteful when the dimension table is right there.
    """
    import pandas as pd

    run = db.scalars(
        select(PreprocessingRun)
        .where(PreprocessingRun.status == "completed")
        .order_by(PreprocessingRun.created_at.desc())
        .limit(1)
    ).first()
    if run is None:
        raise ConflictError(
            "No completed preprocessing run exists yet.",
            remediation="Confirm the mapping and run preprocessing, then reload this page.",
        )
    path = (run.artifacts_json or {}).get("branch_dim")
    if not path:
        raise ConflictError(
            "The newest preprocessing run recorded no branch dimension.",
            remediation="Re-run preprocessing, then reload this page.",
        )
    return pd.read_parquet(path)


@router.get(
    "/lead-time-observed",
    summary="Location Master's stated lead time beside what the order dates show",
)
def get_lead_time_observed(
    refresh: bool = Query(False),
    all_branches: bool = Query(
        False,
        alias="all",
        description=(
            "Ignore the workspace restriction and compare every branch in both "
            "files. The network view is where the four zero-day branches are "
            "visible."
        ),
    ),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """A monitoring view over two files that are read and never written.

    `Avg Lead Time` from Location Master beside the mean of Despatch Date minus
    Order Date from Orders & Receipts, per branch. Both columns already exist;
    subtracting one date from another is a derived view, not an edit (D-105).

    Scoped to the workspace by default, like every other page, so a two-branch
    figure can never read as a national one. `all=true` drops the restriction,
    and that is where the four zero-day branches are visible.

    `refresh=true` re-parses the order file, which takes about two minutes.
    """
    # With the denominators, so this banner reads "2 of 53 branches - 136 of
    # 2,063 SKUs" like the analytics pages rather than a bare "2 branches",
    # which states the restriction without stating how much it hides (D-131).
    total_branches, total_skus = _demand_universe(db)
    scope = resolve_workspace(db).with_total(total_branches, total_skus)
    payload = lead_time_service.build(
        refresh=refresh,
        branches=None if all_branches else (list(scope.branches) if scope.branches else None),
        skus=None if all_branches else (list(scope.skus) if scope.skus else None),
    )
    return _stamp(payload, scope)


@router.get("/lead-time", summary="Per-branch lead time, its variability, and what looks wrong")
def get_lead_time(
    worst: int = Query(8, ge=1, le=57),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    # The branch dimension is a separate artifact from the panel, so it needs
    # the restriction applied on its own - otherwise Supply Intelligence would
    # chart 53 depots beside a Demand Analytics page showing two.
    dimension = _branch_dim(db)
    scope = resolve_workspace(db).with_total(
        int(dimension[analytics.BRANCH_COL].nunique())
        if analytics.BRANCH_COL in dimension.columns and not dimension.empty
        else None
    )
    payload = analytics.lead_time(
        scope.restrict(dimension, analytics.BRANCH_COL), worst=worst
    )
    return _stamp(payload, scope)


@router.get(
    "/sample-mix",
    summary="How far the sampled SKUs distort the composition charts",
)
def get_sample_mix(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Sample composition against the same branches with every SKU.

    The workspace's twenty SKUs were chosen by stratification, so each category
    is represented - and the volume mix is therefore *not* proportional to the
    branches the sample came from. The composition panels would otherwise be
    read as a description of the business (docs/DECISIONS.md D-074).

    Only the SKU restriction is lifted for the reference. The branch axis is
    still applied, because the question is whether this sample represents the
    two branches it was drawn from, and widening to all 53 would both answer a
    different question and report outside the configured scope.
    """
    from app.domain.ais import representativeness

    import dataclasses

    frame = analytics.load_panel(_panel_path(_latest_build(db)))
    scope = resolve_workspace(db)

    # The reference lifts only the SKU axis. Built by replacing `skus` on the
    # scope rather than by filtering by hand, so the branch restriction is
    # applied by exactly the same code that applies it everywhere else.
    branch_only = dataclasses.replace(scope, skus=None).restrict(
        frame, analytics.BRANCH_COL
    )
    sample = scope.restrict(frame, analytics.BRANCH_COL)

    if scope.skus is None:
        return _stamp(
            {
                "restricted": False,
                "reason": (
                    "No SKU restriction is configured, so the panels already "
                    "describe every product these branches carry and no sampling "
                    "caveat applies."
                ),
                "axes": {},
            },
            scope,
        )

    payload = representativeness.analyse(
        sample,
        branch_only,
        target=analytics.TARGET_COL,
        sample_skus=int(sample[analytics.SKU_COL].nunique()) if not sample.empty else 0,
        reference_skus=(
            int(branch_only[analytics.SKU_COL].nunique()) if not branch_only.empty else 0
        ),
    )
    payload["restricted"] = True
    return _stamp(payload, scope)


@router.get(
    "/impact",
    summary="Measured forecast-error reduction, and the benefit projected from it",
)
def get_impact(
    recovery_share: float | None = Query(
        None, ge=0.0, le=1.0,
        description="Share of unfilled demand better planning could recover.",
    ),
    margin_pct: float | None = Query(
        None, ge=0.0, le=1.0, description="Contribution margin on recovered revenue."
    ),
    stock_efficiency_share: float | None = Query(
        None, ge=0.0, le=1.0,
        description="Share of the error reduction that converts to less safety stock.",
    ),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """What the forecasting is worth, with measurement and assumption separated.

    The error reduction is measured: it comes from the rolling-origin folds
    already scored during training, compared against a naive carry-forward at
    branch x SKU. Everything denominated in units or rupees is a projection
    from that measurement under assumptions the caller supplies, and the
    payload says so in `basis` and repeats every assumption it used.

    Nothing here is a realised outcome. No forecast month has elapsed, there is
    no inventory-policy backtest, and no sales counterfactual exists - all
    three are returned as caveats rather than left for the reader to infer
    (docs/DECISIONS.md D-072).
    """
    from app.domain.ais.impact import Exposure
    from app.services import impact_service

    panel, _build, _path, scope = _panel(db)
    if panel.empty:
        return _stamp(
            {"empty": True, "reason": "No panel rows are in scope."}, scope
        )

    payload = analytics.summary(panel, analytics.AnalyticsScope())
    kpis = payload.get("kpis") or {}
    months = int(panel[analytics.PERIOD_COL].nunique())

    exposure = Exposure(
        ordered_units=float(kpis.get("demand_units") or 0.0),
        unfilled_units=float(kpis.get("shortfall_units") or 0.0),
        unfilled_rows=int(kpis.get("censored_rows") or 0),
        demand_value=float(kpis.get("demand_value") or 0.0),
        fill_rate_pct=kpis.get("fill_rate_pct"),
        series_count=int(kpis.get("series_count") or 0),
    )

    overrides = {
        key: value
        for key, value in (
            ("recovery_share", recovery_share),
            ("margin_pct", margin_pct),
            ("stock_efficiency_share", stock_efficiency_share),
        )
        if value is not None
    }

    report = impact_service.build_report(
        db, exposure=exposure, history_months=months, assumptions=overrides
    )
    return _stamp(report, scope)


@router.get("/drift", summary="Demand drift over time, and when it would next cross the line")
def get_drift(
    branch: str | None = Query(None),
    sku: str | None = Query(None),
    explain: bool = Query(True, description="Include a plain-language explanation."),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Measured drift for one scope, with a clearly-labelled projection.

    Drift is computed from the panel, not predicted by a model. The projection
    is a straight line through observed drift and says so; it refuses to
    answer far more often than it answers (docs/DECISIONS.md D-060).
    """
    from app.domain.ais import drift as drift_domain

    panel, _build, _path, scope = _panel(db)
    frame = panel
    label_parts = []
    if branch:
        frame = frame[frame[analytics.BRANCH_COL] == branch]
        label_parts.append(branch)
    if sku:
        frame = frame[frame[analytics.SKU_COL] == sku]
        label_parts.append(sku)
    label = " × ".join(label_parts) if label_parts else "the whole workspace"

    if frame.empty:
        return _stamp(
            {"empty": True, "reason": "No panel rows match this selection.", "scope": label},
            scope,
        )

    # Drift is defined in months - a six-month window against the six before
    # it, and a measurement change dated to a month - so a weekly panel is
    # added up to months before it gets here rather than drift being taught a
    # second calendar. Six weeks against six weeks would be a different
    # question with the same name.
    panel_grain = get_settings().panel_grain
    periods = frame["period"].astype(str)
    if panel_grain != MONTHLY:
        periods = periods.map(
            lambda value: period_month(value, panel_grain)
            if is_period(value, panel_grain)
            else value
        )
    monthly = (
        frame.groupby(periods, observed=True)[analytics.TARGET_COL]
        .sum()
        .sort_index()
    )
    payload = drift_domain.analyse(monthly, scope_label=label)
    if explain and not payload.get("empty"):
        payload["explanation"] = _drift_explanation(payload)
    return _stamp(payload, scope)


def _drift_explanation(payload: dict[str, Any]) -> dict[str, Any]:
    """A plain-language reading of the drift figures.

    Written by the model when a key is configured, from templates otherwise,
    and labelled either way — the two read identically on a screen and a
    reader deserves to know which produced the sentence in front of them.

    Whichever writes it, it only ever restates figures already in `payload`.
    """
    from app.services.assistant import llm

    latest = payload.get("latest") or {}
    projection = payload.get("projection") or {}
    facts = {
        "scope": payload.get("scope"),
        "window_months": payload.get("window_months"),
        "latest_shift_pct": latest.get("shift_pct"),
        "recent_mean_units": latest.get("recent_mean"),
        "baseline_mean_units": latest.get("baseline_mean"),
        "is_material": latest.get("is_material"),
        "threshold_pct": payload.get("threshold_pct"),
        "projection": projection,
        "measurement_change": payload.get("measurement_change"),
    }

    deterministic = _deterministic_drift_text(payload)
    if not llm.is_configured():
        return {"text": deterministic, "answered_by": "deterministic_no_key", "model": None}

    import json as _json

    from app.core.config import get_settings

    settings = get_settings()
    prompt = (
        "You explain a demand-drift chart to a supply planner who knows their business "
        "but not this application's vocabulary.\n\n"
        "GROUNDING — these override everything else:\n"
        "1. Use ONLY the numbers in the facts. Never invent, estimate or re-derive one. "
        "Do no arithmetic.\n"
        "2. Drift here is MEASURED from history, not predicted by a model. Never call it "
        "a forecast.\n"
        "3. Any projection is a straight line through observed drift, extrapolated. Say "
        "so. If `projectable` is false, say plainly that no date can be given and give "
        "the reason from the facts — never supply a date anyway.\n"
        "4. The panel changes source in Apr 2025 from invoiced sales proxy to real "
        "orders, so part of any shift across that date is a change of measurement rather "
        "than of demand. Mention it.\n"
        "5. The threshold is a stated reading aid, not a statistical result.\n\n"
        "Write 3-5 short sentences of plain prose. No bullets, no headings, no markdown. "
        "Explain what drift means, what this scope's number says, what it implies for a "
        "forecast fitted before the shift, and what can or cannot be projected.\n\n"
        f"FACTS: {_json.dumps(facts, default=str)}"
    )
    from app.services.assistant import quality

    try:
        response = llm.client().chat.completions.create(
            model=settings.openai_model,
            messages=[{"role": "user", "content": prompt}],
            # Not `ai_temperature`: this call restates measured figures, and at
            # 2.0 it produced four-language nonsense (docs/DECISIONS.md D-061).
            temperature=settings.ai_explanation_temperature,
            max_tokens=400,
        )
        text = (response.choices[0].message.content or "").strip()
        if not text:
            raise ValueError("the model returned nothing")
        # A provider that answers confidently with nonsense used to render it.
        verdict = quality.check_explanation(
            text,
            must_mention=(str(latest.get("shift_pct") or ""), str(payload.get("scope") or "")),
        )
        if not verdict.ok:
            logger.warning("drift explanation rejected: %s", verdict.reason)
            return {
                "text": deterministic,
                "answered_by": "deterministic_after_unusable_reply",
                "model": None,
                "rejected_because": verdict.reason,
            }
        return {"text": text[:1600], "answered_by": "openai", "model": settings.openai_model}
    except Exception as exc:  # noqa: BLE001 - the panel must still render
        logger.warning("drift explanation failed: %s", exc)
        return {
            "text": deterministic,
            "answered_by": "deterministic_after_provider_error",
            "model": None,
            "provider_error": type(exc).__name__,
        }


def _deterministic_drift_text(payload: dict[str, Any]) -> str:
    latest = payload.get("latest") or {}
    projection = payload.get("projection") or {}
    shift = latest.get("shift_pct")
    window = payload.get("window_months")
    direction = "above" if (shift or 0) >= 0 else "below"
    parts = [
        f"Drift compares the last {window} months against the {window} before them. "
        f"For {payload.get('scope')}, recent demand averages "
        f"{latest.get('recent_mean')} units a month against {latest.get('baseline_mean')} "
        f"earlier — {abs(shift or 0):.1f}% {direction} the baseline.",
        "This is measured from the history, not predicted by a model.",
    ]
    if latest.get("is_material"):
        parts.append(
            f"It is past the {payload.get('threshold_pct'):.0f}% reading aid, so a model "
            "fitted before the shift is being scored against a period that no longer "
            "looks like its training window."
        )
    else:
        parts.append(
            f"It is inside the {payload.get('threshold_pct'):.0f}% reading aid, so the "
            "earlier window is still a reasonable description of the recent one."
        )
    if projection.get("projectable"):
        parts.append(
            f"If the observed trend held, the threshold would be reached around "
            f"{projection.get('expected_period')} — a straight line through past drift "
            "extrapolated, not a model forecast."
        )
    else:
        parts.append(f"No date can be projected: {projection.get('reason')}")
    parts.append(
        f"Part of any shift across {payload.get('measurement_change')} is a change of "
        "measurement rather than of demand: earlier months are invoiced sales proxy, "
        "later months are real orders."
    )
    return " ".join(parts)

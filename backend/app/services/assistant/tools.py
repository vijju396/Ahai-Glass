"""Structured-fact retrieval for the AI Assistant.

Every tool calls into an already-built AIS service and returns a small,
curated dict. The model never sees a raw row, never receives SQL, and never
gets a filesystem or shell surface — it chooses *which* of these to call and
then writes prose about the numbers they return.

Four rules make that safe rather than merely tidy:

**The backend computes; the model narrates.** Every figure in an answer comes
from one of these dicts. Nothing asks the model to add, divide, rank or project
anything, because a model that is allowed to do arithmetic on facts will
eventually do it wrong and present the result in the same confident voice.

**Charts are built here too.** A tool returns a `chart` with an allowlisted
type and data drawn from the same facts. The model is never asked for a data
array, so a chart cannot disagree with the paragraph beside it.

**Scope is validated server-side.** A branch or SKU named in a question is
resolved against the panel's real values; anything unrecognised is dropped and
reported, never passed through.

**Every payload carries its provenance.** Scope, periods, units, run ids and
the caveats that apply — because "1,88,103 units" means nothing without
knowing it is a reconciled national forecast for 2026-08 from run `992947a1`.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings

logger = logging.getLogger(__name__)

#: Chart types the frontend can render. Anything else is refused rather than
#: passed through to a renderer that would silently drop it.
ALLOWED_CHART_TYPES: frozenset[str] = frozenset({"line", "bar", "pie"})

#: Hard caps on what one answer may pull back, so a pathological question
#: cannot turn into an unbounded scan or an enormous prompt.
MAX_CHART_POINTS = 36
MAX_TABLE_ROWS = 12

_EMPTY_SCOPE: dict[str, Any] = {"branch": None, "sku": None, "period": None, "resolved_from": None}

_GREETINGS = {"hi", "hello", "hey", "yo", "hiya", "morning", "thanks", "thank you", "ok", "okay"}

_VISUAL_WORDS = {"chart", "graph", "plot", "visual", "visualise", "visualize", "show", "draw", "trend"}

_CHART_WORDS = {"pie": {"pie", "doughnut", "donut", "share", "split", "mix", "breakdown"},
                "bar": {"bar", "column", "compare", "comparison", "ranking", "rank", "top"},
                "line": {"line", "trend", "over time", "timeline", "history"}}


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9_.\-]+", (text or "").lower())


def is_greeting(question: str) -> bool:
    stripped = (question or "").strip().lower().rstrip("!.?")
    return stripped in _GREETINGS


def is_follow_up(question: str) -> bool:
    """A short question with no subject of its own leans on the previous turn."""
    words = _words(question)
    return len(words) <= 6 and not {"branch", "sku", "model", "stock", "forecast", "demand"} & set(words)


def wants_visual(question: str) -> bool:
    return bool(set(_words(question)) & _VISUAL_WORDS)


def wants_chart_type(question: str) -> str | None:
    lowered = (question or "").lower()
    for kind, terms in _CHART_WORDS.items():
        if any(term in lowered for term in terms):
            return kind
    return None


# ----------------------------------------------------------------------
# Scope
# ----------------------------------------------------------------------


def _panel_and_path(db: Session):
    """The workspace's panel, via the same seam every page uses.

    The assistant must never be able to answer about a branch the screens do
    not show - a chat reply naming a location that has no page is worse than
    no reply. Sharing `_panel` is what guarantees that, so the fourth element
    (the workspace scope) is dropped here only where a tool does not need it.
    """
    from app.api.routes.analytics import _panel

    return _panel(db)


def resolve_scope(db: Session, question: str, current: dict | None, history: list[dict] | None) -> dict[str, Any]:
    """The branch / SKU / period this question is about.

    Resolved against the panel's real values, so a branch the model or the user
    invents simply does not resolve. A previous turn's scope carries forward,
    which is what makes "and the month before?" answerable.
    """
    scope = dict(current or _EMPTY_SCOPE)
    try:
        panel, _build, _path, _scope = _panel_and_path(db)
    except Exception:
        return scope

    from app.domain.ais.analytics import BRANCH_COL, SKU_COL

    haystack = (question or "").upper()
    branches = [str(b) for b in panel[BRANCH_COL].dropna().unique()]
    for branch in sorted(branches, key=len, reverse=True):
        if branch and branch in haystack:
            scope["branch"] = branch
            scope["resolved_from"] = "question"
            break

    sku_match = re.search(r"\bFG\.[A-Z0-9.]+\b", haystack)
    if sku_match:
        candidate = sku_match.group(0)
        if (panel[SKU_COL] == candidate).any():
            scope["sku"] = candidate
            scope["resolved_from"] = "question"

    period_match = re.search(r"\b(20\d{2})-(0[1-9]|1[0-2])\b", question or "")
    if period_match:
        candidate = period_match.group(0)
        if (panel["period"] == candidate).any():
            scope["period"] = candidate
            scope["resolved_from"] = "question"

    if re.search(r"\b(all|every|entire|national|network|clear)\b", (question or "").lower()):
        if re.search(r"\b(all branches|every branch|national|network|clear)\b", (question or "").lower()):
            scope = dict(_EMPTY_SCOPE)
            scope["resolved_from"] = "cleared by question"
    return scope


def workspace_note(db: Session | None = None) -> str:
    """What "everything" actually means in this deployment.

    Returns "" when nothing is restricted, so an unrestricted install still
    reads "the whole network" and nothing here invents a limit that is not
    there.
    """
    if db is None:
        return ""
    try:
        from app.domain.ais.workspace import resolve_workspace  # noqa: PLC0415

        resolved = resolve_workspace(db)
        if not resolved.is_restricted:
            return ""
        branches = ", ".join(resolved.branches) if resolved.branches else None
        bits = []
        if branches:
            bits.append(f"{len(resolved.branches)} branch(es) ({branches})")
        if resolved.skus:
            bits.append(f"{len(resolved.skus)} SKU(s)")
        return " and ".join(bits)
    except Exception:  # noqa: BLE001 - a label must never break a tool
        logger.warning("workspace_note_unavailable", exc_info=True)
        return ""


def _workspace_phrase(db: Session | None = None) -> str:
    """"the whole network" or "this workspace only — ...", for a label."""
    workspace = workspace_note(db)
    return f"this workspace only — {workspace}" if workspace else "the whole network"


def scope_note(scope: dict | None, db: Session | None = None) -> str:
    """The slice a tool's figures describe, written for the model to quote.

    **Never "the whole network" while a workspace restriction is in force.**
    This string is handed to the model as a fact, and it used to read "the
    whole network" on a deployment cut to two branches and 136 SKUs — so the
    model was told, on every single call, that a two-branch figure was a
    national one. The scope note in `caveats` said otherwise, and a model given
    two contradictory facts will use either. Now the restriction is stated
    here, in the field the tool output puts next to the numbers (D-131).
    """
    parts = []
    resolved = scope or {}
    if resolved.get("branch"):
        parts.append(f"branch {resolved['branch']}")
    if resolved.get("sku"):
        parts.append(f"SKU {resolved['sku']}")
    if resolved.get("period"):
        parts.append(f"period {resolved['period']}")
    if parts:
        return ", ".join(parts)
    return _workspace_phrase(db)


def _analytics_scope(scope: dict | None, panel=None):
    """The caller's scope, clamped to the weeks that hold real orders.

    Without the clamp the assistant answered from the full panel while the
    Overall Analysis page answered from the orders window, so the same question
    returned two different totals - the page's own numbers on screen and a
    larger figure in the chat (D-124).
    """
    from app.domain.ais.analytics import AnalyticsScope, orders_start_month

    resolved = scope or {}
    return AnalyticsScope(
        branch=resolved.get("branch") or None,
        start_period=orders_start_month(panel) if panel is not None else None,
    )


def _whole(value: Any) -> Any:
    """A unit quantity rounded to a whole number, or the value untouched."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return int(round(value))
    return value


def _rupees(value: Any) -> str | None:
    """A rupee amount already written in Indian numbering - "₹60.24Cr".

    The facts used to carry the raw rupee figure only, while the system prompt
    asks for "₹8.9Cr or ₹12.4L". That leaves the conversion to the model, and
    it got it wrong the same way every time: ₹60.24Cr came back as ₹6.02Cr, a
    crore being 10^7 and the model dividing by 10^8. Every rupee figure in
    every answer was a tenth of the truth, in the same confident voice - which
    is the failure this module's docstring exists to prevent.

    One crore = 10^7, one lakh = 10^5.
    """
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    amount = float(value)
    sign = "-" if amount < 0 else ""
    amount = abs(amount)
    if amount >= 10_000_000:
        return f"{sign}₹{amount / 10_000_000:.2f}Cr"
    if amount >= 100_000:
        return f"{sign}₹{amount / 100_000:.2f}L"
    return f"{sign}₹{amount:,.0f}"


def _chart(kind: str, title: str, data: list[dict], series: list[dict], x_key: str) -> dict[str, Any] | None:
    """An allowlisted chart spec, or nothing.

    Values come from the caller's own facts. A type outside the allowlist
    returns `None` rather than being coerced into something renderable.
    """
    if kind not in ALLOWED_CHART_TYPES or not data:
        return None
    return {
        "type": kind,
        "title": title,
        "x_key": x_key,
        "series": series,
        "data": data[:MAX_CHART_POINTS],
    }


# ----------------------------------------------------------------------
# Tools
# ----------------------------------------------------------------------


def demand_trend(db: Session, scope: dict | None, *, visual: bool = False, chart_type: str | None = None) -> dict[str, Any]:
    """Monthly ordered-demand history for the scope."""
    from app.domain.ais import analytics as A

    panel, build, path, _scope = _panel_and_path(db)
    payload = A.cached_summary(panel, path, _analytics_scope(scope, panel))
    if payload.get("empty"):
        return {"status": payload.get("reason", "No data for this scope.")}

    trend = payload["trend"]
    facts: dict[str, Any] = {
        "scope": scope_note(scope, db),
        "unit": "units of ordered demand per month",
        "window": payload["window"],
        "months": len(trend),
        "first_month": trend[0]["period"],
        "latest_month": trend[-1]["period"],
        "latest_demand_units": trend[-1]["demand_units"],
        "first_demand_units": trend[0]["demand_units"],
        "mean_monthly_units": round(sum(r["demand_units"] for r in trend) / len(trend), 2),
        "peak": max(trend, key=lambda r: r["demand_units"])["period"],
        "trough": min(trend, key=lambda r: r["demand_units"])["period"],
        "demand_value_rupees": payload["kpis"]["demand_value"],
        "demand_value_display": _rupees(payload["kpis"]["demand_value"]),
        "fill_rate_pct": payload["kpis"]["fill_rate_pct"],
        "caveats": payload["notes"],
        "panel_build_id": build.id,
    }
    first, last = trend[0]["demand_units"], trend[-1]["demand_units"]
    facts["change_pct"] = round((last - first) / first * 100, 1) if first else None
    facts["direction"] = "flat" if facts["change_pct"] is None or abs(facts["change_pct"]) < 5 else (
        "rising" if facts["change_pct"] > 0 else "falling"
    )
    if visual:
        facts["chart"] = _chart(
            chart_type if chart_type in ("line", "bar") else "line",
            f"Ordered demand — {scope_note(scope, db)}",
            [{"period": r["period"], "demand": r["demand_units"]} for r in trend],
            [{"key": "demand", "label": "Ordered units"}],
            "period",
        )
    return facts


def branch_demand(db: Session, scope: dict | None, *, visual: bool = False, chart_type: str | None = None) -> dict[str, Any]:
    """Ordered demand broken down by branch, largest first."""
    from app.domain.ais import analytics as A

    panel, build, path, _scope = _panel_and_path(db)
    payload = A.cached_summary(panel, path, _analytics_scope(None, panel))
    if payload.get("empty"):
        return {"status": payload.get("reason", "No data.")}
    rows = payload["by_branch"][:MAX_TABLE_ROWS]
    facts = {
        "unit": "units of ordered demand over the window below",
        "window": payload["window"],
        "branches_total": payload["kpis"]["branch_count"],
        # The workspace SKU total, because the per-branch counts below cannot
        # be added to reach it: a SKU sold in both branches is one SKU and two
        # rows. Asked how many SKUs this workspace covers, the assistant summed
        # 136 and 135 and answered "271" - which is the series count, not the
        # SKU count. It only became visible once the branches stopped carrying
        # identical SKU lists.
        "skus_total": payload["kpis"]["sku_count"],
        "skus_total_note": (
            "The distinct SKUs in this workspace. The per-branch `skus` counts "
            "below overlap and must never be added together."
        ),
        "total_demand_value_display": _rupees(payload["kpis"]["demand_value"]),
        "total_demand_units": _whole(payload["kpis"]["demand_units"]),
        # Fill rate per branch, so "compare these two branches on fill rate"
        # can be answered. Without it the assistant gave one branch's rate from
        # the network trend and said the other was not in the facts (D-125).
        "branches_ranked_by_demand": [
            {
                "branch": r["name"],
                "units": r["demand_units"],
                "value_rupees": r["demand_value"],
                "value_display": _rupees(r["demand_value"]),
                "skus": r["sku_count"],
                "despatched_units": r["despatched_units"],
                "shortfall_units": r["shortfall_units"],
                "fill_rate_pct": (
                    round(100.0 * r["despatched_units"] / r["demand_units"], 2)
                    if r["demand_units"]
                    else None
                ),
            }
            for r in rows
        ],
        "panel_build_id": build.id,
    }
    if visual:
        facts["chart"] = _chart(
            chart_type if chart_type in ("bar", "pie") else "bar",
            "Ordered demand by branch",
            [{"name": r["name"], "units": r["demand_units"]} for r in rows],
            [{"key": "units", "label": "Ordered units"}],
            "name",
        )
    return facts


def model_leaderboard(db: Session, scope: dict | None, *, visual: bool = False, chart_type: str | None = None) -> dict[str, Any]:
    """The 13 registered models with their measured error, and the champion.

    Includes the models that did not run and why, because "which model is
    best" cannot be answered honestly while six of them are invisible.
    """
    from app.models.champions import ChampionSelection
    from app.models.training import ModelRun, TrainingRun

    # The newest completed run that actually holds national-scope rows, which
    # is not always the newest completed run: a local-tier run produces series
    # rows only. Reading the newest blindly made the assistant answer "no model
    # has been ranked" while a ranked national leaderboard sat one run back
    # (D-124).
    completed = (
        select(TrainingRun)
        .where(TrainingRun.status.in_(("completed", "completed_with_warnings")))
        .order_by(TrainingRun.created_at.desc())
    )
    run = db.scalars(
        completed.where(
            TrainingRun.id.in_(
                select(ModelRun.training_run_id).where(ModelRun.scope_level == "national")
            )
        ).limit(1)
    ).first()
    if run is None:
        if db.scalars(completed.limit(1)).first() is not None:
            return {
                "status": "Training has run, but only at series level, so no model "
                "has a national-scope error to rank. Run the aggregate tier to "
                "produce a national leaderboard."
            }
        return {"status": "No completed training run exists yet, so no model has a measured error."}

    rows = list(
        db.scalars(
            select(ModelRun)
            .where(ModelRun.training_run_id == run.id, ModelRun.scope_level == "national")
            .order_by(ModelRun.wape.is_(None), ModelRun.wape)
        )
    )
    models = [r for r in rows if not r.is_baseline]
    baselines = [r for r in rows if r.is_baseline]
    ranked = [r for r in models if r.wape is not None]

    facts: dict[str, Any] = {
        "training_run_id": run.id,
        # "national aggregate" is the *tier* name, not a claim about coverage:
        # the aggregate is the sum over whatever is in the workspace, which is
        # two branches here, not 53. Saying "the whole network" told the model
        # the opposite of the truth on every call (D-131).
        "scope": (
            f"aggregate tier — every series in scope summed per period ({_workspace_phrase(db)})"
        ),
        "unit": "WAPE, per cent — lower is better",
        "how_to_read_this_ranking": (
            "Sorted by WAPE, which is NOT the same as sorted by trustworthiness. "
            "Rows differ in evaluation_mode and validation_points, and a lower "
            "error measured on fewer points does not beat a higher one measured "
            "on more. The `champion` field below is the application's decision "
            "and is the only model that should be described as champion or "
            "recommended. Never suggest replacing it with a higher-ranked row."
        ),
        "official_model_count": 13,
        # The metric the champion was actually chosen on, alongside the WAPE
        # the table is sorted by. Without it the assistant was asked "why is
        # this model champion", saw a lower WAPE on another row, and invented
        # a reason - "it was evaluated on fewer validation points or different
        # evaluation" - when the real answer is that Exponential Smoothing
        # Additive wins on horizon error, 1.96% against XGBoost's 8.30%.
        "ranking_metric": get_settings().champion_primary_metric,
        "ranking_metric_note": (
            "The champion is chosen on this metric, measured over the whole "
            "planning window rather than one period at a time, NOT on the WAPE "
            "the table is sorted by. To say why a model is champion, compare "
            "`ranking_metric_pct`. If a row has none, say the figure is not in "
            "the facts - never explain the choice by a difference you can see "
            "in some other column."
        ),
        "models_ranked_by_wape": [
            {"model": r.display_name, "wape_pct": round(r.wape, 3), "mae": r.mae, "mase": r.mase,
             "ranking_metric_pct": round(r.horizon_mape, 3) if r.horizon_mape is not None else None,
             "validation_points": r.validation_points, "evaluation_mode": r.evaluation_mode}
            for r in ranked[:MAX_TABLE_ROWS]
        ],
        "models_that_did_not_run": [
            {"model": r.display_name, "status": r.status, "reason": r.failure_reason}
            for r in models
            if r.wape is None
        ],
        # Baselines carry the ranking metric too. With WAPE alone, asked
        # whether a baseline beats the champion, the model compared the two
        # WAPE columns and answered "no, ma6 is lower" - while on the metric
        # that decides it the champion wins 1.96% to 10.57%. Whether a
        # baseline actually won is recorded, not inferred: `beaten_by_baseline`
        # on the champion is the application's own answer.
        "baselines": [
            {
                "method": r.display_name,
                "wape_pct": round(r.wape, 3) if r.wape is not None else None,
                "ranking_metric_pct": (
                    round(r.horizon_mape, 3) if r.horizon_mape is not None else None
                ),
            }
            for r in baselines
        ],
        "caveats": [
            "A baseline is never a registered model and can never be champion.",
            "Whether a baseline beat the champion is the `beaten_by_baseline` "
            "field on the champion - the application's own recorded answer. "
            "Report that field. Never decide it by comparing WAPE columns: "
            "the champion is chosen on `ranking_metric_pct`, and the two "
            "metrics disagree often.",
            "Rows evaluated by holdout_fast have fewer validation points than "
            "rolling_origin rows; the counts are given so they are not compared blindly.",
            "This is the national aggregate. Aggregate series are far easier to "
            "forecast than a single branch x SKU cell, so this error does not transfer down.",
        ],
    }
    # The champion is the stored decision, not the top of this table. Ranking
    # by WAPE alone crowned a model measured by holdout_fast on 26 points over
    # one measured by rolling_origin on 44, so the assistant named a different
    # champion than every other surface in the application (D-124).
    selection = db.scalars(
        select(ChampionSelection)
        .where(
            ChampionSelection.training_run_id == run.id,
            ChampionSelection.scope_kind == "overall",
            ChampionSelection.is_active.is_(True),
        )
        .limit(1)
    ).first()
    if selection is not None:
        champion_row = next(
            (r for r in ranked if r.display_name == selection.champion_display_name), None
        )
        facts["champion"] = {
            "model": selection.champion_display_name,
            "wape_pct": round(selection.champion_wape, 3) if selection.champion_wape is not None else None,
            "ranking_metric_pct": (
                round(champion_row.horizon_mape, 3)
                if champion_row is not None and champion_row.horizon_mape is not None
                else None
            ),
            "bias_pct": selection.champion_bias,
            "validation_points": selection.champion_validation_points,
            "evaluation_mode": selection.champion_evaluation_mode,
            "selected_by": selection.selection_source,
            "beaten_by_baseline": selection.beaten_by_baseline,
        }
        facts["caveats"].append(
            "The champion is the application's stored selection. It is chosen "
            "on `ranking_metric_pct`, so it is often NOT the lowest WAPE in "
            "the table - that is the expected case, not an anomaly, and the "
            "two metrics measure different things."
        )
    elif ranked:
        best = ranked[0]
        facts["champion"] = {"model": best.display_name, "wape_pct": round(best.wape, 3),
                             "bias_pct": best.bias, "validation_points": best.validation_points}
        facts["caveats"].append(
            "No champion has been selected for this run, so the lowest WAPE is "
            "shown instead of a stored decision."
        )
    best_baseline = min((r for r in baselines if r.wape is not None), key=lambda r: r.wape, default=None)
    champion_wape = (facts.get("champion") or {}).get("wape_pct")
    if best_baseline is not None:
        facts["best_baseline"] = {"method": best_baseline.display_name, "wape_pct": round(best_baseline.wape, 3)}
        if champion_wape is not None:
            facts["champion_beats_best_baseline"] = bool(champion_wape < best_baseline.wape)
    if visual and ranked:
        facts["chart"] = _chart(
            chart_type if chart_type in ("bar",) else "bar",
            "WAPE by model — national scope",
            [{"name": r.display_name, "wape": round(r.wape, 3)} for r in ranked[:10]],
            [{"key": "wape", "label": "WAPE %"}],
            "name",
        )
    return facts


def forecast_outlook(db: Session, scope: dict | None, *, visual: bool = False, chart_type: str | None = None) -> dict[str, Any]:
    """The stored forward forecast: point and service-level quantiles."""
    from app.models.forecasts import ForecastRow, ForecastRun

    run = db.scalars(
        select(ForecastRun).where(ForecastRun.status == "completed").order_by(ForecastRun.created_at.desc()).limit(1)
    ).first()
    if run is None:
        return {"status": "No completed forecast run exists yet, so there is no forward forecast to read."}

    query = select(ForecastRow).where(ForecastRow.forecast_run_id == run.id, ForecastRow.scope_level == "national")
    rows = sorted(db.scalars(query), key=lambda r: (r.horizon, r.period))
    if not rows:
        return {"status": "The newest forecast run stored no national rows."}

    facts: dict[str, Any] = {
        "forecast_run_id": run.id,
        "origin_period": getattr(run, "origin_period", None),
        # `scope_level == "national"` is the row's tier in the hierarchy, not a
        # statement that it covers the country. It is the total over the
        # workspace, and calling it "national" invited exactly the reading the
        # whole scope mechanism exists to prevent (D-131).
        "scope": f"top of the forecast hierarchy — the total over {_workspace_phrase(db)}",
        "unit": "units of ordered demand per month, reconciled",
        "horizons": [
            {
                "period": r.period,
                "horizon": r.horizon,
                "point": r.point_forecast,
                "q80": r.q80,
                "q90": r.q90,
                "q95": r.q95,
                "model": r.model_display_name or r.model_id,
                "pre_reconciliation": r.base_forecast,
                "reconciliation_adjustment": r.reconciliation_adjustment,
                "reconciliation_method": r.reconciliation_method,
                "interval_from": (
                    f"{r.quantile_method} - {r.quantile_pooling_level} - "
                    f"{r.quantile_residual_count} residuals"
                ),
                "target_source": r.target_source,
                "is_censored": r.is_censored,
            }
            for r in rows
        ],
        "caveats": [
            "q80/q90/q95 are service-level demand quantities, not a symmetric "
            "confidence band: q95 is the level demand is not expected to exceed 95% of the time.",
            "No month in this forecast has been observed yet, so it has no actuals to be compared against.",
            "The point value is post-reconciliation. The pre-reconciliation value and "
            "the adjustment are given separately, never folded together.",
        ],
    }
    if visual:
        facts["chart"] = _chart(
            chart_type if chart_type in ("line", "bar") else "line",
            "Forward forecast — national",
            [{"period": r.period, "point": r.point_forecast, "q95": r.q95} for r in rows],
            [{"key": "point", "label": "Point"}, {"key": "q95", "label": "q95"}],
            "period",
        )
    return facts


def stock_exceptions(db: Session, scope: dict | None, *, visual: bool = False, chart_type: str | None = None) -> dict[str, Any]:
    """Supply and data exceptions: short despatch, zero stock against demand."""
    from app.domain.ais import analytics as A

    panel, build, path, _scope = _panel_and_path(db)
    payload = A.cached_exceptions(panel, path, _analytics_scope(scope, panel))
    if payload.get("empty"):
        return {"status": payload.get("reason", "No exception condition in this scope.")}
    facts = {
        "scope": scope_note(scope, db),
        "unit": "affected branch x SKU lines",
        "totals": payload["kpis"],
        "by_type": [
            {"type": r["name"], "lines": r["lines"], "units": r["units"], "severity": r["severity"]}
            for r in payload["by_type"]
        ],
        "branches_ranked_by_exception_lines": payload["by_branch"][:MAX_TABLE_ROWS],
        "worst_lines": [
            {"branch": r["branch"], "sku": r["sku"], "type": r["label"], "units": r["units"]}
            for r in payload["top_lines"][:MAX_TABLE_ROWS]
        ],
        "definitions": {k: v["definition"] for k, v in payload["types"].items()},
        "caveats": payload["notes"],
        "panel_build_id": build.id,
    }
    if visual:
        facts["chart"] = _chart(
            chart_type if chart_type in ("bar", "pie") else "bar",
            f"Exception lines by type — {scope_note(scope, db)}",
            [{"name": r["name"], "lines": r["lines"]} for r in payload["by_type"]],
            [{"key": "lines", "label": "Lines"}],
            "name",
        )
    return facts


def inventory_recommendations(db: Session, scope: dict | None, *, visual: bool = False, chart_type: str | None = None) -> dict[str, Any]:
    """Current-snapshot replenishment recommendations and their inputs."""
    from app.services import inventory_service

    try:
        payload = inventory_service.recommendations(
            db, branch=(scope or {}).get("branch") or None, limit=MAX_TABLE_ROWS
        )
    except Exception as exc:  # noqa: BLE001 - relayed as a status, never as a number
        return {"status": f"Inventory recommendations are unavailable: {type(exc).__name__}."}

    items = payload.get("items") or []
    return {
        "scope": scope_note(scope, db),
        "unit": "units to order; stock and cover in units and days",
        "period": payload.get("period"),
        "service_level": payload.get("service_level"),
        "total_rows": payload.get("total"),
        "forecast_run_id": payload.get("forecast_run_id"),
        "unavailable_reason": payload.get("unavailable_reason"),
        "recommendations": [
            {
                "branch": item.get("canonical_branch"),
                "sku": item.get("canonical_sku"),
                # Whole units. The raw figure carries three decimals, and the
                # assistant read it out as "order 5070.994 units", which is not
                # a quantity anyone can place (D-125).
                "recommended_order": _whole(item.get("raw_recommended_order")),
                "order_up_to_level": _whole(item.get("order_up_to_level")),
                "quantile_forecast_per_month": item.get("monthly_quantile_forecast"),
                "point_forecast_per_month": item.get("monthly_point_forecast"),
                "stock_on_hand": item.get("closing_stock_on_hand"),
                "on_order": item.get("confirmed_stock_on_order"),
                "lead_time_days": item.get("lead_time_days"),
                "days_of_cover": item.get("days_of_cover"),
                "model": item.get("forecast_model_id"),
                "caveats": item.get("caveats"),
            }
            for item in items[:MAX_TABLE_ROWS]
        ],
        "caveats": (payload.get("notes") or [])
        + [
            "Stock is a single snapshot dated 2026-08-01 while demand history ends "
            "2026-07, so every recommendation is a current-snapshot estimate.",
            "There is no stock history, so no historical inventory-policy backtest exists.",
        ],
    }


def data_quality(db: Session, scope: dict | None, *, visual: bool = False, chart_type: str | None = None) -> dict[str, Any]:
    """Structural controls, freshness and drift."""
    from app.services import monitoring_service

    try:
        monitoring = monitoring_service.snapshot(db)
    except Exception as exc:  # noqa: BLE001
        return {"status": f"Monitoring is unavailable: {type(exc).__name__}."}
    drift = monitoring.get("drift") or {}
    return {
        "freshness": monitoring.get("freshness"),
        "drift": {
            "window_months": drift.get("window_months"),
            "national_shift_pct": (drift.get("national") or {}).get("shift_pct"),
            "target_source_changed": drift.get("target_source_changed"),
            "branches_ranked_by_shift": (drift.get("rows") or [])[:MAX_TABLE_ROWS],
        },
        "champions": {
            k: v for k, v in (monitoring.get("champions") or {}).items() if k != "rows"
        },
        "error_deterioration": monitoring.get("deterioration"),
        "caveats": [
            "No threshold is applied to any of these; each is reported with its window "
            "and counts so the reader applies their own.",
            "Part of the drift figure is a change of measurement, not of demand: the "
            "earlier window mixes sales-proxy rows and the recent window is all orders.",
        ],
    }


#: Name -> callable. The model may call these and nothing else.
TOOLS: dict[str, Callable[..., dict[str, Any]]] = {
    "demand_trend": demand_trend,
    "branch_demand": branch_demand,
    "model_leaderboard": model_leaderboard,
    "forecast_outlook": forecast_outlook,
    "stock_exceptions": stock_exceptions,
    "inventory_recommendations": inventory_recommendations,
    "data_quality": data_quality,
}

#: One line each, used verbatim as the function description in the tool schema.
TOOL_DESCRIPTIONS: dict[str, str] = {
    "demand_trend": "Monthly ordered-demand history for the current scope: level, direction, peak, trough, fill rate and demand value.",
    "branch_demand": "Ordered demand broken down by branch, ranked largest first, with SKU counts and rupee value.",
    "model_leaderboard": "The 13 registered models with measured WAPE/MAE/MASE at national scope, the champion, the baselines, and the reason any model did not run.",
    "forecast_outlook": "The stored forward forecast for horizons 1-6: point value plus q80/q90/q95 service levels per month.",
    "stock_exceptions": "Supply and data exceptions per branch x SKU line: short despatch, zero stock against live demand, over-despatch, negative stock, unmapped SKUs.",
    "inventory_recommendations": "Current-snapshot replenishment recommendations with their calculation inputs: order quantity, order-up-to level, q95 demand, usable stock, lead time and cover.",
    "data_quality": "Data freshness, input drift by branch, champion age and whether error deterioration is computable yet.",
}

#: Keyword routing for the no-key and provider-failure paths. Deliberately the
#: same tools, so the fallback answers the same question with the same numbers
#: — just chosen by keyword rather than by the model.
_ROUTING: list[tuple[frozenset[str], str]] = [
    (frozenset({"model", "champion", "wape", "accuracy", "baseline", "leaderboard", "best"}), "model_leaderboard"),
    (frozenset({"forecast", "next", "outlook", "q95", "q90", "q80", "horizon", "predict"}), "forecast_outlook"),
    (frozenset({"stock", "zero", "dead", "slow", "exception", "shortfall", "censored", "despatch"}), "stock_exceptions"),
    (frozenset({"order", "reorder", "replenish", "recommendation", "cover", "inventory"}), "inventory_recommendations"),
    (frozenset({"drift", "fresh", "quality", "deterioration", "monitoring"}), "data_quality"),
    (frozenset({"branch", "branches", "depot", "region", "location"}), "branch_demand"),
    (frozenset({"demand", "trend", "history", "monthly", "seasonality", "volume"}), "demand_trend"),
]


def select_tools(question: str, limit: int = 2) -> list[str]:
    words = set(_words(question))
    hits = [name for terms, name in _ROUTING if terms & words]
    seen: list[str] = []
    for name in hits:
        if name not in seen:
            seen.append(name)
    return seen[:limit]


def assistant_available() -> bool:
    return bool(get_settings().ai_assistant_enabled)

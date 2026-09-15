"""Data and model monitoring.

Four questions, each answered from a real artifact rather than a heuristic:

**Data freshness** — how old is the newest month in the panel, and how old is
the stock snapshot. On this dataset those disagree by a month, and the answer
says so rather than reporting one age.

**Input drift** — the last observed months against the earlier history, per
scope, from the panel itself. Drift is reported as a measured shift with its
window, never as a pass/fail flag whose threshold is invisible.

**Champion age** — how long the active champion has been in force, and whether
the run behind it is still the newest.

**Error deterioration** — the champion's backtest WAPE against the error it is
actually accruing on months that have since been observed. This is the only
honest way to detect a model going stale, and on this dataset it is frequently
**not computable**: the forecast origin is the last observed month, so no
actual exists yet for any forecast period. That is reported as "not yet
computable", never as "no deterioration".

Nothing here raises an alert. A monitoring page that decides for the reader
what counts as a problem hides the number that mattered.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import NotFoundError
from app.core.logging import get_logger
from app.db.session import session_scope
from app.models.champions import ChampionSelection
from app.models.datasets import DatasetVersion
from app.models.forecasts import ForecastRow, ForecastRun
from app.models.mappings import PreprocessingRun
from app.models.panel import PanelBuild
from app.models.training import ModelRun, TrainingRun

logger = get_logger(__name__)

#: How many trailing months count as "recent" when measuring drift. Six matches
#: the forecast horizon, so the window being compared is the length of the plan
#: the models are asked to produce.
DRIFT_WINDOW_MONTHS = 6


def _period_to_date(period: str) -> date | None:
    try:
        year, month = (int(part) for part in period.split("-")[:2])
        return date(year, month, 1)
    except (ValueError, AttributeError):
        return None


def _months_between(earlier: date | None, later: date | None) -> int | None:
    if earlier is None or later is None:
        return None
    return (later.year - earlier.year) * 12 + (later.month - earlier.month)


def data_freshness(db: Session) -> dict[str, Any]:
    """How current each input actually is, reported separately.

    The panel's newest month and the stock snapshot's date are different facts
    and are a month apart on this dataset. Collapsing them into one "data age"
    would hide exactly the discrepancy that makes the inventory
    recommendations current-snapshot estimates.
    """
    settings = get_settings()
    today = datetime.now(timezone.utc).date()

    build = db.scalars(
        select(PanelBuild)
        .where(PanelBuild.status == "completed")
        .order_by(PanelBuild.created_at.desc())
        .limit(1)
    ).first()
    version = db.scalars(
        select(DatasetVersion).order_by(DatasetVersion.created_at.desc()).limit(1)
    ).first()

    newest_period: str | None = None
    if build is not None:
        summary = build.summary_json or {}
        newest_period = summary.get("last_period") or summary.get("max_period")
    if newest_period is None:
        run = db.scalars(
            select(ForecastRun)
            .where(ForecastRun.status == "completed")
            .order_by(ForecastRun.created_at.desc())
            .limit(1)
        ).first()
        newest_period = run.origin_period if run else None

    snapshot = _period_to_date(settings.stock_snapshot_date[:7])
    demand_end = _period_to_date(newest_period or "")

    return {
        "demand_history_end": newest_period,
        "demand_history_age_months": _months_between(demand_end, today),
        "stock_snapshot_date": settings.stock_snapshot_date,
        "stock_snapshot_age_months": _months_between(snapshot, today),
        "panel_built_at": build.created_at if build else None,
        "panel_rows": build.panel_rows if build else 0,
        "dataset_ingested_at": version.created_at if version else None,
        "note": (
            "Demand history and the stock snapshot are reported separately "
            "because they do not end at the same month. The stock file is dated "
            f"{settings.stock_snapshot_date} while demand history ends "
            f"{newest_period or 'unknown'} - which is why every inventory "
            "recommendation is labelled a current-snapshot estimate."
        ),
    }


def input_drift(
    db: Session, *, window_months: int = DRIFT_WINDOW_MONTHS
) -> dict[str, Any]:
    """Recent demand against the earlier history, measured from the panel.

    Reported as a percentage shift with both window means and both row counts,
    so a reader can see whether a large shift rests on a handful of months. No
    threshold is applied: what counts as material depends on the branch, and
    encoding one here would make the judgement invisible.
    """
    build = db.scalars(
        select(PanelBuild)
        .where(PanelBuild.status == "completed")
        .order_by(PanelBuild.created_at.desc())
        .limit(1)
    ).first()
    if build is None or not (build.artifacts_json or {}).get("panel"):
        return {
            "available": False,
            "reason": (
                "No completed panel build with a panel artifact exists, so drift "
                "cannot be measured."
            ),
            "window_months": window_months,
            "rows": [],
        }

    try:
        frame = pd.read_parquet(
            (build.artifacts_json or {})["panel"],
            # `canonical_sku` is read only so the workspace SKU restriction can
            # be applied below. Without it the cut is a silent no-op and drift
            # would be measured over products no other page shows.
            columns=["period", "target", "canonical_branch", "canonical_sku", "target_source"],
        )
        # Drift is reported per branch, so it has to be measured over the same
        # branches every other page shows. A national drift figure computed
        # over 53 branches beside a two-branch Demand Analytics page would be
        # two different questions wearing one label (docs/DECISIONS.md D-049).
        from app.domain.ais.workspace import resolve_workspace

        frame = resolve_workspace(db).restrict(frame, "canonical_branch")
    except (OSError, ValueError, KeyError) as exc:
        # A moved or unreadable artifact must degrade this measure, not fail the
        # whole monitoring page - the other three measures do not depend on it.
        return {
            "available": False,
            "reason": (
                f"The panel artifact could not be read ({type(exc).__name__}), "
                "so drift cannot be measured. The rest of the monitoring "
                "snapshot is unaffected."
            ),
            "window_months": window_months,
            "rows": [],
        }
    periods = sorted(frame["period"].dropna().unique())
    if len(periods) <= window_months:
        return {
            "available": False,
            "reason": (
                f"The panel has {len(periods)} month(s), which is not more than "
                f"the {window_months}-month comparison window, so there is no "
                "earlier period to compare against."
            ),
            "window_months": window_months,
            "rows": [],
        }

    recent_periods = set(periods[-window_months:])
    recent = frame[frame["period"].isin(recent_periods)]
    earlier = frame[~frame["period"].isin(recent_periods)]

    def _summary(subset: pd.DataFrame, column: str | None = None) -> dict[str, Any]:
        grouped = subset.groupby("period", observed=True)["target"].sum()
        return {
            "months": int(len(grouped)),
            "mean_monthly_demand": float(grouped.mean()) if len(grouped) else None,
            "rows": int(len(subset)),
        }

    national_recent = _summary(recent)
    national_earlier = _summary(earlier)
    shift = None
    if (
        national_earlier["mean_monthly_demand"]
        and national_recent["mean_monthly_demand"] is not None
    ):
        shift = (
            (national_recent["mean_monthly_demand"] - national_earlier["mean_monthly_demand"])
            / national_earlier["mean_monthly_demand"]
            * 100.0
        )

    rows: list[dict[str, Any]] = []
    if "canonical_branch" in frame.columns:
        recent_branch = (
            recent.groupby(["canonical_branch", "period"], observed=True)["target"]
            .sum()
            .groupby("canonical_branch", observed=True)
            .mean()
        )
        earlier_branch = (
            earlier.groupby(["canonical_branch", "period"], observed=True)["target"]
            .sum()
            .groupby("canonical_branch", observed=True)
            .mean()
        )
        for branch in sorted(set(recent_branch.index) | set(earlier_branch.index)):
            before = float(earlier_branch.get(branch, 0.0))
            after = float(recent_branch.get(branch, 0.0))
            rows.append(
                {
                    "scope_level": "branch",
                    "scope_key": str(branch),
                    "earlier_mean_monthly_demand": before,
                    "recent_mean_monthly_demand": after,
                    "shift_pct": ((after - before) / before * 100.0) if before else None,
                }
            )
        rows.sort(
            key=lambda row: abs(row["shift_pct"]) if row["shift_pct"] is not None else -1,
            reverse=True,
        )

    # The target source changes mid-history on this dataset, and a shift that
    # coincides with it is a measurement change rather than a demand change.
    sources = (
        frame.groupby("period", observed=True)["target_source"]
        .agg(lambda values: sorted(set(values.dropna())))
        .to_dict()
        if "target_source" in frame.columns
        else {}
    )
    recent_sources = sorted(
        {source for period in recent_periods for source in sources.get(period, [])}
    )
    earlier_sources = sorted(
        {
            source
            for period, values in sources.items()
            if period not in recent_periods
            for source in values
        }
    )

    return {
        "available": True,
        "reason": None,
        "window_months": window_months,
        "recent_periods": sorted(recent_periods),
        "national": {
            "earlier": national_earlier,
            "recent": national_recent,
            "shift_pct": shift,
        },
        "target_sources_recent": recent_sources,
        "target_sources_earlier": earlier_sources,
        "target_source_changed": recent_sources != earlier_sources,
        "rows": rows[:60],
        "note": (
            "No threshold is applied. A shift is reported with both window means "
            "and both row counts so the reader can judge whether it is material. "
            + (
                "The target source differs between the two windows "
                f"({earlier_sources} then {recent_sources}), so part of any shift "
                "is a change of measurement rather than of demand."
                if recent_sources != earlier_sources
                else "The target source is the same across both windows."
            )
        ),
    }


def champion_age(db: Session) -> dict[str, Any]:
    """How old each active champion is, and whether its run is still current."""
    newest_run = db.scalars(
        select(TrainingRun).order_by(TrainingRun.created_at.desc()).limit(1)
    ).first()
    selections = list(
        db.scalars(
            select(ChampionSelection)
            .where(ChampionSelection.is_active.is_(True))
            .order_by(ChampionSelection.scope_kind, ChampionSelection.scope_key)
        )
    )
    now = datetime.now(timezone.utc)

    rows: list[dict[str, Any]] = []
    stale = 0
    for selection in selections:
        created = selection.created_at
        if created is not None and created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age_days = (now - created).total_seconds() / 86_400 if created else None
        from_newest = (
            newest_run is not None and selection.training_run_id == newest_run.id
        )
        if not from_newest:
            stale += 1
        rows.append(
            {
                "scope_kind": selection.scope_kind,
                "scope_key": selection.scope_key,
                "champion_model_id": selection.champion_model_id,
                "selection_source": selection.selection_source,
                "selected_at": created,
                "age_days": age_days,
                "training_run_id": selection.training_run_id,
                "from_newest_training_run": from_newest,
                "beaten_by_baseline": selection.beaten_by_baseline,
            }
        )

    beaten = sum(1 for row in rows if row["beaten_by_baseline"])
    return {
        "active_champions": len(rows),
        "newest_training_run_id": newest_run.id if newest_run else None,
        "champions_from_older_runs": stale,
        "champions_beaten_by_a_baseline": beaten,
        "rows": rows[:200],
        "note": (
            f"{beaten} of {len(rows)} active champion(s) are beaten by a "
            "non-registry baseline in their own scope. That is recorded on the "
            "selection rather than hidden: the champion is the best of the 13 "
            "registered models, which is not the same as the best available "
            "forecast."
        )
        if rows
        else "No champion has been selected yet.",
    }


def error_deterioration(db: Session) -> dict[str, Any]:
    """Accrued forecast error against the champion's backtest error.

    Only computable where a forecast period has since been observed in the
    panel. On this dataset the forecast origin **is** the last observed month,
    so nothing is observable yet - and that is what is reported. A monitoring
    page that showed "0% deterioration" here would be asserting the model is
    holding up when nothing has been checked.
    """
    run = db.scalars(
        select(ForecastRun)
        .where(ForecastRun.status == "completed")
        .order_by(ForecastRun.created_at.desc())
        .limit(1)
    ).first()
    if run is None:
        return {
            "computable": False,
            "reason": "No completed forecast run exists.",
            "rows": [],
        }

    build = db.get(PanelBuild, run.panel_build_id)
    artifacts = (build.artifacts_json or {}) if build else {}
    if not artifacts.get("panel"):
        return {
            "computable": False,
            "reason": "The panel artifact behind this forecast run is unavailable.",
            "rows": [],
        }

    forecast_periods = set(
        db.scalars(
            select(ForecastRow.period)
            .where(ForecastRow.forecast_run_id == run.id)
            .distinct()
        )
    )
    try:
        frame = pd.read_parquet(artifacts["panel"], columns=["period"])
    except (OSError, ValueError, KeyError) as exc:
        return {
            "computable": False,
            "reason": (
                f"The panel artifact could not be read ({type(exc).__name__}), "
                "so accrued error cannot be compared against it."
            ),
            "rows": [],
        }
    observed = set(frame["period"].dropna().unique())
    overlap = sorted(forecast_periods & observed)

    if not overlap:
        return {
            "computable": False,
            "reason": (
                f"None of the {len(forecast_periods)} forecast period(s) has been "
                "observed yet - the forecast origin is the last month the panel "
                f"holds ({run.origin_period}), so there is no actual to compare "
                "against. Deterioration becomes computable once a month of "
                "actuals arrives after the origin. Reporting no deterioration "
                "here would claim a check that has not happened."
            ),
            "forecast_periods": sorted(forecast_periods),
            "origin_period": run.origin_period,
            "rows": [],
        }

    # There is overlap, so accrued error can be measured for those months.
    rows: list[dict[str, Any]] = []
    try:
        panel = pd.read_parquet(
            artifacts["panel"], columns=["period", "target", "canonical_branch"]
        )
    except (OSError, ValueError, KeyError) as exc:
        return {
            "computable": False,
            "reason": (
                f"The panel artifact could not be read ({type(exc).__name__})."
            ),
            "rows": [],
        }
    actuals = (
        panel[panel["period"].isin(overlap)]
        .groupby(["canonical_branch", "period"], observed=True)["target"]
        .sum()
    )
    forecast_rows = list(
        db.scalars(
            select(ForecastRow).where(
                ForecastRow.forecast_run_id == run.id,
                ForecastRow.period.in_(overlap),
                ForecastRow.scope_level == "branch",
                ForecastRow.point_forecast.is_not(None),
            )
        )
    )
    for row in forecast_rows:
        actual = actuals.get((row.scope_key, row.period))
        if actual is None:
            continue
        model_run = db.get(ModelRun, row.model_run_id) if row.model_run_id else None
        error = abs(float(row.point_forecast or 0.0) - float(actual))
        accrued_wape = (error / float(actual) * 100.0) if actual else None
        backtest_wape = model_run.wape if model_run else None
        rows.append(
            {
                "scope_level": row.scope_level,
                "scope_key": row.scope_key,
                "period": row.period,
                "model_id": row.model_id,
                "actual": float(actual),
                "point_forecast": float(row.point_forecast or 0.0),
                "absolute_error": error,
                "accrued_wape": accrued_wape,
                "backtest_wape": backtest_wape,
                "deterioration_pct": (
                    accrued_wape - backtest_wape
                    if accrued_wape is not None and backtest_wape is not None
                    else None
                ),
            }
        )
    rows.sort(
        key=lambda row: row["deterioration_pct"]
        if row["deterioration_pct"] is not None
        else float("-inf"),
        reverse=True,
    )
    return {
        "computable": True,
        "reason": None,
        "origin_period": run.origin_period,
        "observed_forecast_periods": overlap,
        "rows": rows[:200],
        "note": (
            "Accrued WAPE is measured on months that have been observed since "
            "the forecast was made; backtest WAPE is what the champion scored "
            "out of sample when it was chosen. A positive deterioration means "
            "the model is doing worse in production than in validation."
        ),
    }


def snapshot(db: Session) -> dict[str, Any]:
    """Everything the monitoring page shows, in one response."""
    from app.domain.ais.workspace import resolve_workspace

    # The drift measure above is already cut to the workspace. Carrying the
    # scope on the payload is what stops a two-branch figure reading as a
    # national one - a restriction applied without being stated is the exact
    # failure D-049 exists to prevent.
    scope = resolve_workspace(db)
    return {
        "workspace_scope": scope.as_dict(),
        "generated_at": datetime.now(timezone.utc),
        "freshness": data_freshness(db),
        "drift": input_drift(db),
        "champions": champion_age(db),
        "deterioration": error_deterioration(db),
        "note": (
            "Nothing here raises an alert. Each measure is reported with its "
            "window and its counts so the reader applies their own threshold; a "
            "page that decided what counts as a problem would hide the number "
            "that mattered."
        ),
    }

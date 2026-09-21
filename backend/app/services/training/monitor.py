"""Live view of a training run: per-model state and the fold design.

The run-level SSE stream already carries counters, but counters cannot answer
the question someone actually has while a run is going - *which* models are
working, which are refusing, and how well the ones that finished are doing.
That needs per-model aggregation, and doing it in the browser would mean
shipping every model run row (884 on the current workspace) on every poll.

Two things are deliberately kept apart here:

**Status counts are not accuracy.** A model with 60 completed runs and a
terrible WAPE is not doing better than one with 20 completed runs and a good
one. Both are returned; neither is collapsed into a single "score".

**The four non-registry baselines are flagged, never mixed in.** They run
alongside the thirteen so the champion can be checked against them, but they
are not candidates. `is_baseline` travels with every row so the UI cannot
accidentally present naive as the fourteenth model.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.champions import ChampionSelection
from app.models.training import ModelRun, TrainingRun

#: Statuses a model run can end in. Listed explicitly so a new one added
#: upstream shows up as an unexpected key rather than being silently folded
#: into a total that no longer adds up.
STATUSES: tuple[str, ...] = (
    "completed",
    "ineligible",
    "failed",
    "timed_out",
    "not_evaluated",
    "running",
    "pending",
)


def _folds(origins: Any) -> list[dict[str, Any]]:
    """The validation design, read from what a run actually did.

    Taken from a stored fold rather than restated from configuration: if the
    run used a different split than the settings imply, this shows the split
    that was used.
    """
    if isinstance(origins, str):
        import json

        try:
            origins = json.loads(origins)
        except (TypeError, ValueError):
            return []
    if not isinstance(origins, list):
        return []
    out = []
    for fold in origins:
        if not isinstance(fold, dict):
            continue
        periods = fold.get("periods") or []
        out.append(
            {
                "index": fold.get("fold_index"),
                "name": fold.get("origin_name"),
                "train_end": fold.get("train_end_period"),
                "train_rows": fold.get("train_rows"),
                "validate_from": periods[0] if periods else None,
                "validate_to": periods[-1] if periods else None,
                "validate_months": len(periods),
                "horizons": fold.get("horizons") or [],
            }
        )
    return out


#: How many completed rows to inspect when picking a representative fold set.
FOLD_CANDIDATES = 40


def fold_design(db: Session, run_id: str) -> list[dict[str, Any]]:
    """The most complete fold set the run actually scored.

    Not the first completed row. Taking `LIMIT 1` picked a model whose second
    origin scored no points, so the panel rendered "validate None -> None
    (0 months)" for origin 2 - a real split shown as a missing one. A model can
    legitimately complete one origin and produce nothing on another (too little
    history at that cut, every point dropped), so the first row is not a safe
    stand-in for the design.

    Several candidates are read and the one with the most fully-specified
    origins wins, tie-broken on origin count. That reports the design as
    executed by a run that actually reached both cuts, which is what the panel
    claims to be showing.
    """
    rows = db.execute(
        select(ModelRun.origins_json)
        .where(
            ModelRun.training_run_id == run_id,
            ModelRun.origins_json.is_not(None),
            ModelRun.status == "completed",
        )
        .limit(FOLD_CANDIDATES)
    ).all()

    best: list[dict[str, Any]] = []
    best_score = (-1, -1)
    for (raw,) in rows:
        folds = _folds(raw)
        if not folds:
            continue
        complete = sum(
            1 for f in folds if f.get("validate_from") and f.get("validate_to")
        )
        score = (complete, len(folds))
        if score > best_score:
            best, best_score = folds, score
        if complete == len(folds) and len(folds) > 1:
            break  # every origin specified; nothing better to find
    return best


def model_progress(db: Session, run_id: str) -> list[dict[str, Any]]:
    """Per-model state across every scope the run touched."""
    rows = list(
        db.execute(
            select(
                ModelRun.model_id,
                ModelRun.display_name,
                ModelRun.is_baseline,
                ModelRun.status,
                ModelRun.scope_level,
                ModelRun.wape,
                ModelRun.mape,
                ModelRun.mae,
                ModelRun.rmse,
                ModelRun.smape,
                ModelRun.mase,
                ModelRun.bias,
                ModelRun.validation_points,
                ModelRun.failure_reason,
                ModelRun.fit_seconds,
            ).where(ModelRun.training_run_id == run_id)
        )
    )

    champions: dict[str, int] = defaultdict(int)
    for (model_id,) in db.execute(
        select(ChampionSelection.champion_model_id).where(
            ChampionSelection.training_run_id == run_id,
            ChampionSelection.is_active.is_(True),
        )
    ):
        if model_id:
            champions[model_id] += 1

    agg: dict[str, dict[str, Any]] = {}
    for (
        model_id,
        display,
        is_baseline,
        status,
        scope_level,
        wape,
        mape,
        mae,
        rmse,
        smape,
        mase,
        bias,
        points,
        reason,
        fit,
    ) in rows:
        cell = agg.setdefault(
            model_id,
            {
                "model_id": model_id,
                "display_name": display or model_id,
                "is_baseline": bool(is_baseline),
                "total": 0,
                "fit_seconds": 0.0,
                "_wape": [],
                "_mape": [],
                "_mape_series": [],
                "_mape_aggregate": [],
                "_mape_weighted": [],
                "_mae": [],
                "_rmse": [],
                "_smape": [],
                "_mase": [],
                "_bias": [],
                "validation_points": 0,
                "reason": None,
                **{s: 0 for s in STATUSES},
            },
        )
        cell["total"] += 1
        if status in cell:
            cell[status] += 1
        else:
            cell.setdefault("other", 0)
            cell["other"] += 1
        if fit:
            cell["fit_seconds"] += float(fit)
        for key, value in (
            ("_wape", wape),
            ("_mape", mape),
            ("_mae", mae),
            ("_rmse", rmse),
            ("_smape", smape),
            ("_mase", mase),
            ("_bias", bias),
        ):
            if value is not None:
                cell[key].append(float(value))
        # Split by grain. One blended accuracy is misleading here: a national
        # total forecasts to about 12% MAPE while a single branch x SKU month
        # is nearer 48%, and the pooled median is dominated by the series rows
        # simply because there are far more of them. Reporting one number made
        # the models look far worse than they are at the levels they are
        # actually accurate on (docs/DECISIONS.md D-081).
        if mape is not None:
            key = "_mape_series" if scope_level == "series" else "_mape_aggregate"
            cell[key].append(float(mape))
            # Volume-weighted accuracy, alongside the unweighted figure.
            #
            # The unweighted mean treats every scope alike, so a SKU selling 99
            # units in 28 months counts as much as one selling 9,672. Measured
            # on this workspace that single choice is worth 22 points at series
            # grain (50.4% unweighted against 72.9% weighted), because MAPE
            # explodes on small denominators: a line averaging 3.5 units a
            # month that is wrong by 7 units scores 200% and has cost nobody
            # anything.
            #
            # The scope's volume is recovered from the two metrics already
            # stored, no new column and no second pass over the panel:
            #   WAPE = 100 * sum|a - f| / sum|a|,  MAE = sum|a - f| / n
            #   =>  sum|a| = 100 * MAE * n / WAPE
            # A zero or missing WAPE leaves the volume unknowable, so that
            # scope is left out of the weighted figure rather than given an
            # invented weight.
            if wape and points and mae is not None and float(wape) > 0:
                volume = 100.0 * float(mae) * int(points) / float(wape)
                if volume > 0:
                    cell["_mape_weighted"].append((float(mape), volume))
        if points:
            cell["validation_points"] = max(cell["validation_points"], int(points))
        # The first eligibility reason seen, so the leaderboard can say *why* a
        # model did not run rather than only that it did not.
        if status == "ineligible" and reason and not cell["reason"]:
            cell["reason"] = reason

    out = []
    for cell in agg.values():
        wapes = cell.pop("_wape")
        mapes = cell.pop("_mape")
        cell["median_wape"] = round(statistics.median(wapes), 2) if wapes else None
        cell["best_wape"] = round(min(wapes), 2) if wapes else None
        cell["median_mape"] = round(statistics.median(mapes), 2) if mapes else None
        # Accuracy is 100 - MAPE clamped at zero - this project's definition
        # (D-043) and the metric the champion selector ranks on. Computed here
        # so every surface reads the same number from one place.
        cell["accuracy"] = (
            round(max(0.0, 100.0 - statistics.median(mapes)), 2) if mapes else None
        )
        weighted = cell.pop("_mape_weighted")
        cell["accuracy_weighted"] = None
        # The MAPE the weighted accuracy is literally 100 minus.
        #
        # The row previously printed a volume-WEIGHTED accuracy next to a
        # MEDIAN MAPE: 83.7% beside 27.3%, where 100 - 27.3 is 72.7. Both were
        # right and the pair was unreadable, because they are two different
        # aggregations of one metric. Publishing the weighted MAPE as well lets
        # the leaderboard show a row whose arithmetic closes.
        cell["mape_weighted"] = None
        if weighted:
            total_volume = sum(volume for _m, volume in weighted)
            if total_volume > 0:
                mape_w = sum(m * volume for m, volume in weighted) / total_volume
                cell["mape_weighted"] = round(mape_w, 2)
                cell["accuracy_weighted"] = round(max(0.0, 100.0 - mape_w), 2)
        for key, label in (
            ("_mape_series", "accuracy_series"),
            ("_mape_aggregate", "accuracy_aggregate"),
        ):
            values = cell.pop(key)
            cell[label] = (
                round(max(0.0, 100.0 - statistics.median(values)), 2) if values else None
            )
        for key, label in (
            ("_mae", "median_mae"),
            ("_rmse", "median_rmse"),
            ("_smape", "median_smape"),
            ("_mase", "median_mase"),
            ("_bias", "median_bias"),
        ):
            values = cell.pop(key)
            cell[label] = round(statistics.median(values), 2) if values else None
        cell["fit_seconds"] = round(cell["fit_seconds"], 2)
        cell["champion_count"] = champions.get(cell["model_id"], 0)
        cell["scored"] = len(wapes)
        out.append(cell)

    # Registry models first, then the baselines, each by how often they won.
    out.sort(key=lambda c: (c["is_baseline"], -c["champion_count"], c["model_id"]))
    return out


def pipeline(db: Session, run_id: str) -> dict[str, Any]:
    """The shape of the run: how many scopes, of what kind, and who won them.

    The Training page explained the *rules* but never the *shape* - how many
    fits a run actually performs, at which levels, and how a champion at one
    level relates to a champion at another. That is the first thing anyone
    being shown this asks, and it was only answerable by reading the database.
    """
    scope_rows = db.execute(
        select(ModelRun.scope_level, ModelRun.scope_key)
        .where(ModelRun.training_run_id == run_id)
        .distinct()
    ).all()
    by_level: dict[str, int] = {}
    for level, _key in scope_rows:
        by_level[str(level)] = by_level.get(str(level), 0) + 1

    models = db.execute(
        select(ModelRun.model_id, ModelRun.is_baseline)
        .where(ModelRun.training_run_id == run_id)
        .distinct()
    ).all()

    champions = db.execute(
        select(ChampionSelection.champion_model_id, ChampionSelection.beaten_by_baseline)
        .where(
            ChampionSelection.training_run_id == run_id,
            ChampionSelection.is_active.is_(True),
        )
    ).all()
    spread: dict[str, int] = {}
    beaten = 0
    for model_id, was_beaten in champions:
        if model_id:
            spread[model_id] = spread.get(model_id, 0) + 1
        if was_beaten:
            beaten += 1

    return {
        "scopes_total": len(scope_rows),
        "scopes_by_level": by_level,
        "registry_models": sum(1 for _m, b in models if not b),
        "baseline_models": sum(1 for _m, b in models if b),
        "champions_selected": len(champions),
        "champions_beaten_by_baseline": beaten,
        "champion_spread": dict(sorted(spread.items(), key=lambda kv: -kv[1])),
    }


def snapshot(db: Session, run: TrainingRun) -> dict[str, Any]:
    """Everything the monitor renders for one run."""
    models = model_progress(db, run.id)
    return {
        "run_id": run.id,
        "status": run.status,
        "stage_detail": run.stage_detail,
        "progress_pct": run.progress_pct,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "duration_seconds": run.duration_seconds,
        "is_live": run.status in ("running", "queued", "pending"),
        "counters": {
            "total": run.model_runs_total,
            "completed": run.model_runs_completed,
            "ineligible": run.model_runs_ineligible,
            "failed": run.model_runs_failed,
            "timed_out": run.model_runs_timed_out,
            "not_evaluated": run.model_runs_not_evaluated,
        },
        "series_requested": run.series_requested,
        "series_evaluated": run.series_evaluated,
        "restriction": run.restriction_json,
        "folds": fold_design(db, run.id),
        "pipeline": pipeline(db, run.id),
        "models": models,
        "registry_model_count": sum(1 for m in models if not m["is_baseline"]),
        "baseline_model_count": sum(1 for m in models if m["is_baseline"]),
    }

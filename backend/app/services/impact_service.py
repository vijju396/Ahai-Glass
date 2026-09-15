"""Assembles the impact report: measured accuracy plus a stated projection.

The measurement half reads the folds that were already scored during training
rather than re-running anything. `model_run.origins_json` carries, per fold,
the horizons, the actuals and the predictions, so per-horizon error is
recoverable exactly as it was computed - no second evaluation path that could
drift from the first.

The comparison is against `naive`, one of the four non-registry baselines.
That choice is deliberate: a naive carry-forward is what a branch does without
a forecasting system, so "how much better than naive" is the closest thing to
"what did the system buy you" that this project can honestly measure.
"""

from __future__ import annotations

import json
from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.domain.ais.impact import (
    DEFAULT_ASSUMPTIONS,
    Exposure,
    ImpactReport,
    build_caveats,
    horizon_accuracy,
    project,
)
from app.models.champions import ChampionSelection
from app.models.training import ModelRun, TrainingRun

logger = get_logger(__name__)

#: The baseline the champion is measured against.
BASELINE_MODEL_ID = "naive"

#: Champion selections are stored per scope kind. Branch x SKU is the level
#: stocking decisions are actually made at, so it is the level the impact
#: panel reports - an aggregate number would look far better and mean less.
SCOPE_KIND = "series"


def _folds(raw: Any) -> list[tuple[Sequence[int], Sequence[Any], Sequence[Any]]]:
    """Horizons, actuals and predictions from one model run's stored origins.

    `origins_json` is a JSON column, so SQLAlchemy hands back a parsed list -
    but the same field read through raw SQL is a string. Both are accepted
    rather than assuming one: an early version assumed a string, and
    `json.loads` on an already-parsed list raised straight into the `except`,
    which returned an empty fold set. Every series then paired to nothing and
    the panel reported no measured horizons at all - a silent zero produced by
    the error handling itself, which is the failure mode this project is least
    willing to ship (docs/DECISIONS.md D-072).
    """
    if not raw:
        return []
    if isinstance(raw, (str, bytes)):
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            return []
    else:
        parsed = raw
    if not isinstance(parsed, list):
        return []
    out = []
    for fold in parsed:
        if not isinstance(fold, dict):
            continue
        horizons = fold.get("horizons") or []
        actuals = fold.get("actuals") or []
        predictions = fold.get("predictions") or []
        if horizons and actuals and predictions:
            out.append((horizons, actuals, predictions))
    return out


def latest_training_run(db: Session) -> TrainingRun | None:
    """The run whose champions are actually in force.

    Not simply the newest completed run. Champion selection is a **separate
    step** from training, so a run can finish and never have champions chosen
    from it - and a newer run in that state says nothing about the models the
    application is currently forecasting with. Picking it would replace a real
    measurement with an empty panel while the forecasts on the next tab were
    still being produced by the older run's champions.

    So the run is resolved from the active champion selections, and only falls
    back to "newest completed" when no champion has ever been selected, where
    an empty panel is the honest answer (docs/DECISIONS.md D-072).
    """
    run_id = db.scalars(
        select(ChampionSelection.training_run_id)
        .where(
            ChampionSelection.is_active.is_(True),
            ChampionSelection.scope_kind == SCOPE_KIND,
        )
        .order_by(ChampionSelection.created_at.desc())
        .limit(1)
    ).first()
    if run_id:
        run = db.get(TrainingRun, run_id)
        if run is not None:
            return run
    return db.scalars(
        select(TrainingRun)
        .where(TrainingRun.status.in_(("completed", "completed_with_warnings")))
        .order_by(TrainingRun.created_at.desc())
        .limit(1)
    ).first()


def measure(db: Session, training_run_id: str) -> tuple[list, int, int]:
    """Per-horizon champion-versus-naive error for one training run.

    Returns the horizon rows, how many series were paired, and how many of
    those series a non-registry baseline beat outright.
    """
    selections = list(
        db.scalars(
            select(ChampionSelection).where(
                ChampionSelection.training_run_id == training_run_id,
                ChampionSelection.is_active.is_(True),
                ChampionSelection.scope_kind == SCOPE_KIND,
            )
        )
    )
    if not selections:
        return [], 0, 0

    champion_by_scope = {s.scope_key: s.champion_model_id for s in selections}
    beaten = sum(1 for s in selections if s.beaten_by_baseline)

    rows = list(
        db.execute(
            select(ModelRun.scope_key, ModelRun.model_id, ModelRun.origins_json).where(
                ModelRun.training_run_id == training_run_id,
                ModelRun.scope_key.in_(list(champion_by_scope)),
                ModelRun.origins_json.is_not(None),
            )
        )
    )

    champion_folds: list = []
    baseline_folds: list = []
    paired: set[str] = set()
    for scope_key, model_id, origins in rows:
        if champion_by_scope.get(scope_key) == model_id:
            folds = _folds(origins)
            if folds:
                champion_folds.extend(folds)
                paired.add(scope_key)
        elif model_id == BASELINE_MODEL_ID:
            baseline_folds.extend(_folds(origins))

    return horizon_accuracy(champion_folds, baseline_folds), len(paired), beaten


def build_report(
    db: Session,
    *,
    exposure: Exposure,
    history_months: int,
    assumptions: dict[str, float] | None = None,
) -> dict[str, Any]:
    """The full payload, measurement and projection kept apart."""
    resolved = {**DEFAULT_ASSUMPTIONS, **(assumptions or {})}
    run = latest_training_run(db)

    report = ImpactReport(exposure=exposure, assumptions=resolved)
    report.history_months = history_months

    if run is None:
        report.caveats = [
            "No completed training run exists, so no error reduction has been "
            "measured and nothing is projected.",
            *build_caveats(report),
        ]
        payload = report.as_dict()
        payload["training_run_id"] = None
        return payload

    horizons, series_count, beaten = measure(db, run.id)
    report.horizons = horizons
    report.series_count = series_count
    report.beaten_by_baseline = beaten
    report.projections = project(
        horizons, exposure, resolved, history_months=history_months
    )
    report.caveats = build_caveats(report)

    payload = report.as_dict()
    payload["training_run_id"] = run.id
    payload["baseline_model_id"] = BASELINE_MODEL_ID
    payload["scope_kind"] = SCOPE_KIND
    return payload

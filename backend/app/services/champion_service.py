"""Champion selection, overrides, rollback and model diagnostics.

The ranking rules live in `app.ml.selection.champion`, which knows nothing about
the database. This module is the boundary: it reads `model_run` rows, hands them
to the ranker, and persists the verdict as an append-only `champion_selection`
history.

Two things it refuses to do:

**It never derives a champion from rows it has not got.** If a scope has no
completed row, the selection is skipped with a stated reason - there is no
fallback to "the first model" and no zero-forecast stand-in.

**It never overrides without a reason.** `MIN_OVERRIDE_REASON_CHARS` is enforced
here rather than only in the schema, so a service-level caller cannot bypass it.
The override records who, when, why, and what it replaced.

And one thing it now refuses to do: **crown a model that cannot be fitted on the
history the forecast will use.** A backtest trains on a window that stops before
its validation fold; the live refit trains on everything. A model can pass the
first and fail the second - see `app/domain/ais/deployability.py` for the case
that prompted this. When it does, the crown passes down the ranking to the best
model that can run, and the refused model keeps its place on the leaderboard
with the requirement it missed.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

import pandas as pd

from app.core.errors import ConflictError, NotFoundError, ValidationFailedError
from app.core.logging import get_logger
from app.db.session import session_scope
from app.domain.ais.backtest_runner import SERIES_COL
from app.domain.ais.deployability import ScopeFit, prepare_scope_fit, refusal_reason
from app.domain.ais.scope_builder import build_aggregate_plan
from app.domain.ais.workspace import resolve_workspace
from app.ml.registry.canonical_models import (
    BASELINE_METHOD_IDS,
    CANONICAL_MODEL_IDS,
    MODEL_DISPLAY_NAMES,
)
from app.core.config import get_settings
from app.ml.selection.champion import (
    Candidate,
    Leaderboard,
    compare_to_baseline,
    rank_candidates,
)
from app.models.champions import (
    MIN_OVERRIDE_REASON_CHARS,
    SCOPE_KINDS,
    SEGMENT_SCOPE_KINDS,
    ChampionSelection,
)
from app.models.training import ModelRun, TrainingRun
from app.services.panel_service import load_panel_frame
from app.services.training.training_service import PANEL_COLUMNS

logger = get_logger(__name__)

#: Which `model_run.scope_level` each champion scope is decided from. A branch
#: champion is chosen from branch-level metrics, never from the series-level
#: rows underneath it - the two are not comparable (D-037 reasoning applied to
#: aggregation level rather than fold count).
SCOPE_KIND_TO_LEVEL: dict[str, str] = {
    "overall": "national",
    "region": "region",
    "branch": "branch",
    "value_class": "segment",
    "product_group": "segment",
    "series": "series",
}

#: The scope key used for the whole network.
NATIONAL_KEY = "NATIONAL"


# ----------------------------------------------------------------------
# Reading rows
# ----------------------------------------------------------------------


def _candidate(row: ModelRun) -> Candidate:
    return Candidate(
        model_id=row.model_id,
        display_name=row.display_name,
        status=row.status,
        is_baseline=row.is_baseline,
        evaluation_mode=row.evaluation_mode,
        wape=row.wape,
        mae=row.mae,
        rmse=row.rmse,
        mape=row.mape,
        accuracy=row.accuracy,
        smape=row.smape,
        mase=row.mase,
        bias=row.bias,
        bias_abs=row.bias_abs,
        legacy_mape=row.legacy_mape,
        legacy_valid=row.legacy_valid,
        validation_points=row.validation_points,
        distinct_test_points=max(
            row.total_test_points - row.duplicate_test_points, 0
        )
        or row.validation_points,
        origins_completed=row.origins_completed,
        origins_total=row.origins_total,
        failure_reason=row.failure_reason,
        model_run_id=row.id,
        extra={"tier": row.tier, "segment": row.segment},
    )


#: Statuses that mean a run reached its own end and evaluated everything it
#: planned to. A run outside this set may still hold usable rows, but it stopped
#: early - so it is only the authority when nothing finished.
FINISHED_STATUSES: tuple[str, ...] = ("completed", "completed_with_warnings")


def resolve_run(db: Session, run_id: str | None) -> TrainingRun:
    """The named run, or the newest **finished** run that produced model rows.

    Two rules, and the second one is the subtle one.

    A run must have rows: a run that failed before writing anything would
    otherwise make every leaderboard empty.

    A *finished* run outranks a newer cancelled or failed one. A run cancelled
    at 88% keeps every row it wrote - that is deliberate, nothing is thrown
    away - but those rows cover whichever scopes happened to come first, in the
    order the tier walked them. Letting that partial sweep silently outrank a
    completed run would change which branches the whole application appears to
    cover, without saying so anywhere (docs/DECISIONS.md D-048).

    A cancelled run is still reachable: pass its id explicitly.
    """
    if run_id:
        run = db.get(TrainingRun, run_id)
        if run is None:
            raise NotFoundError(f"No training run with id {run_id!r}.")
        return run

    def newest(*, finished_only: bool) -> TrainingRun | None:
        query = select(TrainingRun).join(
            ModelRun, ModelRun.training_run_id == TrainingRun.id
        )
        if finished_only:
            query = query.where(TrainingRun.status.in_(FINISHED_STATUSES))
        return db.scalars(
            query.group_by(TrainingRun.id)
            .order_by(TrainingRun.created_at.desc())
            .limit(1)
        ).first()

    # Fall back to any run with rows, so a workspace whose only run was
    # cancelled still has a leaderboard rather than an error.
    row = newest(finished_only=True) or newest(finished_only=False)
    if row is None:
        raise NotFoundError(
            "No training run has produced any model results yet.",
            remediation="POST /api/training to run one.",
        )
    return row


def leaderboard_scopes(
    db: Session, run_id: str, *, scope_level: str | None = None
) -> list[tuple[str, str]]:
    """Every (scope_level, scope_key) the run evaluated, in a stable order."""
    query = select(ModelRun.scope_level, ModelRun.scope_key).where(
        ModelRun.training_run_id == run_id
    )
    if scope_level:
        query = query.where(ModelRun.scope_level == scope_level)
    rows = db.execute(query.distinct().order_by(ModelRun.scope_level, ModelRun.scope_key))
    return [(level, key) for level, key in rows]


def build_leaderboard(
    db: Session,
    run_id: str,
    *,
    scope_level: str = "national",
    scope_key: str = NATIONAL_KEY,
    include_baselines: bool = True,
    deployable: Callable[[Candidate], str | None] | None = None,
) -> Leaderboard:
    """Rank one scope from its stored rows. Every row appears.

    `deployable` is passed straight through to the ranker. Reading a leaderboard
    leaves it unset - that view is a record of how the models scored, and a
    scope's panel is not loaded to render it - while `select_champions` supplies
    it, because awarding a crown is a decision about what will actually run.
    """
    conditions = [
        ModelRun.training_run_id == run_id,
        ModelRun.scope_level == scope_level,
        ModelRun.scope_key == scope_key,
    ]
    if not include_baselines:
        conditions.append(ModelRun.is_baseline.is_(False))
    rows = list(db.scalars(select(ModelRun).where(*conditions)))
    if not rows:
        raise NotFoundError(
            f"Run {run_id!r} evaluated no models at {scope_level}/{scope_key}.",
            remediation=(
                "Check GET /api/training/{run_id} for which tiers and scopes the "
                "run actually reached; a scope the run never reached has no rows "
                "rather than empty metrics."
            ),
        )
    return rank_candidates(
        [_candidate(row) for row in rows],
        primary_metric=get_settings().champion_primary_metric,
        deployable=deployable,
    )


def leaderboard_payload(
    db: Session,
    run_id: str,
    *,
    scope_level: str = "national",
    scope_key: str = NATIONAL_KEY,
    include_baselines: bool = True,
) -> dict[str, Any]:
    """A leaderboard plus the context needed to read it honestly."""
    board = build_leaderboard(
        db,
        run_id,
        scope_level=scope_level,
        scope_key=scope_key,
        include_baselines=include_baselines,
    )
    run = db.get(TrainingRun, run_id)
    champion_row = next(
        (row for row in board.rows if row.is_champion), None
    )
    active = active_champion(
        db, scope_kind=_kind_for_level(scope_level, scope_key), scope_key=scope_key
    )
    present = {row.candidate.model_id for row in board.rows}
    payload = board.as_dict()

    # Show the ranking the crown was actually awarded on.
    #
    # `board` above is re-ranked live and ungated, because rendering a table is
    # not a reason to load a panel. The selection, though, also required each
    # candidate to be fittable on the full history, and where that demoted
    # someone the two disagree - the live board crowns a model the forecast
    # does not use, and the screen contradicts itself. The selection stored the
    # board it decided on, so that is what is served whenever it belongs to the
    # run being asked about.
    if (
        active is not None
        and active.training_run_id == run_id
        and active.ranking_json
        and active.scope_key == scope_key
    ):
        payload = dict(active.ranking_json)
        champion_row = None
        present = {
            str(row.get("model_id")) for row in payload.get("rows") or []
        }
        payload["ranking_source"] = "as_selected"
        payload["ranking_note"] = (
            "This is the ranking the champion was selected on, including the "
            "check that each model can be fitted on the full history - not a "
            "fresh sort of the stored metrics."
        )
    else:
        payload["ranking_source"] = "recomputed"
        payload["ranking_note"] = (
            "No champion has been selected for this scope from this run, so "
            "this is the backtest ranking alone. A model can lead it and still "
            "be unable to fit on the full history."
        )
    payload.update(
        {
            "training_run_id": run_id,
            "panel_build_id": run.panel_build_id if run else None,
            "scope_level": scope_level,
            "scope_key": scope_key,
            "models_missing": [
                model_id for model_id in CANONICAL_MODEL_IDS if model_id not in present
            ],
            "baselines_present": sorted(present & set(BASELINE_METHOD_IDS)),
            "skill_vs_best_baseline": compare_to_baseline(
                champion_row.candidate.wape
                if champion_row
                else next(
                    (
                        row.get("wape")
                        for row in payload.get("rows") or []
                        if row.get("is_champion")
                    ),
                    None,
                ),
                payload.get("best_baseline_wape"),
            ),
            "active_selection": _selection_dict(active) if active else None,
            "origins": run.origins_json if run else None,
        }
    )
    return payload


def _kind_for_level(scope_level: str, scope_key: str = "") -> str:
    """Which champion scope kind a `model_run` scope belongs to.

    `value_class` and `product_group` both live at the `segment` level, so the
    level alone is not enough - the key's prefix decides.
    """
    if scope_level == "segment":
        prefix = scope_key.split("=", 1)[0]
        return prefix if prefix in SEGMENT_SCOPE_KINDS else "value_class"
    for kind, level in SCOPE_KIND_TO_LEVEL.items():
        if level == scope_level and kind not in SEGMENT_SCOPE_KINDS:
            return kind
    return "overall"


# ----------------------------------------------------------------------
# Automatic selection
# ----------------------------------------------------------------------



# ----------------------------------------------------------------------
# The deployability gate
# ----------------------------------------------------------------------

#: The horizons a champion is checked against. The forecast run takes its own
#: horizons from the request, but nothing records them at selection time, and
#: every run so far has asked for six months. Checking the longest ordinary
#: horizon is the conservative direction: a model that can reach month 6 can
#: reach month 1.
GATE_HORIZONS: tuple[int, ...] = (1, 2, 3, 4, 5, 6)


class _Deployability:
    """Answers, per scope, which models could not be fitted on its history.

    Built once per `select_champions` call. Scope frames are prepared on first
    use and cached, so a run that ranks forty series prepares forty frames and
    not the whole panel's worth.

    Every question goes to the adapter that would do the refit, through
    `app.domain.ais.deployability`, so this cannot drift from what the forecast
    run will find.
    """

    def __init__(
        self, panel: "pd.DataFrame", config: dict[str, Any], horizons: Sequence[int]
    ) -> None:
        self._config = config
        self._horizons = tuple(horizons)
        self._series_frames: dict[str, Any] = {}
        if SERIES_COL in panel.columns:
            self._series_frames = dict(tuple(panel.groupby(SERIES_COL, observed=True)))
        # The aggregate frames come from the one builder the forecast run uses,
        # rather than being re-summed here under a second definition.
        self._aggregate_frames = {
            (scope.scope_level, scope.scope_key): scope.frame
            for scope in build_aggregate_plan(panel).series
        }
        self._fits: dict[tuple[str, str], ScopeFit | None] = {}
        self._refusals: dict[tuple[str, str], dict[str, str]] = {}

    def _fit(self, scope_level: str, scope_key: str) -> ScopeFit | None:
        cached = self._fits.get((scope_level, scope_key), _MISSING)
        if cached is not _MISSING:
            return cached  # type: ignore[return-value]
        if scope_level == "series":
            frame = self._series_frames.get(scope_key)
        else:
            frame = self._aggregate_frames.get((scope_level, scope_key))
        fit: ScopeFit | None = None
        if frame is not None and not frame.empty:
            try:
                fit = prepare_scope_fit(
                    frame,
                    scope_level=scope_level,
                    horizons=self._horizons,
                    config=self._config,
                )
            except Exception:  # noqa: BLE001 - a scope we cannot prepare is ungated
                # Not silent: `unchecked_scopes` reports it, and an ungated
                # scope behaves exactly as it did before this gate existed.
                logger.warning(
                    "deployability_frame_failed",
                    extra={"scope_level": scope_level, "scope_key": scope_key},
                )
                fit = None
        self._fits[(scope_level, scope_key)] = fit
        return fit

    def gate(
        self, scope_level: str, scope_key: str
    ) -> Callable[[Candidate], str | None] | None:
        """The predicate for one scope, or `None` if it cannot be checked."""
        fit = self._fit(scope_level, scope_key)
        if fit is None:
            return None
        found = self._refusals.setdefault((scope_level, scope_key), {})

        def refused(candidate: Candidate) -> str | None:
            if candidate.model_id in found:
                return found[candidate.model_id]
            reason = refusal_reason(candidate.model_id, fit)
            if reason is not None:
                found[candidate.model_id] = reason
            return reason

        return refused

    def refusals_for(self, scope_level: str, scope_key: str) -> dict[str, str]:
        return dict(self._refusals.get((scope_level, scope_key), {}))


_MISSING = object()


def _build_deployability(run: TrainingRun) -> tuple[_Deployability | None, str | None]:
    """The gate for a run, or `None` with the reason it could not be built.

    A panel that cannot be read is reported and selection continues ungated,
    which is the behaviour that existed before this gate. Refusing to select
    any champion because the check is unavailable would be a worse failure than
    the one the check prevents.
    """
    try:
        panel = load_panel_frame(run.panel_build_id, PANEL_COLUMNS)
    except Exception as exc:  # noqa: BLE001
        return None, (
            "The panel behind this run could not be read, so no champion was "
            f"checked against the history it will be refitted on: {exc}"
        )
    with session_scope() as db:
        panel = resolve_workspace(db).restrict(panel, "canonical_branch")
    if panel.empty:
        return None, (
            "The workspace restriction leaves no panel rows, so no champion was "
            "checked against the history it will be refitted on."
        )
    settings = get_settings()
    config = {
        "min_history_profile": run.min_history_profile or settings.min_history_profile,
        "xgboost_training_profile": (
            run.xgboost_training_profile or settings.xgboost_training_profile
        ),
        "random_seed": settings.random_seed,
    }
    return _Deployability(panel, config, GATE_HORIZONS), None


def select_champions(
    db: Session,
    run_id: str,
    *,
    scope_kinds: Sequence[str] = (
        "overall",
        "region",
        "branch",
        "value_class",
        "product_group",
    ),
    actor: str | None = None,
    check_deployability: bool = True,
) -> dict[str, Any]:
    """Run the deterministic ranking over every requested scope and persist it.

    Scopes with no rankable row are **skipped with a reason** and reported in
    `skipped`, never given an arbitrary champion.

    With `check_deployability`, every candidate is also asked whether it can be
    fitted on the scope's whole history before it can be crowned, and the crown
    passes down the ranking to the first model that can. `demoted` reports every
    scope where that changed the answer, with the model it moved from, the model
    it moved to, and the requirement the first one failed - a champion that
    changed for a reason nobody can read is not auditable.
    """
    unknown = [kind for kind in scope_kinds if kind not in SCOPE_KINDS]
    if unknown:
        raise ValidationFailedError(
            f"Unknown champion scope kind(s) {unknown}.",
            details={"valid": list(SCOPE_KINDS)},
        )
    run = resolve_run(db, run_id)

    written: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    demoted: list[dict[str, Any]] = []
    unchecked: list[dict[str, Any]] = []

    gate: _Deployability | None = None
    gate_note: str | None = None
    if check_deployability:
        gate, gate_note = _build_deployability(run)

    for kind in scope_kinds:
        level = SCOPE_KIND_TO_LEVEL[kind]
        for scope_level, scope_key in leaderboard_scopes(db, run.id, scope_level=level):
            # `value_class` and `product_group` share the `segment` level, so
            # the key's own prefix is what separates them. Without this, one
            # kind would claim the other's scopes.
            if kind in SEGMENT_SCOPE_KINDS and not scope_key.startswith(f"{kind}="):
                continue
            predicate = gate.gate(scope_level, scope_key) if gate else None
            if gate is not None and predicate is None:
                unchecked.append(
                    {
                        "scope_kind": kind,
                        "scope_key": scope_key,
                        "reason": (
                            "This scope has no preparable frame in the panel, so "
                            "its champion was ranked on its backtest alone and "
                            "may not be fittable on the full history."
                        ),
                    }
                )
            board = build_leaderboard(
                db,
                run.id,
                scope_level=scope_level,
                scope_key=scope_key,
                deployable=predicate,
            )
            refused = gate.refusals_for(scope_level, scope_key) if gate else {}
            if refused and board.champion_model_id is not None:
                # Ranked above the crowned model and refused: the demotion.
                for row in board.rows:
                    if row.candidate.model_id not in refused:
                        continue
                    demoted.append(
                        {
                            "scope_kind": kind,
                            "scope_key": scope_key,
                            "refused_model_id": row.candidate.model_id,
                            "refused_wape": row.candidate.wape,
                            "champion_model_id": board.champion_model_id,
                            "reason": refused[row.candidate.model_id],
                        }
                    )
            if board.champion_model_id is None:
                skipped.append(
                    {
                        "scope_kind": kind,
                        "scope_key": scope_key,
                        "reason": (
                            "No registered model produced a rankable metric in "
                            "this scope. Every model's status and reason are on "
                            "the leaderboard; no champion was invented."
                        ),
                        "excluded_count": board.excluded_count,
                    }
                )
                continue
            selection = _persist(
                db,
                run_id=run.id,
                scope_kind=kind,
                scope_key=scope_key,
                evaluated_scope_level=scope_level,
                board=board,
                selection_source="automatic",
                reason=None,
                actor=actor,
            )
            written.append(_selection_dict(selection))

    db.commit()
    logger.info(
        "champions_selected",
        extra={
            "run_id": run.id,
            "written": len(written),
            "skipped": len(skipped),
            "demoted": len(demoted),
        },
    )
    return {
        "training_run_id": run.id,
        "selected": written,
        "skipped": skipped,
        "selected_count": len(written),
        "skipped_count": len(skipped),
        "deployability_checked": gate is not None,
        "deployability_note": gate_note,
        "demoted": demoted,
        "demoted_count": len(demoted),
        "unchecked_scopes": unchecked,
    }


def _champion_candidate(board: Leaderboard) -> Candidate:
    row = next(row for row in board.rows if row.is_champion)
    return row.candidate


def _persist(
    db: Session,
    *,
    run_id: str,
    scope_kind: str,
    scope_key: str,
    evaluated_scope_level: str | None,
    board: Leaderboard | None,
    selection_source: str,
    reason: str | None,
    actor: str | None,
    champion: Candidate | None = None,
    restored_from_id: str | None = None,
) -> ChampionSelection:
    """Write a new selection row and supersede the active one for that scope."""
    winner = champion if champion is not None else _champion_candidate(board)  # type: ignore[arg-type]
    previous = active_champion(db, scope_kind=scope_kind, scope_key=scope_key)
    now = datetime.now(timezone.utc)
    if previous is not None:
        previous.is_active = False
        previous.superseded_at = now

    selection = ChampionSelection(
        training_run_id=run_id,
        scope_kind=scope_kind,
        scope_key=scope_key,
        evaluated_scope_level=evaluated_scope_level,
        champion_model_id=winner.model_id,
        champion_display_name=(
            winner.display_name or MODEL_DISPLAY_NAMES.get(winner.model_id, winner.model_id)
        ),
        challenger_model_id=board.challenger_model_id if board else None,
        legacy_champion_model_id=board.legacy_champion_model_id if board else None,
        champion_model_run_id=winner.model_run_id,
        champion_wape=winner.wape,
        champion_mae=winner.mae,
        champion_bias=winner.bias,
        champion_validation_points=winner.validation_points,
        champion_evaluation_mode=winner.evaluation_mode,
        best_baseline_model_id=board.best_baseline_model_id if board else None,
        best_baseline_wape=board.best_baseline_wape if board else None,
        beaten_by_baseline=bool(board.beaten_by_baseline) if board else False,
        selection_source=selection_source,
        reason=reason,
        actor=actor,
        is_active=True,
        supersedes_id=previous.id if previous else None,
        restored_from_id=restored_from_id,
        ranked_count=board.ranked_count if board else 0,
        excluded_count=board.excluded_count if board else 0,
        ranking_json=board.as_dict() if board else None,
        notes_json=list(board.notes) if board else None,
    )
    db.add(selection)
    db.flush()
    return selection


# ----------------------------------------------------------------------
# Reading selections
# ----------------------------------------------------------------------


def active_champion(
    db: Session, *, scope_kind: str, scope_key: str
) -> ChampionSelection | None:
    return db.scalars(
        select(ChampionSelection)
        .where(
            ChampionSelection.scope_kind == scope_kind,
            ChampionSelection.scope_key == scope_key,
            ChampionSelection.is_active.is_(True),
        )
        .limit(1)
    ).first()


def require_active_champion(
    db: Session, *, scope_kind: str, scope_key: str
) -> ChampionSelection:
    selection = active_champion(db, scope_kind=scope_kind, scope_key=scope_key)
    if selection is None:
        raise NotFoundError(
            f"No champion is selected for {scope_kind}/{scope_key}.",
            remediation="POST /api/models/champions/select after a training run.",
        )
    return selection


def list_champions(
    db: Session,
    *,
    scope_kind: str | None = None,
    training_run_id: str | None = None,
    active_only: bool = True,
    offset: int = 0,
    limit: int = 100,
) -> tuple[list[ChampionSelection], int]:
    conditions = []
    if scope_kind:
        conditions.append(ChampionSelection.scope_kind == scope_kind)
    if training_run_id:
        conditions.append(ChampionSelection.training_run_id == training_run_id)
    if active_only:
        conditions.append(ChampionSelection.is_active.is_(True))
    total = (
        db.scalar(
            select(func.count()).select_from(ChampionSelection).where(*conditions)
        )
        or 0
    )
    rows = list(
        db.scalars(
            select(ChampionSelection)
            .where(*conditions)
            .order_by(
                ChampionSelection.scope_kind,
                ChampionSelection.scope_key,
                ChampionSelection.created_at.desc(),
            )
            .offset(offset)
            .limit(limit)
        )
    )
    return rows, int(total)


def champion_history(
    db: Session, *, scope_kind: str, scope_key: str
) -> list[ChampionSelection]:
    """Every decision ever made for one scope, newest first.

    The audit trail is the table, so this is a plain query rather than a
    reconstruction from a separate log.
    """
    return list(
        db.scalars(
            select(ChampionSelection)
            .where(
                ChampionSelection.scope_kind == scope_kind,
                ChampionSelection.scope_key == scope_key,
            )
            .order_by(ChampionSelection.created_at.desc())
        )
    )


def _selection_dict(selection: ChampionSelection) -> dict[str, Any]:
    return {
        "id": selection.id,
        "training_run_id": selection.training_run_id,
        "scope_kind": selection.scope_kind,
        "scope_key": selection.scope_key,
        "evaluated_scope_level": selection.evaluated_scope_level,
        "champion_model_id": selection.champion_model_id,
        "champion_display_name": selection.champion_display_name,
        "challenger_model_id": selection.challenger_model_id,
        "legacy_champion_model_id": selection.legacy_champion_model_id,
        "champion_wape": selection.champion_wape,
        "champion_mae": selection.champion_mae,
        "champion_bias": selection.champion_bias,
        "champion_validation_points": selection.champion_validation_points,
        "champion_evaluation_mode": selection.champion_evaluation_mode,
        "best_baseline_model_id": selection.best_baseline_model_id,
        "best_baseline_wape": selection.best_baseline_wape,
        "beaten_by_baseline": selection.beaten_by_baseline,
        "selection_source": selection.selection_source,
        "reason": selection.reason,
        "actor": selection.actor,
        "is_active": selection.is_active,
        "superseded_at": selection.superseded_at,
        "supersedes_id": selection.supersedes_id,
        "restored_from_id": selection.restored_from_id,
        "ranked_count": selection.ranked_count,
        "excluded_count": selection.excluded_count,
        "notes": selection.notes_json,
        "created_at": selection.created_at,
    }


# ----------------------------------------------------------------------
# Override and rollback
# ----------------------------------------------------------------------


def override_champion(
    db: Session,
    *,
    scope_kind: str,
    scope_key: str,
    model_id: str,
    reason: str,
    actor: str | None = None,
    training_run_id: str | None = None,
) -> ChampionSelection:
    """Replace a scope's champion with a named registered model.

    Refused when: the model is not one of the 13; the model is a baseline; the
    model has no row in the run (so the override would assert an accuracy that
    was never measured); or the reason is too short to be one.
    """
    if scope_kind not in SCOPE_KINDS:
        raise ValidationFailedError(
            f"Unknown champion scope kind {scope_kind!r}.",
            details={"valid": list(SCOPE_KINDS)},
        )
    cleaned = (reason or "").strip()
    if len(cleaned) < MIN_OVERRIDE_REASON_CHARS:
        raise ValidationFailedError(
            f"An override reason of at least {MIN_OVERRIDE_REASON_CHARS} "
            "characters is required.",
            details={"reason_length": len(cleaned)},
        )
    if model_id in BASELINE_METHOD_IDS:
        raise ConflictError(
            f"{model_id!r} is a non-registry baseline and can never be champion.",
            remediation=f"Choose one of the 13 registered models: {list(CANONICAL_MODEL_IDS)}.",
        )
    if model_id not in CANONICAL_MODEL_IDS:
        raise ValidationFailedError(
            f"{model_id!r} is not one of the 13 registered models.",
            details={"valid": list(CANONICAL_MODEL_IDS)},
        )

    existing = active_champion(db, scope_kind=scope_kind, scope_key=scope_key)
    run_id = training_run_id or (existing.training_run_id if existing else None)
    if run_id is None:
        run_id = resolve_run(db, None).id
    level = (
        existing.evaluated_scope_level
        if existing and existing.evaluated_scope_level
        else SCOPE_KIND_TO_LEVEL[scope_kind]
    )

    board = build_leaderboard(
        db, run_id, scope_level=level, scope_key=scope_key
    )
    row = next(
        (r for r in board.rows if r.candidate.model_id == model_id), None
    )
    if row is None:
        raise ConflictError(
            f"{model_id!r} was not evaluated at {scope_kind}/{scope_key} in run "
            f"{run_id!r}, so overriding to it would claim an accuracy that was "
            "never measured.",
            remediation=(
                "Run training over this scope first, or override to a model the "
                "run did evaluate."
            ),
        )
    if row.candidate.status != "completed":
        raise ConflictError(
            f"{model_id!r} is {row.candidate.status!r} in this scope "
            f"({row.candidate.failure_reason or 'no reason recorded'}), so it "
            "cannot serve forecasts.",
            remediation="Override to a model that completed.",
        )

    selection = _persist(
        db,
        run_id=run_id,
        scope_kind=scope_kind,
        scope_key=scope_key,
        evaluated_scope_level=level,
        board=board,
        selection_source="manual_override",
        reason=cleaned,
        actor=actor,
        champion=row.candidate,
    )
    db.commit()
    db.refresh(selection)
    logger.info(
        "champion_overridden",
        extra={
            "scope_kind": scope_kind,
            "scope_key": scope_key,
            "model_id": model_id,
            "actor": actor,
        },
    )
    return selection


def rollback_champion(
    db: Session,
    *,
    scope_kind: str,
    scope_key: str,
    reason: str | None = None,
    actor: str | None = None,
) -> ChampionSelection:
    """Restore the previous decision for a scope by writing a new row.

    The superseded row is never resurrected in place: rolling back is itself a
    decision, and the history must show that it happened.
    """
    history = champion_history(db, scope_kind=scope_kind, scope_key=scope_key)
    if not history:
        raise NotFoundError(
            f"No champion history exists for {scope_kind}/{scope_key}."
        )
    if len(history) < 2:
        raise ConflictError(
            "There is only one selection for this scope, so there is nothing to "
            "roll back to.",
            remediation="Override to a specific model instead.",
        )
    current, previous = history[0], history[1]
    cleaned = (reason or "").strip() or (
        f"Rolled back to the selection of {previous.created_at:%Y-%m-%d %H:%M} "
        f"({previous.champion_model_id}), replacing {current.champion_model_id}."
    )

    selection = _persist(
        db,
        run_id=previous.training_run_id,
        scope_kind=scope_kind,
        scope_key=scope_key,
        evaluated_scope_level=previous.evaluated_scope_level,
        board=None,
        selection_source="rollback",
        reason=cleaned,
        actor=actor,
        champion=Candidate(
            model_id=previous.champion_model_id,
            display_name=previous.champion_display_name,
            status="completed",
            evaluation_mode=previous.champion_evaluation_mode,
            wape=previous.champion_wape,
            mae=previous.champion_mae,
            bias=previous.champion_bias,
            validation_points=previous.champion_validation_points,
            model_run_id=previous.champion_model_run_id,
        ),
        restored_from_id=previous.id,
    )
    # The restored row's own ranking snapshot travels with the rollback, so the
    # evidence behind the restored choice is not lost.
    selection.ranking_json = previous.ranking_json
    selection.challenger_model_id = previous.challenger_model_id
    selection.legacy_champion_model_id = previous.legacy_champion_model_id
    selection.best_baseline_model_id = previous.best_baseline_model_id
    selection.best_baseline_wape = previous.best_baseline_wape
    selection.beaten_by_baseline = previous.beaten_by_baseline
    selection.ranked_count = previous.ranked_count
    selection.excluded_count = previous.excluded_count
    db.commit()
    db.refresh(selection)
    logger.info(
        "champion_rolled_back",
        extra={
            "scope_kind": scope_kind,
            "scope_key": scope_key,
            "restored": previous.champion_model_id,
            "actor": actor,
        },
    )
    return selection


# ----------------------------------------------------------------------
# Diagnostics
# ----------------------------------------------------------------------


def model_diagnostics(
    db: Session,
    *,
    run_id: str,
    model_id: str,
    scope_level: str = "national",
    scope_key: str = NATIONAL_KEY,
) -> dict[str, Any]:
    """Folds, residuals, actual-versus-predicted and horizon performance.

    Served from what the run persisted. A model that did not run returns its
    status and reason with empty series - never a fabricated curve.
    """
    row = db.scalars(
        select(ModelRun).where(
            ModelRun.training_run_id == run_id,
            ModelRun.model_id == model_id,
            ModelRun.scope_level == scope_level,
            ModelRun.scope_key == scope_key,
        )
    ).first()
    if row is None:
        raise NotFoundError(
            f"Run {run_id!r} has no row for {model_id!r} at "
            f"{scope_level}/{scope_key}."
        )

    origins = row.origins_json or []
    folds: list[dict[str, Any]] = []
    points: list[dict[str, Any]] = []
    for origin in origins:
        periods = origin.get("periods") or []
        horizons = origin.get("horizons") or []
        actuals = origin.get("actuals") or []
        predictions = origin.get("predictions") or []
        folds.append(
            {
                "origin_name": origin.get("origin_name"),
                "fold_index": origin.get("fold_index"),
                "train_end_period": origin.get("train_end_period"),
                "train_rows": origin.get("train_rows"),
                "status": origin.get("status"),
                "seasonal_period": origin.get("seasonal_period"),
                "failure_reason": origin.get("failure_reason"),
                "eligibility": origin.get("eligibility"),
                "fit_seconds": origin.get("fit_seconds"),
                "predict_seconds": origin.get("predict_seconds"),
                "validation_periods": periods,
                "metrics": origin.get("metrics"),
                "legacy_metrics": origin.get("legacy_metrics"),
                "negative_predictions": origin.get("negative_predictions"),
                "point_count": min(len(actuals), len(predictions)),
            }
        )
        for index in range(min(len(actuals), len(predictions))):
            actual = actuals[index]
            predicted = predictions[index]
            points.append(
                {
                    "origin_name": origin.get("origin_name"),
                    "fold_index": origin.get("fold_index"),
                    "period": periods[index] if index < len(periods) else None,
                    "horizon": horizons[index] if index < len(horizons) else None,
                    "actual": actual,
                    "predicted": predicted,
                    "residual": predicted - actual,
                }
            )

    horizon_rows = _horizon_performance(points)
    available = bool(points)

    return {
        "training_run_id": run_id,
        "model_id": row.model_id,
        "display_name": row.display_name,
        "is_baseline": row.is_baseline,
        "scope_level": scope_level,
        "scope_key": scope_key,
        "status": row.status,
        "evaluation_mode": row.evaluation_mode,
        "failure_reason": row.failure_reason,
        "eligibility": row.eligibility_json,
        "metrics": {
            "mae": row.mae,
            "rmse": row.rmse,
            "wape": row.wape,
            "mape": row.mape,
            "accuracy": row.accuracy,
            "smape": row.smape,
            "mase": row.mase,
            "bias": row.bias,
            "bias_abs": row.bias_abs,
            "naive_mae": row.naive_mae,
            "legacy_mape": row.legacy_mape,
            "legacy_valid": row.legacy_valid,
            "validation_points": row.validation_points,
            "total_test_points": row.total_test_points,
            "duplicate_test_points": row.duplicate_test_points,
        },
        "parameters": row.parameters_json,
        "features": row.features_json,
        "fit_seconds": row.fit_seconds,
        "predict_seconds": row.predict_seconds,
        "folds": folds,
        "points": points,
        "horizon_performance": horizon_rows,
        "diagnostics_available": available,
        "unavailable_reason": _unavailable_reason(row) if not available else None,
    }


def _unavailable_reason(row: ModelRun) -> str:
    """Why there is nothing to chart - and the two cases are different.

    A model that did not complete has no predictions because it never made any.
    A model that *did* complete but stored none was evaluated by a run that
    predated per-origin prediction persistence; saying "it produced no
    predictions" there would blame the model for a gap in the record.
    """
    if row.status != "completed":
        return (
            f"{row.model_id} is {row.status!r} in this scope, so it produced no "
            "predictions to chart. "
            + (row.failure_reason or "No further detail was recorded.")
        )
    return (
        f"{row.model_id} completed, but this training run did not persist "
        "per-origin actuals and predictions, so the charts cannot be drawn from "
        "it. Its metrics are shown and are unaffected. Re-run training to "
        "populate the diagnostics."
    )


def _horizon_performance(points: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """MAE, WAPE and bias per forecast horizon.

    WAPE is `None` where the horizon's actuals sum to zero, for the same reason
    it is `None` anywhere else: there is no denominator, and 0 or 100 would both
    misdescribe the window.

    Scaled by 100, matching `metrics.evaluate`. Returning a fraction here while
    the row above it carries a percentage would put 4.58 and 0.0458 in the same
    payload under the same name.
    """
    grouped: dict[Any, list[dict[str, Any]]] = {}
    for point in points:
        grouped.setdefault(point.get("horizon"), []).append(point)

    rows: list[dict[str, Any]] = []
    for horizon in sorted(grouped, key=lambda value: (value is None, value)):
        bucket = grouped[horizon]
        errors = [abs(item["residual"]) for item in bucket]
        actual_sum = sum(abs(item["actual"]) for item in bucket)
        rows.append(
            {
                "horizon": horizon,
                "points": len(bucket),
                "mae": sum(errors) / len(bucket) if bucket else None,
                "wape": (sum(errors) / actual_sum * 100.0) if actual_sum else None,
                "bias": sum(item["residual"] for item in bucket) / len(bucket)
                if bucket
                else None,
                "zero_actual_points": sum(1 for item in bucket if item["actual"] == 0),
            }
        )
    return rows


def leaderboard_comparison(
    db: Session,
    run_id: str,
    *,
    scope_level: str = "national",
    scope_key: str = NATIONAL_KEY,
) -> list[dict[str, Any]]:
    """Model id and WAPE, for the models-on-x, WAPE-on-y comparison chart.

    Unranked models are included with a `null` WAPE and their reason, so the
    chart has a visible gap where a model did not run rather than silently
    fewer bars.
    """
    board = build_leaderboard(db, run_id, scope_level=scope_level, scope_key=scope_key)
    return [
        {
            "model_id": row.candidate.model_id,
            "display_name": row.candidate.display_name,
            # Already a percentage: `metrics.evaluate` scales WAPE by 100 at
            # source (`metrics.py`), so multiplying again here would report a
            # 4.58% national error as 458%.
            "wape": row.candidate.wape,
            "wape_pct": row.candidate.wape,
            "status": row.candidate.status,
            "is_baseline": row.candidate.is_baseline,
            "is_champion": row.is_champion,
            "exclusion": row.exclusion,
            "exclusion_reason": row.exclusion_reason,
        }
        for row in board.rows
    ]

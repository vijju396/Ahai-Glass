"""The model registry contract, the leaderboard, diagnostics and champions.

`GET /api/models` is the frontend's only source of model identity - it never
carries a second registry, and a frontend test scans for one.

The leaderboard endpoints hold to two rules the rest of the project is built
around:

- **Every model appears**, whatever happened to it, and `models_missing` is
  returned so an accidental omission is visible rather than silent.
- **Both rankings are returned side by side** - the AIS operational ranking and
  the legacy lowest-valid-MAPE parity result - and never blended
  (`docs/DECISIONS.md` D-011).

Champion overrides are audited: the reason is required at the schema *and* the
service boundary, and rollback writes a new row rather than deleting one.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.champions import (
    ChampionHistoryResponse,
    ChampionSelectionOut,
    ComparisonPoint,
    DiagnosticsResponse,
    LeaderboardResponse,
    OverrideRequest,
    RollbackRequest,
    ScopeRef,
    SelectChampionsRequest,
    SelectChampionsResponse,
)
from app.schemas.common import Page
from app.schemas.models import ModelRegistryResponse
from app.services import champion_service
from app.services.model_contract_service import build_model_contract

router = APIRouter(prefix="/models", tags=["models"])


@router.get(
    "",
    response_model=ModelRegistryResponse,
    summary="The official 13 models, plus non-registry baselines",
)
def list_models() -> ModelRegistryResponse:
    return build_model_contract()


@router.get(
    "/leaderboard",
    response_model=LeaderboardResponse,
    summary="Ranked leaderboard for one scope; no model is ever omitted",
)
def leaderboard(
    training_run_id: str | None = Query(
        None, description="Defaults to the newest run that produced results."
    ),
    scope_level: str = Query("national", description="national | region | branch | segment | series"),
    scope_key: str = Query("NATIONAL"),
    include_baselines: bool = Query(True),
    db: Session = Depends(get_db),
) -> LeaderboardResponse:
    run = champion_service.resolve_run(db, training_run_id)
    payload = champion_service.leaderboard_payload(
        db,
        run.id,
        scope_level=scope_level,
        scope_key=scope_key,
        include_baselines=include_baselines,
    )
    return LeaderboardResponse.model_validate(payload)


@router.get(
    "/leaderboard/scopes",
    response_model=Page[ScopeRef],
    summary="Which scopes a run has a leaderboard for",
)
def leaderboard_scopes(
    training_run_id: str | None = Query(None),
    scope_level: str | None = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=2000),
    db: Session = Depends(get_db),
) -> Page[ScopeRef]:
    run = champion_service.resolve_run(db, training_run_id)
    scopes = champion_service.leaderboard_scopes(db, run.id, scope_level=scope_level)
    window = scopes[offset : offset + limit]
    return Page[ScopeRef](
        items=[ScopeRef(scope_level=level, scope_key=key) for level, key in window],
        total=len(scopes),
        offset=offset,
        limit=limit,
    )


@router.get(
    "/leaderboard/comparison",
    response_model=list[ComparisonPoint],
    summary="Models on x, WAPE on y - including the models that did not run",
)
def leaderboard_comparison(
    training_run_id: str | None = Query(None),
    scope_level: str = Query("national"),
    scope_key: str = Query("NATIONAL"),
    db: Session = Depends(get_db),
) -> list[ComparisonPoint]:
    run = champion_service.resolve_run(db, training_run_id)
    return [
        ComparisonPoint.model_validate(point)
        for point in champion_service.leaderboard_comparison(
            db, run.id, scope_level=scope_level, scope_key=scope_key
        )
    ]


@router.get(
    "/champions",
    response_model=Page[ChampionSelectionOut],
    summary="Active champion selections, or the whole history",
)
def list_champions(
    scope_kind: str | None = Query(None),
    training_run_id: str | None = Query(None),
    active_only: bool = Query(True),
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> Page[ChampionSelectionOut]:
    rows, total = champion_service.list_champions(
        db,
        scope_kind=scope_kind,
        training_run_id=training_run_id,
        active_only=active_only,
        offset=offset,
        limit=limit,
    )
    return Page[ChampionSelectionOut](
        items=[ChampionSelectionOut.model_validate(row) for row in rows],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post(
    "/champions/select",
    response_model=SelectChampionsResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Run the deterministic selection over a run's scopes",
)
def select_champions(
    payload: SelectChampionsRequest, db: Session = Depends(get_db)
) -> SelectChampionsResponse:
    run = champion_service.resolve_run(db, payload.training_run_id)
    result = champion_service.select_champions(
        db, run.id, scope_kinds=payload.scope_kinds, actor=payload.actor
    )
    return SelectChampionsResponse.model_validate(result)


@router.get(
    "/champions/current",
    response_model=ChampionSelectionOut,
    summary="The active champion for one scope",
)
def current_champion(
    scope_kind: str = Query("overall"),
    scope_key: str = Query("NATIONAL"),
    db: Session = Depends(get_db),
) -> ChampionSelectionOut:
    return ChampionSelectionOut.model_validate(
        champion_service.require_active_champion(
            db, scope_kind=scope_kind, scope_key=scope_key
        )
    )


@router.get(
    "/champions/history",
    response_model=ChampionHistoryResponse,
    summary="Every champion decision ever made for one scope, newest first",
)
def champion_history(
    scope_kind: str = Query("overall"),
    scope_key: str = Query("NATIONAL"),
    db: Session = Depends(get_db),
) -> ChampionHistoryResponse:
    entries = champion_service.champion_history(
        db, scope_kind=scope_kind, scope_key=scope_key
    )
    return ChampionHistoryResponse(
        scope_kind=scope_kind,
        scope_key=scope_key,
        entries=[ChampionSelectionOut.model_validate(row) for row in entries],
        total=len(entries),
    )


@router.post(
    "/champion/override",
    response_model=ChampionSelectionOut,
    status_code=status.HTTP_201_CREATED,
    summary="Replace a scope's champion; a reason is required and audited",
)
def override_champion(
    payload: OverrideRequest, db: Session = Depends(get_db)
) -> ChampionSelectionOut:
    return ChampionSelectionOut.model_validate(
        champion_service.override_champion(
            db,
            scope_kind=payload.scope_kind,
            scope_key=payload.scope_key,
            model_id=payload.model_id,
            reason=payload.reason,
            actor=payload.actor,
            training_run_id=payload.training_run_id,
        )
    )


@router.post(
    "/champion/rollback",
    response_model=ChampionSelectionOut,
    status_code=status.HTTP_201_CREATED,
    summary="Restore the previous champion by writing a new selection",
)
def rollback_champion(
    payload: RollbackRequest, db: Session = Depends(get_db)
) -> ChampionSelectionOut:
    return ChampionSelectionOut.model_validate(
        champion_service.rollback_champion(
            db,
            scope_kind=payload.scope_kind,
            scope_key=payload.scope_key,
            reason=payload.reason,
            actor=payload.actor,
        )
    )


@router.get(
    "/{model_id}/diagnostics",
    response_model=DiagnosticsResponse,
    summary="Folds, residuals, actual-versus-predicted and horizon performance",
)
def diagnostics(
    model_id: str,
    training_run_id: str | None = Query(None),
    scope_level: str = Query("national"),
    scope_key: str = Query("NATIONAL"),
    db: Session = Depends(get_db),
) -> DiagnosticsResponse:
    run = champion_service.resolve_run(db, training_run_id)
    return DiagnosticsResponse.model_validate(
        champion_service.model_diagnostics(
            db,
            run_id=run.id,
            model_id=model_id,
            scope_level=scope_level,
            scope_key=scope_key,
        )
    )

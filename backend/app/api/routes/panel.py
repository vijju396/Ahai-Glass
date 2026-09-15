"""The monthly panel and its feature manifest."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.errors import ValidationFailedError
from app.db.session import get_db
from app.schemas.common import Page
from app.schemas.panel import PanelBuildOut, PanelBuildRequest
from app.services import panel_service

router = APIRouter(prefix="/panel", tags=["panel"])


@router.post(
    "/builds",
    response_model=PanelBuildOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Build the monthly panel and the direct multi-horizon frames",
)
def create_build(payload: PanelBuildRequest, db: Session = Depends(get_db)) -> PanelBuildOut:
    run_id = payload.preprocessing_run_id
    if run_id is None:
        run_id = panel_service.latest_completed_preprocessing_run(db).id

    horizons = tuple(sorted({h for h in payload.horizons if h >= 1}))
    if not horizons:
        raise ValidationFailedError(
            "At least one horizon of 1 or more is required.",
            details={"horizons": payload.horizons},
        )

    build = panel_service.start_build(
        db, run_id, training_cut_period=payload.training_cut_period, horizons=horizons
    )
    return PanelBuildOut.model_validate(build)


@router.get("/builds", response_model=Page[PanelBuildOut], summary="List panel builds")
def list_builds(
    offset: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=200),
    db: Session = Depends(get_db),
) -> Page[PanelBuildOut]:
    rows, total = panel_service.list_builds(db, offset=offset, limit=limit)
    return Page[PanelBuildOut](
        items=[PanelBuildOut.model_validate(row) for row in rows],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get(
    "/builds/current",
    response_model=PanelBuildOut,
    summary="The most recent panel build",
)
def get_current(db: Session = Depends(get_db)) -> PanelBuildOut:
    return PanelBuildOut.model_validate(panel_service.latest_build(db))


@router.get(
    "/builds/{build_id}",
    response_model=PanelBuildOut,
    summary="Panel build detail, including the feature manifest",
)
def get_build(build_id: str, db: Session = Depends(get_db)) -> PanelBuildOut:
    return PanelBuildOut.model_validate(panel_service.get_build(db, build_id))

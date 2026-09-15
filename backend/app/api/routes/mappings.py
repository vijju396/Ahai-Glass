"""Role mapping: draft, edit, validate, confirm, preprocess.

The reconciliation view at `GET /api/datasets/{id}/mapping` answers "how do the
keys line up". This resource answers "what does each column mean", which is a
separate, versioned, confirmable artefact.
"""

from __future__ import annotations

from collections import Counter

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.domain.ais.mapping_template import (
    FUTURE_KNOWN_COLUMNS,
    NOT_FUTURE_KNOWN_REASONS,
)
from app.ml.features.roles import SemanticRole
from app.models.mappings import MappingVersion
from app.schemas.common import Page
from app.schemas.mappings import (
    MappingConfirmRequest,
    MappingCreateRequest,
    MappingDetail,
    MappingSummary,
    MappingUpdateRequest,
    PreprocessingRunOut,
    SuggestionsResponse,
)
from app.services import mapping_service

router = APIRouter(tags=["mappings"])

SUGGESTION_NOTE = (
    "Suggestions are advisory only and are never persisted as authoritative. "
    "Every one must survive human review: a mapping cannot be confirmed while "
    "its target or time column is still only a suggestion."
)


def _detail(mapping: MappingVersion) -> MappingDetail:
    counts = Counter(assignment.role for assignment in mapping.assignments)
    blocking = sum(1 for r in mapping.rule_results if r.severity == "blocking")
    warnings = sum(1 for r in mapping.rule_results if r.severity == "warning")
    unreviewed = sum(
        1
        for a in mapping.assignments
        if a.is_suggested
        and SemanticRole(a.role) in {SemanticRole.TARGET_COLUMN, SemanticRole.TIME_COLUMN}
    )
    detail = MappingDetail.model_validate(mapping)
    detail.role_counts = dict(sorted(counts.items()))
    detail.unreviewed_count = unreviewed
    detail.blocking_count = blocking
    detail.warning_count = warnings
    # An empty rule_results list is the GOOD case - it means validation ran and
    # found nothing. Every route that returns a MappingDetail validates first,
    # so the absence of violations is meaningful rather than unknown.
    detail.can_confirm = (
        not mapping.is_confirmed
        and mapping.state != "superseded"
        and blocking == 0
        and unreviewed == 0
    )
    detail.future_known_columns = sorted(FUTURE_KNOWN_COLUMNS)
    detail.not_future_known_reasons = dict(NOT_FUTURE_KNOWN_REASONS)
    return detail


# --------------------------------------------------------------------------
# Suggestions (advisory)
# --------------------------------------------------------------------------

@router.get(
    "/datasets/{dataset_id}/mapping/suggestions",
    response_model=SuggestionsResponse,
    summary="Advisory role suggestions, computed fresh and never persisted",
)
def get_suggestions(dataset_id: str, db: Session = Depends(get_db)) -> SuggestionsResponse:
    suggestions = mapping_service.suggestions_for_dataset(db, dataset_id)
    return SuggestionsResponse(
        suggestions=suggestions, total=len(suggestions), note=SUGGESTION_NOTE
    )


# --------------------------------------------------------------------------
# Mapping versions
# --------------------------------------------------------------------------

@router.post(
    "/datasets/{dataset_id}/mapping/versions",
    response_model=MappingDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Create a draft role mapping seeded from the AIS template",
)
def create_mapping(
    dataset_id: str, payload: MappingCreateRequest, db: Session = Depends(get_db)
) -> MappingDetail:
    mapping = mapping_service.create_mapping(db, dataset_id, notes=payload.notes)
    mapping, _ = mapping_service.validate(db, mapping.id)
    return _detail(mapping)


@router.get(
    "/datasets/{dataset_id}/mapping/current",
    response_model=MappingDetail,
    summary="The latest role mapping for a dataset",
)
def get_current_mapping(dataset_id: str, db: Session = Depends(get_db)) -> MappingDetail:
    return _detail(mapping_service.latest_mapping_for_dataset(db, dataset_id))


@router.get("/mappings", response_model=Page[MappingSummary], summary="List role mappings")
def list_mappings(
    dataset_version_id: str | None = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=200),
    db: Session = Depends(get_db),
) -> Page[MappingSummary]:
    rows, total = mapping_service.list_mappings(
        db, dataset_version_id=dataset_version_id, offset=offset, limit=limit
    )
    return Page[MappingSummary](
        items=[MappingSummary.model_validate(row) for row in rows],
        total=total, offset=offset, limit=limit,
    )


@router.get("/mappings/{mapping_id}", response_model=MappingDetail, summary="Mapping detail")
def get_mapping(mapping_id: str, db: Session = Depends(get_db)) -> MappingDetail:
    return _detail(mapping_service.get_mapping(db, mapping_id))


@router.patch(
    "/mappings/{mapping_id}",
    response_model=MappingDetail,
    summary="Edit a draft mapping (refused once confirmed)",
)
def update_mapping(
    mapping_id: str, payload: MappingUpdateRequest, db: Session = Depends(get_db)
) -> MappingDetail:
    if payload.config is not None:
        mapping_service.update_config(
            db, mapping_id, payload.config.model_dump(exclude_none=True)
        )
    if payload.assignments:
        mapping_service.update_assignments(
            db, mapping_id, [a.model_dump() for a in payload.assignments]
        )
    mapping, _ = mapping_service.validate(db, mapping_id)
    return _detail(mapping)


@router.post(
    "/mappings/{mapping_id}/validate",
    response_model=MappingDetail,
    summary="Run every mapping rule and persist the outcomes",
)
def validate_mapping(mapping_id: str, db: Session = Depends(get_db)) -> MappingDetail:
    mapping, _ = mapping_service.validate(db, mapping_id)
    return _detail(mapping)


@router.post(
    "/mappings/{mapping_id}/confirm",
    response_model=MappingDetail,
    summary="Lock the mapping for training use; immutable afterwards",
)
def confirm_mapping(
    mapping_id: str, payload: MappingConfirmRequest, db: Session = Depends(get_db)
) -> MappingDetail:
    return _detail(
        mapping_service.confirm(db, mapping_id, confirmed_by=payload.confirmed_by)
    )


# --------------------------------------------------------------------------
# Preprocessing
# --------------------------------------------------------------------------

@router.post(
    "/mappings/{mapping_id}/preprocess",
    response_model=PreprocessingRunOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Build the dimension and fact tables from a confirmed mapping",
)
def start_preprocessing(mapping_id: str, db: Session = Depends(get_db)) -> PreprocessingRunOut:
    run = mapping_service.start_preprocessing(db, mapping_id)
    return PreprocessingRunOut.model_validate(run)


@router.get(
    "/mappings/{mapping_id}/preprocessing",
    response_model=PreprocessingRunOut,
    summary="Latest preprocessing run for a mapping",
)
def get_preprocessing(mapping_id: str, db: Session = Depends(get_db)) -> PreprocessingRunOut:
    return PreprocessingRunOut.model_validate(
        mapping_service.latest_preprocessing_run(db, mapping_id)
    )

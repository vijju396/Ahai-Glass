"""Dataset ingestion, profiling, validation and key mapping."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.db.session import get_db
from app.domain.ais.source_spec import ALL_PII_COLUMNS
from app.models.datasets import ControlOutcome, DatasetVersion
from app.schemas.common import Page
from app.schemas.datasets import (
    DatasetCreateRequest,
    DatasetCreateResponse,
    DatasetOut,
    DatasetProfileResponse,
    DatasetVersionSummary,
    LeadTimeOut,
    MappingResponse,
    ServiceMeasuresOut,
    ValidationResponse,
)
from app.services import dataset_service

router = APIRouter(prefix="/datasets", tags=["datasets"])

CANONICAL_KEY_RULE = (
    "UPPER(TRIM(Product Code)) -> strip a trailing '.AFM' or '.AF' -> strip a "
    "trailing '.' -> TRIM again. Verified over all 1,703,042 sales rows, this "
    "yields exactly 2,260 distinct SKUs and 63,210 branch x SKU series."
)

WHY_NOT_ORACLE_NO = (
    "Raw Oracle No has only 2,147 distinct values because 109 Oracle numbers "
    "each span several canonical Product Codes - PREGST legacy prefixes, "
    "glass-spec character substitutions such as SCS/GCG, and model-prefix "
    "substitutions such as HX6/ZX6. Using it as the sole SKU key would merge "
    "those products and lose 113 SKUs' identity."
)


def _control_order(code: str) -> tuple[str, int]:
    """Natural sort, so S9 precedes S10 instead of following S1."""
    prefix = code.rstrip("0123456789")
    digits = code[len(prefix):]
    return prefix, int(digits) if digits else 0


def _version_summary(version: DatasetVersion) -> DatasetVersionSummary:
    return DatasetVersionSummary.model_validate(version)


def _manifest_summary(version: DatasetVersion) -> dict[str, Any]:
    if not version.manifest_path:
        return {}
    path = Path(version.manifest_path)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("summary", {})
    except (OSError, json.JSONDecodeError):
        # A missing or unreadable manifest degrades the response; it never
        # turns a successful ingestion into an error.
        return {}


@router.post(
    "",
    response_model=DatasetCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Register the source-file set and start ingestion in the background",
)
def create_dataset(
    payload: DatasetCreateRequest, db: Session = Depends(get_db)
) -> DatasetCreateResponse:
    dataset, version = dataset_service.create_dataset_with_version(
        db, name=payload.name, description=payload.description
    )
    dataset_service.start_ingestion(version.id)
    return DatasetCreateResponse(
        dataset=DatasetOut.model_validate(dataset),
        version_id=version.id,
        message=(
            "Ingestion started. It streams roughly 2.6 million rows across five "
            "files and takes several minutes; poll GET /api/datasets/{id} for progress."
        ),
    )


@router.get("", response_model=Page[DatasetOut], summary="List datasets")
def list_datasets(
    offset: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=200),
    db: Session = Depends(get_db),
) -> Page[DatasetOut]:
    rows, total = dataset_service.list_datasets(db, offset=offset, limit=limit)
    items: list[DatasetOut] = []
    for dataset in rows:
        out = DatasetOut.model_validate(dataset)
        if dataset.versions:
            out.latest_version = _version_summary(dataset.versions[-1])
        items.append(out)
    return Page[DatasetOut](items=items, total=total, offset=offset, limit=limit)


@router.get(
    "/{dataset_id}",
    response_model=DatasetOut,
    summary="Dataset metadata and the latest ingestion's progress",
)
def get_dataset(dataset_id: str, db: Session = Depends(get_db)) -> DatasetOut:
    dataset = dataset_service.get_dataset(db, dataset_id)
    out = DatasetOut.model_validate(dataset)
    if dataset.versions:
        out.latest_version = _version_summary(dataset.versions[-1])
    return out


@router.post(
    "/{dataset_id}/cancel",
    summary="Request cancellation of a running ingestion",
)
def cancel_ingestion(dataset_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    version = dataset_service.latest_version(db, dataset_id)
    cancelled = dataset_service.cancel_ingestion(db, version.id)
    return {
        "version_id": version.id,
        "cancellation_requested": cancelled,
        "detail": (
            "Cancellation requested; the job stops at its next checkpoint."
            if cancelled
            else "No running ingestion to cancel."
        ),
    }


@router.get(
    "/{dataset_id}/profile",
    response_model=DatasetProfileResponse,
    summary="Per-file, per-column profile",
)
def get_profile(dataset_id: str, db: Session = Depends(get_db)) -> DatasetProfileResponse:
    version = dataset_service.latest_version(db, dataset_id)
    detailed = dataset_service.version_with_profile(db, version.id)
    if not detailed.source_files:
        raise NotFoundError(
            "No profile yet: ingestion has not finished reading the source files."
        )
    return DatasetProfileResponse(
        version=_version_summary(detailed),
        source_files=[
            {
                **{
                    key: getattr(source_file, key)
                    for key in (
                        "role", "filename", "sheet_name", "size_bytes",
                        "content_hash_sha256", "row_count", "column_count",
                        "read_seconds",
                    )
                },
                "columns_json": source_file.columns_json,
                "column_profiles": sorted(
                    source_file.column_profiles, key=lambda profile: profile.ordinal
                ),
            }
            for source_file in detailed.source_files
        ],
        pii_columns_excluded=sorted(ALL_PII_COLUMNS),
        total_rows_read=sum(f.row_count for f in detailed.source_files),
    )


@router.get(
    "/{dataset_id}/validation",
    response_model=ValidationResponse,
    summary="Structural controls and the defect register",
)
def get_validation(dataset_id: str, db: Session = Depends(get_db)) -> ValidationResponse:
    version = dataset_service.latest_version(db, dataset_id)
    detailed = dataset_service.version_with_validation(db, version.id)
    if not detailed.controls:
        raise NotFoundError(
            "No validation result yet: ingestion has not reached the control stage."
        )

    failed = [
        control
        for control in detailed.controls
        if control.outcome == ControlOutcome.FAIL.value
    ]
    summary = _manifest_summary(detailed)
    measures = summary.get("service_measures")
    lead_time = summary.get("lead_time")

    return ValidationResponse(
        version=_version_summary(detailed),
        passed=not failed,
        controls=sorted(
            detailed.controls, key=lambda control: _control_order(control.control_code)
        ),
        defects=sorted(
            detailed.defects, key=lambda defect: _control_order(defect.defect_code)
        ),
        service_measures=ServiceMeasuresOut(**measures) if measures else None,
        lead_time=LeadTimeOut(**lead_time) if lead_time else None,
        summary=summary,
        blocking_message=(
            None
            if not failed
            else (
                f"{len(failed)} structural control(s) did not hold: "
                + ", ".join(control.control_code for control in failed)
                + ". Downstream phases must not treat this version as clean."
            )
        ),
    )


@router.get(
    "/{dataset_id}/mapping",
    response_model=MappingResponse,
    summary="Canonical SKU key reconciled against Oracle No",
)
def get_mapping(
    dataset_id: str,
    finding_type: str | None = Query(
        None,
        description="oracle_collision | canonical_disagreement | missing_oracle_no",
    ),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> MappingResponse:
    version = dataset_service.latest_version(db, dataset_id)
    findings, total = dataset_service.reconciliation_findings(
        db, version.id, finding_type=finding_type, limit=limit
    )
    summary = _manifest_summary(version)
    if not summary:
        raise NotFoundError(
            "No mapping result yet: ingestion has not reached the reconciliation stage."
        )
    return MappingResponse(
        version=_version_summary(version),
        canonical_sku_count=summary.get("canonical_sku_count", 0),
        oracle_no_count=summary.get("oracle_no_count", 0),
        oracle_collision_count=summary.get("oracle_collisions", 0),
        canonical_disagreement_count=summary.get("canonical_disagreements", 0),
        rows_missing_oracle=summary.get("rows_missing_oracle", 0),
        sku_prefixes=summary.get("sku_prefixes", {}),
        branch_universes=summary.get("branch_universes", {}),
        sku_universes=summary.get("sku_universes", {}),
        findings=findings,
        findings_total=total,
        canonical_key_rule=CANONICAL_KEY_RULE,
        why_not_oracle_no=WHY_NOT_ORACLE_NO,
    )

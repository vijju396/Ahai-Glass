"""Dataset lifecycle: create a version, run ingestion in the background,
persist files, profiles, controls, defects and key reconciliation.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.core.errors import NotFoundError
from app.core.logging import get_logger
from app.db.session import session_scope
from app.jobs.runner import CancellationToken, JobCancelled, get_runner
from app.models.datasets import (
    ColumnProfile,
    ControlOutcome,
    Dataset,
    DatasetVersion,
    DefectRecord,
    IngestionStatus,
    KeyReconciliation,
    SourceFile,
    ValidationControl,
)
from app.services.ingestion.ais_ingestion import (
    MAX_STORED_FINDINGS,
    AisIngestion,
    IngestionResult,
)

logger = get_logger(__name__)


def _expected_controls() -> dict[str, int]:
    settings = get_settings()
    return {
        "sales_rows": settings.expected_sales_rows,
        "order_rows": settings.expected_order_rows,
        "stock_rows": settings.expected_stock_rows,
        "product_master_rows": settings.expected_product_master_rows,
        "location_master_rows": settings.expected_location_master_rows,
        "sales_skus": settings.expected_sales_skus,
        "series": settings.expected_series,
        "normalized_depots": settings.expected_normalized_depots,
    }


# --------------------------------------------------------------------------
# Reads
# --------------------------------------------------------------------------

def list_datasets(db: Session, *, offset: int, limit: int) -> tuple[list[Dataset], int]:
    total = db.scalar(
        select(func.count()).select_from(Dataset).where(Dataset.is_deleted.is_(False))
    ) or 0
    rows = db.scalars(
        select(Dataset)
        .where(Dataset.is_deleted.is_(False))
        .order_by(Dataset.created_at.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    return list(rows), total


def get_dataset(db: Session, dataset_id: str) -> Dataset:
    dataset = db.get(Dataset, dataset_id)
    if dataset is None or dataset.is_deleted:
        raise NotFoundError(f"No dataset with id {dataset_id!r}.")
    return dataset


def latest_version(db: Session, dataset_id: str) -> DatasetVersion:
    get_dataset(db, dataset_id)
    version = db.scalars(
        select(DatasetVersion)
        .where(DatasetVersion.dataset_id == dataset_id)
        .order_by(DatasetVersion.version_number.desc())
        .limit(1)
    ).first()
    if version is None:
        raise NotFoundError(f"Dataset {dataset_id!r} has no ingested version yet.")
    return version


def get_version(db: Session, version_id: str) -> DatasetVersion:
    version = db.get(DatasetVersion, version_id)
    if version is None:
        raise NotFoundError(f"No dataset version with id {version_id!r}.")
    return version


def version_with_profile(db: Session, version_id: str) -> DatasetVersion:
    version = db.scalars(
        select(DatasetVersion)
        .where(DatasetVersion.id == version_id)
        .options(
            selectinload(DatasetVersion.source_files).selectinload(
                SourceFile.column_profiles
            )
        )
    ).first()
    if version is None:
        raise NotFoundError(f"No dataset version with id {version_id!r}.")
    return version


def version_with_validation(db: Session, version_id: str) -> DatasetVersion:
    version = db.scalars(
        select(DatasetVersion)
        .where(DatasetVersion.id == version_id)
        .options(
            selectinload(DatasetVersion.controls),
            selectinload(DatasetVersion.defects),
        )
    ).first()
    if version is None:
        raise NotFoundError(f"No dataset version with id {version_id!r}.")
    return version


def reconciliation_findings(
    db: Session, version_id: str, *, finding_type: str | None = None, limit: int = 100
) -> tuple[list[KeyReconciliation], int]:
    condition = KeyReconciliation.version_id == version_id
    query = select(KeyReconciliation).where(condition)
    count_query = select(func.count()).select_from(KeyReconciliation).where(condition)
    if finding_type:
        query = query.where(KeyReconciliation.finding_type == finding_type)
        count_query = count_query.where(KeyReconciliation.finding_type == finding_type)
    total = db.scalar(count_query) or 0
    rows = db.scalars(
        query.order_by(
            KeyReconciliation.finding_type, KeyReconciliation.occurrence_count.desc()
        ).limit(limit)
    ).all()
    return list(rows), total


# --------------------------------------------------------------------------
# Writes
# --------------------------------------------------------------------------

def create_dataset_with_version(
    db: Session, *, name: str, description: str | None
) -> tuple[Dataset, DatasetVersion]:
    settings = get_settings()
    dataset = Dataset(
        name=name,
        description=description,
        source_label=str(settings.source_data_dir.name),
    )
    db.add(dataset)
    db.flush()
    version = DatasetVersion(
        dataset_id=dataset.id, version_number=1, status=IngestionStatus.PENDING
    )
    db.add(version)
    db.commit()
    db.refresh(dataset)
    db.refresh(version)
    return dataset, version


def start_ingestion(version_id: str) -> str:
    """Submit the ingestion job. Returns immediately with the version id."""
    runner = get_runner()
    if runner.is_running(version_id):
        return version_id
    runner.submit(version_id, "ingestion", _run_ingestion_job, version_id)
    return version_id


def cancel_ingestion(db: Session, version_id: str) -> bool:
    version = get_version(db, version_id)
    cancelled = get_runner().cancel(version_id)
    if cancelled:
        version.stage_detail = "Cancellation requested."
        db.commit()
    return cancelled


def _run_ingestion_job(version_id: str, *, token: CancellationToken) -> None:
    settings = get_settings()

    def progress(stage: str, pct: float) -> None:
        token.raise_if_cancelled()
        with session_scope() as db:
            version = db.get(DatasetVersion, version_id)
            if version is None:
                return
            version.stage_detail = stage[:300]
            version.progress_pct = pct
            version.status = (
                IngestionStatus.READING if pct < 85 else IngestionStatus.VALIDATING
            )

    with session_scope() as db:
        version = db.get(DatasetVersion, version_id)
        if version is None:
            return
        version.status = IngestionStatus.READING
        version.started_at = datetime.now(timezone.utc)
        version.stage_detail = "Starting"
        version.progress_pct = 0.0

    try:
        ingestion = AisIngestion(settings.source_data_dir, progress=progress)
        result = ingestion.run(_expected_controls(), settings.control_tolerance_pct)
        token.raise_if_cancelled()
        _persist_result(version_id, result)
    except JobCancelled:
        with session_scope() as db:
            version = db.get(DatasetVersion, version_id)
            if version is not None:
                version.status = IngestionStatus.CANCELLED
                version.stage_detail = "Cancelled"
                version.finished_at = datetime.now(timezone.utc)
    except Exception as exc:  # noqa: BLE001 - recorded, not swallowed
        logger.exception("ingestion_failed", extra={"version_id": version_id})
        with session_scope() as db:
            version = db.get(DatasetVersion, version_id)
            if version is not None:
                version.status = IngestionStatus.FAILED
                version.failure_reason = f"{type(exc).__name__}: {exc}"[:2000]
                version.stage_detail = "Failed"
                version.finished_at = datetime.now(timezone.utc)


def _persist_result(version_id: str, result: IngestionResult) -> None:
    settings = get_settings()
    with session_scope() as db:
        version = db.get(DatasetVersion, version_id)
        if version is None:
            return

        for outcome in result.files:
            source_file = SourceFile(
                version_id=version_id,
                role=outcome.role.value,
                filename=outcome.filename,
                sheet_name=outcome.sheet_name,
                size_bytes=outcome.size_bytes,
                content_hash_sha256=outcome.content_hash,
                row_count=outcome.row_count,
                column_count=outcome.column_count,
                read_seconds=round(outcome.read_seconds, 2),
                columns_json=outcome.columns,
            )
            db.add(source_file)
            db.flush()
            for column_name, stats in outcome.column_stats.items():
                db.add(
                    ColumnProfile(
                        source_file_id=source_file.id,
                        column_name=column_name[:300],
                        ordinal=stats["ordinal"],
                        detected_type=stats["detected_type"],
                        non_null_count=stats["non_null_count"],
                        null_count=stats["null_count"],
                        distinct_count=stats["distinct_count"],
                        is_constant=bool(stats["is_constant"]),
                        is_pii=bool(stats["is_pii"]),
                        min_value=_clip(stats["min_value"]),
                        max_value=_clip(stats["max_value"]),
                        mean_value=stats["mean_value"],
                        sample_values_json=stats["sample_values"],
                        note=stats["note"],
                    )
                )

        for control in result.controls:
            db.add(
                ValidationControl(
                    version_id=version_id,
                    control_code=control.code,
                    description=control.description,
                    expected=control.expected,
                    measured=control.measured,
                    outcome=control.outcome.value,
                    difference=control.difference,
                    tolerance_pct=control.tolerance_pct,
                    remediation=control.remediation,
                )
            )

        for defect in result.defects:
            db.add(
                DefectRecord(
                    version_id=version_id,
                    defect_code=defect.code,
                    title=defect.title[:300],
                    severity=defect.severity,
                    extent=_clip(defect.extent),
                    affected_rows=defect.affected_rows,
                    source_role=defect.source_role,
                    rule_applied=defect.rule_applied,
                    fix_description=defect.fix_description,
                    evidence_json=defect.evidence,
                )
            )

        reconciliation = result.reconciliation
        if reconciliation is not None:
            stored = 0
            for oracle, skus in reconciliation.collisions.items():
                if stored >= MAX_STORED_FINDINGS:
                    break
                db.add(
                    KeyReconciliation(
                        version_id=version_id,
                        finding_type="oracle_collision",
                        key_value=oracle[:200],
                        related_values_json=skus[:20],
                        occurrence_count=len(skus),
                        note=(
                            "One Oracle No spans several canonical Product Codes. Using "
                            "Oracle No as the sole SKU key would merge these products."
                        ),
                    )
                )
                stored += 1
            stored = 0
            for sku, oracles in reconciliation.disagreements.items():
                if stored >= MAX_STORED_FINDINGS:
                    break
                db.add(
                    KeyReconciliation(
                        version_id=version_id,
                        finding_type="canonical_disagreement",
                        key_value=sku[:200],
                        related_values_json=oracles[:20],
                        occurrence_count=len(oracles),
                        note="One canonical SKU maps to several Oracle numbers.",
                    )
                )
                stored += 1
            if reconciliation.rows_missing_oracle:
                db.add(
                    KeyReconciliation(
                        version_id=version_id,
                        finding_type="missing_oracle_no",
                        key_value="(aggregate)",
                        related_values_json=None,
                        occurrence_count=reconciliation.rows_missing_oracle,
                        note="Sales rows carrying a Product Code but no Oracle No.",
                    )
                )

        failed = [control for control in result.controls if control.outcome is ControlOutcome.FAIL]
        version.controls_total = len(result.controls)
        version.controls_failed = len(failed)
        version.defects_total = len(result.defects)
        version.duration_seconds = round(result.duration_seconds, 2)
        version.finished_at = datetime.now(timezone.utc)
        version.progress_pct = 100.0
        version.stage_detail = "Complete"
        # A failed control never leaves the version looking clean.
        version.status = (
            IngestionStatus.COMPLETED_WITH_FAILURES if failed else IngestionStatus.COMPLETED
        )
        if failed:
            version.failure_reason = (
                f"{len(failed)} structural control(s) did not hold: "
                + ", ".join(control.code for control in failed)
            )

        manifest_dir = settings.runtime_dir / "storage" / "profiles"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = manifest_dir / f"ingestion_{version_id}.json"
        manifest_path.write_text(
            json.dumps(_build_manifest(version, result), indent=2, default=str),
            encoding="utf-8",
        )
        version.manifest_path = str(manifest_path)


def _build_manifest(version: DatasetVersion, result: IngestionResult) -> dict[str, Any]:
    """The versioned manifest: source hashes, counts, rules applied, controls."""
    return {
        "dataset_version_id": version.id,
        "version_number": version.version_number,
        "built_at_utc": datetime.now(timezone.utc).isoformat(),
        "duration_seconds": round(result.duration_seconds, 2),
        "source_files": [
            {
                "role": outcome.role.value,
                "filename": outcome.filename,
                "sheet_name": outcome.sheet_name,
                "size_bytes": outcome.size_bytes,
                "sha256": outcome.content_hash,
                "rows_read": outcome.row_count,
                "columns": outcome.column_count,
                "pii_columns_excluded": outcome.pii_columns,
            }
            for outcome in result.files
        ],
        "controls": [
            {
                "code": control.code,
                "description": control.description,
                "expected": control.expected,
                "measured": control.measured,
                "outcome": control.outcome.value,
                "difference": control.difference,
            }
            for control in result.controls
        ],
        "defects": [
            {
                "code": defect.code,
                "title": defect.title,
                "severity": defect.severity,
                "rule_applied": defect.rule_applied,
                "extent": defect.extent,
            }
            for defect in result.defects
        ],
        "summary": result.summary,
    }


def _clip(value: Any, length: int = 200) -> str | None:
    if value is None:
        return None
    return str(value)[:length]

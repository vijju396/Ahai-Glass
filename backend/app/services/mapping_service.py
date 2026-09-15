"""Mapping lifecycle: draft, edit, validate, confirm, preprocess.

A confirmed mapping is **immutable**. Editing one is refused; the caller
creates a new version, which supersedes the old. Nothing overwrites a mapping
a training run may already have used.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.core.errors import ConflictError, NotFoundError, ValidationFailedError
from app.core.logging import get_logger
from app.db.session import session_scope
from app.domain.ais.mapping_template import (
    FUTURE_KNOWN_COLUMNS,
    NOT_FUTURE_KNOWN_REASONS,
    build_default_assignments,
    default_config,
)
from app.domain.ais.source_spec import ALL_PII_COLUMNS
from app.jobs.runner import CancellationToken, JobCancelled, get_runner
from app.ml.features.role_suggestion import ColumnSignals, suggest_all
from app.ml.features.roles import (
    AggregationMethod,
    DuplicateHandling,
    ImputationPolicy,
    MappingConfig,
    MappingState,
    MissingTimestampPolicy,
    RoleAssignment,
    SemanticRole,
    blocking_violations,
    validate_mapping,
)
from app.models.datasets import DatasetVersion, IngestionStatus, SourceFile
from app.models.mappings import (
    ColumnRoleAssignment,
    MappingRuleResult,
    MappingVersion,
    PreprocessingRun,
)
from app.services import dataset_service
from app.services.preprocessing.ais_preprocessing import AisPreprocessing

logger = get_logger(__name__)


# --------------------------------------------------------------------------
# Reads
# --------------------------------------------------------------------------

def get_mapping(db: Session, mapping_id: str) -> MappingVersion:
    mapping = db.scalars(
        select(MappingVersion)
        .where(MappingVersion.id == mapping_id)
        .options(
            selectinload(MappingVersion.assignments),
            selectinload(MappingVersion.rule_results),
            selectinload(MappingVersion.preprocessing_runs),
        )
        # The session is configured with expire_on_commit=False, so an
        # identity-mapped MappingVersion keeps its previously loaded
        # collections. Without populate_existing, re-reading straight after
        # `validate()` deleted and re-inserted rule_results returns the stale
        # collection and the caller sees no violations at all.
        .execution_options(populate_existing=True)
    ).first()
    if mapping is None:
        raise NotFoundError(f"No mapping version with id {mapping_id!r}.")
    return mapping


def list_mappings(
    db: Session, *, dataset_version_id: str | None, offset: int, limit: int
) -> tuple[list[MappingVersion], int]:
    query = select(MappingVersion)
    count_query = select(func.count()).select_from(MappingVersion)
    if dataset_version_id:
        query = query.where(MappingVersion.dataset_version_id == dataset_version_id)
        count_query = count_query.where(
            MappingVersion.dataset_version_id == dataset_version_id
        )
    total = db.scalar(count_query) or 0
    rows = db.scalars(
        query.options(selectinload(MappingVersion.assignments))
        .order_by(MappingVersion.created_at.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    return list(rows), total


def latest_mapping_for_dataset(db: Session, dataset_id: str) -> MappingVersion:
    version = dataset_service.latest_version(db, dataset_id)
    mapping = db.scalars(
        select(MappingVersion)
        .where(MappingVersion.dataset_version_id == version.id)
        .order_by(MappingVersion.version_number.desc())
        .limit(1)
        .options(
            selectinload(MappingVersion.assignments),
            selectinload(MappingVersion.rule_results),
            selectinload(MappingVersion.preprocessing_runs),
        )
    ).first()
    if mapping is None:
        raise NotFoundError(
            f"Dataset {dataset_id!r} has no role mapping yet. Create one first."
        )
    return mapping


# --------------------------------------------------------------------------
# Suggestions
# --------------------------------------------------------------------------

def _signals_for_version(db: Session, version_id: str) -> list[ColumnSignals]:
    """Build suggester inputs from the profile the ingestion already produced,
    so suggestion needs no second pass over the source files."""
    detailed = dataset_service.version_with_profile(db, version_id)
    signals: list[ColumnSignals] = []
    for source_file in detailed.source_files:
        for profile in source_file.column_profiles:
            samples = tuple(profile.sample_values_json or ())
            signals.append(
                ColumnSignals(
                    source_role=source_file.role,
                    column_name=profile.column_name,
                    ordinal=profile.ordinal,
                    detected_type=profile.detected_type,
                    row_count=source_file.row_count,
                    non_null_count=profile.non_null_count,
                    distinct_count=profile.distinct_count,
                    is_constant=profile.is_constant,
                    is_pii=profile.is_pii,
                    parses_as_date=_looks_like_a_date_column(profile.column_name, samples),
                    sample_values=samples,
                )
            )
    return signals


def _looks_like_a_date_column(column_name: str, samples: tuple[str, ...]) -> bool:
    """Structural check: do the sampled values actually parse as dates?

    Excel serials arrive as bare numbers, so a numeric column whose name has no
    time cue is not treated as a date on value alone - otherwise every quantity
    column would qualify.
    """
    from app.services.ingestion.readers import parse_loose_date

    if not samples:
        return False
    parsed = sum(1 for sample in samples if parse_loose_date(sample) is not None)
    if parsed / len(samples) < 0.8:
        return False
    lowered = column_name.lower()
    numeric_only = all(
        sample.replace(".", "", 1).replace("-", "", 1).isdigit() for sample in samples
    )
    if numeric_only:
        return any(cue in lowered for cue in ("date", "time", "dt", "month", "period"))
    return True


def suggestions_for_dataset(db: Session, dataset_id: str) -> list[dict[str, Any]]:
    """Advisory only. Computed fresh, never persisted as authoritative."""
    version = dataset_service.latest_version(db, dataset_id)
    generic = {
        (s.source_role, s.column_name): s for s in suggest_all(_signals_for_version(db, version.id))
    }
    return [
        {
            "source_role": key[0],
            "column_name": key[1],
            "role": suggestion.role.value,
            "confidence": round(suggestion.confidence, 2),
            "rationale": suggestion.rationale,
            "is_authoritative": False,
        }
        for key, suggestion in sorted(generic.items())
    ]


# --------------------------------------------------------------------------
# Create / edit
# --------------------------------------------------------------------------

def create_mapping(db: Session, dataset_id: str, *, notes: str | None = None) -> MappingVersion:
    """Create a DRAFT mapping seeded from the AIS template, with the generic
    suggester filling any column the template has no opinion on."""
    version = dataset_service.latest_version(db, dataset_id)
    if version.status not in {
        IngestionStatus.COMPLETED,
        IngestionStatus.COMPLETED_WITH_FAILURES,
    }:
        raise ConflictError(
            "The dataset version has not finished ingesting, so its columns are "
            "not known yet.",
            remediation="Wait for ingestion to reach a terminal status, then retry.",
        )

    source_files = db.scalars(
        select(SourceFile).where(SourceFile.version_id == version.id)
    ).all()
    if not source_files:
        raise ConflictError("The dataset version has no profiled source files.")

    columns_by_source = {
        source_file.role: list(source_file.columns_json or []) for source_file in source_files
    }
    template = {
        (a.source_role, a.column_name): a
        for a in build_default_assignments(columns_by_source)
    }
    generic = {
        (s.source_role, s.column_name): s for s in suggest_all(_signals_for_version(db, version.id))
    }

    ordinals = {
        (source_file.role, column): index
        for source_file in source_files
        for index, column in enumerate(source_file.columns_json or [])
    }

    next_number = (
        db.scalar(
            select(func.max(MappingVersion.version_number)).where(
                MappingVersion.dataset_version_id == version.id
            )
        )
        or 0
    ) + 1

    mapping = MappingVersion(
        dataset_version_id=version.id,
        version_number=next_number,
        state=MappingState.DRAFT.value,
        notes=notes,
        **default_config().as_dict(),
    )
    db.add(mapping)
    db.flush()

    for key in sorted(set(template) | set(generic)):
        source_role, column_name = key
        chosen = template.get(key)
        if chosen is not None:
            role, confidence, rationale, notes_text = (
                chosen.role, chosen.confidence, chosen.rationale, chosen.notes
            )
        else:
            suggestion = generic[key]
            role, confidence, rationale = (
                suggestion.role, suggestion.confidence, suggestion.rationale
            )
            notes_text = NOT_FUTURE_KNOWN_REASONS.get(column_name)
        db.add(
            ColumnRoleAssignment(
                mapping_id=mapping.id,
                source_role=source_role,
                column_name=column_name,
                ordinal=ordinals.get(key, 0),
                role=role.value,
                is_suggested=True,
                confidence=confidence,
                rationale=rationale,
                notes=notes_text,
            )
        )

    db.commit()
    db.refresh(mapping)
    logger.info(
        "mapping_created",
        extra={"mapping_id": mapping.id, "version": next_number, "columns": len(template | generic)},
    )
    return get_mapping(db, mapping.id)


def update_assignments(
    db: Session, mapping_id: str, updates: list[dict[str, Any]]
) -> MappingVersion:
    """Edit a DRAFT mapping's role assignments.

    An edited assignment loses `is_suggested`: it has now been reviewed by a
    person, which is what the confirmation gate requires.
    """
    mapping = get_mapping(db, mapping_id)
    if mapping.is_confirmed:
        raise ConflictError(
            "A confirmed mapping is immutable.",
            remediation=(
                "Create a new mapping version instead. The confirmed one may already "
                "have been used by a training run."
            ),
        )
    if mapping.state == MappingState.SUPERSEDED.value:
        raise ConflictError("This mapping version has been superseded.")

    by_key = {(a.source_role, a.column_name): a for a in mapping.assignments}
    unknown: list[str] = []
    applied = 0

    for update in updates:
        key = (update["source_role"], update["column_name"])
        assignment = by_key.get(key)
        if assignment is None:
            unknown.append(f"{key[0]}.{key[1]}")
            continue
        new_role = SemanticRole(update["role"])
        if assignment.column_name in ALL_PII_COLUMNS and new_role is not SemanticRole.EXCLUDED_PII:
            raise ValidationFailedError(
                f"{assignment.column_name!r} is a PII column and can only be excluded.",
                details={"column": assignment.column_name, "requested_role": new_role.value},
                remediation="PII never enters a modelling dataset or an API payload.",
            )
        assignment.role = new_role.value
        # Reviewed by a person, so no longer a suggestion.
        assignment.is_suggested = False
        assignment.confidence = None
        assignment.rationale = update.get("rationale") or "Set by a reviewer."
        if update.get("aggregation"):
            assignment.aggregation = update["aggregation"]
        if update.get("imputation"):
            assignment.imputation = update["imputation"]
        applied += 1

    if unknown:
        raise ValidationFailedError(
            f"{len(unknown)} column(s) are not part of this mapping.",
            details={"unknown_columns": unknown[:20]},
        )

    db.commit()
    logger.info("mapping_updated", extra={"mapping_id": mapping_id, "applied": applied})
    return get_mapping(db, mapping_id)


def update_config(db: Session, mapping_id: str, config: dict[str, Any]) -> MappingVersion:
    mapping = get_mapping(db, mapping_id)
    if mapping.is_confirmed:
        raise ConflictError(
            "A confirmed mapping is immutable.",
            remediation="Create a new mapping version instead.",
        )
    for field_name, value in config.items():
        if value is not None and hasattr(mapping, field_name):
            setattr(mapping, field_name, value)
    db.commit()
    return get_mapping(db, mapping_id)


# --------------------------------------------------------------------------
# Validate / confirm
# --------------------------------------------------------------------------

def _to_role_assignments(mapping: MappingVersion) -> list[RoleAssignment]:
    return [
        RoleAssignment(
            source_role=a.source_role,
            column_name=a.column_name,
            role=SemanticRole(a.role),
            is_suggested=a.is_suggested,
            confidence=a.confidence,
            rationale=a.rationale,
        )
        for a in mapping.assignments
    ]


def _to_config(mapping: MappingVersion) -> MappingConfig:
    """Coerce the persisted strings back into enum members.

    The rules in `app.ml.features.roles` compare with `is`, which is correct
    for enums but silently false against a raw string - so passing the DB
    values through unconverted made the policy rules (R8, R9) unable to fire
    at all.
    """
    return MappingConfig(
        frequency=mapping.frequency,
        timezone=mapping.timezone,
        forecast_horizon=mapping.forecast_horizon,
        aggregation_method=AggregationMethod(mapping.aggregation_method),
        duplicate_handling=DuplicateHandling(mapping.duplicate_handling),
        missing_timestamp_policy=MissingTimestampPolicy(mapping.missing_timestamp_policy),
        target_imputation_policy=ImputationPolicy(mapping.target_imputation_policy),
        driver_imputation_policy=ImputationPolicy(mapping.driver_imputation_policy),
    )


def validate(db: Session, mapping_id: str) -> tuple[MappingVersion, list[MappingRuleResult]]:
    """Run every rule and persist the outcomes. Returns all of them, blocking
    and warning alike, so a reviewer sees the complete picture at once."""
    mapping = get_mapping(db, mapping_id)
    violations = validate_mapping(
        _to_role_assignments(mapping),
        _to_config(mapping),
        pii_columns=ALL_PII_COLUMNS,
        known_future_columns=FUTURE_KNOWN_COLUMNS,
    )

    for existing in list(mapping.rule_results):
        db.delete(existing)
    db.flush()

    results = [
        MappingRuleResult(
            mapping_id=mapping.id,
            rule_code=violation.code,
            severity=violation.severity,
            message=violation.message,
            columns_json=violation.columns or None,
            remediation=violation.remediation,
        )
        for violation in violations
    ]
    db.add_all(results)
    db.commit()
    return get_mapping(db, mapping_id), results


def confirm(db: Session, mapping_id: str, *, confirmed_by: str) -> MappingVersion:
    """Lock a mapping for training use.

    Refused while any blocking rule fails, or while a required role is still
    only a suggestion - an unreviewed target or time column is exactly the
    thing this gate exists to catch.
    """
    mapping, results = validate(db, mapping_id)
    if mapping.is_confirmed:
        raise ConflictError("This mapping is already confirmed.")

    blocking = [r for r in results if r.severity == "blocking"]
    if blocking:
        raise ValidationFailedError(
            f"{len(blocking)} blocking rule(s) prevent confirmation.",
            details={
                "violations": [
                    {"rule": r.rule_code, "message": r.message, "remediation": r.remediation}
                    for r in blocking
                ]
            },
            remediation="Resolve every blocking rule, then confirm again.",
        )

    unreviewed = [
        a.column_name
        for a in mapping.assignments
        if a.is_suggested
        and SemanticRole(a.role) in {SemanticRole.TARGET_COLUMN, SemanticRole.TIME_COLUMN}
    ]
    if unreviewed:
        raise ValidationFailedError(
            "The target and time columns must be reviewed before confirmation.",
            details={"unreviewed_columns": unreviewed},
            remediation=(
                "Confirm each of these explicitly. A suggested target is a guess, and "
                "on this dataset several columns look like demand."
            ),
        )

    # Supersede any earlier confirmed mapping for the same dataset version.
    previous = db.scalars(
        select(MappingVersion).where(
            MappingVersion.dataset_version_id == mapping.dataset_version_id,
            MappingVersion.state == MappingState.CONFIRMED.value,
            MappingVersion.id != mapping.id,
        )
    ).all()
    now = datetime.now(timezone.utc)
    for earlier in previous:
        earlier.state = MappingState.SUPERSEDED.value
        earlier.superseded_at = now
        earlier.superseded_by_id = mapping.id

    mapping.state = MappingState.CONFIRMED.value
    mapping.confirmed_at = now
    mapping.confirmed_by = confirmed_by
    db.commit()
    logger.info(
        "mapping_confirmed",
        extra={"mapping_id": mapping.id, "superseded": len(previous)},
    )
    return get_mapping(db, mapping_id)


# --------------------------------------------------------------------------
# Preprocessing
# --------------------------------------------------------------------------

def start_preprocessing(db: Session, mapping_id: str) -> PreprocessingRun:
    mapping = get_mapping(db, mapping_id)
    if not mapping.is_confirmed:
        raise ConflictError(
            "Preprocessing requires a confirmed mapping.",
            remediation="Confirm the mapping first; a draft may still change.",
        )
    run = PreprocessingRun(mapping_id=mapping.id, status="pending")
    db.add(run)
    db.commit()
    db.refresh(run)
    get_runner().submit(run.id, "preprocessing", _run_preprocessing_job, run.id)
    return run


def get_preprocessing_run(db: Session, run_id: str) -> PreprocessingRun:
    run = db.get(PreprocessingRun, run_id)
    if run is None:
        raise NotFoundError(f"No preprocessing run with id {run_id!r}.")
    return run


def latest_preprocessing_run(db: Session, mapping_id: str) -> PreprocessingRun:
    run = db.scalars(
        select(PreprocessingRun)
        .where(PreprocessingRun.mapping_id == mapping_id)
        .order_by(PreprocessingRun.created_at.desc())
        .limit(1)
    ).first()
    if run is None:
        raise NotFoundError(f"Mapping {mapping_id!r} has not been preprocessed yet.")
    return run


def _run_preprocessing_job(run_id: str, *, token: CancellationToken) -> None:
    settings = get_settings()

    def progress(stage: str, pct: float) -> None:
        token.raise_if_cancelled()
        with session_scope() as db:
            run = db.get(PreprocessingRun, run_id)
            if run is not None:
                run.stage_detail = stage[:300]
                run.progress_pct = pct
                run.status = "running"

    with session_scope() as db:
        run = db.get(PreprocessingRun, run_id)
        if run is None:
            return
        run.status = "running"
        run.started_at = datetime.now(timezone.utc)
        run.stage_detail = "Starting"

    try:
        output_dir = settings.runtime_dir / "storage" / "prepared" / run_id
        engine = AisPreprocessing(settings.source_data_dir, progress=progress)
        result = engine.run(output_dir)
        token.raise_if_cancelled()

        manifest_path = output_dir / "preprocessing_manifest.json"
        with session_scope() as db:
            run = db.get(PreprocessingRun, run_id)
            if run is None:
                return
            manifest = {
                "preprocessing_run_id": run_id,
                "mapping_id": run.mapping_id,
                "built_at_utc": datetime.now(timezone.utc).isoformat(),
                "duration_seconds": round(result.duration_seconds, 2),
                "artifacts": result.artifacts,
                "summary": result.summary,
                "warnings": result.warnings,
            }
            manifest_path.write_text(
                json.dumps(manifest, indent=2, default=str), encoding="utf-8"
            )

            run.status = "completed"
            run.stage_detail = "Complete"
            run.progress_pct = 100.0
            run.finished_at = datetime.now(timezone.utc)
            run.duration_seconds = round(result.duration_seconds, 2)
            run.branch_dim_rows = len(result.branch_dim)
            run.product_dim_rows = len(result.product_dim)
            run.order_fact_rows = len(result.order_fact)
            run.sales_fact_rows = len(result.sales_fact)
            run.fact_rows = len(result.order_fact) + len(result.sales_fact)
            run.stock_position_rows = len(result.stock_position)
            run.distinct_series = result.summary.get("distinct_series", 0)
            run.distinct_periods = result.summary.get("distinct_periods", 0)
            run.manifest_path = str(manifest_path)
            run.artifacts_json = result.artifacts
            run.summary_json = {**result.summary, "warnings": result.warnings}
    except JobCancelled:
        with session_scope() as db:
            run = db.get(PreprocessingRun, run_id)
            if run is not None:
                run.status = "cancelled"
                run.stage_detail = "Cancelled"
                run.finished_at = datetime.now(timezone.utc)
    except Exception as exc:  # noqa: BLE001 - recorded, not swallowed
        logger.exception("preprocessing_failed", extra={"run_id": run_id})
        with session_scope() as db:
            run = db.get(PreprocessingRun, run_id)
            if run is not None:
                run.status = "failed"
                run.failure_reason = f"{type(exc).__name__}: {exc}"[:2000]
                run.stage_detail = "Failed"
                run.finished_at = datetime.now(timezone.utc)

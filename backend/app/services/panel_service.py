"""Panel build lifecycle."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import ConflictError, NotFoundError
from app.core.logging import get_logger
from app.db.session import session_scope
from app.domain.ais.panel_builder import AisPanelBuilder
from app.jobs.runner import CancellationToken, JobCancelled, get_runner
from app.ml.features.feature_builder import DEFAULT_HORIZONS
from app.models.mappings import PreprocessingRun
from app.models.panel import PanelBuild

logger = get_logger(__name__)


def get_build(db: Session, build_id: str) -> PanelBuild:
    build = db.get(PanelBuild, build_id)
    if build is None:
        raise NotFoundError(f"No panel build with id {build_id!r}.")
    return build


def latest_build(db: Session, preprocessing_run_id: str | None = None) -> PanelBuild:
    query = select(PanelBuild)
    if preprocessing_run_id:
        query = query.where(PanelBuild.preprocessing_run_id == preprocessing_run_id)
    build = db.scalars(query.order_by(PanelBuild.created_at.desc()).limit(1)).first()
    if build is None:
        raise NotFoundError("No panel has been built yet.")
    return build


def list_builds(db: Session, *, offset: int, limit: int) -> tuple[list[PanelBuild], int]:
    total = db.scalar(select(func.count()).select_from(PanelBuild)) or 0
    rows = db.scalars(
        select(PanelBuild).order_by(PanelBuild.created_at.desc()).offset(offset).limit(limit)
    ).all()
    return list(rows), total


def latest_completed_preprocessing_run(db: Session) -> PreprocessingRun:
    """The newest completed run, not the first.

    An earlier run may predate a fix - two exist on this project, and the older
    one reports zero non-glass SKUs (docs/DECISIONS.md D-024).
    """
    run = db.scalars(
        select(PreprocessingRun)
        .where(PreprocessingRun.status == "completed")
        .order_by(PreprocessingRun.created_at.desc())
        .limit(1)
    ).first()
    if run is None:
        raise ConflictError(
            "No completed preprocessing run exists.",
            remediation="Confirm a mapping and run preprocessing first.",
        )
    return run


def start_build(
    db: Session,
    preprocessing_run_id: str,
    *,
    training_cut_period: str | None,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
) -> PanelBuild:
    run = db.get(PreprocessingRun, preprocessing_run_id)
    if run is None:
        raise NotFoundError(f"No preprocessing run with id {preprocessing_run_id!r}.")
    if run.status != "completed":
        raise ConflictError(
            f"The preprocessing run is {run.status!r}, not completed.",
            remediation="Wait for preprocessing to finish, then build the panel.",
        )
    if not run.artifacts_json:
        raise ConflictError("The preprocessing run produced no artifacts.")

    build = PanelBuild(
        preprocessing_run_id=run.id,
        status="pending",
        training_cut_period=training_cut_period,
        horizons=",".join(str(h) for h in horizons),
    )
    db.add(build)
    db.commit()
    db.refresh(build)
    get_runner().submit(build.id, "panel_build", _run_build_job, build.id)
    return build


def _run_build_job(build_id: str, *, token: CancellationToken) -> None:
    settings = get_settings()

    def progress(stage: str, pct: float) -> None:
        token.raise_if_cancelled()
        with session_scope() as db:
            build = db.get(PanelBuild, build_id)
            if build is not None:
                build.stage_detail = stage[:300]
                build.progress_pct = pct
                build.status = "running"

    with session_scope() as db:
        build = db.get(PanelBuild, build_id)
        if build is None:
            return
        run = db.get(PreprocessingRun, build.preprocessing_run_id)
        artifacts = dict(run.artifacts_json or {}) if run else {}
        cut = build.training_cut_period
        horizons = tuple(int(h) for h in build.horizons.split(","))
        build.status = "running"
        build.started_at = datetime.now(timezone.utc)
        build.stage_detail = "Starting"

    try:
        output_dir = settings.runtime_dir / "storage" / "prepared" / f"panel_{build_id}"
        builder = AisPanelBuilder(artifacts, progress=progress)
        result = builder.run(output_dir, horizons=horizons, training_cut_period=cut)
        token.raise_if_cancelled()

        manifest_path = output_dir / "panel_manifest.json"
        with session_scope() as db:
            build = db.get(PanelBuild, build_id)
            if build is None:
                return
            manifest: dict[str, Any] = {
                "panel_build_id": build_id,
                "preprocessing_run_id": build.preprocessing_run_id,
                "built_at_utc": datetime.now(timezone.utc).isoformat(),
                "duration_seconds": round(result.duration_seconds, 2),
                "training_cut_period": cut,
                "horizons": list(horizons),
                "artifacts": result.artifacts,
                "summary": result.summary,
                "warnings": result.warnings,
            }
            manifest_path.write_text(
                json.dumps(manifest, indent=2, default=str), encoding="utf-8"
            )

            grid = result.summary.get("grid", {})
            features = result.summary.get("feature_manifest", {})
            build.status = "completed"
            build.stage_detail = "Complete"
            build.progress_pct = 100.0
            build.finished_at = datetime.now(timezone.utc)
            build.duration_seconds = round(result.duration_seconds, 2)
            build.panel_rows = result.panel_rows
            build.series_count = result.series_count
            build.period_count = result.period_count
            build.observed_rows = int(result.summary.get("observed_rows", 0))
            build.materialised_zero_rows = int(grid.get("materialised_zero_rows", 0))
            build.censored_rows = int(result.summary.get("censored_rows", 0))
            build.training_rows = result.training_rows
            build.scoring_rows = result.scoring_rows
            build.feature_count = int(features.get("feature_count", 0))
            build.manifest_path = str(manifest_path)
            build.artifacts_json = result.artifacts
            build.summary_json = {**result.summary, "warnings": result.warnings}
    except JobCancelled:
        with session_scope() as db:
            build = db.get(PanelBuild, build_id)
            if build is not None:
                build.status = "cancelled"
                build.stage_detail = "Cancelled"
                build.finished_at = datetime.now(timezone.utc)
    except Exception as exc:  # noqa: BLE001 - recorded, not swallowed
        logger.exception("panel_build_failed", extra={"build_id": build_id})
        with session_scope() as db:
            build = db.get(PanelBuild, build_id)
            if build is not None:
                build.status = "failed"
                build.failure_reason = f"{type(exc).__name__}: {exc}"[:2000]
                build.stage_detail = "Failed"
                build.finished_at = datetime.now(timezone.utc)

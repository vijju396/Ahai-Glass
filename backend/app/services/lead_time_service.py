"""The stated-vs-observed lead time view, computed once and cached to disk.

Reading 775,912 order lines out of `.xlsx` takes tens of seconds, which is not
something a page load can do. The per-branch aggregate is small - 53 rows - so
it is computed once and written to a parquet under `runtime/storage`, keyed on
a fingerprint of both source files.

**The fingerprint is size and modification time, not a hash.** Hashing a 90 MB
workbook costs most of what the parse costs, which would defeat the point. Size
and mtime both changing without the content changing is not a failure mode
worth paying for here; the client's files are read-only to this application
anyway (D-105).

Nothing in this module writes to `data/source/`. It reads both files and writes
only into `runtime/storage`.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pandas as pd

from app.core.config import get_settings
from app.domain.ais import lead_time_observed as observed
from app.domain.ais.source_spec import LOCATION_MASTER_SPEC, ORDERS_SPEC

logger = logging.getLogger(__name__)

CACHE_DIR = "lead_time_observed"


def _fingerprint(paths: list[Path]) -> str:
    parts = []
    for path in paths:
        stat = path.stat()
        parts.append(f"{path.name}:{stat.st_size}:{int(stat.st_mtime)}")
    return "|".join(parts)


def _cache_root() -> Path:
    root = get_settings().runtime_dir / "storage" / CACHE_DIR
    root.mkdir(parents=True, exist_ok=True)
    return root


def _shipped_extract(root: Path) -> tuple[pd.DataFrame, dict[str, Any], dict[str, Any]] | None:
    """The durations a deployment carries in place of the orders workbook.

    Distinguished from the ordinary cache by what it lacks: a cache is keyed on
    a fingerprint of the file it was built from, and an extract has no such
    file, so it carries an `extract` block instead. Returning None here means
    "this is not one", and the caller falls through to the normal path.
    """
    meta_path = root / "meta.json"
    lines_path = root / "lines.parquet"
    if not (meta_path.is_file() and lines_path.is_file()):
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - an unreadable extract is not an outage
        logger.warning("lead-time extract unreadable: %s", exc)
        return None
    extract = meta.get("extract")
    if not extract or meta.get("fingerprint"):
        return None
    return pd.read_parquet(lines_path), meta.get("notes", {}), extract


def build(
    *,
    refresh: bool = False,
    branches: list[str] | None = None,
    skus: list[str] | None = None,
) -> dict[str, Any]:
    """Stated vs observed lead time for a workspace, with its own coverage notes.

    The per-line durations are cached whole and the restriction is applied on
    read, so switching workspace does not re-parse 775,912 rows. Restricting
    before every aggregate - never after - is what keeps a two-branch figure
    from being computed over fifty-three (D-049).
    """
    settings = get_settings()
    source = settings.source_data_dir
    orders_path = source / ORDERS_SPEC.filename
    master_path = source / LOCATION_MASTER_SPEC.filename

    root = _cache_root()
    frame_path = root / "branches.parquet"
    meta_path = root / "meta.json"
    lines_path = root / "lines.parquet"

    lines: pd.DataFrame | None = None
    notes: dict[str, Any] | None = None
    master: pd.DataFrame | None = None
    cached_hit = False
    extract: dict[str, Any] | None = None

    # A deployment carries the parsed durations, not the 67 MB workbook they
    # came out of (docs/DECISIONS.md D-137). `build_scoped_bundle.py` writes
    # them with an `extract` block and no fingerprint — no fingerprint is the
    # signal, because there is no file here to fingerprint against.
    shipped = _shipped_extract(root)
    if shipped is not None and not orders_path.exists() and master_path.exists():
        lines, notes, extract = shipped
        master = observed.read_master(master_path)
        cached_hit = True

    missing = [p.name for p in (orders_path, master_path) if not p.exists()]
    if lines is None and missing:
        return {
            "empty": True,
            "reason": (
                f"Source file(s) not found: {', '.join(missing)}. This view reads "
                "them directly and nothing is substituted."
            ),
            "branches": [],
            "notes": {},
        }

    if lines is None:
        stamp = _fingerprint([orders_path, master_path])
        if not refresh and lines_path.exists() and meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                if meta.get("fingerprint") == stamp:
                    lines = pd.read_parquet(lines_path)
                    notes = meta["notes"]
                    master = observed.read_master(master_path)
                    cached_hit = True
            except Exception as exc:  # noqa: BLE001 - a bad cache must not break the page
                logger.warning("lead-time cache unreadable, rebuilding: %s", exc)

        if lines is None or notes is None or master is None:
            lines, notes = observed.read_durations(orders_path)
            master = observed.read_master(master_path)
            lines.to_parquet(lines_path, index=False)
            meta_path.write_text(
                json.dumps({"fingerprint": stamp, "notes": notes}, default=str),
                encoding="utf-8",
            )

    scoped = observed.restrict(lines, branches=branches, skus=skus)
    comparison = observed.compare(
        master[master["branch"].isin(scoped["branch"].unique())] if branches else master,
        observed.aggregate(scoped),
    )
    months = observed.by_month(scoped)
    return _payload(
        comparison,
        notes,
        cached_result=cached_hit,
        scoped_lines=int(len(scoped)),
        by_sku=observed.by_sku(scoped),
        by_month=months,
        distribution=observed.distribution(scoped),
        trend=observed.trend(months),
        scope={
            "branches": sorted(scoped["branch"].unique().tolist()),
            "skus": len(set(skus)) if skus else int(scoped["sku"].nunique()),
            "restricted": bool(branches or skus),
        },
        extract=extract,
    )


def _payload(
    frame: pd.DataFrame,
    notes: dict[str, Any],
    *,
    cached_result: bool,
    scoped_lines: int = 0,
    by_sku: list[dict[str, Any]] | None = None,
    by_month: list[dict[str, Any]] | None = None,
    distribution: list[dict[str, Any]] | None = None,
    trend: dict[str, Any] | None = None,
    scope: dict[str, Any] | None = None,
    extract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    columns = [
        "branch", "lines", "stated_avg", "stated_std", "transit", "service_factor",
        "truck_moq", "observed_mean", "observed_median", "observed_std",
        "observed_p95", "observed_max", "gap_mean", "gap_p95", "review",
        "service_factor_usable",
    ]
    # `astype(object)` before the NaN sweep: on a float column `.where` leaves
    # NaN in place, which serialises to a JSON `NaN` the browser cannot parse
    # and which `int()` refuses. A missing measurement has to reach the page as
    # null, not as a number-shaped hole.
    rows = frame.reindex(columns=columns).astype(object)
    branches = rows.where(pd.notna(rows), None).to_dict("records")
    for row in branches:
        if row.get("lines") is not None:
            row["lines"] = int(row["lines"])
        row["service_factor_usable"] = bool(row.get("service_factor_usable"))

    flagged = [b for b in branches if b.get("review")]
    return {
        "empty": not branches,
        "reason": None if branches else "No branch could be compared.",
        "cached": cached_result,
        "branches": branches,
        "flagged_count": len(flagged),
        "scope": scope or {},
        # Null when the figures came off the workbook itself. Non-null means
        # this deployment carries a branch-restricted extract of the parse
        # instead of the 67 MB file, and the page says so rather than letting
        # a reader assume the whole order history is behind these numbers
        # (D-137). The parse statistics in `notes` still describe the full
        # file, because that is the parse these durations came out of.
        "extract": extract,
        "scoped_lines": scoped_lines,
        "by_sku": by_sku or [],
        "by_month": by_month or [],
        "distribution": distribution or [],
        "trend": trend,
        "notes": notes,
        "definitions": {
            "stated_avg": "Location Master `Avg Lead Time`, a static value supplied per branch.",
            "observed_mean": (
                "Mean of Despatch Date minus Order Date over this branch's order lines. "
                "A derived view of two existing columns; neither is altered."
            ),
            "observed_p95": (
                "The duration 95% of this branch's lines came in under. The mean hides "
                "the tail, and the tail is what causes a stockout."
            ),
            "gap_mean": "observed_mean minus stated_avg. Positive means orders took longer than stated.",
            "service_factor": (
                "Location Master `Service Factor`. A z-score: 1.0 is about 84% service, "
                "1.65 about 95%. Values outside 0-5 cannot be one and are flagged."
            ),
            "by_sku": (
                "Observed duration per SKU. Location Master is branch-grained, so "
                "there is no stated per-SKU lead time to compare against and none is "
                "invented."
            ),
            "trend": (
                "The first third of the observed months against the last third, "
                "weighted by line count. A measured change between two windows, not a "
                "fitted slope - a slope would imply a model of how lead time moves, "
                "and there is none here."
            ),
            "invoice": (
                "Despatch -> Invoice is reported as a shape, not a duration: 40% of lines "
                "are invoiced BEFORE despatch, clustered at -1 and -2 days. That is a "
                "billing practice, so averaging it would produce a meaningless number."
            ),
        },
        "caveats": [
            "This is a comparison, not a correction. No value in Location Master is "
            "rewritten and no order line is dropped from the source.",
            "A gap is not automatically an error. The master's figure may be a "
            "deliberate planning allowance rather than a claim about observed timing - "
            "that is for the client to say.",
            "Order to Despatch is not end-to-end replenishment time. The file has no "
            "goods-receipt date, so the leg after despatch is not observable.",
            "Nothing here feeds a forecast, a recommendation or a safety-stock figure. "
            "The protection period still uses the master's average alone.",
        ],
    }

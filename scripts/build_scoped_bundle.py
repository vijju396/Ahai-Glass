"""Build the deployment bundle: the workspace scope's data, and nothing else.

The first Azure image carried everything this workspace has ever held — the
full 150 MB of client workbooks, a 81 MB panel over 68,675 series that no live
run reads, and six superseded training runs at a grain the application no
longer uses. 348 MB of build context, most of it answering no question the
deployed pages ask.

This builds the other thing: one run, one panel, the branches and SKUs the
deployment reports on, and an extract of the order history restricted to the
same branches. Roughly 100 MB instead of 348 MB, and every row in it is a row
some page can actually reach.

What that costs, stated rather than discovered later:

- **Superseded training runs are gone.** The deployed run history shows one
  run, not seven. The six dropped are 40-to-49-series monthly runs; the live
  one is the 281-series weekly run every screen reads. A monthly run's
  forecasts cannot be read at weekly grain anyway (D-105), so keeping them
  would have shown a reader runs whose numbers contradict the current ones.
- **The source workbooks are not deployed.** Ingestion and preprocessing are
  therefore unavailable on the deployment, and `/api/health` says so by name
  rather than reporting four files mysteriously missing. The Ordered vs
  Dispatched Time page keeps working, because what it needs is the parsed
  durations, and those ship as a branch-restricted extract.

Run it before every image build:

    python scripts/build_scoped_bundle.py
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

BUNDLE = PROJECT_ROOT / "deploy" / "bundle"
RUNTIME = PROJECT_ROOT / "runtime"

#: Where the project root sits inside the image. The Dockerfile's `WORKDIR
#: /app` and `app/core/config.py`'s `parents[2]` have to agree on this, and
#: the stored absolute paths in the database are rewritten to match.
CONTAINER_ROOT = "/app"

#: Shipped whole: 24 KB, and the Ordered vs Dispatched Time page compares the
#: observed durations against the stated averages held in it.
SOURCE_FILES_SHIPPED = ("Location Master.csv",)


def _mb(path: Path) -> float:
    if path.is_file():
        return path.stat().st_size / 1_048_576
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file()) / 1_048_576


def _copy_database(live_run: str) -> dict[str, object]:
    """A consistent copy of the database, pruned to the live run.

    `.backup` rather than a byte copy: the live file carries a write-ahead log,
    and copying the three files would stage a half-applied one.
    """
    target = BUNDLE / "runtime" / "db" / "ais.db"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()

    source = sqlite3.connect(f"file:{RUNTIME / 'db' / 'ais.db'}?mode=ro", uri=True)
    dest = sqlite3.connect(target)
    with dest:
        source.backup(dest)
    source.close()

    before = _mb(target)
    cur = dest.cursor()
    dropped = [
        r[0]
        for r in cur.execute(
            "SELECT id FROM training_run WHERE id <> ?", (live_run,)
        ).fetchall()
    ]

    deleted: dict[str, int] = {}

    def _delete(sql: str, params: tuple, label: str) -> None:
        deleted[label] = deleted.get(label, 0) + cur.execute(sql, params).rowcount

    for run in dropped:
        # forecast_row hangs off forecast_run, which hangs off training_run, so
        # the leaf goes first or the delete leaves orphans behind.
        _delete(
            "DELETE FROM forecast_row WHERE forecast_run_id IN "
            "(SELECT id FROM forecast_run WHERE training_run_id = ?)",
            (run,),
            "forecast_row",
        )
        _delete("DELETE FROM forecast_run WHERE training_run_id = ?", (run,), "forecast_run")
        _delete("DELETE FROM model_run WHERE training_run_id = ?", (run,), "model_run")
        _delete(
            "DELETE FROM champion_selection WHERE training_run_id = ?",
            (run,),
            "champion_selection",
        )
        _delete(
            "DELETE FROM quantile_calibration WHERE training_run_id = ?",
            (run,),
            "quantile_calibration",
        )
        _delete("DELETE FROM training_run WHERE id = ?", (run,), "training_run")

    # Panel builds and preprocessing runs nothing points at any more. Left in
    # place they would list panels whose parquet is not in the bundle, and a
    # page offering a panel it cannot open is worse than one short list.
    _delete(
        "DELETE FROM panel_build WHERE id NOT IN "
        "(SELECT panel_build_id FROM training_run UNION "
        " SELECT panel_build_id FROM forecast_run)",
        (),
        "panel_build",
    )
    _delete(
        "DELETE FROM preprocessing_run WHERE id NOT IN "
        "(SELECT preprocessing_run_id FROM panel_build)",
        (),
        "preprocessing_run",
    )
    dest.commit()
    cur.execute("VACUUM")
    dest.commit()
    dest.close()

    return {
        "runs_dropped": len(dropped),
        "rows_deleted": {k: v for k, v in deleted.items() if v},
        "mb_before_prune": round(before, 1),
        "mb_after_prune": round(_mb(target), 1),
    }


def _rewrite_paths(target_root: str) -> dict[str, object]:
    """Repoint every stored absolute path at the container's project root.

    The application records where it put things — a panel manifest, a run's
    artefact directory, a fitted model file — as absolute paths, and they are
    absolute paths **on the machine that trained the run**. Copied into an
    image they name a directory that does not exist, and the first page to
    open the panel raises `FileNotFoundError` on `/Users/.../panel.parquet`.
    That is exactly how this was found: `/api/analytics/summary` and
    `/api/inventory/recommendations` returned 500 on the deployment while
    working locally (D-137).

    Rewritten here rather than resolved at read time because the bundle is
    built for one known layout: the Dockerfile fixes the project root at
    `/app`, and `app/core/config.py` derives every path from the backend
    package's own location, so the two agree by construction.

    Every text column of every table is scanned, not a hand-listed few. The
    seven that currently carry a path are spread over five tables and two of
    them are inside JSON blobs, which is the kind of list that goes stale
    silently.
    """
    db = sqlite3.connect(BUNDLE / "runtime" / "db" / "ais.db")
    source_root = str(PROJECT_ROOT)
    changed: dict[str, int] = {}
    tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    for table in tables:
        for column in [r[1] for r in db.execute(f"PRAGMA table_info({table})")]:
            try:
                hits = db.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE CAST({column} AS TEXT) LIKE ?",
                    (f"%{source_root}%",),
                ).fetchone()[0]
            except sqlite3.Error:
                continue
            if not hits:
                continue
            db.execute(
                f"UPDATE {table} SET {column} = REPLACE(CAST({column} AS TEXT), ?, ?) "
                f"WHERE CAST({column} AS TEXT) LIKE ?",
                (source_root, target_root, f"%{source_root}%"),
            )
            changed[f"{table}.{column}"] = hits
    db.commit()

    # Nothing may still name the development machine. A path that survives
    # here is a page that 500s on the deployment and nowhere else.
    remaining = 0
    for table in tables:
        for column in [r[1] for r in db.execute(f"PRAGMA table_info({table})")]:
            try:
                remaining += db.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE CAST({column} AS TEXT) LIKE ?",
                    (f"%{source_root}%",),
                ).fetchone()[0]
            except sqlite3.Error:
                continue
    db.close()
    if remaining:
        raise RuntimeError(f"{remaining} stored paths still point at {source_root}")

    # The manifests on disk carry the same paths. Nothing reads an artefact
    # location out of them — the database is what `load_panel` consults — but
    # they are provenance documents the pages surface, and a manifest that
    # names `/Users/HXT/...` on a deployed page is telling a reader something
    # untrue about where the run's output lives.
    manifests = 0
    for file in sorted(BUNDLE.rglob("*.json")):
        text = file.read_text(encoding="utf-8")
        if source_root not in text:
            continue
        file.write_text(text.replace(source_root, target_root), encoding="utf-8")
        manifests += 1

    strays = [
        str(f.relative_to(BUNDLE))
        for f in BUNDLE.rglob("*")
        if f.is_file()
        and f.suffix in {".json", ".txt", ".csv", ".md"}
        and source_root in f.read_text(encoding="utf-8", errors="ignore")
    ]
    if strays:
        raise RuntimeError(f"{source_root} survives in {strays}")

    return {
        "target_root": target_root,
        "columns_rewritten": changed,
        "manifests_rewritten": manifests,
    }


def _copy_storage(live_run: str, panel_id: str, preprocessing_id: str) -> dict[str, object]:
    """Only the artefacts the live run reads: its panel, and its fitted models."""
    kept: list[str] = []
    skipped: list[str] = []

    prepared_src = RUNTIME / "storage" / "prepared"
    prepared_dst = BUNDLE / "runtime" / "storage" / "prepared"
    prepared_dst.mkdir(parents=True, exist_ok=True)
    wanted = {preprocessing_id, f"panel_{panel_id}"}
    for child in sorted(p for p in prepared_src.iterdir() if p.is_dir()):
        if child.name in wanted:
            shutil.copytree(child, prepared_dst / child.name, dirs_exist_ok=True)
            kept.append(f"prepared/{child.name} ({_mb(child):.1f} MB)")
        else:
            skipped.append(f"prepared/{child.name} ({_mb(child):.1f} MB)")

    models_src = RUNTIME / "storage" / "models"
    models_dst = BUNDLE / "runtime" / "storage" / "models"
    models_dst.mkdir(parents=True, exist_ok=True)
    for child in sorted(p for p in models_src.iterdir() if p.is_dir()):
        if child.name == live_run:
            shutil.copytree(child, models_dst / child.name, dirs_exist_ok=True)
            kept.append(f"models/{child.name} ({_mb(child):.1f} MB)")
        else:
            skipped.append(f"models/{child.name} ({_mb(child):.1f} MB)")

    # Small, and read by pages: the column profiles behind Data Studio.
    for name in ("profiles", "raw", "reports", "forecasts"):
        src = RUNTIME / "storage" / name
        if src.is_dir():
            shutil.copytree(src, BUNDLE / "runtime" / "storage" / name, dirs_exist_ok=True)

    mlflow_src = RUNTIME / "mlflow"
    if mlflow_src.is_dir():
        shutil.copytree(mlflow_src, BUNDLE / "runtime" / "mlflow", dirs_exist_ok=True)

    return {"kept": kept, "skipped": skipped}


def _copy_lead_time_extract(branches: list[str]) -> dict[str, object]:
    """The order durations, restricted to the workspace's branches.

    The page needs the parsed durations, not the 67 MB workbook they came out
    of. This is that parse, already on disk as the service's own cache, cut to
    the branches the deployment reports on — which is the same restriction the
    service would apply on read anyway.
    """
    import pandas as pd

    src = RUNTIME / "storage" / "lead_time_observed"
    dst = BUNDLE / "runtime" / "storage" / "lead_time_observed"
    dst.mkdir(parents=True, exist_ok=True)

    lines = pd.read_parquet(src / "lines.parquet")
    before = len(lines)
    scoped = lines[lines["branch"].isin(branches)] if branches else lines
    scoped.to_parquet(dst / "lines.parquet", index=False)

    meta = json.loads((src / "meta.json").read_text(encoding="utf-8"))
    # The parse statistics describe the whole file and stay true of it — they
    # are what was read, not what is shipped. `extract` records the cut so the
    # page can say which it is holding.
    meta["extract"] = {
        "branches": sorted(branches),
        "lines_in_extract": int(len(scoped)),
        "lines_in_full_parse": int(before),
    }
    # The fingerprint named a workbook that is not in the bundle. Clearing it
    # is what tells the service this is a shipped extract rather than a cache
    # it may compare against a file and rebuild.
    meta.pop("fingerprint", None)
    (dst / "meta.json").write_text(json.dumps(meta, default=str), encoding="utf-8")

    return {
        "lines_in_full_parse": before,
        "lines_in_extract": int(len(scoped)),
        "branches": sorted(branches),
        "mb": round(_mb(dst / "lines.parquet"), 2),
    }


def _copy_source_files() -> dict[str, object]:
    src = PROJECT_ROOT / "data" / "source"
    dst = BUNDLE / "data" / "source"
    dst.mkdir(parents=True, exist_ok=True)
    shipped, withheld = [], []
    for path in sorted(p for p in src.iterdir() if p.is_file()):
        if path.name in SOURCE_FILES_SHIPPED:
            shutil.copy2(path, dst / path.name)
            shipped.append(f"{path.name} ({_mb(path):.2f} MB)")
        else:
            withheld.append(f"{path.name} ({_mb(path):.1f} MB)")
    return {"shipped": shipped, "withheld": withheld}


def main() -> int:
    from app.core.config import get_settings

    settings = get_settings()
    branches = list(settings.workspace_branches or [])
    skus = list(settings.workspace_skus or [])

    db = sqlite3.connect(f"file:{RUNTIME / 'db' / 'ais.db'}?mode=ro", uri=True)
    row = db.execute(
        "SELECT id, panel_build_id FROM training_run ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    if row is None:
        print("No training run in the database — nothing to bundle.")
        return 1
    live_run, panel_id = row
    preprocessing_id = db.execute(
        "SELECT preprocessing_run_id FROM panel_build WHERE id = ?", (panel_id,)
    ).fetchone()[0]
    db.close()

    print(f"live run          {live_run}")
    print(f"  panel build     {panel_id}")
    print(f"  preprocessing   {preprocessing_id}")
    print(f"  workspace       {len(branches)} branches, {len(skus)} SKUs")

    if BUNDLE.exists():
        shutil.rmtree(BUNDLE)
    BUNDLE.mkdir(parents=True)

    database = _copy_database(live_run)
    paths = _rewrite_paths(CONTAINER_ROOT)
    storage = _copy_storage(live_run, panel_id, preprocessing_id)
    lead_time = _copy_lead_time_extract(branches)
    sources = _copy_source_files()

    manifest = {
        "live_training_run": live_run,
        "panel_build": panel_id,
        "preprocessing_run": preprocessing_id,
        "workspace": {"branches": sorted(branches), "sku_count": len(skus)},
        "database": database,
        "stored_paths": paths,
        "storage": storage,
        "lead_time_extract": lead_time,
        "source_files": sources,
        "unavailable_on_this_deployment": [
            "Ingestion and preprocessing: the source workbooks are not deployed.",
            "Superseded training runs: only the live run is carried.",
        ],
        "total_mb": round(_mb(BUNDLE), 1),
    }
    (BUNDLE / "BUNDLE.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"\ndatabase      {database['mb_before_prune']} MB -> {database['mb_after_prune']} MB")
    print(
        f"              rewrote {len(paths['columns_rewritten'])} path columns and "
        f"{paths['manifests_rewritten']} manifests to {CONTAINER_ROOT}"
    )
    print(f"              dropped {database['runs_dropped']} superseded runs")
    for line in storage["skipped"]:
        print(f"  skipped     {line}")
    for line in storage["kept"]:
        print(f"  kept        {line}")
    print(
        f"lead time     {lead_time['lines_in_extract']:,} of "
        f"{lead_time['lines_in_full_parse']:,} order lines "
        f"({lead_time['mb']} MB)"
    )
    print(f"source files  shipped {sources['shipped']}")
    print(f"              withheld {len(sources['withheld'])} workbooks")
    print(f"\nbundle        {manifest['total_mb']} MB at {BUNDLE.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

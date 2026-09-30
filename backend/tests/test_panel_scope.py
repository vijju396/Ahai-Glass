"""The panel build is cut to the workspace before the grid is materialised.

The panel is a full branch x SKU x period grid, so building it unrestricted
materialises every series the extract contains. That was attempted once and
exhausted memory (docs/STATUS.md), and the workspace panel that replaced it was
produced by a script that was never committed - so the live panel could not be
rebuilt from this repository at all.

`_scope_artifacts` closes that: it cuts the preprocessed tables down to the
configured workspace and hands the builder the reduced set, which is what makes
a scoped build reproducible. These cover the cut itself rather than the build,
which is exercised end to end separately.
"""

from __future__ import annotations

import pandas as pd
import pytest

from app.domain.ais.workspace import (
    SOURCE_SETTING,
    UNRESTRICTED,
    WorkspaceScope,
)
from app.services.panel_service import _scope_artifacts


def _scope(branches=("BENGALURU",), skus=("FG.A", "FG.B")) -> WorkspaceScope:
    return WorkspaceScope(
        branches=tuple(branches) if branches else None,
        skus=tuple(skus) if skus else None,
        source=SOURCE_SETTING,
        detail="AIS_WORKSPACE_BRANCHES and AIS_WORKSPACE_SKUS",
    )


@pytest.fixture()
def artifacts(tmp_path):
    """One row per (branch, sku) combination across two branches and three SKUs."""
    rows = [
        {"canonical_branch": b, "canonical_sku": s, "period": "2025-W14", "ordered_qty": 1.0}
        for b in ("BENGALURU", "DELHI-1")
        for s in ("FG.A", "FG.B", "FG.C")
    ]
    order_fact = pd.DataFrame(rows)
    sales_fact = order_fact.copy()
    stock = order_fact.drop(columns=["period", "ordered_qty"]).copy()
    stock["closing_qty"] = 5.0
    branch_dim = pd.DataFrame({"canonical_branch": ["BENGALURU", "DELHI-1", "AGRA"]})
    product_dim = pd.DataFrame({"canonical_sku": ["FG.A", "FG.B", "FG.C", "FG.D"]})

    paths = {}
    for name, frame in (
        ("order_fact", order_fact),
        ("sales_fact", sales_fact),
        ("stock_position", stock),
        ("branch_dim", branch_dim),
        ("product_dim", product_dim),
    ):
        path = tmp_path / f"{name}.parquet"
        frame.to_parquet(path, index=False)
        paths[name] = str(path)
    return paths


def test_an_unrestricted_workspace_is_left_exactly_as_it_was(artifacts, tmp_path):
    """No restriction means no copy and no rewrite - the originals are used."""
    out, record = _scope_artifacts(artifacts, tmp_path / "build", UNRESTRICTED)

    assert out == artifacts
    assert record["applied"] is False
    assert not (tmp_path / "build" / "scoped_inputs").exists()


def test_both_axes_are_cut_from_the_fact_tables(artifacts, tmp_path):
    out, record = _scope_artifacts(artifacts, tmp_path / "build", _scope())

    order = pd.read_parquet(out["order_fact"])
    assert sorted(order["canonical_branch"].unique()) == ["BENGALURU"]
    assert sorted(order["canonical_sku"].unique()) == ["FG.A", "FG.B"]
    assert len(order) == 2
    assert record["tables"]["order_fact"] == {"rows_before": 6, "rows_after": 2}


def test_a_dimension_is_cut_on_its_own_axis_only(artifacts, tmp_path):
    """`product_dim` has no branch column; cutting it on branch would empty it."""
    out, _ = _scope_artifacts(artifacts, tmp_path / "build", _scope())

    products = pd.read_parquet(out["product_dim"])
    branches = pd.read_parquet(out["branch_dim"])
    assert sorted(products["canonical_sku"]) == ["FG.A", "FG.B"]
    assert sorted(branches["canonical_branch"]) == ["BENGALURU"]


def test_a_branch_only_workspace_keeps_every_sku(artifacts, tmp_path):
    out, _ = _scope_artifacts(artifacts, tmp_path / "build", _scope(skus=None))

    order = pd.read_parquet(out["order_fact"])
    assert sorted(order["canonical_sku"].unique()) == ["FG.A", "FG.B", "FG.C"]
    assert sorted(order["canonical_branch"].unique()) == ["BENGALURU"]


def test_a_sku_only_workspace_keeps_every_branch(artifacts, tmp_path):
    out, _ = _scope_artifacts(artifacts, tmp_path / "build", _scope(branches=None))

    order = pd.read_parquet(out["order_fact"])
    assert sorted(order["canonical_branch"].unique()) == ["BENGALURU", "DELHI-1"]
    assert sorted(order["canonical_sku"].unique()) == ["FG.A", "FG.B"]


def test_the_cut_is_case_insensitive(artifacts, tmp_path):
    """The setting is typed by an operator; `bengaluru` must not empty the panel."""
    scope = _scope(branches=("bengaluru",), skus=("fg.a",))
    out, _ = _scope_artifacts(artifacts, tmp_path / "build", scope)

    order = pd.read_parquet(out["order_fact"])
    assert len(order) == 1
    assert order.iloc[0]["canonical_branch"] == "BENGALURU"


def test_the_originals_are_never_written_to(artifacts, tmp_path):
    """Preprocessing output is shared by later builds; scoping must not mutate it."""
    before = {name: pd.read_parquet(path).shape for name, path in artifacts.items()}

    out, _ = _scope_artifacts(artifacts, tmp_path / "build", _scope())

    after = {name: pd.read_parquet(path).shape for name, path in artifacts.items()}
    assert after == before
    for name in ("order_fact", "product_dim"):
        assert out[name] != artifacts[name]


def test_the_record_names_the_workspace_it_applied(artifacts, tmp_path):
    """The manifest has to state the cut, not leave a reader to infer it."""
    _, record = _scope_artifacts(artifacts, tmp_path / "build", _scope())

    assert record["applied"] is True
    assert record["branches"] == ["BENGALURU"]
    assert record["skus"] == ["FG.A", "FG.B"]
    assert record["source"] == SOURCE_SETTING
    assert set(record["tables"]) == {
        "order_fact",
        "sales_fact",
        "stock_position",
        "branch_dim",
        "product_dim",
    }


def test_a_missing_table_is_skipped_rather_than_raising(tmp_path):
    """Not every preprocessing run writes every table; a gap is not a failure."""
    frame = pd.DataFrame(
        {"canonical_branch": ["BENGALURU"], "canonical_sku": ["FG.A"], "period": ["2025-W14"]}
    )
    path = tmp_path / "order_fact.parquet"
    frame.to_parquet(path, index=False)

    out, record = _scope_artifacts({"order_fact": str(path)}, tmp_path / "build", _scope())

    assert set(record["tables"]) == {"order_fact"}
    assert len(pd.read_parquet(out["order_fact"])) == 1

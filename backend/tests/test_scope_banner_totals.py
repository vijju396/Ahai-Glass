"""The scope banner's denominator is the network, not the slice.

Every panel-backed page carries a `workspace_scope` saying which slice it
shows - "2 of 53 branches, 136 of 2,063 SKUs". The denominator used to be
counted from the panel frame, but the panel *is* the workspace slice, so it
counted the numerator twice and every page read "2 of 2 branches, 136 of 136
SKUs": a sentence whose only job is to say what is hidden, saying nothing.

Found in the UI while checking the 136-SKU expansion, against a deployment
whose order book actually holds 53 branches and 2,063 SKUs.
"""

from __future__ import annotations

import pandas as pd
import pytest

from app.api.routes import analytics as routes
from app.domain.ais import analytics


@pytest.fixture()
def order_fact(tmp_path):
    """Three branches and four SKUs - the unrestricted universe."""
    frame = pd.DataFrame(
        {
            analytics.BRANCH_COL: ["BENGALURU", "DELHI-1", "AGRA", "AGRA"],
            analytics.SKU_COL: ["FG.A", "FG.B", "FG.C", "FG.D"],
            "ordered_qty": [1.0, 2.0, 3.0, 4.0],
        }
    )
    path = tmp_path / "order_fact.parquet"
    frame.to_parquet(path, index=False)
    routes._demand_universe_from.cache_clear()
    return str(path)


def test_the_universe_counts_the_whole_order_book(order_fact):
    assert routes._demand_universe_from(order_fact) == (3, 4)


def test_it_counts_distinct_values_not_rows(order_fact):
    """AGRA appears twice; a row count would report four branches."""
    branches, _ = routes._demand_universe_from(order_fact)

    assert branches == 3


def test_the_note_states_what_the_page_hides():
    """The regression in words: the reader has to be able to see the gap."""
    from app.domain.ais.workspace import SOURCE_SETTING, WorkspaceScope

    scope = WorkspaceScope(
        branches=("BENGALURU", "DELHI-1"),
        skus=tuple(f"FG.{n}" for n in range(136)),
        source=SOURCE_SETTING,
        detail="AIS_WORKSPACE_BRANCHES and AIS_WORKSPACE_SKUS",
    ).with_total(53, 2063)

    note = scope.note()
    assert "2 of 53 branches" in note
    assert "136 of 2063 SKUs" in note


def test_a_slice_sized_denominator_is_what_this_guards_against():
    """Totals taken from the scoped panel produce "136 of 136" - no gap shown."""
    from app.domain.ais.workspace import SOURCE_SETTING, WorkspaceScope

    scope = WorkspaceScope(
        branches=("BENGALURU", "DELHI-1"),
        skus=("FG.A", "FG.B"),
        source=SOURCE_SETTING,
        detail="AIS_WORKSPACE_BRANCHES and AIS_WORKSPACE_SKUS",
    ).with_total(2, 2)

    assert "2 of 2 branches" in scope.note()


def test_an_unknown_universe_drops_the_denominator_rather_than_failing(tmp_path):
    """A page must still say which slice it shows when the count is unavailable."""
    from app.domain.ais.workspace import SOURCE_SETTING, WorkspaceScope

    scope = WorkspaceScope(
        branches=("BENGALURU",),
        skus=("FG.A",),
        source=SOURCE_SETTING,
        detail="AIS_WORKSPACE_BRANCHES and AIS_WORKSPACE_SKUS",
    ).with_total(None, None)

    note = scope.note()
    assert "covers 1 branches (BENGALURU) and 1 SKUs." in note
    assert "not the national network" in note


def test_a_missing_artifact_returns_no_totals_instead_of_raising():
    """`_demand_universe` is called on every panel-backed page load."""

    class _NoRun:
        def scalars(self, _query):
            class _R:
                def first(self_inner):
                    return None

            return _R()

    assert routes._demand_universe(_NoRun()) == (None, None)


def test_an_unreadable_artifact_is_degraded_not_raised(tmp_path):
    """A corrupt parquet must not take every analytics page down with it."""
    bad = tmp_path / "broken.parquet"
    bad.write_text("not a parquet file", encoding="utf-8")

    class _Run:
        artifacts_json = {"order_fact": str(bad)}

    class _Db:
        def scalars(self, _query):
            class _R:
                def first(self_inner):
                    return _Run()

            return _R()

    routes._demand_universe_from.cache_clear()
    assert routes._demand_universe(_Db()) == (None, None)

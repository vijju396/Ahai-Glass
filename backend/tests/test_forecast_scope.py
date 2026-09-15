"""A forecast run covers the workspace, not the whole panel.

`build_aggregate_plan` derives its scopes from whatever panel it is handed, so
an unrestricted panel produced 1 national + 6 regions + 53 branches + 9
segments. On a two-branch workspace that meant 51 branch scopes with no
champion, appearing on no screen — and a national aggregate that summed 53
branches while only 2 were modelled, so reconciliation distributed a total
across scopes the run had not covered.

Measured before the fix: 318 branch forecast rows (53 branches x 6 horizons).
"""
from __future__ import annotations

import pandas as pd

from app.domain.ais.scope_builder import build_aggregate_plan
from app.domain.ais.workspace import SOURCE_SETTING, UNRESTRICTED, WorkspaceScope


def _panel() -> pd.DataFrame:
    rows = []
    for branch, region in (("AHMEDABAD", "WEST"), ("BENGALURU", "SOUTH-1"), ("CHENNAI", "SOUTH-2")):
        for sku in ("SKU-A", "SKU-B"):
            for month in range(1, 29):
                rows.append(
                    {
                        "series_id": f"{branch}|{sku}",
                        "canonical_branch": branch,
                        "canonical_sku": sku,
                        "region": region,
                        "zone": "ZONE",
                        "value_class": "A",
                        "product_group": "AIS GLASS",
                        "period_index": month,
                        "target": 100.0 + month,
                        "despatched_qty": 90.0 + month,
                        "shortfall_qty": 10.0,
                        "mean_mrp": 5.0,
                    }
                )
    return pd.DataFrame(rows)


def _levels(panel: pd.DataFrame) -> dict[str, int]:
    counts: dict[str, int] = {}
    for scope in build_aggregate_plan(panel).series:
        counts[scope.scope_level] = counts.get(scope.scope_level, 0) + 1
    return counts


def test_the_aggregate_plan_follows_the_panel_it_is_handed():
    """The mechanism behind the bug, stated directly."""
    assert _levels(_panel())["branch"] == 3


def test_restricting_the_panel_restricts_the_branch_scopes():
    scope = WorkspaceScope(
        branches=("AHMEDABAD", "BENGALURU"), source=SOURCE_SETTING, detail="test"
    )

    counts = _levels(scope.restrict(_panel(), "canonical_branch"))

    assert counts["branch"] == 2
    assert counts["national"] == 1


def test_a_region_with_no_branch_left_produces_no_scope():
    """SOUTH-2 exists only via CHENNAI, so it must disappear with it.

    Otherwise the hierarchy carries a region node with nothing beneath it and
    reconciliation has a row to distribute into that no branch supports.
    """
    scope = WorkspaceScope(
        branches=("AHMEDABAD", "BENGALURU"), source=SOURCE_SETTING, detail="test"
    )

    restricted = scope.restrict(_panel(), "canonical_branch")

    regions = {
        s.scope_key for s in build_aggregate_plan(restricted).series if s.scope_level == "region"
    }
    assert regions == {"WEST", "SOUTH-1"}


def test_the_national_aggregate_only_sums_the_branches_in_scope():
    """The reason this matters beyond tidiness.

    A national total over 53 branches, reconciled onto 2 modelled branches,
    would push demand that belongs elsewhere into those two.
    """
    scope = WorkspaceScope(
        branches=("AHMEDABAD", "BENGALURU"), source=SOURCE_SETTING, detail="test"
    )
    restricted = scope.restrict(_panel(), "canonical_branch")

    national = next(
        s for s in build_aggregate_plan(restricted).series if s.scope_level == "national"
    )
    branch_total = restricted["target"].sum()

    assert national.frame["target"].sum() == branch_total


def test_a_sku_restriction_also_narrows_the_plan():
    scope = WorkspaceScope(
        branches=None, skus=("SKU-A",), source=SOURCE_SETTING, detail="test"
    )
    restricted = scope.restrict(_panel(), "canonical_branch")

    national = next(
        s for s in build_aggregate_plan(restricted).series if s.scope_level == "national"
    )
    assert restricted["canonical_sku"].nunique() == 1
    assert national.frame["target"].sum() == restricted["target"].sum()


def test_an_unrestricted_workspace_forecasts_everything():
    panel = _panel()

    assert UNRESTRICTED.restrict(panel, "canonical_branch") is panel
    assert _levels(panel)["branch"] == 3

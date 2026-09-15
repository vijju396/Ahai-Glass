"""Scoping a training run to a few branches and SKUs.

A full run takes tens of minutes, which makes iterating on the models
impractical. `restrict_panel` cuts the panel first so that origins, plans,
cost and every count downstream describe the slice actually trained.

The property these tests care about most is honesty: a run over 2 of 53
branches must carry that fact with it, not look like a network result.
"""
from __future__ import annotations

import pandas as pd
import pytest

from app.domain.ais.scope_builder import restrict_panel


def _panel() -> pd.DataFrame:
    rows = []
    for branch in ("DELHI", "MUMBAI", "CHENNAI"):
        for sku in ("A", "B", "C", "D"):
            for month in range(1, 5):
                rows.append(
                    {
                        "series_id": f"{branch}|{sku}",
                        "canonical_branch": branch,
                        "canonical_sku": sku,
                        "period_index": month,
                        # A ranks highest, then B, then C, then D.
                        "target": {"A": 100, "B": 50, "C": 10, "D": 1}[sku],
                        "mean_mrp": 1.0,
                        "shortfall_qty": 0.0,
                    }
                )
    return pd.DataFrame(rows)


def test_it_keeps_only_the_named_branches():
    frame, applied = restrict_panel(_panel(), branches=["DELHI", "MUMBAI"])

    assert sorted(frame["canonical_branch"].unique()) == ["DELHI", "MUMBAI"]
    assert applied["branches_after"] == 2
    assert applied["panel_branches"] == 3


def test_it_matches_branch_names_case_insensitively():
    frame, _ = restrict_panel(_panel(), branches=["delhi"])

    assert list(frame["canonical_branch"].unique()) == ["DELHI"]


def test_it_reports_a_branch_that_is_not_in_the_panel():
    """A typo must not quietly train a narrower run than was asked for."""
    _, applied = restrict_panel(_panel(), branches=["DELHI", "MUMBIA"])

    assert applied["branches_unknown"] == ["MUMBIA"]
    assert any("MUMBIA" in note for note in applied["notes"])


def test_it_leaves_the_panel_whole_when_no_branch_matches():
    frame, applied = restrict_panel(_panel(), branches=["NOWHERE"])

    assert applied["branches_after"] == 3
    assert len(frame) == 48
    assert any("not applied" in note for note in applied["notes"])


def test_it_keeps_the_largest_skus_by_the_chosen_measure():
    _, applied = restrict_panel(_panel(), max_skus=2, measure="volume")

    assert applied["skus_after"] == 2


def test_it_ranks_skus_inside_the_branch_restriction():
    """The top SKUs *of the chosen branches*, not the top SKUs nationally.

    D is the smallest SKU everywhere except CHENNAI, where it dwarfs the rest.
    Restricting to CHENNAI must therefore keep D; ranking before the branch cut
    would have dropped it.
    """
    panel = _panel()
    chennai_d = (panel["canonical_branch"] == "CHENNAI") & (panel["canonical_sku"] == "D")
    panel.loc[chennai_d, "target"] = 10_000

    _, applied = restrict_panel(panel, branches=["CHENNAI"], max_skus=1, measure="volume")

    assert applied["skus_after"] == 1
    frame, _ = restrict_panel(panel, branches=["CHENNAI"], max_skus=1, measure="volume")
    assert list(frame["canonical_sku"].unique()) == ["D"]


def test_a_restricted_run_carries_a_warning_naming_what_it_covers():
    _, applied = restrict_panel(_panel(), branches=["DELHI"], max_skus=2)

    assert applied["is_restricted"] is True
    assert "1 of 3 branches" in applied["scope_warning"]
    assert "2 of 4 SKUs" in applied["scope_warning"]


def test_an_unrestricted_call_is_not_marked_restricted():
    frame, applied = restrict_panel(_panel())

    assert len(frame) == 48
    assert applied["is_restricted"] is False
    assert "scope_warning" not in applied


def test_it_rejects_an_unknown_measure():
    with pytest.raises(ValueError, match="not a selection measure"):
        restrict_panel(_panel(), max_skus=2, measure="profit")

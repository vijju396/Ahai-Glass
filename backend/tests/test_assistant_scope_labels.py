"""No tool may tell the model a two-branch figure covers the whole network.

The workspace cuts this deployment to BENGALURU and DELHI-1 with 136 SKUs, and
every analytics payload says so on `workspace_scope`. The assistant's tools did
not: `scope_note()` returned the literal string **"the whole network"** whenever
no branch or SKU was named in the question, and two tools hardcoded
`"national"` and `"national aggregate (the whole network summed per month)"`.

Those strings are handed to the model as facts, next to the numbers. So on
every call the model was told a two-branch total was a national one, while the
scope note in `caveats` said the opposite — and a model given two contradictory
facts will use either. The counts made it look plausible: 516 exception lines
and 261 replenishment rows read like a network, not like 272 series.

`scope_level == "national"` in the forecast and leaderboard tables is the name
of a **tier** in the hierarchy — the top of it — not a claim about the country.
The labels now say which.
"""

from __future__ import annotations

import pytest

from app.services.assistant import tools


class _Scope:
    """A restricted workspace, without touching a database."""

    is_restricted = True
    branches = ("BENGALURU", "DELHI-1")
    skus = tuple(f"FG.SKU{i:03d}" for i in range(136))


class _Unrestricted:
    is_restricted = False
    branches = None
    skus = None


@pytest.fixture
def restricted(monkeypatch):
    import app.domain.ais.workspace as workspace

    monkeypatch.setattr(workspace, "resolve_workspace", lambda db: _Scope())
    return object()


@pytest.fixture
def unrestricted(monkeypatch):
    import app.domain.ais.workspace as workspace

    monkeypatch.setattr(workspace, "resolve_workspace", lambda db: _Unrestricted())
    return object()


def test_an_unfiltered_question_never_reads_as_the_whole_network(restricted):
    """The exact regression: this string went to the model on every call."""
    note = tools.scope_note(None, restricted)

    assert "the whole network" not in note
    assert "this workspace only" in note
    assert "BENGALURU" in note and "DELHI-1" in note
    assert "136 SKU(s)" in note


def test_an_unrestricted_deployment_still_says_the_whole_network(unrestricted):
    """The fix must not invent a limit where there is none."""
    assert tools.scope_note(None, unrestricted) == "the whole network"


def test_a_named_branch_still_wins_over_the_workspace_phrase(restricted):
    """A question about one branch is already narrower than the workspace."""
    note = tools.scope_note({"branch": "DELHI-1"}, restricted)

    assert note == "branch DELHI-1"


def test_branch_sku_and_period_are_all_still_reported(restricted):
    note = tools.scope_note(
        {"branch": "DELHI-1", "sku": "FG.MP8.LFH.GCG2120000", "period": "2026-07"},
        restricted,
    )

    assert note == "branch DELHI-1, SKU FG.MP8.LFH.GCG2120000, period 2026-07"


def test_no_database_means_no_claim_either_way():
    """Called without a session, it must not assert a restriction it cannot read."""
    assert tools.scope_note(None, None) == "the whole network"
    assert tools.workspace_note(None) == ""


def test_a_workspace_that_cannot_be_resolved_does_not_break_the_tool(monkeypatch):
    """A label is never worth an exception on a page of real figures."""
    import app.domain.ais.workspace as workspace

    def boom(db):
        raise RuntimeError("no training run")

    monkeypatch.setattr(workspace, "resolve_workspace", boom)

    assert tools.workspace_note(object()) == ""
    assert tools.scope_note(None, object()) == "the whole network"


def test_the_tier_labels_name_a_tier_rather_than_a_country(restricted):
    """`scope_level == "national"` is the top of the hierarchy, not the nation."""
    phrase = tools._workspace_phrase(restricted)

    assert "this workspace only" in phrase
    assert "BENGALURU" in phrase


def test_the_source_carries_no_bare_network_claim_any_more():
    """A literal that says "the whole network" unconditionally is the bug."""
    from pathlib import Path

    source = Path(tools.__file__).read_text(encoding="utf-8")

    assert '"scope": "national"' not in source
    assert '"scope": "national aggregate (the whole network summed per month)"' not in source

"""The scope stamp must not eat a payload's `notes` when it is not a list.

Every analytics payload but one uses `notes` for a list of sentences, so
`_stamp` prepended the workspace sentence to it. The lead-time comparison
(D-105) uses `notes` for a dict of line counts instead, and the page reads
seven figures straight out of it — `lines_usable`, `lines_out_of_range`,
`worst_excluded_days` and the invoice-ordering split.

`_stamp` wrote `[note]` over that dict, so all seven arrived undefined and the
page printed empty tiles. The scope sentence was never needed there: it is
already on `workspace_scope.note`, which is the field `ScopeBanner` renders.
"""

from __future__ import annotations

from app.api.routes.analytics import _stamp
from app.domain.ais.workspace import WorkspaceScope


def _restricted() -> WorkspaceScope:
    scope = WorkspaceScope(
        branches=("BENGALURU", "DELHI-1"),
        skus=("FG.MP8.LFH.GCG2120000",),
        source="setting",
        detail="AIS_WORKSPACE_BRANCHES and AIS_WORKSPACE_SKUS",
    )
    assert scope.is_restricted
    assert scope.note()
    return scope


def test_a_dict_of_notes_survives_the_stamp():
    """The exact regression: seven figures went blank on the Lead Time page."""
    payload = {
        "branches": [],
        "notes": {
            "lines_total": 30_433,
            "lines_usable": 30_217,
            "lines_missing_a_date": 0,
            "lines_out_of_range": 216,
            "worst_excluded_days": 8_412,
            "invoice_rows": 29_901,
            "invoice_before_despatch": 11_960,
            "invoice_same_day": 6_402,
            "invoice_after_despatch": 11_539,
        },
    }

    stamped = _stamp(payload, _restricted())

    assert isinstance(stamped["notes"], dict)
    assert stamped["notes"]["lines_usable"] == 30_217
    assert stamped["notes"]["lines_out_of_range"] == 216
    assert stamped["notes"] == payload["notes"]


def test_the_scope_sentence_is_still_reachable_when_notes_is_a_dict():
    """Nothing is lost by leaving the dict alone - the banner reads this field."""
    stamped = _stamp({"notes": {"lines_total": 1}}, _restricted())

    assert stamped["workspace_scope"]["restricted"] is True
    assert stamped["workspace_scope"]["note"]
    assert "BENGALURU" in stamped["workspace_scope"]["note"]


def test_a_list_of_notes_still_gains_the_scope_sentence_first():
    """The behaviour every other analytics payload depends on is unchanged."""
    scope = _restricted()
    stamped = _stamp({"notes": ["Ordered quantity is the target."]}, scope)

    assert stamped["notes"][0] == scope.note()
    assert stamped["notes"][1] == "Ordered quantity is the target."


def test_a_payload_with_no_notes_gains_the_sentence():
    scope = _restricted()
    stamped = _stamp({"kpis": {}}, scope)

    assert stamped["notes"] == [scope.note()]


def test_the_sentence_is_never_added_twice():
    scope = _restricted()
    stamped = _stamp({"notes": [scope.note()]}, scope)

    assert stamped["notes"] == [scope.note()]


def test_an_unrestricted_workspace_leaves_notes_alone():
    scope = WorkspaceScope(branches=None, skus=None, source="unrestricted", detail="")
    payload = {"notes": ["Ordered quantity is the target."]}

    stamped = _stamp(payload, scope)

    assert stamped["notes"] == ["Ordered quantity is the target."]
    assert stamped["workspace_scope"]["restricted"] is False


def test_the_payload_itself_is_never_mutated():
    """`cached_summary` hands back the dict it holds; stamping in place poisoned it."""
    payload = {"notes": ["one"]}

    _stamp(payload, _restricted())

    assert payload["notes"] == ["one"]
    assert "workspace_scope" not in payload

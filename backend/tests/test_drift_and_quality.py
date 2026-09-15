"""Drift, its projection, and the guard on model-written prose.

Two defects motivate this file, both found by looking at the running app
rather than by a failing test.

`_stamp` appended the workspace note to the **cached** payload, so the page
grew one more identical note on every load — fifteen copies by the time it was
noticed.

And the first live drift explanation, written at temperature 2.0, came back as
four-language nonsense that would have rendered under the chart as though it
explained something.
"""
from __future__ import annotations

import pandas as pd
import pytest

from app.domain.ais import drift
from app.services.assistant import quality

GARBAGE = (
    "Drift shows how demand has changed compared to pastly observed sales and means "
    "average facts consumyac extrem acDemand unde ganho.solatu fortAshutadaastracted "
    "goverrtqeicaier Porուլի demandbuyakers फ whatsappialog القوة.Id.Offset july viac "
    "našem Committeebiased spot'm juvenileAdvice d"
)
GOOD = (
    "Drift compares the last 6 months against the 6 before them. For the whole "
    "workspace, recent demand averages 2871.0 units a month against 2502.8 earlier, "
    "which is 14.72% above the baseline. This is measured from the history, not "
    "predicted by a model."
)


def _monthly(values: list[float], start: str = "2024-04") -> pd.Series:
    year, month = (int(p) for p in start.split("-"))
    periods = []
    for _ in values:
        periods.append(f"{year:04d}-{month:02d}")
        month += 1
        if month > 12:
            month, year = 1, year + 1
    return pd.Series(values, index=periods)


# ----------------------------------------------------------------------
# The measurement
# ----------------------------------------------------------------------


def test_drift_needs_two_full_windows():
    out = drift.analyse(_monthly([100.0] * 11), scope_label="test")

    assert out["empty"] is True
    assert "at least 12 months" in out["reason"]


def test_a_flat_series_has_no_drift():
    out = drift.analyse(_monthly([100.0] * 24), scope_label="test")

    assert out["empty"] is False
    assert out["latest"]["shift_pct"] == 0.0
    assert out["latest"]["is_material"] is False


def test_a_step_up_is_measured_as_a_positive_shift():
    """The step shows where the windows span it, not afterwards.

    On 24 months stepping at month 13, the *last* window (19-24) and its
    baseline (13-18) are both post-step, so the latest shift is correctly
    0% - the drift has been absorbed. The +50% appears at the point whose
    windows sit either side of the step.
    """
    out = drift.analyse(_monthly([100.0] * 12 + [150.0] * 12), scope_label="test")
    shifts = [p["shift_pct"] for p in out["points"]]

    assert max(shifts) == pytest.approx(50.0, abs=0.01)
    assert out["latest"]["shift_pct"] == pytest.approx(0.0, abs=0.01)


def test_a_zero_baseline_is_skipped_rather_than_divided_by():
    """A shift from nothing has no percentage - it is undefined, not infinite."""
    out = drift.analyse(_monthly([0.0] * 12 + [100.0] * 12), scope_label="test")

    for point in out["points"]:
        assert point["baseline_mean"] != 0


def test_points_spanning_the_measurement_change_are_marked():
    out = drift.analyse(_monthly([100.0] * 28), scope_label="test")
    straddling = [p for p in out["points"] if p["straddles_measurement_change"]]

    assert straddling, "some window must span Apr 2025 on a 2024-04 start"


# ----------------------------------------------------------------------
# The projection, which mostly refuses
# ----------------------------------------------------------------------


def test_it_refuses_to_project_from_too_few_clean_points():
    out = drift.analyse(_monthly([100.0] * 24), scope_label="test")

    assert out["projection"]["projectable"] is False
    assert "measurement change" in out["projection"]["reason"]


def test_it_refuses_to_project_a_flat_trend():
    points = [
        drift.DriftPoint(f"2026-{m:02d}", 100.0, 100.0, 5.0, False) for m in range(1, 9)
    ]

    result = drift.project_next_crossing(points)

    assert result["projectable"] is False
    assert "flat or shrinking" in result["reason"]


def test_it_says_so_when_the_threshold_is_already_crossed():
    points = [
        drift.DriftPoint(f"2026-{m:02d}", 100.0, 100.0, 25.0 + m, False) for m in range(1, 9)
    ]

    result = drift.project_next_crossing(points)

    assert result["projectable"] is False
    assert result["already_crossed"] is True


def test_it_refuses_a_crossing_further_out_than_the_limit():
    # Rising 0.1pp a month from 5% needs 150 months to reach 20%.
    points = [
        drift.DriftPoint(f"2026-{m:02d}", 100.0, 100.0, 5.0 + 0.1 * m, False)
        for m in range(1, 9)
    ]

    result = drift.project_next_crossing(points)

    assert result["projectable"] is False
    assert "beyond the" in result["reason"]


def test_it_projects_a_crossing_when_the_trend_supports_one():
    # Rising 2pp a month and ending at 16%, below the 20% reading aid: four
    # points short of it, so a crossing is two months out.
    points = [
        drift.DriftPoint(f"2026-{m:02d}", 100.0, 100.0, 6.0 + 2.0 * m, False)
        for m in range(1, 6)
    ]

    result = drift.project_next_crossing(points)

    assert result["projectable"] is True
    assert result["months_ahead"] > 0
    # It must never present itself as a model forecast.
    assert "not a forecast from any of the 13" in result["basis"]


def test_every_payload_carries_the_measurement_change_caveat():
    out = drift.analyse(_monthly([100.0] * 24), scope_label="test")

    joined = " ".join(out["caveats"])
    assert "2025-04" in joined
    assert "change of measurement" in joined
    assert "not a forecast from any of the 13" in joined


# ----------------------------------------------------------------------
# The prose guard
# ----------------------------------------------------------------------


def test_it_rejects_the_output_that_actually_shipped():
    verdict = quality.check_explanation(GARBAGE, must_mention=("14.72",))

    assert verdict.ok is False
    assert verdict.reason


def test_it_accepts_a_clear_grounded_explanation():
    assert quality.check_explanation(GOOD, must_mention=("14.72",)).ok is True


def test_it_rejects_text_that_mentions_none_of_its_figures():
    """Fluent but ungrounded is the harder failure, and the more dangerous."""
    fluent = (
        "Demand has moved somewhat over the recent period, and this is worth keeping an "
        "eye on as the situation develops over the coming months ahead of the season."
    )

    verdict = quality.check_explanation(fluent, must_mention=("14.72",))

    assert verdict.ok is False
    assert "not grounded" in verdict.reason


def test_it_rejects_a_fragment():
    assert quality.check_explanation("Drift is up.").ok is False


def test_it_rejects_a_concatenation_artefact():
    text = (
        "Drift compares the last six months against the six before them for this scope "
        "and reports fortAshutadaastractedgoverrtqeicaierPordemandbuyakers as the result."
    )

    assert quality.check_explanation(text).ok is False


def test_it_allows_a_heavily_numeric_sentence():
    """Figures and units are not word-like; the bar must not reject them."""
    text = (
        "Recent demand averages 2871.0 units against 2502.8 earlier, a shift of 14.72% "
        "over 6 months, against a 20% reading aid on 17 measured points."
    )

    assert quality.check_explanation(text, must_mention=("14.72",)).ok is True


# ----------------------------------------------------------------------
# The cache-mutation bug
# ----------------------------------------------------------------------


def test_stamping_a_payload_does_not_mutate_it():
    """`_stamp` used to append to the cached dict it was handed.

    `cached_summary` returns the object it holds, so every request added
    another identical workspace note to it — fifteen copies on the page by
    the time it was noticed. Reading a cache must never change it.
    """
    from app.api.routes.analytics import _stamp
    from app.domain.ais.workspace import SOURCE_SETTING, WorkspaceScope

    scope = WorkspaceScope(
        branches=("AHMEDABAD",), source=SOURCE_SETTING, detail="test", total_branches=53
    )
    cached = {"notes": ["an original note"]}

    first = _stamp(cached, scope)
    second = _stamp(cached, scope)

    assert cached["notes"] == ["an original note"], "the cached payload was mutated"
    assert len(first["notes"]) == 2
    assert len(second["notes"]) == 2
    assert first["notes"] == second["notes"]


def test_stamping_twice_over_its_own_output_adds_no_second_copy():
    """Belt and braces: the note is guarded by content as well as by object."""
    from app.api.routes.analytics import _stamp
    from app.domain.ais.workspace import SOURCE_SETTING, WorkspaceScope

    scope = WorkspaceScope(branches=("AHMEDABAD",), source=SOURCE_SETTING, detail="test")

    once = _stamp({"notes": []}, scope)
    twice = _stamp(once, scope)

    assert twice["notes"] == once["notes"]


def test_an_unrestricted_scope_adds_no_note_and_still_reports_itself():
    from app.api.routes.analytics import _stamp
    from app.domain.ais.workspace import UNRESTRICTED

    stamped = _stamp({"notes": ["only mine"]}, UNRESTRICTED)

    assert stamped["notes"] == ["only mine"]
    assert stamped["workspace_scope"]["restricted"] is False

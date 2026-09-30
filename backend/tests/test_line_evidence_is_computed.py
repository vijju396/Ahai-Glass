"""A line's figures are the application's, in both passes, and they say something new.

Three defects on the AI Recommendations page, all of them about what a reader
sees next to a number (D-131).

1. **The chips came from the model.** `_merge_lines` copied the model's
   `evidence` array straight onto the card, and the model echoed the raw fact
   payload back at it: `q95 planning demand: 409.4224468979937`,
   `usable_stock: 0.0`, `is_censored: true`. Field names and sixteen decimal
   places, printed directly beneath a table of the same figures rounded.

2. **So the figures moved between the two passes.** The page renders the
   computed pass first and swaps in the written one, and it tells the reader
   the numbers do not change between them — only the sentences do, because the
   numbers were never the model's to produce. They did change: the fast pass
   showed `q95 planning demand = 409 units/month` and the written pass showed
   the sixteen-decimal echo of the same measurement.

3. **The chips repeated the table.** Every computed chip restated a row the
   card already prints. The exception join — short-despatched units, units
   ordered against zero stock — was carried on the payload and never rendered,
   so the only way it reached the screen was the model's raw echo.

The chips are now built by `_line_evidence` from the line's own fields, carry
what the table cannot, and are identical whoever wrote the prose.
"""

from __future__ import annotations

from app.services.assistant import recommendations as R

_LINE = {
    "scope_key": "BENGALURU|FG.BA5.LFH.GCG2120000",
    "branch": "BENGALURU",
    "sku": "FG.BA5.LFH.GCG2120000",
    "urgency": "critical",
    "urgency_reason": "No usable stock against a q95 planning demand of 2,644 units a month.",
    "service_level": 95,
    "point_forecast": 1180.0,
    "quantile_forecast": 2643.7312109,
    "usable_stock": 0.0,
    "on_order": 500.0,
    "backorders": 120.0,
    "days_of_cover": 0.0,
    "protection_period_days": 34.0,
    "recommended_order": 2953.7312,
    "model": "sarimax",
    "demand_segment": "smooth",
    "is_censored": True,
    "exceptions": [
        {"type": "Short despatch", "units": 368.0},
        {"type": "Zero stock, live demand", "units": 255.0},
    ],
}


def test_the_model_can_no_longer_put_a_figure_on_a_card():
    """The exact regression: a raw echo reaching the screen."""
    merged = R._merge_lines(
        [_LINE],
        [
            {
                "scope_key": _LINE["scope_key"],
                "explanation": "written by the model",
                "evidence": [
                    "q95 planning demand: 2643.7312109",
                    "usable_stock: 0.0",
                    "is_censored: true",
                ],
            }
        ],
    )

    evidence = merged[0]["evidence"]
    assert not any("2643.7312109" in chip for chip in evidence)
    assert not any("usable_stock" in chip for chip in evidence)
    assert not any(chip.endswith(": true") for chip in evidence)
    # The sentence is still the model's.
    assert merged[0]["explanation"] == "written by the model"
    assert merged[0]["written_by_model"] is True


def test_the_figures_are_identical_in_both_passes():
    """The page promises this. It was not true."""
    computed = R._merge_lines([_LINE], R._deterministic_lines([_LINE]), by_model=False)
    written = R._merge_lines(
        [_LINE],
        [{"scope_key": _LINE["scope_key"], "explanation": "prose", "evidence": ["anything"]}],
    )

    assert computed[0]["evidence"] == written[0]["evidence"]


def test_the_chips_carry_what_the_table_cannot():
    """Repeating a printed row spends attention on nothing."""
    evidence = R._line_evidence(_LINE)

    assert "Short despatch: 368 units" in evidence
    assert "Zero stock, live demand: 255 units" in evidence
    assert "already on order: 500 units" in evidence
    assert "backorders: 120 units" in evidence
    # The six figures the card's own table prints are not repeated here.
    assert not any("days of cover" in chip.lower() for chip in evidence)
    assert not any("protection period" in chip.lower() for chip in evidence)
    assert not any("recommended order" in chip.lower() for chip in evidence)


def test_a_censored_line_with_no_exception_row_still_says_so():
    """The badge is a claim; a reader looks for it among the figures."""
    line = _LINE | {"exceptions": []}

    assert "ordered quantity is a lower bound on demand" in R._line_evidence(line)


def test_an_uncensored_line_makes_no_censoring_claim():
    line = _LINE | {"exceptions": [], "is_censored": False}

    assert not any("lower bound" in chip for chip in R._line_evidence(line))


def test_a_line_with_nothing_extra_carries_no_chips():
    """An empty list, not a row of zeroes that would read as measurements."""
    bare = {
        "scope_key": "A|B",
        "branch": "A",
        "sku": "B",
        "urgency": "medium",
        "urgency_reason": "No order is recommended for this line at the current snapshot.",
        "exceptions": [],
        "is_censored": False,
        "on_order": 0.0,
        "backorders": None,
        "demand_segment": None,
    }

    assert R._line_evidence(bare) == []


def test_the_next_step_names_a_page_the_ui_actually_has():
    """Supply Intelligence was unrouted (D-105); this sent the reader nowhere."""
    written = R._deterministic_lines([_LINE])

    assert "Supply Intelligence" not in written[0]["next_step"]
    assert "Per Branch & SKU" in written[0]["next_step"]


def test_no_verify_on_label_names_an_unrouted_page():
    """Same defect on the network items: five labels, none a current tab."""
    labels = set(R.VERIFY_ON.values())

    assert not any("Supply Intelligence" in label for label in labels)
    assert not any("Operational Exceptions" in label for label in labels)
    assert R.VERIFY_ON["model_leaderboard"] == "Training"
    assert R.VERIFY_ON["forecast_outlook"] == "Forecasting"
    assert R.VERIFY_ON["data_quality"] == "Overall Analysis"


def test_the_line_prompt_no_longer_asks_the_model_for_figures():
    """Asking for something that is then discarded invites the model to try."""
    assert '"evidence"' not in R.LINE_SYSTEM_PROMPT
    assert "not the numbers" in R.LINE_SYSTEM_PROMPT


def test_the_exception_tally_counts_lines_on_this_page():
    """A chip that says 2 must filter to exactly 2 cards."""
    other = _LINE | {
        "scope_key": "DELHI-1|FG.X",
        "branch": "DELHI-1",
        "sku": "FG.X",
        "exceptions": [{"type": "Short despatch", "units": 100.0}],
    }
    tally = R._exception_tally([_LINE, other])

    assert tally[0] == {"label": "Short despatch", "lines": 2, "units": 468.0}
    assert {"label": "Zero stock, live demand", "lines": 1, "units": 255.0} in tally


def test_the_tally_is_ordered_by_how_many_lines_it_covers():
    tally = R._exception_tally([_LINE])

    assert [row["label"] for row in tally] == ["Short despatch", "Zero stock, live demand"]


def test_a_line_with_no_exception_contributes_nothing_rather_than_a_zero_row():
    assert R._exception_tally([_LINE | {"exceptions": []}]) == []

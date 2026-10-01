"""Accuracy and MAPE are both measured, and neither is derived from the other.

The screens print the two side by side. The tempting shortcut is to send one
and compute the other as `100 - x`, and it is wrong in exactly the place that
matters: `series_accuracy()` floors at zero, so a line whose six-month error is
340% reports 0.0% accuracy, and the subtraction would print "100.00% MAPE" —
a figure nobody measured, on the worst lines in the run (D-134).

Four of 261 lines floor on the six-month total and twenty on the single period,
so this is not a hypothetical.
"""

from __future__ import annotations

import statistics

from app.services.training.accuracy_windows import WindowScore


def _score(**series: list[float]) -> WindowScore:
    """A window carrying per-line error values directly.

    `by_series` is what both methods read, so filling it is enough to exercise
    the floor without standing up a run, its champions and its backtests.
    """
    score = WindowScore(
        label="A 6-month total", months=6, periods=26, grain="weekly", level="series"
    )
    for key, values in series.items():
        score.by_series[key] = list(values)
    return score


def test_accuracy_floors_at_zero_and_error_does_not() -> None:
    score = _score(blown=[340.0, 340.0], fine=[2.0, 4.0])

    assert score.series_accuracy()["blown"] == 0.0
    assert score.series_error()["blown"] == 340.0


def test_error_is_not_recoverable_from_the_floored_accuracy() -> None:
    """The specific lie this guards: 100 - 0 is 100, and the line is at 340."""
    score = _score(blown=[340.0])

    derived = 100.0 - score.series_accuracy()["blown"]
    assert derived == 100.0
    assert score.series_error()["blown"] != derived


def test_the_two_do_agree_wherever_nothing_was_floored() -> None:
    # Which is why the shortcut survives casual testing: on every line that is
    # not catastrophic, the subtraction gives the right answer.
    score = _score(ok=[10.0, 12.0], good=[1.0, 3.0])

    for key, accuracy in score.series_accuracy().items():
        assert round(100.0 - accuracy, 6) == round(score.series_error()[key], 6)


def test_error_is_the_median_of_the_line_s_own_blocks() -> None:
    # Not the mean, and not the best block. The median is what
    # `series_accuracy` subtracts from 100, so the two describe one reading.
    values = [4.0, 90.0, 12.0]
    score = _score(line=values)

    assert score.series_error()["line"] == statistics.median(values)


def test_a_line_with_no_scored_block_appears_in_neither() -> None:
    # An empty list is "not measured", which is a different state from an
    # error of zero and must not be reported as one.
    score = _score(empty=[], scored=[5.0])

    assert "empty" not in score.series_error()
    assert "empty" not in score.series_accuracy()
    assert score.series_error()["scored"] == 5.0

"""Unit tests for the planning-window scorer's new volume-weighted reading.

The endpoint that combines these into the demo's headline figure is exercised
live; here we pin the arithmetic that feeds it, which needs no database.
"""

from app.services.training.accuracy_windows import WindowScore


def _score() -> WindowScore:
    return WindowScore(label="A 6-month total", months=6, level="series")


def test_add_still_works_with_only_an_error_and_ignores_volume() -> None:
    # Backward compatible: the old two-argument call records the error and
    # simply contributes nothing to the volume totals.
    score = _score()
    score.add("BR|SKU", 10.0)
    assert score.blocks == [10.0]
    assert score.by_series == {"BR|SKU": [10.0]}
    assert score.pooled_wape() is None  # no actual volume seen


def test_pooled_wape_is_summed_error_over_summed_actual() -> None:
    score = _score()
    # Two lines: a big one off by 10 on 100, a small one off by 5 on 10.
    score.add("BIG|SKU", 10.0, abs_error=10.0, actual=100.0)
    score.add("SMALL|SKU", 50.0, abs_error=5.0, actual=10.0)
    # WAPE weights by volume: (10 + 5) / (100 + 10) = 13.6%, not the 30% the
    # unweighted median of the two error percentages would give.
    assert round(score.pooled_wape(), 2) == 13.64


def test_pooled_wape_none_when_nothing_scored() -> None:
    assert _score().pooled_wape() is None

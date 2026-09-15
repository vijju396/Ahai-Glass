"""Champion ranking rules, in isolation from the database.

The ranker is pure, so these are exact assertions rather than smoke tests. What
they pin down:

- the four ranking keys, in order, including the `model_id` tie-break that
  makes the champion reproducible between two identical runs,
- that a non-completed row is never ranked and never disappears,
- that `None` is never treated as a good score,
- that a baseline can win on WAPE and still not be champion, and that the
  leaderboard says so out loud,
- that a short-window model is excluded from the order rather than silently
  compared against a long-window one.
"""

from __future__ import annotations

import pytest

from app.ml.selection.champion import (
    MIN_VALIDATION_POINTS,
    Candidate,
    Ineligibility,
    compare_to_baseline,
    rank_candidates,
)


def _c(model_id: str, **kwargs) -> Candidate:
    """A completed candidate with ten validation points unless overridden.

    `mape` mirrors `wape` unless a test sets it explicitly. Most tests here
    exercise ranking *mechanics* — the bias tie-break, comparability gates,
    baseline handling — which are the same whichever metric ranks. Giving both
    metrics the same value keeps those tests independent of that choice, so
    only the tests that are genuinely about the metric have to name one.
    """
    base = {
        "display_name": model_id.upper(),
        "status": "completed",
        "evaluation_mode": "rolling_origin",
        "validation_points": 10,
        "distinct_test_points": 10,
        "origins_completed": 2,
        "origins_total": 2,
    }
    base.update(kwargs)
    base.setdefault("mape", base.get("wape"))
    return Candidate(model_id=model_id, **base)


class TestRankingOrder:
    def test_lowest_wape_wins(self) -> None:
        board = rank_candidates(
            [_c("sarimax", wape=12.0, mae=5.0), _c("xgboost", wape=8.0, mae=9.0)]
        )
        assert board.champion_model_id == "xgboost"
        assert board.challenger_model_id == "sarimax"

    def test_absolute_bias_breaks_a_wape_tie(self) -> None:
        board = rank_candidates(
            [
                _c("sarimax", wape=10.0, bias=-8.0, mae=5.0),
                _c("xgboost", wape=10.0, bias=2.0, mae=5.0),
            ]
        )
        assert board.champion_model_id == "xgboost"

    def test_bias_is_compared_by_magnitude_not_sign(self) -> None:
        """A large negative bias must not beat a small positive one."""
        board = rank_candidates(
            [
                _c("sarimax", wape=10.0, bias=-1.0, mae=5.0),
                _c("xgboost", wape=10.0, bias=4.0, mae=5.0),
            ]
        )
        assert board.champion_model_id == "sarimax"

    def test_mae_breaks_a_wape_and_bias_tie(self) -> None:
        board = rank_candidates(
            [
                _c("sarimax", wape=10.0, bias=1.0, mae=9.0),
                _c("xgboost", wape=10.0, bias=1.0, mae=4.0),
            ]
        )
        assert board.champion_model_id == "xgboost"

    def test_model_id_breaks_a_total_tie_deterministically(self) -> None:
        """Two runs over identical data must name the same champion."""
        rows = [
            _c("xgboost", wape=10.0, bias=1.0, mae=4.0),
            _c("sarimax", wape=10.0, bias=1.0, mae=4.0),
        ]
        first = rank_candidates(rows)
        second = rank_candidates(list(reversed(rows)))
        assert first.champion_model_id == second.champion_model_id == "sarimax"

    def test_a_missing_bias_never_wins_a_tie_break(self) -> None:
        """`None` is undefined, not zero - it must not read as perfect."""
        board = rank_candidates(
            [
                _c("sarimax", wape=10.0, bias=None, bias_abs=None, mae=4.0),
                _c("xgboost", wape=10.0, bias=3.0, mae=4.0),
            ]
        )
        assert board.champion_model_id == "xgboost"

    def test_a_missing_mae_never_wins_a_tie_break(self) -> None:
        board = rank_candidates(
            [
                _c("sarimax", wape=10.0, bias=1.0, mae=None),
                _c("xgboost", wape=10.0, bias=1.0, mae=99.0),
            ]
        )
        assert board.champion_model_id == "xgboost"

    def test_ranks_are_contiguous_from_one(self) -> None:
        board = rank_candidates(
            [_c("a", wape=3.0), _c("b", wape=2.0), _c("c", wape=1.0)]
        )
        assert [row.rank for row in board.rows if row.ranked] == [1, 2, 3]
        assert [row.candidate.model_id for row in board.rows[:3]] == ["c", "b", "a"]


class TestNothingIsHidden:
    def test_a_failed_model_appears_unranked_with_its_reason(self) -> None:
        board = rank_candidates(
            [
                _c("xgboost", wape=8.0),
                _c(
                    "lstm",
                    status="failed",
                    wape=None,
                    validation_points=0,
                    distinct_test_points=0,
                    failure_reason="ValueError: input contains NaN",
                ),
            ]
        )
        row = next(r for r in board.rows if r.candidate.model_id == "lstm")
        assert row.rank is None
        assert row.ranked is False
        assert row.exclusion == Ineligibility.NOT_COMPLETED.value
        assert row.exclusion_reason
        assert row.candidate.failure_reason == "ValueError: input contains NaN"

    def test_every_status_that_did_not_run_is_present_and_unranked(self) -> None:
        statuses = ["failed", "ineligible", "timed_out", "not_evaluated_budget"]
        board = rank_candidates(
            [_c("xgboost", wape=8.0)]
            + [
                _c(f"m_{status}", status=status, wape=None, distinct_test_points=0)
                for status in statuses
            ]
        )
        assert len(board.rows) == 5
        assert board.ranked_count == 1
        assert board.excluded_count == 4
        for status in statuses:
            row = next(r for r in board.rows if r.candidate.model_id == f"m_{status}")
            assert row.rank is None
            assert row.exclusion == Ineligibility.NOT_COMPLETED.value

    def test_a_completed_row_with_undefined_wape_is_excluded_not_zeroed(self) -> None:
        board = rank_candidates([_c("xgboost", wape=None), _c("sarimax", wape=5.0)])
        row = next(r for r in board.rows if r.candidate.model_id == "xgboost")
        assert row.exclusion == Ineligibility.NO_PRIMARY_METRIC.value
        assert row.candidate.wape is None
        assert board.champion_model_id == "sarimax"

    def test_no_rankable_row_yields_no_champion_rather_than_a_guess(self) -> None:
        board = rank_candidates(
            [
                _c("xgboost", status="ineligible", wape=None, distinct_test_points=0),
                _c("lstm", status="failed", wape=None, distinct_test_points=0),
            ]
        )
        assert board.champion_model_id is None
        assert board.ranked_count == 0
        assert any("no champion" in note.lower() or "No registered model" in note for note in board.notes)


class TestEvidenceThresholds:
    def test_too_few_validation_points_is_excluded(self) -> None:
        board = rank_candidates(
            [
                _c("xgboost", wape=8.0),
                _c(
                    "sarimax",
                    wape=1.0,
                    validation_points=MIN_VALIDATION_POINTS - 1,
                    distinct_test_points=MIN_VALIDATION_POINTS - 1,
                ),
            ]
        )
        row = next(r for r in board.rows if r.candidate.model_id == "sarimax")
        assert row.exclusion == Ineligibility.TOO_FEW_VALIDATION_POINTS.value
        # Its better WAPE must not have made it champion.
        assert board.champion_model_id == "xgboost"

    def test_a_much_shorter_window_in_the_same_mode_is_incomparable(self) -> None:
        board = rank_candidates(
            [
                _c("xgboost", wape=8.0, validation_points=10, distinct_test_points=10),
                _c("sarimax", wape=1.0, validation_points=4, distinct_test_points=4),
            ]
        )
        row = next(r for r in board.rows if r.candidate.model_id == "sarimax")
        assert row.exclusion == Ineligibility.INCOMPARABLE_TEST_WINDOW.value
        assert "4 of 10" in (row.comparability_note or "")
        assert board.champion_model_id == "xgboost"

    def test_a_fast_holdout_model_is_judged_against_its_own_mode(self) -> None:
        """D-037: `lstm` gets 6 points where rolling-origin models get 10. That
        is a labelled difference, not a disqualification."""
        board = rank_candidates(
            [
                _c("xgboost", wape=8.0, distinct_test_points=10),
                _c(
                    "lstm",
                    wape=6.0,
                    evaluation_mode="holdout_fast",
                    validation_points=6,
                    distinct_test_points=6,
                ),
            ]
        )
        lstm = next(r for r in board.rows if r.candidate.model_id == "lstm")
        assert lstm.ranked is True
        assert lstm.exclusion is None
        assert board.champion_model_id == "lstm"
        assert any("D-037" in note for note in board.notes)
        assert any("mixes evaluation modes" in note for note in board.notes)

    def test_a_failed_row_does_not_raise_the_comparability_bar(self) -> None:
        """A zero-point failed row must not become the yardstick."""
        board = rank_candidates(
            [
                _c("xgboost", wape=8.0, distinct_test_points=6),
                _c("lstm", status="failed", wape=None, distinct_test_points=0),
            ]
        )
        assert board.champion_model_id == "xgboost"


class TestBaselines:
    def test_a_baseline_is_never_champion_even_when_it_wins(self) -> None:
        board = rank_candidates(
            [
                _c("xgboost", wape=11.0),
                _c("ma6", wape=9.9, is_baseline=True),
            ]
        )
        assert board.champion_model_id == "xgboost"
        ma6 = next(r for r in board.rows if r.candidate.model_id == "ma6")
        assert ma6.is_champion is False
        assert ma6.rank is None
        assert ma6.exclusion == Ineligibility.IS_BASELINE.value

    def test_being_beaten_by_a_baseline_is_stated_plainly(self) -> None:
        board = rank_candidates(
            [
                _c("xgboost", wape=11.0),
                _c("ma6", wape=9.9, is_baseline=True),
                _c("naive", wape=12.0, is_baseline=True),
            ]
        )
        assert board.beaten_by_baseline is True
        assert board.best_baseline_model_id == "ma6"
        assert board.best_baseline_wape == 9.9
        note = " ".join(board.notes)
        assert "beats the champion" in note
        assert "not the best available forecast" in note

    def test_beating_every_baseline_sets_the_flag_false(self) -> None:
        board = rank_candidates(
            [_c("xgboost", wape=4.5), _c("ma6", wape=9.9, is_baseline=True)]
        )
        assert board.beaten_by_baseline is False
        assert not any("beats the champion" in note for note in board.notes)

    def test_baselines_are_ordered_among_themselves_for_reporting(self) -> None:
        board = rank_candidates(
            [
                _c("xgboost", wape=4.0),
                _c("ma3", wape=10.3, is_baseline=True),
                _c("ma6", wape=9.9, is_baseline=True),
            ]
        )
        assert board.best_baseline_model_id == "ma6"


class TestLegacyParityRanking:
    def test_the_legacy_ranking_is_computed_separately(self) -> None:
        """The two rankings can disagree, and both are returned."""
        board = rank_candidates(
            [
                _c("xgboost", wape=4.0, legacy_mape=80.0, legacy_valid=True),
                _c("sarimax", wape=9.0, legacy_mape=30.0, legacy_valid=True),
            ]
        )
        assert board.champion_model_id == "xgboost"
        assert board.legacy_champion_model_id == "sarimax"

    def test_a_row_the_references_would_reject_has_no_legacy_rank(self) -> None:
        board = rank_candidates(
            [
                _c("xgboost", wape=4.0, legacy_mape=None, legacy_valid=False),
                _c("sarimax", wape=9.0, legacy_mape=30.0, legacy_valid=True),
            ]
        )
        xgb = next(r for r in board.rows if r.candidate.model_id == "xgboost")
        assert xgb.legacy_rank is None
        assert xgb.rank == 1
        assert board.legacy_champion_model_id == "sarimax"

    def test_no_valid_legacy_row_yields_no_legacy_champion(self) -> None:
        board = rank_candidates([_c("xgboost", wape=4.0, legacy_valid=False)])
        assert board.legacy_champion_model_id is None
        assert board.champion_model_id == "xgboost"

    def test_a_baseline_never_takes_the_legacy_crown_either(self) -> None:
        board = rank_candidates(
            [
                _c("xgboost", wape=4.0, legacy_mape=80.0, legacy_valid=True),
                _c("ma6", wape=1.0, legacy_mape=1.0, legacy_valid=True, is_baseline=True),
            ]
        )
        assert board.legacy_champion_model_id == "xgboost"


class TestSkillScore:
    def test_a_better_champion_gives_a_positive_improvement(self) -> None:
        result = compare_to_baseline(4.5, 9.0)
        assert result["improvement_pct"] == 50.0
        assert result["champion_better"] is True

    def test_a_worse_champion_gives_a_negative_improvement(self) -> None:
        result = compare_to_baseline(12.0, 10.0)
        assert result["improvement_pct"] < 0
        assert result["champion_better"] is False

    def test_an_undefined_input_gives_none_and_says_why(self) -> None:
        for champion, baseline in ((None, 9.0), (4.0, None), (4.0, 0.0)):
            result = compare_to_baseline(champion, baseline)
            assert result["improvement_pct"] is None
            assert result["champion_better"] is None
            assert result["reason"]



class TestPrimaryMetricChoice:
    """Which metric ranks is configurable, and MAPE is the default.

    The reported accuracy is `100 - MAPE`, so ranking by MAPE keeps the
    leaderboard order and the headline number consistent. Ranking by one while
    reporting the other can put the model with the better accuracy second
    (docs/DECISIONS.md D-043).
    """

    def test_mape_is_the_default(self) -> None:
        from app.ml.selection.champion import DEFAULT_PRIMARY_METRIC

        assert DEFAULT_PRIMARY_METRIC == "mape"

    def test_the_two_metrics_can_pick_different_champions(self) -> None:
        # Measured on the real run: the champion differs in 40 of 166 scopes.
        rows = [
            _c("sarimax", wape=10.0, mape=20.0, bias=-1.0, mae=5.0),
            _c("xgboost", wape=12.0, mape=15.0, bias=-1.0, mae=6.0),
        ]
        assert rank_candidates(rows, primary_metric="mape").champion_model_id == "xgboost"
        assert rank_candidates(rows, primary_metric="wape").champion_model_id == "sarimax"

    def test_a_row_without_the_ranking_metric_is_excluded_not_ranked(self) -> None:
        board = rank_candidates(
            [_c("sarimax", wape=4.0, mape=None, bias=0.0, mae=1.0)], primary_metric="mape"
        )
        assert board.champion_model_id is None
        assert board.excluded_count == 1

    def test_an_unknown_metric_is_refused(self) -> None:
        with pytest.raises(ValueError, match="primary_metric must be one of"):
            rank_candidates([_c("sarimax", wape=1.0)], primary_metric="rmse")

    def test_a_baseline_is_compared_on_the_same_metric(self) -> None:
        # Comparing a MAPE-ranked champion against a WAPE-ranked baseline would
        # be comparing two different measurements.
        board = rank_candidates(
            [
                _c("sarimax", wape=5.0, mape=30.0, bias=1.0, mae=5.0),
                _c("ma6", wape=90.0, mape=20.0, bias=1.0, mae=9.0, is_baseline=True),
            ],
            primary_metric="mape",
        )
        assert board.champion_model_id == "sarimax"
        assert board.best_baseline_model_id == "ma6"
        # The baseline has the better MAPE, so it beats the champion on the
        # metric in use - and that must be said, not hidden.
        assert board.beaten_by_baseline is True
        assert any("MAPE" in note for note in board.notes)

    def test_bias_still_breaks_a_tie_on_the_primary_metric(self) -> None:
        # The tie-break matters more under MAPE, which is one-sided: between
        # two models it cannot separate, the less biased one should win.
        board = rank_candidates(
            [
                _c("sarimax", wape=1.0, mape=10.0, bias=-8.0, mae=5.0),
                _c("xgboost", wape=99.0, mape=10.0, bias=2.0, mae=5.0),
            ],
            primary_metric="mape",
        )
        assert board.champion_model_id == "xgboost"

    def test_the_setting_drives_the_service(self) -> None:
        from app.core.config import Settings

        assert Settings().champion_primary_metric == "mape"
        with pytest.raises(ValueError):
            Settings(champion_primary_metric="rmse")

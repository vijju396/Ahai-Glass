"""The sampling caveat fires where it should and stays quiet where it should not."""

from __future__ import annotations

import pandas as pd
import pytest

from app.domain.ais.representativeness import (
    MATERIAL_GAP_POINTS,
    AxisComparison,
    LevelComparison,
    analyse,
    compare_axis,
)


def _frame(rows):
    return pd.DataFrame(rows, columns=["glass_type", "target"])


class TestMateriality:
    def test_a_dominant_level_with_a_large_gap_is_material(self):
        """The regression that motivated the rule.

        Lam at 90.2% against 68.4% is a 21.7 point overstatement but only a
        1.3x ratio, because a level holding two thirds of the volume cannot
        have an extreme ratio. Requiring gap AND ratio silently excused the
        worst distortion on the page.
        """
        level = LevelComparison("Lam", sample_pct=90.2, branch_pct=68.4)
        assert level.ratio == pytest.approx(1.32, abs=0.01)
        assert level.material is True

    def test_a_collapsed_small_level_is_material_via_the_ratio(self):
        level = LevelComparison("Category C", sample_pct=0.3, branch_pct=16.3)
        assert level.material is True

    def test_a_tiny_level_with_an_extreme_ratio_stays_quiet(self):
        """0.2% against 0.1% is a 2x ratio on nothing."""
        level = LevelComparison("HIGH END", sample_pct=0.2, branch_pct=0.1)
        assert level.ratio == pytest.approx(2.0)
        assert level.material is False

    def test_a_matching_level_is_not_material(self):
        assert LevelComparison("A", sample_pct=50.0, branch_pct=50.0).material is False

    def test_the_gap_threshold_is_the_documented_one(self):
        just_under = LevelComparison("x", MATERIAL_GAP_POINTS - 0.1, 0.0)
        # No branch share means no ratio, so it falls back to the points test.
        assert just_under.material is True  # 4.9 >= the 2.0 minor floor
        assert LevelComparison("x", 1.0, 0.0).material is False


class TestAxis:
    def test_no_material_level_produces_no_caveat(self):
        axis = AxisComparison(
            column="glass_type",
            label="Glass",
            levels=[LevelComparison("Lam", 50.0, 50.0), LevelComparison("Side", 50.0, 50.0)],
        )
        assert axis.worst is None
        assert axis.caveat() is None

    def test_the_caveat_names_the_largest_material_gap(self):
        axis = AxisComparison(
            column="vehicle_age_category",
            label="Age",
            levels=[
                LevelComparison("Category Z", 54.9, 28.0),
                LevelComparison("Category C", 0.3, 16.3),
            ],
        )
        text = axis.caveat()
        assert text is not None
        assert "Category Z" in text
        assert "54.9%" in text and "28.0%" in text
        assert "2.0x" in text

    def test_a_missing_column_is_reported_not_silently_skipped(self):
        axis = compare_axis(
            pd.DataFrame({"target": [1.0]}),
            pd.DataFrame({"target": [1.0]}),
            "glass_type",
            "Glass",
            target="target",
        )
        assert axis.comparable is False
        assert axis.reason and "no glass_type column" in axis.reason

    def test_zero_demand_is_reported_rather_than_dividing_by_zero(self):
        axis = compare_axis(
            _frame([("Lam", 0.0)]), _frame([("Lam", 0.0)]), "glass_type", "Glass", target="target"
        )
        assert axis.comparable is False

    def test_unknown_levels_are_excluded_from_the_shares(self):
        axis = compare_axis(
            _frame([("Lam", 50.0), ("UNKNOWN", 50.0)]),
            _frame([("Lam", 100.0)]),
            "glass_type",
            "Glass",
            target="target",
        )
        levels = {level.level: level for level in axis.levels}
        assert "UNKNOWN" not in levels
        assert levels["Lam"].sample_pct == pytest.approx(100.0)


class TestAnalyse:
    def test_a_representative_sample_flags_nothing(self):
        same = _frame([("Lam", 60.0), ("Sidelite", 40.0)])
        out = analyse(same, same, target="target")
        assert out["material_axis_count"] == 0
        assert out["worst_axis"] is None
        assert out["axes"]["glass_type"]["caveat"] is None

    def test_a_distorted_sample_names_its_worst_axis(self):
        sample = _frame([("Lam", 90.0), ("Sidelite", 10.0)])
        reference = _frame([("Lam", 50.0), ("Sidelite", 50.0)])
        out = analyse(sample, reference, target="target")
        assert out["axes"]["glass_type"]["material"] is True
        assert out["worst_axis"] == "glass_type"

    def test_every_composition_axis_is_present_even_when_absent_from_the_panel(self):
        out = analyse(_frame([("Lam", 1.0)]), _frame([("Lam", 1.0)]), target="target")
        for column in ("glass_type", "vehicle_category", "vehicle_age_category", "value_class"):
            assert column in out["axes"]
        # The three the frame does not carry are reported as not comparable
        # rather than quietly reading as "no distortion".
        assert out["axes"]["vehicle_category"]["comparable"] is False

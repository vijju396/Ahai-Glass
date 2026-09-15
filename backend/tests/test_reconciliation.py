"""Hierarchical reconciliation.

Pure numerics, so the assertions are exact. What they pin down:

- coherence: every parent equals the sum of its children after reconciliation,
- non-negativity, and that clipping does not break the coherence it follows,
- that a method which cannot be computed falls back and **says which method it
  fell back from and why**, rather than proceeding on a covariance it could not
  estimate,
- that quantiles stay ordered `point <= q80 <= q90 <= q95` at every node,
- that a base series with no parent is grouped under `UNKNOWN` rather than
  dropped, so its demand still reaches the national total.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.ml.reconciliation.mint import (
    MIN_RESIDUALS_FOR_VARIANCE,
    Hierarchy,
    build_hierarchy,
    bottom_up,
    check_coherence,
    reconcile,
    reconcile_quantiles,
    shrink_covariance,
)


def _small_hierarchy() -> Hierarchy:
    """Four base series in two branches, one region, one national node."""
    return build_hierarchy(
        ["JAIPUR|A", "JAIPUR|B", "MUMBAI|A", "MUMBAI|B"],
        parents=[
            {"branch": "JAIPUR", "region": "NORTH-1"},
            {"branch": "JAIPUR", "region": "NORTH-1"},
            {"branch": "MUMBAI", "region": "WEST"},
            {"branch": "MUMBAI", "region": "WEST"},
        ],
    )


def _residuals(hierarchy: Hierarchy, rows: int = 12, seed: int = 42) -> np.ndarray:
    rng = np.random.default_rng(seed)
    base = rng.normal(0.0, 3.0, size=(rows, hierarchy.base_count))
    return np.hstack([base, base @ hierarchy.S[hierarchy.base_count :].T])


class TestHierarchyConstruction:
    def test_nodes_are_base_first_then_each_level(self) -> None:
        hierarchy = _small_hierarchy()
        assert hierarchy.base_count == 4
        levels = [level for level, _key in hierarchy.nodes]
        assert levels[:4] == ["series"] * 4
        assert levels[4:] == ["branch", "branch", "region", "region", "national"]

    def test_the_summing_matrix_sums_the_right_children(self) -> None:
        hierarchy = _small_hierarchy()
        base = np.array([10.0, 20.0, 30.0, 40.0])
        values = hierarchy.S @ base
        assert values[hierarchy.index_of("branch", "JAIPUR")] == 30.0
        assert values[hierarchy.index_of("branch", "MUMBAI")] == 70.0
        assert values[hierarchy.index_of("region", "NORTH-1")] == 30.0
        assert values[hierarchy.index_of("national", "NATIONAL")] == 100.0

    def test_a_series_with_no_parent_is_grouped_not_dropped(self) -> None:
        """Its demand must still reach the national total, and the gap must be
        visible as an UNKNOWN node."""
        hierarchy = build_hierarchy(
            ["A", "B"],
            parents=[{"branch": "JAIPUR", "region": "NORTH-1"}, {}],
        )
        base = np.array([10.0, 5.0])
        values = hierarchy.S @ base
        assert ("branch", "UNKNOWN") in hierarchy.nodes
        assert values[hierarchy.index_of("branch", "UNKNOWN")] == 5.0
        assert values[hierarchy.index_of("national", "NATIONAL")] == 15.0

    def test_a_mismatched_parent_list_is_refused(self) -> None:
        with pytest.raises(ValueError, match="every base series needs one"):
            build_hierarchy(["A", "B"], parents=[{"branch": "X"}])


class TestBottomUp:
    def test_it_is_coherent_by_construction(self) -> None:
        hierarchy = _small_hierarchy()
        values = bottom_up(hierarchy, [10.0, 20.0, 30.0, 40.0])
        coherent, worst = check_coherence(hierarchy, values)
        assert coherent
        assert worst == pytest.approx(0.0)

    def test_it_discards_the_aggregates_own_forecasts(self) -> None:
        hierarchy = _small_hierarchy()
        forecasts = [10.0, 20.0, 30.0, 40.0] + [999.0] * (hierarchy.node_count - 4)
        result = reconcile(hierarchy, forecasts, method="bottom_up")
        assert result.values[hierarchy.index_of("national", "NATIONAL")] == 100.0
        assert result.coherent
        assert any("sum of its base children" in note for note in result.notes)

    def test_the_adjustment_is_reported_not_folded_in(self) -> None:
        hierarchy = _small_hierarchy()
        forecasts = [10.0, 20.0, 30.0, 40.0] + [999.0] * (hierarchy.node_count - 4)
        result = reconcile(hierarchy, forecasts, method="bottom_up")
        national = hierarchy.index_of("national", "NATIONAL")
        assert result.base_values[national] == 999.0
        assert result.adjustments[national] == pytest.approx(100.0 - 999.0)

    def test_a_wrong_length_input_is_refused(self) -> None:
        hierarchy = _small_hierarchy()
        with pytest.raises(ValueError, match="hierarchy nodes"):
            reconcile(hierarchy, [1.0, 2.0], method="bottom_up")


class TestMinT:
    def test_variance_scaling_produces_a_coherent_result(self) -> None:
        hierarchy = _small_hierarchy()
        forecasts = np.array([10.0, 20.0, 30.0, 40.0, 31.0, 69.0, 31.0, 69.0, 101.0])
        result = reconcile(
            hierarchy,
            forecasts,
            method="mint_variance",
            residuals=_residuals(hierarchy),
        )
        assert result.method == "mint_variance"
        assert result.fallback_from is None
        assert result.coherent
        assert any("diagonal weight matrix" in note for note in result.notes)

    def test_shrinkage_produces_a_coherent_result_and_reports_its_intensity(
        self,
    ) -> None:
        hierarchy = _small_hierarchy()
        forecasts = np.array([10.0, 20.0, 30.0, 40.0, 31.0, 69.0, 31.0, 69.0, 101.0])
        result = reconcile(
            hierarchy,
            forecasts,
            method="mint_shrinkage",
            residuals=_residuals(hierarchy),
        )
        assert result.method == "mint_shrinkage"
        assert result.coherent
        assert result.shrinkage_intensity is not None
        assert 0.0 <= result.shrinkage_intensity <= 1.0

    def test_reconciliation_moves_the_incoherent_input_toward_agreement(self) -> None:
        """The base sums to 100 but the national forecast says 130; the
        reconciled national must land between the two, not stay at either."""
        hierarchy = _small_hierarchy()
        forecasts = np.array([10.0, 20.0, 30.0, 40.0, 30.0, 70.0, 30.0, 70.0, 130.0])
        result = reconcile(
            hierarchy,
            forecasts,
            method="mint_variance",
            residuals=_residuals(hierarchy),
        )
        national = result.values[hierarchy.index_of("national", "NATIONAL")]
        assert 100.0 < national < 130.0

    def test_an_already_coherent_input_is_left_essentially_alone(self) -> None:
        hierarchy = _small_hierarchy()
        base = np.array([10.0, 20.0, 30.0, 40.0])
        forecasts = hierarchy.S @ base
        result = reconcile(
            hierarchy,
            forecasts,
            method="mint_variance",
            residuals=_residuals(hierarchy),
        )
        assert np.allclose(result.values, forecasts, atol=1e-6)
        assert np.allclose(result.adjustments, 0.0, atol=1e-6)


class TestFallbacks:
    def test_no_residuals_falls_back_to_bottom_up_and_says_so(self) -> None:
        hierarchy = _small_hierarchy()
        forecasts = np.array([10.0, 20.0, 30.0, 40.0, 31.0, 69.0, 31.0, 69.0, 130.0])
        result = reconcile(hierarchy, forecasts, method="mint_shrinkage")
        assert result.method == "bottom_up"
        assert result.fallback_from == "mint_shrinkage"
        assert "no covariance" in result.fallback_reason
        assert result.coherent

    def test_too_few_residuals_falls_back_and_names_the_threshold(self) -> None:
        hierarchy = _small_hierarchy()
        forecasts = np.array([10.0, 20.0, 30.0, 40.0, 31.0, 69.0, 31.0, 69.0, 130.0])
        result = reconcile(
            hierarchy,
            forecasts,
            method="mint_variance",
            residuals=_residuals(hierarchy, rows=MIN_RESIDUALS_FOR_VARIANCE - 1),
        )
        assert result.method == "bottom_up"
        assert result.fallback_from == "mint_variance"
        assert str(MIN_RESIDUALS_FOR_VARIANCE) in result.fallback_reason

    def test_a_wrong_shaped_residual_matrix_is_refused_not_guessed(self) -> None:
        hierarchy = _small_hierarchy()
        forecasts = np.zeros(hierarchy.node_count)
        with pytest.raises(ValueError, match="columns for"):
            reconcile(
                hierarchy,
                forecasts,
                method="mint_variance",
                residuals=np.zeros((12, 3)),
            )

    def test_an_unknown_method_is_refused_with_the_valid_set(self) -> None:
        hierarchy = _small_hierarchy()
        with pytest.raises(ValueError, match="Unknown reconciliation method"):
            reconcile(hierarchy, np.zeros(hierarchy.node_count), method="magic")

    def test_no_reconciliation_says_the_levels_may_not_add_up(self) -> None:
        hierarchy = _small_hierarchy()
        forecasts = np.array([10.0, 20.0, 30.0, 40.0, 31.0, 69.0, 31.0, 69.0, 130.0])
        result = reconcile(hierarchy, forecasts, method="none")
        assert result.method == "none"
        assert result.coherent is False
        assert any("not guaranteed to add up" in note for note in result.notes)

    def test_proportional_splits_the_national_total_by_share(self) -> None:
        hierarchy = _small_hierarchy()
        forecasts = np.zeros(hierarchy.node_count)
        forecasts[hierarchy.index_of("national", "NATIONAL")] = 200.0
        result = reconcile(
            hierarchy,
            forecasts,
            method="proportional",
            historical_shares=[0.1, 0.2, 0.3, 0.4],
        )
        assert result.method == "proportional"
        assert np.allclose(result.values[:4], [20.0, 40.0, 60.0, 80.0])
        assert result.coherent

    def test_proportional_with_no_signal_at_all_splits_equally(self) -> None:
        """Nothing distinguishes the series, so an equal split is the only
        defensible answer - and it is still coherent."""
        hierarchy = _small_hierarchy()
        forecasts = np.zeros(hierarchy.node_count)
        forecasts[hierarchy.index_of("national", "NATIONAL")] = 100.0
        result = reconcile(
            hierarchy, forecasts, method="proportional", historical_shares=[0, 0, 0, 0]
        )
        assert np.allclose(result.values[:4], 25.0)
        assert result.coherent


class TestNonNegativity:
    def test_negative_base_forecasts_are_clipped_and_counted(self) -> None:
        hierarchy = _small_hierarchy()
        forecasts = np.array([-5.0, 20.0, 30.0, 40.0, 15.0, 70.0, 15.0, 70.0, 85.0])
        result = reconcile(
            hierarchy,
            forecasts,
            method="mint_variance",
            residuals=_residuals(hierarchy),
        )
        assert np.all(result.values >= 0.0)
        assert result.negatives_clipped >= 1
        assert any("clipped to zero" in note for note in result.notes)

    def test_clipping_does_not_break_coherence(self) -> None:
        """The parents are re-aggregated from the clipped children, so the
        hierarchy still adds up afterwards."""
        hierarchy = _small_hierarchy()
        forecasts = np.array([-5.0, 20.0, 30.0, 40.0, 15.0, 70.0, 15.0, 70.0, 85.0])
        result = reconcile(
            hierarchy,
            forecasts,
            method="mint_variance",
            residuals=_residuals(hierarchy),
        )
        assert result.coherent
        assert result.values[hierarchy.index_of("national", "NATIONAL")] == pytest.approx(
            float(np.sum(result.values[:4]))
        )

    def test_clipping_can_be_disabled_for_a_non_count_target(self) -> None:
        hierarchy = _small_hierarchy()
        forecasts = np.array([-5.0, 20.0, 30.0, 40.0, 15.0, 70.0, 15.0, 70.0, 85.0])
        result = reconcile(
            hierarchy,
            forecasts,
            method="bottom_up",
            enforce_non_negative=False,
        )
        assert result.negatives_clipped == 0
        assert result.values[0] < 0


class TestShrinkage:
    def test_intensity_is_clamped_into_the_unit_interval(self) -> None:
        rng = np.random.default_rng(7)
        residuals = rng.normal(size=(10, 5))
        for requested in (-3.0, 0.0, 0.4, 1.0, 9.0):
            _matrix, intensity = shrink_covariance(residuals, intensity=requested)
            assert 0.0 <= intensity <= 1.0

    def test_intensity_one_returns_the_diagonal(self) -> None:
        rng = np.random.default_rng(7)
        residuals = rng.normal(size=(20, 4))
        matrix, intensity = shrink_covariance(residuals, intensity=1.0)
        assert intensity == 1.0
        off_diagonal = matrix - np.diag(np.diag(matrix))
        assert np.allclose(off_diagonal, 0.0)

    def test_a_constant_series_gets_a_positive_variance_floor(self) -> None:
        """A zero variance would make the weight matrix singular and let the
        constant series dictate the whole projection."""
        residuals = np.column_stack(
            [np.random.default_rng(1).normal(size=20), np.zeros(20)]
        )
        matrix, _intensity = shrink_covariance(residuals)
        assert np.all(np.diag(matrix) > 0)

    def test_too_few_rows_returns_an_identity_rather_than_a_singular_matrix(
        self,
    ) -> None:
        matrix, intensity = shrink_covariance(np.zeros((1, 3)))
        assert matrix.shape == (3, 3)
        assert intensity == 1.0


class TestQuantileReconciliation:
    def test_the_ordering_holds_at_every_node(self) -> None:
        hierarchy = _small_hierarchy()
        point = hierarchy.S @ np.array([10.0, 20.0, 30.0, 40.0])
        quantiles = {
            "q80": point * 1.1,
            "q90": point * 1.2,
            "q95": point * 1.3,
        }
        output, report = reconcile_quantiles(hierarchy, point, quantiles)
        assert np.all(output["q80"] >= point - 1e-9)
        assert np.all(output["q90"] >= output["q80"] - 1e-9)
        assert np.all(output["q95"] >= output["q90"] - 1e-9)
        assert report["levels"] == ["q80", "q90", "q95"]

    def test_a_crossing_is_corrected_and_counted(self) -> None:
        hierarchy = _small_hierarchy()
        point = np.full(hierarchy.node_count, 10.0)
        # q90 deliberately below q80.
        quantiles = {
            "q80": np.full(hierarchy.node_count, 15.0),
            "q90": np.full(hierarchy.node_count, 12.0),
            "q95": np.full(hierarchy.node_count, 20.0),
        }
        output, report = reconcile_quantiles(hierarchy, point, quantiles)
        assert report["crossings_corrected"] == hierarchy.node_count
        assert np.all(output["q80"] <= output["q90"])
        assert np.all(output["q90"] <= output["q95"])

    def test_a_quantile_below_the_point_forecast_is_raised_to_it(self) -> None:
        hierarchy = _small_hierarchy()
        point = np.full(hierarchy.node_count, 50.0)
        quantiles = {"q80": np.full(hierarchy.node_count, 10.0)}
        output, _report = reconcile_quantiles(hierarchy, point, quantiles)
        assert np.all(output["q80"] == 50.0)

    def test_negative_quantiles_are_floored_at_zero(self) -> None:
        hierarchy = _small_hierarchy()
        point = np.zeros(hierarchy.node_count)
        quantiles = {"q80": np.full(hierarchy.node_count, -5.0)}
        output, _report = reconcile_quantiles(hierarchy, point, quantiles)
        assert np.all(output["q80"] >= 0.0)

    def test_a_wrong_length_quantile_is_refused(self) -> None:
        hierarchy = _small_hierarchy()
        with pytest.raises(ValueError, match="values for"):
            reconcile_quantiles(
                hierarchy, np.zeros(hierarchy.node_count), {"q80": np.zeros(2)}
            )


class TestCoherenceCheck:
    def test_an_incoherent_vector_is_detected(self) -> None:
        hierarchy = _small_hierarchy()
        values = hierarchy.S @ np.array([10.0, 20.0, 30.0, 40.0])
        values[hierarchy.index_of("national", "NATIONAL")] += 50.0
        coherent, worst = check_coherence(hierarchy, values)
        assert coherent is False
        assert worst == pytest.approx(50.0)

    def test_floating_point_noise_is_tolerated(self) -> None:
        hierarchy = _small_hierarchy()
        values = hierarchy.S @ np.array([10.0, 20.0, 30.0, 40.0])
        values[hierarchy.index_of("national", "NATIONAL")] += 1e-9
        coherent, _worst = check_coherence(hierarchy, values)
        assert coherent is True

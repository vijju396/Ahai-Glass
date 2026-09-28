"""Per branch x SKU recommendation lines: ranking, honesty, and the join.

The defect this replaces was not a crash. The page answered "50 branch x SKU
lines are flagged critical" — a count of lines, never a line — so a planner
could read the whole page and still not know what to order. These tests pin the
grain, and the three places where keeping the grain could still go wrong:
ranking that a model could reorder, a `cannot_recommend` line collapsing into a
zero, and written text landing on the wrong branch x SKU.
"""

from __future__ import annotations

from app.domain.ais import line_recommendations as L


def _item(**overrides):
    """A recommendation row as the inventory service returns one.

    `scope_key` is derived after the overrides rather than fixed, because two
    rows sharing a key is not a case the service produces and a fixture that
    invented one would test the wrong thing.
    """
    base = {
        "canonical_branch": "BENGALURU",
        "canonical_sku": "FG.AAA",
        "service_level": 95,
        "forecast_period": "2026-08",
        "forecast_model_id": "var_exog",
        "monthly_point_forecast": 100.0,
        "monthly_quantile_forecast": 200.0,
        "usable_stock_on_hand": 500.0,
        "confirmed_stock_on_order": 0.0,
        "backorders": 0.0,
        "days_of_cover": 60.0,
        "lead_time_days": 4.0,
        "protection_period_days": 34.0,
        "order_up_to_level": 300.0,
        "recommended_order": 0.0,
        "is_censored": False,
        "target_source": "order",
        "unavailable_reason": None,
    }
    merged = base | overrides
    merged.setdefault(
        "scope_key", f"{merged['canonical_branch']}|{merged['canonical_sku']}"
    )
    return merged


class TestUrgency:
    def test_no_usable_stock_against_live_demand_is_critical(self) -> None:
        line = L.build_lines([_item(usable_stock_on_hand=0.0)])[0]
        assert line["urgency"] == L.CRITICAL
        assert "No usable stock" in line["urgency_reason"]

    def test_cover_shorter_than_the_protection_period_is_high(self) -> None:
        """Stock runs out before a replenishment ordered today can arrive."""
        line = L.build_lines(
            [_item(days_of_cover=10.0, protection_period_days=34.0)]
        )[0]
        assert line["urgency"] == L.HIGH
        assert "before a replenishment" in line["urgency_reason"]

    def test_stock_is_tested_before_cover(self) -> None:
        """A zero-stock line whose cover is null must not fall through.

        Testing cover first would land this on `medium`, which is the quiet
        version of the failure this module exists to prevent.
        """
        line = L.build_lines([_item(usable_stock_on_hand=0.0, days_of_cover=None)])[0]
        assert line["urgency"] == L.CRITICAL

    def test_an_adequate_line_is_medium_not_absent(self) -> None:
        line = L.build_lines([_item(recommended_order=50.0)])[0]
        assert line["urgency"] == L.MEDIUM

    def test_an_unavailable_line_is_not_a_severity_and_not_a_zero(self) -> None:
        """`cannot_recommend` is the absence of a recommendation.

        It must not render as a mild severity, and the order must stay None
        rather than becoming zero — a recommended order of nothing is a
        different statement from no recommendation.
        """
        line = L.build_lines(
            [
                _item(
                    unavailable_reason="No active champion for this scope.",
                    recommended_order=None,
                )
            ]
        )[0]
        assert line["urgency"] == L.CANNOT_RECOMMEND
        assert line["recommended_order"] is None
        assert "No active champion" in line["urgency_reason"]


class TestRanking:
    def test_it_ranks_critical_above_high_above_medium(self) -> None:
        lines = L.build_lines(
            [
                _item(canonical_sku="FG.MED", recommended_order=10.0),
                _item(canonical_sku="FG.CRIT", usable_stock_on_hand=0.0),
                _item(canonical_sku="FG.HIGH", days_of_cover=1.0),
            ]
        )
        assert [line["sku"] for line in lines] == ["FG.CRIT", "FG.HIGH", "FG.MED"]

    def test_within_a_band_the_larger_order_comes_first(self) -> None:
        lines = L.build_lines(
            [
                _item(canonical_sku="FG.SMALL", usable_stock_on_hand=0.0, recommended_order=5.0),
                _item(canonical_sku="FG.BIG", usable_stock_on_hand=0.0, recommended_order=900.0),
            ]
        )
        assert [line["sku"] for line in lines] == ["FG.BIG", "FG.SMALL"]

    def test_a_null_order_sorts_last_rather_than_as_zero(self) -> None:
        lines = L.build_lines(
            [
                _item(canonical_sku="FG.NULL", usable_stock_on_hand=0.0, recommended_order=None),
                _item(canonical_sku="FG.ZERO", usable_stock_on_hand=0.0, recommended_order=0.0),
            ]
        )
        assert [line["sku"] for line in lines] == ["FG.ZERO", "FG.NULL"]

    def test_the_limit_trims_after_ranking_never_before(self) -> None:
        """Otherwise the cut would be decided by whatever order arrived."""
        lines = L.build_lines(
            [
                _item(canonical_sku="FG.MED", recommended_order=10.0),
                _item(canonical_sku="FG.CRIT", usable_stock_on_hand=0.0),
            ],
            limit=1,
        )
        assert [line["sku"] for line in lines] == ["FG.CRIT"]

    def test_counts_describe_the_whole_ranking(self) -> None:
        lines = L.build_lines(
            [
                _item(canonical_sku="FG.A", usable_stock_on_hand=0.0),
                _item(canonical_sku="FG.B", days_of_cover=1.0),
                _item(canonical_sku="FG.C", recommended_order=5.0),
            ]
        )
        assert L.counts(lines) == {
            L.CRITICAL: 1,
            L.HIGH: 1,
            L.MEDIUM: 1,
            L.CANNOT_RECOMMEND: 0,
        }


class TestHonesty:
    def test_a_censored_line_carries_its_censoring(self) -> None:
        """Ordered quantity is a lower bound there; the flag must survive."""
        line = L.build_lines([_item(is_censored=True)])[0]
        assert line["is_censored"] is True

    def test_it_copies_figures_and_never_recomputes_an_order(self) -> None:
        line = L.build_lines(
            [_item(recommended_order=1632.59, order_up_to_level=1632.59, usable_stock_on_hand=0.0)]
        )[0]
        assert line["recommended_order"] == 1632.59
        assert line["order_up_to_level"] == 1632.59

    def test_a_non_finite_figure_becomes_none_not_zero(self) -> None:
        line = L.build_lines([_item(days_of_cover=float("nan"))])[0]
        assert line["days_of_cover"] is None

    def test_exceptions_join_on_branch_and_sku(self) -> None:
        lines = L.build_lines(
            [_item(canonical_branch="BENGALURU", canonical_sku="FG.AAA")],
            exception_lines=[
                {"branch": "bengaluru", "sku": "fg.aaa", "label": "Short despatch", "units": 640},
                {"branch": "DELHI-1", "sku": "FG.AAA", "label": "Zero stock", "units": 12},
            ],
        )
        assert lines[0]["exceptions"] == [{"type": "Short despatch", "units": 640.0}]

    def test_a_line_with_no_exception_makes_no_claim_about_health(self) -> None:
        line = L.build_lines([_item()], exception_lines=[])[0]
        assert line["exceptions"] == []

    def test_a_row_without_a_branch_or_sku_is_dropped(self) -> None:
        """The grain is the whole point; a row with no grain is not a line."""
        assert L.build_lines([_item(canonical_sku="")]) == []


class TestMergeByKey:
    """Written text must attach to the line it names, never by position.

    A model that dropped, reordered or hallucinated a line would otherwise
    have its sentence silently printed against a different branch x SKU. That
    is the worst thing this page could do: a confident, well-evidenced
    paragraph about the wrong location.
    """

    def _ranked(self):
        return L.build_lines(
            [_item(canonical_sku="FG.AAA", usable_stock_on_hand=0.0), _item(canonical_sku="FG.BBB")]
        )

    def test_it_joins_on_scope_key_not_position(self) -> None:
        from app.services.assistant.recommendations import _merge_lines

        ranked = self._ranked()
        # Deliberately returned in the opposite order to the ranking.
        written = [
            {"scope_key": ranked[1]["scope_key"], "explanation": "about BBB", "evidence": []},
            {"scope_key": ranked[0]["scope_key"], "explanation": "about AAA", "evidence": []},
        ]
        merged = _merge_lines(ranked, written)
        assert merged[0]["sku"] == ranked[0]["sku"]
        assert merged[0]["explanation"] == "about AAA"
        assert merged[1]["explanation"] == "about BBB"

    def test_a_line_the_model_skipped_keeps_its_facts_and_says_so(self) -> None:
        from app.services.assistant.recommendations import _merge_lines

        ranked = self._ranked()
        merged = _merge_lines(
            ranked, [{"scope_key": ranked[0]["scope_key"], "explanation": "only this one"}]
        )
        assert len(merged) == 2
        assert merged[1]["written_by_model"] is False
        assert merged[1]["explanation"] is None
        # The computed reason survives whoever wrote the prose.
        assert merged[1]["urgency_reason"]

    def test_a_key_the_ranking_never_produced_is_ignored(self) -> None:
        from app.services.assistant.recommendations import _merge_lines

        ranked = self._ranked()
        merged = _merge_lines(ranked, [{"scope_key": "MADE|UP", "explanation": "invented"}])
        assert len(merged) == 2
        assert all(line["explanation"] is None for line in merged)

    def test_the_template_fallback_never_claims_a_model_wrote_it(self) -> None:
        from app.services.assistant.recommendations import (
            _deterministic_lines,
            _merge_lines,
        )

        ranked = self._ranked()
        merged = _merge_lines(ranked, _deterministic_lines(ranked), by_model=False)
        assert all(line["written_by_model"] is False for line in merged)
        assert all(line["explanation"] for line in merged)


class TestFastPass:
    """`prose=False` must be fast without being less accurate.

    The figures and the ranking were never the model's work, so skipping the
    model cannot change them. If it ever does, the fast pass has become a
    degraded pass and the page would be showing two different answers
    depending on how long someone waited.
    """

    def test_the_computed_pass_makes_no_model_call(self, monkeypatch) -> None:
        from app.services.assistant import llm, recommendations as R

        def explode(*_a, **_k):  # pragma: no cover - asserted by not being hit
            raise AssertionError("prose=False must not reach the provider")

        monkeypatch.setattr(llm, "client", explode)
        monkeypatch.setattr(R, "_gather", lambda db: {})
        monkeypatch.setattr(R, "_caveats", lambda db: [])
        monkeypatch.setattr(
            R, "_gather_lines", lambda db: (L.build_lines([_item(usable_stock_on_hand=0.0)]), {}, 1)
        )

        payload = R.generate(None, prose=False)

        assert payload["answered_by"] == "computed_only"
        assert payload["lines_answered_by"] == "computed_only"
        assert payload["lines"][0]["urgency"] == L.CRITICAL

    def test_the_fast_pass_carries_the_same_figures_as_a_written_one(
        self, monkeypatch
    ) -> None:
        from app.services.assistant import recommendations as R

        ranked = L.build_lines([_item(usable_stock_on_hand=0.0, recommended_order=1632.59)])
        monkeypatch.setattr(R, "_gather", lambda db: {})
        monkeypatch.setattr(R, "_caveats", lambda db: [])
        monkeypatch.setattr(R, "_gather_lines", lambda db: (ranked, {}, 1))

        fast = R.generate(None, prose=False)["lines"][0]

        # Whatever the model later writes, these are the numbers on the page.
        assert fast["recommended_order"] == 1632.59
        assert fast["urgency"] == L.CRITICAL
        assert fast["urgency_reason"]
        assert fast["written_by_model"] is False


class TestCache:
    def test_only_a_fully_model_written_pass_is_cached(self) -> None:
        """Caching a fallback would pin a provider blip in place for the TTL."""
        from app.services.assistant import recommendations as R

        R._CACHE.clear()
        R._store("k", {"answered_by": "deterministic_after_provider_error", "lines_answered_by": "openai"})
        assert R._cached("k") is None

        R._store("k", {"answered_by": "openai", "lines_answered_by": "openai"})
        assert R._cached("k") is not None

    def test_a_hit_says_it_is_one_and_how_old(self) -> None:
        from app.services.assistant import recommendations as R

        R._CACHE.clear()
        R._store("k", {"answered_by": "openai", "lines_answered_by": "openai"})
        hit = R._cached("k")
        assert hit["cached"] is True
        assert hit["cache_age_seconds"] >= 0

    def test_an_expired_entry_is_not_served(self, monkeypatch) -> None:
        from app.services.assistant import recommendations as R

        R._CACHE.clear()
        R._store("k", {"answered_by": "openai", "lines_answered_by": "openai"})
        monkeypatch.setattr(R, "CACHE_TTL_SECONDS", -1.0)
        assert R._cached("k") is None

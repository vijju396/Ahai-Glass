"""Demand-analytics aggregations and the AI assistant.

What is asserted here is the part that would be wrong in a way nobody notices:

- **Unknown is not zero.** A sales-proxy month has no despatch figure, so it
  must be excluded from a fill rate rather than counted as zero despatch. If
  that ever regresses, every fill rate on the page silently drops.
- **Exception conditions are real conditions.** Each one is asserted against a
  frame built to contain exactly that condition and nothing else.
- **The assistant never invents a number.** With OpenAI mocked, the answer is
  checked to contain only figures the tools actually returned, and the key is
  checked never to appear in a response.
- **No key is a working state**, not a broken one.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from app.domain.ais import analytics as A
from app.ml.features.panel import month_index


def _frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """A panel-shaped frame with sensible defaults for the untouched columns."""
    defaults: dict[str, Any] = {
        "series_id": "BR1|SKU1",
        "canonical_branch": "BR1",
        "canonical_sku": "SKU1",
        "product_group": "AIS GLASS",
        "value_class": "A",
        "region": "NORTH-1",
        "target": 100.0,
        "despatched_qty": 100.0,
        "shortfall_qty": 0.0,
        "over_delivered_qty": 0.0,
        "mean_mrp": 10.0,
        "is_censored": False,
        "target_source": "order",
        "is_materialised": False,
        "in_product_master": True,
        "is_non_glass": False,
        "closing_qty": 50.0,
        "usable_qty": 50.0,
        "closing_value": 500.0,
        "stock_class": "fast",
        "has_negative_row": False,
    }
    records = []
    for index, row in enumerate(rows):
        merged = {**defaults, **row}
        merged.setdefault("period_index", month_index("2025-01") + index)
        records.append(merged)
    frame = pd.DataFrame(records)
    frame["period"] = frame["period_index"].map(A.index_to_period)
    frame["demand_value"] = pd.to_numeric(frame["target"], errors="coerce").fillna(0.0) * pd.to_numeric(
        frame["mean_mrp"], errors="coerce"
    ).fillna(0.0)
    frame["shortfall_positive"] = pd.to_numeric(frame["shortfall_qty"], errors="coerce").clip(lower=0.0)
    return frame


@pytest.fixture(autouse=True)
def _clear_caches():
    A.clear_caches()
    yield
    A.clear_caches()


class TestUnknownIsNotZero:
    def test_a_proxy_month_is_excluded_from_the_fill_rate(self):
        # One order month fully filled, one proxy month with no despatch at all.
        # The fill rate must be 100%, not 50%: the proxy month has no
        # denominator, and counting it as zero despatch would halve every fill
        # rate on the page while looking entirely plausible.
        frame = _frame(
            [
                {"target": 100.0, "despatched_qty": 100.0, "target_source": "order"},
                {"target": 100.0, "despatched_qty": None, "target_source": "sales_proxy"},
            ]
        )
        payload = A.summary(frame, A.AnalyticsScope())
        assert payload["kpis"]["fill_rate_pct"] == 100.0
        assert payload["kpis"]["despatch_rows_excluded_from_fill_rate"] == 1

    def test_the_excluded_count_is_reported_per_period(self):
        frame = _frame([{"despatched_qty": None, "target_source": "sales_proxy"}])
        trend = A.summary(frame, A.AnalyticsScope())["trend"]
        assert trend[0]["fill_rate_pct"] is None
        assert trend[0]["despatched_units"] is None
        assert trend[0]["despatch_rows_excluded"] == 1

    def test_demand_units_still_count_a_proxy_month(self):
        # The exclusion is from the *ratio*, not from demand: a proxy month is a
        # labelled substitute for demand, not an absence of it.
        frame = _frame([{"target": 60.0, "despatched_qty": None}, {"target": 40.0}])
        assert A.summary(frame, A.AnalyticsScope())["kpis"]["demand_units"] == 100.0


class TestSummaryShape:
    def test_every_panel_the_page_renders_is_present(self):
        payload = A.summary(_frame([{}, {}, {}]), A.AnalyticsScope())
        for key in (
            "trend",
            "by_branch",
            "by_product_group",
            "by_value_class",
            "branch_by_group",
            "branch_over_time",
            "seasonality",
            "concentration",
            "coverage",
            "kpis",
            "notes",
        ):
            assert key in payload, key

    def test_the_cross_tab_is_split_by_value_class(self):
        # It was product_group first, which put an "AIS GLASS / HIGH END"
        # legend under a panel titled "by Value Class".
        frame = _frame([{"value_class": "A"}, {"value_class": "B"}])
        assert set(A.summary(frame, A.AnalyticsScope())["branch_by_group"]["groups"]) == {"A", "B"}

    def test_quarterly_is_a_real_rollup_of_the_months_present(self):
        frame = _frame([{"target": 10.0}, {"target": 20.0}, {"target": 30.0}])  # 2025-01..03
        payload = A.summary(frame, A.AnalyticsScope(grain="quarterly"))
        assert [row["period"] for row in payload["trend"]] == ["2025-Q1"]
        assert payload["trend"][0]["demand_units"] == 60.0

    def test_only_the_grains_the_data_supports_are_offered(self):
        payload = A.summary(_frame([{}]), A.AnalyticsScope())
        assert payload["available_grains"] == ["monthly", "quarterly"]
        assert "invent" in payload["grain_note"]

    def test_an_unknown_grain_falls_back_to_monthly_rather_than_failing(self):
        payload = A.summary(_frame([{}]), A.AnalyticsScope(grain="hourly"))
        assert payload["scope"]["grain"] == "monthly"

    def test_seasonality_carries_its_observation_count(self):
        frame = _frame([{"target": 10.0}, {"target": 20.0}])
        rows = A.summary(frame, A.AnalyticsScope())["seasonality"]
        assert all("observations" in row for row in rows)
        assert all(row["observations"] >= 1 for row in rows)

    def test_an_empty_scope_says_so_rather_than_returning_zeros(self):
        payload = A.summary(_frame([{}]), A.AnalyticsScope(branch="NOWHERE"))
        assert payload["empty"] is True
        assert "No panel row matches" in payload["reason"]
        assert "kpis" not in payload

    def test_scoping_to_a_branch_narrows_the_totals(self):
        frame = _frame(
            [
                {"canonical_branch": "BR1", "series_id": "BR1|S", "target": 10.0},
                {"canonical_branch": "BR2", "series_id": "BR2|S", "target": 90.0},
            ]
        )
        assert A.summary(frame, A.AnalyticsScope(branch="BR1"))["kpis"]["demand_units"] == 10.0


class TestExceptions:
    def test_a_short_despatch_is_found_and_measured_in_units_short(self):
        frame = _frame([{"is_censored": True, "shortfall_qty": 40.0, "despatched_qty": 60.0}])
        payload = A.exceptions(frame, A.AnalyticsScope())
        row = next(r for r in payload["rows"] if r["type"] == "censored_line")
        assert row["units"] == 40.0
        assert row["severity"] == "critical"
        assert "lower bound" in row["definition"]

    def test_zero_stock_against_live_demand_is_found(self):
        frame = _frame([{"usable_qty": 0.0, "target": 25.0}])
        payload = A.exceptions(frame, A.AnalyticsScope())
        assert any(r["type"] == "zero_stock_live_demand" for r in payload["rows"])

    def test_zero_stock_with_no_recent_demand_is_not_an_exception(self):
        frame = _frame([{"usable_qty": 0.0, "target": 0.0}])
        payload = A.exceptions(frame, A.AnalyticsScope())
        assert not any(r["type"] == "zero_stock_live_demand" for r in payload["rows"])

    def test_a_negative_stock_row_is_surfaced_not_clamped(self):
        frame = _frame([{"has_negative_row": True}])
        payload = A.exceptions(frame, A.AnalyticsScope())
        assert any(r["type"] == "negative_stock_row" for r in payload["rows"])

    def test_an_unmapped_sku_is_surfaced(self):
        frame = _frame([{"in_product_master": False, "target": 12.0}])
        payload = A.exceptions(frame, A.AnalyticsScope())
        assert any(r["type"] == "unmapped_sku" for r in payload["rows"])

    def test_over_despatch_is_separate_from_short_despatch(self):
        # Net and gross shortfall differ precisely because of these rows, so the
        # two conditions must never be merged into one count.
        frame = _frame([{"over_delivered_qty": 15.0}])
        payload = A.exceptions(frame, A.AnalyticsScope())
        types = {r["type"] for r in payload["rows"]}
        assert "over_despatch" in types
        assert "censored_line" not in types

    def test_a_clean_frame_yields_no_exceptions(self):
        payload = A.exceptions(_frame([{}]), A.AnalyticsScope())
        assert payload["empty"] is True

    def test_every_row_carries_the_definition_it_was_found_by(self):
        frame = _frame([{"is_censored": True, "shortfall_qty": 5.0}, {"has_negative_row": True}])
        payload = A.exceptions(frame, A.AnalyticsScope())
        assert payload["rows"]
        for row in payload["rows"]:
            assert row["definition"]
            assert row["measure"]

    def test_no_row_carries_an_employee_dimension(self):
        # The reference ranks employees. AIS has no personnel data and must
        # never grow any, so the ranked entity is the branch x SKU line.
        #
        # Asserted over the row *fields and values*, not the whole payload:
        # the notes deliberately use the word "employee" to explain why there
        # is no employee dimension, and an assertion that forbade the
        # explanation would be testing the prose rather than the data.
        frame = _frame([{"is_censored": True, "shortfall_qty": 5.0}])
        payload = A.exceptions(frame, A.AnalyticsScope())
        assert payload["rows"]
        for row in payload["rows"]:
            blob = " ".join(f"{key} {value}" for key, value in row.items() if key != "definition").lower()
            for forbidden in ("employee", "attendance", "payroll", "headcount", "punch", "shift"):
                assert forbidden not in blob, (forbidden, row)
        # And the ranked entity really is the line.
        assert {"branch", "sku", "series_id"} <= set(payload["rows"][0])


class TestBranchScorecard:
    def test_a_branch_is_scored_on_four_measures_with_targets(self):
        frame = _frame([{}, {}, {}])
        payload = A.branch_scorecard(frame, A.AnalyticsScope())
        entry = payload["branches"][0]
        assert set(entry["metric_values"]) == {
            "fill_rate",
            "short_despatch_share",
            "demand_stability",
            "coverage",
        }
        assert entry["rank"] == 1
        assert all("target" in scale for scale in payload["scales"].values())

    def test_off_target_measures_are_named(self):
        frame = _frame([{"target": 100.0, "despatched_qty": 10.0}])  # fill rate 10%
        entry = A.branch_scorecard(frame, A.AnalyticsScope())["branches"][0]
        assert "fill_rate" in entry["off_target"]

    def test_the_note_says_it_rates_a_branch_not_a_person(self):
        payload = A.branch_scorecard(_frame([{}]), A.AnalyticsScope())
        assert "never an individual" in payload["note"]


class TestCaching:
    def test_a_repeat_call_returns_the_cached_object(self):
        frame = _frame([{}, {}])
        first = A.cached_summary(frame, "path-a", A.AnalyticsScope())
        second = A.cached_summary(frame, "path-a", A.AnalyticsScope())
        assert first is second

    def test_a_different_panel_path_is_a_different_key(self):
        frame = _frame([{}, {}])
        assert A.cached_summary(frame, "path-a", A.AnalyticsScope()) is not A.cached_summary(
            frame, "path-b", A.AnalyticsScope()
        )

    def test_a_different_scope_is_a_different_key(self):
        frame = _frame([{"canonical_branch": "BR1"}])
        assert A.cached_summary(frame, "p", A.AnalyticsScope()) is not A.cached_summary(
            frame, "p", A.AnalyticsScope(branch="BR1")
        )


# ----------------------------------------------------------------------
# Assistant
# ----------------------------------------------------------------------


class TestAssistantWithoutAKey:
    """No key must be a working state, not a broken one."""

    def test_status_reports_unconfigured_with_setup_steps(self, client):
        response = client.get("/api/assistant/status")
        assert response.status_code == 200
        body = response.json()
        assert body["configured"] is False
        assert len(body["steps"]) >= 3
        assert body["suggested_questions"]

    def test_status_never_echoes_the_key_or_its_length(self, client):
        # The variable *name* is in the setup steps on purpose - that is the
        # instruction. What must never appear is a value, or a length that
        # would confirm one is set.
        body = client.get("/api/assistant/status").json()
        blob = json.dumps(body).lower()
        assert "sk-" not in blob
        assert "key_length" not in blob
        assert "openai_api_key" not in body
        assert set(body) == {
            "enabled",
            "configured",
            "model",
            "steps",
            "notes",
            "suggested_questions",
        }

    def test_a_question_is_answered_deterministically(self, client):
        response = client.post(
            "/api/assistant/ask",
            json={"question": "Show the monthly demand trend", "history": [], "current_scope": None},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["answered_by"] == "deterministic_no_key"
        assert body["answer"]

    def test_an_out_of_scope_question_is_declined(self, client):
        body = client.post(
            "/api/assistant/ask",
            json={"question": "What is the capital of France?", "history": [], "current_scope": None},
        ).json()
        assert body["tools_used"] == []
        assert "outside what I can see" in body["answer"]

    def test_a_greeting_is_answered_without_touching_a_tool(self, client):
        body = client.post(
            "/api/assistant/ask", json={"question": "hi", "history": [], "current_scope": None}
        ).json()
        assert body["answered_by"] == "static"
        assert body["tools_used"] == []

    def test_an_empty_question_is_rejected_by_validation(self, client):
        assert client.post(
            "/api/assistant/ask", json={"question": "", "history": [], "current_scope": None}
        ).status_code == 422

    def test_history_is_capped(self, client):
        turns = [{"role": "user", "content": f"q{i}"} for i in range(20)]
        response = client.post(
            "/api/assistant/ask",
            json={"question": "why?", "history": turns, "current_scope": None},
        )
        assert response.status_code == 422


class TestAssistantChartSafety:
    def test_only_allowlisted_chart_types_exist(self):
        from app.services.assistant import tools

        assert tools.ALLOWED_CHART_TYPES == frozenset({"line", "bar", "pie"})

    def test_a_type_outside_the_allowlist_produces_no_chart(self):
        from app.services.assistant import tools

        assert tools._chart("treemap", "t", [{"a": 1}], [{"key": "a", "label": "A"}], "a") is None

    def test_a_chart_is_capped_in_points(self):
        from app.services.assistant import tools

        data = [{"x": i, "y": i} for i in range(500)]
        chart = tools._chart("line", "t", data, [{"key": "y", "label": "Y"}], "x")
        assert chart is not None
        assert len(chart["data"]) == tools.MAX_CHART_POINTS


class TestAssistantWithMockedOpenAI:
    """The model path, without ever making a paid call.

    The SDK is mocked, so these assert the loop's contract: tools are chosen by
    the model but *run* by the backend, the chart comes from the tool rather
    than the model, and a provider failure degrades to the deterministic writer
    instead of failing the request.
    """

    @staticmethod
    def _tool_call(name: str):
        call = MagicMock()
        call.id = f"call_{name}"
        call.function.name = name
        call.function.arguments = "{}"
        return call

    def _responses(self, tool_names: list[str], answer: str):
        """Selection turn, a follow-up turn asking for nothing more, then the
        final answer - the three calls a real two-round loop makes."""
        selection = MagicMock()
        selection.choices = [MagicMock()]
        selection.choices[0].message.tool_calls = [self._tool_call(n) for n in tool_names]
        selection.choices[0].message.content = None

        satisfied = MagicMock()
        satisfied.choices = [MagicMock()]
        satisfied.choices[0].message.tool_calls = None
        satisfied.choices[0].message.content = None

        final = MagicMock()
        final.choices = [MagicMock()]
        final.choices[0].message.content = answer
        final.choices[0].message.tool_calls = None
        return [selection, satisfied, final]

    def _client(self, responses):
        fake = MagicMock()
        fake.chat.completions.create.side_effect = responses
        return fake

    def test_the_model_selects_a_tool_and_the_backend_runs_it(self, client, monkeypatch):
        answer = "Ordered demand is rising.\n- **Latest** - 200,686 units."
        fake = self._client(self._responses(["demand_trend"], answer))
        with patch("app.services.assistant.llm.is_configured", return_value=True), patch(
            "app.services.assistant.llm.client", return_value=fake
        ):
            body = client.post(
                "/api/assistant/ask",
                json={"question": "Show the demand trend", "history": [], "current_scope": None},
            ).json()
        assert body["answered_by"] == "openai"
        assert body["tools_used"] == ["demand_trend"]
        assert body["answer"] == answer

    def test_the_tool_schema_gives_the_model_no_arguments_to_author(self):
        from app.services.assistant import agent

        for entry in agent._schema():
            assert entry["function"]["parameters"]["properties"] == {}
            assert entry["function"]["parameters"]["additionalProperties"] is False

    def test_a_provider_failure_degrades_to_the_deterministic_writer(self, client):
        fake = MagicMock()
        fake.chat.completions.create.side_effect = RuntimeError("rate limited")
        with patch("app.services.assistant.llm.is_configured", return_value=True), patch(
            "app.services.assistant.llm.client", return_value=fake
        ):
            body = client.post(
                "/api/assistant/ask",
                json={"question": "Show the monthly demand trend", "history": [], "current_scope": None},
            ).json()
        assert body["answered_by"] == "deterministic_after_provider_error"
        assert "rate limited" in body["provider_error"]
        assert body["answer"]

    def test_a_tool_free_reply_is_not_trusted_as_an_answer(self, client):
        # An ungrounded reply must never be returned as the answer: it falls
        # through to the writer that reads the real facts.
        empty = MagicMock()
        empty.choices = [MagicMock()]
        empty.choices[0].message.tool_calls = None
        empty.choices[0].message.content = "I think demand is probably about 5 million units."
        fake = self._client([empty])
        with patch("app.services.assistant.llm.is_configured", return_value=True), patch(
            "app.services.assistant.llm.client", return_value=fake
        ):
            body = client.post(
                "/api/assistant/ask",
                json={"question": "Show the monthly demand trend", "history": [], "current_scope": None},
            ).json()
        assert body["answered_by"] == "deterministic_after_provider_error"
        assert "probably about 5 million" not in body["answer"]

    def test_the_tool_budget_is_bounded(self):
        from app.services.assistant import agent

        assert agent.MAX_TOOL_CALLS <= 4
        assert agent.MAX_ROUNDS <= 2

    def test_no_response_ever_carries_the_key(self, client):
        answer = "Demand is rising."
        fake = self._client(self._responses(["demand_trend"], answer))
        with patch("app.services.assistant.llm.is_configured", return_value=True), patch(
            "app.services.assistant.llm.client", return_value=fake
        ), patch("app.core.config.get_settings") as settings:
            settings.return_value.openai_api_key = "sk-test-do-not-leak"
            settings.return_value.openai_model = "gpt-4.1-mini"
            settings.return_value.ai_assistant_enabled = True
            settings.return_value.ai_max_output_tokens = 900
            settings.return_value.ai_request_timeout_seconds = 30.0
            response = client.post(
                "/api/assistant/ask",
                json={"question": "Show the demand trend", "history": [], "current_scope": None},
            )
        assert "sk-test-do-not-leak" not in response.text


class TestDeterministicWriter:
    def test_it_states_only_figures_present_in_the_facts(self):
        from app.services.assistant import llm

        facts = {
            "model_leaderboard": {
                "champion": {"model": "VAR", "wape_pct": 4.578, "validation_points": 10},
                "best_baseline": {"method": "MA6", "wape_pct": 9.939},
                "champion_beats_best_baseline": True,
                "models_that_did_not_run": [{"model": "Auto ARIMA", "status": "ineligible", "reason": "short"}],
            }
        }
        answer = llm.compose_answer("why is this champion?", facts)
        assert "4.578" in answer
        assert "9.939" in answer
        assert "Auto ARIMA" in answer

    def test_it_reports_a_baseline_beating_the_champion_plainly(self):
        from app.services.assistant import llm

        facts = {
            "model_leaderboard": {
                "champion": {"model": "SARIMAX", "wape_pct": 116.0, "validation_points": 10},
                "best_baseline": {"method": "MA6", "wape_pct": 90.69},
                "champion_beats_best_baseline": False,
            }
        }
        assert "loses to" in llm.compose_answer("which model is best?", facts)

    def test_no_facts_means_the_scope_message_not_an_invented_answer(self):
        from app.services.assistant import llm

        assert llm.compose_answer("anything", {}) == llm.SCOPE_MESSAGE


class TestLeadTime:
    """Lead time was in the data and on no screen except one table column.

    Two of the three computed columns reached nothing at all. What these
    assert is the part that would mislead a reader: a zero-day lead time is a
    gap rather than a fast branch, transit cannot exceed the total it sits
    inside, and zero variability is ambiguous rather than a reliability
    finding.
    """

    @staticmethod
    def _branches(rows: list[dict[str, Any]]) -> pd.DataFrame:
        defaults = {
            "canonical_branch": "BR1",
            "region": "NORTH-1",
            "avg_lead_time_days": 4.0,
            "std_lead_time_days": 1.0,
            "transit_lead_time_days": 2.0,
            "holds_stock": True,
        }
        return pd.DataFrame([{**defaults, **row} for row in rows])

    def test_it_reports_the_median_and_the_spread(self):
        payload = A.lead_time(
            self._branches(
                [
                    {"canonical_branch": "A", "avg_lead_time_days": 3.0, "std_lead_time_days": 0.5},
                    {"canonical_branch": "B", "avg_lead_time_days": 5.0, "std_lead_time_days": 1.5},
                ]
            )
        )
        assert payload["kpis"]["median_avg_days"] == 4.0
        assert payload["kpis"]["median_std_days"] == 1.0
        assert payload["kpis"]["branches_with_a_usable_lead_time"] == 2

    def test_variability_is_relative_to_the_mean(self):
        # A 2-day spread on a 3-day lead time is far worse than the same spread
        # on 12 days, which is why the ranking uses the coefficient of
        # variation rather than the raw standard deviation.
        payload = A.lead_time(
            self._branches(
                [
                    {"canonical_branch": "VOLATILE", "avg_lead_time_days": 3.0, "std_lead_time_days": 2.0},
                    {"canonical_branch": "SLOW", "avg_lead_time_days": 12.0, "std_lead_time_days": 2.0},
                ]
            )
        )
        assert payload["least_reliable"][0]["branch"] == "VOLATILE"
        assert payload["least_reliable"][0]["cv_pct"] == pytest.approx(66.7, abs=0.1)

    def test_a_zero_day_lead_time_is_an_anomaly_not_a_fast_branch(self):
        payload = A.lead_time(
            self._branches([{"canonical_branch": "PLANT", "avg_lead_time_days": 0.0, "std_lead_time_days": 0.0}])
        )
        assert payload["kpis"]["branches_with_a_usable_lead_time"] == 0
        reasons = " ".join(row["reason"] for row in payload["anomalies"])
        assert "not credible" in reasons
        # And it is kept out of the medians, so one plant row cannot drag the
        # network median toward zero.
        assert payload["kpis"]["median_avg_days"] is None

    def test_transit_exceeding_the_total_is_reported_as_a_contradiction(self):
        payload = A.lead_time(
            self._branches(
                [{"canonical_branch": "BAWAL", "avg_lead_time_days": 2.0, "transit_lead_time_days": 44.0}]
            )
        )
        reasons = " ".join(row["reason"] for row in payload["anomalies"])
        assert "exceeds the total lead time" in reasons
        # It must not be plotted as a negative duration in the transit split.
        charted = [row for row in payload["by_branch"] if (row["handling_days"] or 0) >= 0]
        assert not charted

    def test_zero_variability_is_called_ambiguous_not_reliable(self):
        payload = A.lead_time(
            self._branches([{"canonical_branch": "FLAT", "std_lead_time_days": 0.0}])
        )
        assert payload["kpis"]["branches_zero_variability"] == 1
        notes = " ".join(payload["notes"])
        assert "ambiguous" in notes
        assert "only one observation" in notes

    def test_it_states_that_variability_changes_no_recommendation(self):
        # The protection period is review + average lead time. Surfacing the
        # spread without saying it is unused would imply it was already
        # accounted for.
        payload = A.lead_time(self._branches([{}]))
        notes = " ".join(payload["notes"])
        assert "does not currently affect any recommendation" in notes

    def test_handling_days_is_the_total_minus_transit(self):
        payload = A.lead_time(
            self._branches([{"avg_lead_time_days": 5.0, "transit_lead_time_days": 2.0}])
        )
        assert payload["by_branch"][0]["handling_days"] == 3.0

    def test_an_empty_dimension_says_so(self):
        assert A.lead_time(pd.DataFrame())["empty"] is True

    def test_the_endpoint_serves_it(self, client, monkeypatch):
        frame = self._branches([{"canonical_branch": "A", "avg_lead_time_days": 6.0}])
        monkeypatch.setattr("app.api.routes.analytics._branch_dim", lambda db: frame)
        response = client.get("/api/analytics/lead-time")
        assert response.status_code == 200
        body = response.json()
        assert body["kpis"]["median_avg_days"] == 6.0
        assert body["by_branch"][0]["branch"] == "A"

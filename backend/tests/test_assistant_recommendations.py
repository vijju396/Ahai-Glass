"""AI recommendations, and the temperature they are written at.

The value of this feature is entirely in whether its items are true. A list of
plausible-sounding suggestions that are not grounded in a measured figure is
worse than no list, because it reads exactly the same on a screen.

So the tests here are mostly about what the feature *refuses* to emit: an item
with no evidence, an item invented when the provider fails, a list that hides
which of the two writers produced it. The temperature tests exist because 2.0
is a deliberate, unusual setting that raises exactly this risk.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.core.config import get_settings
from app.db.session import session_scope
from app.services.assistant import recommendations as R
from app.services.assistant import tools

FACTS = {
    "stock_exceptions": {
        "totals": {
            "critical_lines": 3638,
            "short_despatch_lines": 2587,
            "zero_stock_live_demand_lines": 1051,
        }
    },
    "model_leaderboard": {
        "champion": {"model": "VAR with exogenous variables", "wape_pct": 6.4},
        "best_baseline": {"method": "ma6", "wape_pct": 5.1},
        "champion_beats_best_baseline": False,
    },
    "data_quality": {"drift": {"national_shift_pct": 23.29, "window_months": 6}},
}


def _completion(content: str):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


@pytest.fixture
def clear_settings():
    yield
    get_settings.cache_clear()


@pytest.fixture
def db_session():
    with session_scope() as session:
        yield session


# ----------------------------------------------------------------------
# Grounding
# ----------------------------------------------------------------------


def test_an_item_with_no_evidence_is_dropped():
    """The prompt asks for a measured figure; this is what enforces it.

    A recommendation nobody can check is the failure mode that matters, and
    asking a model nicely is not a guarantee.
    """
    kept = R._clean(
        [
            {
                "title": "Grounded",
                "severity": "high",
                "observation": "3,638 lines are critical.",
                "explanation": "Because the facts say so.",
                "evidence": ["critical_lines = 3,638"],
                "source": "stock_exceptions",
            },
            {
                "title": "Ungrounded",
                "severity": "critical",
                "observation": "Things look concerning.",
                "explanation": "No figure attached.",
                "evidence": [],
                "source": "stock_exceptions",
            },
        ]
    )

    assert [item["title"] for item in kept] == ["Grounded"]


def test_an_item_missing_its_explanation_is_dropped():
    kept = R._clean(
        [
            {
                "title": "No explanation",
                "severity": "high",
                "observation": "3,638 lines.",
                "explanation": "   ",
                "evidence": ["critical_lines = 3,638"],
            }
        ]
    )

    assert kept == []


def test_items_come_back_most_severe_first():
    kept = R._clean(
        [
            {
                "title": "Medium",
                "severity": "medium",
                "observation": "x",
                "explanation": "y",
                "evidence": ["a"],
            },
            {
                "title": "Critical",
                "severity": "critical",
                "observation": "x",
                "explanation": "y",
                "evidence": ["a"],
            },
            {
                "title": "High",
                "severity": "high",
                "observation": "x",
                "explanation": "y",
                "evidence": ["a"],
            },
        ]
    )

    assert [item["title"] for item in kept] == ["Critical", "High", "Medium"]


def test_an_unknown_severity_becomes_medium_rather_than_ranking_first():
    kept = R._clean(
        [
            {
                "title": "Odd",
                "severity": "catastrophic",
                "observation": "x",
                "explanation": "y",
                "evidence": ["a"],
            }
        ]
    )

    assert kept[0]["severity"] == "medium"


def test_the_list_is_capped():
    many = [
        {
            "title": f"Item {n}",
            "severity": "high",
            "observation": "x",
            "explanation": "y",
            "evidence": ["a"],
        }
        for n in range(20)
    ]

    assert len(R._clean(many)) == R.MAX_ITEMS


def test_every_item_names_a_page_its_figures_can_be_checked_on():
    kept = R._clean(
        [
            {
                "title": "Checkable",
                "severity": "high",
                "observation": "x",
                "explanation": "y",
                "evidence": ["a"],
                "source": "stock_exceptions",
            }
        ]
    )

    assert kept[0]["verify_on"] == "Operational Exceptions"


def test_an_unrecognised_source_is_not_passed_through():
    """A source the model invented must not become a link to nowhere."""
    kept = R._clean(
        [
            {
                "title": "Made-up source",
                "severity": "high",
                "observation": "x",
                "explanation": "y",
                "evidence": ["a"],
                "source": "crystal_ball",
            }
        ]
    )

    assert kept[0]["source"] is None
    assert kept[0]["verify_on"] is None


def test_every_declared_source_is_a_real_tool():
    assert set(R.SOURCES) <= set(tools.TOOLS)
    assert set(R.SOURCES) == set(R.VERIFY_ON)


# ----------------------------------------------------------------------
# The deterministic writer
# ----------------------------------------------------------------------


def test_the_template_writer_reports_only_what_the_facts_contain():
    items = R._deterministic(FACTS)
    titles = [item["title"] for item in items]

    assert any("Critical supply exceptions" in t for t in titles)
    assert any("baseline is beating the champion" in t for t in titles)
    for item in items:
        assert item["evidence"], item["title"]


def test_the_template_writer_emits_nothing_from_empty_facts():
    """Silence is the correct output when there is nothing measured to say."""
    assert R._deterministic({}) == []
    assert R._deterministic({"stock_exceptions": {"totals": {"critical_lines": 0}}}) == []


def test_the_template_writer_explains_jargon_it_uses():
    items = R._deterministic(FACTS)
    baseline = next(i for i in items if "baseline" in i["title"])

    # The reader is assumed not to know these terms.
    assert "WAPE" in baseline["explanation"]
    assert "lower is better" in baseline["explanation"]
    assert "never allowed to become champion" in baseline["explanation"]


# ----------------------------------------------------------------------
# Which writer, and at what temperature
# ----------------------------------------------------------------------


def test_with_no_key_it_says_so_rather_than_implying_a_model_wrote_it(db_session):
    with patch.object(R.llm, "is_configured", return_value=False), patch.object(
        R, "_gather", return_value=FACTS
    ):
        out = R.generate(db_session)

    assert out["answered_by"] == "deterministic_no_key"
    assert out["model"] is None
    assert out["items"]


def test_a_provider_failure_falls_back_instead_of_emptying_the_page(db_session):
    with patch.object(R.llm, "is_configured", return_value=True), patch.object(
        R, "_gather", return_value=FACTS
    ), patch.object(R.llm, "client", side_effect=RuntimeError("boom")):
        out = R.generate(db_session)

    assert out["answered_by"] == "deterministic_after_provider_error"
    assert out["items"], "a provider failure must not blank the panel"
    # The type only. A provider message can carry request details and this is
    # returned to a browser.
    assert out["provider_error"] == "RuntimeError"
    assert "boom" not in json.dumps(out)


def test_a_model_reply_with_no_evidenced_item_falls_back(db_session):
    """An empty list from the model is a failure, not an answer.

    Returning it would say "nothing to report" when what happened is that
    everything reported was unusable.
    """
    reply = _completion(json.dumps({"items": [{"title": "Vague", "severity": "high"}]}))
    fake = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **_: reply))
    )
    with patch.object(R.llm, "is_configured", return_value=True), patch.object(
        R, "_gather", return_value=FACTS
    ), patch.object(R.llm, "client", return_value=fake):
        out = R.generate(db_session)

    assert out["answered_by"] == "deterministic_after_provider_error"


def test_the_configured_temperature_is_used_and_reported(db_session, monkeypatch, clear_settings):
    monkeypatch.setenv("AI_TEMPERATURE", "2.0")
    get_settings.cache_clear()
    seen: dict[str, object] = {}

    def create(**kwargs):
        seen.update(kwargs)
        return _completion(
            json.dumps(
                {
                    "items": [
                        {
                            "title": "Grounded item",
                            "severity": "critical",
                            "observation": "3,638 lines are critical.",
                            "explanation": "Explained plainly.",
                            "evidence": ["critical_lines = 3,638"],
                            "source": "stock_exceptions",
                        }
                    ]
                }
            )
        )

    fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    with patch.object(R.llm, "is_configured", return_value=True), patch.object(
        R, "_gather", return_value=FACTS
    ), patch.object(R.llm, "client", return_value=fake):
        out = R.generate(db_session)

    assert seen["temperature"] == 2.0
    assert seen["response_format"] == {"type": "json_object"}
    # Reported, because at 2.0 the same facts give a different list each run
    # and a reader comparing two of them should know why.
    assert out["temperature"] == 2.0
    assert out["answered_by"] == "openai"


def test_tool_selection_stays_deterministic_even_when_prose_does_not(
    monkeypatch, clear_settings
):
    """The two temperatures are separate on purpose.

    The selection call emits function names and JSON arguments, not prose.
    Randomness there does not read as variety - it reads as the assistant
    answering a different question than the one asked.
    """
    monkeypatch.setenv("AI_TEMPERATURE", "2.0")
    get_settings.cache_clear()
    settings = get_settings()

    assert settings.ai_temperature == 2.0
    assert settings.ai_tool_choice_temperature == 0.0


def test_temperature_is_bounded_to_the_providers_range(monkeypatch, clear_settings):
    monkeypatch.setenv("AI_TEMPERATURE", "3.5")
    get_settings.cache_clear()

    with pytest.raises(Exception):
        get_settings()


# ----------------------------------------------------------------------
# Caveats
# ----------------------------------------------------------------------


def test_the_payload_always_carries_the_caveats_that_qualify_it(db_session):
    with patch.object(R.llm, "is_configured", return_value=False), patch.object(
        R, "_gather", return_value=FACTS
    ):
        out = R.generate(db_session)

    joined = " ".join(out["caveats"])
    assert "not instructions to act" in joined
    assert "no inventory-policy backtest" in joined
    assert "2026-08-01" in joined


def test_one_failing_source_does_not_empty_the_others(db_session):
    def boom(*_args, **_kwargs):
        raise RuntimeError("source down")

    with patch.dict(tools.TOOLS, {"stock_exceptions": boom}):
        gathered = R._gather(db_session)

    assert "temporarily unavailable" in gathered["stock_exceptions"]["status"]
    assert set(gathered) == set(R.SOURCES)

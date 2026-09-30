"""Money reaches the model already written, and SKU counts are never summed.

Two defects found by asking the assistant about the workspace after it grew
from 20 SKUs to 136, both reproducible across repeated runs at temperature 0.3:

**Every rupee figure was a tenth of the truth.** The facts carried the raw
amount (602,400,000) and the system prompt asked for "₹8.9Cr", so the model did
the conversion - and divided by 10^8 rather than 10^7 every time. ₹60.24Cr came
back as ₹6.02Cr, ₹39.5Cr as ₹3.95Cr. `tools.py`'s own docstring names this
failure: a model allowed to do arithmetic on facts will do it wrong in the same
confident voice.

**"How many SKUs?" answered 271.** That is the series count. The facts gave a
per-branch SKU count and no workspace total, so the model added 136 and 135.
It was invisible while both branches carried the same twenty SKUs.
"""

from __future__ import annotations

import pytest

from app.services.assistant.tools import _rupees


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        (602_400_000, "₹60.24Cr"),
        (395_000_000, "₹39.50Cr"),
        (923_140_944.1, "₹92.31Cr"),
        (10_000_000, "₹1.00Cr"),
        (9_999_999, "₹100.00L"),
        (100_000, "₹1.00L"),
        (99_999, "₹99,999"),
        (0, "₹0"),
    ],
)
def test_a_rupee_amount_is_written_in_indian_numbering(amount, expected):
    assert _rupees(amount) == expected


def test_the_crore_divisor_is_ten_million_not_a_hundred_million():
    """The exact regression: ₹60.24Cr must never come back as ₹6.02Cr."""
    assert _rupees(602_400_000) == "₹60.24Cr"
    assert _rupees(602_400_000) != "₹6.02Cr"


def test_a_negative_amount_keeps_its_sign():
    assert _rupees(-45_000_000) == "-₹4.50Cr"


@pytest.mark.parametrize("value", [None, "not a number", True, False])
def test_a_non_numeric_value_yields_nothing_rather_than_a_fake_amount(value):
    """A missing figure must not become "₹0Cr" in an answer."""
    assert _rupees(value) is None


def test_branch_demand_publishes_a_workspace_sku_total(monkeypatch):
    """The per-branch counts overlap; only the total answers "how many SKUs"."""
    from app.services.assistant import tools

    payload = {
        "window": {"start": "2025-W14", "end": "2026-W31"},
        "kpis": {
            "branch_count": 2,
            "sku_count": 136,
            "demand_units": 146_814.0,
            "demand_value": 602_400_000.0,
            "fill_rate_pct": 88.4,
        },
        "by_branch": [
            {
                "name": "BENGALURU",
                "demand_units": 99_730.0,
                "demand_value": 395_000_000.0,
                "sku_count": 136,
                "despatched_units": 86_400.0,
                "shortfall_units": 13_330.0,
            },
            {
                "name": "DELHI-1",
                "demand_units": 47_084.0,
                "demand_value": 207_400_000.0,
                "sku_count": 135,
                "despatched_units": 43_150.0,
                "shortfall_units": 3_934.0,
            },
        ],
        "notes": [],
    }

    class _Build:
        id = "build-1"

    monkeypatch.setattr(
        tools, "_panel_and_path", lambda db: (object(), _Build(), "path", None)
    )
    monkeypatch.setattr(tools, "_analytics_scope", lambda scope, panel=None: None)

    from app.domain.ais import analytics as A

    monkeypatch.setattr(A, "cached_summary", lambda *a, **k: payload)

    facts = tools.branch_demand(None, None)

    assert facts["skus_total"] == 136
    assert "never be added" in facts["skus_total_note"]
    assert facts["total_demand_value_display"] == "₹60.24Cr"
    assert facts["branches_ranked_by_demand"][0]["value_display"] == "₹39.50Cr"

    # The sum the model reached for is 271 - it must not be a fact.
    summed = sum(r["skus"] for r in facts["branches_ranked_by_demand"])
    assert summed == 271
    assert facts["skus_total"] != summed


def test_the_prompt_forbids_converting_rupees_by_hand():
    """Rule 3 used to ask for crores while giving only raw rupees."""
    from app.services.assistant.llm import SYSTEM_PROMPT  # noqa: PLC0415

    assert "_display" in SYSTEM_PROMPT
    assert "Never convert" in SYSTEM_PROMPT


def test_the_greeting_states_the_real_horizon_count():
    """"horizons 1-6" was hardcoded; a weekly build forecasts 26 periods."""
    from app.core.config import get_settings
    from app.services.assistant.llm import greeting_message

    text = greeting_message(None)
    assert f"horizons 1-{get_settings().forecast_horizon}" in text


def test_the_system_prompt_claims_no_network_wide_scope():
    """It asserted "53 branches, about 2,300 SKUs" on every single turn.

    D-125 removed that constant from the greeting but left it in the system
    prompt, where the model reads it before every answer.
    """
    from app.services.assistant.llm import SYSTEM_PROMPT

    assert "53 branches" not in SYSTEM_PROMPT
    assert "2,300 SKUs" not in SYSTEM_PROMPT
    assert "restricted slice" in SYSTEM_PROMPT

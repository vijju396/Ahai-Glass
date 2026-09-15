"""The analytics cache key must cover every scope field.

The bug this guards was silent and total: `_key` listed the scope fields by
hand, `sku` was added to `AnalyticsScope` without being added there, and so
the first SKU's answer was served for every other SKU. The page showed a
different heading and identical numbers.

Measured before the fix, both of these returned 20 series and 29,135 units -
the branch total - for two different SKUs.
"""
from __future__ import annotations

import dataclasses

from app.domain.ais.analytics import AnalyticsScope, _key


def test_two_different_skus_get_two_different_keys():
    a = _key("panel", AnalyticsScope(branch="AHMEDABAD", sku="SKU-A"))
    b = _key("panel", AnalyticsScope(branch="AHMEDABAD", sku="SKU-B"))

    assert a != b


def test_the_key_covers_every_field_on_the_scope():
    """The property, not the field list.

    Asserting the count is what makes the next filter safe: adding a field to
    the scope and forgetting the key fails here instead of silently serving a
    stale answer.
    """
    scope = AnalyticsScope(
        branch="AHMEDABAD",
        sku="SKU-A",
        product_group="AIS GLASS",
        value_class="A",
        start_period="2025-01",
        end_period="2025-06",
        grain="quarterly",
    )
    field_count = len(dataclasses.fields(AnalyticsScope))

    # panel path + every scope field.
    assert len(_key("panel", scope)) == 1 + field_count


def test_every_field_actually_changes_the_key():
    base = AnalyticsScope()
    baseline = _key("panel", base)
    changes = {
        "branch": "AHMEDABAD",
        "sku": "SKU-A",
        "product_group": "AIS GLASS",
        "value_class": "A",
        "start_period": "2025-01",
        "end_period": "2025-06",
        "grain": "quarterly",
    }
    for field in dataclasses.fields(AnalyticsScope):
        assert field.name in changes, f"{field.name} is not covered by this test"
        altered = dataclasses.replace(base, **{field.name: changes[field.name]})
        assert _key("panel", altered) != baseline, field.name


def test_extra_arguments_still_separate_keys():
    """The scorecard passes its row limit as an extra."""
    scope = AnalyticsScope(branch="AHMEDABAD")

    assert _key("panel", scope, 8) != _key("panel", scope, 20)


def test_the_panel_path_separates_keys():
    """A rebuilt panel is a different key, not a stale hit."""
    scope = AnalyticsScope(branch="AHMEDABAD")

    assert _key("panel-a", scope) != _key("panel-b", scope)

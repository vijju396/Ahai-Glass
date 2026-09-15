"""Semantic roles, mapping validation, and the advisory suggester."""

from __future__ import annotations

import pytest

from app.ml.features.role_suggestion import ColumnSignals, suggest_all, suggest_role
from app.ml.features.roles import (
    ImputationPolicy,
    MappingConfig,
    MissingTimestampPolicy,
    RoleAssignment,
    SemanticRole,
    blocking_violations,
    validate_mapping,
)


def _assignment(column: str, role: SemanticRole, source: str = "orders") -> RoleAssignment:
    return RoleAssignment(source_role=source, column_name=column, role=role)


def _valid_set() -> list[RoleAssignment]:
    return [
        _assignment("Order Date", SemanticRole.TIME_COLUMN),
        _assignment("Quantity", SemanticRole.TARGET_COLUMN),
        _assignment("Depo", SemanticRole.SERIES_IDENTIFIER),
        _assignment("Oracle No", SemanticRole.SERIES_IDENTIFIER),
        _assignment("Despatch Qty", SemanticRole.SUPPLY),
    ]


class TestMappingValidation:
    def test_a_complete_mapping_has_no_blocking_violations(self) -> None:
        violations = validate_mapping(_valid_set(), MappingConfig())
        assert blocking_violations(violations) == []

    def test_a_missing_target_blocks(self) -> None:
        assignments = [a for a in _valid_set() if a.role is not SemanticRole.TARGET_COLUMN]
        codes = {v.code for v in blocking_violations(validate_mapping(assignments, MappingConfig()))}
        assert "R1" in codes

    def test_a_missing_time_column_blocks(self) -> None:
        assignments = [a for a in _valid_set() if a.role is not SemanticRole.TIME_COLUMN]
        codes = {v.code for v in blocking_violations(validate_mapping(assignments, MappingConfig()))}
        assert "R1" in codes

    def test_two_targets_in_one_source_block(self) -> None:
        assignments = [*_valid_set(), _assignment("Despatch Qty2", SemanticRole.TARGET_COLUMN)]
        violations = blocking_violations(validate_mapping(assignments, MappingConfig()))
        r2 = next(v for v in violations if v.code == "R2")
        assert len(r2.columns) == 2
        assert "within a source" in r2.message

    def test_one_target_per_source_across_two_sources_is_allowed(self) -> None:
        """The multi-source shape AIS actually has: the order file contributes
        ordered quantity on its order date, the sales file contributes invoiced
        quantity on its invoice date. The hybrid target needs both, so a global
        singleton rule would block a correct mapping."""
        assignments = [
            *_valid_set(),
            _assignment("Quantity", SemanticRole.TARGET_COLUMN, source="sales"),
            _assignment("Inv Date", SemanticRole.TIME_COLUMN, source="sales"),
            _assignment("Branch", SemanticRole.SERIES_IDENTIFIER, source="sales"),
        ]
        assert blocking_violations(validate_mapping(assignments, MappingConfig())) == []

    def test_two_time_columns_in_one_source_block(self) -> None:
        assignments = [*_valid_set(), _assignment("Despatch Date", SemanticRole.TIME_COLUMN)]
        violations = blocking_violations(validate_mapping(assignments, MappingConfig()))
        r2 = next(v for v in violations if v.code == "R2")
        assert "orders" in r2.message

    def test_one_column_cannot_hold_two_roles(self) -> None:
        assignments = [
            *_valid_set(),
            _assignment("Quantity", SemanticRole.HISTORICAL_DRIVER),
        ]
        codes = {v.code for v in blocking_violations(validate_mapping(assignments, MappingConfig()))}
        assert "R3" in codes

    def test_pii_can_only_be_excluded(self) -> None:
        """A PII column mapped as a feature is a blocking error, not a warning."""
        assignments = [*_valid_set(), _assignment("Customer Name", SemanticRole.STATIC_ATTRIBUTE)]
        violations = blocking_violations(
            validate_mapping(assignments, MappingConfig(), pii_columns=frozenset({"Customer Name"}))
        )
        r4 = next(v for v in violations if v.code == "R4")
        assert "Customer Name" in r4.columns
        assert "excluded_pii" in (r4.remediation or "")

    def test_pii_mapped_as_excluded_is_accepted(self) -> None:
        assignments = [*_valid_set(), _assignment("Customer Name", SemanticRole.EXCLUDED_PII)]
        violations = blocking_violations(
            validate_mapping(assignments, MappingConfig(), pii_columns=frozenset({"Customer Name"}))
        )
        assert [v for v in violations if v.code == "R4"] == []

    def test_a_driver_without_future_values_cannot_be_future_known(self) -> None:
        """The leakage rule. MRP can change, so its future value is not known;
        claiming otherwise fails here rather than at forecast time."""
        assignments = [*_valid_set(), _assignment("MRP Rate", SemanticRole.FUTURE_KNOWN_DRIVER)]
        violations = blocking_violations(
            validate_mapping(
                assignments, MappingConfig(), known_future_columns=frozenset({"calendar_month"})
            )
        )
        r5 = next(v for v in violations if v.code == "R5")
        assert "MRP Rate" in r5.columns
        assert "historical_driver" in (r5.remediation or "")
        assert "leakage" in (r5.remediation or "").lower()

    def test_a_genuinely_future_known_driver_is_accepted(self) -> None:
        assignments = [
            *_valid_set(),
            _assignment("calendar_month", SemanticRole.FUTURE_KNOWN_DRIVER),
        ]
        violations = blocking_violations(
            validate_mapping(
                assignments, MappingConfig(), known_future_columns=frozenset({"calendar_month"})
            )
        )
        assert [v for v in violations if v.code == "R5"] == []

    def test_the_future_known_rule_is_skipped_when_no_set_is_supplied(self) -> None:
        """Absent a declared future-known set, the rule cannot be evaluated and
        must not fabricate a verdict."""
        assignments = [*_valid_set(), _assignment("MRP Rate", SemanticRole.FUTURE_KNOWN_DRIVER)]
        violations = validate_mapping(assignments, MappingConfig())
        assert [v for v in violations if v.code == "R5"] == []

    def test_a_missing_series_identifier_warns_but_does_not_block(self) -> None:
        assignments = [
            a for a in _valid_set() if a.role is not SemanticRole.SERIES_IDENTIFIER
        ]
        violations = validate_mapping(assignments, MappingConfig())
        r6 = next(v for v in violations if v.code == "R6")
        assert r6.severity == "warning"
        assert blocking_violations(violations) == []

    def test_a_non_positive_horizon_blocks(self) -> None:
        violations = blocking_violations(
            validate_mapping(_valid_set(), MappingConfig(forecast_horizon=0))
        )
        assert {v.code for v in violations} == {"R7"}

    def test_leaving_periods_missing_warns_for_intermittent_demand(self) -> None:
        config = MappingConfig(missing_timestamp_policy=MissingTimestampPolicy.LEAVE_MISSING)
        violations = validate_mapping(_valid_set(), config)
        r8 = next(v for v in violations if v.code == "R8")
        assert r8.severity == "warning"
        assert "explicit_zero" in (r8.remediation or "")

    def test_zero_imputing_the_target_warns(self) -> None:
        """Zero-imputing a missing target makes it indistinguishable from an
        observed zero, which is the one confusion this dataset cannot afford."""
        config = MappingConfig(target_imputation_policy=ImputationPolicy.ZERO)
        violations = validate_mapping(_valid_set(), config)
        r9 = next(v for v in violations if v.code == "R9")
        assert r9.severity == "warning"
        assert "indistinguishable" in r9.remediation.lower()

    def test_every_violation_is_returned_not_just_the_first(self) -> None:
        violations = validate_mapping([], MappingConfig(forecast_horizon=0))
        codes = {v.code for v in violations}
        assert {"R1", "R6", "R7"} <= codes


class TestRoleSuggestion:
    def _signals(self, **overrides) -> ColumnSignals:
        base = {
            "source_role": "orders",
            "column_name": "Quantity",
            "ordinal": 0,
            "detected_type": "numeric",
            "row_count": 775_912,
            "non_null_count": 775_912,
            "distinct_count": 96,
            "is_constant": False,
            "is_pii": False,
        }
        base.update(overrides)
        return ColumnSignals(**base)

    def test_pii_outranks_every_other_signal(self) -> None:
        suggestion = suggest_role(
            self._signals(column_name="Customer Name", detected_type="text", is_pii=True)
        )
        assert suggestion.role is SemanticRole.EXCLUDED_PII
        assert suggestion.confidence == 1.0

    def test_a_date_parsing_column_is_the_time_column(self) -> None:
        suggestion = suggest_role(
            self._signals(column_name="Order Date", detected_type="text", parses_as_date=True)
        )
        assert suggestion.role is SemanticRole.TIME_COLUMN
        assert suggestion.confidence > 0.9

    def test_a_constant_column_is_ignored(self) -> None:
        suggestion = suggest_role(self._signals(column_name="Replenishment A", is_constant=True))
        assert suggestion.role is SemanticRole.IGNORED
        assert "Constant" in suggestion.rationale

    def test_an_empty_column_is_ignored(self) -> None:
        suggestion = suggest_role(self._signals(non_null_count=0))
        assert suggestion.role is SemanticRole.IGNORED

    def test_a_price_column_is_historical_never_future_known(self) -> None:
        """The safe default: a price can change, so it must never be suggested
        as future-known."""
        suggestion = suggest_role(self._signals(column_name="MRP Rate"))
        assert suggestion.role is SemanticRole.HISTORICAL_DRIVER
        assert "future value is not knowable" in suggestion.rationale

    def test_a_despatch_column_is_supply_not_target(self) -> None:
        """'Despatch Qty' carries both a supply and a demand cue; the specific
        reading must win, or the censored signal becomes the target."""
        suggestion = suggest_role(self._signals(column_name="Despatch Qty"))
        assert suggestion.role is SemanticRole.SUPPLY

    def test_a_stock_column_is_inventory(self) -> None:
        """Regression: 'CLO QTY' matched the demand cue `qty` before any
        inventory cue and was suggested as the forecast TARGET. A stock
        quantity standing in for demand is the worst mislabel available here,
        so closing-balance abbreviations are recognised explicitly."""
        suggestion = suggest_role(self._signals(column_name="CLO QTY", source_role="stock"))
        assert suggestion.role is SemanticRole.INVENTORY

    @pytest.mark.parametrize(
        "column", ["CLO QTY", "CLS QTY", "SOH QTY", "Closing Qty", "OH Quantity"]
    )
    def test_no_stock_quantity_is_ever_suggested_as_the_target(self, column: str) -> None:
        suggestion = suggest_role(self._signals(column_name=column, source_role="stock"))
        assert suggestion.role is not SemanticRole.TARGET_COLUMN

    @pytest.mark.parametrize(
        "column", ["Despatch Qty", "Dispatch Quantity", "Issued Qty", "Delivered Units"]
    )
    def test_no_fulfilment_quantity_is_ever_suggested_as_the_target(self, column: str) -> None:
        """Despatched quantity is supply-censored. Suggesting it as the target
        would train a model to reproduce the stockout."""
        suggestion = suggest_role(self._signals(column_name=column))
        assert suggestion.role is not SemanticRole.TARGET_COLUMN

    def test_a_lead_time_column_is_capacity(self) -> None:
        suggestion = suggest_role(
            self._signals(column_name="Avg Lead Time", source_role="location_master")
        )
        assert suggestion.role is SemanticRole.CAPACITY

    def test_an_unrecognised_numeric_defaults_to_a_historical_driver(self) -> None:
        """The safe default, because a historical driver cannot leak future
        information."""
        suggestion = suggest_role(self._signals(column_name="Zzz Metric"))
        assert suggestion.role is SemanticRole.HISTORICAL_DRIVER
        assert "cannot leak" in suggestion.rationale

    def test_a_low_cardinality_identifier_is_a_series_identifier(self) -> None:
        suggestion = suggest_role(
            self._signals(column_name="Branch Code", detected_type="text", distinct_count=53)
        )
        assert suggestion.role is SemanticRole.SERIES_IDENTIFIER

    def test_a_low_cardinality_text_column_is_a_static_attribute(self) -> None:
        suggestion = suggest_role(
            self._signals(column_name="Zone", detected_type="text", distinct_count=4)
        )
        assert suggestion.role is SemanticRole.STATIC_ATTRIBUTE

    def test_high_cardinality_free_text_is_ignored_not_guessed(self) -> None:
        suggestion = suggest_role(
            self._signals(
                column_name="Some Free Text", detected_type="text", distinct_count=700_000
            )
        )
        assert suggestion.role is SemanticRole.IGNORED
        assert "rather than guessed" in suggestion.rationale

    def test_detection_uses_no_dataset_specific_column_name(self) -> None:
        """The suggester must work on unrelated headers. A generic 'delivery
        date' gets the time role from the same structural signal."""
        suggestion = suggest_role(
            self._signals(
                source_role="anything",
                column_name="posting_date",
                detected_type="text",
                parses_as_date=True,
            )
        )
        assert suggestion.role is SemanticRole.TIME_COLUMN

    def test_target_contention_is_resolved_and_stated(self) -> None:
        """Ordered and despatched quantity both look like demand. One keeps the
        role; the other is demoted with the contention spelled out."""
        signals = [
            self._signals(column_name="Quantity", ordinal=0),
            self._signals(column_name="Order Volume", ordinal=1),
        ]
        suggestions = {s.column_name: s for s in suggest_all(signals)}
        targets = [s for s in suggestions.values() if s.role is SemanticRole.TARGET_COLUMN]
        assert len(targets) == 1
        demoted = next(s for s in suggestions.values() if s.role is not SemanticRole.TARGET_COLUMN)
        assert demoted.role is SemanticRole.HISTORICAL_DRIVER
        assert "reassign if this is actually" in demoted.rationale.lower()

    def test_suggest_all_returns_one_suggestion_per_column(self) -> None:
        signals = [
            self._signals(column_name=f"col_{index}", ordinal=index) for index in range(6)
        ]
        assert len(suggest_all(signals)) == 6

    @pytest.mark.parametrize(
        "column",
        ["Quantity", "Order Date", "Customer Name", "CLO QTY", "Zzz", "Avg Lead Time"],
    )
    def test_no_column_is_left_unclassified(self, column: str) -> None:
        suggestion = suggest_role(self._signals(column_name=column))
        assert isinstance(suggestion.role, SemanticRole)
        assert suggestion.rationale

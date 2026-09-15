"""Semantic column roles and mapping configuration.

Generic and dataset-agnostic: no AIS column name appears here. AIS's own
defaults live in `app.domain.ais.mapping_template` as one instantiation of
these contracts, not as part of them (docs/ARCHITECTURE.md SS3).

The split between `HISTORICAL_DRIVER` and `FUTURE_KNOWN_DRIVER` is the
load-bearing distinction in this module. It exists so a driver known only up
to "now" can never be silently used as if its future value were available -
the failure Meriton raises at fit time as `FutureExogenousUnavailable`, caught
here at mapping-confirmation time instead.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class SemanticRole(StrEnum):
    TIME_COLUMN = "time_column"
    TARGET_COLUMN = "target_column"
    SERIES_IDENTIFIER = "series_identifier"
    HISTORICAL_DRIVER = "historical_driver"
    FUTURE_KNOWN_DRIVER = "future_known_driver"
    STATIC_ATTRIBUTE = "static_attribute"
    INVENTORY = "inventory"
    CAPACITY = "capacity"
    SUPPLY = "supply"
    EXCLUDED_PII = "excluded_pii"
    IGNORED = "ignored"


#: Roles that may appear at most once **per source**, not once per mapping.
#:
#: A dataset spanning several source files legitimately has one time column and
#: one target column in each fact source: AIS's order file contributes ordered
#: quantity on its order date, and its sales file contributes invoiced quantity
#: on its invoice date. The hybrid target needs both (docs/DECISIONS.md D-002),
#: so a global singleton constraint would block a correct mapping. What must
#: never happen is two target columns inside one source.
SINGLETON_ROLES_PER_SOURCE: frozenset[SemanticRole] = frozenset(
    {SemanticRole.TIME_COLUMN, SemanticRole.TARGET_COLUMN}
)

#: Roles that must be assigned before a mapping can be confirmed.
REQUIRED_ROLES: frozenset[SemanticRole] = frozenset(
    {SemanticRole.TIME_COLUMN, SemanticRole.TARGET_COLUMN}
)

#: Roles whose columns feed a model as features.
FEATURE_ROLES: frozenset[SemanticRole] = frozenset(
    {
        SemanticRole.HISTORICAL_DRIVER,
        SemanticRole.FUTURE_KNOWN_DRIVER,
        SemanticRole.STATIC_ATTRIBUTE,
    }
)

#: Roles whose columns are deliberately kept out of every modelling dataset.
NON_MODELLING_ROLES: frozenset[SemanticRole] = frozenset(
    {SemanticRole.EXCLUDED_PII, SemanticRole.IGNORED}
)


class AggregationMethod(StrEnum):
    SUM = "sum"
    MEAN = "mean"
    MEDIAN = "median"
    LAST = "last"
    FIRST = "first"
    MAX = "max"
    MIN = "min"
    COUNT = "count"


class DuplicateHandling(StrEnum):
    AGGREGATE = "aggregate"
    KEEP_LAST = "keep_last"
    KEEP_FIRST = "keep_first"
    REJECT = "reject"


class MissingTimestampPolicy(StrEnum):
    """How an implied-but-absent period is treated.

    `EXPLICIT_ZERO` is the correct choice for intermittent demand and is
    materially different from `LEAVE_MISSING`: a month with no order is a real
    observation of zero demand, not an absent one. Conflating them is the most
    damaging mistake available on a panel that is 62% zeros.
    """

    EXPLICIT_ZERO = "explicit_zero"
    LEAVE_MISSING = "leave_missing"
    FORWARD_FILL = "forward_fill"
    REJECT = "reject"


class ImputationPolicy(StrEnum):
    LEAVE_MISSING = "leave_missing"
    ZERO = "zero"
    FORWARD_FILL = "forward_fill"
    INTERPOLATE = "interpolate"
    MEDIAN = "median"
    REJECT = "reject"


class MappingState(StrEnum):
    DRAFT = "draft"
    CONFIRMED = "confirmed"
    SUPERSEDED = "superseded"


@dataclass
class RoleAssignment:
    """One column's assigned role. `is_suggested` records that the value came
    from the advisory suggester and has not been reviewed by a person."""

    source_role: str
    column_name: str
    role: SemanticRole
    is_suggested: bool = False
    confidence: float | None = None
    rationale: str | None = None
    aggregation: AggregationMethod | None = None
    imputation: ImputationPolicy | None = None
    notes: str | None = None


@dataclass
class MappingConfig:
    """Mapping-level configuration, independent of any specific dataset."""

    frequency: str = "monthly"
    timezone: str = "Asia/Kolkata"
    forecast_horizon: int = 6
    aggregation_method: AggregationMethod = AggregationMethod.SUM
    duplicate_handling: DuplicateHandling = DuplicateHandling.AGGREGATE
    missing_timestamp_policy: MissingTimestampPolicy = MissingTimestampPolicy.EXPLICIT_ZERO
    target_imputation_policy: ImputationPolicy = ImputationPolicy.LEAVE_MISSING
    driver_imputation_policy: ImputationPolicy = ImputationPolicy.LEAVE_MISSING

    def as_dict(self) -> dict[str, str | int]:
        return {
            "frequency": self.frequency,
            "timezone": self.timezone,
            "forecast_horizon": self.forecast_horizon,
            "aggregation_method": self.aggregation_method.value,
            "duplicate_handling": self.duplicate_handling.value,
            "missing_timestamp_policy": self.missing_timestamp_policy.value,
            "target_imputation_policy": self.target_imputation_policy.value,
            "driver_imputation_policy": self.driver_imputation_policy.value,
        }


@dataclass
class RuleViolation:
    code: str
    severity: str  # blocking | warning
    message: str
    columns: list[str] = field(default_factory=list)
    remediation: str | None = None

    @property
    def is_blocking(self) -> bool:
        return self.severity == "blocking"


def _by_role(
    assignments: list[RoleAssignment],
) -> dict[SemanticRole, list[RoleAssignment]]:
    grouped: dict[SemanticRole, list[RoleAssignment]] = {}
    for assignment in assignments:
        grouped.setdefault(assignment.role, []).append(assignment)
    return grouped


def validate_mapping(
    assignments: list[RoleAssignment],
    config: MappingConfig,
    *,
    pii_columns: frozenset[str] = frozenset(),
    known_future_columns: frozenset[str] = frozenset(),
) -> list[RuleViolation]:
    """Every rule that must hold before a mapping can be confirmed.

    Returns all violations rather than raising on the first, so a person sees
    the complete list instead of fixing them one round-trip at a time.
    `known_future_columns` names the columns whose future values genuinely
    exist - anything else claiming `FUTURE_KNOWN_DRIVER` is a blocking error.
    """
    violations: list[RuleViolation] = []
    grouped = _by_role(assignments)

    # R1 - required roles present
    for role in sorted(REQUIRED_ROLES):
        if not grouped.get(role):
            violations.append(
                RuleViolation(
                    code="R1",
                    severity="blocking",
                    message=f"No column is assigned the {role.value!r} role.",
                    remediation=f"Assign exactly one column the {role.value!r} role.",
                )
            )

    # R2 - singleton roles assigned at most once PER SOURCE. Two target
    # columns in one file is an error; one target column in each of two source
    # files is the correct shape for a multi-source dataset.
    for role in sorted(SINGLETON_ROLES_PER_SOURCE):
        per_source: dict[str, list[RoleAssignment]] = {}
        for assignment in grouped.get(role, []):
            per_source.setdefault(assignment.source_role, []).append(assignment)
        for source, columns in sorted(per_source.items()):
            if len(columns) > 1:
                violations.append(
                    RuleViolation(
                        code="R2",
                        severity="blocking",
                        message=(
                            f"{len(columns)} columns in {source!r} claim the "
                            f"{role.value!r} role, which may be assigned only once "
                            "within a source."
                        ),
                        columns=[a.column_name for a in columns],
                        remediation=(
                            f"Reassign all but one of these columns in {source!r}. "
                            "Other sources may each keep their own."
                        ),
                    )
                )

    # R3 - one role per column, per source
    seen: dict[tuple[str, str], SemanticRole] = {}
    for assignment in assignments:
        key = (assignment.source_role, assignment.column_name)
        if key in seen and seen[key] is not assignment.role:
            violations.append(
                RuleViolation(
                    code="R3",
                    severity="blocking",
                    message=(
                        f"{assignment.column_name!r} in {assignment.source_role!r} is "
                        f"assigned two roles: {seen[key].value!r} and {assignment.role.value!r}."
                    ),
                    columns=[assignment.column_name],
                    remediation="Each column must have exactly one role.",
                )
            )
        seen[key] = assignment.role

    # R4 - PII may only be excluded, never modelled
    for assignment in assignments:
        if assignment.column_name in pii_columns and assignment.role is not SemanticRole.EXCLUDED_PII:
            violations.append(
                RuleViolation(
                    code="R4",
                    severity="blocking",
                    message=(
                        f"{assignment.column_name!r} is a PII column but is assigned "
                        f"{assignment.role.value!r}."
                    ),
                    columns=[assignment.column_name],
                    remediation=(
                        "PII columns may only take the 'excluded_pii' role. They never "
                        "enter a modelling dataset or an API payload."
                    ),
                )
            )

    # R5 - a future-known driver's future values must genuinely exist.
    # This is the whole reason the two driver roles are distinct.
    if known_future_columns:
        for assignment in grouped.get(SemanticRole.FUTURE_KNOWN_DRIVER, []):
            if assignment.column_name not in known_future_columns:
                violations.append(
                    RuleViolation(
                        code="R5",
                        severity="blocking",
                        message=(
                            f"{assignment.column_name!r} is mapped as a future-known "
                            "driver, but its value is not available for the forecast "
                            "horizon."
                        ),
                        columns=[assignment.column_name],
                        remediation=(
                            "Reassign it as 'historical_driver'. A driver known only up "
                            "to now must never be used as if its future value were "
                            "available - that is leakage, and it fails at forecast time."
                        ),
                    )
                )

    # R6 - a series identifier is what makes the panel; warn if absent
    if not grouped.get(SemanticRole.SERIES_IDENTIFIER):
        violations.append(
            RuleViolation(
                code="R6",
                severity="warning",
                message=(
                    "No series identifier is assigned, so the dataset collapses to a "
                    "single aggregate series."
                ),
                remediation=(
                    "Assign the columns that identify one series - for this dataset, "
                    "branch and SKU."
                ),
            )
        )

    # R7 - horizon must be positive and bounded
    if config.forecast_horizon < 1:
        violations.append(
            RuleViolation(
                code="R7", severity="blocking",
                message=f"Forecast horizon must be at least 1, got {config.forecast_horizon}.",
            )
        )

    # R8 - intermittent demand needs explicit zeros, not absent periods
    if config.missing_timestamp_policy is MissingTimestampPolicy.LEAVE_MISSING:
        violations.append(
            RuleViolation(
                code="R8",
                severity="warning",
                message=(
                    "Absent periods will be left missing rather than materialised as "
                    "explicit zeros."
                ),
                remediation=(
                    "For intermittent demand, prefer 'explicit_zero': a month with no "
                    "order is a real observation of zero, not an absent one."
                ),
            )
        )

    # R9 - a target imputed to zero fabricates demand
    if config.target_imputation_policy is ImputationPolicy.ZERO:
        violations.append(
            RuleViolation(
                code="R9",
                severity="warning",
                message="Missing target values will be imputed as zero.",
                remediation=(
                    "Zero-imputing a missing target is indistinguishable from observing "
                    "no demand. Prefer 'leave_missing' so the two stay separable."
                ),
            )
        )

    return violations


def blocking_violations(violations: list[RuleViolation]) -> list[RuleViolation]:
    return [violation for violation in violations if violation.is_blocking]

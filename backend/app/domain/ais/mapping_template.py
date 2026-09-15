"""The AIS default role mapping.

One instantiation of the generic contracts in `app.ml.features.roles` - not
part of them. This is the only place AIS column names are bound to semantic
roles, and every value here is a **default a person can override**, not a
hardcoded truth.

The `FUTURE_KNOWN` set is the important one. For AIS it contains only calendar
features, the forecast horizon, and static branch/product attributes. Notably
absent: `MRP`, `Despatch Qty` and `Shortfall`. A price changes and a despatch
has not happened yet, so their future values are not knowable - treating them
as future-known would be leakage that only surfaces at forecast time.
"""

from __future__ import annotations

from app.domain.ais.source_spec import ALL_PII_COLUMNS, SourceRole
from app.ml.features.roles import (
    AggregationMethod,
    DuplicateHandling,
    ImputationPolicy,
    MappingConfig,
    MissingTimestampPolicy,
    RoleAssignment,
    SemanticRole,
)

#: Columns whose future values genuinely exist for the forecast horizon.
#: Anything outside this set claiming `future_known_driver` is a blocking
#: validation error (rule R5).
FUTURE_KNOWN_COLUMNS: frozenset[str] = frozenset(
    {
        # Calendar and horizon - derivable for any future period.
        "calendar_month",
        "horizon_step",
        # Static attributes - constant per series, so known in advance.
        "Branch",
        "Depo",
        "Region",
        "Zone",
        "Supply Hub",
        "Tier",
        "Prod Group",
        "Product Group",
        "Product Sub Group",
        "Item Group",
        "Item Sub Grp",
        "Vehicle Category",
        "Vehicle Age Category",
        "Glass\nType",
        "OEM",
        "OEM/Non-OEM",
    }
)

#: Explicitly NOT future-known, with the reason. Surfaced in the UI so the
#: distinction is visible rather than buried in a config file.
NOT_FUTURE_KNOWN_REASONS: dict[str, str] = {
    "AIS\nMRP": "A price can change; its future value is not knowable in advance.",
    "MRP Rate": "A price can change; its future value is not knowable in advance.",
    "AIS MRP Value": "Derived from a price that can change.",
    "Despatch Qty": (
        "A future despatch has not happened yet. It is also supply-censored, so it "
        "is not a demand signal either."
    ),
    "CLO QTY": "Stock is a single snapshot; there is no future stock position.",
    "Last GRN Date": "A future receipt date is not known.",
}


#: Default role per column, per source file. Overridable in the UI.
DEFAULT_ROLES: dict[SourceRole, dict[str, SemanticRole]] = {
    SourceRole.ORDERS: {
        "Depo": SemanticRole.SERIES_IDENTIFIER,
        "Oracle No": SemanticRole.SERIES_IDENTIFIER,
        "Order Date": SemanticRole.TIME_COLUMN,
        # The forecast target. Ordered quantity, never despatched.
        "Quantity": SemanticRole.TARGET_COLUMN,
        # Co-evolving but supply-censored, so a historical driver only. It is
        # also VAR's paired endogenous series (docs/DECISIONS.md D-004).
        "Despatch Qty": SemanticRole.SUPPLY,
        "Despatch Date": SemanticRole.IGNORED,
        "Supply Hub": SemanticRole.STATIC_ATTRIBUTE,
        "Price Group": SemanticRole.STATIC_ATTRIBUTE,
        "Item Group": SemanticRole.STATIC_ATTRIBUTE,
        "Item Sub Grp": SemanticRole.STATIC_ATTRIBUTE,
        "Material Code": SemanticRole.IGNORED,
        "Material": SemanticRole.IGNORED,
        "Order No": SemanticRole.IGNORED,
        "MRP Rate": SemanticRole.HISTORICAL_DRIVER,
        "MRP Value": SemanticRole.HISTORICAL_DRIVER,
        "Invoice Date": SemanticRole.IGNORED,
        "Month": SemanticRole.IGNORED,
    },
    SourceRole.SALES: {
        "Branch": SemanticRole.SERIES_IDENTIFIER,
        "Product Code": SemanticRole.SERIES_IDENTIFIER,
        "Inv Date": SemanticRole.TIME_COLUMN,
        # The labelled substitute used only where order history does not exist.
        "Quantity": SemanticRole.TARGET_COLUMN,
        "Branch State": SemanticRole.STATIC_ATTRIBUTE,
        "Product Group": SemanticRole.STATIC_ATTRIBUTE,
        "Product Sub Group": SemanticRole.STATIC_ATTRIBUTE,
        "Vehicle Classification": SemanticRole.STATIC_ATTRIBUTE,
        "OEM Name": SemanticRole.STATIC_ATTRIBUTE,
        "Model Name": SemanticRole.STATIC_ATTRIBUTE,
        "Make": SemanticRole.STATIC_ATTRIBUTE,
        "AIS\nMRP": SemanticRole.HISTORICAL_DRIVER,
        "AIS MRP Value": SemanticRole.HISTORICAL_DRIVER,
        "Oracle No": SemanticRole.IGNORED,
        "HSN Code": SemanticRole.IGNORED,
        "Product Name": SemanticRole.IGNORED,
        "Inv No": SemanticRole.IGNORED,
        "Ord No": SemanticRole.IGNORED,
        "Ord Date": SemanticRole.IGNORED,
        "Record Type": SemanticRole.IGNORED,
        "Price Group": SemanticRole.STATIC_ATTRIBUTE,
        "Customer Category": SemanticRole.IGNORED,
        "Reason": SemanticRole.IGNORED,
        "Month": SemanticRole.IGNORED,
    },
    SourceRole.STOCK: {
        "Branch": SemanticRole.SERIES_IDENTIFIER,
        "Prod Code": SemanticRole.SERIES_IDENTIFIER,
        "CLO QTY": SemanticRole.INVENTORY,
        "CLO VAL": SemanticRole.INVENTORY,
        "MRP VAL": SemanticRole.INVENTORY,
        "Classification": SemanticRole.STATIC_ATTRIBUTE,
        "Prod Group": SemanticRole.STATIC_ATTRIBUTE,
        "Prod Name": SemanticRole.IGNORED,
        "UOM": SemanticRole.IGNORED,
        "Last GRN Date": SemanticRole.IGNORED,
    },
    SourceRole.PRODUCT_MASTER: {
        "Item Code (Oracle Code)": SemanticRole.SERIES_IDENTIFIER,
        "Vehicle Age Category": SemanticRole.STATIC_ATTRIBUTE,
        "Vehicle Category": SemanticRole.STATIC_ATTRIBUTE,
        "OEM": SemanticRole.STATIC_ATTRIBUTE,
        "OEM/Non-OEM": SemanticRole.STATIC_ATTRIBUTE,
        "Glass\nType": SemanticRole.STATIC_ATTRIBUTE,
        "Product Group": SemanticRole.STATIC_ATTRIBUTE,
        "Sales Category BASED ON Actual Sales April to Mar'24-25 AFM + WE VOLUMES":
            SemanticRole.STATIC_ATTRIBUTE,
        "AIS MRP\nw.e.f. 11th May'26": SemanticRole.HISTORICAL_DRIVER,
        "AIS Basic\nw.e.f. 11th May'26": SemanticRole.HISTORICAL_DRIVER,
        "AFM MRP\nw.e.f. 11th May'26": SemanticRole.HISTORICAL_DRIVER,
        "Substition code -1": SemanticRole.STATIC_ATTRIBUTE,
        "Substition code -2": SemanticRole.STATIC_ATTRIBUTE,
        "Product Name": SemanticRole.IGNORED,
        "S.No": SemanticRole.IGNORED,
    },
    SourceRole.LOCATION_MASTER: {
        "Branch Code": SemanticRole.SERIES_IDENTIFIER,
        "Branch Name": SemanticRole.STATIC_ATTRIBUTE,
        "Region": SemanticRole.STATIC_ATTRIBUTE,
        "Zone": SemanticRole.STATIC_ATTRIBUTE,
        "Supply Hub": SemanticRole.STATIC_ATTRIBUTE,
        "Tier": SemanticRole.STATIC_ATTRIBUTE,
        "Branch Type": SemanticRole.STATIC_ATTRIBUTE,
        "City": SemanticRole.STATIC_ATTRIBUTE,
        "District": SemanticRole.STATIC_ATTRIBUTE,
        "State": SemanticRole.STATIC_ATTRIBUTE,
        "Avg Lead Time": SemanticRole.CAPACITY,
        "Std. LeadTime": SemanticRole.CAPACITY,
        "Transit Lead Time": SemanticRole.CAPACITY,
        "Service Factor": SemanticRole.CAPACITY,
        "Truck (MoQ)": SemanticRole.CAPACITY,
        "Status": SemanticRole.STATIC_ATTRIBUTE,
        # Zero for all 57 branches - rule C16 forbids using them.
        "Replenishment A": SemanticRole.IGNORED,
        "Replenishment B": SemanticRole.IGNORED,
        "Replenishment C": SemanticRole.IGNORED,
        "Reporting Branch": SemanticRole.IGNORED,
        "Abbreviation": SemanticRole.IGNORED,
        "Division Name": SemanticRole.IGNORED,
        "Currency Decimal": SemanticRole.IGNORED,
        "Base Currency": SemanticRole.IGNORED,
        "Company": SemanticRole.IGNORED,
        "WE Supply": SemanticRole.IGNORED,
        "Country": SemanticRole.IGNORED,
    },
}


def default_config() -> MappingConfig:
    """AIS defaults. Monthly, six-month horizon, and explicit zeros - because
    62% of series are intermittent and an absent month is a real observation of
    zero demand, not a gap."""
    return MappingConfig(
        frequency="monthly",
        timezone="Asia/Kolkata",
        forecast_horizon=6,
        aggregation_method=AggregationMethod.SUM,
        duplicate_handling=DuplicateHandling.AGGREGATE,
        missing_timestamp_policy=MissingTimestampPolicy.EXPLICIT_ZERO,
        target_imputation_policy=ImputationPolicy.LEAVE_MISSING,
        driver_imputation_policy=ImputationPolicy.LEAVE_MISSING,
    )


def default_role_for(source_role: SourceRole, column_name: str) -> SemanticRole | None:
    """The AIS default for one column, or None if there is no opinion."""
    if column_name in ALL_PII_COLUMNS:
        return SemanticRole.EXCLUDED_PII
    return DEFAULT_ROLES.get(source_role, {}).get(column_name)


def build_default_assignments(
    columns_by_source: dict[str, list[str]],
) -> list[RoleAssignment]:
    """Seed a draft mapping from the AIS template.

    A column with no template entry is left for the generic suggester rather
    than guessed here, so an unrecognised column surfaces as unreviewed instead
    of silently acquiring a role.
    """
    assignments: list[RoleAssignment] = []
    for source_name, columns in columns_by_source.items():
        try:
            source_role = SourceRole(source_name)
        except ValueError:
            continue
        for column_name in columns:
            role = default_role_for(source_role, column_name)
            if role is None:
                continue
            assignments.append(
                RoleAssignment(
                    source_role=source_name,
                    column_name=column_name,
                    role=role,
                    is_suggested=True,
                    confidence=1.0 if role is SemanticRole.EXCLUDED_PII else 0.9,
                    rationale=(
                        "Declared PII; excluded from every modelling dataset."
                        if role is SemanticRole.EXCLUDED_PII
                        else "AIS default mapping template."
                    ),
                    notes=NOT_FUTURE_KNOWN_REASONS.get(column_name),
                )
            )
    return assignments

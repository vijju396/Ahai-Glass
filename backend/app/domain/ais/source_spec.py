"""The five AIS source files: expected shape, column roles, and PII.

This is the only place AIS column names are declared. `app/ml/` and the generic
services never reference them (docs/ARCHITECTURE.md SS3).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class SourceRole(StrEnum):
    SALES = "sales"
    ORDERS = "orders"
    STOCK = "stock"
    PRODUCT_MASTER = "product_master"
    LOCATION_MASTER = "location_master"


@dataclass(frozen=True)
class SourceFileSpec:
    role: SourceRole
    filename: str
    reader: str  # csv | xlsx | xlsb
    skip_rows: int
    sheets: tuple[str, ...] = ()
    expected_rows: int | None = None
    required_columns: tuple[str, ...] = ()
    pii_columns: frozenset[str] = field(default_factory=frozenset)


# --------------------------------------------------------------------------
# PII (rule C13). Dropped at ingestion; never in the panel or an API payload.
# --------------------------------------------------------------------------

SALES_PII: frozenset[str] = frozenset(
    {
        "Customer Code",
        "Customer Name",
        "GST Number",
        "Consignee Code",
        "Consignee Name",
    }
)

ORDERS_PII: frozenset[str] = frozenset({"Invoice No"})

LOCATION_PII: frozenset[str] = frozenset(
    {
        "PAN No",
        "GSTIN",
        "CIN Number",
        "TIN No / VAT ??",
        "TAN Reg No",
        "ST Reg No",
        "Contact person Code",
        "Contact Person",
        "Email",
        "Branch Email",
        "Landline Number",
        "Fax",
        "Mobile",
        "Address1",
        "Address2",
        "Zip",
    }
)

ALL_PII_COLUMNS: frozenset[str] = SALES_PII | ORDERS_PII | LOCATION_PII


# --------------------------------------------------------------------------
# File specifications
# --------------------------------------------------------------------------

SALES_SPEC = SourceFileSpec(
    role=SourceRole.SALES,
    filename="Sales Data FY 24~26.xlsb",
    reader="xlsb",
    skip_rows=0,
    sheets=("FY 25-26 Sales", "FY 24-25 Sales"),
    expected_rows=1_703_042,
    required_columns=(
        "Branch",
        "Inv Date",
        "Product Code",
        "Oracle No",
        "Product Name",
        "HSN Code",
        "Quantity",
        "Month",
    ),
    pii_columns=SALES_PII,
)

ORDERS_SPEC = SourceFileSpec(
    role=SourceRole.ORDERS,
    filename="Orders & Receipts (Lead Time).xlsx",
    reader="xlsx",
    skip_rows=0,
    expected_rows=775_912,
    required_columns=(
        "Depo",
        "Supply Hub",
        "Order Date",
        "Despatch Date",
        "Material Code",
        "Oracle No",
        "Quantity",
        "Despatch Qty",
        "Month",
    ),
    pii_columns=ORDERS_PII,
)

STOCK_SPEC = SourceFileSpec(
    role=SourceRole.STOCK,
    filename="Stock in Hand as on 1st Aug'26.xlsx",
    reader="xlsx",
    skip_rows=1,  # row 1 is a "Stock Ledger" title row carrying column totals
    expected_rows=144_921,
    required_columns=(
        "Branch",
        "Prod Group",
        "Prod Code",
        "CLO QTY",
        "CLO VAL",
        "MRP VAL",
        "Last GRN Date",
    ),
)

PRODUCT_MASTER_SPEC = SourceFileSpec(
    role=SourceRole.PRODUCT_MASTER,
    filename="Substitution Mapping.xlsx",
    reader="xlsx",
    skip_rows=0,
    expected_rows=2_417,
    required_columns=(
        "Item Code (Oracle Code)",
        "Product Name",
        "Vehicle Age Category",
        "Vehicle Category",
        "OEM",
        "OEM/Non-OEM",
        "Product Group",
    ),
)

LOCATION_MASTER_SPEC = SourceFileSpec(
    role=SourceRole.LOCATION_MASTER,
    filename="Location Master.csv",
    reader="csv",
    skip_rows=1,  # row 1 is a "Branch Master" title row
    expected_rows=57,
    required_columns=(
        "Branch Code",
        "Branch Name",
        "Region",
        "Zone",
        "Supply Hub",
        "Tier",
        "Avg Lead Time",
        "Status",
    ),
    pii_columns=LOCATION_PII,
)

SOURCE_SPECS: tuple[SourceFileSpec, ...] = (
    SALES_SPEC,
    ORDERS_SPEC,
    STOCK_SPEC,
    PRODUCT_MASTER_SPEC,
    LOCATION_MASTER_SPEC,
)

SPEC_BY_ROLE: dict[SourceRole, SourceFileSpec] = {spec.role: spec for spec in SOURCE_SPECS}


# --------------------------------------------------------------------------
# Column-level facts used by the cleaning rules
# --------------------------------------------------------------------------

#: Present only in the FY 24-25 sheet (rule C3). Dropped after a name-based
#: union, never used to align columns positionally.
SALES_FY2425_ONLY_COLUMNS: frozenset[str] = frozenset({"Doc Series"})

#: The transposition pair (rule C2). Both sheets declare this header order;
#: only FY 24-25's data matches it.
TRANSPOSED_PAIR: tuple[str, str] = ("HSN Code", "Product Name")

#: Columns that must be TRIM+UPPER normalised on landing (rules C6, C7).
NORMALIZE_UPPER_COLUMNS: dict[SourceRole, tuple[str, ...]] = {
    SourceRole.SALES: ("Branch", "Product Code", "Oracle No", "Product Sub Group"),
    SourceRole.ORDERS: ("Depo", "Supply Hub", "Material Code", "Oracle No", "Item Sub Grp"),
    SourceRole.STOCK: ("Branch", "Prod Code", "Prod Group"),
    SourceRole.PRODUCT_MASTER: ("Item Code (Oracle Code)",),
    SourceRole.LOCATION_MASTER: ("Branch Code", "Region", "Zone", "Supply Hub"),
}

#: Zero for all 57 branches; never used in any calculation (rule C16).
DEAD_LOCATION_COLUMNS: tuple[str, ...] = (
    "Replenishment A",
    "Replenishment B",
    "Replenishment C",
)

#: Product groups outside the glass forecast scope. Reported as "stock without
#: demand history" rather than dropped (docs/DECISIONS.md D-005).
NON_GLASS_PRODUCT_GROUPS: frozenset[str] = frozenset(
    {"MOLDING", "WIPER", "ADHESIVES"}
)

#: The sentinel used for a missing GRN date (defect D6).
MISSING_DATE_SENTINEL = "00-00-0000"

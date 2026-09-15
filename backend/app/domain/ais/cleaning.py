"""Cleaning rules C1-C16 (docs/DATA_CONTRACT.md SS2).

Each rule is a small pure function so it can be unit-tested against the exact
defect it exists for, rather than only through a full ingestion run.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

from app.domain.ais.source_spec import TRANSPOSED_PAIR

# --------------------------------------------------------------------------
# C8 - the canonical SKU key
# --------------------------------------------------------------------------

#: Suffixes carried by Product Code / Material Code but not by Oracle No.
#: `.AFM` appears in sales and stock, `.AF` in the (truncated) order file.
_SKU_SUFFIX = re.compile(r"\.(AFM|AF)$")


def canonical_sku(product_code: Any) -> str:
    """UPPER(TRIM(code)) -> strip trailing `.AFM`/`.AF` -> strip trailing `.`
    -> TRIM again.

    That final TRIM matters: one real code is `'FG.TX4.LFH.GBG2120700 .'`,
    where the space sits *before* the trailing dot and so survives the first
    TRIM. Verified over all 1,703,042 sales rows, this rule yields exactly
    2,260 distinct SKUs and 63,210 branch x SKU series - the control universe
    that raw `Oracle No` (2,147 values, 109 collisions) cannot reproduce.
    """
    if product_code is None:
        return ""
    code = str(product_code).strip().upper()
    code = _SKU_SUFFIX.sub("", code)
    return code.rstrip(".").strip()


def canonical_branch(branch: Any) -> str:
    """C6/C7. Collapses the 110 raw depot spellings to 53."""
    if branch is None:
        return ""
    return str(branch).strip().upper()


# --------------------------------------------------------------------------
# C2 - the FY 25-26 Product Name / HSN Code transposition
# --------------------------------------------------------------------------

#: An HSN code is 8 digits. Values arrive from the .xlsb as floats
#: (`70071100.0`), so the check is on the integer part.
_HSN_PATTERN = re.compile(r"^\d{6,8}$")


def looks_like_hsn(value: Any) -> bool:
    if value is None:
        return False
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    return bool(_HSN_PATTERN.match(text))


def looks_like_product_name(value: Any) -> bool:
    """Free text: contains a letter and is not a bare number."""
    if value is None:
        return False
    text = str(value).strip()
    return bool(text) and any(char.isalpha() for char in text) and not looks_like_hsn(text)


@dataclass
class TranspositionVerdict:
    is_transposed: bool
    rows_sampled: int
    hsn_in_name_column: int
    name_in_hsn_column: int
    confidence: float
    reason: str


def detect_transposition(
    sample_rows: list[tuple[Any, ...]], header: list[str], *, min_confidence: float = 0.9
) -> TranspositionVerdict:
    """Decide by VALUE PATTERN whether `HSN Code` and `Product Name` are
    swapped beneath their headers (rule C2 - "detect by type, not position").

    Both sales sheets declare the order `Product Code, HSN Code, Product Name`.
    FY 24-25's data matches it. FY 25-26's does not: it carries the name where
    the header says HSN, and the HSN where the header says name.
    """
    hsn_label, name_label = TRANSPOSED_PAIR
    if hsn_label not in header or name_label not in header:
        return TranspositionVerdict(
            False, 0, 0, 0, 0.0, f"Header lacks {hsn_label!r} or {name_label!r}."
        )
    hsn_index = header.index(hsn_label)
    name_index = header.index(name_label)

    sampled = 0
    swapped_evidence = 0
    correct_evidence = 0
    for row in sample_rows:
        if max(hsn_index, name_index) >= len(row):
            continue
        under_hsn_header = row[hsn_index]
        under_name_header = row[name_index]
        if under_hsn_header is None or under_name_header is None:
            continue
        sampled += 1
        # Swapped: a product name sits under the HSN header and an HSN code
        # sits under the name header.
        if looks_like_product_name(under_hsn_header) and looks_like_hsn(under_name_header):
            swapped_evidence += 1
        elif looks_like_hsn(under_hsn_header) and looks_like_product_name(under_name_header):
            correct_evidence += 1

    if sampled == 0:
        return TranspositionVerdict(False, 0, 0, 0, 0.0, "No comparable rows in the sample.")

    decided = swapped_evidence + correct_evidence
    if decided == 0:
        return TranspositionVerdict(
            False, sampled, 0, 0, 0.0, "No row matched either pattern; left untouched."
        )
    confidence = swapped_evidence / decided
    is_transposed = confidence >= min_confidence
    reason = (
        f"{swapped_evidence} of {decided} decidable rows carry a product name under "
        f"{hsn_label!r} and an HSN code under {name_label!r}."
        if is_transposed
        else f"{correct_evidence} of {decided} decidable rows match the declared header order."
    )
    return TranspositionVerdict(
        is_transposed, sampled, swapped_evidence, correct_evidence, confidence, reason
    )


def apply_transposition(row: tuple[Any, ...], hsn_index: int, name_index: int) -> list[Any]:
    """Swap the two values back into their declared columns."""
    values = list(row)
    values[hsn_index], values[name_index] = values[name_index], values[hsn_index]
    return values


# --------------------------------------------------------------------------
# C1 / C3 - name-based union of the two sales sheets
# --------------------------------------------------------------------------

@dataclass
class UnionPlan:
    """How to project one sheet's rows onto the shared column order.

    `indices[i]` is the position in this sheet's row that supplies shared
    column `i`, or None when the sheet lacks that column. Built from column
    NAMES so the extra `Doc Series` column in FY 24-25 cannot shift everything
    after it by one - the exact failure a positional union would cause.
    """

    shared_columns: list[str]
    indices: list[int | None]
    dropped_columns: list[str]
    missing_columns: list[str]


def build_union_plan(sheet_header: list[str], shared_columns: list[str]) -> UnionPlan:
    position = {name: index for index, name in enumerate(sheet_header)}
    indices: list[int | None] = [position.get(name) for name in shared_columns]
    dropped = [name for name in sheet_header if name not in set(shared_columns)]
    missing = [name for name, index in zip(shared_columns, indices, strict=True) if index is None]
    return UnionPlan(shared_columns, indices, dropped, missing)


def shared_columns_of(headers: list[list[str]]) -> list[str]:
    """Columns present in every sheet, in the first sheet's order."""
    if not headers:
        return []
    common = set(headers[0])
    for header in headers[1:]:
        common &= set(header)
    return [name for name in headers[0] if name in common]


def project_row(row: tuple[Any, ...] | list[Any], plan: UnionPlan) -> list[Any]:
    return [
        None if index is None or index >= len(row) else row[index] for index in plan.indices
    ]


# --------------------------------------------------------------------------
# C9 / C10 - canonical key vs Oracle No reconciliation
# --------------------------------------------------------------------------

@dataclass
class KeyReconciliationResult:
    canonical_sku_count: int = 0
    oracle_no_count: int = 0
    rows_missing_oracle: int = 0
    #: canonical SKU -> the several Oracle Nos it maps to (should be empty)
    disagreements: dict[str, list[str]] = field(default_factory=dict)
    #: Oracle No -> the several canonical SKUs sharing it (109 expected)
    collisions: dict[str, list[str]] = field(default_factory=dict)
    prefix_counts: dict[str, int] = field(default_factory=dict)

    @property
    def collision_count(self) -> int:
        return len(self.collisions)

    @property
    def disagreement_count(self) -> int:
        return len(self.disagreements)


class KeyReconciler:
    """Accumulates the canonical <-> Oracle mapping across a streaming pass."""

    def __init__(self) -> None:
        self._sku_to_oracle: dict[str, set[str]] = defaultdict(set)
        self._oracle_to_sku: dict[str, set[str]] = defaultdict(set)
        self._skus: set[str] = set()
        self._missing_oracle = 0
        self._prefixes: Counter[str] = Counter()

    def observe(self, product_code: Any, oracle_no: Any) -> str:
        sku = canonical_sku(product_code)
        if not sku:
            return ""
        self._skus.add(sku)
        self._prefixes[sku.split(".", 1)[0]] += 1
        oracle = str(oracle_no).strip().upper() if oracle_no is not None else ""
        if not oracle or oracle in {"NONE", "NAN"}:
            self._missing_oracle += 1
            return sku
        self._sku_to_oracle[sku].add(oracle)
        self._oracle_to_sku[oracle].add(sku)
        return sku

    def result(self) -> KeyReconciliationResult:
        return KeyReconciliationResult(
            canonical_sku_count=len(self._skus),
            oracle_no_count=len(self._oracle_to_sku),
            rows_missing_oracle=self._missing_oracle,
            disagreements={
                sku: sorted(oracles)
                for sku, oracles in self._sku_to_oracle.items()
                if len(oracles) > 1
            },
            collisions={
                oracle: sorted(skus)
                for oracle, skus in self._oracle_to_sku.items()
                if len(skus) > 1
            },
            prefix_counts=dict(self._prefixes),
        )

    @property
    def canonical_skus(self) -> set[str]:
        return self._skus


# --------------------------------------------------------------------------
# C15 - the Location Master footer row
# --------------------------------------------------------------------------

def is_location_footer_row(row: list[str], header: list[str]) -> bool:
    """Row 58 shifts values into the wrong columns: `Status` holds `57.52`.

    Detected structurally - a numeric value in a column that must hold a status
    word, or an empty branch code - rather than by trusting a row count.
    """
    if not row or not any(str(cell).strip() for cell in row):
        return True
    position = {name: index for index, name in enumerate(header)}
    code_index = position.get("Branch Code")
    if code_index is not None and code_index < len(row):
        if not str(row[code_index]).strip():
            return True
    status_index = position.get("Status")
    if status_index is not None and status_index < len(row):
        status = str(row[status_index]).strip()
        if status:
            try:
                float(status)
                return True  # a number where a status word belongs
            except ValueError:
                pass
    return False

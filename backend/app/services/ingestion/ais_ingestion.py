"""Streams the five AIS source files, applies rules C1-C16, and computes the
structural controls.

One pass per file, row-tuples throughout. The originals are opened read-only
and never written to. Progress is reported through a callback so the job runner
can surface it without this module knowing anything about jobs or HTTP.
"""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.logging import get_logger
from app.domain.ais import cleaning
from app.domain.ais.controls import (
    ControlInputs,
    ControlResult,
    LeadTimeStats,
    ServiceMeasures,
    evaluate_controls,
)
from app.domain.ais.source_spec import (
    ALL_PII_COLUMNS,
    DEAD_LOCATION_COLUMNS,
    LOCATION_MASTER_SPEC,
    MISSING_DATE_SENTINEL,
    NON_GLASS_PRODUCT_GROUPS,
    ORDERS_SPEC,
    PRODUCT_MASTER_SPEC,
    SALES_SPEC,
    STOCK_SPEC,
    SourceFileSpec,
    SourceRole,
)
from app.services.ingestion import readers

logger = get_logger(__name__)

ProgressFn = Callable[[str, float], None]

#: Rows sampled per sheet for the transposition verdict. Large enough to be
#: decisive, small enough to be free.
TRANSPOSITION_SAMPLE = 200

#: Cap on stored reconciliation findings per type, so a pathological source
#: cannot write millions of rows. The full counts are always reported.
MAX_STORED_FINDINGS = 500


@dataclass
class FileOutcome:
    role: SourceRole
    filename: str
    sheet_name: str | None
    size_bytes: int
    content_hash: str
    row_count: int
    column_count: int
    read_seconds: float
    columns: list[str]
    pii_columns: list[str] = field(default_factory=list)
    column_stats: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass
class DefectFinding:
    code: str
    title: str
    severity: str
    extent: str | None
    affected_rows: int | None
    source_role: str | None
    rule_applied: str | None
    fix_description: str
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class OrderKeys:
    """The order file carries two SKU-shaped columns, and they are NOT
    interchangeable.

    `Material Code` is `Oracle No` plus an `.AFM` suffix in the common case,
    but it yields 3,139 distinct canonical values against `Oracle No`'s 2,063 -
    roughly 1,076 spec variants that join no master row. Measured line-weighted
    coverage of the product master: 99.909% via `Oracle No`, 93.699% via
    `Material Code`. So `Oracle No` is the master join key in THIS file.

    That is the opposite of the sales file, where `Product Code` is the
    identity key (2,260 SKUs, 63,210 series) and `Oracle No` collides across
    109 groups. Different files, different reliable keys -
    docs/DECISIONS.md D-003.
    """

    oracle_skus: set[str] = field(default_factory=set)
    material_skus: set[str] = field(default_factory=set)
    lines_total: int = 0
    lines_joining_master_via_oracle: int = 0
    lines_joining_master_via_material: int = 0

    def coverage_via_oracle_pct(self) -> float | None:
        if not self.lines_total:
            return None
        return self.lines_joining_master_via_oracle / self.lines_total * 100

    def coverage_via_material_pct(self) -> float | None:
        if not self.lines_total:
            return None
        return self.lines_joining_master_via_material / self.lines_total * 100


@dataclass
class IngestionResult:
    files: list[FileOutcome] = field(default_factory=list)
    controls: list[ControlResult] = field(default_factory=list)
    defects: list[DefectFinding] = field(default_factory=list)
    reconciliation: cleaning.KeyReconciliationResult | None = None
    service_measures: ServiceMeasures | None = None
    lead_time: LeadTimeStats | None = None
    summary: dict[str, Any] = field(default_factory=dict)
    duration_seconds: float = 0.0

    @property
    def failed_controls(self) -> list[ControlResult]:
        return [control for control in self.controls if control.failed]


class _ColumnStatsAccumulator:
    """Streaming per-column stats.

    A PII column is counted but its values are never retained - no samples, no
    min, no max (rule C13).
    """

    def __init__(self, columns: list[str], pii: frozenset[str]) -> None:
        self.columns = columns
        self.pii = {name for name in columns if name in pii}
        self._non_null = Counter()
        self._distinct: dict[str, set[str]] = {name: set() for name in columns}
        self._distinct_overflow: set[str] = set()
        self._samples: dict[str, list[str]] = {name: [] for name in columns}
        self._numeric_sum: dict[str, float] = {}
        self._numeric_count: Counter = Counter()
        self._min: dict[str, str] = {}
        self._max: dict[str, str] = {}
        self._numeric_seen: Counter = Counter()
        self._rows = 0

    def observe(self, row: list[Any] | tuple[Any, ...]) -> None:
        self._rows += 1
        for index, name in enumerate(self.columns):
            value = row[index] if index < len(row) else None
            if value is None or value == "":
                continue
            self._non_null[name] += 1
            if name in self.pii:
                continue
            text = str(value)
            if name not in self._distinct_overflow:
                bucket = self._distinct[name]
                bucket.add(text)
                if len(bucket) > 20_000:
                    # Stop tracking exact cardinality rather than grow unbounded.
                    self._distinct_overflow.add(name)
                    bucket.clear()
            if len(self._samples[name]) < 5 and text not in self._samples[name]:
                self._samples[name].append(text[:120])
            numeric = readers.to_float(value)
            if numeric is not None:
                self._numeric_seen[name] += 1
                self._numeric_sum[name] = self._numeric_sum.get(name, 0.0) + numeric
                self._numeric_count[name] += 1
                low = self._min.get(name)
                if low is None or numeric < float(low):
                    self._min[name] = repr(numeric)
                high = self._max.get(name)
                if high is None or numeric > float(high):
                    self._max[name] = repr(numeric)

    def result(self) -> dict[str, dict[str, Any]]:
        stats: dict[str, dict[str, Any]] = {}
        for index, name in enumerate(self.columns):
            non_null = self._non_null[name]
            is_pii = name in self.pii
            overflowed = name in self._distinct_overflow
            distinct = None if is_pii or overflowed else len(self._distinct[name])
            numeric_share = (
                self._numeric_seen[name] / non_null if non_null else 0.0
            )
            detected = "numeric" if numeric_share >= 0.8 else ("text" if non_null else "empty")
            mean = (
                self._numeric_sum[name] / self._numeric_count[name]
                if self._numeric_count[name]
                else None
            )
            stats[name] = {
                "ordinal": index,
                "detected_type": detected,
                "non_null_count": non_null,
                "null_count": self._rows - non_null,
                "distinct_count": distinct,
                "is_constant": distinct == 1,
                "is_pii": is_pii,
                "min_value": None if is_pii else self._min.get(name),
                "max_value": None if is_pii else self._max.get(name),
                "mean_value": None if is_pii else mean,
                "sample_values": [] if is_pii else self._samples[name],
                "note": (
                    "PII - counted only; values never read into the profile or any payload."
                    if is_pii
                    else ("Cardinality above 20,000; exact distinct count not tracked." if overflowed else None)
                ),
            }
        return stats


def _open_rows(
    path: Path, spec: SourceFileSpec, sheet: str | None
) -> tuple[list[str], Any]:
    if spec.reader == "csv":
        return readers.read_csv_rows(path, skip_rows=spec.skip_rows)
    if spec.reader == "xlsx":
        return readers.read_xlsx_rows(path, sheet_name=sheet, skip_rows=spec.skip_rows)
    if spec.reader == "xlsb":
        if sheet is None:
            raise readers.SourceReadError("An .xlsb read requires an explicit sheet name.")
        return readers.read_xlsb_rows(path, sheet_name=sheet, skip_rows=spec.skip_rows)
    raise readers.SourceReadError(f"Unsupported reader {spec.reader!r}.")


def _describe(path: Path) -> tuple[int, str]:
    return path.stat().st_size, readers.file_sha256(path)


class AisIngestion:
    """Runs one full ingestion pass over the five source files."""

    def __init__(self, source_dir: Path, *, progress: ProgressFn | None = None) -> None:
        self.source_dir = source_dir
        self._progress = progress or (lambda _stage, _pct: None)

    def _report(self, stage: str, pct: float) -> None:
        logger.info("ingestion_progress", extra={"stage": stage, "progress_pct": round(pct, 1)})
        self._progress(stage, pct)

    def _path(self, spec: SourceFileSpec) -> Path:
        path = self.source_dir / spec.filename
        if not path.exists():
            raise readers.SourceReadError(f"Source file missing: {spec.filename}")
        return path

    # ------------------------------------------------------------------
    # Sales (rules C1, C2, C3, C4, C6, C8, C9, C13)
    # ------------------------------------------------------------------

    def _read_sales(self, result: IngestionResult) -> tuple[cleaning.KeyReconciler, set[tuple[str, str]], int]:
        spec = SALES_SPEC
        path = self._path(spec)
        size_bytes, content_hash = _describe(path)

        # Pass 1: headers only, to build a NAME-based union plan (C1/C3) and to
        # sample each sheet for the transposition verdict (C2).
        headers: dict[str, list[str]] = {}
        samples: dict[str, list[tuple[Any, ...]]] = {}
        for sheet in spec.sheets:
            header, rows = _open_rows(path, spec, sheet)
            headers[sheet] = header
            sample: list[tuple[Any, ...]] = []
            for row in rows:
                sample.append(row)
                if len(sample) >= TRANSPOSITION_SAMPLE:
                    break
            samples[sheet] = sample
        self._report("Sales: analysing sheet headers", 5.0)

        shared = cleaning.shared_columns_of([headers[sheet] for sheet in spec.sheets])
        plans = {sheet: cleaning.build_union_plan(headers[sheet], shared) for sheet in spec.sheets}

        dropped_by_sheet = {sheet: plan.dropped_columns for sheet, plan in plans.items()}
        for sheet, dropped in dropped_by_sheet.items():
            if dropped:
                result.defects.append(
                    DefectFinding(
                        code="D2",
                        title=f"Sheet-only column dropped after name-based union: {sheet}",
                        severity="corrected",
                        extent=", ".join(dropped),
                        affected_rows=None,
                        source_role=spec.role.value,
                        rule_applied="C1/C3",
                        fix_description=(
                            "Sheets are unioned by validated column NAME, never by position. "
                            "A positional union would shift every column after 'Doc Series' "
                            "by one in the FY 24-25 sheet."
                        ),
                        evidence={"sheet": sheet, "dropped_columns": dropped},
                    )
                )

        # Transposition verdict per sheet (C2)
        verdicts: dict[str, cleaning.TranspositionVerdict] = {}
        for sheet in spec.sheets:
            verdict = cleaning.detect_transposition(samples[sheet], headers[sheet])
            verdicts[sheet] = verdict
            if verdict.is_transposed:
                result.defects.append(
                    DefectFinding(
                        code="D1",
                        title=f"Product Name and HSN Code transposed beneath their headers: {sheet}",
                        severity="corrected",
                        extent=f"confidence {verdict.confidence:.1%} over {verdict.rows_sampled} sampled rows",
                        affected_rows=None,
                        source_role=spec.role.value,
                        rule_applied="C2",
                        fix_description=(
                            "Detected by value pattern, not position: an HSN code is 6-8 digits, "
                            "a product name is free text. The two values are swapped back into "
                            "their declared columns on every row of this sheet."
                        ),
                        evidence={
                            "sheet": sheet,
                            "reason": verdict.reason,
                            "rows_name_under_hsn_header": verdict.hsn_in_name_column,
                            "rows_matching_declared_order": verdict.name_in_hsn_column,
                        },
                    )
                )

        # Pass 2: the full streaming read.
        reconciler = cleaning.KeyReconciler()
        series: set[tuple[str, str]] = set()
        stats = _ColumnStatsAccumulator(shared, spec.pii_columns)
        position = {name: index for index, name in enumerate(shared)}
        code_index = position["Product Code"]
        oracle_index = position["Oracle No"]
        branch_index = position["Branch"]
        inv_date_index = position.get("Inv Date")
        month_index = position.get("Month")

        total_rows = 0
        bad_dates = 0
        month_mismatches = 0
        started = time.perf_counter()

        for sheet_number, sheet in enumerate(spec.sheets, start=1):
            header, rows = _open_rows(path, spec, sheet)
            plan = plans[sheet]
            verdict = verdicts[sheet]
            swap: tuple[int, int] | None = None
            if verdict.is_transposed:
                hsn_label, name_label = cleaning.TRANSPOSED_PAIR
                swap = (header.index(hsn_label), header.index(name_label))

            sheet_rows = 0
            for raw in rows:
                # C2 first, so the projection reads corrected values.
                row = cleaning.apply_transposition(raw, *swap) if swap else raw
                projected = cleaning.project_row(row, plan)
                sheet_rows += 1
                total_rows += 1

                sku = reconciler.observe(projected[code_index], projected[oracle_index])
                branch = cleaning.canonical_branch(projected[branch_index])
                if sku and branch:
                    series.add((branch, sku))

                # C4/C5: Excel serial conversion, then cross-check the Month field.
                if inv_date_index is not None:
                    converted = readers.excel_serial_to_date(projected[inv_date_index])
                    if converted is None and projected[inv_date_index] is not None:
                        bad_dates += 1
                    elif converted is not None and month_index is not None:
                        if not _month_matches(converted, projected[month_index]):
                            month_mismatches += 1

                stats.observe(projected)
                if total_rows % 200_000 == 0:
                    self._report(
                        f"Sales: {total_rows:,} rows read", 5.0 + 30.0 * (total_rows / 1_750_000)
                    )

            logger.info("sales_sheet_read", extra={"sheet": sheet, "rows": sheet_rows})
            self._report(f"Sales: finished {sheet}", 5.0 + 15.0 * sheet_number)

        read_seconds = time.perf_counter() - started

        if bad_dates:
            result.defects.append(
                DefectFinding(
                    code="D3",
                    title="Invoice dates outside the plausible Excel-serial range",
                    severity="recorded",
                    extent=f"{bad_dates:,} rows",
                    affected_rows=bad_dates,
                    source_role=spec.role.value,
                    rule_applied="C4",
                    fix_description=(
                        "Serials convert on the 1899-12-30 epoch. A value outside "
                        "20,000-60,000 is not a plausible date here and is recorded as "
                        "unconvertible rather than converted to a wrong date."
                    ),
                    evidence={"unconvertible_rows": bad_dates},
                )
            )
        if month_mismatches:
            result.defects.append(
                DefectFinding(
                    code="D15",
                    title="Converted invoice date disagrees with the Month field",
                    severity="recorded",
                    extent=f"{month_mismatches:,} rows",
                    affected_rows=month_mismatches,
                    source_role=spec.role.value,
                    rule_applied="C5",
                    fix_description=(
                        "Recorded as a defect, never used to silently overwrite either field."
                    ),
                    evidence={"mismatched_rows": month_mismatches},
                )
            )

        column_stats = stats.result()
        result.files.append(
            FileOutcome(
                role=spec.role,
                filename=spec.filename,
                sheet_name=" + ".join(spec.sheets),
                size_bytes=size_bytes,
                content_hash=content_hash,
                row_count=total_rows,
                column_count=len(shared),
                read_seconds=read_seconds,
                columns=shared,
                pii_columns=sorted(spec.pii_columns & set(shared)),
                column_stats=column_stats,
            )
        )
        return reconciler, series, total_rows

    # ------------------------------------------------------------------
    # Orders (rules C6, C7, C13, C14) + service measures
    # ------------------------------------------------------------------

    def _read_orders(
        self, result: IngestionResult, master_skus: set[str]
    ) -> tuple[int, set[str], OrderKeys, ServiceMeasures, LeadTimeStats]:
        spec = ORDERS_SPEC
        path = self._path(spec)
        size_bytes, content_hash = _describe(path)
        header, rows = _open_rows(path, spec, None)
        position = {name: index for index, name in enumerate(header)}

        stats = _ColumnStatsAccumulator(header, spec.pii_columns)
        measures = ServiceMeasures()
        lead_values: list[int] = []
        unparseable = 0
        negative = 0

        raw_depots: set[str] = set()
        normalized_depots: set[str] = set()
        keys = OrderKeys()
        sub_group_variants: Counter[str] = Counter()

        depot_index = position["Depo"]
        order_date_index = position["Order Date"]
        despatch_date_index = position["Despatch Date"]
        qty_index = position["Quantity"]
        despatch_qty_index = position["Despatch Qty"]
        material_index = position["Material Code"]
        oracle_index = position["Oracle No"]
        sub_group_index = position.get("Item Sub Grp")

        total_rows = 0
        started = time.perf_counter()
        for row in rows:
            total_rows += 1
            raw_depot = row[depot_index]
            if raw_depot is not None:
                raw_depots.add(str(raw_depot))
                normalized_depots.add(cleaning.canonical_branch(raw_depot))

            # Both key candidates are tracked so the coverage difference
            # between them is measured rather than assumed.
            oracle_sku = cleaning.canonical_sku(row[oracle_index])
            material_sku = cleaning.canonical_sku(row[material_index])
            keys.lines_total += 1
            if oracle_sku:
                keys.oracle_skus.add(oracle_sku)
                if oracle_sku in master_skus:
                    keys.lines_joining_master_via_oracle += 1
            if material_sku:
                keys.material_skus.add(material_sku)
                if material_sku in master_skus:
                    keys.lines_joining_master_via_material += 1

            if sub_group_index is not None and row[sub_group_index] is not None:
                sub_group_variants[str(row[sub_group_index])] += 1

            measures.observe(
                readers.to_float(row[qty_index]), readers.to_float(row[despatch_qty_index])
            )

            # C14: lead time only from parseable dates.
            ordered_on = readers.parse_loose_date(row[order_date_index])
            despatched_on = readers.parse_loose_date(row[despatch_date_index])
            if despatched_on is None or ordered_on is None:
                unparseable += 1
            else:
                days = (despatched_on - ordered_on).days
                if days < 0:
                    negative += 1
                else:
                    lead_values.append(days)

            stats.observe(row)
            if total_rows % 100_000 == 0:
                self._report(
                    f"Orders: {total_rows:,} lines read", 40.0 + 25.0 * (total_rows / 800_000)
                )

        read_seconds = time.perf_counter() - started
        lead_time = LeadTimeStats(lead_values, unparseable_dates=unparseable, negative_excluded=negative)

        if len(raw_depots) > len(normalized_depots):
            result.defects.append(
                DefectFinding(
                    code="D4",
                    title="Depot values differ only by case and whitespace",
                    severity="corrected",
                    extent=f"{len(raw_depots)} raw spellings collapse to {len(normalized_depots)}",
                    affected_rows=None,
                    source_role=spec.role.value,
                    rule_applied="C6/C7",
                    fix_description="TRIM then UPPER on landing, for every join key.",
                    evidence={
                        "raw_distinct": len(raw_depots),
                        "normalized_distinct": len(normalized_depots),
                    },
                )
            )
        case_variant_groups = _case_variant_groups(sub_group_variants)
        if case_variant_groups:
            result.defects.append(
                DefectFinding(
                    code="D5",
                    title="Item Sub Grp values differ only by case",
                    severity="corrected",
                    extent="; ".join(
                        f"{key}: " + ", ".join(f"{v}={c:,}" for v, c in variants)
                        for key, variants in case_variant_groups.items()
                    ),
                    affected_rows=None,
                    source_role=spec.role.value,
                    rule_applied="C6/C7",
                    fix_description="Normalised with the same TRIM+UPPER rule as every other key.",
                    evidence={"groups": {k: dict(v) for k, v in case_variant_groups.items()}},
                )
            )
        if negative or unparseable:
            result.defects.append(
                DefectFinding(
                    code="D10",
                    title="Corrupt despatch dates produce impossible lead times",
                    severity="corrected",
                    extent=f"{unparseable:,} unparseable, {negative:,} negative",
                    affected_rows=unparseable + negative,
                    source_role=spec.role.value,
                    rule_applied="C14",
                    fix_description=(
                        "The column contains '0000-00-00' and values yielding lead times down to "
                        "-8,763 days. Every lead-time statistic is computed on parseable, "
                        "non-negative values only; the exclusions are counted here rather than hidden."
                    ),
                    evidence={"unparseable": unparseable, "negative": negative},
                )
            )
        if measures.lines_over_delivered:
            result.defects.append(
                DefectFinding(
                    code="D11",
                    title="Order lines despatched beyond the quantity ordered",
                    severity="recorded",
                    extent=f"{measures.lines_over_delivered:,} lines, {measures.over_delivered:,} units",
                    affected_rows=measures.lines_over_delivered,
                    source_role=spec.role.value,
                    rule_applied=None,
                    fix_description=(
                        "Net and gross shortfall are therefore different numbers and are reported "
                        "separately. Collapsing them into one would hide this entirely."
                    ),
                    evidence=measures.as_dict(),
                )
            )

        oracle_coverage = keys.coverage_via_oracle_pct()
        material_coverage = keys.coverage_via_material_pct()
        if (
            oracle_coverage is not None
            and material_coverage is not None
            and oracle_coverage - material_coverage > 1.0
        ):
            result.defects.append(
                DefectFinding(
                    code="D17",
                    title="Material Code and Oracle No are not interchangeable join keys",
                    severity="recorded",
                    extent=(
                        f"{len(keys.material_skus):,} distinct via Material Code vs "
                        f"{len(keys.oracle_skus):,} via Oracle No; master coverage "
                        f"{material_coverage:.3f}% vs {oracle_coverage:.3f}%"
                    ),
                    affected_rows=keys.lines_total - keys.lines_joining_master_via_material,
                    source_role=spec.role.value,
                    rule_applied="C9",
                    fix_description=(
                        "Material Code carries spec variants that join no master row, so "
                        "Oracle No is the product-master join key in the ORDER file. Note "
                        "this is the opposite of the SALES file, where Product Code is the "
                        "identity key and Oracle No collides across 109 groups. Measured, "
                        "not assumed."
                    ),
                    evidence={
                        "distinct_material_code": len(keys.material_skus),
                        "distinct_oracle_no": len(keys.oracle_skus),
                        "line_coverage_via_material_pct": round(material_coverage, 3),
                        "line_coverage_via_oracle_pct": round(oracle_coverage, 3),
                    },
                )
            )

        result.files.append(
            FileOutcome(
                role=spec.role,
                filename=spec.filename,
                sheet_name=None,
                size_bytes=size_bytes,
                content_hash=content_hash,
                row_count=total_rows,
                column_count=len(header),
                read_seconds=read_seconds,
                columns=header,
                pii_columns=sorted(spec.pii_columns & set(header)),
                column_stats=stats.result(),
            )
        )
        return total_rows, normalized_depots, keys, measures, lead_time

    # ------------------------------------------------------------------
    # Stock (rules C11, C13) + defects D6, D7, D13
    # ------------------------------------------------------------------

    def _read_stock(self, result: IngestionResult) -> tuple[int, set[str], set[str]]:
        spec = STOCK_SPEC
        path = self._path(spec)
        size_bytes, content_hash = _describe(path)
        header, rows = _open_rows(path, spec, None)
        position = {name: index for index, name in enumerate(header)}

        stats = _ColumnStatsAccumulator(header, spec.pii_columns)
        branch_index = position["Branch"]
        code_index = position["Prod Code"]
        group_index = position["Prod Group"]
        qty_index = position["CLO QTY"]
        value_index = position["CLO VAL"]
        grn_index = position["Last GRN Date"]
        class_index = position.get("Classification")

        total_rows = 0
        negative_rows = 0
        negative_min = 0.0
        unclassified = 0
        stocked_rows = 0
        stocked_missing_grn = 0
        missing_grn_total = 0
        non_glass_rows = 0
        non_glass_groups: Counter[str] = Counter()
        stock_branches: set[str] = set()
        stock_skus: set[str] = set()
        total_value = 0.0
        started = time.perf_counter()

        for row in rows:
            total_rows += 1
            stock_branches.add(cleaning.canonical_branch(row[branch_index]))
            sku = cleaning.canonical_sku(row[code_index])
            if sku:
                stock_skus.add(sku)

            quantity = readers.to_float(row[qty_index]) or 0.0
            total_value += readers.to_float(row[value_index]) or 0.0
            if quantity < 0:
                negative_rows += 1
                negative_min = min(negative_min, quantity)
            if quantity > 0:
                stocked_rows += 1

            grn = str(row[grn_index]).strip() if row[grn_index] is not None else ""
            if grn.startswith(MISSING_DATE_SENTINEL):
                missing_grn_total += 1
                if quantity > 0:
                    stocked_missing_grn += 1

            if class_index is not None:
                value = row[class_index]
                if value is None or not str(value).strip():
                    unclassified += 1

            group = cleaning.canonical_branch(row[group_index])
            if group in NON_GLASS_PRODUCT_GROUPS:
                non_glass_rows += 1
                non_glass_groups[group] += 1

            stats.observe(row)
            if total_rows % 50_000 == 0:
                self._report(f"Stock: {total_rows:,} rows read", 65.0 + 8.0 * (total_rows / 150_000))

        read_seconds = time.perf_counter() - started

        if missing_grn_total:
            share = (stocked_missing_grn / stocked_rows * 100) if stocked_rows else 0.0
            result.defects.append(
                DefectFinding(
                    code="D6",
                    title="Last GRN Date coded 00-00-0000",
                    severity="recorded",
                    extent=(
                        f"{missing_grn_total:,} rows overall; {stocked_missing_grn:,} "
                        f"({share:.0f}%) of the {stocked_rows:,} rows that actually hold stock"
                    ),
                    affected_rows=missing_grn_total,
                    source_role=spec.role.value,
                    rule_applied="C12",
                    fix_description=(
                        "Recorded as missing_data, never as a true zero or a real date. Both the "
                        "overall count and the stocked-row count are reported - the analysis "
                        "document quotes only the latter."
                    ),
                    evidence={
                        "missing_overall": missing_grn_total,
                        "missing_on_stocked_rows": stocked_missing_grn,
                        "stocked_rows": stocked_rows,
                    },
                )
            )
        if unclassified:
            result.defects.append(
                DefectFinding(
                    code="D7",
                    title="Stock rows carry no A/B/C/D classification",
                    severity="recorded",
                    extent=f"{unclassified:,} of {total_rows:,} rows",
                    affected_rows=unclassified,
                    source_role=spec.role.value,
                    rule_applied="C12",
                    fix_description=(
                        "Marked 'unclassified' rather than silently folded into class D."
                    ),
                    evidence={"unclassified_rows": unclassified, "total_rows": total_rows},
                )
            )
        if negative_rows:
            result.defects.append(
                DefectFinding(
                    code="D9",
                    title="Negative closing stock",
                    severity="recorded",
                    extent=f"{negative_rows} rows, minimum {negative_min:.0f}",
                    affected_rows=negative_rows,
                    source_role=spec.role.value,
                    rule_applied="C11",
                    fix_description=(
                        "Preserved as visible data-quality exceptions. Excluded from usable stock "
                        "on hand, never deleted or clamped in place."
                    ),
                    evidence={"rows": negative_rows, "minimum": negative_min},
                )
            )
        if non_glass_rows:
            result.defects.append(
                DefectFinding(
                    code="D13",
                    title="Stock file covers non-glass product groups",
                    severity="recorded",
                    extent=f"{non_glass_rows:,} rows across {len(non_glass_groups)} groups",
                    affected_rows=non_glass_rows,
                    source_role=spec.role.value,
                    rule_applied=None,
                    fix_description=(
                        "Outside the glass forecast scope. Reported as 'stock without demand "
                        "history' rather than dropped, so the inventory value stays visible."
                    ),
                    evidence={"groups": dict(non_glass_groups)},
                )
            )

        result.files.append(
            FileOutcome(
                role=spec.role,
                filename=spec.filename,
                sheet_name=None,
                size_bytes=size_bytes,
                content_hash=content_hash,
                row_count=total_rows,
                column_count=len(header),
                read_seconds=read_seconds,
                columns=header,
                column_stats=stats.result(),
            )
        )
        result.summary["stock_total_value"] = total_value
        result.summary["stock_stocked_rows"] = stocked_rows
        return total_rows, stock_branches, stock_skus

    # ------------------------------------------------------------------
    # Product master + Location master (rules C13, C15, C16)
    # ------------------------------------------------------------------

    def _read_product_master(self, result: IngestionResult) -> tuple[int, set[str]]:
        spec = PRODUCT_MASTER_SPEC
        path = self._path(spec)
        size_bytes, content_hash = _describe(path)
        header, rows = _open_rows(path, spec, None)
        position = {name: index for index, name in enumerate(header)}
        code_index = position["Item Code (Oracle Code)"]
        stats = _ColumnStatsAccumulator(header, spec.pii_columns)

        master_skus: set[str] = set()
        total_rows = 0
        substitute_count = 0
        sub_index = position.get("Substition code -1")
        started = time.perf_counter()
        for row in rows:
            if not any(cell is not None and str(cell).strip() for cell in row):
                continue
            total_rows += 1
            sku = cleaning.canonical_sku(row[code_index])
            if sku:
                master_skus.add(sku)
            if sub_index is not None and row[sub_index] is not None and str(row[sub_index]).strip():
                substitute_count += 1
            stats.observe(row)
        read_seconds = time.perf_counter() - started

        result.defects.append(
            DefectFinding(
                code="D16",
                title="Substitution mapping is largely empty",
                severity="recorded",
                extent=f"{substitute_count} of {total_rows:,} SKUs have a substitute",
                affected_rows=substitute_count,
                source_role=spec.role.value,
                rule_applied=None,
                fix_description=(
                    "Substitution is treated as the exception, not the rule. Whether the map is "
                    "unfinished or substitution genuinely does not happen is an open question for "
                    "the business - the two imply very different inventory policies."
                ),
                evidence={"with_substitute": substitute_count, "total": total_rows},
            )
        )
        result.files.append(
            FileOutcome(
                role=spec.role, filename=spec.filename, sheet_name=None,
                size_bytes=size_bytes, content_hash=content_hash, row_count=total_rows,
                column_count=len(header), read_seconds=read_seconds, columns=header,
                column_stats=stats.result(),
            )
        )
        return total_rows, master_skus

    def _read_location_master(self, result: IngestionResult) -> tuple[int, set[str]]:
        spec = LOCATION_MASTER_SPEC
        path = self._path(spec)
        size_bytes, content_hash = _describe(path)
        header, rows = _open_rows(path, spec, None)
        position = {name: index for index, name in enumerate(header)}
        code_index = position["Branch Code"]
        stats = _ColumnStatsAccumulator(header, spec.pii_columns)

        branches: set[str] = set()
        total_rows = 0
        footer_rows = 0
        dead_columns: list[str] = []
        dead_tracker = {name: set() for name in DEAD_LOCATION_COLUMNS if name in position}
        started = time.perf_counter()

        for row in rows:
            row_list = [("" if cell is None else cell) for cell in row]
            if cleaning.is_location_footer_row(row_list, header):
                footer_rows += 1
                continue
            total_rows += 1
            branches.add(cleaning.canonical_branch(row_list[code_index]))
            for name in dead_tracker:
                dead_tracker[name].add(readers.to_float(row_list[position[name]]) or 0.0)
            stats.observe(row_list)
        read_seconds = time.perf_counter() - started

        dead_columns = [name for name, values in dead_tracker.items() if values <= {0.0}]

        if footer_rows:
            result.defects.append(
                DefectFinding(
                    code="D12",
                    title="Location master footer row shifts values into the wrong columns",
                    severity="corrected",
                    extent=f"{footer_rows} row(s)",
                    affected_rows=footer_rows,
                    source_role=spec.role.value,
                    rule_applied="C15",
                    fix_description=(
                        "Detected structurally - a numeric value in the Status column, or an empty "
                        "branch code - rather than by trusting a row count."
                    ),
                    evidence={"footer_rows": footer_rows},
                )
            )
        if dead_columns:
            result.defects.append(
                DefectFinding(
                    code="D8",
                    title="Replenishment columns are zero for every branch",
                    severity="recorded",
                    extent=", ".join(dead_columns),
                    affected_rows=total_rows,
                    source_role=spec.role.value,
                    rule_applied="C16",
                    fix_description="Never used in any calculation.",
                    evidence={"dead_columns": dead_columns, "branches": total_rows},
                )
            )

        result.files.append(
            FileOutcome(
                role=spec.role, filename=spec.filename, sheet_name=None,
                size_bytes=size_bytes, content_hash=content_hash, row_count=total_rows,
                column_count=len(header), read_seconds=read_seconds, columns=header,
                pii_columns=sorted(spec.pii_columns & set(header)),
                column_stats=stats.result(),
            )
        )
        return total_rows, branches

    # ------------------------------------------------------------------
    # Orchestration
    # ------------------------------------------------------------------

    def run(self, expected: dict[str, int], tolerance_pct: float) -> IngestionResult:
        result = IngestionResult()
        started = time.perf_counter()

        # The product master is read first so order-line coverage against it
        # can be measured during the order pass itself, line by line, rather
        # than approximated afterwards from distinct-value sets.
        self._report("Reading the product master", 1.0)
        master_rows, master_skus = self._read_product_master(result)

        self._report("Reading the sales workbook", 2.0)
        reconciler, series, sales_rows = self._read_sales(result)

        self._report("Reading the order workbook", 40.0)
        order_rows, depots, order_keys, measures, lead_time = self._read_orders(
            result, master_skus
        )

        self._report("Reading the stock snapshot", 65.0)
        stock_rows, stock_branches, stock_skus = self._read_stock(result)

        self._report("Reading the location master", 80.0)
        location_rows, master_branches = self._read_location_master(result)

        self._report("Reconciling keys and evaluating controls", 86.0)
        reconciliation = reconciler.result()
        # Line-weighted, via Oracle No - the measured join key for this file.
        coverage = order_keys.coverage_via_oracle_pct()

        controls = evaluate_controls(
            ControlInputs(
                sales_rows=sales_rows,
                order_rows=order_rows,
                stock_rows=stock_rows,
                product_master_rows=master_rows,
                location_master_rows=location_rows,
                canonical_sku_count=reconciliation.canonical_sku_count,
                series_count=len(series),
                normalized_depot_count=len({d for d in depots if d}),
                product_master_coverage_pct=coverage,
                lead_time=lead_time,
            ),
            expected,
            tolerance_pct,
        )

        result.controls = controls
        result.reconciliation = reconciliation
        result.service_measures = measures
        result.lead_time = lead_time
        result.duration_seconds = time.perf_counter() - started
        result.summary.update(
            {
                "series_count": len(series),
                "canonical_sku_count": reconciliation.canonical_sku_count,
                "oracle_no_count": reconciliation.oracle_no_count,
                "oracle_collisions": reconciliation.collision_count,
                "canonical_disagreements": reconciliation.disagreement_count,
                "rows_missing_oracle": reconciliation.rows_missing_oracle,
                "sku_prefixes": reconciliation.prefix_counts,
                # Four distinct branch universes; reconciled, never conflated.
                "branch_universes": {
                    "location_master": len(master_branches),
                    "stock": len({b for b in stock_branches if b}),
                    "order_depots": len({d for d in depots if d}),
                    "selling_branches": len({branch for branch, _ in series}),
                },
                "sku_universes": {
                    "sales": reconciliation.canonical_sku_count,
                    "orders_via_oracle_no": len(order_keys.oracle_skus),
                    "orders_via_material_code": len(order_keys.material_skus),
                    "stock": len(stock_skus),
                    "product_master": len(master_skus),
                    "sales_or_orders": len(
                        reconciler.canonical_skus | order_keys.oracle_skus
                    ),
                },
                "product_master_coverage_pct": coverage,
                "product_master_coverage": {
                    "measure": "line-weighted share of order lines joining the product master",
                    "via_oracle_no_pct": coverage,
                    "via_material_code_pct": order_keys.coverage_via_material_pct(),
                    "lines_total": order_keys.lines_total,
                    "lines_joined_via_oracle_no": order_keys.lines_joining_master_via_oracle,
                },
                "service_measures": measures.as_dict(),
                "lead_time": lead_time.as_dict(),
                "pii_columns_excluded": sorted(ALL_PII_COLUMNS),
            }
        )
        self._report("Ingestion complete", 100.0)
        return result


def _month_matches(converted, month_value: Any) -> bool:
    """C5: cross-check a converted date against the source's `Month` label
    (e.g. "Apr'25")."""
    if month_value is None:
        return True
    text = str(month_value).strip()
    if "'" not in text:
        return True
    name, year = text.split("'", 1)
    months = {
        "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
        "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
    }
    expected_month = months.get(name.strip().upper()[:3])
    if expected_month is None:
        return True
    try:
        expected_year = 2000 + int(year.strip()[:2])
    except ValueError:
        return True
    return converted.month == expected_month and converted.year == expected_year


def _case_variant_groups(counts: Counter[str]) -> dict[str, list[tuple[str, int]]]:
    """Group values that differ only by case/whitespace."""
    grouped: dict[str, list[tuple[str, int]]] = {}
    buckets: dict[str, list[tuple[str, int]]] = {}
    for value, count in counts.items():
        buckets.setdefault(value.strip().upper(), []).append((value, count))
    for key, variants in buckets.items():
        if len(variants) > 1:
            grouped[key] = sorted(variants, key=lambda pair: -pair[1])
    return grouped

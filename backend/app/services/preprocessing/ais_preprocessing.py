"""Builds the preprocessed dimension and fact tables from a confirmed mapping.

Output, written as Parquet with a versioned manifest:

- `branch_dim`   one row per canonical branch, with its hierarchy and lead times
- `product_dim`  one row per canonical SKU, with its attributes
- `order_fact`   canonical_branch x canonical_sku x month, ordered/despatched
- `sales_fact`   canonical_branch x canonical_sku x month, invoiced quantity
- `stock_position` canonical_branch x canonical_sku, the 1 Aug 2026 snapshot

Phase 4 builds the modelling panel on top of these. The two facts are kept
**separate** here rather than pre-merged, because the hybrid target
(docs/DECISIONS.md D-002) needs to know which source each period came from -
merging them now would erase `target_source`.
"""

from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from app.core.logging import get_logger
from app.domain.ais import cleaning
from app.domain.ais.source_spec import (
    LOCATION_MASTER_SPEC,
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


def month_key(value: date) -> str:
    return f"{value.year:04d}-{value.month:02d}"


@dataclass
class MonthlyFactRow:
    """One canonical_branch x canonical_sku x month cell.

    `is_censored` is set where ordered demand was not fully served, meaning
    true demand was *at least* the ordered quantity and possibly more.
    """

    branch: str
    sku: str
    period: str
    ordered_qty: float = 0.0
    despatched_qty: float = 0.0
    shortfall_qty: float = 0.0
    over_delivered_qty: float = 0.0
    line_count: int = 0
    mrp_sum: float = 0.0
    mrp_count: int = 0

    @property
    def is_censored(self) -> bool:
        return self.shortfall_qty > 0

    @property
    def mean_mrp(self) -> float | None:
        return self.mrp_sum / self.mrp_count if self.mrp_count else None


@dataclass
class PreprocessingResult:
    branch_dim: list[dict[str, Any]] = field(default_factory=list)
    product_dim: list[dict[str, Any]] = field(default_factory=list)
    order_fact: list[dict[str, Any]] = field(default_factory=list)
    sales_fact: list[dict[str, Any]] = field(default_factory=list)
    stock_position: list[dict[str, Any]] = field(default_factory=list)
    artifacts: dict[str, str] = field(default_factory=dict)
    summary: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0


class AisPreprocessing:
    """One preprocessing pass. Streams the sources again rather than caching
    the ingestion pass, so a re-run always reflects the files on disk."""

    def __init__(self, source_dir: Path, *, progress: ProgressFn | None = None) -> None:
        self.source_dir = source_dir
        self._progress = progress or (lambda _stage, _pct: None)

    def _report(self, stage: str, pct: float) -> None:
        logger.info("preprocessing_progress", extra={"stage": stage, "progress_pct": pct})
        self._progress(stage, pct)

    def _open(self, spec: SourceFileSpec, sheet: str | None = None):
        path = self.source_dir / spec.filename
        if not path.exists():
            raise readers.SourceReadError(f"Source file missing: {spec.filename}")
        if spec.reader == "csv":
            return readers.read_csv_rows(path, skip_rows=spec.skip_rows)
        if spec.reader == "xlsx":
            return readers.read_xlsx_rows(path, sheet_name=sheet, skip_rows=spec.skip_rows)
        return readers.read_xlsb_rows(path, sheet_name=sheet or "", skip_rows=spec.skip_rows)

    # ------------------------------------------------------------------
    # Dimensions
    # ------------------------------------------------------------------

    def _build_branch_dim(self, result: PreprocessingResult) -> dict[str, dict[str, Any]]:
        spec = LOCATION_MASTER_SPEC
        header, rows = self._open(spec)
        position = {name: index for index, name in enumerate(header)}
        dim: dict[str, dict[str, Any]] = {}

        for raw in rows:
            row = [("" if cell is None else cell) for cell in raw]
            if cleaning.is_location_footer_row(row, header):
                continue
            code = cleaning.canonical_branch(row[position["Branch Code"]])
            if not code:
                continue
            avg_lead = readers.to_float(row[position.get("Avg Lead Time", -1)]) if "Avg Lead Time" in position else None
            dim[code] = {
                "canonical_branch": code,
                "branch_name": str(row[position["Branch Name"]]).strip(),
                "region": cleaning.canonical_branch(row[position["Region"]]),
                "zone": cleaning.canonical_branch(row[position["Zone"]]),
                "supply_hub": cleaning.canonical_branch(row[position["Supply Hub"]]),
                "tier": str(row[position["Tier"]]).strip(),
                "branch_type": str(row[position.get("Branch Type", -1)]).strip()
                if "Branch Type" in position else None,
                "city": str(row[position.get("City", -1)]).strip() if "City" in position else None,
                "state": str(row[position.get("State", -1)]).strip() if "State" in position else None,
                "status": str(row[position["Status"]]).strip(),
                # Capacity columns. Lead time drives the protection period in
                # the inventory calculation (docs/AIS_DOMAIN_RULES.md SS4).
                "avg_lead_time_days": avg_lead,
                "std_lead_time_days": readers.to_float(row[position["Std. LeadTime"]])
                if "Std. LeadTime" in position else None,
                "transit_lead_time_days": readers.to_float(row[position["Transit Lead Time"]])
                if "Transit Lead Time" in position else None,
                "service_factor": readers.to_float(row[position["Service Factor"]])
                if "Service Factor" in position else None,
                "truck_moq": readers.to_float(row[position["Truck (MoQ)"]])
                if "Truck (MoQ)" in position else None,
                "in_location_master": True,
                "sells": False,
                "orders": False,
                "holds_stock": False,
            }
        result.summary["branch_dim_from_master"] = len(dim)
        return dim

    def _build_product_dim(self, result: PreprocessingResult) -> dict[str, dict[str, Any]]:
        spec = PRODUCT_MASTER_SPEC
        header, rows = self._open(spec)
        position = {name: index for index, name in enumerate(header)}
        sales_category_column = next(
            (name for name in header if name.startswith("Sales Category")), None
        )
        dim: dict[str, dict[str, Any]] = {}

        for row in rows:
            if not any(cell is not None and str(cell).strip() for cell in row):
                continue
            sku = cleaning.canonical_sku(row[position["Item Code (Oracle Code)"]])
            if not sku:
                continue
            substitute_1 = row[position.get("Substition code -1", -1)] if "Substition code -1" in position else None
            substitute_2 = row[position.get("Substition code -2", -1)] if "Substition code -2" in position else None
            dim[sku] = {
                "canonical_sku": sku,
                "vehicle_age_category": _clean_text(row[position.get("Vehicle Age Category", -1)])
                if "Vehicle Age Category" in position else None,
                # Normalised: the master carries 'Car & Muv' and 'Car & MUV'.
                "vehicle_category": cleaning.canonical_branch(row[position["Vehicle Category"]])
                if "Vehicle Category" in position else None,
                "oem": _clean_text(row[position.get("OEM", -1)]) if "OEM" in position else None,
                # Normalised: 'Non-OEM' and 'NON-OEM' both appear.
                "oem_status": cleaning.canonical_branch(row[position["OEM/Non-OEM"]])
                if "OEM/Non-OEM" in position else None,
                "glass_type": _clean_text(row[position.get("Glass\nType", -1)])
                if "Glass\nType" in position else None,
                "product_group": cleaning.canonical_branch(row[position["Product Group"]])
                if "Product Group" in position else None,
                "value_class": _clean_text(row[position[sales_category_column]])
                if sales_category_column else None,
                "substitute_sku_1": cleaning.canonical_sku(substitute_1) or None,
                "substitute_sku_2": cleaning.canonical_sku(substitute_2) or None,
                "has_substitute": bool(cleaning.canonical_sku(substitute_1)),
                "in_product_master": True,
                "sells": False,
                "ordered": False,
                "held_in_stock": False,
                "is_non_glass": False,
            }
        result.summary["product_dim_from_master"] = len(dim)
        return dim

    # ------------------------------------------------------------------
    # Facts
    # ------------------------------------------------------------------

    def _build_order_fact(
        self,
        result: PreprocessingResult,
        branch_dim: dict[str, dict[str, Any]],
        product_dim: dict[str, dict[str, Any]],
    ) -> None:
        spec = ORDERS_SPEC
        header, rows = self._open(spec)
        position = {name: index for index, name in enumerate(header)}
        depot_index = position["Depo"]
        oracle_index = position["Oracle No"]
        date_index = position["Order Date"]
        qty_index = position["Quantity"]
        despatch_qty_index = position["Despatch Qty"]
        mrp_index = position.get("MRP Rate")

        cells: dict[tuple[str, str, str], MonthlyFactRow] = {}
        unmapped_dates = 0
        unknown_branches: set[str] = set()
        unknown_skus: set[str] = set()
        processed = 0

        for row in rows:
            processed += 1
            ordered_on = readers.parse_loose_date(row[date_index])
            if ordered_on is None:
                unmapped_dates += 1
                continue
            branch = cleaning.canonical_branch(row[depot_index])
            # The order file's master join key is Oracle No, not Material Code
            # (docs/DECISIONS.md D-017).
            sku = cleaning.canonical_sku(row[oracle_index])
            if not branch or not sku:
                continue

            key = (branch, sku, month_key(ordered_on))
            cell = cells.get(key)
            if cell is None:
                cell = MonthlyFactRow(branch=branch, sku=sku, period=key[2])
                cells[key] = cell

            ordered = readers.to_float(row[qty_index]) or 0.0
            despatched = readers.to_float(row[despatch_qty_index]) or 0.0
            cell.ordered_qty += ordered
            cell.despatched_qty += despatched
            cell.line_count += 1
            gap = ordered - despatched
            if gap > 0:
                cell.shortfall_qty += gap
            elif gap < 0:
                cell.over_delivered_qty += -gap
            if mrp_index is not None:
                mrp = readers.to_float(row[mrp_index])
                if mrp is not None and mrp > 0:
                    cell.mrp_sum += mrp
                    cell.mrp_count += 1

            if branch in branch_dim:
                branch_dim[branch]["orders"] = True
            else:
                unknown_branches.add(branch)
            if sku in product_dim:
                product_dim[sku]["ordered"] = True
            else:
                unknown_skus.add(sku)

            if processed % 200_000 == 0:
                self._report(f"Orders: {processed:,} lines aggregated", 20.0 + 20.0 * (processed / 800_000))

        result.order_fact = [
            {
                "canonical_branch": cell.branch,
                "canonical_sku": cell.sku,
                "period": cell.period,
                "ordered_qty": cell.ordered_qty,
                "despatched_qty": cell.despatched_qty,
                "shortfall_qty": cell.shortfall_qty,
                "over_delivered_qty": cell.over_delivered_qty,
                "is_censored": cell.is_censored,
                "line_count": cell.line_count,
                "mean_mrp": cell.mean_mrp,
            }
            for cell in cells.values()
        ]
        result.summary["order_fact"] = {
            "cells": len(cells),
            "lines_processed": processed,
            "lines_without_a_usable_date": unmapped_dates,
            "branches_not_in_location_master": sorted(unknown_branches),
            "skus_not_in_product_master": len(unknown_skus),
            "censored_cells": sum(1 for c in cells.values() if c.is_censored),
            "periods": sorted({c.period for c in cells.values()}),
        }
        if unknown_branches:
            result.warnings.append(
                f"{len(unknown_branches)} order depot(s) are absent from Location Master: "
                f"{sorted(unknown_branches)}. Their rows are kept and flagged, not dropped."
            )

    def _build_sales_fact(
        self,
        result: PreprocessingResult,
        branch_dim: dict[str, dict[str, Any]],
        product_dim: dict[str, dict[str, Any]],
    ) -> None:
        spec = SALES_SPEC
        cells: dict[tuple[str, str, str], MonthlyFactRow] = {}
        unmapped_dates = 0
        unknown_branches: set[str] = set()
        processed = 0

        # Header analysis first: name-based union plan and the FY 25-26
        # transposition verdict (rules C1, C2, C3).
        headers: dict[str, list[str]] = {}
        samples: dict[str, list[tuple[Any, ...]]] = {}
        for sheet in spec.sheets:
            header, rows = self._open(spec, sheet)
            headers[sheet] = header
            sample: list[tuple[Any, ...]] = []
            for row in rows:
                sample.append(row)
                if len(sample) >= 200:
                    break
            samples[sheet] = sample

        shared = cleaning.shared_columns_of([headers[sheet] for sheet in spec.sheets])
        plans = {sheet: cleaning.build_union_plan(headers[sheet], shared) for sheet in spec.sheets}
        verdicts = {
            sheet: cleaning.detect_transposition(samples[sheet], headers[sheet])
            for sheet in spec.sheets
        }
        position = {name: index for index, name in enumerate(shared)}
        branch_index = position["Branch"]
        code_index = position["Product Code"]
        date_index = position["Inv Date"]
        qty_index = position["Quantity"]
        mrp_index = position.get("AIS\nMRP")

        for sheet in spec.sheets:
            header, rows = self._open(spec, sheet)
            plan = plans[sheet]
            swap: tuple[int, int] | None = None
            if verdicts[sheet].is_transposed:
                hsn_label, name_label = cleaning.TRANSPOSED_PAIR
                swap = (header.index(hsn_label), header.index(name_label))

            for raw in rows:
                processed += 1
                row = cleaning.apply_transposition(raw, *swap) if swap else raw
                projected = cleaning.project_row(row, plan)

                invoiced_on = readers.excel_serial_to_date(projected[date_index])
                if invoiced_on is None:
                    unmapped_dates += 1
                    continue
                branch = cleaning.canonical_branch(projected[branch_index])
                sku = cleaning.canonical_sku(projected[code_index])
                if not branch or not sku:
                    continue

                key = (branch, sku, month_key(invoiced_on))
                cell = cells.get(key)
                if cell is None:
                    cell = MonthlyFactRow(branch=branch, sku=sku, period=key[2])
                    cells[key] = cell
                cell.ordered_qty += readers.to_float(projected[qty_index]) or 0.0
                cell.line_count += 1
                if mrp_index is not None:
                    mrp = readers.to_float(projected[mrp_index])
                    if mrp is not None and mrp > 0:
                        cell.mrp_sum += mrp
                        cell.mrp_count += 1

                if branch in branch_dim:
                    branch_dim[branch]["sells"] = True
                else:
                    unknown_branches.add(branch)
                if sku in product_dim:
                    product_dim[sku]["sells"] = True

                if processed % 300_000 == 0:
                    self._report(
                        f"Sales: {processed:,} rows aggregated",
                        45.0 + 35.0 * (processed / 1_750_000),
                    )

        result.sales_fact = [
            {
                "canonical_branch": cell.branch,
                "canonical_sku": cell.sku,
                "period": cell.period,
                # Invoiced quantity. A CENSORED signal: it records what was
                # available to sell, not what was wanted. Never merged with
                # ordered quantity without a target_source label.
                "invoiced_qty": cell.ordered_qty,
                "line_count": cell.line_count,
                "mean_mrp": cell.mean_mrp,
            }
            for cell in cells.values()
        ]
        result.summary["sales_fact"] = {
            "cells": len(cells),
            "rows_processed": processed,
            "rows_without_a_usable_date": unmapped_dates,
            "branches_not_in_location_master": sorted(unknown_branches),
            "periods": sorted({c.period for c in cells.values()}),
            "transposition_corrected": [
                sheet for sheet, verdict in verdicts.items() if verdict.is_transposed
            ],
            "columns_dropped_by_name_union": {
                sheet: plan.dropped_columns for sheet, plan in plans.items()
            },
        }

    def _build_stock_position(
        self,
        result: PreprocessingResult,
        branch_dim: dict[str, dict[str, Any]],
        product_dim: dict[str, dict[str, Any]],
    ) -> set[str]:
        spec = STOCK_SPEC
        header, rows = self._open(spec)
        position = {name: index for index, name in enumerate(header)}
        aggregated: dict[tuple[str, str], dict[str, Any]] = {}
        negative_rows = 0
        non_glass_rows = 0
        non_glass_orphans: set[str] = set()

        for row in rows:
            branch = cleaning.canonical_branch(row[position["Branch"]])
            sku = cleaning.canonical_sku(row[position["Prod Code"]])
            if not branch or not sku:
                continue
            quantity = readers.to_float(row[position["CLO QTY"]]) or 0.0
            group = cleaning.canonical_branch(row[position["Prod Group"]])
            is_non_glass = group in NON_GLASS_PRODUCT_GROUPS
            if is_non_glass:
                non_glass_rows += 1
            if quantity < 0:
                negative_rows += 1

            key = (branch, sku)
            entry = aggregated.setdefault(
                key,
                {
                    "canonical_branch": branch,
                    "canonical_sku": sku,
                    "closing_qty": 0.0,
                    "closing_value": 0.0,
                    "mrp_value": 0.0,
                    # Rule C11: negative stock is preserved as a visible
                    # exception and excluded from usable stock, never clamped
                    # in place or deleted.
                    "has_negative_row": False,
                    "usable_qty": 0.0,
                    "stock_class": None,
                    "product_group": group,
                    "is_non_glass": is_non_glass,
                    "last_grn_date": None,
                    "grn_date_missing": False,
                },
            )
            entry["closing_qty"] += quantity
            entry["closing_value"] += readers.to_float(row[position["CLO VAL"]]) or 0.0
            entry["mrp_value"] += readers.to_float(row[position["MRP VAL"]]) or 0.0
            if quantity < 0:
                entry["has_negative_row"] = True
            else:
                entry["usable_qty"] += quantity

            classification = row[position.get("Classification", -1)] if "Classification" in position else None
            if classification is not None and str(classification).strip():
                entry["stock_class"] = str(classification).strip()
            grn = row[position["Last GRN Date"]]
            parsed_grn = readers.parse_loose_date(grn)
            if parsed_grn is None:
                entry["grn_date_missing"] = True
            else:
                existing = entry["last_grn_date"]
                iso = parsed_grn.isoformat()
                if existing is None or iso > existing:
                    entry["last_grn_date"] = iso

            if branch in branch_dim:
                branch_dim[branch]["holds_stock"] = True
            if sku in product_dim:
                product_dim[sku]["held_in_stock"] = True
                product_dim[sku]["is_non_glass"] = is_non_glass
            elif is_non_glass:
                # Non-glass SKUs are almost never in the product master, which
                # covers glass only. Recording the flag here would be lost when
                # the orphan row is created later, so it is collected and
                # applied after orphan creation - otherwise defect D13's
                # non-glass population silently reports zero.
                non_glass_orphans.add(sku)

        result.stock_position = list(aggregated.values())
        result.summary["stock_position"] = {
            "rows": len(aggregated),
            "negative_source_rows": negative_rows,
            "non_glass_source_rows": non_glass_rows,
            "unclassified_cells": sum(1 for e in aggregated.values() if e["stock_class"] is None),
            "cells_with_stock": sum(1 for e in aggregated.values() if e["usable_qty"] > 0),
            "total_usable_qty": sum(e["usable_qty"] for e in aggregated.values()),
            "total_closing_value": sum(e["closing_value"] for e in aggregated.values()),
            "non_glass_skus_outside_product_master": len(non_glass_orphans),
        }
        return non_glass_orphans

    # ------------------------------------------------------------------
    # Orchestration
    # ------------------------------------------------------------------

    def run(self, output_dir: Path) -> PreprocessingResult:
        result = PreprocessingResult()
        started = time.perf_counter()

        self._report("Building the branch dimension", 2.0)
        branch_dim = self._build_branch_dim(result)

        self._report("Building the product dimension", 6.0)
        product_dim = self._build_product_dim(result)

        self._report("Aggregating the order fact", 20.0)
        self._build_order_fact(result, branch_dim, product_dim)

        self._report("Aggregating the sales fact", 45.0)
        self._build_sales_fact(result, branch_dim, product_dim)

        self._report("Building the stock position", 82.0)
        non_glass_orphans = self._build_stock_position(result, branch_dim, product_dim)

        # Branches and SKUs seen in a fact but absent from their master are
        # added here rather than dropped, flagged so the gap stays visible.
        for fact_rows, branch_field, sku_field in (
            (result.order_fact, "canonical_branch", "canonical_sku"),
            (result.sales_fact, "canonical_branch", "canonical_sku"),
            (result.stock_position, "canonical_branch", "canonical_sku"),
        ):
            for row in fact_rows:
                branch = row[branch_field]
                if branch not in branch_dim:
                    branch_dim[branch] = _orphan_branch(branch)
                sku = row[sku_field]
                if sku not in product_dim:
                    product_dim[sku] = _orphan_product(sku)

        # Apply the non-glass flag now that every orphan row exists. Doing it
        # during the stock pass would lose it for SKUs absent from the product
        # master - which is most non-glass items, since that master is glass-only.
        for sku in non_glass_orphans:
            if sku in product_dim:
                product_dim[sku]["is_non_glass"] = True

        result.branch_dim = list(branch_dim.values())
        result.product_dim = list(product_dim.values())

        self._report("Writing Parquet artifacts", 90.0)
        result.artifacts = _write_parquet(output_dir, result)

        periods = sorted(
            {row["period"] for row in result.order_fact}
            | {row["period"] for row in result.sales_fact}
        )
        series = {
            (row["canonical_branch"], row["canonical_sku"])
            for row in result.order_fact + result.sales_fact
        }
        result.summary.update(
            {
                "branch_dim_rows": len(result.branch_dim),
                "product_dim_rows": len(result.product_dim),
                "distinct_series": len(series),
                "distinct_periods": len(periods),
                "period_range": [periods[0], periods[-1]] if periods else [],
                "periods": periods,
                # The hybrid target's two windows, kept separable so
                # target_source can be assigned in Phase 4.
                "order_periods": sorted({row["period"] for row in result.order_fact}),
                "sales_periods": sorted({row["period"] for row in result.sales_fact}),
                "branch_universes": {
                    "in_location_master": sum(
                        1 for b in result.branch_dim if b.get("in_location_master")
                    ),
                    "sells": sum(1 for b in result.branch_dim if b.get("sells")),
                    "orders": sum(1 for b in result.branch_dim if b.get("orders")),
                    "holds_stock": sum(1 for b in result.branch_dim if b.get("holds_stock")),
                },
                "sku_universes": {
                    "in_product_master": sum(
                        1 for p in result.product_dim if p.get("in_product_master")
                    ),
                    "sells": sum(1 for p in result.product_dim if p.get("sells")),
                    "ordered": sum(1 for p in result.product_dim if p.get("ordered")),
                    "held_in_stock": sum(1 for p in result.product_dim if p.get("held_in_stock")),
                    "non_glass": sum(1 for p in result.product_dim if p.get("is_non_glass")),
                },
            }
        )
        result.duration_seconds = time.perf_counter() - started
        self._report("Preprocessing complete", 100.0)
        return result


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _orphan_branch(code: str) -> dict[str, Any]:
    return {
        "canonical_branch": code, "branch_name": code, "region": None, "zone": None,
        "supply_hub": None, "tier": None, "branch_type": None, "city": None,
        "state": None, "status": None, "avg_lead_time_days": None,
        "std_lead_time_days": None, "transit_lead_time_days": None,
        "service_factor": None, "truck_moq": None,
        "in_location_master": False, "sells": False, "orders": False,
        "holds_stock": False,
    }


def _orphan_product(sku: str) -> dict[str, Any]:
    return {
        "canonical_sku": sku, "vehicle_age_category": None, "vehicle_category": None,
        "oem": None, "oem_status": None, "glass_type": None, "product_group": None,
        "value_class": None, "substitute_sku_1": None, "substitute_sku_2": None,
        "has_substitute": False, "in_product_master": False, "sells": False,
        "ordered": False, "held_in_stock": False, "is_non_glass": False,
    }


def _write_parquet(output_dir: Path, result: PreprocessingResult) -> dict[str, str]:
    import pyarrow as pa
    import pyarrow.parquet as pq

    output_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, str] = {}
    tables = {
        "branch_dim": result.branch_dim,
        "product_dim": result.product_dim,
        "order_fact": result.order_fact,
        "sales_fact": result.sales_fact,
        "stock_position": result.stock_position,
    }
    for name, rows in tables.items():
        path = output_dir / f"{name}.parquet"
        if not rows:
            # An empty table still gets a file, so a downstream reader fails on
            # empty data rather than on a missing path.
            pq.write_table(pa.table({}), path)
        else:
            pq.write_table(pa.Table.from_pylist(rows), path, compression="snappy")
        written[name] = str(path)
    return written

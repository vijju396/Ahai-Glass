"""Assembles the AIS monthly panel from the preprocessed dimension and fact tables.

Two decisions carried forward from Phase 3 are settled here, explicitly:

**The series universe is the demand-bearing union of the order and sales
facts** - branch x SKU pairs that actually ordered or sold something. It is
*not* the 63,210 control: that control counts branch x SKU in the sales file
alone and stays a check on the canonical key (docs/VALIDATION_REPORT.md S7).
Stock-only pairs are excluded, because a pair with stock and no demand history
has nothing to forecast from; they remain visible in `stock_position`
(docs/DECISIONS.md D-005, D-025).

**The target is hybrid, and every row says which source it came from**
(D-002). Ordered quantity is the truth. The invoiced-sales period is a
`sales_proxy`: a censored signal recording what was available to sell, not what
was wanted. The two windows are read from the facts themselves rather than
hardcoded, and orders win wherever they overlap.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from app.core.logging import get_logger
from app.ml.features.feature_builder import (
    DEFAULT_HORIZONS,
    build_feature_manifest,
    build_origin_features,
    build_scoring_frame,
    build_training_frame,
)
from app.ml.features.panel import (
    build_period_grid,
    index_to_period,
    month_index,
    summarise_sparsity,
)

logger = get_logger(__name__)

ProgressFn = Callable[[str, float], None]

#: Static attributes constant per series, so knowable in advance for every
#: horizon. These are the only AIS columns permitted as future-known features
#: (docs/DECISIONS.md D-002; the mapping template's FUTURE_KNOWN_COLUMNS).
STATIC_FEATURE_COLUMNS: tuple[str, ...] = (
    "region",
    "zone",
    "supply_hub",
    "tier",
    "product_group",
    "vehicle_category",
    "vehicle_age_category",
    "glass_type",
    "oem_status",
    "value_class",
)

#: Columns carried on the panel for inventory and diagnostics but NOT fed to a
#: model as future-known. MRP can change; stock is a single snapshot.
CONTEXT_COLUMNS: tuple[str, ...] = (
    "mean_mrp",
    "avg_lead_time_days",
    "std_lead_time_days",
    "truck_moq",
    "closing_qty",
    "usable_qty",
    "closing_value",
    "stock_class",
    "has_substitute",
    "substitute_sku_1",
)


@dataclass
class PanelResult:
    panel_rows: int = 0
    series_count: int = 0
    period_count: int = 0
    training_rows: int = 0
    scoring_rows: int = 0
    artifacts: dict[str, str] = field(default_factory=dict)
    summary: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0


class AisPanelBuilder:
    """Builds the panel, the origin features, and the training/scoring frames."""

    def __init__(self, artifacts: dict[str, str], *, progress: ProgressFn | None = None) -> None:
        self.artifacts = artifacts
        self._progress = progress or (lambda _stage, _pct: None)

    def _report(self, stage: str, pct: float) -> None:
        logger.info("panel_progress", extra={"stage": stage, "progress_pct": pct})
        self._progress(stage, pct)

    def _read(self, name: str) -> pd.DataFrame:
        path = self.artifacts.get(name)
        if not path or not Path(path).exists():
            raise FileNotFoundError(
                f"Preprocessed table {name!r} is missing. Run preprocessing first."
            )
        return pd.read_parquet(path)

    # ------------------------------------------------------------------
    # The hybrid target
    # ------------------------------------------------------------------

    def _build_observations(
        self, order_fact: pd.DataFrame, sales_fact: pd.DataFrame, result: PanelResult
    ) -> pd.DataFrame:
        """One observation per series x month, with its source labelled.

        Windows come from the facts, not from constants, so a new extract with
        a different span needs no code change.
        """
        order_fact = order_fact.copy()
        sales_fact = sales_fact.copy()
        order_fact["period_index"] = order_fact["period"].map(month_index)
        sales_fact["period_index"] = sales_fact["period"].map(month_index)

        order_window = (
            int(order_fact["period_index"].min()),
            int(order_fact["period_index"].max()),
        )
        sales_window = (
            int(sales_fact["period_index"].min()),
            int(sales_fact["period_index"].max()),
        )

        order_fact["series_id"] = (
            order_fact["canonical_branch"] + "|" + order_fact["canonical_sku"]
        )
        sales_fact["series_id"] = (
            sales_fact["canonical_branch"] + "|" + sales_fact["canonical_sku"]
        )

        orders = order_fact.rename(columns={"ordered_qty": "target"})[
            [
                "series_id", "canonical_branch", "canonical_sku", "period_index",
                "target", "despatched_qty", "shortfall_qty", "over_delivered_qty",
                "is_censored", "line_count", "mean_mrp",
            ]
        ].copy()
        orders["target_source"] = "order"

        # The proxy contributes only months the order book does not cover.
        # Orders win on overlap (D-002), so this is a period filter, not a
        # row-level preference: inside the order window, a series with no order
        # row has genuinely zero ordered demand, and its invoiced sales must not
        # overwrite that.
        proxy_periods = sales_fact["period_index"] < order_window[0]
        proxy = sales_fact.loc[proxy_periods].rename(
            columns={"invoiced_qty": "target"}
        )[
            ["series_id", "canonical_branch", "canonical_sku", "period_index",
             "target", "line_count", "mean_mrp"]
        ].copy()
        proxy["target_source"] = "sales_proxy"
        # Typed explicitly rather than assigned pd.NA: an all-NA object column
        # makes pandas warn about concat dtype inference, and would leave the
        # column object-typed in the Parquet output.
        for column in ("despatched_qty", "shortfall_qty", "over_delivered_qty"):
            proxy[column] = pd.Series([pd.NA] * len(proxy), dtype="Float64")
        # Censoring is unknowable from an invoice: the invoice records what was
        # sold, and nothing about what was asked for. Nullable, not False.
        proxy["is_censored"] = pd.Series([pd.NA] * len(proxy), dtype="boolean")

        orders["is_censored"] = orders["is_censored"].astype("boolean")
        for column in ("despatched_qty", "shortfall_qty", "over_delivered_qty"):
            orders[column] = orders[column].astype("Float64")

        observations = pd.concat([orders, proxy], ignore_index=True)

        dropped_overlap = int((~proxy_periods).sum())
        result.summary["target_windows"] = {
            "order_window": [index_to_period(order_window[0]), index_to_period(order_window[1])],
            "sales_window": [index_to_period(sales_window[0]), index_to_period(sales_window[1])],
            "sales_rows_superseded_by_orders": dropped_overlap,
            "note": (
                "Ordered quantity is the target. Inside the order window a series "
                "with no order row has genuinely zero ordered demand, so invoiced "
                "sales are not substituted there. The proxy covers only months "
                "before the order book begins."
            ),
        }
        if dropped_overlap:
            result.warnings.append(
                f"{dropped_overlap:,} sales-fact rows fall inside the order window "
                "and were superseded by the order book rather than merged. They "
                "remain available in sales_fact."
            )
        return observations

    # ------------------------------------------------------------------
    # Orchestration
    # ------------------------------------------------------------------

    def run(
        self,
        output_dir: Path,
        *,
        horizons: tuple[int, ...] = DEFAULT_HORIZONS,
        training_cut_period: str | None = None,
    ) -> PanelResult:
        result = PanelResult()
        started = time.perf_counter()

        self._report("Reading the preprocessed tables", 3.0)
        order_fact = self._read("order_fact")
        sales_fact = self._read("sales_fact")
        branch_dim = self._read("branch_dim")
        product_dim = self._read("product_dim")
        stock_position = self._read("stock_position")

        self._report("Assembling the hybrid target", 12.0)
        observations = self._build_observations(order_fact, sales_fact, result)
        panel_end = int(observations["period_index"].max())

        self._report("Materialising the period grid", 25.0)
        grid, grid_stats = build_period_grid(
            observations[["series_id", "period_index"]].drop_duplicates(),
            panel_end=panel_end,
            start_policy="first_observation",
        )
        panel = grid[["series_id", "period_index"]].merge(
            observations, on=["series_id", "period_index"], how="left"
        )

        # An absent month inside an active series is a real zero. Distinguishing
        # it from missing data is the whole point of value_unavailable_reason.
        materialised = panel["target"].isna()
        panel["target"] = panel["target"].fillna(0.0).astype("float64")
        panel["is_materialised"] = materialised
        panel["value_unavailable_reason"] = pd.Series(
            ["true_zero"] * len(panel), dtype="string"
        ).where(materialised.to_numpy(), other=pd.NA)
        # A row with no censoring observation is not censored as far as the
        # model is concerned, but the distinction is kept in the source columns:
        # a sales_proxy row's despatched/shortfall stay null, never zero.
        panel["is_censored"] = panel["is_censored"].astype("boolean").fillna(False).astype(bool)

        # A materialised row inherits the source of the window it falls in, so
        # a zero is attributable rather than anonymous.
        order_start = month_index(result.summary["target_windows"]["order_window"][0])
        panel["target_source"] = panel["target_source"].astype("string")
        panel.loc[panel["target_source"].isna(), "target_source"] = (
            panel.loc[panel["target_source"].isna(), "period_index"]
            .ge(order_start)
            .map({True: "order", False: "sales_proxy"})
        )

        panel["canonical_branch"] = panel["series_id"].str.split("|").str[0]
        panel["canonical_sku"] = panel["series_id"].str.split("|").str[1]
        panel["period"] = panel["period_index"].map(index_to_period)

        self._report("Joining dimensions and stock context", 45.0)
        panel = panel.merge(
            branch_dim[
                [
                    "canonical_branch", "branch_name", "region", "zone", "supply_hub",
                    "tier", "avg_lead_time_days", "std_lead_time_days", "truck_moq",
                    "in_location_master",
                ]
            ],
            on="canonical_branch",
            how="left",
        )
        panel = panel.merge(
            product_dim[
                [
                    "canonical_sku", "product_group", "vehicle_category",
                    "vehicle_age_category", "glass_type", "oem_status", "value_class",
                    "has_substitute", "substitute_sku_1", "in_product_master",
                    "is_non_glass",
                ]
            ],
            on="canonical_sku",
            how="left",
        )
        panel = panel.merge(
            stock_position[
                [
                    "canonical_branch", "canonical_sku", "closing_qty", "usable_qty",
                    "closing_value", "stock_class", "has_negative_row",
                ]
            ],
            on=["canonical_branch", "canonical_sku"],
            how="left",
        )
        # A series with no stock row holds zero stock. That is a fact, and it is
        # recorded as zero_stock rather than left ambiguous.
        panel["stock_row_present"] = panel["closing_qty"].notna()
        panel["closing_qty"] = panel["closing_qty"].fillna(0.0)
        panel["usable_qty"] = panel["usable_qty"].fillna(0.0)
        panel["closing_value"] = panel["closing_value"].fillna(0.0)
        panel["has_negative_row"] = (
            panel["has_negative_row"].astype("boolean").fillna(False).astype(bool)
        )

        for column in STATIC_FEATURE_COLUMNS:
            if column in panel.columns:
                panel[column] = panel[column].fillna("UNKNOWN").astype("category")

        panel = panel.sort_values(["series_id", "period_index"], kind="mergesort").reset_index(
            drop=True
        )

        self._report("Building leakage-safe origin features", 62.0)
        origin_features = build_origin_features(panel)

        manifest = build_feature_manifest(
            static_columns=STATIC_FEATURE_COLUMNS, horizons=horizons
        )

        cut_index = month_index(training_cut_period) if training_cut_period else None
        self._report("Building the direct multi-horizon training frame", 78.0)
        training = build_training_frame(
            panel,
            origin_features,
            horizons=horizons,
            static_columns=STATIC_FEATURE_COLUMNS,
            max_origin_period=cut_index,
        )

        self._report("Building the scoring frame", 88.0)
        scoring = build_scoring_frame(
            panel,
            origin_features,
            origin_period=cut_index if cut_index is not None else panel_end,
            horizons=horizons,
            static_columns=STATIC_FEATURE_COLUMNS,
        )

        self._report("Writing Parquet artifacts", 93.0)
        result.artifacts = _write(output_dir, panel, origin_features, training, scoring)

        periods = sorted(panel["period"].unique())
        result.panel_rows = len(panel)
        result.series_count = int(panel["series_id"].nunique())
        result.period_count = len(periods)
        result.training_rows = len(training)
        result.scoring_rows = len(scoring)
        result.summary.update(
            {
                "grid": grid_stats.as_dict(),
                "period_range": [periods[0], periods[-1]] if periods else [],
                "periods": periods,
                "series_universe": {
                    "definition": (
                        "branch x SKU pairs with demand in the order or sales fact. "
                        "Not the 63,210 control, which counts the sales file alone "
                        "and remains a check on the canonical key."
                    ),
                    "panel_series": result.series_count,
                    "sales_control_series": 63_210,
                    "stock_only_pairs_excluded": int(
                        len(stock_position)
                        - stock_position.assign(
                            series_id=stock_position["canonical_branch"]
                            + "|"
                            + stock_position["canonical_sku"]
                        )["series_id"]
                        .isin(set(panel["series_id"]))
                        .sum()
                    ),
                },
                "target_source_rows": {
                    str(key): int(value)
                    for key, value in panel["target_source"].value_counts().items()
                },
                "censored_rows": int(panel["is_censored"].sum()),
                "materialised_zero_rows": int(panel["is_materialised"].sum()),
                "observed_rows": int((~panel["is_materialised"]).sum()),
                "sparsity": summarise_sparsity(panel),
                "feature_manifest": manifest.as_dict(),
                "training_cut_period": training_cut_period,
                "training_rows": len(training),
                "training_origins": (
                    int(training["origin_period"].nunique()) if len(training) else 0
                ),
                "scoring_origin": (
                    index_to_period(cut_index if cut_index is not None else panel_end)
                ),
                # Expected to be 0: non-glass SKUs are stock-only, so the
                # demand-bearing universe excludes them by construction. This
                # is the D-005 scope working, not the D-024 flag failing.
                "non_glass_series_in_panel": int(
                    panel.loc[
                        panel["is_non_glass"].astype("boolean").fillna(False), "series_id"
                    ].nunique()
                ),
                "series_without_a_product_master_row": int(
                    panel.loc[
                        ~panel["in_product_master"].astype("boolean").fillna(False),
                        "series_id",
                    ].nunique()
                ),
            }
        )
        result.duration_seconds = time.perf_counter() - started
        self._report("Panel build complete", 100.0)
        return result


def _write(
    output_dir: Path,
    panel: pd.DataFrame,
    origin_features: pd.DataFrame,
    training: pd.DataFrame,
    scoring: pd.DataFrame,
) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, str] = {}
    for name, frame in (
        ("panel", panel),
        ("origin_features", origin_features),
        ("training_frame", training),
        ("scoring_frame", scoring),
    ):
        path = output_dir / f"{name}.parquet"
        frame.to_parquet(path, compression="snappy", index=False)
        written[name] = str(path)
    return written

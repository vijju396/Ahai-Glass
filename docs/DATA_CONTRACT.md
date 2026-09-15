# DATA_CONTRACT.md

## 1. Source files (read-only)

`data/source/`, extracted from `OneDrive_1_08-09-2026.zip`. **Never modified.**

| File | Rows | Grain | Period |
|---|---|---|---|
| `Sales Data FY 24~26.xlsb` | 1,703,042 | invoice line | Apr 2024 – Mar 2026 |
| `Orders & Receipts (Lead Time).xlsx` | 775,912 | order line | Apr 2025 – Jul 2026 |
| `Stock in Hand as on 1st Aug'26.xlsx` | 144,921 | branch x SKU snapshot | 1 Aug 2026 |
| `Substitution Mapping.xlsx` | 2,417 | SKU master | MRP w.e.f. 11 May 2026 |
| `Location Master.csv` | 57 | branch master | — |

The `.xlsb` has two sheets (`FY 25-26 Sales` 881,012 rows, `FY 24-25 Sales`
822,030). Large files are read with streaming readers (`pyxlsb` row iteration,
`openpyxl` read-only mode) — never loaded whole into a DataFrame.

## 2. Cleaning rules, in order

**C1. Union the sales sheets by validated column name, never by position.**
FY 24-25 has 34 columns, FY 25-26 has 33. Positional union corrupts the join.

**C2. Correct the FY 25-26 transposition by value pattern.** Both sheets declare
`Product Code, HSN Code, Product Name`. FY 24-25 data matches. FY 25-26 data is
`FG.M11…`, `'BOLERO (2022) FD LH GR'`, `70071100.0` — Name and HSN swapped.
Detection: HSN is 8 digits numeric, Name is free text. Detect by **type, not
position**, and assert the corrected column actually parses as an HSN code.
`Product Code` and `Oracle No` are unaffected.

**C3. Drop the FY 24-25-only `Doc Series` column** after the name-based union.

**C4. Convert Excel serial dates on the 1899-12-30 epoch.** `.xlsb` only
(`Inv Date = 45751.0`).

**C5. Validate every converted date against the `Month` field.** A mismatch is
a recorded defect, not a silent overwrite.

**C6. Normalize branch and depot values** with `TRIM` then `UPPER`.

**C7. Case variants resolve by C6.** 110 raw depot values -> **53**
(`Jaipur` / `JAIPUR` / `JODhPUR`). Same for `Item Sub Grp`
(`LAMINATED` 394,668 / `Laminated` 356) and `Supply Hub`.

**C8. Canonical SKU key.** `UPPER(TRIM(Product Code))` -> strip trailing
`.AFM` or `.AF` -> strip trailing `.` -> `TRIM` again. Reproduces **2,260**
SKUs and **63,210** branch x SKU series exactly.

**C9. Reconcile canonical Product Code against Oracle No** and report, per
ingestion: missing Oracle numbers (11 rows), disagreements (0), duplicate
mappings, and collisions (**109** Oracle Nos spanning multiple canonical SKUs).

**C10. Never use raw Oracle No as the sole SKU key.** It has only 2,147
distinct values and would lose 113 SKUs' identity. See DECISIONS.md D-003.

**C10a. The reliable key differs by file, and both are measured.** Sales uses
canonical `Product Code` for SKU identity. The ORDER file's product-master join
uses `Oracle No`: measured line-weighted master coverage is **99.909%** via
`Oracle No` against **93.699%** via `Material Code`, because `Material Code`
carries roughly 1,076 spec variants (3,139 distinct values vs 2,063) that join
no master row. Assuming one key works everywhere is the trap; both are
computed per ingestion and the gap is recorded as defect D17.
See DECISIONS.md D-017.

**C11. Preserve negative stock rows** (2 rows, min −30) as visible
data-quality exceptions. Excluded from `usable_stock_on_hand`, never deleted
or clamped in place.

**C12. Distinguish these six states explicitly.** Conflating them is the most
damaging available mistake on a panel that is 62% zeros:

| State | Meaning |
|---|---|
| `true_zero` | A real observation of no demand |
| `missing_data` | No observation exists |
| `zero_stock` | Stock is genuinely zero |
| `not_applicable` | The measure does not apply here |
| `model_ineligible` | A validated data requirement is unmet |
| `model_failed` | The fit raised |

Plus `out_of_budget` for a series a tier did not reach.

**C13. Exclude PII** — see `docs/AIS_DOMAIN_RULES.md` §7. Dropped at
ingestion, never in the panel, never in an API payload.

**C14. Clean despatch dates before any lead-time statistic.** `Despatch Date`
contains `0000-00-00` and values producing lead times down to −8,763 days;
68 rows unparseable, 216 negative. Uncleaned, Roorkee's standard deviation is
132 days instead of ~1.5.

**C15. Drop the Location Master footer row by detection.** Row 58 shifts values
into the wrong columns (`Status = "57.52"`). 57 data rows.

**C16. Never use `Replenishment A/B/C`.** Zero for all 57 branches.

## 3. Monthly panel

Grain: `canonical_branch x canonical_sku x month`. Explicit zero-demand months
are materialised for active series, tagged `true_zero` — not left absent.

Columns:

```
period_start, canonical_branch, canonical_sku
target, target_source, is_censored, value_unavailable_reason
ordered_qty, despatched_qty, shortfall_qty, over_delivered_qty
branch_name, region, zone, supply_hub, tier
product_group, product_sub_group, item_sub_group
vehicle_category, vehicle_age_category, glass_type, oem_status, value_class
mrp                      -- time-valid; a historical driver, never future-known
lead_time_avg_days, lead_time_std_days, transit_lead_time_days, truck_moq
closing_stock_qty, closing_stock_value, mrp_value, last_grn_date, stock_class
substitute_sku_1, substitute_sku_2, has_substitute
```

Persisted as **Parquet** with a versioned manifest recording: source file
hashes (SHA-256), row counts in and out, every cleaning rule applied, control
results, the panel schema, and a UTC build timestamp.

## 3a. Preprocessed dimension and fact tables

Built from a **confirmed** mapping, written as Parquet with a versioned
manifest under `runtime/storage/prepared/<run_id>/`. Phase 4 builds the
modelling panel on these. Measured row counts from the real files:

| Table | Grain | Rows | Notes |
|---|---|---|---|
| `branch_dim` | canonical branch | 57 | hierarchy, tier, lead times; `sells` / `orders` / `holds_stock` flags |
| `product_dim` | canonical SKU | 6,247 | 2,417 from the master, the rest stock-only; 189 flagged non-glass |
| `order_fact` | branch × SKU × month | 363,305 | the **true target**; 109,145 cells (30.0%) censored |
| `sales_fact` | branch × SKU × month | 558,367 | `invoiced_qty`, the **censored proxy** |
| `stock_position` | branch × SKU | 144,920 | the 1 Aug 2026 snapshot |

**The two facts are deliberately separate.** Merging them would erase which
source each period came from, and `target_source` is exactly what the hybrid
panel needs. Measured: 16 order periods (Apr 2025 – Jul 2026), 24 sales
periods (Apr 2024 – Mar 2026), **28 distinct monthly periods** combined
(Apr 2024 – Jul 2026).

`sales_fact`'s quantity column is named `invoiced_qty`, never `target`: it
records what was available to sell, not what was wanted.

**Orphans are added, never dropped.** A branch or SKU seen in a fact but absent
from its master gets a row with `in_location_master` / `in_product_master`
false, so the gap stays visible. Measured: 0 order depots outside Location
Master, 2 order SKUs outside the product master.

**Negative stock** (rule C11) is flagged per cell with `has_negative_row` and
excluded from `usable_qty`, never clamped in place.

## 4. Features — all strictly before the forecast origin

Lag and rolling terms are shifted **before** a target row is generated. The
builder constructs features only from months strictly earlier than the cut,
and a test asserts that a deliberately corrupted future value cannot change any
feature.

| Group | Features |
|---|---|
| Lags | 1, 2, 3, 4, 5, 6, 9, 12 |
| Rolling mean | 3, 6, 12 |
| Rolling std | 3, 6, 12 |
| Non-zero counts | 6, 12 |
| Sparsity | consecutive zero months |
| Trend | 3-month mean − 6-month mean |
| Seasonal | same calendar month one year earlier |
| Calendar | month of the target period |
| Horizon | forecast horizon 1–6 (a feature, so one fit covers all six) |
| Hierarchy | branch, region, zone, supply hub, tier |
| Product | group, sub-group, glass type, OEM status, vehicle category, vehicle-age category |
| Price | time-valid MRP |
| Provenance | censoring indicator, target-source indicator |

**Future-known vs historical is structural.** `future_known_driver_*` covers
calendar month, horizon step and the static attributes. `mrp`,
`despatched_qty` and `shortfall_qty` are `historical_driver_*` only — MRP
changes, so its future value is not genuinely known. A `future_known_driver`
missing a horizon value is a validation error, not a gap-fill.

## 4a. The monthly panel, as built

Measured against the real client data, at a 2025-09 training cut:

| Artifact | Rows | Grain |
|---|---|---|
| `panel` | 1,503,753 | branch x SKU x month |
| `origin_features` | 1,503,753 | one row per (series, origin) |
| `training_frame` | 3,895,148 | one row per (series, origin, horizon) |
| `scoring_frame` | 360,702 | one row per (series, horizon) from the cut |

- **68,675 series**, 28 monthly periods, Apr 2024 - Jul 2026.
- **634,951 observed rows and 868,802 materialised zeros** (57.8% of cells
  zero). `is_materialised` distinguishes them on every row.
- **994,526 `order` rows and 509,227 `sales_proxy` rows.** Never merged, never
  described as equivalent.
- **109,145 censored rows** - demand there was at least the observed value.
- **35 features**, deepest lookback 11 months.

Sparsity, measured: 10,877 series have exactly one non-zero month; 21,804 have
twelve or more; median observed months 26; median non-zero months 6; median ADI
3.0; median CV-squared 0.201.

The `scoring_frame` at the mandated 2025-09 origin targets
**Oct 2025 - Mar 2026**, which is exactly the mandated validation window.

## 5. Persisted per training run

Fold boundaries; training and validation row counts; predictions; actuals;
residuals; resolved model parameters; selected features; fit and inference
duration; warnings; skipped folds; and, explicitly, which metrics were
unavailable and why.

Predictions and actuals are stored **per origin** in `model_run.origins_json`,
not only summarised into metrics. Phase 7 found `OriginResult.as_dict()`
silently dropping them, which meant no actual-versus-predicted or residual chart
could be drawn from a stored run. Six floats per origin per model is a small
price for evidence that can be re-checked.

## 6. Persisted per champion decision

`champion_selection` is **append-only**. An override writes a new row and marks
the previous one superseded; a rollback writes another restoring the earlier
choice. So the audit history *is* the table, not a second log that can drift
from it, and a forecast that recorded `champion_selection_id` can still resolve
which decision was in force when it was produced.

Each row carries the champion, the challenger, the legacy-parity winner, the
best baseline and whether that baseline beat the champion, the selection source
(`automatic` / `manual_override` / `rollback`), the reason and actor for a
manual decision, and the **whole leaderboard as it stood** in `ranking_json` —
stored rather than recomputed, because a board rebuilt from today's rows would
answer a different question from the one the planner accepted.

A partial unique index enforces one active row per scope; the superseded history
accumulates beneath it.

## 7. Persisted per forecast run

`forecast_run` holds the origin period, the requested and achieved
reconciliation methods, what it fell back from and why, the coherence verdict
with its measured worst gap, the count of negatives clipped and quantile
crossings corrected, and the reconciliation base level with any partial levels
(D-050).

`forecast_row` is one row per (scope, period) and carries:

| Group | Fields |
|---|---|
| Value | `point_forecast`, `q80`, `q90`, `q95` |
| Reconciliation | `base_forecast`, `reconciliation_adjustment`, `reconciliation_method` |
| Interval provenance | `quantile_method`, `quantile_pooling_level`, `quantile_residual_count` |
| Data honesty | `target_source`, `is_censored`, `unavailable_reason` |
| Lineage | `model_id`, `model_run_id`, `champion_selection_id`, `forecast_source` |
| Denormalised keys | `canonical_branch`, `canonical_sku`, `region`, `demand_segment` |

The pre-reconciliation value is kept beside the adjustment so the change is
displayed rather than folded into the number. A row with `unavailable_reason`
set has a **null** point forecast, never a zero — "no forecast" and "a forecast
of zero" are different facts and this schema cannot conflate them.

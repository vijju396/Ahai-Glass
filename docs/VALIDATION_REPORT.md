# VALIDATION_REPORT.md

**Status: Phase 1 baseline — controls established and independently
reproduced from the client files before any application code existed.**
Phase 2 wires these same controls into the ingestion pipeline and
`GET /api/datasets/{id}/validation`, so the numbers below become automated
assertions rather than a one-off audit.

Source: `data/source/`, extracted read-only from
`OneDrive_1_08-09-2026.zip` (157,246,204 bytes, five files, all dated
2026-09-08). The originals are never modified.

The HTML document `AIS-forecasting-analysis.html` is treated as a **proposed
analysis, not verified truth**. Every figure below was recomputed from the
source files. Agreements and disagreements are both recorded.

---

## 1. Structural controls

Reproduced independently, before implementation.

| # | Control | Target | Measured | Status |
|---|---|---|---|---|
| S1 | Sales rows | 1,703,042 | **1,703,042** (881,012 FY25-26 + 822,030 FY24-25) | PASS |
| S2 | Order rows | 775,912 | **775,912** | PASS |
| S3 | Stock rows | 144,921 | **144,921** | PASS |
| S4 | Product-master rows | 2,417 | **2,417** | PASS |
| S5 | Location-master rows | 57 | **57** data rows (+1 junk footer) | PASS |
| S6 | Sales SKUs | ~2,260 | **2,260** canonical | PASS (exact) |
| S7 | Branch × SKU series | ~63,210 | **63,210** | PASS (exact) |
| S8 | Normalized order depots | 53 | 110 raw → **53** | PASS |
| S9 | Product-master coverage of order lines | ~99.9% | **99.909%** (line-weighted, via `Oracle No`) | PASS |
| S10 | Median order-to-despatch lead time | ~3 d | **3 d** (after date cleaning) | PASS |
| S11 | 95th-percentile lead time | ~6 d | **6 d** (after date cleaning) | PASS |

A failing control **never** allows silent continuation. Ingestion raises,
Data Studio renders the difference, and the failure is recorded here.

---

## 2. The canonical SKU key — solved and proven

**Rule:** `UPPER(TRIM(Product Code))` → strip a trailing `.AFM` or `.AF`
→ strip a trailing `.` → `TRIM` again.

Measured over all 1,703,042 sales rows:

| Quantity | Value |
|---|---|
| Distinct raw `Product Code` | 2,260 |
| **Distinct canonical SKU** | **2,260** |
| Distinct raw `Oracle No` | **2,147** |
| **Branch × canonical SKU series** | **63,210** |
| Rows with a missing `Oracle No` | 11 |
| Canonical SKUs mapping to >1 Oracle No (disagreements) | **0** |
| Oracle Nos mapping to >1 canonical SKU (collisions) | **109** |

The canonical key reproduces the 2,260-SKU and 63,210-series universe
**exactly**. Raw `Oracle No` does not, and this is why (rule D10):

| Cause | Count | Example |
|---|---|---|
| `PREGST.` legacy prefix sharing an Oracle No with its `FG.` twin | 121 SKUs | `PREGST.MYB.RDL.G00300A000` → `FG.MYB.RDL.G00300A000` |
| Glass-spec character substitution | — | `FG.TMS.LFH.**SCS**31B0000` → `FG.TMS.LFH.**GCG**31B0000` |
| Model-prefix substitution | — | `FG.**HX6**.FDL.G00400A000` → `FG.**ZX6**.FDL.G00400A000` |
| `NONOE*` prefixes | 4 distinct | `NONOE05`, `NONOE08`, `NONOE37`, `NONOE63` |
| Interior space before the trailing dot | 1 | `'FG.TX4.LFH.GBG2120700 .'` |

Prefix distribution: 2,135 `FG.`, 121 `PREGST.`, 4 `NONOE*`.

Normalizing the interior-space case does **not** change either count
(2,260 and 63,210 both hold), so the universe is stable under
normalization. The mapping direction is many-to-one: canonical Product
Code → Oracle No. Using `Oracle No` alone would collapse 2,260 SKUs to
2,147 and lose 113 SKUs' identity.

**Reconciliation output required by rule D9** — missing Oracle numbers,
disagreements, duplicate mappings and collisions — is persisted per
ingestion and served at `/api/datasets/{id}/mapping`.

---

## 3. Data defects catalogued

Confirmed in the source. Each has a coded fix in `docs/DATA_CONTRACT.md`.

| # | Defect | Extent | Verified how |
|---|---|---|---|
| D1 | `Product Name` / `HSN Code` transposed beneath their headers in **FY 25-26** | 881,012 rows | Both sheets declare `Product Code, HSN Code, Product Name`. FY24-25 data matches. FY25-26 data reads `FG.M11…`, `'BOLERO (2022) FD LH GR'`, `70071100.0`. `Product Code` and `Oracle No` are unaffected. |
| D2 | Extra `Doc Series` column in FY 24-25 | 34 cols vs 33 | Header comparison |
| D3 | Excel serial dates | `.xlsb` only | `Inv Date = 45751.0`; 1899-12-30 epoch |
| D4 | Depot case variants | 110 → 53 | `Jaipur` / `JAIPUR` / `JODhPUR` |
| D5 | `Item Sub Grp` case variants | 4 → 2 | `LAMINATED` 394,668 / `Laminated` 356; `TEMPERED` 379,472 / `Tempered` 1,011 |
| D6 | `Last GRN Date` coded `00-00-0000` | 104,797 rows total; **24,304 = 49% of the 49,199 rows that hold stock** | The HTML quotes only the stocked-row figure; both are recorded |
| D7 | Unclassified stock | **44,016** rows have no A/B/C/D class (30% of file) | `Classification` null count |
| D8 | `Replenishment A/B/C` all zero | 3 dead columns, all 57 branches | `min == max == 0.0` |
| D9 | Negative stock | **2** rows, min `-30` | Preserved as visible exceptions, never clamped away silently |
| D10 | **`Despatch Date` contains `0000-00-00` and corrupt values** | **3 unparseable, 281 negative** (284 excluded of 775,912) | Not mentioned in the HTML. Raw, Roorkee's lead-time std is 132 days instead of ~1.5. The 3/281 split differs from an earlier pandas probe's 68/216 because the pipeline's parser recognises more real formats — the total excluded is 284 either way |
| D11 | **Over-despatch** | **9,498 lines, 35,867 units** shipped beyond ordered | Not mentioned in the HTML. Makes net and gross shortfall differ by 7.6% |
| D12 | Location-master footer row misaligns values | 1 row | `Status = "57.52"` — a number in a status column |
| D13 | Stock file covers non-glass items | 6,171 product codes vs 2,260 in sales | `MOLDING` 3,099, `HIGH END` 1,687, `WIPER` 1,652, `ADHESIVES` 432 |
| D14 | Product-master value case variants | — | `Car & Muv` / `Car & MUV`; `Non-OEM` / `NON-OEM` |
| **D17** | **`Material Code` and `Oracle No` are not interchangeable join keys in the order file** | 3,139 distinct canonical values via `Material Code` vs **2,063** via `Oracle No`; master coverage **93.699%** vs **99.909%** | Found in Phase 2 while a control failed. `Material Code` carries ~1,076 spec variants that join no master row |
| D16 | Substitution mapping largely empty | 132 of 2,417 SKUs have a substitute | Open question for the business: unfinished map, or substitution genuinely does not happen |

---

## 4. Demand-target controls

Ordered quantity is the primary target. Reported separately, as required:

| Measure | Value |
|---|---|
| Total ordered | **2,602,392** |
| Total despatched | **2,133,961** |
| **Net shortfall** (ordered − despatched) | **468,431** |
| **Gross positive shortfall** (Σ max(ordered − despatched, 0)) | **504,298** = **19.38%** of ordered |
| **Over-delivery quantity** | **35,867** across 9,498 lines |
| **Net fill rate** | **81.99%** |
| Order lines fully unserved | 161,099 = 20.8% |
| Order lines with any shortfall | 168,599 = 21.7% |
| depot × SKU × month cells with a shortfall | **29.5%** |
| depot × SKU × month cells served zero | **19.3%** |

Monthly fill rate, measured — the deterioration from March 2026 is real:

| Month | Ordered | Despatched | Fill |
|---|---|---|---|
| 2025-04 | 139,283 | 120,364 | 0.864 |
| 2025-09 | 159,291 | 134,106 | 0.842 |
| 2025-10 | 143,953 | 120,845 | 0.839 |
| 2026-01 | 147,257 | 132,692 | 0.901 |
| 2026-03 | 157,100 | 118,291 | **0.753** |
| 2026-05 | 182,337 | 135,759 | 0.745 |
| 2026-06 | 193,349 | 123,560 | **0.639** |
| 2026-07 | 200,686 | 138,904 | 0.692 |

Lead time, on cleaned dates: median **3 d**, p95 **6**, max **27**. By hub —
Kolkatta 2.62, Pune 2.99, Dharuhera 3.16, Kadi 3.35, Chennai 3.43. Roorkee
is reported only after D10 cleaning; raw it is corrupted to std 132 d.

---

## 5. Findings that differ from the HTML document

The HTML holds up well. Differences are recorded, not smoothed over.

| HTML claim | Recomputed | Assessment |
|---|---|---|
| 504,052 units shortfall | **504,298** | Agrees to 0.05%; grain-of-clamping difference |
| "Missing GRN dates 24,304" | 24,304 of stocked rows, but **104,797** overall | HTML figure is correct but scoped; both recorded |
| 43% of stock value with no 6-month demand | **42.5%** | Agrees |
| 20,945 zero-stock/live-demand combos, 281,937 units | **21,576 / 378,003** on a strict Feb–Jul 2026 window | Window-choice difference, not an error |
| Median 75 days cover; p10 42, p90 164; 32 of 53 > 60 d | **64; 39, 150; 27 of 53** | Same shape, consistently lower — different demand denominator |
| 1,892 SKUs short; 94,522 in stock vs 499,357 short; ~19% transferable | **1,782; 91,961 vs 289,327; 32%** | HTML uses the full 16-month shortfall; ours a 6-month window |
| "2,260 SKUs" | **2,260** canonical, but only 2,147 distinct Oracle No | HTML is right; it does not explain which key produces it. §2 does. |
| "51 branches" | **51** selling branches; 53 order depots; 54 stock branches; 57 in master | HTML uses the selling-branch count; all four are distinct and reconciled |
| Croston / SBA / TSB proposed | **not implemented** | Outside the verified 13 (`docs/MODEL_INVENTORY.md` §0) |
| Reported accuracy from "a single training run" | not reproduced in Phase 1 | The HTML's WMAPE figures are its own claim. AIS measures its own and will not restate the HTML's. |

---

## 6. PII excluded from modelling datasets and API payloads

Rule D13. Dropped at ingestion, never written to the panel, never serialized
to the frontend. Enforced by `backend/tests/test_pii_exclusion.py`.

- **Location Master** — `PAN No`, `GSTIN`, `CIN Number`, `TIN No / VAT ??`,
  `TAN Reg No`, `ST Reg No`, `Contact person Code`, `Contact Person`, `Email`,
  `Branch Email`, `Landline Number`, `Fax`, `Mobile`, `Address1`, `Address2`,
  `Zip`
- **Sales** — `Customer Code`, `Customer Name`, `GST Number`,
  `Consignee Code`, `Consignee Name`
- **Orders** — `Invoice No`

Retained because they are non-personal and modelling-relevant: `Branch Code`,
`Branch Name`, `Region`, `Zone`, `Supply Hub`, `Tier`, `Transit Lead Time`,
`Avg Lead Time`, `Std. LeadTime`, `Service Factor`, `Truck (MoQ)`, `City`,
`District`, `State`.

---

## 7. Measured runtime baseline

Single-fit times on the real 24-month AIS national series
(`train=18, horizon=6, period=12`), each reference's own configuration:

```
sarimax                0.06 s   ok
auto_arima             0.47 s   ok
xgboost (grid)         0.32 s   ok
xgboost (fast)         0.014 s  ok
var                    0.01 s   ok
lstm                   5.75 s   ok
exp_additive                    INELIGIBLE  (<2 seasonal cycles)
exp_additive_damped             INELIGIBLE
exp_multiplicative              INELIGIBLE
exp_multiplicative_damped       INELIGIBLE
```

Pooled global XGBoost at real shape (950,000 rows × 29 features, 300 trees,
8 threads): fit **21.5 s**; scoring 380,000 rows (63,210 × 6 horizons)
**0.3 s**. Point + q80 + q90 + q95 ≈ **86 s fit, 1.2 s score**.

Series coverage, measured over 63,172 series with non-zero volume:

| Coverage of units | Series required | Share of 63,210 |
|---|---|---|
| 50% | 1,858 | 2.94% |
| 70% | 5,595 | 8.85% |
| 80% | 9,807 | 15.51% |
| 90% | 18,581 | 29.40% |
| 95% | 27,752 | 43.90% |

Volume concentration by series size: 13,272 series sold 1–2 units in two
years (0.58% of units); 446 series above 1,000 units carry 27.70%.

These figures set the training budget in `docs/ARCHITECTURE.md` §6. A naive
"all 13 models on all 63,210 series" run costs **≳130 hours** — LSTM alone
101 h — and is not operationally reasonable.

---

## Modelling validation (Phases 7–12)

Everything in this section was measured on the real files. Nothing is carried
over from the analysis document.

### Leakage controls, verified

| Control | How it is enforced | Verified by |
|---|---|---|
| Chronological validation only | `folds.py` builds rolling origins from period index; no random split exists in the codebase | `test_leakage.py` (42 tests) |
| Preprocessing fitted inside each fold | scalers, encoders and exogenous rank guards are constructed per fold from training rows only | `test_leakage.py`, `test_ml_adapters.py` |
| Lags built only from before the origin | `feature_builder.py` shifts before the target row is emitted | `test_leakage.py` |
| MRP never future-known | mapping rule R5 blocks it at confirmation time; the exogenous set is calendar-only | `test_roles.py`, `test_mapping_api.py` |
| Future frame carries a null target | `_future_frame` sets the target column to NaN so an adapter cannot read an actual | `test_forecast_api.py` |
| Recursive folds do not consume actuals | `allow_actuals_in_recursion` defaults False (D-031) | `test_leakage.py` |

### Determinism, verified

Two independent aggregate-tier runs over the real panel produced **byte-identical
WAPEs across all 17 models** (13 registered + 4 baselines). Random seed 42 is
fixed in settings and is read-only through the API, so a stored run cannot be
made irreproducible from the UI.

Champion ranking is a total order — WAPE, then absolute bias, then MAE, then
`model_id` — and a test reverses the input list to assert the same champion
emerges.

### Model eligibility, measured

Six of the thirteen are ineligible **at every scope** on this dataset:

| Model | Requirement | Available | Status |
|---|---|---|---|
| `auto_arima` | 24 training observations | 22 | Ineligible |
| `auto_arima_exog` | 24 | 22 | Ineligible |
| `exp_additive` | 24 | 22 | Ineligible |
| `exp_additive_damped` | 24 | 22 | Ineligible |
| `exp_multiplicative` | 24 | 22 | Ineligible |
| `exp_multiplicative_damped` | 24 | 22 | Ineligible |

They appear on every leaderboard with that exact requirement and its
remediation. **1,911 of 5,219 `model_run` rows are `ineligible`; 0 are
`failed`.** This is a property of a 28-month panel, not a defect, and it is not
worked around by lowering a threshold.

### Reconciliation coherence, measured

| Check | Result |
|---|---|
| Method used | `mint_variance` (requested and achieved; no fallback) |
| Reconciliation base level | `branch` |
| Partial levels, left unreconciled | `series` (100 of 68,675 — the top-N local tier) |
| Coherent | **true** |
| Max incoherence | **0.0** |
| Negative forecasts clipped | 0 |
| Quantile crossings corrected | 0 |
| Level agreement, 2026-08 | branch 188,103 = region 188,103 = national 188,103 |

Coherence is re-checked from the **persisted rows** by
`GET /api/forecasts/hierarchy`, not taken from the run's own flag.

**A defect this check caught.** Before D-050 the projection took the finest
level *present* as its base, so the top-N series tier became the base and a
100-series hierarchy was reconciled over the full-network aggregates. Branch and
region totals disagreed by **37,794 units** while the run reported
`coherent: true` — both flags accurate about the subset handed to the
projection, neither true of the persisted data. The base is now the finest
**complete** level, and each level pair carries two flags:

- `expected_coherent: false` — the lower level is a deliberate subset, so the
  totals were never expected to agree.
- `expected_coherent: true` with `coherent: false` — levels reconciled together
  disagree, which is a defect and is named as one.

It was found by an end-to-end HTTP check rather than by any unit test, which is
the argument for keeping that check.

### Quantile ordering, measured

`point ≤ q80 ≤ q90 ≤ q95` holds on **every one of the 2,256 persisted forecast
rows**. Verified both at generation (monotone sort with a counted correction)
and on read.

Achieved interval width against the model's own measured error, national scope:

| Level | Value (2026-08) | Above point |
|---|---|---|
| point | 187,503 | — |
| q80 | 196,467 | 4.8% |
| q90 | 198,942 | 6.1% |
| q95 | 201,968 | **7.7%** |

The champion's national WAPE is 4.58%, so a q95 at 7.7% above the point is
consistent with the measured error. **Before the D-045 fix it was 3.2%** — an
interval narrower than the model's own average error. That defect is recorded
because it would have propagated directly into every order-up-to level.

### Interval calibration provenance

378 calibration cells across the three runs. On the aggregate tier every served
horizon used `empirical / scope_all_horizons`: 12 residuals per scope, which is
above the 5-residual floor but below the 19 a conformal q95 order statistic
needs. **Every row says so.** No horizon was served an interval with no
provenance, and `horizons_without_interval` was 0.

### Inventory arithmetic, verified

The policy in `docs/AIS_DOMAIN_RULES.md` §4, checked against a worked example:

```
monthly q95 = 100, lead time 3 d, review 30 d, usable stock 40
protection_period_days = 30 + 3               = 33
protection_months      = 33 / 30.4375         = 1.0842
order_up_to_level      = 100 * 1.0842         = 108.42
recommended_order      = 108.42 - 40 - 0 + 0  =  68.42
days_of_cover          = 40 / 80 * 30.4375    =  15.22
```

Service-level monotonicity on a real row:
q80 = 1,091 ≤ q90 = 1,098 ≤ q95 = 1,105.

Refusals verified: a missing forecast, a missing stock record and a missing lead
time each yield a stated reason and a **null** recommendation. A long position
yields **zero to order** with the surplus named, never a negative order.

### Placement measures against the domain document

| Measure | This run | Domain doc | Note |
|---|---|---|---|
| Zero stock against live demand | 21,549 | 21,576 | Window definition differs (last 6 order-fact periods); both reported |
| Negative stock rows | 2 | 2 | Agrees |
| Dead or slow positions | 23,788 | — | Newly measured |
| Dead stock value | ₹88,689,982 | — | Newly measured |

### PII exclusion, verified

No response schema across training, leaderboard, champion, forecast, inventory,
monitoring, scenario or settings payloads carries a field matching any name in
`ALL_PII_COLUMNS`. The evaluation column list (`PANEL_COLUMNS`) is asserted
against the same set. 12 dedicated tests plus per-area assertions.

`GET /api/settings` publishes the database **dialect** and never a connection
string or a filesystem path; a test asserts no `C:\` or `.venv` reaches the
client.

### What remains unverified

- **The pooled tier has never been run end to end.** `pooled.py` exists and the
  cost model estimates it, but every figure in this report comes from the
  aggregate and local tiers. Full-network series-level scoring is the one
  operational claim not yet demonstrated.
- **Error deterioration has never been measured**, because no forecast period
  has an actual yet — the origin is the last observed month. The endpoint
  returns `computable: false` with that reason and needs no change to start
  working.
- **No lint has run.** `ruff` is configured in `pyproject.toml` but not
  installed in the backend venv.

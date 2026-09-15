# UI_VISUAL_PARITY.md

Every rendered visual in the read-only reference (`D:\Labour_AI forecast\frontend_sodexo`),
its AIS destination, the real AIS field and endpoint behind it, and its status.

**Reference is read-only.** Nothing in `D:\Labour_AI forecast` was edited, and no
`.env`, database or employee data was copied from it. The reference app was
**not executed** — its UI was inspected from source, so nothing below claims
pixel-comparison against a running reference (see §6).

**Status vocabulary used here**

| Status | Meaning |
|---|---|
| `Done` | implemented against a real AIS endpoint and verified in the browser |
| `Done (structure)` | panel and interaction implemented; a stated part of the data is genuinely unavailable, and the panel says so |
| `Not ported` | deliberately not built, with the reason given |
| `Outstanding` | **planned in this inventory and not yet built.** Listed so the gap is visible rather than implied by absence — see §8 for the exact remaining work |

---

## 0. Shared primitives ported

| Reference | AIS destination | Notes |
|---|---|---|
| `components/ui/Card.tsx` — `Card`, `KpiCard`, `Badge` | `components/ui/Dashboard.tsx` | Ported into the same module as the other primitives rather than a second file. `KpiCard` was folded into `StatTile`, which supersedes it. Tones remapped to the AIS palette. |
| `components/ui/Dashboard.tsx` — `StatTile`, `Panel`, `ClearChip`, `MiniTable`, `TINTS`, `SERIES_COLORS`, `TICK`, `TOOLTIP`, `LABEL` | `components/ui/Dashboard.tsx` | Ported. `money()` → `inr()` (₹ lakh/crore), `num()` kept. |
| `components/layout/Sidebar.tsx` (expandable section) | `components/layout/AppShell.tsx` | **Not ported.** The AIS shell already has a grouped, sectioned sidebar; the three new destinations were added to it as an `Analytics` group and an `Assistant` group. The reference's click-to-expand sub-navigation was not adopted, because AIS's forecasting workflow is separate top-level pages rather than tabs of one page. |
| `components/layout/PageContainer.tsx` — `LoadingState`, `ErrorState`, `EmptyState` | existing `components/ui/States.tsx` | AIS equivalents already existed; reused rather than duplicated. |
| `components/assistant/ChatChart.tsx` | `features/assistant/components/ChatChart.tsx` | Ported; same allowlisted `line`/`bar`/`pie` types. |
| `components/forecasting/SeriesSelect.tsx` | existing Forecast Explorer scope controls | AIS already had scope/branch/SKU selects. |

Reference `--color-primary: #c2410c` (Sodexo orange) is replaced throughout by
AIS corporate blue `#005BAB`; no Sodexo asset, colour or labour label is
carried over.

---

## 1. Overview → **Executive Command Center** (existing AIS page)

| # | Reference panel | Type | Interaction | AIS equivalent | Fields / API | Status |
|---|---|---|---|---|---|---|
| 1.1 | `Overview.tsx` hero + capability list | text + links | link-through | Existing AIS command centre hero | `GET /api/monitoring`, `GET /api/forecasts` | `Done` (pre-existing) |
| 1.2 | Data-source health strip | badge row | — | Health components strip | `GET /api/health` | `Done` (pre-existing) |

The reference Overview carries no chart. AIS's existing command centre is
richer than it; it is left as the landing page rather than being reduced to
match.

---

## 2. LaborAnalytics.tsx → **Demand Analytics** (new page, `/demand-analytics`)

The reference's densest page: 15 panels, cross-filtering, 4 KPI tiles.
AIS mapping: **location → branch**, **department → value class**,
**labour cost → ordered demand value (₹, `target × mean_mrp`)**,
**scheduled vs actual → ordered vs despatched quantity**.

| # | Reference panel | Type | Interaction | AIS panel | Fields / API | Status |
|---|---|---|---|---|---|---|
| 2.1 | Filter bar (date range, location, department, grain) | controls | sets page filters | Period range, branch, value class, grain, plus a `Clear all` | `GET /api/analytics/filters` | `Done` |
| 2.2 | `Total Labor Cost` KPI + sparkline | StatTile + area spark | — | `Ordered demand value` ₹ + monthly spark | `target × mean_mrp` | `Done` |
| 2.3 | `Overtime Cost` KPI + spark | StatTile | — | `Unfilled demand` (shortfall units) + spark | `shortfall_qty` clipped ≥ 0 | `Done` |
| 2.4 | `Attendance Rate` KPI + spark | StatTile | — | `Fill rate %` + spark | `despatched_qty / target` | `Done` |
| 2.5 | `Labor Utilization` KPI + spark | StatTile | — | `Ordered-demand share` % + spark | `target_source == 'order'` share | `Done` |
| 2.6 | `Cost by Location` | doughnut, centre total | **click segment / legend → filter branch**, dim others | `Demand by Branch` | `canonical_branch` | `Done` |
| 2.7 | `Cost by Department` (two-line tick: name + cost centre) | bar + LabelList | **click column → filter** | `Demand by Value Class` (tick shows SKU count under name) | `value_class` | `Done` |
| 2.8 | `Overtime Hours by Department` | bar + LabelList | **click column → filter** | `Unfilled Demand by Value Class` | `shortfall_qty` | `Done` |
| 2.9 | `Cost by Site × Department` | **stacked** bar | click a column → filter branch | `Demand by Branch × Value Class` | cross-tab | `Done` |
| 2.10 | `Labor Cost Trend` | area, gradient fill | — | `Ordered Demand Trend` | monthly `target` | `Done` |
| 2.11 | `Scheduled vs Actual Hours` | 2-line, dashed vs solid | legend | `Ordered vs Despatched` | `target` vs `despatched_qty` | `Done` |
| 2.12 | `Overtime Trend` | area | — | `Unfilled Demand Trend` | `shortfall_qty` | `Done` |
| 2.13 | `Efficiency` (ReferenceLine y=100) | 2-line + reference line | legend | `Fill Rate` — 100% reference line | fill rate, censored share | `Done` |
| 2.14 | `Attendance Mix` | 3-line | legend | `Demand Signal Mix` — order / proxy / censored % | `target_source`, `is_censored` | `Done` |
| 2.15 | `Cost by Location over Time` | multi-line, one per site | **click legend → filter**, others dimmed | `Demand by Branch over Time` | branch × month | `Done` |
| 2.16 | `Hours by Department` (grey=rostered, solid=actual) | grouped bar | legend | `Ordered vs Despatched by Value Class` | grouped | `Done` |
| 2.17 | `Cost per Hour Worked` (avg ReferenceLine) | line + avg reference line | — | `Realised Price per Unit` ₹ + window-average line | `value / target` | `Done` |
| 2.18 | `Productivity` | MiniTable | — | `Demand Concentration` — top-5-SKU share per branch | Pareto share | `Done` |
| 2.19 | `Shift Utilization` | MiniTable | — | `Coverage` — months covered vs months in window | observed vs window | `Done` |
| 2.20 | `Manager Scorecard` — scale table + per-site cards with target-marked metric bars, rank, focus | table + card grid + custom bars | — | **Branch Operational Scorecard** — 4 measures: fill rate, censoring, demand stability, coverage | `GET /api/analytics/branch-scorecard` | `Done` |

**Why value class and not product group.** Measured on the real panel,
`product_group` has three levels and one of them holds 99.7% of demand, so a
breakdown by it is a single bar. `value_class` has six populated levels
(A/B/C/D/New Model/UNKNOWN) and is the documented AIS dimension that actually
carries the structure the reference's department axis carries. Both are
returned by the API; the department-shaped panels use value class.

**Honest deviation.** The reference's grain selector offers `daily / weekly /
monthly`. AIS demand history is **monthly only** (`period_index`), so the AIS
grain control offers `monthly` and `quarterly` (a real roll-up) and says why
daily is absent. Fabricating daily values from monthly data is explicitly
forbidden and was not done.

---

## 3. TimePunchAnalytics.tsx → **Operational Exceptions** (new page, `/exceptions`)

Reference domain is punch/attendance exceptions per employee. AIS has no
employee data and must never acquire any. Mapping: **punch exception → data
and supply exception on a branch × SKU line**; **employee ranking → branch ×
SKU exception ranking**.

| # | Reference panel | Type | Interaction | AIS panel | Fields / API | Status |
|---|---|---|---|---|---|---|
| 3.1 | 5 KPI tiles + sparklines | StatTile | — | Censored lines, over-despatched lines, zero-stock-live-demand, negative-stock rows, unmapped SKUs | `GET /api/analytics/exceptions` | `Done` |
| 3.2 | `By Severity` | doughnut | **click → filter severity** | `By Severity` (critical / high / medium) | derived severity | `Done` |
| 3.3 | `By Issue Type` | bar | **click → filter type** | `By Exception Type` | 6 real exception types | `Done` |
| 3.4 | `Top Employees` | ranked bar | **click → drill to that entity** | `Top Branch × SKU Lines` | ranked by units affected | `Done` |
| 3.5 | `By Location` | bar | **click → filter branch** | `By Branch` | `canonical_branch` | `Done` |
| 3.6 | `By Department` | bar | **click → filter** | `By Product Group` | `product_group` | `Done` |
| 3.7 | `Alerts` / exception detail table | table + drill-down | row expand | Exception detail table with the defining measure per row | same endpoint | `Done` |
| 3.8 | Punch-time distribution (hourly) | histogram | — | **Not ported** | AIS has no intra-month timestamps. A monthly panel cannot produce an hour-of-day histogram, and inventing one is forbidden. | `Not ported` |

**Exception types are real AIS conditions**, each with a stated definition:
censored line (despatch < order), over-despatch, zero stock against live
demand, negative stock row, SKU absent from the product master, non-glass SKU
carrying stock. All six come from the panel and the stock snapshot.

---

## 4. AIRecommendations.tsx → **Supply Intelligence** (existing page, extended)

| # | Reference panel | Type | Interaction | AIS panel | Fields / API | Status |
|---|---|---|---|---|---|---|
| 4.1 | Recommendation KPI tile | StatTile | — | Existing supply KPI strip | `GET /api/inventory/recommendations` | `Done` (pre-existing) |
| 4.2 | `By Priority` | doughnut | **click → filter priority** | `By Urgency` — cover-days bands | derived from cover days | **`Outstanding`** |
| 4.3 | `By Category` | bar | **click → filter** | `By Stock Class` | `stock_class` | **`Outstanding`** |
| 4.4 | `Actions by Site` | bar | **click → filter branch** | `Recommended Order Value by Branch` | order qty × MRP | **`Outstanding`** |
| 4.5 | Recommendation detail table + ClearChips | table | clear filters | Existing recommendation table (kept — it already exposes every calculation input) | same | `Done` (pre-existing) |

---

## 5. LaborForecasting tabs → **Forecast Explorer / Training Center / Monitoring / Model Leaderboard**

AIS already implements most of these more strictly than the reference. Gaps
closed rather than duplicated.

| # | Reference tab / panel | Type | AIS destination | Fields / API | Status |
|---|---|---|---|---|---|
| 5.1 | `DemandDriversTab` — driver/feature mapping | list + confirm | Existing **Mapping & Validation** (role editor, 29-feature manifest) | `GET /api/datasets/{id}/mapping` | `Done` (pre-existing) |
| 5.2 | `DataAnalysisTab` — historical demand trend | line | Demand Analytics 2.10 + Forecast Explorer history | `GET /api/analytics/summary` | `Done` |
| 5.3 | `DataAnalysisTab` — seasonality curve | bar (per period-of-cycle mean) | **Demand Analytics → `Seasonality`** panel | month-of-year means | `Done` |
| 5.4 | `DataPreprocessingTab` — 5 KPI cards | KpiCard | Existing **Mapping → Preprocessing panel** | `GET /api/mappings/{id}/preprocessing` | `Done` (pre-existing) |
| 5.5 | `ModelTrainingTab` — run controls, per-model status | table + controls | Existing **Training Center** (13 models, full status vocabulary) | `GET /api/training/{id}/model-runs` | `Done` (pre-existing) |
| 5.6 | `ForecastExplorerTab` — 6 KPI + forecast timeline, model/view/granularity controls, legend, ReferenceLine at origin | line + controls | Existing **Forecast Explorer** (already has Actual / Actual-vs-Forecast / Forecast / Full timeline, q80–q95, CSV) | `GET /api/forecasts/series` | `Done` (pre-existing) |
| 5.7 | `ForecastExplorerTab` — forecast metadata / explanation panel | detail panel | Existing Forecast-detail table (point, q80–q95, pre-reconciliation, adjustment, interval provenance, model, source) | same | `Done` (pre-existing) |
| 5.8 | `DriftTab` — drift signal, comparison means, highlighted window, 2 ReferenceLines | line + reference lines | **Monitoring → drift**. The AIS page reports drift as a table with both window means, both row counts and the measurement-change caveat; the reference's *chart* of it is not yet drawn. | `GET /api/monitoring` | **`Outstanding (chart only)`** |
| 5.9 | `StaffingImpactTab` — required vs available curve + signed gap bars | ComposedChart (line + signed bars) | **Supply Intelligence → `Cover vs Requirement`** — q95 requirement vs usable stock, signed gap bars. The underlying figures are all already on the page in the recommendation table; the ComposedChart is not yet drawn. | `GET /api/inventory/recommendations` | **`Outstanding`** |
| 5.10 | `ModelPerformanceTab` — model comparison bars, champion highlighted via `Cell` | bar + champion cell | Existing **Model Leaderboard → WAPE chart** (already highlights champion, keeps ineligible models on the axis) | `GET /api/models/leaderboard` | `Done` (pre-existing) |

---

## 6. AIAssistant.tsx + ChatChart.tsx → **AI Assistant** (new page, `/assistant`)

| # | Reference element | AIS equivalent | Status |
|---|---|---|---|
| 6.1 | Dedicated assistant page, `fill` layout, internal scroll | `features/assistant/pages/AssistantPage.tsx` | `Done` |
| 6.2 | Suggested starter questions | 7 AIS questions (branch forecast, zero-stock SKUs, why champion, baseline beats model, dead stock, demand trend, explain recommendation) | `Done` |
| 6.3 | Follow-up context (history round-trip) | `history[]` posted back, capped at 6 turns | `Done` |
| 6.4 | Visible scope + clear-scope control | Branch / SKU / period scope chip with clear | `Done` |
| 6.5 | Loading / retry / error / not-configured states | All four, plus explicit setup instructions when no key | `Done` |
| 6.6 | `ChatChart` line / bar / pie from backend facts | Ported, allowlisted types, values only from backend facts | `Done` |
| 6.7 | Links from an answer to the supporting app view | Source links to Forecast Explorer / Leaderboard / Supply | `Done` |
| 6.8 | Assistant entry point from analytics pages | Ask-assistant action in the page header | `Done` |

**Verification limitation, stated rather than glossed.** The reference app was
inspected as source only — it was never installed or run, since doing so would
mean writing to a read-only project (`npm install`) and touching its database.
So parity here is **structural and behavioural against the source**, not a
pixel diff against a rendered reference. Every claim above is verified against
the AIS implementation in a browser instead.

---

## 7. Deliberate non-ports

| Reference element | Why not |
|---|---|
| Sodexo logo / `--color-primary: #c2410c` orange theme | Replaced by AIS blue `#005BAB` and the AIS logo with its red diamond. |
| Employee names, attendance, payroll, risk scores | AIS holds no employee data and must not. Replaced by branch × SKU exception rankings. |
| Hour-of-day punch histogram | Requires intra-day timestamps AIS does not have (§3.8). |
| "Enterprise data via UKG/Workday/POS/Payroll/ERP connectors" footer | Replaced with the real AIS source list. |
| Reference React 19 / Vite 8 / TS 6 versions | AIS stays on React 18 / Vite 6; only Recharts, Tailwind and lucide were added. Upgrading the framework to match version numbers was out of scope. |

---

## 8. Outstanding, stated rather than implied

Five inventory entries are **not yet built**. They are listed here with the
exact remaining work rather than being quietly marked done, because an
inventory that overstates itself is worse than one with gaps in it.

| # | What is missing | Where it goes | Data | Effort |
|---|---|---|---|---|
| 4.2 | `By Urgency` doughnut — recommendation count by cover-days band, clickable | Supply Intelligence, above the existing table | `days_of_cover` from `GET /api/inventory/recommendations`; no new endpoint needed | small |
| 4.3 | `By Stock Class` bar, clickable | Supply Intelligence | `stock_class`, already on every recommendation row | small |
| 4.4 | `Recommended Order Value by Branch` bar, clickable | Supply Intelligence | `raw_recommended_order` x MRP, grouped by `canonical_branch` | small |
| 5.8 | The drift **chart** — recent vs earlier window with both means as reference lines | Monitoring, beside the existing drift table | `GET /api/monitoring` already returns both window means and every branch's shift; nothing new is required server-side | small |
| 5.9 | `Cover vs Requirement` ComposedChart — q95 requirement line with signed gap bars | Supply Intelligence | `monthly_quantile_forecast` vs `closing_stock_on_hand` per row, both already returned | medium |

None of the five needs a new endpoint or any new aggregation: every figure is
already in a payload the page fetches. What is missing is the chart component
in each case.

Everything in §2, §3 and §6 — the two new dashboard pages and the assistant —
is built and verified in a browser against the running application.

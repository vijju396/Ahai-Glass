# STATUS.md

## Frontend redesign — 9 September 2026

AIS-branded React redesign applied across all ten workspaces. The official logo
is stored locally; blue/navy website colors anchor the new responsive shell,
cards, tables, forms and light/dark themes. The executive dashboard now includes
real demand history/outlook, regional forecasts, model benchmarks and stock KPIs.
Data Studio, mapping, training, supply, scenarios and monitoring have new measured
data visuals. Settings documents brand provenance.

Forecast Explorer adds Full timeline, Actual, Actual vs forecast, and Forecast
views; history range, zoom, quantile visibility, per-origin backtest selection,
source-aware labels, detail tables and view-specific CSV exports. It requests
up to 120 history months (all 28 currently available), rather than silently
showing only the API's 24-month default. Diagnostics are pinned to the forecast's
training run and model. Overlapping backtest origins are never merged.

Verification: frontend **157 tests passing across 15 files**; production
TypeScript/Vite build passes. Browser checked all ten routes against real API
data, forecast mode/origin selection, scenario evaluation, dark mode, and
360/390px mobile layouts. No browser console errors observed. Existing Vite
large-chunk and React Router future-flag warnings remain non-blocking.

Backend code, data files, model registry, model artifacts, champions and stored
forecasts were not modified or regenerated. Backend tests were not rerun for
this frontend-only change; the previous full-suite baseline follows below.

See `docs/FRONTEND_DESIGN.md` and decision D-051. Original replaced frontend files
are recoverable in `runtime/backups/frontend-redesign-20260909-171111`; subsequent
refinement backups are timestamped beside it.

## Current state

**All twelve phases complete.** The five source files ingest with every
structural control passing; column roles are mapped, validated and confirmed;
preprocessing has built the dimension and fact tables; the monthly panel with
its leakage-safe direct multi-horizon features is built from the real data; all
thirteen registered models are implemented as adapters and backtested across
the two mandated rolling origins; champions are selected deterministically and
overridable with an audited reason; forecasts for horizons 1-6 are generated,
calibrated and reconciled coherently; inventory recommendations expose their own
arithmetic; all ten React pages consume real API data; and 896 tests pass.

**896 tests: 739 backend, 157 frontend.** Both suites green. 57 API endpoints,
all documented in `docs/API_CONTRACT.md` and cross-checked against the running
app (no drift in either direction).

The earlier summary here read "883 tests: 731 backend, 152 frontend". The
frontend count was already 157 by the time Phase 11 closed - it is recorded
correctly higher up this file - and the backend gained 8 tests in the
verification pass below. The per-phase "actual output" blocks further down are
left exactly as they were measured at the time; they are a record, not a
running total.

### The headline finding, stated first

**A non-registry baseline beats the champion in 47 of 166 scopes.** At the
national aggregate the champion (`var_exog`, WAPE 4.578%) comfortably beats the
best baseline (`ma6`, 9.939%). Further down the hierarchy that reverses often
enough to matter. Every leaderboard, every champion selection row and the
Executive Command Center say so in words rather than leaving two numbers to be
compared. The champion is the best of the thirteen registered models; that is
not the same claim as the best available forecast.

**Six of the thirteen models are ineligible on this dataset**, at every scope:
both Auto ARIMA variants and all four exponential-smoothing variants need 24
training observations and the primary origin has 22. They appear on every
leaderboard with that exact requirement and its remediation. 1,911 of 5,219
`model_run` rows are `ineligible` — recorded, never hidden.

### Measured, on the real data

| Fact | Value |
|---|---|
| Panel | 1,503,753 rows · 68,675 series · 28 months (2024-04 … 2026-07) |
| Training runs | 3 · 5,219 `model_run` rows · 3,308 completed, 1,911 ineligible, **0 failed** |
| Aggregate tier | 69 scopes · 276 s actual against a 424 s estimate |
| Determinism | Two independent runs produced byte-identical WAPEs |
| Champions | 166 active · 1 overall, 6 region, 50 branch, 6 value_class, 3 product_group, 100 series |
| Scopes skipped | 3 branches, each with a stated reason (no rankable model) |
| Forecasts | 2,256 rows across 5 levels · 600 series-level · 72 with a reason and no number |
| Reconciliation | `mint_variance`, coherent, max incoherence **0.0**, 0 quantile crossings |
| Quantile calibration | 378 cells · conformal where the order statistic exists, empirical otherwise |
| Inventory | 100 real recommendations · q80 ≤ q90 ≤ q95 holding · protection 33-35 days |
| Placement | 23,788 dead/slow positions (₹88.7 M) · 21,549 zero-stock-against-live-demand · 2 negative-stock rows surfaced |

### What is not claimed

- **No historical inventory-policy backtest.** The stock file is a single
  snapshot dated 2026-08-01 while demand history ends 2026-07. Every
  recommendation is labelled a current-snapshot estimate.
- **No error-deterioration measurement yet.** The forecast origin *is* the last
  observed month, so no forecast period has an actual to compare against. The
  monitoring endpoint returns `computable: false` with that reason rather than
  reporting zero deterioration.
- **No accuracy figure beyond what is in this document.** Every number here was
  measured in this project on the real files.
- **The panel is 68,675 series, not 63,210.** The 63,210 figure is the sales
  universe control and it reconciles; the panel is the demand-bearing union of
  sales and orders (D-025). Both are reported, never conflated.

| Phase | Scope | State |
|---|---|---|
| 0 | Audit: source data, reference projects, model parity, architecture, scale | Complete |
| 1 | Project foundation and documentation | Complete |
| 2 | Data ingestion and source validation | Complete |
| 3 | Mapping and preprocessing | Complete |
| 4 | Monthly panel and feature engineering | Complete |
| 5 | The 13-model adapter registry | Complete |
| 6 | Backtesting and metrics | Complete |
| 7 | Training orchestration and persistence | Complete |
| 8 | Champion selection and leaderboard | Complete |
| 9 | Forecast generation and reconciliation | Complete |
| 10 | Inventory recommendations | Complete |
| 11 | React UI completion | Complete |
| **12** | **End-to-end testing and documentation** | **Complete** |

### Notes carried forward by earlier phases, and how they were resolved

The Phase 1-6 records below contain forward-looking notes ("Phase 8 must not
…"). They are history, not outstanding work. Each one was acted on:

| Raised in | Note | Resolved by |
|---|---|---|
| Phase 2 | Alembic baseline must precede the Phase 3 tables | Phase 3 — revision generated before the tables were used |
| Phase 3 | Phase 4 must decide the panel's series universe | D-025 — the demand-bearing union, 68,675 series, reported beside the 63,210 sales control |
| Phase 3 | Phase 4 must read the *latest* preprocessing run, not the first | Phase 4 — the older run predates the non-glass fix (D-024) |
| Phase 4 | Phase 5 must not promote historical drivers to future-known features | D-032 — the exogenous set is calendar-only; rule R5 blocks the rest at confirmation |
| Phase 5 | No accuracy figure exists yet; Phase 6 owns evaluation | Phase 6 — the first measured figures, and Phase 7 the first at scale |
| Phase 6 | Phase 8 must not rank a 6-point metric against a 10-point one without showing both | D-044 — comparability assessed within an evaluation mode, both counts on the row, mixed-mode note on the response |
| Phase 6 | Phase 8 must not compare VAR's median against a model evaluated on all series | Phase 8 — `validation_points` is a leaderboard column; D-042 records why VAR is viable at aggregate level and sparse below it |
| Phase 6 | Phase 9 should re-measure quantile coverage once residuals are plentiful | D-045 — the pooling scheme itself was wrong across magnitudes and was replaced; coverage re-measured |
| Phase 6 | Budget pre-emption is Phase 7's | Phase 7 — measured, and left opt-in: a fresh interpreter costs more than the fit it would protect |

The two notes still genuinely open are in **What is not claimed** above: the
pooled tier and error deterioration.

### Running it

```bash
# backend
cd backend && .venv/Scripts/python.exe -m alembic upgrade head
cd backend && .venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000

# frontend
cd frontend && npm install && npm run dev      # http://localhost:5173

# tests
cd backend && .venv/Scripts/python.exe -m pytest -q     # 739
cd frontend && npm test                                  # 157
```

The pipeline order is: register a dataset → confirm the mapping → preprocess →
build the panel → train → select champions → generate forecasts → read
recommendations. Each stage refuses to run before its predecessor and says
which one is missing.

---

## Phase 1 — completed 2026-09-08

### Verified working, not just written

- `uvicorn app.main:app` starts; startup registry assertion passes.
- `GET /api/health` returns `status: ok` with all five components healthy —
  database, model_registry (`13 of 13 models registered.`), source_data
  (`All 5 source files present.`), ml_dependencies, mlflow.
- `GET /api/models` returns all 13 models in rank order 1–13 with correct
  display names, minimum-history values, holdout policy and pooled-training
  capability, plus the 4 baselines in a separate array.
- `vite build` compiles: 155 modules, 279.60 kB JS / 11.03 kB CSS.
- `tsc -b` passes with `strict`, `noUnusedLocals`, `noUnusedParameters` and
  `noUncheckedIndexedAccess`.

### Test results (actual output)

**Backend — 25 passed**

```
............................                                          [100%]
25 passed in 1.50s
```

`tests/test_model_registry.py` (16) — exactly 13 models; IDs in exact order
against a literal transcription; display names verbatim; no duplicates;
dependency coverage; no forbidden substitute (prophet / random_forest /
lightgbm / croston / sba / tsb / moving_average); baselines structurally
separated; capability sets reference only known models; exogenous set is
exactly the four `_exog` variants; fast-holdout set matches Sodexo; LSTM has no
`_exog` sibling; startup assertion passes; and four negative cases — missing
model, duplicate, a 14th model, and a baseline promoted into the 13.

`tests/test_api_contract.py` (9) — health component breakdown; registry
reports ok; all 13 models in order; display names and eligibility metadata;
baselines separated; explanatory notes present; structured 404 shape with
correlation ID; OpenAPI generated; correlation header echoed.

**Frontend — 23 passed**

```
✓ src/test/no-duplicate-registry.test.ts (4 tests)
✓ src/features/command-center/__tests__/CommandCenterPage.test.tsx (4 tests)
✓ src/test/accessibility.test.tsx (7 tests)
✓ src/features/leaderboard/__tests__/ModelLeaderboardPage.test.tsx (8 tests)

Test Files  4 passed (4)
     Tests  23 passed (23)
```

`no-duplicate-registry` scans real application source (tests and the API
fixture exempt) and asserts: no `model_id` literal, no display-name literal,
and no forecasting arithmetic anywhere in the frontend.

`ModelLeaderboardPage` asserts a loading state, exactly 13 rows, display names
in backend order, a status pill on every row so none can vanish, eligibility
metadata, baselines rendered outside the table, an explicit "not yet measured"
notice with **no** metric columns present, and an actionable error state.

`accessibility` asserts all ten destinations as links numbered 1–10 exactly
once each, a working skip link to the `main` landmark, keyboard reachability of
the first nav link, an accessible name on the theme toggle, and that
`Ineligible` / `Failed` / `Not evaluated (budget)` are conveyed as **text**,
not colour alone.

### Files created

**Documentation (9)** — `README.md`, `CLAUDE.md`, `docs/ARCHITECTURE.md`,
`docs/API_CONTRACT.md`, `docs/DATA_CONTRACT.md`, `docs/MODEL_INVENTORY.md`,
`docs/AIS_DOMAIN_RULES.md`, `docs/DECISIONS.md`,
`docs/VALIDATION_REPORT.md`, `docs/STATUS.md`.

**Backend (13)** — `requirements.txt`, `pyproject.toml`, `.env.example`,
`app/main.py`, `app/core/{config,logging,errors}.py`,
`app/db/{base,session}.py`, `app/schemas/{common,models}.py`,
`app/services/model_contract_service.py`,
`app/ml/registry/canonical_models.py`, `app/api/router.py`,
`app/api/routes/{health,models}.py`, plus package markers.

**Frontend (24)** — `package.json`, `vite.config.ts`, `tsconfig.json`,
`index.html`, `.env.example`, `src/{main.tsx,App.tsx,vite-env.d.ts}`,
`src/app/{routes.tsx,queryClient.ts,navigation.ts}`,
`src/api/{client,models,health}.ts`, `src/types/api.ts`,
`src/styles/index.css`, `src/components/layout/{AppShell.tsx,layout.css}`,
`src/components/ui/{Card,StatusPill,States,Toast,PhaseNotice}.tsx` + `ui.css`,
ten feature pages, `src/test/{setup.ts,renderWithProviders.tsx}`, and four
test files.

**Project (6)** — `.gitignore`, `scripts/{setup,start_backend,start_frontend,run_tests}.ps1`,
`runtime/` tree with `.gitkeep` markers.

### Decisions recorded

D-001 through D-016 in `docs/DECISIONS.md`. The four that shape everything
downstream:

- **D-001** — six of thirteen models are legitimately `Ineligible` at monthly
  grain. Measured: the hybrid panel gives at most 22 training rows before a
  6-month holdout; `auto_arima` and the four ES variants need 24. Default
  profile reports them Ineligible with the exact reason; `monthly_relaxed` is a
  labelled opt-in so all 13 can be compared.
- **D-002** — hybrid panel, `sales_proxy` Apr 2024–Mar 2025 and `order`
  Apr 2025–Jul 2026, giving 28 periods and a second validation origin.
- **D-003** — the canonical SKU key reproduces 2,260 SKUs and 63,210 series
  exactly; raw `Oracle No` cannot (2,147 values, 109 collisions).
- **D-009** — full-covariance MinT is not computable at 63,210 base series
  (~32 GB); variance-scaling below, shrinkage MinT above.

### Issues found and fixed during the phase

1. **numpy conflict.** `numpy==2.0.2` was incompatible with
   `tensorflow-cpu==2.17.0` (`numpy<2.0.0`) — hard `ResolutionImpossible`.
   Repinned to 1.26.4, matching Oxea's resolved set. All 21 dependencies now
   install and import together. (D-008)
2. **Assertion ordering.** `assert_canonical_registry()` reported a baseline
   promoted into the 13 as a downstream display-name count mismatch. The
   overlap check now runs before the coverage checks, so the real problem is
   named. Found by the negative test, fixed in the production code rather than
   the test. (D-013)
3. **Vitest/Vite version clash.** Vitest 2.1.8 bundles its own Vite 5, which
   collided with Vite 6 and broke `tsc -b`. Upgraded to Vitest 3.2.7.
4. **Missing `@types/node`** and a `vitest/config` import needed for the
   `test` key in `vite.config.ts`.

### Blockers

**None.** Phase 2 can start.

### Notes carried forward

- The project sits under a OneDrive-synced path with spaces. `.venv`,
  `node_modules`, `runtime/` and `dist/` are gitignored, but OneDrive will
  still try to sync them and can hold locks during installs. (D-016)
- `data/source/` and the source zip are gitignored: large, and client data.
- Nothing has been committed or pushed.
- No file in any reference project was modified. Verified by inspection only.

---

## Phase 2 — completed 2026-09-08

### Verified against the real client data, end to end

A full ingestion ran over all five files in `data/source/`, submitted through
`POST /api/datasets` and executed on the background job runner.

**Every structural control passes.** Live output from
`GET /api/datasets/{id}/validation`:

```
CODE  OUTCOME   EXPECTED     MEASURED     CONTROL
S1    pass      1,703,042    1,703,042    Sales invoice-line rows
S2    pass        775,912      775,912    Order lines
S3    pass        144,921      144,921    Stock snapshot rows
S4    pass          2,417        2,417    Product-master rows
S5    pass             57           57    Location-master rows (footer excluded)
S6    pass          2,260        2,260    Distinct canonical SKUs
S7    pass         63,210       63,210    Branch x SKU series
S8    pass             53           53    Normalized order depots
S9    pass       >= 99.0%      99.909%    Product-master coverage of order lines
S10   pass         3 days       3 days    Median lead time (cleaned dates)
S11   pass         6 days       6 days    95th-percentile lead time (cleaned dates)

FAILED CONTROLS: NONE
```

**The 2,260-SKU and 63,210-series universe is reproducible** from the canonical
key, not asserted: 2,260 canonical SKUs against 2,147 distinct Oracle numbers,
109 collisions, 0 disagreements, 11 rows without an Oracle number.

**Service measures, reported separately as required:** ordered 2,602,392,
despatched 2,133,961, net shortfall 468,431, gross positive shortfall 504,298
(19.378%), over-delivered 35,867 across 9,498 lines, net fill rate 82.00%.

**Lead time on cleaned dates:** median 3 d, p95 6 d, max 27 d, from 775,628
usable lines; 284 excluded (3 unparseable, 281 negative) and counted, not
hidden.

**14 defects catalogued**, each with the rule that handled it: D1, D2, D4, D5,
D6, D7, D8, D9, D10, D11, D12, D13, D16, D17.

**Read cost, measured:** 8 m 8 s total — product master 0.2 s, sales 6 m 7 s
(1.7 M rows across two sheets), orders 1 m 45 s, stock 11.0 s, location master
under 0.1 s.

**PII containment verified on the real payload.** A leak scan over the
39,663-byte `/profile` response found none of `SALONI`, `LAXMI`, `09AFMPG`,
`AAECA8434D`, `aisadsl.com`, a real mobile number, or a real address. All 22
PII columns are profiled and counted; none exposes a sample, min, max, mean or
distinct count.

**UI verified in a real browser** against the live API, in both light and dark:
Data Studio renders all 11 controls, the six service-measure tiles, the
lead-time exclusions, all 14 defects with their rules, and the five source
files with content hashes. Mapping & Validation renders the canonical-key
contrast, the rule text, four branch universes, and the reconciliation
findings.

### Test results (actual output)

**Backend — 147 passed** (was 25)

```
........................................................................ [ 48%]
........................................................................ [ 97%]
...                                                                      [100%]
147 passed in 1.71s
```

`test_cleaning_rules.py` (56) — canonical SKU including the
`FG.TX4.LFH.GBG2120700 .` interior-space case; branch normalisation; the
1899-12-30 epoch cross-checked against the source's own `Month` labels;
`0000-00-00` rejection; transposition detection on real FY 25-26 and FY 24-25
row shapes, including an undecided verdict on a mixed sample; name-based union
proving a positional union would misread `Doc Series` as `Inv No`; key
reconciliation; footer detection.

`test_controls.py` (25) — all controls pass on measured values; every control
reported even when passing; a short sales read fails with a remediation; the
SKU and series universes admit no tolerance; using Oracle No as the key fails
S6 with 2,147; corrupt lead times fail S10 and S11; absent inputs are
`not_evaluated` rather than passed; net versus gross shortfall; a null despatch
counts as nothing shipped.

`test_pii_exclusion.py` (14) — declaration completeness, no over-marking of
modelling columns, and no PII value in a profile, a serialised profile, or a
schema field.

`test_dataset_api.py` (27) — route contracts against a real database:
pagination, progress, structured 404, every control returned, net and gross
shortfall as separate fields, lead-time exclusions, defect register with its
rule, a failed control producing a blocking message while remaining visible,
the canonical-key explanation, four branch universes, the two order-file keys,
findings and filtering, content hashes, PII containment, and a 202 that does
not await the ~475 s ingestion.

**Frontend — 46 passed** (was 23)

```
Test Files  6 passed (6)
     Tests  46 passed (46)
```

`DataStudioPage.test.tsx` (12) — loading and error states, the
start-ingestion empty state, live progress with an accessible progressbar, all
11 controls rendered, a failed control still shown with its measured value and
remediation, net and gross shortfall as distinct figures, lead-time exclusions,
the defect register with rules, source files with hashes, named PII exclusions,
and no fabricated figures before data arrives.

`MappingPage.test.tsx` (10) — empty and running states, the canonical-versus-
Oracle contrast, the key rule and its justification, four branch universes, the
two non-equivalent order-file keys, findings, PII flagged with no sample value,
and an honest phase notice for editable mapping.

`accessibility.test.tsx` (+2) — theme-toggle regressions.

### Files created

**Backend (14)** — `app/models/datasets.py`, `app/models/__init__.py`,
`app/services/ingestion/readers.py`, `app/services/ingestion/ais_ingestion.py`,
`app/domain/ais/source_spec.py`, `app/domain/ais/cleaning.py`,
`app/domain/ais/controls.py`, `app/services/dataset_service.py`,
`app/jobs/runner.py`, `app/schemas/datasets.py`, `app/api/routes/datasets.py`,
`alembic.ini`, `alembic/env.py`, `alembic/script.py.mako`.

**Backend tests (4)** — `test_cleaning_rules.py`, `test_controls.py`,
`test_pii_exclusion.py`, `test_dataset_api.py`.

**Frontend (5)** — `api/datasets.ts`, `hooks/useActiveDataset.ts`,
`components/ui/format.ts`, `test/fixtures.ts`, plus two page test files.

**Changed** — `app/main.py` (schema creation, runner shutdown),
`app/api/router.py`, `tests/conftest.py` (isolated test database),
`types/api.ts`, `styles/index.css`, `components/layout/AppShell.tsx`,
`features/data-studio/pages/DataStudioPage.tsx`,
`features/mapping/pages/MappingPage.tsx`, and four docs.

### Issues found and fixed during the phase

1. **S9 coverage failed at 65.4% against an expected ~99.9% — two real bugs.**
   The join used `Material Code` instead of `Oracle No`, and measured a set
   intersection instead of the line-weighted share the claim describes.
   Measured both ways rather than relaxing the threshold: **99.909%** via
   `Oracle No`, **93.699%** via `Material Code`. This exposed a genuine
   finding — the reliable key differs by file, since sales uses `Product Code`
   for identity while orders use `Oracle No` for the master join. Recorded as
   D-017 and defect D17, with the remediation text naming the key so nobody
   relaxes the control instead of checking it.
2. **Pydantic `alias` broke response field names.** `alias` governs
   serialization as well as validation, so `sample_values`, `columns`,
   `evidence` and `related_values` were emitted under their ORM column names.
   Switched to `validation_alias`. Caught by the route tests and confirmed
   fixed against the live API.
3. **Two test expectations were wrong, not the code.** Excel serials 45751 and
   45383 convert to 2025-04-04 and 2024-04-01; I had guessed 2025-04-02 and
   2024-03-30. Verified against the source's own `Month` labels, and the test
   now documents that cross-check. Two lead-time fixtures were also
   unrepresentative — a 5-element list whose median happened to be 3, and a
   distribution whose p95 was 3 rather than 6.
4. **Control and defect codes sorted lexically** (S1, S10, S11, S2...). Added a
   natural sort.
5. **Dark mode ignored the OS preference.** Tokens existed only under an
   explicit `data-theme`. Added a `prefers-color-scheme` block guarded with
   `:not([data-theme='light'])` so the toggle still wins in both directions.
6. **The theme toggle's first click was a no-op on a dark-preference machine.**
   It read `data-theme`, which is absent until an explicit choice is made. Now
   reads the effective theme via `matchMedia`. Two regression tests added, and
   verified in the live browser.
7. **`pytest`'s `tmp_path` raises `PermissionError`** on this machine's Temp
   directory (`scandir` denied). Used `NamedTemporaryFile` in the affected
   fixture.
8. **Tests were writing to the real database.** `app.db.session` builds its
   engine at import time, so `conftest.py` now sets `AIS_DATABASE_URL` before
   any app import, with a guard test asserting the engine points at the
   throwaway file.

### Blockers

**None.** Phase 3 can start.

### Notes carried forward

- Ingestion takes **~8 minutes**; it is a background job and the UI polls.
  Phase 7 reuses the same runner for training.
- The `sales_or_orders` SKU union is **2,391**, above the 2,260 sales universe:
  the order file contributes SKUs with no sales history. That is the cold-start
  population D-005 routes by attributes, not a control breach.
- Alembic is scaffolded and `env.py` reads the app's own settings and metadata,
  but no revision has been generated yet — the schema is currently created by
  `create_all` at startup. Phase 3 should generate the initial revision before
  the schema changes again.
- Nothing has been committed or pushed. No reference-project file was modified.

---

## Phase 3 — completed 2026-09-09

### Verified end to end against the real client data

The full lifecycle ran through the live API: create draft → confirmation gate
refuses → leakage rule blocks → review → confirm → immutability → preprocess.

```
POST   /datasets/{id}/mapping/versions   -> 201   119 assignments, 0 blocking
POST   /mappings/{id}/confirm            -> 422   unreviewed: Order Date, Inv Date, Quantity, Quantity
PATCH  (MRP Rate -> future_known_driver) -> R5 blocking, leakage remediation
PATCH  (review target + time columns)    -> unreviewed=0  can_confirm=true
POST   /mappings/{id}/confirm            -> 200   state=confirmed
PATCH  (after confirm)                   -> 409   "A confirmed mapping is immutable."
POST   /mappings/{id}/preprocess         -> 202
```

**Role distribution on the real 119 columns** (five source files):

```
static_attribute 33   ignored 32   excluded_pii 22   historical_driver 11
series_identifier 8   capacity 5   inventory 3   target_column 2
time_column 2   supply 1
```

**Preprocessing completed in 386.67 s.** Measured output:

| Table | Rows |
|---|---|
| `branch_dim` | 57 |
| `product_dim` | 6,247 (2,417 from master, 189 non-glass) |
| `order_fact` | 363,305 cells |
| `sales_fact` | 558,367 cells |
| `stock_position` | 144,920 |
| distinct series | 70,089 |
| distinct periods | **28** (2024-04 → 2026-07) |

**Two independent confirmations of earlier claims, now measured rather than
predicted:**

- **30.0% of order cells are censored** (109,145 of 363,305). The analysis
  document independently reports "30.0% of depot × SKU × month cells had some
  shortfall". Different code path, same number.
- **28 monthly periods spanning Apr 2024 – Jul 2026**, from 16 order periods
  plus 24 sales periods — exactly the hybrid span D-002 predicted.

**Other measured facts:** 0 order depots outside Location Master, 2 order SKUs
outside the product master, 0 order lines without a usable date, transposition
corrected in `FY 25-26 Sales`, `Doc Series` dropped from `FY 24-25 Sales` by the
name-based union, 2 negative stock rows preserved and excluded from usable
quantity, 44,015 unclassified stock cells, Rs 20.91 cr closing value.

**Alembic baseline generated and round-tripped:** `195e0924d846` creates all 11
tables; `downgrade base` returns the database to `alembic_version` only.

**UI verified in the browser** against the live API: 119 role rows rendered,
selects correctly locked on the confirmed mapping, immutability notice shown,
5 artifact rows, and all six preprocessing tiles carrying real numbers.

### Test results (actual output)

**Backend — 238 passed** (was 147)

```
........................................................................ [ 60%]
........................................................................ [ 90%]
......................                                                   [100%]
238 passed in 6.23s
```

New: `test_roles.py` (48) — every rule R1–R9 including the multi-source
singleton case; PII may only be excluded; the future-known leakage rule and its
skip-when-unknowable case; every violation returned rather than the first; and
the suggester — PII outranks everything, a date-parsing column wins the time
role, constants are ignored, a price is historical *never* future-known, no
stock or fulfilment quantity is ever suggested as the target, unrecognised
numerics default to historical drivers, target contention is resolved and
stated, and no column is left unclassified.

`test_mapping_api.py` (30) — advisory suggestions, template defaults, config
defaults suited to intermittent demand, everything starts unreviewed, editing
clears the suggestion, PII cannot be reassigned, unknown columns rejected,
rules produce blocking and warning rows, confirmation refused while the target
is unreviewed and while a rule fails, immutability, double-confirm refused,
supersession, and the preprocessing gate.

`test_migrations.py` (10) — fresh/managed/pre-baseline start states, missing
tables actually created, pre-existing data survives adoption, the drift-repair
path, and a check that every ORM table is covered by a migration.

`test_preprocessing.py` (7) — month keying, censoring set only on a genuine
shortfall, over-delivery not counted as censoring, mean MRP null rather than
zero without observations.

**Frontend — 69 passed** (was 46)

```
Test Files  7 passed (7)
     Tests  69 passed (69)
```

New: `RoleEditor.test.tsx` (20) — one row per assignment, draft roles editable,
same-named columns from different sources disambiguated, PII never offered a
select, edits sent to the API, suggested/reviewed distinction, non-future-known
reasons shown, blocking rule with remediation, confirmation disabled while
unreviewed and while blocked, name required, confirm call, API refusal
surfaced, everything locked once confirmed, the reviewed-count note,
preprocessing offered only when confirmed, and source/role/unreviewed filters.

`MappingPage.test.tsx` — the three obsolete Phase-3-placeholder assertions
replaced with tests of the real editor, the create-draft empty state, and the
honest not-preprocessed-yet state.

### Files created

**Backend (9)** — `app/ml/features/roles.py`,
`app/ml/features/role_suggestion.py`, `app/domain/ais/mapping_template.py`,
`app/models/mappings.py`, `app/services/preprocessing/ais_preprocessing.py`,
`app/services/mapping_service.py`, `app/schemas/mappings.py`,
`app/api/routes/mappings.py`, `app/db/migrate.py`, plus
`alembic/versions/195e0924d846_*.py`.

**Backend tests (4)** — `test_roles.py`, `test_mapping_api.py`,
`test_migrations.py`, `test_preprocessing.py`.

**Frontend (3)** — `api/mappings.ts`,
`features/mapping/components/RoleEditor.tsx`,
`features/mapping/components/PreprocessingPanel.tsx`.

**Changed** — `app/main.py` (Alembic instead of `create_all`),
`app/api/router.py`, `app/models/__init__.py`, `alembic/env.py`,
`types/api.ts`, `test/fixtures.ts`, `MappingPage.tsx`,
`features/mapping/__tests__/MappingPage.test.tsx`, and four docs.

### Issues found and fixed during the phase

1. **The singleton-role rule blocked the only correct mapping.** Two columns
   claimed `target_column` and two claimed `time_column`, and both were right:
   the order file and the sales file each contribute their own, which the
   hybrid target needs. Scoped the rule per source. A generic design error, not
   an AIS quirk. (D-019)
2. **My own `ensure_schema` corrupted the real database.** It stamped a
   pre-baseline database at head, so the Phase 3 tables were never created and
   the first mapping request died with `no such table: mapping_version`. Now
   creates missing tables before stamping, plus a drift check that repairs and
   logs when a database claims head but lacks a declared table. (D-023)
3. **`alembic/env.py` overwrote a caller-supplied URL** with the app setting,
   sending a programmatic `command.upgrade` at the app database rather than the
   requested one. It now only falls back when no URL is set.
4. **Stale relationship collections after re-validation.** The session uses
   `expire_on_commit=False`, so re-reading a mapping straight after `validate()`
   deleted and re-inserted its rule results returned the *old* collection and
   the caller saw no violations at all. Added `populate_existing=True`.
5. **`can_confirm` treated "zero violations" as "not validated"** and refused a
   clean mapping. An empty rule list is the good case.
6. **The policy rules R8 and R9 could never fire.** `_to_config` passed raw DB
   strings where the rules compare enum identity with `is`, which is silently
   false against a string. Now coerced to enum members.
7. **`product_dim` reported `non_glass: 0`** despite 5,183 non-glass stock rows
   catalogued as defect D13. The flag was applied only to SKUs already in the
   glass-only product master, so orphan rows lost it. Now applied after orphan
   creation — 189 non-glass SKUs. (D-024)
8. **The suggester labelled `CLO QTY` as the forecast target**, because `qty`
   matched the demand cue before any inventory cue. A stock quantity standing in
   for demand is the worst available mislabel; closing-balance abbreviations are
   now recognised, with tests asserting no stock or fulfilment quantity is ever
   suggested as the target.
9. **Two comboboxes shared an accessible name.** Both the order and sales files
   carry a column called `Quantity`, so a screen-reader user could not tell the
   selects apart. The label now includes the source.
10. **A confirmed mapping showed 115 columns as "Suggested"**, which reads like
    confirmation did not stick. It is accurate — they kept their template
    default — so the UI now states how many columns a person actually reviewed
    rather than relabelling them.

### Blockers

**None.** Phase 4 can start.

### Notes carried forward

- **`distinct_series` is 70,089, above the 63,210 control.** Not a breach: the
  control counts branch × SKU in *sales only*, while preprocessing spans the
  union of the order and sales facts. Phase 4 must decide the panel's series
  universe explicitly and state which number it uses.
- **`product_dim` is 6,247 rows**, of which 2,417 come from the product master.
  The remainder are stock-only or order-only SKUs, including 189 non-glass.
  D-005 scopes the forecast to the sales ∪ orders universe, so Phase 4 filters
  rather than forecasting all 6,247.
- Preprocessing takes **~390 s** and re-streams the sources every run.
- Only **4 of 119** columns were reviewed by a person; the rest kept template
  defaults. That is the intended gate, and the UI states it.
- Two preprocessing runs exist in the database; the newer one carries the
  non-glass fix. Phase 4 must read the latest, not the first.
- Nothing committed or pushed. No reference-project file modified.

---

## Phase 4 — completed 2026-09-09

### Verified against the real client data

The panel was built from the newest preprocessing run, at the mandated
2025-09 training cut, in **139.9 s**:

| Artifact | Rows | Grain |
|---|---|---|
| `panel` | **1,503,753** | branch × SKU × month |
| `origin_features` | 1,503,753 | one row per (series, origin) |
| `training_frame` | **3,895,148** | one row per (series, origin, horizon) |
| `scoring_frame` | 360,702 | one row per (series, horizon) from the cut |

- **68,675 series**, **28 monthly periods**, Apr 2024 – Jul 2026
- **634,951 observed rows** and **868,802 materialised zeros** (57.8% of cells)
- **994,526 `order` rows** and **509,227 `sales_proxy` rows**
- **109,145 censored rows** — demand there was at least the observed value
- **35 features**, deepest lookback 11 months, horizons 1–6
- 17 training origins; **286,721** sales rows superseded by the order book

**The scoring frame's origin of 2025-09 targets Oct 2025 – Mar 2026**, which is
exactly the mandated validation window — reached by construction, not by
configuration.

**Sparsity, measured:** 10,877 series have exactly one non-zero month (the
analysis document independently reports ~10,200 single-month series); 21,804
have twelve or more; median observed months 26; median non-zero months 6;
median ADI 3.0; median CV² 0.201.

### Leakage verified on real data, not only fixtures

A spot-check walked every one of the 87 training rows of the longest-history
real series:

```
rows checked                     : 87
y != panel[target_period]        : 0
lag_1 != panel[origin_period]    : 0
target != origin + horizon       : 0
```

And the cut bounds both ends, as it must: with a 2025-09 cut the maximum origin
is **2025-08** and the maximum target is **2025-09**. No target beyond the cut.

The hybrid target is visible in a single real series — `sales_proxy` for
Apr 2024 – Mar 2025, then `order` from Apr 2025, with materialised zeros
labelled `true_zero` throughout and `despatched_qty` null on every proxy row.

The whole build also runs clean under `-W error::FutureWarning`, so the
nullable-dtype handling is forward-compatible rather than merely quiet today.

### Test results (actual output)

**Backend — 298 passed** (was 238)

```
........................................................................ [ 96%]
..........                                                               [100%]
298 passed in 10.82s
```

New: `test_leakage.py` (42) — the lag convention (`lag_1` is the origin's own
value; early lags missing, never zero-filled); rolling windows ending at the
origin and never reaching forward; population `ddof=0` matching the
references' `pstdev`; sparsity and obsolescence run counting; **corrupting
every value after an origin changes no feature at that origin**; one series
cannot see another; row order is irrelevant; a gapped panel raises rather than
silently mislabelling; `y` matches the panel at `target_period`; no lag ever
equals `y`; the cut bounds the target as well as the origin; all horizons share
one frame; `same_month_last_year` is indexed on the target; the scoring frame
carries no `y` and only future periods; the period grid invents no history and
is gapless; and the manifest declares per feature whether it uses target
history.

`test_panel_api.py` (18) — 202 without waiting, defaulting to the **newest**
completed preprocessing run, refusing an incomplete run or one without
artifacts, guidance when no run exists, a malformed cut period rejected,
horizons deduplicated and sorted, an empty horizon set refused, observed and
materialised rows reported separately and summing to the panel row count, the
two target sources distinguished, and the panel universe kept separate from the
63,210 control.

**Frontend — 80 passed** (was 69)

```
Test Files  8 passed (8)
     Tests  80 passed (80)
```

New: `PanelPanel.test.tsx` (11) — the build empty state, starting at the
mandated cut, live progress with an accessible progressbar, observed versus
materialised rows as different facts, the "a zero is a real observation"
explanation, the two target sources never presented as equivalent, the panel
universe separated from the 63,210 control, the sparsity table, horizon-as-a-
feature rather than recursive chaining, a surfaced failure reason, and no
figures shown while a build is still running.

### Files created

**Backend (7)** — `app/ml/features/feature_builder.py`,
`app/ml/features/panel.py`, `app/domain/ais/panel_builder.py`,
`app/models/panel.py`, `app/services/panel_service.py`,
`app/schemas/panel.py`, `app/api/routes/panel.py`, plus
`alembic/versions/c18b5336f053_panel_build.py`.

**Backend tests (2)** — `test_leakage.py`, `test_panel_api.py`.

**Frontend (3)** — `api/panel.ts`,
`features/mapping/components/PanelPanel.tsx`,
`features/mapping/__tests__/PanelPanel.test.tsx`.

**Changed** — `app/api/router.py`, `app/models/__init__.py`,
`app/models/mappings.py` (panel-build relationship), `types/api.ts`,
`test/fixtures.ts`, `MappingPage.tsx`, and three docs.

### Issues found and fixed during the phase

1. **`build_period_grid` reported zero materialised rows.** It detected
   materialisation by scanning for NaN, but the normal caller passes only the
   key columns and joins values afterwards — so nothing was ever NaN and every
   filled month was counted as observed. The stat fed the manifest, so it would
   have quietly misreported panel composition. Now decided by whether the
   `(series, period)` key was observed.
2. **Four pandas `FutureWarning`s** from all-NA object columns in `concat` and
   from `.fillna(...).astype(bool)` on object dtype. Fixed with explicit
   nullable dtypes (`Float64`, `boolean`), which also keeps the Parquet output
   properly typed rather than object-typed. The build now runs clean under
   `-W error::FutureWarning`.
3. **A misleading summary field.** `non_glass_series_in_panel` reads 0, which
   looks like the D-024 flag failing again. It is correct: non-glass SKUs are
   stock-only, so the demand-bearing universe excludes them by construction.
   The field now carries a comment saying so.
4. **Two test-query mistakes of my own** — a Testing Library regex that did not
   match the real copy, and a first-series pick that had no training rows
   because it started at the cut.

### Blockers

**None.** Phase 5 can start.

### Notes carried forward

- **The training frame is 4× the analysis document's 948,150 rows** because it
  uses every valid origin up to the cut rather than a restricted set. A
  deliberate difference, recorded in D-029 rather than presented as parity. At
  3.9 M rows the pooled XGBoost fit is roughly 90 s per model, so point plus
  three quantiles is about six minutes — inside the budget.
- **`min_series_age` exists on the training-frame builder but defaults to 1**
  (no filter). Phase 6 or 7 should consider raising it: XGBoost's reference
  minimum is 5 lagged rows, and origins with one month of history contribute
  mostly-missing lags.
- **Three series universes now coexist** — 63,210 (sales control), 70,089
  (preprocessing union), 68,675 (panel). Each is reported by name; none is a
  breach of the others.
- The panel carries context columns (`mean_mrp`, lead times, stock fields) that
  are deliberately **not** future-known features. Phase 5 must not promote them
  into the exogenous matrix.
- Nothing committed or pushed. No reference-project file modified.

---

## Phase 5 — completed 2026-09-09

### Verified against real client data, not fixtures

All thirteen models were fitted on a real AIS series taken from the Phase 4
panel — `DELHI-2|FG.M1C.LFH.GCG2120000`, 28 months — under both history
profiles, on a trailing six-month holdout (22 training months, i.e. train
through Jan 2026, which is the *second* mandated origin of
`docs/ARCHITECTURE.md` §7, not the primary Sep 2025 cut; the primary cut leaves
18 training months and Phase 6 measures it):

```
=== profile reference ===
  resolved period : None
  rejected        : {12: 'needs 24 observations for two complete cycles,
                          reference window has 22'}
  outcome         : {'COMPLETED': 7, 'INELIGIBLE': 6}
  not completed   : ['auto_arima', 'auto_arima_exog', 'exp_additive',
                     'exp_additive_damped', 'exp_multiplicative',
                     'exp_multiplicative_damped']

=== profile monthly_relaxed ===
  resolved period : 6 (strength 0.242)
  outcome         : {'COMPLETED': 13}
```

The six Ineligible under the default profile are exactly the six §5 predicted
before any adapter existed, all for `insufficient_history`, each carrying its
requirement and remediation. None was hidden, none was replaced by a zero
forecast, and one model's ineligibility stopped nothing else.

Measured fit times on that series: `sarimax` 2.0 s, `sarimax_exog` 0.13 s,
`xgboost` 1.4 s, `var` 0.37 s, `var_exog` 0.03 s, `lstm` 10.9 s.

**Persistence round-trips exactly.** All nine models eligible on that series —
LSTM included — reload and predict identical values. Neither reference project
persists a trained model at all, so this is new work (D-035).

### Test results (actual output)

Backend:

```
392 passed in 51.55s
```

| File | Tests |
|---|---|
| `tests/test_api_contract.py` | 12 |
| `tests/test_cleaning_rules.py` | 69 |
| `tests/test_controls.py` | 21 |
| `tests/test_dataset_api.py` | 20 |
| `tests/test_leakage.py` | 42 |
| `tests/test_mapping_api.py` | 28 |
| `tests/test_migrations.py` | 10 |
| **`tests/test_ml_adapters.py`** | **91 (new this phase)** |
| `tests/test_model_registry.py` | 16 |
| `tests/test_panel_api.py` | 18 |
| `tests/test_pii_exclusion.py` | 12 |
| `tests/test_preprocessing.py` | 6 |
| `tests/test_roles.py` | 47 |

Frontend:

```
 Test Files  9 passed (9)
      Tests  82 passed (82)
   Duration  8.08s
```

`npx tsc -b` — clean, no output.

The load-bearing adapter tests:

- `test_recursion_does_not_consume_actuals_by_default` — blinding the output
  frame's actuals changes no prediction under the default; with
  `allow_actuals_in_recursion=True` it does. Both directions are asserted, so
  the reference behaviour stays reproducible and is provably not the default
  (D-031).
- `test_the_relaxed_profile_admits_every_model` — all 13 reach `COMPLETED`.
- Save/load round-trip per family, including the Keras path.

### Files created

| File | Lines | Purpose |
|---|---|---|
| `backend/app/ml/adapters/base.py` | 395 | The common contract; `validate_eligibility` never raises |
| `backend/app/ml/adapters/sarimax_adapter.py` | 184 | SARIMAX x2, Sodexo's AR-collision guard |
| `backend/app/ml/adapters/auto_arima_adapter.py` | 176 | Auto ARIMA x2, `aicc` |
| `backend/app/ml/adapters/xgboost_adapter.py` | 389 | XGBoost x2, direct multi-horizon default |
| `backend/app/ml/adapters/exp_smoothing_adapter.py` | 204 | The four ES variants |
| `backend/app/ml/adapters/var_adapter.py` | 299 | VAR x2, generalized, reads column 0 |
| `backend/app/ml/adapters/lstm_adapter.py` | 236 | LSTM, 64 units, patience-8 |
| `backend/app/ml/legacy_models/exog.py` | 224 | Exogenous pairing, rank and collinearity guards |
| `backend/app/ml/evaluation/seasonality.py` | 136 | Per-profile seasonal-period resolution |
| `backend/app/domain/ais/exog_features.py` | 95 | The only AIS-aware file in the model path |
| `backend/app/ml/registry/model_registry.py` | 133 | Binds all 13; `assert_registry_bound()` |
| `backend/tests/test_ml_adapters.py` | 737 | 91 tests |
| `frontend/src/test/no-live-backend.test.ts` | 29 | Proves the test transport is guarded |

Changed: `backend/app/main.py` (second startup assertion),
`backend/app/services/model_contract_service.py` (duplicate `_MIN_HISTORY`
table deleted), `frontend/src/test/setup.ts`, `frontend/src/api/client.ts`,
`docs/DECISIONS.md`, `docs/MODEL_INVENTORY.md`, `docs/STATUS.md`.

### Decisions recorded

D-031 through D-036 in `docs/DECISIONS.md` — recursive folds must not consume
actuals; the exogenous set is calendar features and that is the honest answer;
the relaxed profile needed a shorter seasonal period to mean anything; VAR
reads the target from column 0 rather than summing; persistence is new work;
the API reads its thresholds from the adapters rather than a second table.

### Issues found and fixed during the phase

1. **Base eligibility hardcoded the label column `target`**, but the Phase 4
   direct multi-horizon frame labels it `y` — so both XGBoost variants, the two
   models that most need that frame, were reported Ineligible for a reason that
   was an artefact of my own contract. Added `label_columns`, so each model
   declares what it reads.
2. **The four `_exog` variants were permanently ineligible** — the per-series
   frame carried no future-known column at all, so the exogenous matrix was
   always empty. Ineligible for a fixable reason is worse than ineligible for a
   real one; `exog_features.py` fixes it honestly rather than by promoting a
   historical driver (D-032).
3. **`monthly_relaxed` did not deliver what D-001 promised.** Lowering the row
   threshold left the ES variants ineligible anyway on their *second* gate, two
   complete seasonal cycles. Fixed by resolving the period per profile (D-033).
4. **Both reference projects feed actuals into recursive validation folds** —
   verified at four exact lines. Resolved deliberately and recorded rather than
   copied (D-031).
5. **A duplicated `_MIN_HISTORY` table** in `model_contract_service` was free
   to drift from what the adapters enforce. Deleted (D-036).
6. **`numpy==2.0.2` was unsatisfiable** against `tensorflow-cpu==2.17.0`, which
   pins `numpy<2.0.0` — a hard `ResolutionImpossible`, not a warning. Repinned
   to 1.26.4.
7. **The registry assertion reported the wrong failure.** A baseline promoted
   into the 13 surfaced as a display-name count mismatch, which points at the
   wrong file. The overlap check now runs first.
8. **Vitest 2 bundles its own Vite 5**, which clashed with Vite 6 and broke
   `tsc -b`. Upgraded to Vitest 3.2.7.
9. **The frontend suite was opening real sockets.** Tests stub the `api/`
   modules per test; any query a test did not stub reached the real axios
   client, and axios in jsdom uses XHR — so jsdom attempted 127.0.0.1:8000 and
   logged unattributed `AggregateError` stacks. Nothing failed, which is the
   problem: a test running while a dev backend was up would have silently
   exercised live data instead of its fixtures. The transport now rejects by
   default, `client.ts` keeps the underlying error as `cause` so the endpoint
   name survives its generic user-facing message, and
   `no-live-backend.test.ts` asserts the guard is installed.
10. **Test-expectation mistakes of my own** — a first-series pick with no
    training rows, and Testing Library regexes that did not match the real copy.

### Blockers

**None.** Phase 6 can start.

### Notes carried forward

- **No accuracy figure exists yet.** Fitting is not evaluation. Phase 6 owns
  rolling-origin backtesting and the metric set; until it runs, any number
  describing model quality would be fabricated.
- **The default profile leaves 6 of 13 uncompared** at monthly grain, and that
  is the truthful default. `monthly_relaxed` compares all 13 at the cost of a
  weaker seasonal claim, and the profile label carries that cost. Phase 8 must
  never present a champion chosen under one profile as if chosen under the
  other.
- **`predict_quantiles` needs backtest residuals**, which do not exist until
  Phase 6. The adapters expose the method and the residual store is empty; no
  interval is fabricated in the meantime.
- **LSTM is the budget risk** at 10.9 s per fit on one series. At 63,210 series
  it cannot be fitted per series, which is what the tiering in Phase 7 is for.
- **MinT is still not computable at 63,210 base series** (~32 GB dense
  covariance). Variance-scaling below, shrinkage above, as recorded in Phase 0.
- Nothing committed or pushed. No reference-project file modified — a
  `find -newermt` scan over all three roots returns zero files. The five AIS
  source files retain their 2026-09-08 timestamps.

---

## Phase 6 — completed 2026-09-09

### The headline finding, stated first

**On the median series, the registered models do not beat a six-month moving
average.** Measured on a 60-series stratified sample (12 per demand segment),
both mandated origins, `monthly_relaxed`, median pooled WAPE:

| | Median WAPE | n |
|---|---|---|
| `var` | **64.55** | 6 |
| **`ma6` (baseline)** | **90.69** | 46 |
| `ma3` (baseline) | 91.93 | 46 |
| `exp_additive_damped` | 93.22 | 42 |
| `naive` (baseline) | 100.00 | 46 |
| `xgboost` | 102.76 | 46 |
| `seasonal_naive` (baseline) | 108.47 | 46 |
| `sarimax` | 116.35 | 46 |

`var` is the only registered model ahead of `ma6`, and it completed on 6 of 60
series - it is ineligible on the rest for want of two non-constant endogenous
series, so that 64.55 describes six easy series, not a win.

This is exactly what the baselines exist to reveal, and it is why they are
computed on the same origins as the 13 rather than quoted from elsewhere. Two
caveats, both real:

- The sample is **stratified by segment**, not drawn in population proportion.
  The real panel is 61.96% intermittent and 15.84% single-event, so a
  population-weighted median would sit differently. Neither figure is the
  other, and this one is labelled.
- A single well-behaved series tells the opposite story: on
  `DELHI-2|FG.M1C.LFH.GCG2120000` (smooth, 28 months) `sarimax` reaches WAPE
  30.29 against `seasonal_naive` 36.52 and `ma6` 43.83.

No champion is being selected here - that is Phase 8 - but Phase 8 must not
present a champion that loses to `ma6` without saying so.

### Verified against real client data

Origins resolved from the panel's own range (2024-04..2026-07, 28 periods):

```
  primary  train 2024-04..2025-09 (18m)  val 2025-10..2026-03  mandated=True
  second   train 2024-04..2026-01 (22m)  val 2026-02..2026-07  mandated=True
  total test periods 12, distinct 10   (the two windows overlap on 2026-02..03)
```

All 13 on a real series, both profiles:

| Profile | Completed | Ineligible | Failed |
|---|---|---|---|
| `reference` | **7** | **6** | 0 |
| `monthly_relaxed` | **13** | 0 | 0 |

The six ineligible under the default are `auto_arima`, `auto_arima_exog` and
the four `exp_*` variants - the same six Phase 0 predicted and Phase 5
measured. `auto_arima` reports "this window has 22" and `exp_additive` reports
"18" because the first uses the fast-holdout origin and the second uses the
first rolling origin; both are correct for the window they were given.

Quantile calibration, measured **out of sample**: residuals collected from the
`primary` origin only, calibrated, then applied to the `second` origin's point
forecasts, which the calibration never saw. 900 residuals across 96 cells, 996
held-out points:

| Level | Target | Achieved | Mean pinball |
|---|---|---|---|
| q80 | 80% | **79.72%** | 1.622 |
| q90 | 90% | **89.06%** | 1.368 |
| q95 | 95% | **93.07%** | 1.125 |

q95 under-covers by 1.9 points, which is consistent with its pooling: q95 needs
19 residuals for a genuine order statistic, so 84 of 96 cells fell back from
`model_horizon_segment` to `model_horizon`, against 24 of 96 at q80. Every
offset was `conformal` - none had to interpolate - because the fallback found
enough residuals rather than because the finest cell was dense.

**196 of 996 rows (19.7%) needed a monotonicity correction.** That is high, and
it is a symptom rather than a bug: q80 is calibrated on a finer pool than q95,
so their offsets come from different populations and can cross. The count is
reported rather than silently sorted away.

### Test results (actual output)

```
506 passed in 38.65s
```

| File | Tests |
|---|---|
| `tests/test_api_contract.py` | 12 |
| **`tests/test_backtest.py`** | **37 (new)** |
| `tests/test_cleaning_rules.py` | 69 |
| `tests/test_controls.py` | 21 |
| `tests/test_dataset_api.py` | 20 |
| `tests/test_leakage.py` | 42 |
| `tests/test_mapping_api.py` | 28 |
| **`tests/test_metrics.py`** | **77 (new)** |
| `tests/test_migrations.py` | 10 |
| `tests/test_ml_adapters.py` | 91 |
| `tests/test_model_registry.py` | 16 |
| `tests/test_panel_api.py` | 18 |
| `tests/test_pii_exclusion.py` | 12 |
| `tests/test_preprocessing.py` | 6 |
| `tests/test_roles.py` | 47 |

Frontend unchanged this phase: 82 passed, `tsc -b` clean.

The load-bearing tests:

- `test_reference_metrics_match_an_independent_transcription` re-implements
  Meriton/Sodexo's algorithm **inside the test** and compares, over seven
  input shapes including all-zero and NaN-bearing windows. Parity is checked
  against the references, not against our own port.
- `test_corrupting_the_validation_window_changes_no_prediction` sets every
  post-origin actual to 999,999 and asserts no prediction moves.
- `test_the_resolved_period_equals_resolving_on_that_window_alone` asserts each
  fold's seasonal period equals what the resolver returns for that fold's
  training slice in isolation.
- `test_mase_denominator_ignores_the_validation_window` corrupts the validation
  actuals and asserts the naive benchmark does not move.
- `test_all_thirteen_come_back_whatever_happened_to_them` runs the whole
  registry and asserts every model reaches a terminal status with a reason -
  7 completed, 6 ineligible, matching the real-data result.
- `test_a_divergent_forecast_contributes_no_residuals` - the guard has to keep
  a runaway series out of the quantile calibration too, not just the metrics.

### Files created

| File | Lines | Purpose |
|---|---|---|
| `backend/app/ml/evaluation/folds.py` | 266 | Origins, the mandated pair, overlap accounting |
| `backend/app/ml/evaluation/metrics.py` | 393 | Reference parity + the AIS metric set |
| `backend/app/ml/evaluation/baselines.py` | 185 | The four non-registry baselines |
| `backend/app/ml/evaluation/segmentation.py` | 182 | Syntetos-Boylan classification |
| `backend/app/ml/evaluation/quantiles.py` | 343 | Residual store, conformal/empirical offsets, monotonicity |
| `backend/app/ml/evaluation/backtest.py` | 615 | The orchestrator and the status vocabulary |
| `backend/app/domain/ais/backtest_runner.py` | 285 | AIS wiring, window composition, censoring counts |
| `backend/tests/test_metrics.py` | 623 | 77 tests |
| `backend/tests/test_backtest.py` | 554 | 37 tests |

Changed: `backend/app/ml/evaluation/seasonality.py` (delegates
`smallest_fold_train_size` to `folds.py` rather than keeping a second copy),
`backend/app/ml/adapters/var_adapter.py` (exogenous index alignment),
`docs/DECISIONS.md`, `docs/MODEL_INVENTORY.md`, `docs/STATUS.md`.

### Decisions recorded

D-037 through D-041 in `docs/DECISIONS.md` - a fast-holdout model gets fewer
test points and the leaderboard says so; the mandated origins overlap so
pooling de-duplicates; the evaluation budget is an admission gate and a
post-hoc verdict, not pre-emption; the primary origin trains mostly on the
sales proxy and validates entirely on orders; a divergent forecast is refused
at the evaluation boundary rather than fixed in the fitter.

### Issues found and fixed during the phase

1. **`var_exog` failed on every real series** - `ValueError: The indices for
   endog and exog are not aligned`. `_prepare_endog` resets its index while
   `build_exog_pair` keeps the caller's, and a panel slice carries parquet row
   numbers, so statsmodels saw two different indices. Invisible in Phase 5
   because no exogenous columns were being supplied to VAR at all. Fixed by
   aligning positionally, with a length assertion so that stays a fact rather
   than an assumption - a silent length mismatch would shift every driver
   against its own month.
2. **SARIMAX produced a forecast of 3.67e11** against actuals of 0-10, on a
   panel whose largest observed value anywhere is 745. Inherited from both
   references' `enforce_stationarity=False`. It moved the pooled pinball loss
   from 1.62 to 78,922,256. Resolved by a guard at the evaluation boundary
   rather than by quietly changing the fitter (D-041).
3. **My own docs misstated the primary origin's training length.** The Phase 5
   entry said "22 of them before the September 2025 cut". 22 is the trailing
   six-month holdout figure - train through 2026-01, the *second* origin. The
   mandated cut leaves **18**. Corrected in `docs/STATUS.md` and
   `docs/MODEL_INVENTORY.md`, and `test_the_primary_origin_trains_on_eighteen_months_not_twenty_two`
   now pins it.
4. **`conformal_minimum(0.80)` returned 5 instead of 4.** The closed form
   `level / (1 - level)` is algebraically right and numerically wrong: in
   binary floating point `0.8 / 0.2` is 4.000000000000001, whose ceiling is 5.
   It would have demanded a fifth residual at q80 that the order statistic does
   not need. Now solved by evaluating the actual condition.
5. **`smallest_fold_train_size` existed in two places** once `folds.py` was
   added. Deleted from `seasonality.py`, which now re-exports it - the D-036
   lesson applied before it could drift.
6. **Two of my own tests were weaker than their names.** One claimed to prove
   per-fold seasonal resolution but only asserted the training windows
   differed; it now uses a series that is flat for 18 months and 6-periodic
   afterwards, so the primary origin *cannot* see the cycle. The other claimed
   "every registered model comes back" while requesting three; it now requests
   all 13, and the fixture carries the calendar drivers so the four `_exog`
   variants are genuinely exercised instead of being ineligible for want of a
   column.

### Blockers

**None.** Phase 7 can start.

### Notes carried forward

- **`ruff` is configured in `pyproject.toml` but not installed** in the backend
  venv, so no lint has ever run on this codebase. Not installed as part of this
  phase because a first lint of ~10k lines is its own change, not a Phase 6
  change.
- **Budget pre-emption is Phase 7's.** `TIMED_OUT` currently means "overran and
  was discarded", not "was stopped". LSTM at 10.9 s x 68,675 series is 208
  hours, so the tiering in `docs/ARCHITECTURE.md` §6 is load-bearing, not an
  optimisation.
- **q95 pooling is thin.** 84 of 96 cells fall back past
  `model_horizon_segment`. Phase 9 should re-measure coverage once residuals
  come from a full run rather than a 60-series sample; more residuals should
  pull q95 from 93.07% toward 95%.
- **The 19.7% monotonicity correction rate should fall** for the same reason.
  If it does not once residuals are plentiful, the per-level pooling
  independence is the thing to revisit.
- **`var` is ineligible on 54 of 60 sampled series** - it needs two
  non-constant endogenous series and `despatched_qty` is frequently constant or
  null. That is a real property of the data, not a defect, but it means VAR's
  leaderboard presence will be sparse and its metrics drawn from an easier
  subpopulation. Phase 8 must not compare its median against a model evaluated
  on all 60.
- Nothing committed or pushed. No reference-project file modified. The five AIS
  source files retain their 2026-09-08 timestamps.

---

## Phase 7 — completed 2026-09-09

### The state this phase inherited

The service layer existed from a previous session but had never run. Finishing
it turned up a defect that had made the **whole application** unimportable:
`TrainingRun.calibrations` declared `back_populates="training_run"` while
`QuantileCalibration` never defined that relationship, so SQLAlchemy's mapper
configuration raised `KeyError: 'training_run'` on the first ORM instantiation.
Every test touching any model failed with it. Fixed by adding the reverse
relationship.

### Verified against real client data

Two independent aggregate-tier runs over the real 1,503,753-row panel:

| Measure | Run 1 | Run 2 |
|---|---|---|
| `model_run` rows | 1,173 | 1,173 |
| Distinct models | 17 (13 + 4 baselines) | 17 |
| Completed / ineligible / **failed** | 738 / 435 / **0** | 738 / 435 / **0** |
| Calibration cells | 126 | 126 |
| Residuals recorded | 5,148 | 5,148 |
| Wall clock | 275.8 s | 276 s |
| Estimate shown beforehand | 424.5 s | 424.5 s |
| National `var_exog` WAPE | 4.5784% | 4.5784% |

**The two runs produced byte-identical WAPEs across all 17 models.** That is the
determinism claim, measured rather than asserted.

The estimate over-predicted by 35%. It is stored on the run beside
`duration_seconds` so the gap is auditable rather than forgotten.

A third run added the local tier (100 series): 2,873 rows over 169 scopes,
1,832 completed, 1,041 ineligible, 0 failed.

### The national leaderboard, as measured

```
var_exog                     completed   wape= 4.578  pts=10  rolling_origin
sarimax_exog                 completed   wape= 6.192  pts=10  rolling_origin
var                          completed   wape= 9.603  pts=10  rolling_origin
xgboost_exog                 completed   wape=10.603  pts=10  rolling_origin
xgboost                      completed   wape=11.156  pts=10  rolling_origin
sarimax                      completed   wape=13.157  pts=10  rolling_origin
lstm                         completed   wape=14.661  pts= 6  holdout_fast
auto_arima                   ineligible  needs 24 training observations; window has 22
auto_arima_exog              ineligible  needs 24 training observations; window has 22
exp_additive                 ineligible  needs 24 training observations; window has 22
exp_additive_damped          ineligible  needs 24 training observations; window has 22
exp_multiplicative           ineligible  needs 24 training observations; window has 22
exp_multiplicative_damped    ineligible  needs 24 training observations; window has 22
--- non-registry baselines ---
ma6                          completed   wape= 9.939  pts=10
ma3                          completed   wape=10.314  pts=10
naive / seasonal_naive       completed   wape=11.835  pts=10
```

At the national aggregate the registered models **do** beat the baselines —
`var_exog` at 4.578% against `ma6` at 9.939%, a 53.9% improvement. That is the
opposite of the Phase 6 finding on the median *individual series*, and the
difference is the aggregation level: a national total is far less intermittent
than the cells beneath it. Both figures are true and neither generalises to the
other.

### Test results (actual output)

```
tests/test_training_api.py .................................. [100%]
34 passed
```

### Files created

- `backend/app/api/routes/training.py` — 9 endpoints including the SSE stream
- `backend/app/schemas/training.py`
- `backend/tests/test_training_api.py`

### Files changed

- `backend/app/models/training.py` — the missing `training_run` relationship
- `backend/app/core/errors.py` — see below
- `backend/app/ml/evaluation/backtest.py` — persist per-origin actuals and
  predictions
- `backend/app/api/router.py`

### Issues found and fixed during the phase

1. **The `RequestValidationError` handler turned every 422 into a 500.**
   Pydantic puts the raw exception a custom validator raised into `ctx`, and a
   `ValueError` is not JSON serialisable, so `JSONResponse` blew up while
   rendering the error. Any endpoint with a custom validator was affected.
   Fixed by sanitising `ctx` to strings in `_serialisable_fields`.

2. **`OriginResult.as_dict()` dropped `actuals` and `predictions`.** Phase 6
   promised to persist predictions and actuals; the summariser silently omitted
   them, so an actual-versus-predicted chart could not be drawn from a stored
   run. Six floats per origin per model is a small price for evidence that can
   be checked. Added.

3. **`DEFAULT_HARD_TIMEOUT_MODELS` is deliberately empty** and a test asserted
   the opposite. The measured overhead table in `hard_timeout.py` is right: a
   fresh interpreter costs more than the fit it protects, for all thirteen. The
   test was wrong and now asserts opt-in behaviour instead.

### Blockers

**None.**

---

## Phase 8 — completed 2026-09-09

### Verified against real client data

Champion selection over the 169-scope run: **166 selected, 3 skipped**, each
skip carrying the reason "no registered model produced a rankable metric".

Champion mix across the 166 scopes:

```
lstm 42 · sarimax_exog 33 · var_exog 27 · var 20 · sarimax 19 · xgboost 16 · xgboost_exog 9
```

No single model dominates, which is the case for segment-level champions rather
than one global winner.

**47 of 166 scopes are beaten by a non-registry baseline.** Recorded on the
selection row itself (`beaten_by_baseline`), so the comparison travels with the
decision instead of living only on a leaderboard someone might not open.

Override and rollback exercised on the real national scope:

```
history after override:  [(xgboost, manual_override, active), (var_exog, automatic, superseded)]
history after rollback:  [(var_exog, rollback, active), (xgboost, manual_override, superseded),
                          (var_exog, automatic, superseded)]
active rows for overall/NATIONAL: 1
```

All four refusals fire correctly against real rows:

| Attempt | Result |
|---|---|
| Override to `ma6` | 409 — non-registry baseline, can never be champion |
| Override to `prophet` | 422 — not one of the 13 registered models |
| Override with a 5-character reason | 422 — at least 10 characters required |
| Override to `auto_arima` | 409 — ineligible in this scope, cannot serve forecasts |

### Files created

- `backend/app/ml/selection/champion.py` — the ranker, database-free
- `backend/app/models/champions.py` — append-only `champion_selection`
- `backend/app/services/champion_service.py`
- `backend/app/schemas/champions.py`
- `backend/alembic/versions/2b7edba9538f_champion_selections.py`
- `backend/tests/test_champion_selection.py`, `backend/tests/test_leaderboard_api.py`

### Test results (actual output)

```
tests/test_champion_selection.py ...........................  27 passed
tests/test_leaderboard_api.py ...........................     39 passed
```

### Decisions recorded

- **D-043** — the champion scope kinds are named after the columns the aggregate
  tier actually groups by (`value_class`, `product_group`), not after a
  taxonomy that exists only in prose. The Syntetos-Boylan demand segment is
  deliberately absent: it classifies an individual series' sparsity, and an
  aggregate of many series does not have one.
- **D-044** — comparability is assessed *within* an evaluation mode. A
  `holdout_fast` model's 6 test points are judged against other fast-holdout
  rows, so `lstm` is ranked rather than excluded, and the mixed-mode note
  appears on the response (extends D-037).

### Issues found and fixed during the phase

1. **Segment champions were silently skipped.** The first implementation
   filtered segment scopes with a demand-segment name check, but the real scope
   keys are `value_class=A` and `product_group=AIS GLASS`. Nine scopes matched
   nothing and were dropped without a reason — the exact failure mode this
   project is built to avoid. Fixed by matching the key's own prefix; the count
   went from 57 to 66 selections on the aggregate tier.

2. **`wape_pct` double-scaled the metric.** `metrics.evaluate` already scales
   WAPE by 100 at source, so multiplying again would have rendered a 4.58%
   national error as **458%** on the comparison chart. Caught while reconciling
   `mae=7558` against `wape=4.578` — those two are only consistent if WAPE is
   already a percentage. A test now pins it.

3. **`_horizon_performance` returned WAPE as a fraction** while the row above it
   carried a percentage, putting 4.58 and 0.0458 in one payload under one name.
   Scaled to match.

### Blockers

**None.**

---

## Phase 9 — completed 2026-09-09

### Verified against real client data

Forecast generation from origin **2026-07** for 2026-08 … 2027-01:

| Measure | Value |
|---|---|
| Scopes forecast | 166 of 169 (3 unavailable, each with a reason) |
| Rows written | 996 across 5 levels (600 series-level) |
| Rows with a reason and no number | 18 |
| Reconciliation | `mint_variance` |
| Coherent | **true**, max incoherence **0.0** |
| Negatives clipped | 0 |
| Quantile crossings corrected | 0 |
| Wall clock | 170 s |

Level totals for 2026-08 agree exactly:

```
branch    n=50  total = 187,503
region    n= 6  total = 187,503
national  n= 1  total = 187,503
```

National forecast, after the interval fix below:

```
2026-08 h1 point=187,503  q80=196,467  q90=198,942  q95=201,968   (empirical / scope_all_horizons)
2026-09 h2 point=183,372  q80=190,129  q90=192,605  q95=195,631
2026-10 h3 point=179,890  q80=183,945  q90=186,421  q95=189,447
2026-11 h4 point=177,965  q80=182,064  q90=184,540  q95=187,565
2026-12 h5 point=179,156  q80=186,277  q90=188,753  q95=191,779
2027-01 h6 point=172,190  q80=174,515  q90=176,991  q95=180,016
```

### Files created

- `backend/app/ml/reconciliation/mint.py` — MinT variance and shrinkage, with
  bottom-up and proportional as documented fallbacks
- `backend/app/services/forecast_service.py`
- `backend/app/models/forecasts.py`, `backend/app/schemas/forecasts.py`
- `backend/app/api/routes/forecasts.py`
- `backend/alembic/versions/533752466943_forecast_runs_and_rows.py`
- `backend/tests/test_reconciliation.py`, `backend/tests/test_forecast_api.py`

### Test results (actual output)

```
tests/test_reconciliation.py .................................  33 passed
tests/test_forecast_api.py ............................         28 passed
```

### Decisions recorded

- **D-045** — a scope is calibrated from **its own** out-of-sample residuals,
  with the run's pooled cells as the fallback. See the defect below for the
  measurement that forced this.
- **D-046** — quantiles are not projected independently through the
  reconciliation. Two separate projections of q80 and q90 can cross, and a
  crossed interval is worse than a slightly sub-optimal one, so each level's
  spread is carried across and the ordering re-checked.

### Issues found and fixed during the phase

1. **The quantile bands were far too narrow, and the cause was a real
   methodological error.** The training run pools residuals by (model, horizon,
   segment) across *every scope it evaluated* (D-010), and the offsets are
   absolute quantities. At the aggregate tier those scopes differ in magnitude
   by more than fifty times — a small product-group segment against the
   national total — so an absolute offset from the mixed pool is meaningless at
   either end.

   Measured: the national q95 came out **3.2%** above the point forecast while
   that same model's national WAPE was **4.58%** — an interval narrower than
   the model's own average error. After calibrating from the scope's own
   residuals: **7.7%**, which is consistent with the model's measured error.
   The method is labelled `empirical / scope_all_horizons` on every row,
   because 12 residuals is below the 19 a conformal q95 order statistic needs.

2. **Series champions were selected but never forecast.** The forecast job built
   only the aggregate plan, so 100 selected series champions produced nothing
   and the inventory endpoint had no branch × SKU rows to work with. Fixed by
   building series scopes from the active champion selections.

3. **`series_key` versus `series_id`.** The panel's column is `series_id`; the
   reconciliation parent map and the history query both used `series_key`. The
   run failed with `KeyError` and — correctly — recorded its own failure reason
   rather than dying silently.

4. **The series view 500ed on an unreadable panel artifact.** History is
   supplementary to the forecast rows, which live in the database, so an
   unreadable artifact now degrades that one section with a stated reason.

### Blockers

**None.**

---

## Phase 10 — completed 2026-09-09

### Verified against real client data

100 real recommendations at q95 for 2026-08, sorted by order quantity:

```
BENGALURU|FG.BA5.LFH.GCG2120000    order=1105  oul=1105  stock=0    lead=4d  protection=34d  cover=0
SECUNDRABAD|FG.BA5.LFH.GCG2120000  order=1081  oul=1081  stock=0    lead=5d  protection=35d  cover=0
COCHIN|FG.PG1.LFH.GCG2120000       order= 849  oul= 849  stock=0    lead=5d  protection=35d  cover=0
VIJAYAWADA|FG.BA5.LFH.GCG2120000   order= 656  oul= 656  stock=0    lead=4d  protection=34d  cover=0
LUDHIANA|FG.MP8.LFH.GCG2120000     order= 639  oul= 677  stock=38   lead=4d  protection=34d  cover=3
```

The top rows are zero-stock-against-live-demand positions, which is what a
planner needs to see first. Service levels are ordered as required:

```
q80 order=1091   q90 order=1098   q95 order=1105
```

Placement measures from the 2026-08-01 snapshot:

| Measure | Value |
|---|---|
| Positions with stock | 49,199 of 70,724 |
| Dead or slow positions | 23,788 · 409,031 units · ₹88,689,982 |
| Zero stock against live demand | 21,549 · 377,501 units of recent demand |
| Negative stock rows | 2, surfaced as data-quality exceptions |

The domain document's independently derived figure for zero-stock-against-live-
demand is 21,576 against this run's 21,549. The difference is the window
definition — this measure uses the last six periods of the order fact — and
both numbers are reported rather than one being quietly adopted.

### Files created

- `backend/app/domain/ais/inventory.py` — the policy arithmetic, database-free
- `backend/app/services/inventory_service.py`
- `backend/app/schemas/inventory.py`, `backend/app/api/routes/inventory.py`
- `backend/tests/test_inventory.py`

### Test results (actual output)

```
tests/test_inventory.py ...............................  31 passed
```

### Notes carried forward

- **The q80→q95 spread is narrow at series level** (1,091 → 1,105, about 1.3%).
  Same cause as the aggregate-level issue in Phase 9 and same honest label:
  12 residuals per series, empirical interpolation rather than a measured tail.
  More origins would widen it; the label says which it is.
- `confirmed_stock_on_order` and `backorders` are **zero by absence**, not by
  measurement — the source set has no open-order snapshot. Every row says so.

### Blockers

**None.**

---

## Phase 11 — completed 2026-09-09

### What changed

All ten navigation destinations now consume real API data. The `PhaseNotice`
component — the honest placeholder used through Phases 1-10 — is **deleted**,
because nothing renders one any more, and a guard test asserts no file
reintroduces it.

| Page | Source |
|---|---|
| Executive Command Center | health, models, training, leaderboard, forecasts, inventory |
| Data Studio | datasets, profile, validation, mapping |
| Mapping & Validation | mappings, rules, preprocessing, panel |
| Training Center | training estimate / submit / detail / cancel |
| Model Leaderboard | leaderboard, comparison, scopes, diagnostics, champions |
| Forecast Explorer | forecast runs, series, scopes |
| Supply Intelligence | recommendations, overview, transferable |
| Scenario Planner | scenarios |
| Data & Model Monitoring | monitoring |
| Connections & Settings | settings, exports |

### Test results (actual output)

```
Test Files  15 passed (15)
     Tests  152 passed (152)
```

`tsc -b --noEmit` clean.

### Files created

- `frontend/src/api/{training,leaderboard,forecasts,inventory,operations}.ts`
- `frontend/src/types/{phase7,operations}.ts`
- `frontend/src/features/leaderboard/components/{WapeChart,ChampionPanel,DiagnosticsPanel}.tsx`
- `frontend/src/test/phase7Fixtures.ts`
- Six new page test files

### Files changed

- All five previously-placeholder pages, plus the Command Center
- `frontend/src/components/ui/ui.css` — form, metric and chart styles
- `frontend/src/test/setup.ts` — ECharts stub, see below

### Files deleted

- `frontend/src/components/ui/PhaseNotice.tsx`

### Issues found and fixed during the phase

1. **A flaky test suite, caused by the environment rather than the assertions.**
   ECharts renders onto a canvas and jsdom has none, so its deferred render
   threw `clearRect of null` — and whichever test happened to be running when
   it fired was the one that failed. The same suite failed on different tests
   between runs, which reads as a problem with the tests rather than with the
   environment. Fixed by stubbing the chart component in `setup.ts` with a
   marker element carrying its series names, so a test can still assert *what
   the page asked the chart to draw* — which is the part that matters here,
   since a chart must show a gap for a model that did not run.

2. **The WAPE chart draws a labelled gap, not a missing bar.** A model with no
   defined WAPE stays on the x-axis with its reason in the tooltip and a note
   under the chart. Silently fewer bars would let a reader conclude the model
   was never in the comparison.

### Blockers

**None.**

---

## Phase 12 — completed 2026-09-09

### What this phase added

Three endpoint areas the contract had listed but not built, plus the
documentation pass.

- **`GET /api/monitoring`** — freshness, drift, champion age, error
  deterioration. Each measure carries its own availability flag and reason.
- **`POST /api/scenarios`** — what-if over a read-only baseline forecast.
- **`GET /api/exports/{kind}`** — CSV of exactly what a page displays,
  including the rows that carry a reason instead of a number.
- **`GET /api/settings`** — the effective runtime configuration, read-only.

### Verified against real client data

```
freshness:     demand history ends 2026-07 (2 mo old) | stock 2026-08-01 (1 mo old)
drift:         national +22.99% recent vs earlier
               target source changed: [order, sales_proxy] -> [order]
               top branch shifts: HYDERABAD +83.3%, HUBLI +57.5%, DELHI-2 +55.9%
champions:     166 active | 0 from older runs | 47 beaten by a baseline
deterioration: NOT COMPUTABLE - none of the 6 forecast periods has been observed yet
```

**The drift measure catches its own confound.** The +23% national shift spans a
boundary where the target source changed from a mixed order/sales-proxy window
to order-only, so part of the shift is a change of *measurement*, not of
demand. The response says so, because a drift number that hid that would be
worse than no drift number.

**Error deterioration is honestly not computable.** The forecast origin is the
last month the panel holds, so no forecast period has an actual yet. Returning
`computable: false` with that reason is the only truthful answer; a zero would
claim a check that never happened.

Scenario, on real rows (demand ×1.2, q95, lead time 3 d → 10 d):

```
baseline demand 299,643 -> scenario 359,571  (+20.0%)
baseline order  379,135 -> scenario 551,470  (+45.5%)
```

Demand moved 20% while the order position moved 45.5%, because the lead-time
lever lengthened the protection period as well. The two are reported separately
so the compounding is visible.

All four exports produce provenance-headed CSVs:

```
# AIS leaderboard export | training_run=892e7ee2... | scope=national/NATIONAL
#   | generated=20260909T102720Z | ranked=7 unranked=10
#   | an empty metric cell means undefined, not zero
```

### End-to-end verification over real HTTP

The app was started on a real port and every area exercised through the network
rather than through TestClient. 15 endpoint checks plus a CSV download, **all
200**, against the live database:

```
/health                         ok
/models                         13 models, 4 baselines
/settings                       13 models, dialect sqlite
/training/current               completed · 2873 model runs
/models/leaderboard             champion var_exog wape 4.578 · 17 rows · missing []
/models/leaderboard/comparison  17 bars, 6 labelled gaps
/models/champions               166 active champions
/models/var_exog/diagnostics    available=True folds=2 points=12
/forecasts/runs/current         origin 2026-07 · mint_variance · coherent True · 996 rows
/forecasts/series               24 history + 6 horizons
/forecasts/hierarchy            4 levels, gaps coherent where expected
/inventory/recommendations      100 rows, top order 1105
/inventory/overview             dead 23788 · zero-stock 21549
/monitoring                     drift True · deterioration computable False
/exports                        4 export kinds
/exports/leaderboard            17 rows + provenance header + content-disposition
```

This is what found the reconciliation defect below. It is worth keeping.

### Documentation

`docs/API_CONTRACT.md` rewritten from section 4 onward. **Cross-checked
programmatically against the running app: 57 live routes, 57 documented, no
drift in either direction.** The check is worth keeping — it is the kind of
thing that rots silently.

### Test results (actual output)

```
backend:  731 passed
frontend: 152 passed (15 files)
```

Per-file backend counts:

```
test_api_contract 12    test_backtest 37       test_champion_selection 27
test_cleaning_rules 69  test_controls 21       test_dataset_api 20
test_forecast_api 32    test_inventory 31      test_leaderboard_api 39
test_leakage 42         test_mapping_api 28    test_metrics 77
test_migrations 10      test_ml_adapters 91    test_model_registry 16
test_operations_api 29  test_panel_api 18      test_pii_exclusion 12
test_preprocessing 6    test_reconciliation 33 test_roles 47
test_training_api 34
```

### Files created

- `backend/app/services/{monitoring_service,scenario_service,export_service}.py`
- `backend/app/api/routes/operations.py`, `backend/app/schemas/operations.py`
- `backend/tests/test_operations_api.py`
- `frontend/src/api/operations.ts`, `frontend/src/types/operations.ts`
- Three page test files

### Issues found and fixed during the phase

1. **Reconciliation was projecting a partial hierarchy and reporting it as
   coherent.** Found by the end-to-end HTTP check, not by any unit test — which
   is the argument for running that check.

   `LEVEL_ORDER` picked the finest level *present* as the reconciliation base,
   so the presence of any series row made `series` the base. The local tier
   forecasts the top-N series by value, so the projection reconciled a
   100-series hierarchy — whose branch, region and national nodes are sums of
   only those 100 series — and wrote the results over the full-network
   aggregate rows.

   **Measured: branch and region totals disagreed by 37,794 units for 2026-08
   while the run reported `coherent: true` and `max_incoherence: 0.0`.** Both
   flags were accurate about the subset the projection was handed; neither was
   true of what got persisted. This is the exact failure mode this project is
   built to prevent, and it survived to the last phase.

   Fixed by choosing the finest **complete** level as the base, measured against
   the panel's own series count (D-050). Levels below it are left unreconciled
   with a stated reason, and the hierarchy response now carries two flags per
   gap — `coherent` and `expected_coherent` — because a non-matching pair can
   mean either "a subset, as designed" or "a defect". Four regression tests,
   including one that perturbs a stored national row to confirm a genuine
   disagreement is still called a defect.

   After the fix, on real data: `base_level: branch`,
   `partial_levels: [series]`, and branch = region = national = **188,103**
   exactly.

2. **Monitoring 500ed on a moved artifact.** Three parquet reads in
   `monitoring_service` were unguarded, so one relocated file failed the whole
   snapshot — including the three measures that do not depend on it. Each read
   now degrades its own measure with a stated reason.

3. **`D-042` was cited in code but never written.** `scope_builder.py` and
   `training_service.py` both referenced it for the aggregate-tier VAR pair
   choice. Found by scanning every `D-nnn` in the source against the decision
   log; written up, and the scan is now part of the delivery checklist in
   `CLAUDE.md`.

### Notes carried forward

- **`ruff` is configured but still not installed**, so no lint has ever run on
  this codebase. Unchanged from Phase 6; a first lint of ~14k lines is its own
  change.
- **Error deterioration becomes measurable when a month of actuals arrives
  after 2026-07.** Nothing needs to change for that — the endpoint computes it
  as soon as an overlap exists.
- **The pooled tier has never been run end to end.** `pooled.py` exists and the
  cost model estimates it, but every measurement in this document comes from
  the aggregate and local tiers. Full-network series-level scoring is the one
  operational claim not yet demonstrated.
- Nothing committed or pushed. No reference-project file modified. The five AIS
  source files retain their 2026-09-08 timestamps.

---

## Verification pass — 2026-09-09

A full re-verification of the completed build against every claim in
`CLAUDE.md`. Two real defects were found and fixed; everything else held.

### What was checked, and what it measured

| Claim | Result |
|---|---|
| Backend suite green | **739 passed in 52.76s** |
| Frontend suite green | **157 passed, 15 files**; `tsc -b` clean |
| Documented test counts | **Wrong** - see below |
| 57 endpoints, no drift | **57 = 57**, path-parameter names included |
| Exactly 13 models, in order | 13 canonical, 13 bound, order verified |
| Baselines never among the 13 | id sets disjoint |
| Every `D-nnn` cited in code exists | 23 cited, 51 written, **0 missing** |
| Reference projects untouched | `find -newermt` over all three roots: **0 files** |
| AIS source files unmodified | all five retain 2026-09-08 timestamps |
| Pooled tier never run | **confirmed** - 0 rows with `tier='pooled'` |
| Deterioration not computable | **confirmed** - `computable: false` with the reason |
| `ruff` not installed | confirmed - still true |

Endpoint drift needs one clarification: the app exposes **60** `/api` routes,
of which three (`/api/docs`, `/api/redoc`, `/api/openapi.json`) are FastAPI's
own documentation routes rather than application endpoints. The 57 application
endpoints match `docs/API_CONTRACT.md` exactly.

### Defect V1 — a run orphaned by a restart said `running` forever

The live database held a training run (`992947a1`) with `status='running'`,
`started_at` at 11:08, no `finished_at`, and zero `model_run` rows. The process
that owned it was long gone.

The job runner is in-process (D-007), so **every** restart - deploy, crash,
Ctrl-C - orphans whatever was in flight. A run's row is only ever written by
the worker that owned it, and nothing reconciled the row afterwards, so the
status stayed `running` indefinitely. `GET /api/training` duly reported it as
running, which means the UI would show a spinner for a run that can never
finish.

That is a false status, and status is load-bearing in this project. A visible
failure is strictly better than a permanent spinner, because the failure tells
the reader to resubmit.

**Fixed** by `reconcile_orphaned_runs()`, called from the application lifespan
before the app serves traffic. Any run still in `queued`, `running` or
`cancelling` is marked `failed` with a reason naming what happened and how many
`model_run` rows it had already written. Those rows are **kept** - the same
reasoning as cancellation: partial evidence is evidence, and deleting it
destroys the only record of what did complete.

Run against the real database: 1 run reconciled, now reporting `failed` /
`Interrupted`. Four new tests cover it, including one parametrised over all
three live statuses and one asserting the partial rows survive.

### Defect V2 — the estimate-versus-actual audit recorded 0.0 every time

`cost_model.py` exists so nobody starts a three-hour run by accident, and its
docstring promises the estimate is "stored beside the actual duration so it can
be audited against reality instead of being quietly forgotten".

It was being forgotten. `_run_training_job` built its summary from
`config.get("estimated", 0.0)` - a key nothing ever wrote - so every completed
run recorded:

```
ae0fa1c4 {"estimated_seconds": 0.0, "actual_seconds": 275.8}
98ae5329 {"estimated_seconds": 0.0, "actual_seconds": 279.4}
892e7ee2 {"estimated_seconds": 0.0, "actual_seconds": 511.8}
```

The correct value was in the `training_run.estimated_seconds` column the whole
time (424 s for the aggregate runs), so the comparison looked implemented while
being worthless. This is the failure mode worth naming: not a crash, but a
field that reads plausibly and means nothing.

**Fixed** by carrying `run.estimated_seconds` into the job config and reading it
there. Two tests cover it, one of which asserts the dead key cannot come back.

Worth noting now that the numbers are real: the aggregate-tier estimate of
424 s against an actual 275.8 s is **54% high**. The estimate is conservative,
which is the right direction for a pre-flight cost warning, but the measured
per-model fit times in `cost_model.MEASURED_FIT_SECONDS` are drawn from a
28-month series and aggregate series fit faster. Worth re-deriving from
`model_run.fit_seconds` now that three runs' worth of real timings exist.

### Documented test counts were stale

`CLAUDE.md` and the `docs/STATUS.md` summary both said "883 tests: 731 backend,
152 frontend". The frontend had been 157 since Phase 11 - recorded correctly in
this file's own Phase 11 verification note - and the summary was never updated.
With the 8 tests added above the true figure is **896: 739 backend, 157
frontend**. Corrected in both files.

The per-phase "Test results (actual output)" blocks were deliberately **not**
touched. Those record what was measured when each phase closed; editing them to
match a later total would turn a measurement into a fiction.

### Not fixed, and why

- **`ruff` is still not installed**, so still no lint has ever run. Unchanged
  from the standing gap - a first lint of this codebase is its own change.
- **The pooled tier still has not been run end to end.** Confirmed rather than
  fixed: the code path exists and 0 rows have ever come out of it, so every
  accuracy figure in these docs remains an aggregate- and local-tier figure.
- **The cost estimate is 54% high** on the one tier with real timings. Recorded
  above rather than tuned, because re-deriving the table is a change that
  should be measured across more than three runs.

---

## Reference-led UI parity pass — 2026-09-09

A reference-led implementation against the read-only Sodexo frontend at
`D:\Labour_AI forecastrontend_sodexo`, inventoried in
`docs/UI_VISUAL_PARITY.md`. The reference was **read, never run** — installing
or executing it would mean writing to a read-only project — so parity is
structural and behavioural against its source, not a pixel diff.

### Delivered

| Area | What |
|---|---|
| Shared primitives | `components/ui/Dashboard.tsx` — `StatTile` (with sparkline), `Panel`, `ClearChip`, `MiniTable`, `Card`, `Badge`, the tint/series palettes. Ported structure, AIS palette, `money()` → `inr()` in lakh/crore. |
| **Demand Analytics** (`/demand-analytics`) | The reference's densest page, all 20 panels: 4 KPI tiles, clickable doughnut, value-labelled bars, stacked cross-tab, area/line trends, a 100% reference line, a multi-line per-branch trend whose legend filters, two MiniTables, and the branch scorecard with target-marked bars. Cross-filtering with dimming throughout. |
| **Operational Exceptions** (`/exceptions`) | 7 panels: KPI strip, severity doughnut, exception-type bar, ranked branch × SKU bar, branch bar, definitions panel, drill-down table. |
| **AI Assistant** (`/assistant`) | React → AIS FastAPI → OpenAI. 7 bounded read-only tools, function-calling with zero-argument schemas, allowlisted chart specs built in the backend, deterministic fallback, and a labelled `answered_by`. |
| Backend | `app/domain/ais/analytics.py` (aggregations), `app/api/routes/analytics.py` (5 endpoints), `app/services/assistant/` (tools, llm, agent, service), `app/api/routes/assistant.py` (2 endpoints). |
| Config | `OPENAI_API_KEY`, `OPENAI_MODEL`, `AI_ASSISTANT_ENABLED`, `AI_MAX_OUTPUT_TOKENS`, `AI_REQUEST_TIMEOUT_SECONDS`, accepted both unprefixed and with the project's `AIS_` prefix. |

### Measured on real client data

| Figure | Value |
|---|---|
| Ordered demand value | ₹1,346.02 Cr over 28 months |
| Ordered units | 4,165,509 (matches the panel total exactly) |
| Fill rate | 82.0%, with 1,140,448 proxy rows excluded from the ratio |
| Ordered-demand share | 66.1% |
| Exception lines | 66,007 across 5 conditions; 21,549 zero-stock-live-demand (matches Supply Intelligence) |
| Summary endpoint | 5.3 s cold, instant cached |
| Exceptions endpoint | **1.9 s**, down from 24.9 s after vectorising |

### Issues found and fixed during the pass

1. **A panel disagreed with its own title.** The stacked cross-tab was titled
   "by Value Class" and split by `product_group`, so the legend read
   "AIS GLASS / HIGH END". Split by `value_class` now, and the mapping is
   documented: `product_group` has three levels with one holding 99.7% of
   demand, so it makes a one-bar chart.
2. **The exceptions endpoint took 24.9 s.** A per-series Python loop over
   ~68,000 series. Vectorised to group-bys and one concat: 1.9 s, identical
   output (66,007 lines, same per-type counts).
3. **The empty payload changed shape.** With nothing to report, the exceptions
   response omitted `rows`/`by_type` entirely, so a caller reading them
   crashed. It now always carries the collection keys.
4. **A real crash on the empty selection.** `summary?.branch_over_time.data`
   guarded one level too shallow. Found by the test that renders the empty
   state.
5. **A console error I introduced** — a fragment in a `.map()` without a key.
   Fixed; a fresh tab now logs nothing.
6. **A pre-existing flaky test** (`test_it_defaults_to_the_newest_panel_build`,
   passing about two runs in three). Two panel builds created in the same
   millisecond tie on `created_at`, making "newest" genuinely ambiguous. Fixed
   in the fixture by giving them distinct timestamps. My first attempt added
   `id.desc()` as a tiebreak, which was wrong — `id` is a random uuid4, so it
   would still have failed half of the ties — and was reverted.
7. **A test that passed for the wrong reason.** `findByText(/No API key
   configured/i)` matched the page *footer*, which renders before the status
   query resolves, so the assertion passed while the setup card was absent. Now
   waits on an element that only exists once status has loaded.

### Verification

```
backend:  784 passed in 52.73s
frontend: 181 passed (16 files)
tsc -b:   clean
build:    ✓ built in 10.02s
```

64 API endpoints, all documented in `docs/API_CONTRACT.md` §9 and cross-checked
against the running app. 13 models still bound in order. No key material in
`frontend/dist`. Reference projects: 0 files modified across all three. The
five AIS source files retain their 2026-09-08 timestamps.

Browser-verified against the running application at 1440 px, 768 px and 375 px
with no horizontal overflow and no console errors.

### Outstanding

Five inventory entries are **not built**, listed with their exact remaining
work in `docs/UI_VISUAL_PARITY.md` §8: three Supply Intelligence breakdown
charts (4.2–4.4), the drift chart (5.8), and the cover-vs-requirement
ComposedChart (5.9). None needs a new endpoint — every figure is already in a
payload the page fetches; what is missing is the chart component.

---

## Scoped training, ineligible models, and Forecast Explorer filters

Three things, from one request: training was too slow to iterate on, six models
reported `Ineligible` on every row, and the Forecast Explorer had no way to
find a series.

### 1. A training run can be scoped (D-044)

`POST /api/training` now accepts `branches` and `max_skus`. `restrict_panel()`
cuts the panel before origins, plans and cost are computed, so every count
downstream describes the slice actually trained. SKUs are ranked *inside* the
branch restriction.

Measured, BENGALURU + AHMEDABAD × top-20 SKUs by value:

```
panel cut     1,503,753 rows -> 1,120   (40 of 68,675 series)
duration      443.1 s  (7m 23s), aggregate + local
model runs    799 written · 597 completed · 14 ineligible · 0 failed
```

A restricted run carries `restriction_json` and a warning naming exactly what
it covered, so its leaderboard can never be read as a network result.

### 2. The six ineligible models are eligible (D-045)

Not a defect. Auto ARIMA, Auto ARIMA exog and the four Exponential Smoothing
variants each require 24 training observations; a 28-month panel leaves 18–22
at the rolling origin. `min_history_profile=monthly_relaxed` lowers all six to
18. Under it, **all 13 models ran on all 47 scopes with zero failures**.

What is still ineligible is a real data fact: VAR and VAR-exog on 7 of 47
scopes, because a single-cell series has no second non-constant endogenous
series. That was not relaxed.

Champion accuracy on this slice (`100 - MAPE`, MAPE defined for 785 of 785
completed rows): 94.0% national, 94.0% segment, 88.6% region, 88.6% branch,
80.1% median at series level. A non-registry baseline still beats the champion
on 10 of 47 scopes.

**These figures describe two branches and twenty SKUs, not the network.**

### 3. Forecast Explorer filters by location and SKU (D-046)

Location and SKU dropdowns at series level, derived from the trained scope keys
so they cannot offer an untrained combination. The SKU list narrows to the
chosen location; changing location clears a SKU that location does not stock.
The count line says how many trained series matched and that untrained ones are
absent. No new endpoint.

### Verification

```
backend:  809 passed in 49.38s
frontend: 187 passed (16 files)
tsc --noEmit: clean
alembic upgrade head: 533752466943 -> a41c9b7f2d10
```

Nine new backend tests (`tests/test_scope_restriction.py`) and six new frontend
tests. Reference projects and the five AIS source files untouched.

---

## The silent startup exit is fixed (D-047)

Starting the backend on a busy port exited with no message at all. The cause
was **not** `configure_logging()`, which is what I said earlier and had wrong.

`alembic/env.py` called `fileConfig(...)`, whose default
`disable_existing_loggers=True` disables every logger not named in
`alembic.ini` and drops root to WARNING. The app runs Alembic in-process from
its lifespan, so `uvicorn`, `uvicorn.error` and every `app.*` logger were dead
from that point on. Uvicorn binds *after* the lifespan, so its
`[Errno 10048]` went to a disabled logger — along with `Application startup
complete.`, `Uvicorn running on …`, `startup_complete` and `schema_ready`.

`env.py` now skips `fileConfig` when the app already owns logging, and passes
`disable_existing_loggers=False` when it does not.

Verified with port 8000 held by another process:

```
INFO:     Application startup complete.
ERROR:    [Errno 10048] error while attempting to bind on address
          ('127.0.0.1', 8000): [winerror 10048] only one usage of each socket
          address (protocol/network address/port) is normally permitted
```

And on a free port the app starts and serves: `GET /api/health -> 200`, with
`Uvicorn running on http://127.0.0.1:8127` printed. `alembic current` from the
CLI still works and still prints its own lines.

Alembic's migration output now goes through the JSON formatter with everything
else, instead of a second plain-text format on a second stream.

### Verification

```
backend:  814 passed in 53.62s
alembic current (CLI): a41c9b7f2d10 (head)
```

Changed: `backend/app/core/logging.py`, `backend/alembic/env.py`.
New: `backend/tests/test_logging_config.py` (5 tests) — one of which asserts
the hazard is real, so the guard cannot be removed later as redundant.

---

## One location scope across every page, and two slicers on Forecast Explorer

### Forecast Explorer (D-050)

Lands on **series** level. Two dropdowns only — **Location** and **SKU** — and
`Branch × SKU` is gone: a location plus a SKU *is* the series, so the pair
resolves the scope with no third click. They cross-filter both ways, so neither
list can offer a value that yields nothing. The "Switch to series level" hint
is removed.

### One workspace location scope (D-049)

`app/domain/ais/workspace.py` resolves the question once — from
`AIS_WORKSPACE_BRANCHES` if set, else the active training run's restriction,
else unrestricted — and it is applied at four shared seams rather than in each
endpoint. Verified live, every page's endpoint returns the same two locations:

```
analytics/filters        ['AHMEDABAD', 'BENGALURU']
analytics/summary        ['AHMEDABAD', 'BENGALURU']
analytics/exceptions     ['AHMEDABAD', 'BENGALURU']
analytics/scorecard      ['AHMEDABAD', 'BENGALURU']
analytics/series         ['AHMEDABAD', 'BENGALURU']
analytics/lead-time      ['AHMEDABAD', 'BENGALURU']
inventory/recommend      ['AHMEDABAD', 'BENGALURU']
leaderboard/scopes       ['AHMEDABAD', 'BENGALURU']   (40 series, was 100/30 branches)
monitoring drift         ['AHMEDABAD', 'BENGALURU']
```

Every restricted payload carries `workspace_scope`, and its sentence is
prepended to the page's notes. Confirmed rendering in the browser on Demand
Analytics:

> This workspace covers 2 of 53 branches (AHMEDABAD, BENGALURU). Every figure
> on this page describes those branches only, not the national network.

**This hides 51 branches of real data on the analytics pages.** That was asked
for explicitly and is why the note is mandatory. Clearing the setting and
running an unrestricted training run restores all 53 with no code change.

### A cancelled run no longer outranks a completed one (D-048)

A full 53-branch run was cancelled at 88%. Its rows are kept, per contract —
but `resolve_run` picked the newest run *with rows*, so the partial sweep
became the authority for the whole application and the cancellation appeared to
do nothing. It now prefers a finished run, falling back only when nothing has
finished. A cancelled run is still reachable by id.

### Verification

```
backend:  829 passed in 43.99s   (was 814)
frontend: 190 passed (16 files)
tsc --noEmit: clean
```

New: `backend/app/domain/ais/workspace.py`,
`backend/tests/test_workspace_scope.py` (15 tests).
Changed: `champion_service.py`, `api/routes/analytics.py`,
`services/assistant/tools.py`, `inventory_service.py`, `monitoring_service.py`,
`core/config.py`, `ForecastExplorerPage.tsx` and its tests.

Known: `_panel()` now returns a 4-tuple `(frame, build, path, scope)`. Every
caller was updated; the assistant shares the same seam by design.

---

## Lead time was built but unreachable, and one page leaked branches

### Lead time is now near the top of Supply Intelligence

`LeadTimePanels` was mounted, but as the **last** element of a page 21,758 px
tall — reachable only after scrolling past four long tables. Built, rendering,
and effectively invisible.

Two changes:

- **A sticky section nav** on Supply Intelligence: Lead time · Inventory
  exposure · Replenishment · Zero stock vs demand · Dead / slow stock. The page
  is long enough that anchors are not a nicety.
- **Lead time moved above the recommendation tables**, where it belongs
  anyway: the protection period every recommendation below uses is built from
  it.

Measured after the move: the lead-time section starts at **1,504 px** instead
of roughly 20,000.

Also fixed a copy bug the two-branch workspace exposed: the "Branches measured"
tile read *"2 of 2 · the rest report a zero-day lead time"* when there is no
rest. It now names the count only when some are actually missing.

### A workspace leak on Supply Intelligence (D-049)

`zero_stock_live_demand` listed LUDHIANA, SECUNDRABAD, JAIPUR, HYDERABAD and
others while every other panel on the page showed two branches. Cause: it is
built by an **outer** merge of the stock frame with the order fact, and only
the stock frame had been restricted — so a branch present in orders alone
survived. The order fact is now restricted too.

```
before  zero_stock_live_demand: 15 branches · totals.positions 146,364
after   zero_stock_live_demand: ['AHMEDABAD', 'BENGALURU'] · totals.positions 7,830
```

This is a defect in the D-049 work reported as complete in the previous entry.
The sweep that verified it probed `inventory/recommendations`, not the lists
nested inside `inventory/overview`.

### Verification

```
backend:  829 passed in 49.66s
frontend: 190 passed (16 files)
tsc --noEmit: clean
```

Changed: `inventory_service.py`, `SupplyIntelligencePage.tsx`,
`LeadTimePanels.tsx`, `components/ui/Card.tsx` (accepts an `id` for anchors),
`styles/ais.css`.

---

## Calendar pickers for the history window (D-051)

The two 28-entry month dropdowns on Demand Analytics are now **From** / **To**
calendar pickers (`<input type="month">`), bounded by the panel's real range.

```
From/To   type=month  min=2024-04  max=2026-07
beside    "Data available Apr 2024 – Jul 2026 · 28 months"
```

Month grain, not day: the panel has no day-level values, and a date picker
would invite a question the data cannot answer. Out-of-range typed input is
clamped, the two ends cannot cross, and a **Full history** reset appears once a
window is set.

Verified live: setting Jan 2025 → Jun 2025 filtered the page to a 6-month
window, `From.max` became `2025-06` and `To.min` became `2025-01`, and the
reset restored the full 28 months.

### Verification

```
frontend: 201 passed (17 files)   (was 190)
tsc --noEmit: clean
```

New: `frontend/src/components/ui/MonthRange.tsx` and its 11 tests.
Changed: `DemandAnalyticsPage.tsx`.

---

## Three destinations removed from the UI (D-052)

Executive Command Center (`/`), Data & Model Monitoring (`/monitoring`) and
Connections & Settings (`/settings`) are gone from the navigation and the
router. The nav is now ten items:

```
DATA        Data Studio · Mapping & Validation
ANALYTICS   Demand Analytics · Operational Exceptions
MODELLING   Training Center · Model Leaderboard · Forecast Explorer
OPERATIONS  Supply Intelligence · Scenario Planner
ASSISTANT   AI Assistant
```

`/` now redirects to Demand Analytics (`LANDING_PATH`), so an existing bookmark
still lands somewhere real. Verified in the running app: `/`, `/monitoring` and
`/settings` all resolve to `/demand-analytics`.

**Two silent breakages caught and fixed.** `AppShell` built its workflow strip
from `NAV_ITEMS.slice(1, 6)` — positional, and correct only while the command
centre occupied position 0; it now selects by nav index, verified as
`01 Data Studio · 02 Mapping & Validation · 03 Training Center · 04 Model
Leaderboard · 05 Forecast Explorer`. And the assistant's `data_quality` tool
link pointed at `/monitoring`; that entry is removed rather than repointed.

**The page components are still on disk**, unrouted and unlinked — this project
has no git history, so unrouting is the reversible form of removal. Their unit
tests still run and now cover unreachable pages. Deleting
`src/features/{command-center,monitoring,settings}/` and their tests is a
one-word go-ahead.

The backend is untouched: `GET /api/monitoring` and `GET /api/settings` still
exist and stay in `docs/API_CONTRACT.md`.

### Verification

```
frontend: 203 passed (17 files)   (was 201)
tsc --noEmit: clean
```

Changed: `app/navigation.ts`, `app/routes.tsx`, `components/layout/AppShell.tsx`,
`features/assistant/pages/AssistantPage.tsx`, `test/accessibility.test.tsx`.

---

## Reconciliation counters, and AI recommendations

### Orphaned runs no longer contradict themselves (D-053)

`reconcile_orphaned_runs()` set the status and the reason but not the counters,
so a run reported `model_runs_total = 0` beside a `failure_reason` on the same
record saying it had written 2,227. Fixed: one grouped read rebuilds every
counter, distinct `(scope_level, scope_key)` gives `series_evaluated`, and
`duration_seconds` is the subtraction of two timestamps already on the row.

Backfilled on the live record (`3c87a9ec`):

```
before   total=0     completed=0     ineligible=0    series_evaluated=0    duration=None
after    total=2227  completed=1420  ineligible=807  series_evaluated=131  duration=688.27s
```

`series_requested` and `residuals_recorded` came from memory that died with the
process; they stay 0 and a warning on the row says so. The message no longer
says "Resubmit the run to continue" — there is no resume.

### AI recommendations on the Assistant page (D-054)

`GET /api/assistant/recommendations` — a standing pass over five of the
existing bounded tools, returning a ranked list where every item carries its
figures and names the page to check them on. Collapsible panel above the
conversation.

Verified live with no key configured:

```
answered_by deterministic_no_key | temperature 2.0 | items 2
 [critical] Critical supply exceptions are open      -> Operational Exceptions
 [medium]   Recent demand has shifted                -> Demand Analytics
```

**Temperature is 2.0 as requested**, applied to the call that writes prose.
Tool selection is a separate setting held at 0. The trade-off is recorded in
D-054: at 2.0 the same facts give a different list each run and the grounding
rules are followed less consistently — `AI_TEMPERATURE=0.3` reverses it.

**No live OpenAI call has been made.** No key is configured, and every model
path is tested against a stub.

### Verification

```
backend:  853 passed in 48.63s   (was 829)
frontend: 213 passed (18 files)  (was 203)
tsc --noEmit: clean
```

New: `app/services/assistant/recommendations.py`,
`tests/test_assistant_recommendations.py` (19),
`frontend/src/features/assistant/components/Recommendations.tsx` and its 10 tests.
Changed: `core/config.py` (two temperature settings), `assistant/agent.py`,
`api/routes/assistant.py`, `api/analytics.ts`, `AssistantPage.tsx`,
`training_service.py`, `tests/test_training_api.py`, `docs/API_CONTRACT.md`.

---

## AI Recommendations split out from the AI Assistant (D-055)

Two destinations now, both under Assistant in the nav:

```
ASSISTANT   AI Assistant  /assistant       ask a question
            AI Recommendations  /recommendations   the standing list
```

The assistant page no longer carries the panel — verified in the running app:
`/assistant` still has its suggested questions, composer and Ask button, and
no recommendation list; `/recommendations` renders the list plus a "How this
list is built" card.

The collapse control is replaced by **Refresh**. It existed to give the
conversation its height back, which is no longer a problem, and a page that
hides its own only content is a worse control than none. Refresh earns its
place at temperature 2.0, where a re-read genuinely differs.

`Recommendations` moved to
`frontend/src/features/recommendations/components/RecommendationList.tsx`, its
test alongside it, and `RecommendationsPage.tsx` is the new page. Nothing about
the endpoint, grounding or caveats changed.

### Verification

```
frontend: 213 passed (18 files)
tsc --noEmit: clean
```

Nav is 11 items; `REQUIRED_NAV_INDEXES` is untouched (14 is a new index, not
one of the original ten).

---

## The UI is eight tabs, on a 2 × 20 workspace (D-056, D-057)

### Navigation

```
ANALYSIS    Overall Analysis      /overall
            Per Branch & SKU      /series
MODELLING   Training              /training
            Forecasting           /forecasting
OPERATIONS  Supply Intelligence   /supply
            Scenario Planner      /scenarios
ASSISTANT   AI Assistant          /assistant
            AI Recommendations    /recommendations
```

Seven pages unrouted (Data Studio, Mapping & Validation, Demand Analytics,
Operational Exceptions, Training Center, Model Leaderboard, Forecast Explorer)
plus the workflow strip that linked four of them. `/` redirects to Overall
Analysis. Components remain on disk — no git here, so unrouting is the
reversible form of removal.

### Verified in the running app

```
Overall Analysis   6 charts · ₹24.72Cr · 7.2K units short · 85.1% fill · 60.3% order share
Per Branch & SKU   2 locations x 20 SKUs, cross-filtering, "1 of 40 series in scope"
Training           13 models · 2 folds · rolling origin · MAPE primary
Forecasting        BENGALURU|FG.MP8 -> LSTM, 14.40% WAPE, 6/6 horizons, 393 units Aug 26
```

**Independence, demonstrated rather than asserted** — same branch, three SKUs:

| SKU | Champion | Error | Next month |
|---|---|---|---|
| FG.MP8.LFH.GCG2120000 | LSTM | 14.40% WAPE | 393 |
| FG.TK4.LFH.GCG2120000 | SARIMAX with exogenous variables | 14.52% WAPE | 221 |
| FG.MYC.BCK.G00300A000 | VAR with exogenous variables | 44.70% WAPE | 21 |

### Trained and forecast on the new slice

- Training `c6812131`: **472 s**, 884 model runs, 561 completed, 115 ineligible,
  **0 failed**, 40 series.
- Champion selection: 52 scopes, **0 skipped** — including 40 at series level,
  which the default scope-kind list omitted.
- Forecast `73862318`: 312 rows written, 342 unavailable, 63.9 s.

### Four defects found by verifying, not by testing

1. **A silent cache bug.** `_key` listed scope fields by hand, so adding `sku`
   did nothing — one SKU's answer was served for every other. Now derived from
   the dataclass; 5 regression tests, one asserting every field changes the key.
2. **Route ordering.** `/training/{run_id}` shadowed `/training/explain`.
3. **Champion selection skipped series scopes** by default, so the Forecasting
   tab had no data to show. Selected explicitly.
4. **A 34px percentage axis** clipped its numbers to bare `%` signs.

### Verification

```
backend:  858 passed in 39.18s   (was 853)
frontend: 213 passed (18 files)
tsc --noEmit: clean
```

### Known gaps

- **The forecast run is not workspace-scoped.** It wrote 53 branch scopes on a
  2-branch workspace, because forecast generation walks the panel hierarchy
  rather than the workspace. The pages read series-level rows, which are
  correct, but the aggregate rows cover branches no page shows.
- **342 of 654 forecast rows are unavailable** and say why; that is the honest
  state, not a failure.
- The four new pages have **no component tests yet** — they were verified in
  the browser against live data. The nav contract is tested.

---

## Forecast run scoping fixed (D-058)

The forecast run built its scope plan from the unrestricted panel, so it
covered 53 branches on a 2-branch workspace and reconciled a 53-branch
national total onto 2 modelled branches.

The panel is now cut to the workspace before the plan is built. Regenerated
(`f5e2be64`), same champions and same panel:

```
scopes            121 -> 52       (52 with a champion, was 52 of 121)
rows unavailable  342 -> 0
branch scopes      53 -> 2        AHMEDABAD, BENGALURU
regions             6 -> 2        WEST, SOUTH-1
reconciliation    mint_variance -> mint_shrinkage
```

`rows_unavailable` reaching zero is the substantive part: every scope now has
a champion, so nothing is forecast without a model. The reconciliation method
also improved — a coherent 5-node hierarchy admits shrinkage where the
60-node mixed one fell back to variance scaling.

Verified in the UI: `AHMEDABAD|FG.MYC.BCK.G00300A000` → VAR, 84 units for
Aug 26, 6/6 horizons, reconciled by `mint_shrinkage`.

### Verification

```
backend:  864 passed in 45.53s   (was 858)
frontend: 213 passed (18 files)
```

New: `backend/tests/test_forecast_scope.py` (6 tests).
Changed: `backend/app/services/forecast_service.py`.

---

## Demand Analytics visuals restored to Overall Analysis (D-059)

The D-057 rewrite of Overall Analysis carried six panels where Demand
Analytics had sixteen. Overall Analysis is now rebuilt from that page and
carries all of them, plus the scope banner, the ABC/Pareto view and the
exception mix — **18 panels, 19 charts**.

Verified in the running app: every original panel title present, the filter
bar intact, and filtering drives the whole page (₹24.72Cr → ₹9.50Cr on
AHMEDABAD, restored on clear).

```
frontend: 213 passed (18 files)
tsc --noEmit: clean
```

Changed: `frontend/src/features/overall/pages/OverallAnalysisPage.tsx`.

---

## Gaps filled, drift added, two silent bugs fixed

### Two defects found by looking at the running app

**The page grew a note on every load** (D-062). `_stamp` appended the
workspace note to the *cached* payload, so "How these measures are defined"
had accumulated fifteen identical copies. Measured: 16 → 17 → 18 notes across
three consecutive requests. `_stamp` now returns a copy; stable at 1.

**Temperature 2.0 produced unusable prose** (D-061). The first live drift
explanation came back as four-language nonsense that would have rendered under
the chart as if it explained something. Explanations now run at
`AI_EXPLANATION_TEMPERATURE=0.3` while the assistant keeps 2.0, plus a
coherence guard that rejects non-prose *and* fluent text that mentions none of
its figures — the harder failure. A rejected reply falls back to the template
and says so.

### Forecasting resolves at every selection (D-064)

```
all / all   -> national / NATIONAL       6 rows, drift +14.72%
one / all   -> branch / AHMEDABAD        6 rows, drift  +3.63%
one / one   -> series / AHMEDABAD|FG.MP8 6 rows, drift  -4.60%
all / one   -> no such level; explained, not shown as empty
```

Aggregates now carry a prominent caution that their error does not transfer to
a single branch × SKU cell.

### Demand drift, with an honest projection (D-060)

New `GET /api/analytics/drift` plus a panel on Forecasting: 17 measured
points, a 20% reading aid, and a projected crossing at **2026-09** from 6
clean points. Points straddling the Apr 2025 source change are drawn muted and
excluded from the projection. The projection returns `projectable: false` with
a reason in four distinct cases, and states in every payload that it is not a
forecast from any of the 13 models. An LLM explanation sits below the chart.

### The gaps were a missing axis (D-063)

On a workspace defined as 20 SKUs, Overall Analysis had **no per-SKU visual**.
Added `by_sku` to the summary payload plus **Top SKUs by Ordered Demand**
(filled vs unfilled, stacked) and **Service Risk by SKU** (unfilled share,
worst first). Now 20 panels, 21 charts. "How these measures are defined"
removed on request.

### Supply Intelligence explains itself (D-065)

Eight terms defined on the page — recommended order, protection period,
service level, usable stock, dead stock, zero stock against live demand,
negative stock row, lead-time CV — each with its limit stated alongside it.

### Verification

```
backend:  884 passed in 59.34s   (was 864)
frontend: 213 passed (18 files)
tsc --noEmit: clean
```

New: `backend/app/domain/ais/drift.py`,
`backend/app/services/assistant/quality.py`,
`backend/tests/test_drift_and_quality.py` (20 tests),
`frontend/src/features/supply/components/SupplyExplainer.tsx`.
Changed: `api/routes/analytics.py`, `domain/ais/analytics.py`, `core/config.py`,
`api/analytics.ts`, `OverallAnalysisPage.tsx`, `ForecastingPage.tsx`,
`SupplyIntelligencePage.tsx`, `ReferenceParityPages.test.tsx`.

---

## Forecast view slicer, and drift as a line chart (D-066)

Four views on the Forecasting chart — **Full timeline · Actual · Backtest vs
actual · Forecast** — each swapping the matching detail table, verified live:

```
Full timeline      -> forecast-table
Actual             -> actual-table + forecast-table
Backtest vs actual -> backtest-table + forecast-table
Forecast           -> forecast-table
```

Backtest is a separate view, not another line, because it is how the error was
measured on months that already happened — not the future forecast. Each
backtest origin is shown on its own.

Drift is now a line chart: measured shift in solid blue, the windows that
straddle the Apr 2025 source change in dashed grey, and the projected path to
the threshold in dashed amber when one is projectable. A shaded band marks the
region inside the reading aid.

Two things caught while building it. `connectNulls` on the solid line drew a
straight line through the excluded region — turned off, so the gap is honest.
And a `NaN` in the projected rows made Recharts render an empty container with
no error at all; projected rows now carry `null`.

### Verification

```
backend:  884 passed in 43.90s
frontend: 213 passed (18 files)
tsc --noEmit: clean
```

**One intermittent failure observed**, not caused by this work and not chased:
`test_rollback_restores_the_previous_choice_as_a_new_row` failed once in five
full runs and passed the other four. It creates three champion rows in quick
succession, so it looks like the same created_at tie that made the panel-build
test flaky. Champion code was not touched this turn.

---

## The forecast looked like zero because the chart mixed two populations (D-067)

`_history_for` read the panel **unrestricted** while the forecast came from
the restricted run, so the full timeline drew a 53-branch actual against a
2-branch forecast:

```
before   national history Jul 2026 = 200,686   forecast Aug 2026 = 3,310
after    national history tail [3258, 3705, 3242] -> forecast [3311, 3202, 3341]
         AHMEDABAD    tail [1142, 1457,  953] -> forecast [1198, 1281, 1051]
```

The forecast now continues the actual line instead of collapsing onto the
axis. This was the cause of "can't detect what is actual, backtest, forecast"
— the forecast was sixty times smaller than the line beside it.

### Telling the three apart (D-068)

The full timeline now carries a labelled **"forecast begins"** divider and a
shaded band over the forecast span, distinct stroke treatments per series, and
the **backtest drawn on the timeline itself**, aligned to the months it
covers. Legend verified in the running app:

```
Ordered demand (actual) · Backtest (out-of-sample) · Forecast · q80 · q90 · q95
```

Next-month national forecast reads 3,311 against a 3,242 July actual.

### Verification

```
backend:  884 passed in 53.89s
frontend: 213 passed (18 files)
tsc --noEmit: clean
```

Changed: `backend/app/services/forecast_service.py`,
`frontend/src/components/charts/DemandChart.tsx`,
`frontend/src/features/forecasting/pages/ForecastingPage.tsx`.

Not visually confirmed: the "forecast begins" divider and shaded band render
as ECharts canvas, and the browser pane would not screenshot that region
reliably. The legend, the series list and the underlying numbers were all
verified; the marker itself was not seen.

---

## "Not available" no longer means "does not apply" (D-069)

The chart tooltip printed **"Not available"** for every null, so hovering a
historical month reported the forecast as unavailable, and hovering a forecast
month reported the actual as unavailable. Neither is true — a forecast simply
does not reach Mar 2026, and Oct 2026 has not happened.

That matters beyond wording: "Not available" is the term this project uses for
a value that *should* exist and could not be produced, and the seven data
states are required to stay distinct.

The tooltip now knows each series' span. Outside it, the series is omitted;
inside it, a null still reads "Not available" and carries the row's
`unavailable_reason`. Verified live:

```
mid-history   Ordered demand (actual) 2,611
near origin   Ordered demand (actual) 3,242 · Backtest (out-of-sample) 3,022.85
Dec 26        Forecast 3,226.55 · q80 3,773.8 · q90 3,872.15 · q95 3,970.5
```

### Verification

```
backend:  884 passed in 70.84s
frontend: 213 passed (18 files)
tsc --noEmit: clean
```

Changed: `frontend/src/components/charts/DemandChart.tsx`.

---

## The layout gaps are closed (D-070)

My first pass added SKU panels lower down and left the visible hole alone —
the four-column row where 1+1+1+2 wrapped. Fixed properly by adding the axes
the sample was actually chosen on and which the UI never showed:

```
Demand by Glass Type        Lam 65,056 · Backlite 4,838 · Sidelite 2,264
Demand by Vehicle Category  CAR & MUV 53,264 · 3W 10,854 · COMMERCIAL 7,929 · HIGH END 111
Demand by Vehicle Age       >15y 39,582 · 9-15y 17,834 · 3-6y 12,678 · 0-3y 1,840 · 6-9y 224
```

The branch-scorecard card grid was a separate hole: fixed at four columns, so
two branches left two cells empty whatever was added. It now follows the
branch count.

Measured rather than eyeballed — every grid row checked for trailing empty
cells:

```
before   2 rows with holes (1 and 2 cells)
after    0 holes across 9 rows · 24 charts
```

### Verification

```
backend:  884 passed in 49.21s
frontend: 213 passed (18 files)
tsc --noEmit: clean
```

Changed: `backend/app/domain/ais/analytics.py`, `frontend/src/api/analytics.ts`,
`OverallAnalysisPage.tsx`, `ReferenceParityPages.test.tsx`.

## The row that the hole-count missed, and four panels to fill it (D-071)

D-070 above reports "0 holes across 9 rows". That was measured with modulo
arithmetic, and **it was wrong** — the row still rendered with a gap. The count
was `(cols - (spanUnits % cols)) % cols`, which for 8 units in 4 columns is 0.
But CSS grid places items in order and a 2-span item cannot be split: arriving
with one column left, `Demand by Branch × Value Class` wrapped to the next row,
leaving a cell empty behind it and pushing `Demand by Vehicle Age` onto a row
of its own with three cells empty. A remainder tells you the units divide; it
cannot tell you they tile.

**Fixed by ordering.** The 2-span panel is now first in its row, and carries
`lg:col-span-2` as well as `xl:col-span-2` so the row tiles at both
breakpoints.

**Four panels added**, taking the row to 12 units — three exact rows of four.
Each is a ratio of figures `/analytics/summary` already returns; none is a new
measurement:

```
Fill Rate by Glass Type             Lam 53.0% · Backlite 52.6% · Sidelite 48.8%
Value per Unit by Vehicle Category  ₹27K · ₹4K · ₹2K · ₹2K per unit
Volume vs Value by SKU              20 marks, sized by branch × SKU series count
Unfilled Share by Vehicle Age       0-3y 38.7% · 6-9y 26.8% · 3-6y 24.9% · 9-15y 6.4% · >15y 5.4%
```

The last one is the finding worth keeping: **unfilled share runs inversely to
volume on the age axis.** The oldest parc carries the most demand (39,582
units) and is served best (5.4% unfilled); the newest carries the least (1,840)
and is served worst (38.7%). Small, new-vehicle demand is the least reliably
met — which the volume bars alone could never show.

Fill rate omits any level with no recorded despatch, because `despatched_units`
is `None` there and a `None` is not a zero. Plotting it at 0% would read as
"nothing was despatched" when the truth is "nothing was recorded". All three
glass types have despatch recorded on this workspace, so the footnote naming
the omission does not currently render.

### Verification — geometry measured, not computed

Every grid child grouped into real rows by `getBoundingClientRect().top`, each
row's occupancy compared to its computed column count. This is the check that
replaces the arithmetic which produced the false result above.

```
viewport 1440 · grid-template-columns: 271.2px × 4
row 1  Branch × Value Class | Branch | Value Class                       4/4
row 2  Unfilled by Value Class | Glass Type | Vehicle Cat | Vehicle Age   4/4
row 3  Fill Rate | Value per Unit | Volume vs Value | Unfilled Share      4/4
rows 4-9  (trend, branch, seasonality, SKU, concentration rows)        all full
totalHoles: 0   ·   52 SVGs · 103 bars · 20 scatter marks
```

An earlier probe reported every chart empty, including ones known to work.
That was stale HMR state in the open tab, not a defect — a full reload renders
all of them. Fill-rate labels were cross-checked against the API rather than
read off the chart: 34,505/65,056 = 53.0%, 2,547/4,838 = 52.6%,
1,104/2,264 = 48.8%.

```
backend:  884 passed (0 failed, 0 errors, exit 0)
frontend: 213 passed (18 files)
tsc --noEmit: clean
decision citations: 38 cited, 71 documented, 0 missing
```

Changed: `frontend/src/features/overall/pages/OverallAnalysisPage.tsx`,
`docs/DECISIONS.md`, `docs/STATUS.md`.

## Forecast impact panel, and a live training monitor (D-072, D-073)

Two features, both on request. 67 endpoints now, from 65.

### Forecast impact — Forecasting tab, between the forecast and drift

The ask was impact on sales, stock-outs and revenue at 1 / 3 / 6 months. **None
of those three is measurable in this project** and the panel says so rather
than producing a number: no forecast month has elapsed (history ends 2026-07,
the origin is 2026-08), there is no inventory-policy backtest, and a sales
uplift needs a counterfactual that does not exist in any dataset here.

What *is* measured is error against a naive carry-forward, recovered from the
folds already scored during training - no second evaluation path:

```
horizon   champion   naive    reduction
   1       20.31%    25.61%    20.72%
   2       22.84%    24.07%     5.11%
   3       20.47%    25.52%    19.78%
   4       25.91%    27.36%     5.31%
   5       30.00%    28.38%    -5.69%   <- naive wins; drawn, not hidden
   6       28.51%    30.85%     7.57%
```

Three sliders on the panel convert that into units and rupees - recovery
share, margin, stock efficiency - defaulted conservatively and echoed in the
payload. Chosen over hard-coded constants because this is shown to a client:
a challenged figure is answered by moving a slider, not by defending a hidden
number. Verified live: 0.30 -> 0.60 on recovery share doubled every figure
(Rs 55K -> Rs 1.10L, Rs 1.57L -> Rs 3.14L, Rs 1.20L -> Rs 2.40L).

**Six months projects less than three** (Rs 1.20L against Rs 1.57L) because the
measured reduction falls from 19.78% to 7.57%. Stated on the panel, because it
looks like a bug and is not.

**A silent failure worth recording.** The first version read `origins_json`
with `json.loads`; it is a JSON column, so SQLAlchemy returns a parsed list and
`json.loads` raised straight into the function's own `except`, returning no
folds. The endpoint then reported 40 series, 16 beaten by a baseline, and *no
measured horizons at all*. Caught only by comparing the endpoint against the
same numbers computed independently from raw SQL - the error handling produced
the zero, not the data.

**Impact follows the champions in force, not the newest run.** Champion
selection is a separate step, so a newer training run can exist with no
champions chosen from it. Picking it would blank the panel while the
Forecasting tab beside it was still serving the older run's champions. Found
by running a second training run during verification and watching the panel go
empty.

### Training monitor — top of the Training tab

The page explained the design; it could not say whether a run was working.
`GET /training/{run_id}/monitor` aggregates per-model state server-side (884
model-run rows would otherwise ship on every 2-second poll) and returns the
fold design read from a fold the run actually scored:

```
origin 1 (primary)  train through 2025-09 (18 mo) -> validate 2025-10..2026-03
origin 2 (second)   train through 2026-01 (22 mo) -> validate 2026-02..2026-07
```

Drawn on a real month axis, so the leakage-safety property is visible rather
than asserted. Status is stacked by outcome and never collapsed into a score;
the four baselines sit below a labelled divider and can never be presented as a
fourteenth model.

**Verified against two real training runs**, not a fixture. The first
(`61c53a7f`) exposed a defect: the progress bar advanced from SSE while the
model table sat frozen, because a React Query interval pauses on a hidden tab
and an EventSource does not. `refetchIntervalInBackground` while live fixes it,
confirmed on a second run (`0f69c55b`) with the tab hidden - bar 11.8% ->
18.6% and table 51 -> 119 advancing together, where before the table had stuck
at 357 while the bar moved.

Both runs remain in the database as real history; `c6812131` still holds the
active champions.

### Verification

```
backend:  901 passed (884 + 17 new in tests/test_impact.py), 0 failed, 0 errors
frontend: 213 passed (18 files)
tsc --noEmit: clean
endpoint drift: 0 missing from docs/API_CONTRACT.md
decision citations: 40 cited, 73 documented, 0 missing
```

Created: `backend/app/domain/ais/impact.py`,
`backend/app/services/impact_service.py`,
`backend/app/services/training/monitor.py`, `backend/tests/test_impact.py`,
`frontend/src/features/forecasting/components/ImpactPanel.tsx`,
`frontend/src/features/training-explained/components/TrainingMonitor.tsx`.
Changed: `backend/app/api/routes/analytics.py`,
`backend/app/api/routes/training.py`, `frontend/src/api/analytics.ts`,
`frontend/src/api/training.ts`, `ForecastingPage.tsx`, `TrainingPage.tsx`,
`docs/API_CONTRACT.md`, `docs/DECISIONS.md`, `docs/STATUS.md`.

## Composition panels now declare their sampling bias (D-074)

Asked whether the 20 SKUs relate to the vehicle-category chart. They do - and
checking it surfaced that **every composition panel on Overall Analysis was
being read as a business fact when it describes a stratified sample.**

`GET /api/analytics/sample-mix` compares the sample against the same two
branches with every SKU, and each of the four composition panels renders its
own computed caveat with an expandable level-by-level table.

```
axis                  worst level            sample   branches    gap
vehicle_age_category  Category Z (>15 yrs)    54.9%     28.0%    +26.9
glass_type            Lam                     90.2%     68.4%    +21.7
value_class           A                       95.4%     74.3%    +21.1
vehicle_category      CAR & MUV               73.8%     87.2%    -13.4
```

Two findings worth keeping. **Vehicle category is the least distorted of the
four** - the axis the question was about - and vehicle age, never a
stratification rule, is the worst; computing per axis rather than writing a
sentence is what caught that. And the first materiality rule (gap AND ratio)
**excused the single largest distortion**, because a level holding two thirds
of the volume cannot have an extreme ratio. Changed to OR, with a points floor
so tiny levels stay quiet.

### Verification

```
backend:  914 passed (901 + 13 new in tests/test_representativeness.py), 0 failed
frontend: 213 passed (18 files)
tsc --noEmit: clean
endpoint drift: 0 missing (67 -> 68 documented)
UI: 4 caveats render on /overall with the correct per-axis figures;
    expanded table matches the API level for level
```

Created: `backend/app/domain/ais/representativeness.py`,
`backend/tests/test_representativeness.py`,
`frontend/src/components/ui/SampleMixCaveat.tsx`.
Changed: `backend/app/api/routes/analytics.py` (new route; `_latest_build` and
`_panel_path` extracted from `_panel`), `frontend/src/api/analytics.ts`,
`OverallAnalysisPage.tsx`, `docs/API_CONTRACT.md`, `docs/DECISIONS.md`,
`docs/STATUS.md`.

## Workspace moved to Delhi, SKUs re-selected, training made startable (D-075, D-076)

**Branches are now BENGALURU + DELHI-1.** There is no branch called DELHI - the
network has DELHI-1, DELHI-2 and DELHI-E1, and DELHI-1 is the largest with a
full 28 months.

**The twenty SKUs are re-selected to track demand by vehicle category.** Two
proportional-allocation attempts failed (allocating slots proportionally does
not make volume proportional - one windscreen outsells several sidelites), and
unconstrained optimisation failed the other way, picking twenty negligible
products carrying 1.1% of units. The selection now optimises mix deviation
against a coverage term; lambda 0.2/0.5/0.8 all converge on the same twenty.

```
axis                    old gap   new gap
vehicle_category  *        13.4       4.9     <- the requested axis
value_class                21.1       7.3
glass_type                 21.7      14.8
vehicle_age_category       26.9      15.1
coverage of branch units   15.9%      8.4%    <- the cost, stated
```

It forecasts better too: series beaten by a baseline fell **16/40 -> 6/40**,
and measured error reduction at one month rose 20.7% -> 26.3%.

**`AIS_MIN_HISTORY_PROFILE=monthly_relaxed` is now set.** Without it the Start
training button produces a run where **six of thirteen models are 100%
ineligible** - 28 months of history, a second fold training on 22, and Auto
ARIMA plus all four Exponential Smoothing variants needing 24. This is the
trade-off `config.py` documents and D-001 records; the earlier working run had
used the relaxed profile and the new one silently did not.

**Training now starts from the page**, and a run is drawn as a race: one bar
per model, sorted by measured accuracy, rows travelling to new positions with
FLIP as the ranking changes, settling into the leaderboard when the run ends.
It replaced a lattice of coloured cells that showed work being done and nothing
about models competing, and absorbed the old accuracy chart and model table.

The leaderboard promptly proved its own caveat: **VAR ranks first on median
accuracy with zero champion wins** (scored on 32 scopes, ineligible on 18)
while **Auto ARIMA ranks fifth and wins 10**. Most accurate on the median is
not the same as champion.

### Verification

```
training run a2c987d9   553 completed · 97 ineligible · 0 failed
champions               50 active (40 series) · 6 beaten by a baseline
forecast run bc8b8020   completed · mint_shrinkage · 6 periods with q80/q90/q95
race reordering         9 of 17 rows changed position in 20s on a live run
start button            one click -> one queued run; hidden while a run is live
backend                 914 passed, 0 failed, 0 errors
frontend                213 passed (18 files)
tsc --noEmit            clean
```

Created: `frontend/src/features/training-explained/components/ModelRace.tsx`,
`TrainingLauncher.tsx`.
Removed: `TrainingLattice.tsx` (superseded), and the `AccuracyChart` /
`ModelTable` sections of `TrainingMonitor.tsx`.
Changed: `TrainingMonitor.tsx`, `frontend/src/api/training.ts`,
`frontend/src/styles/reference.css`, `backend/.env`, `docs/DECISIONS.md`,
`docs/STATUS.md`.

## Training view rebuilt as a vertical accuracy race (D-077)

The horizontal bar race and the separate leaderboard are gone. One panel now
carries the whole ranking: thirteen columns, height = accuracy (100 - median
MAPE), best on the left, reordering live as the run scores them.

```
run 8c691b3a · 419.9s · 553 completed · 97 ineligible · 0 failed

 #  model                                   accuracy  wins
 1  VAR                                       69.2      0
 2  LSTM                                      68.8      9
 3  VAR with exogenous variables              66.9      1
 5  Auto ARIMA                                65.6     10
 ...
13  SARIMAX with exogenous variables          45.0      0

best baseline  Moving average (6)  61.5%   <- dashed line
models below that line: 7 of 13
```

MAPE needed no backend change: `champion_primary_metric` was already `"mape"`
and accuracy was already defined as `100 - MAPE` clamped at zero, so the column
height is the same quantity the champion selector ranks on.

Baselines are a dashed reference line rather than columns - the request was for
thirteen models ranked 1st to 13th, and a line cannot be mistaken for a
fourteenth model. Seven models falling below `ma6` is the chart's most useful
finding and the removed table buried it.

Verified on a live run: 5 of 13 columns changed position in 22 seconds; column
left-offsets monotonic once transitions settle; button reads `Train models` and
starts one run per click.

```
backend   914 passed, 0 failed
frontend  213 passed (18 files) — includes the no-duplicate-registry guard
tsc --noEmit clean
```

Changed: `ModelRace.tsx` (rewritten vertical), `TrainingMonitor.tsx`
(leaderboard removed), `TrainingLauncher.tsx` (button label),
`backend/app/services/training/monitor.py` (fold selection),
`docs/DECISIONS.md`, `docs/STATUS.md`.

## Training console rebuilt as a bar chart race (D-078)

One button, thirteen models, horizontal bars that overtake continuously; the
settled order is the result. Custom DOM + `d3-scale`, zustand outside React's
render path, one `requestAnimationFrame` loop writing widths and transforms.

New: `src/config/models.ts` (families, metric, race constants, family rule),
`features/training-race/` (types, store, frame planner, MockTrainer,
SSETrainer, ApiTrainer, BarRace, TrainingConsole), and
`GET /api/training/{run_id}/model-events` emitting
`started`/`progress`/`finished`/`failed`.

The model list is **not** in the config file: the thirteen are asserted
server-side and `no-duplicate-registry.test.ts` bans model literals in frontend
source, so `resolveModels()` adapts the API rows instead. Everything else
variable is in that one file.

Four defects found and fixed while building: `width` declared in JSX undid the
loop every render; the field reloaded mid-race on every query refetch; a
StrictMode-detached ref measured zero so the loop never drew; and the
forbidden-token guard is a substring scan that the *comment* about it tripped.

**Not verified here:** rAF does not fire in a hidden document and this
environment reports the pane hidden even when fronted - 0 frames in 1.2s. The
frame arithmetic was extracted to `frame.ts` and tested without a DOM instead
(14 tests); a full mock run replayed through the real planner gives **13 lead
changes** against a required 4. Sustained 60fps still needs a profiler on a
visible window.

```
backend   914 passed, 0 failed
frontend  227 passed (19 files) - includes the registry guard
tsc --noEmit clean
model-events stream verified against a live run
```

## Impact panel removed; race attaches to the current run (D-079)

The measured/projected impact charts and their caveat panel are removed from
Forecasting and `ImpactPanel.tsx` deleted, along with a caption that had been
hard-coding "negative at month 5" three runs after it stopped being true. The
`/analytics/impact` endpoint and its tests remain.

The race now hydrates from the current run on mount instead of only on a button
press - which fixes all three reports at once: blank during training, blank
after training, and wiped when navigating back. A finished run goes straight to
`done` so bars show final lengths rather than replaying an old race.

**Pre-existing bug found:** `_TERMINAL_RUN_STATES` omitted
`completed_with_warnings`, the state 14 of 28 runs are in. Both SSE streams use
it to decide when to send `end`, so neither ever closed on a normal run.

```
before   started 17 · progress 17 · finished  0 · end 0
after    started 17 · progress 17 · finished 17 · end 1
```

Verified with no button press: navigating away and back gives 17 racers, all
scored, phase `done`, statuses `finished`, standings VAR 69.2 / LSTM 68.8 /
VAR+exog 66.9.

```
backend   914 passed, 0 failed
frontend  227 passed (19 files)
tsc --noEmit clean
```

## Race is the 13; leaderboard added; Ineligible diagnosed (D-080)

Baselines no longer get lanes - the race and the leaderboard are the thirteen
registered models. Baselines are still fitted and reported in one line beneath
the table, because `ma6` at 61.5% beats seven of the thirteen and deleting that
would flatter the result.

New `Leaderboard.tsx`, following Oxea's: a row per model including those that
did not run, status badges keeping Completed / Ineligible / Failed / Timed out
apart, and rank / accuracy / MAPE / WAPE / MAE / RMSE / bias / scopes / wins /
fit. Sortable; unscored models sort last either way. Hover an Ineligible row
for the requirement it missed.

**Accuracy was already MAPE-based** - verified rather than asserted: VAR shows
69.2%, which is `100 − 30.84` (MAPE); WAPE would have given 65.9%. It is now
computed once in `monitor.model_progress` so three surfaces cannot diverge. The
WAPE on screen was the Forecasting page's per-series tile, a different thing.

**The 97 Ineligible:** 30 VAR (needs two co-evolving series, only 1 of 4
qualifies), 24 multiplicative smoothing (needs strictly positive values, series
contain real zeros), 43 insufficient history - of which 33 are one SKU,
`FG.M20.FDR.G003200200`, a genuinely new product with 4-8 months. 54 of 97 are
impossible; making them "eligible" would mean fitting models on data that
cannot carry them.

```
backend   914 passed, 0 failed
frontend  227 passed (19 files)
tsc --noEmit clean
UI verified: 13 race lanes, 13 leaderboard rows, all columns, baseline line present
```

## SKUs re-selected on real eligibility; Ineligible 97 -> 16 (D-081)

Selection now demands what the models demand: >= 18 non-zero months before the
first fold cut in both branches, no zero months, complete non-constant
`mean_mrp` so VAR has a second series. 56 of 1,258 SKUs qualify; the mix
objective picks 20.

```
                 before      after
ineligible       97 of 850   16 of 816
Completed        0 of 13     11 of 13
accuracy         45-69%      64-73%
coverage          8.4%       16.5%
```

Remaining 16 are VAR / VAR+exog at aggregate scopes only - summing
always-supplied SKUs leaves nothing for VAR to co-evolve with. Structural.

**Cost:** the eligible pool is mature class-A product, so glass type (14.8 ->
25.3) and value class (7.3 -> 20.6) got less representative; vehicle age
improved (15.1 -> 3.8). 3W, HIGH END and classes C/D/New Model drop out.

**Leaderboard gained `Agg.` and `Series` accuracy columns.** The blended number
was a mix of national (87.5%) and branch x SKU (51.6%) and sat near the harder
one because most scopes are series-level.

**Champion mismatch explained on the page:** ranking first is an average across
scopes, a champion is chosen per scope, and a banner now fires when the
displayed run has no champions selected - which was why Forecasting served an
older run's model.

```
training 9d4acafe · 608 completed · 16 ineligible · 0 failed
champions selected · forecast 3811a3b9 · mint_shrinkage
backend 914 passed · frontend 227 passed (19 files) · tsc clean
UI: 13 lanes, 13 rows, 11 Completed / 2 Partial
```

## Positivity relaxed - and it was never the binding rule (D-082)

Measured before changing anything: all 56 SKUs passing the other rules already
had zero zero-months, so relaxing positivity moved nothing. The binding rule
was `mean_mrp` complete-and-non-constant, which existed only to make VAR
eligible. Dropped that instead.

```
                 before    after
ineligible       16         6
Completed        11 of 13  11 of 13
glass gap        25.3      21.4
value gap        20.6      18.3
coverage         16.5%     14.7%
```

Removing VAR's own constraint *improved* VAR: it gained aggregate scores it
previously had none of (82.1%). The remaining 6 are VAR / VAR+exog on three
aggregate scopes where the companion series flatten.

Run `bcc6f53f` - 618 completed, 6 ineligible, 0 failed. Champions selected and
forecast rebuilt. Leader LSTM at 70.0% blended, 84.5% aggregate, 65.8% series.

```
backend 914 passed, 0 failed
frontend 227 passed (19 files)
tsc --noEmit clean
UI: 13 lanes, 13 rows, 11 Completed / 2 Partial
```

## Reserved slots for 3W and class C (D-083)

Run `6a83f712`. Forced picks: 3W `FG.BA5` (16 months, 9,672 units), class C
`FG.T56` (14 months, 341 units), and COMMERCIAL `FG.TCF` - the third reserved
because forcing 3W had removed COMMERCIAL entirely, and COMMERCIAL is 9.5% of
real demand against 3W's 4.1%.

HIGH END stays out: its best SKU has 4 clear months and would be Ineligible for
almost every model.

```
                    D-082        D-083
ineligible           6            14
Completed          11 of 13      9 of 13
categories          2             3
value classes       2             3
coverage           14.7%        19.5%
vehicle_age gap     8.7           3.4
vehicle_cat gap     7.5          12.3
```

The 14 Ineligible: 8 VAR at aggregate scopes (structural), 6 on the two forced
SKUs where the multiplicative pair needs 18 observations and one SKU has 4 zero
months. Both are the price of the slot.

Vehicle-category error rose despite the category being present - 3W is 16.1% of
the sample against 4.1% of real demand, because its only usable SKU is large.
Presence and proportion pull apart here.

Leader: Exponential Smoothing Multiplicative, 73.5% blended / 86.3% aggregate /
71.2% series. Champions selected, forecast rebuilt.

```
backend 914 passed, 0 failed
frontend 227 passed (19 files)
tsc --noEmit clean
UI: 13 lanes, 13 rows, 9 Completed / 4 Partial
```

## The pipeline is explained on the page, and the champion mismatch is fixed (D-084)

Training explained its rules but never its shape. `monitor.pipeline` now carries
scope counts by level, registry/baseline counts, champions selected, champions
beaten by a baseline, and the champion spread; `PipelineExplainer` renders it as
six steps - scopes, fits, folds, ineligibility, per-scope selection, refit and
reconciliation. No figure in it is prose: the reconciliation method is read from
the forecast run, and six tests feed a differently-shaped run to prove the
sentences move.

**Cause of the Training/Forecasting mismatch:** champion selection had never run
on `9bc1c69c` (0 active champions), so Forecasting served `6a83f712`'s. The
default `scope_kinds` also omits `series`, so the obvious call selects 9 of 49
and looks successful.

```
champions          49 of 49 scopes
distinct winners   13 - every registered model won at least one scope
beaten by baseline 14 of 49
forecast           b428bb95 - origin 2026-07, mint_shrinkage, coherent
rows               294 = 49 x 6; 288 with a number, 6 with a reason and none
NATIONAL champion  exp_additive, lineage 9bc1c69c - Training and Forecasting agree
```

The 6 unavailable rows are one series whose champion (`var_exog`) won on
validation then could not refit on full history. Null, never zero.

```
backend 914 passed, 0 failed
frontend 233 passed (20 files)
tsc --noEmit clean
```

## 196 baseline rows were written and counted by nothing (D-085)

The monitor reported `total 833 / completed 623`, which does not reconcile.
`_evaluate_scope` persists registry models and baselines in two loops; both
incremented `rows`, only one incremented `counts`. Run counters are written from
that return value rather than recomputed from the rows, so every baseline row
inflated the total while belonging to no status.

```
before   total 833 · completed 623 · ineligible 14   (196 unaccounted)
after    total 833 · completed 819 · ineligible 14   (sums exactly)
```

Counters on run `9bc1c69c` were recomputed from its rows. `TestScopeCounting`
guards the structure - every persisting loop must touch `counts`, and there must
be exactly two - and was verified to fail against the reintroduced bug.

```
backend 915 passed, 0 failed
frontend 233 passed (20 files)
```

## Scenario Planner removed from the UI (D-086)

Requested. Nav is now **seven tabs**: Overall Analysis, Per Branch & SKU,
Training, Forecasting, Supply Intelligence, AI Assistant, AI Recommendations.

Unrouted, not deleted - the page, its test, `POST /api/scenarios` and the API
client are untouched, so restoring it is the nav item plus the route.
`REQUIRED_NAV_INDEXES` drops 8; survivors keep their original numbers so the
gaps still record what went.

```
nav links      7 (verified in the browser)
/scenarios     falls through to Overall Analysis, no error
endpoints      67 = 67, POST /api/scenarios still live and documented
frontend       233 passed (20 files)
tsc            clean
```

## Volume-weighted accuracy on the leaderboard (D-087)

Asked to lift 73.5% towards 90%. Measured first: the blend is an unweighted mean
over 49 scopes and 40 are branch x SKU at 43% accuracy, while national is
already 86.6%. The worst series are the smallest - FG.T56 sells 99 units in 28
months and scores 201% MAPE.

**Bias correction was tried and rejected on evidence.** A leakage-safe factor
estimated inside each fold's training window made national 89.4% -> 82.6%. The
-10% bias comes from a 42% demand rise that accelerates only in the scored
months, so it is not estimable from training data.

Seasonality, log transform and damping changed national accuracy by under half a
point. No configuration was left on the table.

```
leader, unweighted   73.5%
leader, weighted     83.7%
```

`accuracy_weighted` weights each scope by its demand volume, recovered from the
stored MAE/WAPE/points rather than re-reading the panel; scopes with no usable
WAPE are excluded rather than assigned a weight. Both figures are on every row,
and the unweighted one is exactly 100 - MAPE in the next-but-two column. The
champion selector still ranks on MAPE.

90% is not reachable on this metric and the docs say so.

```
backend 915 passed, 0 failed
frontend 233 passed (20 files)
tsc --noEmit clean
```

## Leaderboard row now reconciles; race aligned; forecast line joined (D-088)

```
before   accuracy 83.7% (weighted)  beside  MAPE 27.3% (median)   -> 100-27.3 = 72.7
after    accuracy 83.7% (weighted)  beside  MAPE 16.3% (weighted) -> sums to 100.0
```

`mape_weighted` published from the monitor and shown in the MAPE column.
`race_events._accuracy` now emits the weighted figure, so the bars and the table
quote the same number; the baseline comparison line does too.

The forecast line's break at the origin is closed by anchoring the point series
to the last actual - a drawing bridge only, kept out of the tooltip by
`spanFor`, and the quantile bands are not bridged.

Sampling caveats collapsed behind "How representative is this sample?".

**85% not reached.** 83.7% is what is measured; going higher needs the
weekly-grain work, not a setting.

```
backend 915 passed · frontend 233 passed · tsc clean
```

## q95 under-coverage, and the assistant's multi-script answers (D-089, D-090)

**q95 delivered 72.9% against a claimed 95%.** Two defects: offsets were
absolute quantities pooled across scopes of different size, and a scope has
twelve residuals where q95 needs nineteen. Residuals are now relative and the
offset is a fraction of the point forecast; a scope claims only the levels its
own sample supports and falls through per level to the run's pooled cell.

Restricted to series scopes after pooling across levels blew the national q95
out to 93-162% above the point forecast - the 91.1% measurement was taken on
series and did not transfer.

```
NATIONAL   conformal  scope_all_horizons     n=12   q95 +24% -> +40%
SERIES     conformal  model_horizon_segment  n=41   q95 +44% -> +98%
```

`MAX_RELATIVE_OFFSET = 20.0` rejects the 156 stored absolute-era calibrations
rather than applying `261.0` as a multiplier.

**The assistant answered in four scripts.** `AI_TEMPERATURE` was 2.0 and the
coherence guard, which rejects that text correctly, was wired to the drift
explanation only - the chat path published whatever came back. Temperature is
0.3 and the guard now runs on both paths, with a chat-specific length floor and
markdown-aware tokenisation so it stops rejecting good short answers.

```
training 7927ee3a - 833 fits, 819 completed, 14 ineligible, 49 champions
forecast 91775e14 - origin 2026-07, coherent, 288 rows + 6 unavailable
backend 919 passed - frontend 233 passed - tsc clean
```

## Stored/displayed/described inconsistencies resolved (D-091)

**q95 is published again at aggregate scopes.** The national forecast held a
stored q95 the current generator would have left empty. `_scope_calibration`
now runs a second pass without the conformal requirement, used only where
there is no pooled cell to prefer, so the band is computed from the twelve
residuals and labelled `empirical`.

```
NATIONAL   q80/q90 conformal n=12   q95 empirical n=12
SERIES     q95 conformal n=41       unchanged
```

Still a measured 72.9% coverage from twelve residuals - the label carries that,
the number is not a 95% service level.

**Leaderboard captions corrected.** Four still claimed the unweighted
`100 - MAPE` was in the MAPE column; that column became weighted in D-088 and
the unweighted figure is no longer displayed anywhere.

**`data/scoped/` regenerated.** It described AHMEDABAD and 1,059 rows; the live
workspace is BENGALURU and DELHI-1 at 1,118 rows over 40 series.

```
forecast f84488b3 - origin 2026-07, coherent, 288 rows + 6 unavailable
```

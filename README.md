# AIS Glass Forecast & Inventory Intelligence

Demand forecasting and inventory recommendation for the AIS Consumer Glass
Solutions branch network, at **branch × SKU × month**, across **13 registered
forecasting models**.

The demand panel holds **68,675 series** over 28 months — the demand-bearing
union of the sales and order histories. The **63,210** figure quoted in the
analysis document is the *sales* universe, and it reconciles exactly; the two
are reported separately and never conflated (`docs/DECISIONS.md` D-025).

**All twelve build phases are complete.** 883 tests pass (731 backend, 152
frontend) and 57 API endpoints are documented and cross-checked against the
running app.

The forecast target is **ordered quantity**, not despatched quantity. 19.38% of
ordered units were never despatched, so a model trained on despatches learns
the supply constraint and forecasts the stockout forward — it would recommend
the very stock levels that caused the stockout.

## What it produces, measured

Every figure below was measured in this project on the real client files. None
is carried over from the analysis document.

| | |
|---|---|
| National champion | `var_exog` (VAR with exogenous variables), WAPE **4.578%** |
| Best baseline it beats | `ma6` at 9.939% — a **53.9%** improvement |
| **Where a baseline wins** | **47 of 166 scopes.** Stated on every leaderboard and selection row |
| Models ineligible on this data | **6 of 13** — both Auto ARIMA and all four exponential-smoothing variants need 24 training observations; the primary origin has 22 |
| Models that failed | **0** of 5,219 evaluations |
| Determinism | Two independent runs produced byte-identical WAPEs |
| Forecasts | Horizons 1–6 from origin 2026-07, five levels, **coherent to 0.0** |
| Quantile ordering | `point ≤ q80 ≤ q90 ≤ q95` on all 2,256 persisted rows |
| Inventory | Protection periods 33–35 days from real per-branch lead times |
| Placement | 23,788 dead/slow positions (₹88.7 M) · 21,549 zero-stock-against-live-demand |

The champion is the best of the thirteen registered models. On this dataset
that is **not** the same claim as the best available forecast, and the
application says so wherever the two differ.

## Pipeline order

Each stage refuses to run before its predecessor and names the one that is
missing:

```
register a dataset -> confirm the mapping -> preprocess -> build the panel
   -> train -> select champions -> generate forecasts -> read recommendations
```

## Stack

| Layer | Choice |
|---|---|
| Frontend | React 18 + TypeScript (strict), Vite, React Router, TanStack Query, Apache ECharts |
| Backend | Python 3.12, FastAPI, Pydantic v2 |
| Database | SQLite + SQLAlchemy for the POC, PostgreSQL-ready by construction |
| ML | statsmodels, pmdarima, XGBoost, scikit-learn, TensorFlow (CPU) |
| Tracking | MLflow |
| Data | pandas, Polars, NumPy, PyArrow, streaming `pyxlsb` / `openpyxl` readers |
| Tests | pytest (backend), Vitest + React Testing Library (frontend) |

## Setup

### Prerequisites

| Tool | Version used | Note |
|---|---|---|
| Python | 3.12.10 | 3.12 specifically — `pmdarima` and the TensorFlow CPU wheel are pinned against it |
| Node.js | 24.19.0 | 20+ is enough for Vite 6 |
| npm | 11.17.0 | ships with Node |
| OS | Windows | the helper scripts are PowerShell; the commands underneath are plain `python` / `npm` and run anywhere |

### Clone to a short path (Windows)

```bash
git clone https://github.com/vijju396/Ahai-Glass.git C:/dev/ais
```

Not a preference. `statsmodels` ships compiled extensions, and Windows applies
the 260-character `MAX_PATH` limit when **loading a DLL** even with
`LongPathsEnabled=1` set in the registry. Cloning under a long path was measured
to break 29 tests with:

```
ImportError: DLL load failed while importing _innovations:
The filename or extension is too long.
```

A clone root under ~80 characters is comfortable; 159 characters was not.
Nothing is wrong with the checkout when this happens — move it and re-run.

### What a clone does not contain

Three things are deliberately gitignored, and the application will not serve
data until you supply the first two:

| Missing | Why | What to do |
|---|---|---|
| `data/source/` | Five AIS client files, ~151 MB, not ours to publish | Obtain them from AIS and place them in `data/source/` with their original names (see **Source files** below) |
| `backend/.env` | Holds an API key | `cp backend/.env.example backend/.env` |
| `runtime/` | Generated — database, MLflow, Parquet, logs | Created on first run |

`data/scoped/` **is** committed: the derived slice the deployment actually
reports on — BENGALURU and DELHI-1, 20 SKUs, 40 series, 1,118 panel rows over
2024-04 → 2026-07. `manifest.json` beside the parquet files records the
branches, the SKUs and which decisions chose them.

It is a convenience export and a readable record, not the system of record,
and nothing reads it at runtime. Regenerate it after changing
`AIS_WORKSPACE_BRANCHES` or `AIS_WORKSPACE_SKUS` — it silently described the
previous workspace for several selections before anyone noticed.

#### Source files

Exact filenames, because the readers match on them:

```
data/source/Location Master.csv
data/source/Orders & Receipts (Lead Time).xlsx
data/source/Sales Data FY 24~26.xlsb
data/source/Stock in Hand as on 1st Aug'26.xlsx
data/source/Substitution Mapping.xlsx
```

These are read-only. Nothing in this repository writes to them.

### 1. Install

```bash
powershell -ExecutionPolicy Bypass -File scripts/setup.ps1
```

Creates `backend/.venv`, installs `requirements.txt`, then runs `npm install`.
Equivalent by hand:

```bash
cd backend && python -m venv .venv && ./.venv/Scripts/python.exe -m pip install -r requirements.txt
```

```bash
cd frontend && npm install
```

### 2. Configure

```bash
cp backend/.env.example backend/.env
```

Then read it. Two settings decide what the application shows:

- **`AIS_WORKSPACE_BRANCHES` / `AIS_WORKSPACE_SKUS`** — the slice every page
  reports on. Shipped set to the POC's two branches and twenty SKUs. Leave both
  blank for the whole network. This is not a UI filter; it is stated on every
  payload as `workspace_scope` (D-049).
- **`OPENAI_API_KEY`** — optional. Blank is fine: the AI Assistant and AI
  Recommendations pages fall back to templates and **say so on the page**.
  Every other page is unaffected. The key never reaches the browser — React
  calls this backend, and the backend calls OpenAI.

### 3. Start

Two terminals:

```bash
powershell -ExecutionPolicy Bypass -File scripts/start_backend.ps1
```

```bash
powershell -ExecutionPolicy Bypass -File scripts/start_frontend.ps1
```

- App — http://localhost:5173
- API docs — http://127.0.0.1:8000/api/docs
- Health — http://127.0.0.1:8000/api/health

Migrations run at startup; there is no separate `alembic upgrade` step.

### 4. Load the data

A fresh database is empty, and the pages will render honest empty states until
it is not. The chain is nine POSTs against the running API — there is no UI
route for it, because the pages that drove it were unrouted (D-052, D-057).

```
POST /api/datasets                              register + ingest the five files
POST /api/datasets/{id}/mapping/versions        create a column mapping
POST /api/mappings/{id}/validate                run the structural controls
POST /api/mappings/{id}/confirm                 accept the mapping
POST /api/mappings/{id}/preprocess              -> preprocessing_run_id
POST /api/panel/builds                          -> panel_build_id
POST /api/training                              -> training_run_id
POST /api/models/champions/select               pick a champion per scope
POST /api/forecasts/runs                        refit, quantiles, reconcile
```

Each returns **202** with an id and runs on the background job runner; poll the
matching `GET` for `status` and `progress_pct`. Nothing long-running happens
inside a request handler.

Two of these have a trap worth knowing before you hit it:

- **`champions/select` defaults to every scope kind except `series`.** On a
  49-scope run that selects 9, returns success, and leaves Forecasting serving
  an older run's champions. Pass them explicitly:
  `{"scope_kinds": ["overall","region","branch","value_class","product_group","series"]}`
  (D-084).
- **`forecasts/runs` takes `horizons` as a list**, not a count:
  `{"horizons": [1,2,3,4,5,6], "reconciliation": "mint_shrinkage"}`.

Measured timings on the POC slice — 2 branches, 20 SKUs, 49 scopes:

```
ingestion    ~475 s   streams ~2.6 M rows (docs/API_CONTRACT.md)
training      469 s   833 fits = 17 candidates x 49 scopes
forecast       84 s   294 rows = 49 scopes x 6 months
```

A full-network run is very much larger. `POST /api/training/estimate` returns a
cost projection before you commit to one; it currently runs about **54% high**
on the aggregate tier, which is the safe direction for a warning.

Training can also be started from the **Training** tab once a panel exists.

#### What the pages show before any of this has run

Verified against a fresh clone with an empty database. Nothing is broken here —
these are the honest empty states, each carrying its own remediation:

| Page | Before data |
|---|---|
| Overall Analysis, Per Branch & SKU | `409` — "No completed panel build exists yet. **What to do:** register a dataset, confirm the mapping…" |
| Supply Intelligence | `409` — "No completed preprocessing run exists yet." |
| Training, Forecasting, AI Assistant, AI Recommendations | Render; their data sections stay empty |

`GET /api/health` returns **200** with `status: "error"` and names the component
at fault — `source_data: "data/source is missing."` — so a misconfigured install
is distinguishable from a merely empty one. `model_registry` reports
`13 of 13 models registered` either way.

One thing to know: the frontend reaches the API through **Vite's same-origin
proxy** (`/api` → `127.0.0.1:8000`, in `vite.config.ts`). Pointing
`VITE_API_BASE` at an absolute cross-origin URL instead will fail CORS, and
every page will then claim the backend is unreachable. Change the proxy target,
not the base URL.

### 5. Tests

```bash
powershell -ExecutionPolicy Bypass -File scripts/run_tests.ps1
```

Or individually:

```bash
cd backend && ./.venv/Scripts/python.exe -m pytest
```

```bash
cd frontend && npm run test && npx tsc --noEmit
```

915 backend, 233 frontend. **The tests need no database, no API key and no
`data/source/`** — every model path is exercised against a stub — so a clone
can verify itself before any client file arrives. That is the fastest way to
confirm an install is sound.

Measured on a fresh clone of this repository: `setup.ps1` exited 0, then 915
backend tests passed in 78 s and 233 frontend tests in 15 s, with `backend/.env`
copied straight from the example and `OPENAI_API_KEY` left blank.

## Layout

```
data/source/     the five client files, read-only, gitignored (see Setup)
docs/            architecture, contracts, model inventory, decisions, validation
backend/
  app/
    api/         thin routers
    schemas/     Pydantic request/response models
    services/    business logic
    repositories/ SQLAlchemy data access
    jobs/        background training runner
    ml/          GENERIC forecasting core — no AIS column name appears here
      registry/  canonical_models.py, the single source of model truth
      adapters/  the 13 ForecastModelAdapter subclasses
    domain/ais/  ISOLATED AIS business rules
  tests/
frontend/src/
  api/           the single HTTP client
  features/      one folder per page; 7 are routed, the rest kept but unrouted
  components/    layout + reusable design system
runtime/         generated: database, MLflow, Parquet, logs (gitignored)
scripts/         setup and start/test helpers
```

## The 13 models

Exactly thirteen, registered once, in a fixed order, asserted at startup:

`sarimax`, `sarimax_exog`, `auto_arima`, `auto_arima_exog`, `xgboost`,
`xgboost_exog`, `exp_additive`, `exp_additive_damped`, `exp_multiplicative`,
`exp_multiplicative_damped`, `var`, `var_exog`, `lstm`.

Verified against the actual source of both reference projects, not their
documentation — `docs/MODEL_INVENTORY.md` cites the file and line for every
decision.

`naive`, `seasonal_naive`, `ma3` and `ma6` exist as **non-registry baselines**:
reported for comparison, used as the MASE denominator, never counted among the
13 and never eligible to be champion. q80/q90/q95 are **forecast outputs**
calibrated from out-of-sample residuals, not extra models.

### Six models are legitimately Ineligible at monthly grain

Measured, not assumed. The hybrid panel spans 28 monthly periods; a 6-month
holdout leaves at most 22 training rows; `auto_arima` and the four
exponential-smoothing variants need 24. There is no origin in this dataset
where those six are eligible with a 6-month validation window.

The default `reference` profile reports them as **Ineligible** with the exact
unmet requirement and its remediation — they stay on the leaderboard.
Setting `AIS_MIN_HISTORY_PROFILE=monthly_relaxed` is a documented, clearly
labelled deviation that lets all 13 be compared. See
`docs/DECISIONS.md` D-001.

## Data honesty rules

These are enforced by tests, not just documented:

- Ordered quantity is the target; `sales_proxy` is a **labelled** substitute,
  never described as equivalent.
- Net shortfall (468,431) and gross positive shortfall (504,298) are reported
  **separately** — 9,498 lines were over-despatched, so they differ by 7.6%.
- `true_zero`, `missing_data`, `zero_stock`, `not_applicable`,
  `model_ineligible`, `model_failed` and `out_of_budget` are seven distinct
  states, never collapsed.
- An ineligible or failed model never disappears from the leaderboard and is
  never replaced by a zero forecast.
- No GSTIN, PAN, customer name, email, mobile or address reaches the modelling
  panel or any API payload.
- Inventory recommendations are labelled **current-snapshot estimates**: the
  stock file is one snapshot dated 1 Aug 2026 while sales end Mar 2026, so no
  historical inventory-policy backtest is claimed.
- The frontend performs **no** forecasting arithmetic and carries **no** second
  model registry.

## Reference projects

`D:\OXEA`, `D:\Meriton forecast` and `D:\Labour_AI forecast` are **read-only**.
Nothing in this project edits, formats, moves, deletes, renames, installs into,
or creates files inside them.

## Documentation

| Document | Contents |
|---|---|
| `docs/ARCHITECTURE.md` | Topology, boundaries, hierarchy, measured training budget |
| `docs/API_CONTRACT.md` | Every endpoint, conventions, error contract |
| `docs/DATA_CONTRACT.md` | Source files, 16 cleaning rules, panel schema, features |
| `docs/MODEL_INVENTORY.md` | The 13 models with file/line citations and per-model decisions |
| `docs/AIS_DOMAIN_RULES.md` | Demand target, service measures, inventory maths, PII |
| `docs/DECISIONS.md` | Every decision with its evidence and what was rejected |
| `docs/VALIDATION_REPORT.md` | Controls reproduced from source, leakage and coherence verification, defect register |
| `docs/STATUS.md` | Phase-by-phase record with the actual test output and measured figures |

## Known limitations

Stated here rather than buried:

- **The pooled tier has never been run end to end.** Full-network series-level
  scoring is the one operational claim not yet demonstrated; every measurement
  above comes from the aggregate and local tiers.
- **Error deterioration has never been measured.** The forecast origin is the
  last observed month, so no forecast period has an actual to compare against.
  `GET /api/monitoring` returns `computable: false` with that reason rather
  than a reassuring zero.
- **Quantile intervals rest on 12 residuals per scope**, below the 19 a
  conformal q95 order statistic needs, so they are labelled `empirical` rather
  than `conformal`. More origins would widen and firm them.
- **No lint has run.** `ruff` is configured but not installed.

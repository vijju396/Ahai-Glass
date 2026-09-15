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

## Quick start

One-time setup:

```bash
powershell -ExecutionPolicy Bypass -File scripts/setup.ps1
```

Then, in two terminals:

```bash
powershell -ExecutionPolicy Bypass -File scripts/start_backend.ps1
```

```bash
powershell -ExecutionPolicy Bypass -File scripts/start_frontend.ps1
```

- App — http://localhost:5173
- API docs — http://127.0.0.1:8000/api/docs
- Health — http://127.0.0.1:8000/api/health

Tests:

```bash
powershell -ExecutionPolicy Bypass -File scripts/run_tests.ps1
```

Or individually:

```bash
cd backend && ./.venv/Scripts/python.exe -m pytest
```

```bash
cd frontend && npm run test
```

## Layout

```
data/source/     the five client files, read-only, never modified
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
  features/      ten pages, one folder each
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

# ARCHITECTURE.md

**Status: locked in Phase 1.**

## 1. Pattern: modular monolith with in-process background workers

One FastAPI application plus a thread-pool job runner, over SQLite. There is no
Redis, no Celery, and no container: none was asked for, and inventing that
infrastructure for a POC would add operational surface without adding
capability at this cadence.

```text
React 18 + TypeScript (strict) + Vite            localhost:5173
        |
        |  REST /api  (proxied in dev, so CORS stays narrow)
        |  SSE for training progress
        v
FastAPI + uvicorn                                localhost:8000
  api/routes/       thin handlers, Pydantic in and out
  schemas/          explicit request/response models
  services/         business logic, framework-agnostic
  repositories/     SQLAlchemy data access, engine-agnostic
  jobs/             thread-pool runner, cancellation tokens, progress
  ml/               GENERIC forecasting core - no AIS column name appears here
    registry/       canonical_models.py + model_registry.py
    adapters/       the 13 ForecastModelAdapter subclasses
    legacy_models/  fit logic ported from Meriton/Sodexo
    features/       leakage-safe feature builder
    evaluation/     rolling-origin folds, metrics, quantile calibration
    reconciliation/ MinT variants and documented fallbacks
    selection/      deterministic champion ranking, database-free
  domain/ais/       ISOLATED AIS business layer
                    (incl. inventory.py - the order-up-to policy)
        |
        +-------------------+-------------------+
        v                   v                   v
   SQLite (WAL)          MLflow            Parquet + manifest
   runtime/db/ais.db     runtime/mlflow    runtime/storage/prepared
```

Compared with the references: this mirrors **Sodexo's** FastAPI/React topology
(the closer structural precedent — Meriton is a Flask/Jinja monolith) and
**Sodexo's** relational persistence pattern (`TrainingJob`, `ModelRun`,
`ModelPrediction`), which is materially safer than Meriton's flat JSON files
under session UUIDs. It replaces both references' single-global-lock daemon
thread with a bounded worker pool, a real jobs table, and cancellation.

### Service inventory, as built

| Service | Owns |
|---|---|
| `dataset_service` | ingestion, profiling, structural controls |
| `mapping_service` | column roles, rules, confirmation gate, preprocessing |
| `panel_service` | the monthly panel and its feature frames |
| `training/training_service` | tier orchestration, per-model rows, budget |
| `champion_service` | leaderboard assembly, selection, override, rollback, diagnostics |
| `forecast_service` | champion refit, calibration, reconciliation, persistence |
| `inventory_service` | recommendations, placement measures, holdings |
| `monitoring_service` | freshness, drift, champion age, error deterioration |
| `scenario_service` | read-only what-if over a stored forecast |
| `export_service` | CSV of exactly what a page displays |

Six tables carry the modelling record, all append-only in the sense that matters
— a re-run is a new row, never an overwrite: `training_run`, `model_run`,
`quantile_calibration`, `champion_selection`, `forecast_run`, `forecast_row`.
`champion_selection` additionally supersedes rather than updates, so the audit
history *is* the table.

## 2. Why SQLite, and how PostgreSQL replaces it

The modelling panel is roughly 1.5 M rows / ~35 MB. That is not big data, and
the usual justifications for a distributed engine or a lake apply to none of
it. SQLite with WAL handles it comfortably and needs no server process.

PostgreSQL readiness is a real constraint on the code, not an aspiration:

- Every table is defined with portable SQLAlchemy types — no SQLite-only
  affinity tricks, no `AUTOINCREMENT`, no `rowid` dependence.
- All schema changes go through Alembic.
- The only engine-conditional code in the tree is
  `app/db/session.py`, which applies SQLite `PRAGMA`s behind an
  `if _is_sqlite` guard.
- Switching engines is setting `AIS_DATABASE_URL` to a PostgreSQL DSN.
- Analytical scans read Parquet, not the database, so no engine-specific
  window-function or `COPY` behaviour is relied on.

## 3. Architectural boundaries (non-negotiable)

- **`app/ml/` and generic `app/services/` must not reference a single AIS
  column name.** No `branch`, no `oracle_no`, no `despatch_qty`. They operate
  on the canonical schema below. A test greps for AIS-specific literals in
  those packages.
- **`app/domain/ais/` is the only place AIS business rules live** — shortfall,
  censoring, days of cover, order-up-to, transferable stock, ABC routing.
- **The frontend never computes a forecast, a quantile, or an order quantity.**
  React formats what the API returns. `no-duplicate-registry.test.ts` enforces
  both this and the single-registry rule.
- **No long-running work in the request cycle.** Training and forecast
  generation return a job ID immediately; progress is polled or streamed.

## 4. Canonical prepared schema

Generic, dataset-agnostic, following the convention both references converge on
(`date` / `target` / dimension / exogenous):

```text
period_start              month start, UTC-normalised
series_id                 canonical_branch | canonical_sku
target                    float - ordered quantity
target_source             order | sales_proxy
is_censored               bool - ordered demand was not fully served
value_unavailable_reason  true_zero | missing_data | zero_stock | not_applicable
static_attribute_*        constant per series: branch, region, zone, hub, tier,
                          product group/sub-group, vehicle category,
                          vehicle-age category, glass type, OEM status
historical_driver_*        known only up to now: despatched_qty, shortfall_qty,
                          mrp (price changes, so never future-known)
future_known_driver_*      genuinely known ahead: calendar month, horizon step,
                          the static attributes above
```

The `historical_driver_*` / `future_known_driver_*` split is structural
precisely so a historical-only driver can never be silently used as a
future-known regressor — the failure Meriton raises as
`FutureExogenousUnavailable`, caught here at mapping-confirmation time
instead.

## 5. Hierarchy and reconciliation

```text
branch x SKU  (63,210)  ->  branch (51)  ->  region (6)  ->  national (1)
```

**Full-covariance MinT is not computable at the base level.** A 63,210 x 63,210
covariance matrix is roughly 32 GB in float64 and would be estimated from at
most 28 observations. So:

| Level | Method | Why |
|---|---|---|
| base -> branch | MinT with **variance (WLS) scaling** — diagonal only | Tractable at 63,210 series; a documented MinT variant, not an invention |
| branch -> region -> national | **MinT with shrinkage covariance** | A 51 x 51 matrix is estimable with shrinkage |
| fallback | bottom-up, or proportional top-down | Used when the covariance estimate is unstable; which one ran is recorded per forecast row |

Non-negativity is enforced, the reconciliation adjustment is stored and
displayed rather than folded silently into the number, and point/quantile
ordering is re-checked after reconciliation.

## 6. Training budget — measured, not assumed

Measured single-fit times on the real 24-month AIS national series:
`sarimax` 0.06 s, `auto_arima` 0.47 s, `xgboost` grid 0.32 s / fast 0.014 s,
`var` 0.01 s, `lstm` 5.75 s.

A naive "all 13 models on all 63,210 series" run costs **≳130 hours** (LSTM
alone 101 h, `auto_arima` 16.5 h). That is not operationally reasonable, so
training is tiered:

| Tier | Scope | Models | Measured |
|---|---|---|---|
| **Aggregate** | 1 national + 6 regions + 51 branches + segments ≈ 63 series | **all 13**, full rolling-origin CV | ~10 min |
| **High-value local** | top `max_local_series` (default 500, ~30% of units) | **all 13**, expensive-model holdout policy | ~1.1 h |
| **Full network** | all 63,210 series x 6 horizons | pooled global `xgboost`/`xgboost_exog` + 3 quantiles | **~2 min** |
| **Cold start / sparse** | remainder | attribute-based routing from the pooled model | included |

Pooled global XGBoost measured at real shape (950,000 rows x 29 features, 300
trees, 8 threads): **21.5 s** to fit, **0.3 s** to score 380,000 rows. Point
plus three quantiles is ~86 s fit and ~1.2 s score.

Rules that make this honest:

- Every series records **which models actually evaluated it**.
- Anything outside a tier's budget is `not_evaluated_budget` — never a zero
  forecast, never omitted from the leaderboard.
- The estimated cost is shown before a run can be submitted.
- Per-model timeouts (`per_model_timeout_seconds`, `lstm_timeout_seconds`)
  produce `timed_out` for that model and never abort the run.

## 7. Backtesting

Chronological only. Random splitting is not implemented anywhere.

- **Primary origin (mandated):** train through **Sep 2025**, validate
  **Oct 2025 – Mar 2026**, six horizons, no retraining between them.
- **Second origin:** train through Jan 2026, validate Feb – Jul 2026 — available
  because the hybrid panel extends to Jul 2026 on order data.
- Standard models use three expanding-window folds where history permits.
- `auto_arima`, `auto_arima_exog` and `lstm` use a **single chronological
  holdout** sized to the same total test rows the folds would consume
  (Sodexo's `holdout_size`), so their `validation_points` stay comparable. The
  leaderboard labels the difference and never blends metrics across modes.
- Imputation, scaling, encoding, feature selection and hyperparameter tuning
  are fitted **independently inside every fold**.

## 8. Observability

Structured JSON logs, one line per event, with a correlation ID that travels
from the HTTP request into the job runner. Stack traces, file paths and
connection strings stay server-side; clients get a stable error code plus the
correlation ID. MLflow records params, metrics and artifacts per model run.

## 9. Deliberately not included

- **Redis / Celery** — not requested; a bounded thread pool with a jobs table
  fits a monthly-cadence POC.
- **Docker / Kubernetes / cloud** — not requested. Plain local processes.
- **A data lake or medallion layering** — at ~35 MB that is three schemas and
  one Parquet file, not a platform.
- **Real-time serving endpoints** — the forecast is monthly batch.
- **GPU** — nothing in the 13 requires one; TF runs CPU-only.
- **Croston / SBA / TSB** — proposed by the HTML analysis, but outside the
  verified 13. Not implemented.

## 10. Where AIS intentionally differs from Meriton / Sodexo / Oxea

Recorded in full in `docs/DECISIONS.md`; summarised here.

| Driver | Consequence |
|---|---|
| **Monthly**, not daily or hourly | Seasonal period 12 needs 24 rows for two cycles; the panel offers 22. Six of 13 models are legitimately `Ineligible` under reference thresholds. |
| **63,210 series**, not 1 or 4 | Sodexo runs all 13 on all series only because it hardcodes 4. AIS needs the tiered budget in §6 and pooled global training. |
| **Intermittent demand** (62% of series) | WAPE replaces MAPE as the primary metric. Multiplicative smoothing is ineligible wherever a zero exists. Legacy lowest-MAPE ranking is retained but separately labelled and frequently undefined. |
| **24-month history** | No deep learning beyond the registered LSTM; no long-horizon architectures; quantile calibration pools across series rather than per series. |
| **Order demand vs sales proxy** | A `target_source` column and a hybrid panel exist, which neither reference needed. |
| **Single stock snapshot** | Inventory recommendations are labelled current-snapshot estimates. No historical inventory-policy backtest is claimed. |
| **No trained-model persistence in either reference** | Real `save`/`load` per adapter plus MLflow — new work, not a port. |

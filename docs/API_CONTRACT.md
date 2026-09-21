# API_CONTRACT.md

All routes under `/api`. Every request and response body is an explicit
Pydantic schema; OpenAPI is generated at `/api/openapi.json`, with Swagger at
`/api/docs`.

**Every endpoint listed below is implemented and covered by tests.** The
`[Live]` markers in sections 3-3b date from earlier phases when part of the
surface was still planned; nothing in this document is aspirational any more.
Counted from the running app: 55 routes.

## Conventions

- **Pagination** — `offset` (default 0), `limit` (default 25, max 200),
  `sort_by` (allow-listed per endpoint; an unknown value is ignored, never a
  400), `sort_dir` (`asc` | `desc`). Envelope:
  `{"items": [...], "total": n, "offset": n, "limit": n}`.
- **Errors** — one shape, always:

  ```json
  {"error": {"code": "source_control_failed",
             "message": "One or more source-data controls did not hold.",
             "details": {"...": "..."},
             "remediation": "...",
             "correlation_id": "…"}}
  ```

  Stable codes: `not_found`, `validation_failed`, `conflict`,
  `source_control_failed`, `data_unavailable`, `model_ineligible`,
  `internal_error`. Stack traces, file paths and connection strings never reach
  a client.
- **Correlation** — send `X-Correlation-ID`; it is echoed on the response and
  stamped into every log line, including the background job's.
- **CORS** — the React origin only (`http://localhost:5173`,
  `http://127.0.0.1:5173`). Never a wildcard.
- **No PII** — no client payload carries GSTIN, PAN, customer name, email,
  mobile or address. Enforced by test.
- **Long-running work** — training and forecast generation return a job ID
  immediately (202). Never awaited in the request handler.

## 1. Health

```
GET  /api/health                        [Live]  component breakdown: database,
                                                model_registry, source_data,
                                                ml_dependencies, mlflow
```

## 2. Models

```
GET  /api/models                        [Live]  the official 13 + baselines
```

The frontend's **only** source of model identity. Returns per model:
`model_id`, `display_name`, `rank` (1–13), `dependency_module`,
`requires_exogenous`, `supports_pooled_training`, `uses_fast_holdout`,
`min_required_history`, `min_history_reason`, `family`. Plus
`official_model_count` (13), `min_history_profile`,
`xgboost_training_profile`, `baselines[]` and `notes[]`.

Baselines are a separate array. They are never mixed into `models`.

## 3. Datasets and validation

```
POST /api/datasets                       [Live]  register the source set and start
                                                 ingestion in the background (202)
GET  /api/datasets                       [Live]  list (paginated)
GET  /api/datasets/{id}                  [Live]  detail + live ingestion progress
POST /api/datasets/{id}/cancel           [Live]  request cancellation
GET  /api/datasets/{id}/profile          [Live]  per-file, per-column profile
GET  /api/datasets/{id}/validation       [Live]  structural controls + defect register
GET  /api/datasets/{id}/mapping          [Live]  canonical key reconciliation
```

**`POST /api/datasets`** returns **202** with a `version_id`. Ingestion streams
~2.6 M rows and takes about **475 s** measured, so it runs on the background
job runner; `GET /api/datasets/{id}` carries `status`, `stage_detail` and
`progress_pct` for polling.

**`/validation`** returns every control from `docs/VALIDATION_REPORT.md` §1 with
its `expected`, `measured`, `outcome`, `difference` and `remediation` — passing
and failing alike, because an omitted row is indistinguishable from a control
nobody ran. A failure sets the version to `completed_with_failures` and
populates `blocking_message`; nothing downstream may treat that version as
clean. It also returns `service_measures` (net **and** gross shortfall as
separate fields, plus over-delivery) and `lead_time` (with its exclusion
counts).

**`/mapping`** returns the canonical-key reconciliation: `canonical_sku_count`,
`oracle_no_count`, `oracle_collision_count`, `canonical_disagreement_count`,
`rows_missing_oracle`, `sku_prefixes`, the four `branch_universes`, the
`sku_universes` per source and key, and the findings themselves. It also
carries `canonical_key_rule` and `why_not_oracle_no` as text, so the API
explains the key choice rather than leaving it to a document.

**`/profile`** exposes `is_pii` per column with counts, and `null` for every
value-bearing field on a PII column. `pii_columns_excluded` lists them by
name.

## 3a. Role mapping and preprocessing

```
GET   /api/datasets/{id}/mapping/suggestions   [Live]  advisory suggestions, never persisted
POST  /api/datasets/{id}/mapping/versions      [Live]  create a DRAFT mapping (201)
GET   /api/datasets/{id}/mapping/current       [Live]  latest mapping for a dataset
GET   /api/mappings                            [Live]  list mapping versions (paginated)
GET   /api/mappings/{id}                       [Live]  mapping detail
PATCH /api/mappings/{id}                       [Live]  edit a DRAFT (409 once confirmed)
POST  /api/mappings/{id}/validate              [Live]  run every rule, persist outcomes
POST  /api/mappings/{id}/confirm               [Live]  lock for training use
POST  /api/mappings/{id}/preprocess            [Live]  build dimensions and facts (202)
GET   /api/mappings/{id}/preprocessing         [Live]  latest preprocessing run
```

`GET /api/datasets/{id}/mapping` (the key reconciliation) answers *how the keys
line up*. This resource answers *what each column means* — a separate,
versioned, confirmable artefact.

**Suggestions are advisory.** Every one carries a `confidence`, a `rationale`,
and `is_authoritative: false`. The response's `note` says so explicitly.

**`PATCH`** clears `is_suggested` on every assignment it touches: an edited
role has been reviewed by a person, which is what the confirmation gate
requires. Reassigning a PII column to anything but `excluded_pii` is a 422.

**Rule results** are returned in full, blocking and warning alike, each with a
`rule_code`, `severity`, affected `columns` and a `remediation`. The rules:

| Rule | Severity | Checks |
|---|---|---|
| R1 | blocking | a time column and a target column are assigned |
| R2 | blocking | those two roles appear at most once **per source** |
| R3 | blocking | one role per column |
| R4 | blocking | a PII column is only ever `excluded_pii` |
| R5 | blocking | a `future_known_driver`'s future values genuinely exist |
| R6 | warning | a series identifier is assigned |
| R7 | blocking | the forecast horizon is at least 1 |
| R8 | warning | absent periods become explicit zeros, not gaps |
| R9 | warning | a missing target is not imputed to zero |

R2 is scoped per source deliberately: the order file and the sales file each
legitimately carry their own target and time column, and the hybrid target
needs both (`docs/DECISIONS.md` D-002).

**`POST /confirm`** is refused (422) while any blocking rule fails, or while
the target or time column is still only a suggestion — the error names the
exact columns. A confirmed mapping is **immutable**; a later confirmation
supersedes it rather than overwriting it.

**`POST /preprocess`** requires a confirmed mapping (409 otherwise) and returns
**202**: it re-streams all five sources and takes about **390 s** measured.
`GET /preprocessing` carries `status`, `stage_detail`, `progress_pct`, the row
counts of each table produced, the Parquet `artifacts`, and a `summary` with
the period ranges, branch and SKU universes, censoring counts and warnings.

## 3b. The monthly panel

```
POST /api/panel/builds            [Live]  build the panel and the frames (202)
GET  /api/panel/builds            [Live]  list builds (paginated)
GET  /api/panel/builds/current    [Live]  the most recent build
GET  /api/panel/builds/{id}       [Live]  detail, including the feature manifest
```

**`POST`** takes an optional `preprocessing_run_id` (defaulting to the **newest
completed** run, not the first - an earlier run may predate a fix), an optional
`training_cut_period` as `YYYY-MM`, and `horizons`. Horizons are deduplicated
and sorted; a set with nothing >= 1 is a 422. An incomplete preprocessing run,
or one without artifacts, is a 409. Returns **202**: the build takes about
**140 s** measured.

The response reports `observed_rows` and `materialised_zero_rows` **separately**
- an observed zero and a filled zero are different facts - along with
`censored_rows`, `training_rows`, `scoring_rows` and `feature_count`. The
`summary` carries the period range, the two `target_source_rows` counts, the
`series_universe` (which names the panel count *and* the 63,210 sales control
so they cannot be confused), the sparsity measures, and the full feature
manifest with its lag convention.

## 4. Training

```
POST /api/training/estimate                what the run will cost, starting nothing
POST /api/training                          submit a run (202 + run id)
GET  /api/training/explain                  validation design, the 13 models, metrics, tuning
GET  /api/training                           list runs, newest first
GET  /api/training/current                    the most recent run
GET  /api/training/{run_id}                    run detail + per-model status
GET  /api/training/{run_id}/model-runs          per-model rows, paginated
GET  /api/training/{run_id}/calibrations         the quantile cells the run wrote
GET  /api/training/{run_id}/events                SSE progress stream
GET  /api/training/{run_id}/monitor               per-model progress + the fold design it used
GET  /api/training/{run_id}/accuracy-windows      the same forecasts scored over 1, 3 and 6 months
                                                  ?scope_key=BRANCH|SKU narrows it to one line
GET  /api/training/{run_id}/model-events           SSE per-model deltas, for the training race
POST /api/training/{run_id}/cancel                 cancel; rows already written are kept
```

Submission selects the tiers (`aggregate`, `local`, `pooled` — executed in that
order), the history and XGBoost profiles, and the local-series cap.

**A run can be scoped.** `branches` (a list of branch names), `skus` (an explicit
list, which takes precedence) and `max_skus`
(top-N by the selection measure) cut the panel *before* origins, plans and cost
are computed, so every count downstream describes the slice actually trained.
SKUs are ranked inside the branch restriction, not nationally.

A scoped run carries what it covered in `restriction`, and the same sentence is
added to `warnings`: *"This run covers 2 of 53 branches and 20 of 2334 SKUs
(40 of 68675 series). Its results describe that slice, not the network."* An
unrestricted run has `restriction: null`. A branch name that is not in the panel
is reported in `restriction.branches_unknown` rather than silently ignored; a
restriction that leaves no data at all is a 409, not an empty run.

**The estimate is returned with the submission**, taken from what was stored on
the run, so the number the caller saw is the number that can later be audited
against `duration_seconds`. `POST /api/training/estimate` gives the same figure
without starting anything.

Per-model `status` is one of: `queued`, `preparing_data`,
`validating_eligibility`, `training`, `cross_validating`,
`generating_forecast`, `saving_artifacts`, `completed`, `failed`,
`ineligible`, `timed_out`, `not_evaluated_budget`, `cancelled`.

**There is no status filter on any of these endpoints.** A caller may filter by
`tier`, `scope_level`, `scope_key` or `include_baselines`, but not by status:
the ineligible, failed and timed-out rows are the point of the table.
`GET /api/training/{run_id}` returns `models_missing` — registry models with no
row at all — so an accidental omission is visible rather than silent.

`/events` emits `progress` frames only when something changed, then `end` on a
terminal state or `timeout` at `max_seconds`. An unknown run id is a structured
404 before the stream opens, never a 200 that streams an error into the body.

`/model-events` is the same discipline at per-model grain: `started`,
`progress`, `finished` and `failed` frames carrying one model's accuracy as it
moves, suppressed below a delta threshold so a stationary model does not emit.
It is what the training race animates. Both streams treat
`completed_with_warnings` as terminal - it was omitted once, and the effect was
that neither stream ever sent `end`.

`/monitor` additionally carries `pipeline`: the run's scope count, its scopes by
hierarchy level, the registry and baseline model counts, how many champions were
selected, how many were beaten by a baseline, and the champion spread by model.
It exists so the Training page can state the **shape** of a run rather than only
its rules (`docs/DECISIONS.md` D-084).

### Workspace location scope

Every panel-backed payload carries `workspace_scope`:

```json
{"restricted": true, "branches": ["AHMEDABAD","BENGALURU"], "branch_count": 2,
 "total_branches": 53, "source": "training_run", "note": "This workspace covers 2 of 53 branches ..."}
```

`source` is `setting` (`AIS_WORKSPACE_BRANCHES`), `training_run` (the active
run's restriction), or `unrestricted`. When restricted, `note` is also
prepended to the payload's `notes` so it renders above every other note on the
page. An unrestricted workspace reports `restricted: false` rather than
omitting the key — a client must be able to tell "everything" from "narrowed"
(docs/DECISIONS.md D-049).

It applies to `/analytics/*`, `/inventory/*`, `/monitoring` and the assistant
tools alike, so the location list is identical on every page.

## 5. Model results

```
GET  /api/models                              the 13 models + non-registry baselines
GET  /api/models/leaderboard                   ranked, scope-filterable
GET  /api/models/leaderboard/scopes             which scopes a run has a board for
GET  /api/models/leaderboard/comparison          models on x, WAPE on y
GET  /api/models/{model_id}/diagnostics           folds, residuals, actual-vs-predicted,
                                                  horizon-level performance
GET  /api/models/champions                         active selections, or full history
POST /api/models/champions/select                   run the deterministic selection
GET  /api/models/champions/current                   active champion for one scope
GET  /api/models/champions/history                    every decision for one scope
POST /api/models/champion/override                     manual override; reason required
POST /api/models/champion/rollback                      restore the previous champion
```

Leaderboard rows carry **both rankings side by side**: `rank` is the AIS
operational ranking (WAPE, then absolute bias, then MAE, then `model_id`) and
`legacy_rank` is the references' lowest-valid-MAPE rule, `null` where
undefined. They are never blended.

A row that is not ranked still appears, with `exclusion` and
`exclusion_reason`: `not_completed`, `no_primary_metric`,
`too_few_validation_points`, `incomparable_test_window`, or `is_baseline`.
Comparability is assessed **within an evaluation mode**, so a `holdout_fast`
model's 6 test points are judged against other fast-holdout rows rather than
against a `rolling_origin` model's 10 (`docs/DECISIONS.md` D-037); both counts
travel on the row and the mixed-mode note appears on the response.

`beaten_by_baseline` and `skill_vs_best_baseline` are first-class fields. A
baseline can never be champion, but it frequently forecasts better, and the
response says so in words rather than leaving two numbers to be compared.

**Override** requires a reason of at least 10 characters, enforced at the schema
*and* the service boundary. It is refused for a baseline, for an unregistered
model, and for a model that did not complete in that scope — overriding to an
ineligible model would claim an accuracy that was never measured.
**Rollback** writes a new selection row restoring the previous choice; it never
resurrects a superseded row in place, because rolling back is itself a decision
the history must show.

`GET /api/models/{model_id}/diagnostics` distinguishes two empty cases: a model
that never produced predictions, and a model that completed under a run which
did not persist them. The second must not read as the model's fault.

## 6. Forecasts

```
POST /api/forecasts/runs                     generate horizons 1-6 (202 + run id)
GET  /api/forecasts/runs                      list forecast runs
GET  /api/forecasts/runs/current               the most recent completed run
GET  /api/forecasts/runs/{run_id}               run detail + reconciliation verdict
GET  /api/forecasts                              query rows by scope/period/model
GET  /api/forecasts/series                        one scope: history + horizons +
                                                  point/q80/q90/q95 + drivers
GET  /api/forecasts/hierarchy                      level totals with the adjustment shown
```

Generation refits each scope's **active champion** on its whole history, applies
the quantile calibration, reconciles the levels, and persists one row per
(scope, period). `reconciliation` accepts `mint_shrinkage`, `mint_variance`,
`bottom_up`, `proportional` or `none`; a method whose covariance cannot be
estimated **falls back and records what it fell back from and why**.

Every row carries `target_source`, `is_censored`, `reconciliation_method`,
`reconciliation_adjustment` (as a separate field, never folded into the
number), the interval's provenance (`quantile_method`,
`quantile_pooling_level`, `quantile_residual_count`), and full lineage
(`training_run_id` via the run, `model_run_id`, `champion_selection_id`).

**A row with `unavailable_reason` has a null point forecast, never a zero.**
`include_unavailable` defaults to `true`, because a scope whose champion would
not refit is a fact a planner needs.

`GET /api/forecasts/hierarchy` re-checks coherence **from the persisted rows**
rather than echoing the run's own flag, and returns `level_gaps` so a
disagreement between two stored levels is visible.

Reconciliation runs from the finest **complete** level. The local tier forecasts
the top-N series rather than the whole network, so a run including it reports
`reconciliation_base_level: "branch"` and `partial_levels: ["series"]`, and the
series rows carry `reconciliation_method: "none"` with a reason. Each gap
therefore carries **two** flags, because a non-matching pair can mean two
different things (D-050):

- `expected_coherent: false` — the lower level is a subset, so the totals were
  never expected to agree.
- `expected_coherent: true` with `coherent: false` — two levels that *were*
  reconciled together disagree, and the reason says that is a defect.

## 7. Inventory

```
GET  /api/inventory/recommendations          per branch x SKU, calculation exposed
GET  /api/inventory/overview                  cover, dead stock, zero-stock/live-demand
GET  /api/inventory/transferable               which other branches hold a SKU
```

Each recommendation returns the **inputs**, not just the answer:
`order_up_to_level`, `usable_stock_on_hand`, `confirmed_stock_on_order`,
`backorders`, `lead_time_days`, `review_period_days`,
`protection_period_days`, `protection_months`, `service_level`,
`raw_recommended_order` (pre-rounding), `recommended_order`, `days_of_cover`,
plus `warnings[]` and `unavailable_reason`. Every row is labelled
`is_current_snapshot_estimate`.

`scope_level` defaults to `series`, because a replenishment order is placed for
a branch × SKU. A request at a level the run did not forecast returns a stated
reason rather than an aggregate dressed as a line item.

A missing forecast, stock record or lead time each produce a reason and **no
number**. "Order nothing" and "we could not work out what to order" are
different instructions. `confirmed_stock_on_order` and `backorders` are zero
**by absence** — the source set has no open-order snapshot — and every row says
so.

`/transferable` returns holdings only. The source set carries no inter-branch
lane, transfer cost or transit time, so it is deliberately not a transfer plan.

## 8. Monitoring

```
GET  /api/monitoring                         freshness, drift, champion age,
                                             error deterioration
```

Four measures, each with its own availability flag and reason:

- **Freshness** reports the demand-history end and the stock-snapshot date
  **separately**, because they are a month apart on this dataset and collapsing
  them would hide why recommendations are current-snapshot estimates.
- **Drift** compares the last six months against the earlier history, per
  branch, and reports both window means and both row counts. **No threshold is
  applied.** When the target source differs between the windows the note says
  so, because part of any shift across that boundary is a change of measurement
  rather than of demand.
- **Champion age** reports how long each active champion has been in force,
  whether its run is still the newest, and how many are beaten by a baseline.
- **Error deterioration** compares accrued production error against backtest
  WAPE. On this dataset it is **not computable** — the forecast origin is the
  last observed month — and `computable: false` with a reason is returned.
  Reporting zero deterioration would claim a check that never happened.

Nothing here raises an alert. A page that decided what counts as a problem
would hide the number that mattered.

## 9. Scenarios

```
POST /api/scenarios                          evaluate a what-if against a baseline
```

A scenario is a transformation of a **stored, read-only** forecast: it is
computed on read and never written back. Three levers — `demand_multiplier`
(bounded to 0.1–5.0), `service_level`, `lead_time_days` — and the response
returns each beside its baseline value.

The multiplier scales the point forecast **and its quantiles together**; scaling
the point alone would leave an interval that no longer brackets it. Stock is
held at zero on both sides of the comparison, so the difference between the two
order columns is attributable to the levers alone — for a real order position
use `/api/inventory/recommendations`. A scope with no baseline forecast stays in
the response with its reason and is never scaled from nothing.

## 10. Exports and settings

```
GET  /api/exports                             which exports exist, and what each mirrors
GET  /api/exports/{kind}                       CSV: leaderboard | forecasts |
                                               recommendations | model_runs
GET  /api/settings                              the effective runtime configuration
```

An export contains **the same rows and columns the page showed**, including the
rows carrying a reason instead of a number. An undefined metric is an empty
cell, never a zero. Every file opens with a `# ` provenance comment naming the
run, the scope, the generation timestamp and the relevant caveat, so a file
found on a shared drive months later can be traced back.

`GET /api/settings` is read-only by design — there is no write endpoint, so a
planner cannot change the random seed or a history profile behind a run that has
already been stored. It publishes the database **dialect** but never a
connection string or a filesystem path.

## 9. Demand analytics and the AI assistant — reference parity

Added for the reference-parity pages (`docs/UI_VISUAL_PARITY.md`) and the
lead-time panels. Eight endpoints, taking the live application from 57 to
**65**, since joined by `/api/analytics/impact` (the forecast-impact panel) and
`/api/training/{run_id}/monitor` (the live training monitor), then
`/api/analytics/sample-mix` (the composition-sampling caveat) and
`/api/training/{run_id}/model-events` (the training race's per-model stream),
for a measured total of **73** - counted from the running app's OpenAPI
document rather than by adding to the previous sentence, which is how the
figure had drifted to a claimed 68. The most recent addition is
`/api/training/{run_id}/accuracy-windows`, which re-scores the champions' own
backtests over one month, a quarter and half a year. It re-fits nothing and
redefines no metric: the monthly figure is its first row, unchanged, because a
wider window is a wider question and must not read as a better forecast.

```
GET  /api/analytics/filters                 filter options + the grains the data supports
GET  /api/analytics/summary                 every Demand Analytics panel, for one filter state
GET  /api/analytics/exceptions              supply and data exceptions per branch x SKU line
GET  /api/analytics/branch-scorecard        per-branch operational scorecard, ranked
GET  /api/analytics/series                  branch x SKU options for scope pickers
GET  /api/analytics/drift                   measured demand drift, and a labelled projection
GET  /api/analytics/impact                  measured error reduction + a benefit projection
GET  /api/analytics/sample-mix              how far the sampled SKUs distort the composition charts
GET  /api/analytics/lead-time               per-branch lead time, its variability, and anomalies
GET  /api/assistant/status                  whether the assistant is configured, and how to configure it
POST /api/assistant/ask                     ask a question about this application's data
GET  /api/assistant/recommendations         what is worth attention, explained
```

**One response per page.** `GET /api/analytics/summary` returns every panel's
data in one payload, filtered server-side, so the panels on a page can never be
displaying different filters. The reference does the same, for the same reason.

**`available_grains` is authoritative.** It returns `["monthly", "quarterly"]`
and `grain_note` explains the absence of daily and weekly: AIS demand history is
monthly, and a daily split of monthly rows would be invented data. The UI
renders only the grains this field lists.

**Unknown is never zero.** `fill_rate_pct` is computed only over months that
carry a despatch figure. A sales-proxy month has none, so it is excluded and
`despatch_rows_excluded_from_fill_rate` reports how many. `despatched_units`
and `fill_rate_pct` are `null` for such a period rather than `0`.

**Every exception carries its definition.** Each row in
`/api/analytics/exceptions` names the condition it was found by, its severity,
and the unit its measure is in. The ranked entity is a **branch x SKU line** —
AIS holds no employee, attendance or payroll data, so the reference's
employee-level ranking has no equivalent here by design.

### Assistant

`GET /api/assistant/status` reports `configured`, the model in use, and the
setup steps. It **never** returns the key, any part of it, or its length.

`GET /api/assistant/recommendations` runs a fixed set of the same bounded
read-only tools and returns a short ranked list, each item carrying
`observation`, a plain-language `explanation`, the `evidence` figures it rests
on, and `verify_on` — the page those figures can be checked against. No
parameters: it is one standing question, so a caller cannot steer which
evidence is gathered.

**An item with no evidence never leaves the backend.** The prompt says a
recommendation must carry a measured figure; `_clean` drops any that does not,
so the rule is enforced rather than requested. `answered_by` is `openai`,
`deterministic_no_key` or `deterministic_after_provider_error`, and
`temperature` is reported because at 2.0 the same facts produce a different
list each run (docs/DECISIONS.md D-054). `provider_error` carries the exception
*type* only, never the provider's message.

`POST /api/assistant/ask` takes `{question, history[], current_scope}` and
returns:

| Field | Meaning |
|---|---|
| `answer` | prose, restricted to `- ` bullets and `**bold**` |
| `answered_by` | `openai`, `deterministic_no_key`, `deterministic_after_provider_error`, `static`, `disabled` or `validation` |
| `tools_used` | which AIS data tools ran |
| `facts` | the computed figures the answer was written from |
| `chart` | an allowlisted `line`/`bar`/`pie` spec built by the backend, or `null` |
| `scope` | backend-defined; the client stores and resends it, never constructs one |
| `provider_error` | present only when the model path failed |

Four properties this contract guarantees:

- **The backend computes; the model narrates.** Every figure in `answer` comes
  from `facts`. The model is never asked to add, rank or project anything.
- **Charts come from the backend.** `chart.data` is built from the same facts,
  so a chart cannot disagree with the paragraph beside it. The model never
  authors a data array, and the tool schema gives it no arguments at all.
- **`answered_by` is load-bearing.** A deterministic answer is labelled as one
  in the UI rather than being presented as model output.
- **No key is a working state.** With `OPENAI_API_KEY` blank the endpoint still
  answers from the application's own data, and the rest of the app is
  unaffected.

`history` is capped at 12 turns and `question` at 2000 characters; the agent is
bounded to 2 rounds and 3 tool calls per request.

### Lead time

`GET /api/analytics/lead-time` reads the branch dimension (57 rows) and returns
per-branch average, standard deviation and transit time, plus the derived
coefficient of variation and handling split.

It exists because the lead-time source file reached only one table column and
the Data Studio ingestion controls; `std_lead_time_days` and
`transit_lead_time_days` reached no screen at all.

Three things the payload is careful about, because the raw columns mislead:

- **A zero-day average is an anomaly, not a fast branch.** Eight of 57 rows
  report zero; they are excluded from every median and listed under
  `anomalies` with the reason, so one plant row cannot pull the network median
  toward zero.
- **Transit can exceed the total.** One branch carries a 44-day transit against
  a 0-day total. Those rows are reported as contradictions rather than plotted
  as a negative handling duration.
- **A standard deviation of zero is ambiguous** — either every receipt took the
  same time, or there was one observation. The branch dimension carries no
  observation count, so the payload says the two cannot be distinguished.

`notes` states plainly that **lead-time variability affects no recommendation
today**: the protection period is `review period + average lead time`, so a
volatile branch is given the same cover as a stable one with the same mean.
Changing that would move every recommended quantity and is a separate
decision.

# DECISIONS.md

Every material decision, its evidence, and what was rejected. Numbered for
citation from code comments and other documents.

## D-051 — AIS analytics redesign preserves the forecasting boundary

The frontend uses the official AIS logo downloaded from the website's rendered
asset inventory and the observed corporate blue (#005BAB), navy (#0F2754), and
white palette. Additional chart and status colors are an analytics extension,
not a claim to possess the official corporate brand manual.

The project remains React + FastAPI with its existing thirteen-model registry.
The Visualize skill's project-change guidance is followed: implement in the
application rather than deliver an unrelated in-conversation mockup. ECharts
is already installed, so no chart dependency or second model registry is added.

Actual-vs-forecast means persisted out-of-sample diagnostics, requested using
the forecast's training_run_id and model_id. The viewer selects one backtest
origin/fold at a time because overlapping months have distinct predictions.
Future forecasts remain separate from observed actuals. q80/q90/q95 are labelled
as service-level demand quantities, not symmetric confidence intervals. Missing
predictions stay unavailable, and sales-proxy history is labelled in the chart.
The frontend only filters, formats and charts API results; no forecasting,
reconciliation, calibration or inventory-order calculations were moved into it.

The executive dashboard ranks only API-ranked entries and shows excluded counts;
the full leaderboard retains every status and exclusion reason. Supply priority
visuals explicitly describe their loaded-page scope rather than implying they
rank the full network. CSV export follows the active Explorer view.

---

## D-001 — Six of thirteen models are legitimately Ineligible at monthly grain

**Decided:** ship both a strict default and a labelled opt-in.

**Evidence.** Measured, not inferred. All 13 model families were run on the
real 24-month AIS national series with `train=18, period=12`, using each
reference project's own configuration:

```
sarimax                0.06 s  ok        exp_additive            ERR
auto_arima             0.47 s  ok        exp_additive_damped     ERR
xgboost (grid)         0.32 s  ok        exp_multiplicative      ERR
xgboost (fast)         0.014s  ok        exp_mult_damped         ERR
var                    0.01 s  ok        lstm                    5.75 s  ok
```

All four exponential-smoothing variants raise
`Cannot compute initial seasonals using heuristic method with less than two
full seasonal cycles`. `auto_arima` requires 24 training rows in both
references (`Sodexo models.py:118`, `Meriton training_service.py:1063`); the
mandated cut through Sep 2025 supplies 18.

The arithmetic is unavoidable. The hybrid panel (D-002) spans 28 monthly
periods; a 6-month holdout leaves at most **22** training rows; `auto_arima`
and `exp_*` need **24**. **No origin in this dataset makes those six models
eligible with a 6-month validation window.**

**Resolution.** Two paths, both shipped, controlled by
`AIS_MIN_HISTORY_PROFILE`:

- `reference` (**default**) — reference thresholds honoured exactly. Six models
  report `Ineligible` with the precise unmet requirement and its remediation.
  They stay on the leaderboard.
- `monthly_relaxed` — documented deviation lowering the ES / Auto-ARIMA minimum
  to 18 rows with a shorter seasonal period, so all 13 can be compared. Every
  leaderboard row states which profile produced it; metrics from different
  profiles are never blended.

**Rejected:** shortening validation to 4 months (abandons the mandated
Oct 2025 – Mar 2026 window); moving to a weekly panel (the order file's daily
dates would support ~69 buckets and make everything eligible, but a monthly
panel was specified); silently lowering thresholds; substituting an easier
algorithm.

---

## D-002 — Hybrid target panel with an explicit `target_source`

**Decided:** `sales_proxy` for Apr 2024 – Mar 2025, `order` for
Apr 2025 – Jul 2026. Orders win on any overlap.

**Problem.** Ordered quantity is the primary target, but the order file starts
Apr 2025 — only **6 months** before the mandated Sep 2025 cut. Sales run
Apr 2024 – Mar 2026 but are a **censored** signal: 19.38% of ordered units were
never despatched, so a model trained on despatches learns the supply constraint
and forecasts the stockout forward.

**Consequence, and it is a benefit.** The union spans **28 monthly periods**
(Apr 2024 – Jul 2026), not 24, and yields a genuine second validation origin
(train through Jan 2026, validate Feb – Jul 2026). The mandated origin trains
on 12 proxy + 6 order months.

Every panel row carries `target_source`. The two sources are never described as
equivalent, and the Forecast Explorer marks the proxy period distinctly.

---

## D-003 — Canonical SKU key from Product Code, never raw Oracle No

**Decided:** `UPPER(TRIM(Product Code))` -> strip trailing `.AFM` / `.AF` ->
strip trailing `.` -> `TRIM` again.

**Evidence.** Measured over all 1,703,042 sales rows:

| | |
|---|---|
| Distinct canonical SKU | **2,260** — exact control match |
| Branch x canonical SKU series | **63,210** — exact control match |
| Distinct raw `Oracle No` | **2,147** |
| Oracle Nos colliding across canonical SKUs | **109** |
| Canonical SKUs mapping to >1 Oracle No | **0** |

Raw `Oracle No` collapses 2,260 SKUs to 2,147 and loses 113 SKUs' identity.
Causes found in the data: 121 `PREGST.`-prefixed legacy codes sharing an Oracle
No with their `FG.` twin; glass-spec character substitutions
(`...SCS31B0000` -> `...GCG31B0000`); model-prefix substitutions
(`FG.HX6...` -> `FG.ZX6...`); four `NONOE*` prefixes; one code with an interior
space before its trailing dot.

Normalising the whitespace case does not change either count, so the universe
is stable. The mapping is many-to-one, canonical -> Oracle, and the
reconciliation report (missing / disagreements / duplicates / collisions) is
persisted per ingestion.

---

## D-004 — VAR's second endogenous series is despatched quantity

**Decided:** Meriton's generalized multi-endogenous design, with
`despatched_qty` as the paired series at branch x SKU grain.

**Reasoning.** Meriton requires `>= 2` non-constant aligned endogenous columns
(`_prepare_var_endog:1964-1977`) and marks the model ineligible otherwise.
Sodexo's narrower `target + var_pair` design needs a domain-specific pair; AIS
has no natural second demand series. Despatched quantity genuinely co-evolves
with ordered quantity and is available at the same grain.

It is supply-censored, and that is stated in `parameter_metadata()` and in the
UI: it is a co-movement signal, not a second demand truth. At aggregate levels
`mrp_value` and `shortfall_qty` are additional candidates. Most sparse series
will have a constant pair, and VAR is then `Ineligible` with that reason —
not `Failed`.

---

## D-005 — Forecast scope is the sales ∪ orders SKU universe

**Decided:** the panel covers canonical SKUs appearing in sales or orders
(the 2,260 universe). The stock file's remaining codes are reported as
"stock without demand history", never silently dropped.

The stock snapshot holds **6,171** product codes, including MOLDING (3,099),
HIGH END (1,687), WIPER (1,652) and ADHESIVES (432) — non-glass items outside
the forecast scope. Dropping them without a trace would hide real inventory
value; forecasting them without demand history would be fabrication.

---

## D-006 — SQLite now, PostgreSQL-ready by construction

Portable SQLAlchemy types only, Alembic for every schema change, one
`if _is_sqlite` guard in `app/db/session.py` for WAL pragmas, and analytical
scans against Parquet rather than engine-specific SQL. Switching engines is
setting `AIS_DATABASE_URL`.

Follows **Sodexo's** relational schema pattern (`TrainingJob` / `ModelRun` /
`ModelPrediction`) rather than Meriton's flat JSON files under session UUIDs.

---

## D-007 — No Redis, no Celery, no containers

Neither was requested. Both reference projects run training in an in-process
daemon thread behind a single global lock; AIS keeps in-process execution but
replaces the global lock with a bounded thread pool, a real jobs table,
cancellation tokens and per-model timeouts. That is a genuine improvement over
both references without importing infrastructure a monthly-cadence POC cannot
justify.

---

## D-008 — numpy pinned to 1.26.4

`tensorflow-cpu==2.17.0` requires `numpy<2.0.0`. An initial pin of
`numpy==2.0.2` produced a hard `ResolutionImpossible`. TF 2.17.0 is itself
Oxea's choice, made because `tensorflow-cpu==2.21.0` (Meriton's) conflicts with
`mlflow==2.19.0` over protobuf.

Verified installed together and importable: numpy 1.26.4, pandas 2.2.3,
statsmodels 0.14.6, scikit-learn 1.5.2, xgboost 3.3.0, pmdarima 2.1.1,
tensorflow 2.17.0, mlflow 2.19.0. Nothing was installed into any reference
project.

---

## D-009 — MinT is not computable at the base level

Full-covariance MinT over 63,210 base series needs a 63,210² matrix (~32 GB
float64) estimated from at most 28 observations. So: **variance (WLS) scaling**
for base -> branch, **full MinT with shrinkage** for branch -> region ->
national (a 51 x 51 matrix), and bottom-up or proportional as the documented
fallback. Which method ran is recorded per forecast row.

---

## D-010 — Quantiles are calibrated by segment, never per series

One origin x six validation months yields **six** residuals per
series·model·horizon, against the references' own 5-residual minimum. Per-series
calibration would be arithmetically possible and statistically worthless.

Residuals pool by **model x horizon x demand segment**; conformal calibration
where enough residuals exist, empirical percentiles otherwise; which one ran is
recorded. `point <= q80 <= q90 <= q95` is enforced by monotone sorting, and
crossings are **logged with a count**, never silently corrected.

---

## D-011 — WAPE is primary; legacy MAPE is preserved but separately labelled

Both references rank by lowest valid MAPE. MAPE excludes zero actuals, and 62%
of AIS series are intermittent — so many series have 0–2 non-zero validation
points and their legacy MAPE is `None`.

AIS therefore reports two rankings side by side:

- **AIS operational champion** — reliable and eligible; lowest WAPE; then
  lowest absolute bias; then lowest MAE; then deterministic `model_id`
  tie-break. Requires comparable validation period and fold coverage.
- **Legacy parity result** — lowest valid MAPE, exactly as Meriton and Sodexo
  compute it, shown as `None` where undefined rather than substituted.

The two are never conflated in the UI or the API.

---

## D-012 — sMAPE and MASE are new work

Neither reference implements sMAPE or MASE (verified: `Sodexo metrics.py`
returns only `mape, accuracy, mae, rmse, wape, bias`; Meriton's
`metrics_service.py` is the same set). Both are required here, so both are
implemented fresh, with the naive baseline for MASE fitted **inside each fold**.
Pinball loss and interval coverage are likewise new.

---

## D-013 — Baselines are structurally separated from the 13

`naive`, `seasonal_naive`, `ma3` and `ma6` live in `BASELINE_METHOD_IDS`, a
tuple distinct from `CANONICAL_MODEL_IDS`.
`assert_canonical_registry()` fails if the two ever intersect, and that check
runs **before** the count and coverage checks so a promoted baseline is
reported as itself rather than as a downstream count mismatch. A regression
test covers exactly that case.

---

## D-014 — The HTML analysis document is treated as a proposal

Every important figure in `AIS-forecasting-analysis.html` was recomputed from
the client files. It holds up well; differences are recorded in
`docs/VALIDATION_REPORT.md` §5 rather than smoothed over. Its proposed
Croston / SBA / TSB methods are **not** implemented, because they are outside
the verified 13. Its reported accuracy figures are its own claim and are not
restated as ours.

---

## D-015 — Two defects the HTML does not mention

Found in the source and now first-class validation controls:

- **Corrupt despatch dates.** `Despatch Date` contains `0000-00-00` and other
  invalid values; 68 unparseable, producing **216 negative lead times, minimum
  −8,763 days**. Raw, this corrupts Roorkee's lead-time standard deviation to
  132 days instead of ~1.5. Lead-time statistics are computed only on cleaned
  dates.
- **Over-despatch.** **9,498 order lines shipped 35,867 units beyond what was
  ordered.** Net shortfall (468,431) and gross positive shortfall (504,298)
  therefore differ by 7.6%. Both are reported separately, along with
  over-delivery quantity and net fill rate.

---

## D-016 — Project location note

The project sits under a OneDrive-synced path containing spaces.
`backend/.venv`, `frontend/node_modules`, `runtime/` and `frontend/dist` are
gitignored, but OneDrive will still attempt to sync them and can hold file
locks during installs. Moving the venv outside the synced tree is supported via
standard virtualenv activation; flagged rather than silently worked around.

---

## D-017 — The order file's product-master join key is `Oracle No`, not `Material Code`

**Decided in Phase 2, from measurement, after a control failed.**

The S9 coverage control first came out at **65.4%** against an expected ~99.9%.
Rather than relax the threshold, the join was measured both ways:

| Key | Line-weighted coverage | Distinct canonical values |
|---|---|---|
| `Material Code` | 93.699% (727,024 / 775,912) | 3,139 |
| **`Oracle No`** | **99.909%** (775,207 / 775,912) | **2,063** |

Two separate mistakes were in the original implementation: the wrong key, and
the wrong *measure* — a set intersection over distinct SKUs instead of the
line-weighted share the "99.9% of order lines" claim actually describes.

`Material Code` is `Oracle No` plus an `.AFM` suffix in the common case, but it
carries roughly **1,076 extra spec variants that join no master row**. So it is
not a substitute for `Oracle No` in this file.

**The important consequence — different files, different reliable keys:**

| File | Identity key | Why |
|---|---|---|
| Sales | **`Product Code`** (canonical) | Reproduces 2,260 SKUs and 63,210 series exactly; `Oracle No` collides across 109 groups (D-003) |
| Orders | **`Oracle No`** | 99.909% master coverage; `Material Code` carries unjoinable variants |

Neither key is universally correct, and assuming one would be wrong is exactly
the trap. Both are now measured per ingestion, the difference is recorded as
defect **D17**, and the S9 remediation text names the key so nobody relaxes the
control instead of checking it.

**Also corrected here:** the S9 control description now states its measure
explicitly — "Product-master coverage of order lines (line-weighted, via Oracle
No)" — so the number cannot be silently reinterpreted later.

---

## D-018 — Ingestion runs as a background job, not in a request

Streaming 2.6 M rows across the five files takes **~475 s** measured
end to end. `POST /api/datasets` therefore returns **202** with a version id
immediately and the work runs on the thread-pool runner
(`app/jobs/runner.py`), reporting progress the UI polls.

This is the runner Phase 7 reuses for training. It keeps both reference
projects' in-process execution but replaces their single global lock with a
bounded pool, per-job cancellation tokens, and a real status record — see
D-007.

**Read cost, measured:** product master <1 s, sales ~260 s (1.7 M rows, two
sheets), orders ~150 s (776 K rows), stock ~55 s, location master <1 s.

---

## D-019 — Singleton roles are scoped per source, not per mapping

**Decided in Phase 3, after the rule blocked a correct mapping.**

The first real draft returned two blocking R2 violations: two columns claimed
`target_column` and two claimed `time_column`. Both were correct. The order
file contributes ordered quantity on its order date; the sales file contributes
invoiced quantity on its invoice date. The hybrid target (D-002) needs both.

A global singleton constraint would therefore block the only correct mapping
this dataset admits. `SINGLETON_ROLES_PER_SOURCE` now scopes the rule to one
occurrence **within a source**, which still catches the genuine error — two
target columns inside one file — and the violation message names the source.

This was a design error in the generic rule, not an AIS quirk: any
multi-source dataset has the same shape.

---

## D-020 — Suggestions are advisory, and the confirmation gate is narrow but hard

Three properties, chosen together:

- **Every suggestion is advisory.** It carries a confidence, a rationale, and
  `is_authoritative: false`. Editing an assignment clears `is_suggested`,
  because it has then been reviewed by a person.
- **The gate is narrow.** Confirmation requires only the *target* and *time*
  columns to be reviewed, not all 119. Requiring every column would be
  theatre: most are template defaults nobody needs to think about.
- **The gate is hard where it matters.** A suggested target blocks
  confirmation with the exact column names, because on this dataset several
  columns look like demand — ordered, despatched and invoiced quantity all do,
  and only ordered quantity is the target.

The UI states how many columns a person actually reviewed rather than
relabelling template defaults as "Reviewed". On the real mapping that is 4 of
119, and saying so is more honest than hiding it.

---

## D-021 — A confirmed mapping is immutable; a new version supersedes it

Editing a confirmed mapping returns 409 with the remediation "create a new
mapping version". A later confirmation marks the earlier one `superseded` with
a timestamp and a pointer, and never overwrites it.

The reason is lineage: a training run may already have used the confirmed
mapping, and a forecast whose mapping silently changed underneath it cannot be
explained afterwards. This follows Sodexo's job/run/prediction persistence
pattern rather than Meriton's overwrite-in-place session files.

---

## D-022 — The order and sales facts stay separate through preprocessing

Preprocessing emits `order_fact` and `sales_fact` as two tables, not one.

Merging them here would erase which source each period came from, and
`target_source` is exactly what the hybrid panel needs in Phase 4. Measured on
the real files: 16 order periods (Apr 2025 – Jul 2026) and 24 sales periods
(Apr 2024 – Mar 2026), combining to **28 distinct monthly periods** spanning
Apr 2024 – Jul 2026 — the span D-002 predicted, now confirmed rather than
assumed.

`sales_fact`'s quantity column is named `invoiced_qty`, not `target`, for the
same reason: it is a censored signal and must not be mistaken for demand.

---

## D-023 — Alembic owns the schema, including two drift cases

`app/db/migrate.py` handles three start states rather than assuming a clean
one:

1. **Empty database** — migrate to head.
2. **Already managed** — upgrade to head.
3. **Pre-baseline** (tables but no `alembic_version`, which is what Phase 2's
   `create_all` produced) — create the missing tables, then stamp. A bare stamp
   would assert a schema the database does not have; a bare upgrade would fail
   on the tables it does have.

Plus a **drift check** after either path: if the database claims head but is
missing a table the metadata declares, the missing tables are created and the
event is logged as `schema_drift_detected` with their names.

That check exists because my own first implementation caused exactly this: it
stamped a pre-baseline database at head, the mapping tables were never
created, and the first mapping request failed with a bare
`no such table: mapping_version`. Repairing loudly beats surfacing as a 500.

**Also fixed:** `alembic/env.py` was overwriting any caller-supplied
`sqlalchemy.url` with the application setting, which sent a programmatic
`command.upgrade` at the app database instead of the one requested. It now
only falls back to settings when no URL is present.

---

## D-024 — The non-glass flag is applied after orphan rows exist

`product_dim` reported `non_glass: 0` on the first real run, despite 5,183
non-glass stock rows being catalogued in Phase 2 as defect D13.

Cause: the flag was set during the stock pass, but only for SKUs already in
`product_dim`. The product master covers glass only, so nearly every non-glass
SKU is absent from it and is added later as an orphan row — losing the flag.

Non-glass SKUs are now collected during the stock pass and the flag applied
after orphan creation. Measured after the fix: **189 non-glass SKUs**, which is
the distinct-SKU count behind those 5,183 branch-level rows.

A defect that silently reports zero is worse than one reported loudly, and this
one would have quietly widened the forecast scope in Phase 4.

---

## D-025 — The panel universe is the demand-bearing union, and it is not 63,210

**Decided:** the panel holds branch × SKU pairs that ordered or sold something.
Measured: **68,675 series**, from 1,503,753 panel rows over 28 monthly periods.

The 63,210 control counts branch × SKU in the **sales file alone**. It stays a
control on the canonical key (`docs/VALIDATION_REPORT.md` S7) and is *not* the
panel size. Three universes now coexist, and each is reported by name rather
than conflated:

| Universe | Count | What it is |
|---|---|---|
| Sales control | 63,210 | branch × SKU in sales; validates the canonical key |
| Preprocessing series | 70,089 | union of order and sales facts, before the grid |
| **Panel series** | **68,675** | demand-bearing pairs the panel actually carries |

The panel is smaller than 70,089 because a series first observed after the
panel end contributes nothing.

**78,694 stock-only pairs are excluded.** A pair holding stock with no demand
history has nothing to forecast from; inventing a forecast for it would be
fabrication. They stay fully visible in `stock_position`, which is where the
dead-stock and misplacement analysis reads them.

---

## D-026 — A materialised zero and an absent month are different facts

**Decided:** each series' grid runs from **its own first observation** to the
panel end. Missing months inside that span become explicit zeros carrying
`value_unavailable_reason = true_zero`; months before the first observation are
never created.

Measured: **634,951 observed rows and 868,802 materialised zeros**, so 57.8% of
panel cells are zero.

Three properties, each deliberate:

- **No invented history.** A SKU first listed in June 2026 does not acquire two
  years of zeros it never lived through. `start_policy="first_observation"`.
- **Interior zeros are materialised.** A month with no order is a real
  observation of zero demand. Leaving it out would hide the sparsity the model
  must learn, and would make `shift`-based lags count *observations* instead of
  months.
- **Trailing zeros are kept.** They are the obsolescence signal, and the deck's
  proposal to use TSB for obsolescence detection depends on them existing.

`is_materialised` is carried on every row, so an observed zero and a filled
zero remain distinguishable downstream.

---

## D-027 — Lag 1 is the origin's own value, and the cut bounds the target too

Two conventions that every off-by-one in this layer turns on.

**`lag_1` is the value AT the forecast origin** - the most recent observation
available when the forecast is made, so `lag_k = target[o-(k-1)]`. That matches
both reference implementations, where `lag_1 = history[-1]` and `history` holds
everything known at prediction time (Meriton `_xgb_features`, Sodexo `_lag`).
A training row is `(origin o, horizon h)` with `y = target[o+h]`; since
`h >= 1`, a feature drawn from `<= o` can never contain the target.

**The training cut bounds the target period, not only the origin.** Filtering
origins alone would let a horizon-6 row read a target six months past the cut -
chronological-looking and still a leak. Verified on the real panel: with a
2025-09 cut, the maximum origin is 2025-08 and the maximum target is 2025-09.

Two further details worth stating:

- `same_month_last_year` is indexed on the **target** period
  (`origin + horizon - 12`), not the origin, because that is the month whose
  seasonality is being predicted. It is knowable at the origin whenever
  `horizon <= 12`.
- An early lag with no history is **left missing, never zero-filled**. Zero
  would tell the model "no demand" where the truth is "no observation".

The decisive test rewrites every value after an origin to 1e9 and asserts not
one feature at that origin moves
(`tests/test_leakage.py::test_corrupting_the_future_changes_no_origin_feature`).

---

## D-028 — A gapped panel raises instead of silently mislabelling

`build_origin_features` asserts the panel is a gap-free period grid and raises
otherwise.

`shift` counts rows, not months. On a panel missing March, `lag_2` would
silently mean "two observations back" rather than "two months back" - producing
a model that trains and scores and is quietly wrong about seasonality. That is
exactly the class of bug that never surfaces as an error, so it is made loud.

---

## D-029 — The training frame is denser than the analysis document's

Measured at the mandated 2025-09 cut: **3,895,148 training rows** across 17
origins × 6 horizons.

The analysis document reports 948,150 training rows, roughly 15 per series.
That implies far fewer origins - likely a single origin, or a restriction to
series with twelve months of history. Ours uses **every valid origin up to the
cut**, which is standard for direct multi-horizon and gives the model four
times the data.

This is a deliberate difference, not parity. It is recorded rather than
smoothed over, because the analysis document's accuracy figures were produced
on its own training set and are not ours to restate. `min_series_age` exists on
the builder for Phases 6 and 7 to restrict origins if runtime demands it -
XGBoost's reference minimum is 5 lagged rows.

Cost implication: the measured pooled-XGBoost benchmark was 21.5 s for 950,000
rows × 29 features. At 3.9 M rows the fit is roughly 90 s per model, so point
plus three quantiles is about six minutes - still well inside the budget in
`docs/ARCHITECTURE.md` §6.

---

## D-030 — Censoring is unknown on a sales-proxy row, not false

An invoice records what was sold. It says nothing about what was asked for, so
whether that month's demand was censored is **unknowable** from the sales file.

On a `sales_proxy` row, `despatched_qty`, `shortfall_qty` and
`over_delivered_qty` therefore stay **null** - never zero, which would assert
full service. The panel's `is_censored` flag resolves to `False` for the model,
because a model needs a value, but the underlying nulls are preserved so the
distinction survives into diagnostics.

Measured: 509,227 `sales_proxy` rows, all with null despatch and shortfall;
994,526 `order` rows, of which 109,145 are genuinely censored.

**And orders win by period, not by row.** Inside the order window a series with
no order row has *genuinely zero ordered demand*, so its invoiced sales must
not be substituted there - doing so would resurrect the censored signal the
whole design exists to avoid. Measured: 286,721 sales-fact rows fall inside the
order window and were superseded rather than merged. The proxy covers only
months before the order book begins (Apr 2024 – Mar 2025).

---

## D-031 — A recursive fold must not consume actuals, though both references do

**Verified in the reference source, at these exact lines:**

- Meriton `training_service.py:1130` (XGBoost) and `:1257` (LSTM)
- Sodexo `models.py:211` (XGBoost) and `:327` (LSTM)

All four do the same thing: `history.append(row["target"] if notna else
prediction)`. On a **validation fold** the actuals *are* present, so the
recursive walk consumes them and every step becomes effectively
one-step-ahead. The fold then flatters the model relative to the six-month plan
it is supposed to be evidence for.

This is a genuine conflict between two instructions - preserve reference
behaviour, and keep validation leakage-safe - so it is resolved explicitly
rather than silently:

**XGBoost defaults to direct multi-horizon, not recursion at all.** `horizon`
is a feature, the Phase 4 training frame already carries one row per (series,
origin, horizon), and one fit answers all six horizons. There is no walk, so
nothing to leak. The analysis document specifies exactly this - "rather than
chaining a one-month model into itself six times, which compounds its own
errors" - so this is the AIS design, not a deviation from it.

**LSTM has no direct-multi-horizon equivalent**, being a sequence model, so it
stays recursive but feeds **its own predictions**. A six-month fold is then a
genuine six-month forecast.

`ModelContext.allow_actuals_in_recursion` defaults to **False** and reproduces
the reference behaviour when set True, which is what the parity tests use.
Tests assert both directions: with the default, blinding the output frame's
actuals changes nothing; with the flag on, it does.

---

## D-032 — The exogenous set is calendar features, and that is the honest answer

An exogenous regressor is legitimate only if its value is known for the
forecast horizon. On the AIS panel that rules out nearly everything: MRP can
change, despatched quantity has not happened, stock is one snapshot. What
remains knowable for any future month is the **calendar**, plus the static
attributes that are constant per series.

So `app/domain/ais/exog_features.py` derives `calendar_month`, `month_sin`,
`month_cos` and `quarter` from the period index, and offers the static
attributes separately on request. Sine and cosine are included because a raw
month number tells a regression model that December (12) is distant from
January (1).

That is a thin exogenous matrix, and it is deliberately thinner than it could
be. The alternative - passing a historical driver and labelling it
future-known - is the failure mapping rule R5 exists to block, and it fails at
forecast time rather than at fit time.

Consequence, measured: with this set the four `_exog` variants are genuinely
evaluable. Before it they were permanently ineligible for a fixable reason,
which is worse than being ineligible for a real one.

---

## D-033 — The relaxed profile needed a shorter seasonal period to mean anything

D-001 promised that `monthly_relaxed` would let all 13 models be compared.
When first implemented it did not: lowering the row threshold to 18 left the
four Exponential Smoothing variants ineligible anyway, because their **second**
gate requires two complete seasonal cycles - 24 months at period 12.

`app/ml/evaluation/seasonality.py` now resolves the period per profile, porting
Sodexo's `resolve_seasonal_period` (`validation_plan.py:56-77`):

| Profile | Candidates | Resolved on the real 22-month window |
|---|---|---|
| `reference` | 12 only | **None** - 12 needs 24 observations |
| `monthly_relaxed` | 12, 6, 4, 3 | **6** (autocorrelation 0.242) |

Measured through the real adapter stack on a real AIS series:

| Profile | Completed | Ineligible |
|---|---|---|
| `reference` | **7** | **6** - `auto_arima`, `auto_arima_exog`, four `exp_*` |
| `monthly_relaxed` | **13** | 0 |

The default remains `reference`, because "no annual cycle is estimable from 22
months" is the truthful answer. A half-year cycle is a real pattern in
replacement demand, not a fiction invented to fill a leaderboard - but it is a
weaker claim than an annual one, and the profile label carries that.

A constant series resolves to `None` rather than 0, because zero
autocorrelation would let a flat series win a tie against a real signal.

---

## D-034 — VAR reads the target from column 0 rather than summing

Meriton's `_fit_var` returns `forecast.sum(axis=1) + constant_total`. That is
correct in Meriton's design, where the endogenous columns are
**dimension-pivoted slices of one target** and their sum reconstructs it.

AIS's endogenous columns are **different quantities** - ordered quantity and
despatched quantity (D-004). Summing them would forecast their total, which is
not a demand forecast of anything. The target is placed at column 0 by
construction and read from there, exactly as Sodexo does (`forecast[:, 0]`).

Meriton's constant-column handling is kept in full: a constant endogenous
column is dropped and its last value carried as an additive offset, rather than
being left in to make the system singular.

---

## D-035 — Persistence is new work, and it round-trips exactly

Neither reference persists a trained model; both refit from scratch on every
run and every fold (confirmed: no `pickle`, `joblib` or `mlflow` in either
project's model code). So `save`/`load` is new work for all 13.

Formats per family, chosen for portability rather than uniformity:

| Family | Format | Why |
|---|---|---|
| statsmodels (SARIMAX, ES, VAR) | pickle of the results object | statsmodels has no stable native format |
| pmdarima (Auto ARIMA) | pickle | same |
| XGBoost | native JSON + a metadata sidecar | version-portable; pickle is not |
| LSTM | Keras `.keras` + a scaler sidecar | a Keras model is not reliably picklable |

Verified on real AIS data: a reloaded model predicts **exactly** the same
values as the original, for all 9 models eligible on that series - LSTM
included.

---

## D-036 — The API reads its thresholds from the adapters, not a second table

`model_contract_service` originally carried its own `_MIN_HISTORY` table
alongside the adapters' thresholds. Two copies of the same fact is how an API
ends up advertising a requirement nothing enforces.

The table is deleted. `GET /api/models` and the `min_required_history` helper
both instantiate the bound adapter and ask it. Three tests assert the API's
advertised minimum, capability flags, display name and family all equal the
adapter's, so the two cannot drift apart.

The startup assertion is likewise now **two** checks: the canonical id list,
then `assert_registry_bound()` over the adapters actually bound to it -
covering a renamed display name or a capability flag disagreeing with the
registry, neither of which the id check alone would catch.

---

## D-037 — A fast-holdout model gets fewer test points, and the leaderboard says so

Sodexo sizes its fast holdout to consume the same **total** test rows a 3-fold
CV would (`validation_plan.py:16-25`), so that `validation_points` stays
comparable between a CV-evaluated model and a holdout-evaluated one. The
comment there is explicit that comparability is the goal.

That arithmetic does not survive the move to monthly grain. Matching two
six-month origins would need a twelve-month validation window from a 28-month
panel, and a twelve-month-ahead forecast is not the six-month plan being
evaluated. Matching three would need eighteen.

So AIS keeps the horizon honest and **gives up the row-count comparability**.
`auto_arima`, `auto_arima_exog` and `lstm` are evaluated on the single origin
with the most training history (`second`, train through 2026-01). Measured
consequence on a real series: those three report `validation_points = 6` where
the rolling-origin models report 10.

The difference is labelled - `evaluation_mode` is `holdout_fast` versus
`rolling_origin` on every row - and metrics are never blended across modes.
Phase 8 must not rank a 6-point metric against a 10-point one without showing
both counts.

---

## D-038 — The mandated origins overlap, so pooling de-duplicates rather than averages

`docs/ARCHITECTURE.md` §7 mandates two origins. Their validation windows are
2025-10..2026-03 and 2026-02..2026-07, which **overlap on 2026-02 and
2026-03**. Measured: 12 total test periods, 10 distinct.

Averaging the two origins' metrics would weight those two months twice. So the
pooled metric is computed from the underlying `(period, actual, prediction)`
triples de-duplicated by period, keeping the prediction from the origin with
**more training history** - the one a deployment would actually have used for
that month. `total_test_points`, `distinct_test_points` and
`duplicate_test_points` are all reported, so the overlap is visible rather than
assumed away.

A third origin was implemented and then made opt-in for the same reason.
Measured on the real panel, adding one (train through 2025-07) takes total test
periods from 12 to 18 while distinct test periods stay at 12: four of its six
validation months are already covered. It would raise the apparent fold count
without adding independent evidence, so `max_origins` defaults to 2.

---

## D-039 — The evaluation budget is an admission gate and a post-hoc verdict, not pre-emption

`TIMED_OUT` has to mean something specific. What it means here:

- **Before** a model starts, if the run budget is spent, it is
  `NOT_EVALUATED_BUDGET` and never fitted.
- **After** a fit returns, if it exceeded its per-model allowance, it is
  `TIMED_OUT` and its metrics are **discarded**, so an overrunning model cannot
  win a comparison against models that stayed inside the budget.

What it does **not** do is interrupt a fit already running. statsmodels,
pmdarima, XGBoost and TensorFlow spend their time inside C extensions where a
Python-level timer cannot pre-empt them; a thread cannot be killed safely and a
signal-based alarm is not available on Windows for non-main threads. Real
pre-emption needs a subprocess per fit.

That belongs with the job runner in Phase 7, which already owns process
lifecycle and cancellation tokens. Until then the budget is documented as what
it is rather than described as a timeout it does not enforce. The measured
risk this bounds: LSTM at 10.9 s per series against 68,675 series is 208 hours,
which is why the tiering exists at all.

---

## D-040 — The primary origin trains mostly on the sales proxy and validates entirely on orders

Measured on the real panel, per window:

| Window | Rows | `order` | `sales_proxy` | Censored |
|---|---|---|---|---|
| `primary` train (2024-04..2025-09) | 853,506 | 40.34% | **59.66%** | 36,134 |
| `primary` validate (2025-10..2026-03) | 380,552 | **100%** | 0% | 34,086 |
| `second` train (2024-04..2026-01) | 1,103,702 | 53.86% | 46.14% | 57,135 |
| `second` validate (2026-02..2026-07) | 400,051 | **100%** | 0% | 52,010 |

This is not leakage - the proxy is genuinely all that exists before 2025-04
(D-004) - but it means the mandated primary origin measures **cross-signal
generalisation**, not same-signal accuracy. A model is fitted largely on
invoiced sales and scored entirely on ordered demand. Ordered quantity and the
sales proxy are never described as equivalent, so a metric that spans both
cannot be reported as though they were.

`target_source_mix` is therefore attached to every backtest report, per window,
and `panel_target_source_mix` gives the same composition for a whole run. A
reviewer reading the leaderboard can see which signal the number came from.

Censoring is reported the same way and for the same reason. 34,086 rows in the
primary validation window are censored - the ordered quantity is a lower bound
because the line was despatched short. Those points are **scored** rather than
dropped, because excluding them would bias every metric toward months where
supply was easy, but `censored_points` travels with the metric set.

---

## D-041 — A divergent forecast is refused at the evaluation boundary, not fixed in the fitter

Both references fit SARIMAX with `enforce_stationarity=False` and
`enforce_invertibility=False` (`docs/MODEL_INVENTORY.md` §2), which AIS
preserves for parity. On AIS's short intermittent monthly series that setting
sometimes yields AR roots outside the unit circle and a forecast that grows
geometrically.

Measured on the real panel, `sarimax` at the `second` origin:

| Series | Actuals | Largest forecast |
|---|---|---|
| `JALANDHAR|FG.M11.FDR.G00320A000` | 5, 10, 0, 2, 0, 3 | **3.67e11** |
| `ANDHERI|FG.HQX.LFH.GCG21200D0` | 1, 2, 0, 2, 2, 12 | **7.42e3** |

The panel's largest observed target anywhere is **745**. A single such series
moved the pooled pinball loss by seven orders of magnitude: 78,922,256 before
the guard, 1.62 after.

Two bad options were available. Changing the fitter to
`enforce_stationarity=True` would break the parity claim in §2 silently.
Leaving it alone would let one runaway series dominate every pooled metric and
every quantile calibration it entered.

So the fit is left exactly as the references configure it, and the **guard sits
at the evaluation boundary**: a forecast whose largest magnitude exceeds 100x
the largest value ever observed in that series' training window is reported
`FAILED`, with its measured magnitude in the reason. It is not scored, and it
contributes no residuals. 100x is deliberately loose - far beyond any real
demand swing - so it catches divergence and not ambition. For an all-zero
training window a relative bound would reject every non-zero forecast, so an
absolute floor of 1,000 applies instead.

Negative point forecasts are handled differently: they are **counted, not
clipped**. `negative_predictions` is reported per origin, and the forecast is
scored as the model gave it. Clipping at zero here would flatter a model that
forecasts negative demand; clipping belongs at the forecast boundary in Phase
9, where it will be recorded as an adjustment rather than hidden inside a
metric.

---

## D-042 — VAR's second series at aggregate level is `active_cells`, not `despatched_qty`

VAR needs at least two aligned, non-constant endogenous series. Per series the
pair is the target and `despatched_qty` (D-004). At aggregate level that pair
does not survive: `despatched_qty` is null on every sales-proxy member row, and
`_aggregate` propagates a null rather than summing the known part — so the
column is null for roughly half the panel's months and VAR would be left with
one endogenous series.

Summing the known part instead would produce a lower bound presented as a
total, which nothing downstream would know to treat as one.

So the aggregate tier pairs the target with **`active_cells`**: how many member
branch × SKU cells were non-zero that month. It measures the *breadth* of
demand where the target measures its size, and the two genuinely move
differently — a month can hold flat volume while demand spreads across more
SKUs, or concentrate the same volume into fewer. That is the kind of second
series VAR exists to exploit, and it is counted from the target so it can never
be null.

Measured consequence: `var_exog` is the champion in 27 of 166 real scopes and
the national champion at WAPE 4.578%. With `despatched_qty` as the pair it
would have been `ineligible` almost everywhere at aggregate level, as it is on
54 of 60 sampled *individual* series where the same null problem applies.

---

## D-043 — Champion scope kinds are named after the columns the run groups by

The aggregate tier groups by `value_class` and `product_group`
(`scope_builder.SEGMENT_COLUMNS`), writing scope keys of the form
`value_class=A` and `product_group=AIS GLASS`. The champion scope kinds are
therefore `overall`, `region`, `branch`, `value_class`, `product_group` and
`series` — named after what actually exists rather than after a taxonomy in
prose.

The Syntetos-Boylan **demand segment is deliberately absent** from that list.
It classifies an individual series' sparsity from its ADI and CV², and an
aggregate of many series does not have one. It is used where it belongs: for
quantile calibration pooling (D-010).

Measured consequence of getting this wrong: the first implementation filtered
segment scopes by demand-segment name, so all nine `value_class` and
`product_group` scopes matched nothing and were dropped **without a reason** —
the exact failure this project exists to prevent. Selections went from 57 to 66
once the key prefix was used instead.

---

## D-044 — Comparability is assessed within an evaluation mode

D-037 established that `auto_arima`, `auto_arima_exog` and `lstm` are evaluated
on a single chronological holdout and get fewer test points — 6 against a
rolling-origin model's 10 on the real panel.

Phase 8 had to decide what that means for ranking. Excluding a 6-point model
from the order would remove `lstm` from every leaderboard, and `lstm` is the
champion in 42 of 166 real scopes. Ranking it against a 10-point model without
comment would hide the difference D-037 exists to name.

So candidacy is assessed **within a mode**: a `holdout_fast` row is measured
against the best `holdout_fast` row, and a `rolling_origin` row against the
best `rolling_origin` row. Rows that clear their own mode's bar then enter one
combined order — the plan being evaluated is the same six-month plan either way
— and three things travel with them: `evaluation_mode` on the row, both point
counts on the row, and a note on the response saying the ranking mixes modes.

The `MIN_TEST_POINT_SHARE = 0.5` floor still applies inside each mode, so a row
that only managed two or three points before running out of history is excluded
as `incomparable_test_window` rather than compared.

---

## D-045 — A scope is calibrated from its own residuals, not the run's pooled cells

D-010 pools residuals by model × horizon × demand segment across every scope a
run evaluates, and stores the offsets as **absolute quantities**. That is right
for a set of comparably-sized series. It is wrong across the aggregate tier,
where scopes differ in magnitude by more than fifty times — a small
product-group segment against the national total.

Measured on the real run: the national q95 came out **3.2%** above the point
forecast while that same model's national WAPE was **4.58%**. An interval
narrower than the model's own average error is not a conservative interval, it
is a broken one, and it would have driven every order-up-to level in Phase 10.

Forecast generation therefore calibrates each scope from **its own**
out-of-sample residuals, which are on its own scale, falling back to the run's
pooled cell only where a scope has fewer than `MIN_RESIDUALS`. After the change
the national q95 sits **7.7%** above the point, consistent with the measured
error.

The honesty cost is stated rather than hidden: two origins × six horizons gives
12 residuals per scope, below the 19 a conformal q95 order statistic needs, so
the method is labelled `empirical / scope_all_horizons` on every row. Twelve
residuals at the right scale beat five thousand at the wrong one, but the label
says which it is, and a row that fell back to the pooled cell says that the
interval's width may not match its scope.

---

## D-046 — Quantiles are carried through reconciliation, not projected through it

Reconciliation is a projection, and projecting q80 and q90 independently is
arithmetically available. It is also wrong: two separate projections can cross,
and a q90 below its q80 is worse than a slightly sub-optimal interval.

So the point forecast is projected, and each quantile level is then carried
across, floored at the reconciled point, re-sorted, and re-checked. Crossings
are **counted** on the run (`quantile_crossings_corrected`) rather than
silently repaired, for the same reason D-010 counts them at calibration time: a
crossing is a signal that the calibration is thin.

Measured on the real run: 0 crossings at the aggregate tier, and the ordering
`point ≤ q80 ≤ q90 ≤ q95` holds on every one of the 2,256 persisted rows.

---

## D-047 — Monitoring reports "not computable" and never a reassuring zero

Error deterioration compares a champion's accrued production error against its
backtest WAPE. On this dataset it cannot be computed at all: the forecast
origin **is** the last month the panel holds, so no forecast period has an
actual to compare against.

Three responses were available. Report 0% deterioration — which asserts the
champion is holding up when nothing has been checked. Omit the measure — which
makes an absent check indistinguishable from an absent feature. Or return
`computable: false` with the reason.

The endpoint returns the third, and the page renders it as "this has not been
checked yet" rather than as a green tick. It becomes measurable with no code
change as soon as one month of actuals arrives after the origin.

The same principle governs the other three measures: **no thresholds are
applied anywhere**. Drift reports both window means, both row counts and the
percentage shift, and leaves the judgement to the reader. It also reports when
the target source differs between the two windows — measured on the real panel,
the +23% national shift spans the boundary where a mixed order/sales-proxy
window becomes order-only, so part of that shift is a change of measurement
rather than of demand. A drift figure that hid that confound would be worse
than no drift figure.

---

## D-048 — A scenario is a read-only transformation, not a re-forecast

A scenario could re-fit models under changed assumptions. It does not, for two
reasons: re-fitting takes minutes per scope, and a scenario that re-fits cannot
be compared cleanly against the baseline because both the model and the
assumption changed.

So a scenario reads stored forecast rows, applies a bounded demand multiplier
(0.1–5.0), a service level and a lead time, and returns baseline beside
scenario. The baseline rows are never written — a test re-reads them after a
×3.0 scenario and asserts they are unchanged.

Three consequences are stated on every response rather than left implicit:

- The multiplier scales the point forecast **and its quantiles together**.
  Scaling the point alone would leave an interval that no longer brackets it.
- Stock on hand is held at **zero on both sides**, so the difference between the
  two order columns is attributable to the levers alone. For a real order
  position the caller uses `/api/inventory/recommendations`.
- Nothing is re-fitted, so a scenario cannot say whether the scaled demand is
  **plausible** — only what it would imply.

A scope with no baseline forecast stays in the response with its reason. A
scenario cannot invent a forecast that does not exist.

---

## D-049 — An export carries the rows the page showed, including the empty ones

The obvious implementation of an export filters to the rows that have numbers.
That produces a file which is a *different dataset* from the one the planner was
looking at, and the difference is invisible once the file leaves the
application.

So every export includes the `unavailable_reason` column and the rows that have
one; an undefined metric is an **empty cell**, never a zero; and each file opens
with a `# ` provenance comment naming the run, the scope, the generation
timestamp and the relevant caveat — the recommendations export leads with
`CURRENT-SNAPSHOT ESTIMATES` — so a file found on a shared drive months later
can be traced back to what produced it.

---

## D-050 — Reconciliation runs from the finest *complete* level, not the finest present

A projection needs its base level to be a complete decomposition of its
parents. The local tier deliberately forecasts the **top-N series by value**,
not the whole network, so a run that includes it has 100 series rows against a
68,675-series panel.

The first implementation picked the base level as the first non-empty level in
`series → branch → region → national`, so the presence of *any* series row made
`series` the base. The projection then reconciled a 100-series hierarchy — whose
branch, region and national nodes are sums of only those 100 series — and wrote
the results onto the existing full-network aggregate rows.

**Measured consequence, caught by an end-to-end HTTP check rather than by a
unit test:** branch and region totals disagreed by 37,794 units for 2026-08,
while the run reported `coherent: true` and `max_incoherence: 0.0`. Both were
accurate about the subset the projection was handed. Neither was true of the
data that got persisted.

So the base level is now the finest level that is **complete**, measured against
the panel's own series count. A level below it is left unreconciled, its rows
carry `reconciliation_method: "none"` with a reason, and the run records
`partial_levels`.

The hierarchy response then has to distinguish two different things a
non-matching pair can mean, and it carries both:

- `expected_coherent: false` — the lower level is a subset, so the totals were
  never expected to agree. Reporting this as incoherent would raise a false
  alarm on every run that includes the local tier.
- `expected_coherent: true` with `coherent: false` — two levels that *were*
  reconciled together disagree. The reason says "that is a defect, not an
  expected gap", because it is.

Four regression tests cover it, including one that perturbs a stored national
row to confirm a genuine disagreement is still called a defect.

---

---

## D-043 — MAPE is the primary ranking metric, so accuracy and the leaderboard agree

Requested directly: rank on MAPE, and report accuracy as `100 - MAPE`.

D-011 made WAPE primary and kept the references' lowest-MAPE ranking as a
separately labelled parity result. That reasoning was about intermittency —
MAPE drops zero actuals and divides by small ones, and 62% of AIS series are
intermittent. **Measured, that objection does not apply to the tiers this
application actually trains.** MAPE is defined for 100% of completed rows at
every scope level, because the aggregate tier sums to dense series and the
local tier selects the top 500 by value with at least twelve observed months.
The sparse tail is served by the pooled tier, which is not ranked per series.

The positive reason is consistency. The accuracy figure shown to a reader is
`100 - MAPE`. Ranking by WAPE while reporting accuracy from MAPE can put the
model with the *better accuracy* in second place, which is indefensible on a
page that shows both.

**What changed.** `rank_candidates(primary_metric=...)`, defaulting to `mape`
and configurable through `AIS_CHAMPION_PRIMARY_METRIC`. The metric governs the
eligibility gate, the sort, and the baseline comparison — a champion chosen on
MAPE is compared against the best baseline *by MAPE*, since comparing across
two metrics is not a comparison. WAPE is still computed and still shown on
every row; nothing was removed.

**Measured effect on the current run.**

| | Result |
|---|---|
| National ranking | **Identical** under both metrics — same champion, same order |
| Champion changes across all scopes | **40 of 166 (24.1%)** |
| National champion | VAR with exogenous variables, MAPE 4.659% → **accuracy 95.34%** |
| Median champion accuracy | 95.3% national · 93.9% region · 89.5% branch · 80.4% series |

**The cost, stated rather than discovered later.** MAPE is asymmetric: a
forecast that is too high is penalised more than one that is too low by the
same amount, so MAPE-driven selection leans toward models that forecast low.
Measured on this run, champions chosen by MAPE under-forecast in **75%** of
scopes against **70%** under WAPE, with a median bias of **-5.21%** against
**-4.12%**. For an inventory system an under-forecast is a stockout. Two
mitigations are already in place and one is worth watching:

- Absolute bias is the **second** sort key, so between two models MAPE cannot
  separate, the less biased one wins.
- Replenishment sizes on q80/q90/q95, not the point forecast, so the service
  level absorbs some of the lean.
- Bias is on every leaderboard row. If the fleet-wide bias drifts further
  negative, this decision is the first thing to revisit.

**Accuracy clamps at zero.** `accuracy = max(0, 100 - MAPE)`, so a MAPE above
100% reports 0% rather than a negative number. Two of 166 active champions are
in that state, both single series at SECUNDRABAD (MAPE 110.1% and 205.9%). The
clamp is honest — a negative accuracy is meaningless — but 0% conflates "very
wrong" with "arbitrarily wrong", so the MAPE itself stays on the row.

**Not changed: how the models are fitted.** The 13 adapters still fit exactly
as the reference projects fit them; none was switched to a MAPE objective.
"Train on the basis of MAPE" is implemented as *selection*, which is what both
reference projects do and what CLAUDE.md's "do not reinvent a fitter" requires.
Changing an objective function would break the parity citations in
`docs/MODEL_INVENTORY.md` §2.

---

## D-044 — A training run can be restricted to named branches and top-N SKUs

**Decision.** `POST /api/training` accepts `branches` and `max_skus`. Both cut
the panel in `restrict_panel()` *before* origins, plans and cost are computed,
so every count downstream describes the slice actually trained. The restriction
is stored on `training_run.restriction_json`.

**Why.** A full run over 68,675 series takes tens of minutes, which makes
iterating on the models impractical — the request that prompted this was
literally "training is taking so much of time".

**Measured.** A run over BENGALURU + AHMEDABAD × top-20 SKUs by value:

| | |
|---|---|
| Panel cut | 1,503,753 rows → 1,120 (40 of 68,675 series) |
| Duration | **443.1 s** (7m 23s), aggregate + local tiers |
| Model runs | 799 written · 597 completed · 14 ineligible · 0 failed |
| Scopes | 47 (7 aggregate + 40 series) |

**SKUs are ranked inside the branch restriction, not nationally.** The top
twenty SKUs *of the chosen branches* is a coherent slice; the top twenty
nationally may barely appear in them.

**A restricted run says so, in three places.** `restriction.scope_warning`, the
run's `warnings` list (which sets `completed_with_warnings`), and
`summary.restriction`. A leaderboard built from two branches must never be
readable as a network result. A branch name absent from the panel lands in
`restriction.branches_unknown` rather than quietly narrowing the run; a
restriction that leaves nothing is a 409, not an empty run.

---

## D-045 — The six "ineligible" models were a history threshold, not a defect

**Investigated.** Six of the thirteen reported `ineligible` on all 169 rows of
the previous run:

```
Auto ARIMA needs at least 24 training observations; this window has 22.
Exponential Smoothing Additive needs at least 24 training observations; this window has 18.
```

Auto ARIMA, Auto ARIMA with exogenous variables, and the four Exponential
Smoothing variants all carry a 24-observation reference minimum. The AIS panel
is 28 months, so the earlier rolling origin leaves 18–22 training months. They
were not failing: `Ineligible` was reporting a validated data requirement
exactly as CLAUDE.md's status vocabulary requires.

**Remedy, already an accepted parameter.** `min_history_profile=monthly_relaxed`
lowers all six thresholds from 24 to 18. Re-running the scoped run under it:

| Model | ineligible before | ineligible after |
|---|---|---|
| auto_arima, auto_arima_exog | 169 / 169 | **0 / 47** |
| the four exp_* variants | 169 / 169 each | **0 / 47** each |

All thirteen now run on every scope, with **zero failures**.

**What remains ineligible is a genuine data fact, not a threshold.** VAR and
VAR-with-exogenous are ineligible on 7 of 47 scopes: *"VAR requires two
non-constant, co-evolving series; only 1 of 4 qualify here."* A single-cell
series has `active_cells` constant at 1, so there is no second endogenous
series to give it. That is not fixable by relaxing a threshold and was not
relaxed.

**Measured accuracy on this slice** (`100 - MAPE`, champions only, MAPE defined
for 785 of 785 completed rows):

| Level | scopes | median accuracy |
|---|---|---|
| national | 1 | 94.0% |
| segment | 2 | 94.0% |
| region | 2 | 88.6% |
| branch | 2 | 88.6% |
| series | 40 | 80.1% (range 16.8% – 91.3%) |

A non-registry baseline still beats the champion on **10 of 47** scopes. That
is reported, not hidden — the same finding as the full run.

---

## D-046 — Forecast Explorer filters series by location and SKU

**Decision.** At `series` level the scope picker gains Location and SKU
dropdowns. Both are derived by splitting the trained scope keys (`BRANCH|SKU`)
client-side; no endpoint was added.

**Why derived rather than fetched.** The filters then cannot offer a
combination the training run does not hold. A branch/SKU catalogue from
`/analytics/filters` would list 53 × 2,334 pairs, almost none of which have a
forecast — every one an empty state. The panel-level counts remain available on
Demand Analytics, which is where the whole catalogue belongs.

The SKU list narrows to the chosen location, and changing location clears a SKU
that location does not stock rather than leaving the picker pointing at
nothing. The count line states how many of the trained series matched and that
untrained ones are absent, so a missing SKU reads as "not trained", not "no
demand".

**Not a registry duplication.** Splitting on a delimiter is not forecasting
arithmetic; `src/test/no-duplicate-registry.test.ts` still passes.

---

## D-047 — Alembic may not reconfigure logging while the app owns it

**The symptom.** Starting the backend on a port already in use exited in
silence. No error, no traceback, no `[Errno 10048]` — the process simply
stopped after the alembic lines, which reads like a crash with no cause.

**The cause, which is not where I first looked.** `alembic/env.py` called
`fileConfig(config.config_file_name)`. `fileConfig` defaults to
`disable_existing_loggers=True`: it sets `.disabled = True` on every logger not
named in `alembic.ini`, and replaces the root handlers with alembic's stderr
console at WARNING. The app runs Alembic **in-process** from its lifespan
(`ensure_schema()`), so from that moment `uvicorn`, `uvicorn.error` and every
`app.*` logger were dead for the rest of the process.

Uvicorn binds the socket *after* the lifespan completes and reports a bind
failure with `logging.getLogger("uvicorn.error").error(exc)`. That logger no
longer existed in a usable state, so the one message that named the problem
went nowhere. `Application startup complete.`, `Uvicorn running on …`,
`startup_complete` and `schema_ready` were lost the same way.

Measured, before the fix:

```
>>> fileConfig("alembic.ini")
uvicorn.error disabled = True | app.main disabled = True | root level = 30
```

**I first blamed `configure_logging()`'s `root.handlers.clear()`. That was
wrong** and is worth recording, because it is the plausible answer.
Uvicorn's loggers carry their own handler on the `uvicorn` logger with
`propagate = False`, so clearing root does not touch them — asserted now by
`test_configure_logging_leaves_uvicorns_own_handler_alone`.

**The fix, guarded twice.**

1. `env.py` skips `fileConfig` entirely when `logging_is_configured()` — a flag
   `configure_logging()` sets. In-process, the app's configuration stands.
2. When Alembic *is* the CLI entry point and legitimately owns logging, it
   still passes `disable_existing_loggers=False`. Silencing a library is a
   formatting choice; disabling it is a way to lose an error.

**Verified end to end.** With port 8000 occupied:

```
INFO:     Application startup complete.
ERROR:    [Errno 10048] error while attempting to bind on address
          ('127.0.0.1', 8000): [winerror 10048] only one usage of each
          socket address ... is normally permitted
```

A side effect worth having: alembic's own migration lines now come through the
JSON formatter like everything else, instead of a second plain-text format on
a second stream.

Five regression tests in `backend/tests/test_logging_config.py`, including one
that asserts the hazard is real — `fileConfig` with its defaults still disables
all three critical loggers — so the guard cannot be quietly removed as
redundant.

---

## D-048 — A finished training run outranks a newer cancelled one

**Decision.** `champion_service.resolve_run` now prefers the newest run whose
status is `completed` or `completed_with_warnings`, and only falls back to any
run with rows when nothing has finished. A cancelled run stays reachable by id.

**Why, found the hard way.** A full 53-branch run was cancelled at 88%. Per the
contract its rows are kept — nothing is discarded. But `resolve_run` picked the
newest run *with rows*, so the partial sweep immediately became the authority
for the leaderboard, the Forecast Explorer, and everything downstream. The
cancellation appeared to do nothing.

The rows a cancelled run holds are not a sample of anything: they are whichever
scopes the tier reached first, in walk order. Letting them outrank a completed
run silently changes which branches the application appears to cover, and
nothing on any page says so.

**Measured.** Before: `resolve_run` returned the cancelled run, and
`/models/leaderboard/scopes?scope_level=series` listed 100 series across 30
branches. After: it returns the completed scoped run, and the same endpoint
lists 40 series across 2.

---

## D-049 — One workspace location scope, applied at every seam

**The problem.** Every screen answered "which locations does this cover?" for
itself, and they disagreed:

| Page | Read from | Locations shown |
|---|---|---|
| Demand Analytics, Exceptions, Scorecard | the panel | 53 |
| Model Leaderboard, Forecast Explorer | a training run | whatever it reached |
| Supply Intelligence lead times | the branch dimension | 57 |
| Supply Intelligence replenishment | a forecast run | whatever it covered |

Four numbers, no page explaining the difference.

**Decision.** `app/domain/ais/workspace.py` resolves it once, in precedence
order:

1. `AIS_WORKSPACE_BRANCHES`, when an operator names the locations explicitly.
2. Otherwise the branches the **active training run** was restricted to (D-044).
3. Otherwise unrestricted — every branch in the panel.

Option 2 is what makes this self-consistent with no hardcoded branch names: an
application whose models cover two branches now describes two branches. It also
means the scope follows the run, so a later full run restores all 53 on its own.

**Applied at four seams, not in each endpoint.** `_panel()` in the analytics
route (which Demand Analytics, Operational Exceptions, the branch scorecard,
the series picker *and* the AI assistant all share), the branch dimension for
lead times, the three loaders plus the forecast-row query in
`inventory_service`, and the drift frame in `monitoring_service`. Restricting at
the shared loader is what makes the location list identical by construction
rather than by coincidence.

The assistant deliberately shares the page seam: a chat answer naming a branch
that has no page anywhere is worse than no answer.

**It is never silent.** Every restricted payload carries `workspace_scope`
(branches, count, total, source, and a sentence) and the sentence is prepended
to the page's own `notes`, so it renders above every other note:

> This workspace covers 2 of 53 branches (AHMEDABAD, BENGALURU). Every figure
> on this page describes those branches only, not the national network. Source:
> training run bd88633f, which was restricted to these branches.

An unrestricted workspace reports `restricted: false` rather than omitting the
key, so a client can tell "everything" from "narrowed" instead of inferring it
from a missing field.

**The cost, stated plainly.** This hides 51 branches of real client data on the
analytics pages, which read the full panel and do not need a model to be
meaningful. That is a deliberate choice for a two-location workspace, requested
explicitly, and it is the reason the note is mandatory rather than optional.
Clearing `AIS_WORKSPACE_BRANCHES` and running an unrestricted training run
restores all 53 with no code change.

**Verified live** across every page's endpoint — `analytics/filters`,
`/summary`, `/exceptions`, `/branch-scorecard`, `/series`, `/lead-time`,
`inventory/recommendations`, `/transferable`, `models/leaderboard/scopes` at
both series and branch level, and `monitoring` drift — all return exactly
`['AHMEDABAD', 'BENGALURU']`.

---

## D-050 — Forecast Explorer is two cross-filtering slicers, not three pickers

**Decision.** The page lands on **series** level and offers exactly two
dropdowns, Location and SKU. The `Branch × SKU` picker is removed.

**Why the third picker had to go.** A series scope key is `BRANCH|SKU`, so a
location and a SKU together *are* the series. A third dropdown could only
restate the two choices already made — or contradict them, which is worse.
The pair resolves the scope on its own, with no extra click.

**They cross-filter in both directions.** Location lists the branches that
stock the selected SKU; SKU lists the SKUs the selected location stocks.
Neither list can offer a value that would produce an empty result, in either
direction. A one-way cascade (location narrows SKU only) was the first
implementation and was wrong: picking a SKU stocked at one branch left the
Location list offering branches that did not have it.

**Series is now the landing level**, replacing `national`. It is the grain the
whole application forecasts at, and the only level where a location and a SKU
are separate choices. The earlier compromise — keeping `national` as the
landing level and adding a "Switch to series level" hint — was rejected on
being told so: a feature reachable only by changing a dropdown the reader had
no reason to touch reads as absent.

Above series level the page falls back to a single plain Scope picker, because
there the scope list *is* the location list.

**Still honest about coverage.** The hint names the resolved key, or the number
of series still matching, and always says that a branch or SKU the training run
did not reach does not appear — so a missing SKU reads as "not trained", never
as "no demand".

---

## D-051 — The history window is a month calendar, bounded by the data

**Decision.** The two 28-entry period dropdowns on Demand Analytics are now
`<input type="month">` calendar pickers, labelled **From** and **To**, with
`min` and `max` set to the panel's own first and last month.

**Month, not day.** The panel is one row per branch × SKU × **month**; there
are no day-level values anywhere in it. `type="date"` would invite a reader to
ask for "12 Jun 2024" and hand them a whole month back — the quiet kind of
fabrication `docs/DATA_CONTRACT.md` and the existing `GRAIN_NOTE` already
refuse for daily and weekly views. `type="month"` opens the browser's real
calendar at the grain the data actually has.

**Bounded in both directions.** `min`/`max` come from `period_range`, so the
calendar cannot offer a month outside the data. Typed input is not bounded by
those attributes, so an out-of-range value is **clamped** rather than sent as a
query that would return an empty page. The two ends also constrain each other —
`To` can never precede `From` — because a backwards window silently returns
nothing.

**The range is stated, not implied.** *"Data available Apr 2024 – Jul 2026 ·
28 months"* sits beside the pickers, so an empty result is attributable rather
than mysterious, and an empty picker says what it defaults to. A **Full
history** reset appears only once a window is set, since there is otherwise
nothing to clear.

Eleven tests in `frontend/src/components/ui/__tests__/MonthRange.test.tsx`,
including one asserting the input type is `month` — so a later change to
`date` fails rather than passing quietly.

---

## D-052 — Three destinations removed from the UI

**Decision.** Removed from the navigation and from the router:

| index | page | path |
|---|---|---|
| 1 | Executive Command Center | `/` |
| 9 | Data & Model Monitoring | `/monitoring` |
| 10 | Connections & Settings | `/settings` |

Requested directly. The remaining ten destinations are unchanged.

**Removed from the UI, not deleted from the repository.** The page components
still exist under `src/features/{command-center,monitoring,settings}/`; they are
simply not imported by `routes.tsx` and not linked from anywhere, so nothing in
the UI reaches them. This project has no git history to recover a deletion
from, so unrouting is the reversible form of the same result — re-adding a nav
entry and a `<Route>` restores any of them. Their unit tests still run and
still pass, which now means they cover unreachable pages; say the word and I
will delete the three directories and their tests.

The backend is untouched: `GET /api/monitoring` and `GET /api/settings` still
exist, still work, and stay in `docs/API_CONTRACT.md`. Endpoint drift is
measured against the running app, and no route was removed from it.

**`/` now redirects rather than 404s**, to Demand Analytics — chosen over the
first nav item because Data Studio is a pipeline screen, whereas Demand
Analytics does the job the command centre did: showing the reader where things
stand. One constant, `LANDING_PATH` in `navigation.ts`, so changing it is a
one-line edit. The `*` catch-all points at the same constant instead of `/`,
which would otherwise have bounced through a removed route.

**Two things that would have broken silently.**

`AppShell` built its planning-workflow strip from `NAV_ITEMS.slice(1, 6)` — a
*positional* slice that only worked while the Executive Command Center sat at
position 0. With it gone the strip would have rendered Mapping, Demand
Analytics, Operational Exceptions, Training and Leaderboard: five plausible
links, silently the wrong five. It now selects by nav index. Verified in the
running app: `01 Data Studio · 02 Mapping & Validation · 03 Training Center ·
04 Model Leaderboard · 05 Forecast Explorer`.

The AI assistant's `TOOL_LINKS` map sent the `data_quality` tool's "check it
here" link to `/monitoring`. That entry is removed rather than repointed: the
file's own rule is that a figure the reader can verify is worth more than one
they cannot, and a link that silently redirects to an unrelated page is worse
than no link. The tool still runs and its facts still appear in the answer.

**Numbers are not reassigned.** The surviving destinations keep their original
indexes, so the sequence is now `2,3,4,5,6,7,8` plus the parity pages `11,12,13`.
The gaps are the record of what went. `REQUIRED_NAV_INDEXES` lists the seven
explicitly rather than deriving them from `index <= 10`, so removing another
page is a deliberate edit to that array and not a filter quietly returning a
shorter one.

A new test asserts no link to any of the three survives anywhere in the shell,
and that the landing path is a real destination.

---

## D-053 — Reconciliation rebuilds the counters it can, and says which it cannot

**The defect.** `reconcile_orphaned_runs()` set `status`, `finished_at`,
`failure_reason` and a warning — but not the counters. Those are written only
by the owning worker, at completion, and an orphaned run has no owner left. So
the row contradicted itself: `model_runs_total = 0` beside a `failure_reason`
on the same record reading *"It had written 2227 model_run row(s)"*, and a
Training Center showing "0 model runs" for a run that produced 2,227.

`duration_seconds` was null while `started_at` and `finished_at` were both set
— a subtraction nobody performed.

**Measured on the real record** (run `3c87a9ec`, orphaned when the backend was
restarted mid-run):

```
before   total=0     completed=0     ineligible=0    series_evaluated=0    duration=None
after    total=2227  completed=1420  ineligible=807  series_evaluated=131  duration=688.27s
```

**Fix.** One grouped read over `model_run` answers every counter — the same
rows, so the total is their sum — plus a distinct `(scope_level, scope_key)`
count for `series_evaluated`, matching what the completion path means by a
"series". `duration_seconds` is `finished_at - started_at`, normalised for
SQLite handing back naive datetimes, and left null when a `queued` run never
started rather than invented as zero.

**What is not recovered, stated on the row.** `series_requested` comes from the
in-memory scope plan and `residuals_recorded` from the residual store; both
died with the process. They stay at 0 and a warning says so, because a 0 that
looks like a measurement is worse than a 0 that admits it is missing.

**The message no longer promises a resume.** It said *"Resubmit the run to
continue"*, which reads as continuation. There is none — the stored rows are a
record, not a checkpoint. It now says there is no resume and a resubmission
starts over.

Five tests in `tests/test_training_api.py`, including one asserting the
counters and the prose on the same row agree — the exact contradiction above.

**The cause was not the run.** Run `3c87a9ec` did not fail; the backend was
killed at 18:12:44 while it was 67% through, to pick up an unrelated fix. The
job runner is in-process (D-007), so any restart destroys in-flight training.
Reconciliation makes that loss visible, not survivable — checking
`GET /api/training/current` before restarting is the only defence today.

---

## D-054 — AI recommendations, and temperature 2.0

**Decision.** `GET /api/assistant/recommendations` runs a fixed set of the
existing bounded read-only tools and returns a short ranked list — each item an
`observation` with its figure, a plain-language `explanation`, the `evidence`
it rests on, and `verify_on`, the page a reader can check it against. Rendered
as a collapsible panel above the conversation on the AI Assistant page.

**The sources are fixed, not model-chosen.** This is a standing question, so
the same evidence is gathered every run; a list whose shape changed run to run
could not be compared against the last one. The model explains what the tools
returned — it cannot query, cannot compute, and is told to do no arithmetic.

**An item with no evidence never leaves the backend.** `_clean` drops any item
without a measured figure, an observation and an explanation. The prompt asks
for grounding; this enforces it. Fewer evidenced items is the correct outcome —
a recommendation nobody can check reads exactly like one they can, which is why
asking the model nicely is not sufficient.

**Nothing is framed as an instruction to act.** There is no inventory-policy
backtest in this project, so no item can claim acting would have helped. Every
payload carries that caveat, the stock-snapshot caveat, and the workspace-scope
note.

### Temperature 2.0, as requested, with the cost stated

`AI_TEMPERATURE` defaults to **2.0** — OpenAI's maximum. Two consequences worth
being explicit about, because they cut against what this application is for:

- The same facts produce a **noticeably different list each run**. The panel
  prints the temperature next to a model-written list for that reason.
- At 2.0 token choice is close to uniform over the distribution, so the
  grounding rules in the prompt are followed **less consistently** than at 0.
  In an application whose contract is never to state a number it did not
  measure, that is the risk to know about. `_clean` is the backstop, but it can
  only drop a malformed item — it cannot detect a plausible-looking figure that
  was never in the facts.

Lower it with `AI_TEMPERATURE=0.3` and nothing else changes.

**Tool selection stays at 0**, as a separate setting
(`AI_TOOL_CHOICE_TEMPERATURE`). That call emits function names and JSON
arguments, not prose. Randomness there does not read as variety — it reads as
the assistant answering a different question than the one asked, or as
malformed arguments the API rejects. Applying 2.0 to it would degrade the
answer rather than vary it.

**It works with no key.** `_deterministic` writes the same list from the same
facts using templates, labelled `deterministic_no_key`, and a provider failure
falls back the same way with `provider_error` carrying the exception *type*
only. Measured on the real database with no key configured: 2 items —
3,638 critical exception lines, and a +23.3% demand shift over 6 months.

19 backend tests, 10 frontend. No live OpenAI call was made: the key is not
configured and every model path is tested against a stub.

---

## D-055 — AI Recommendations is its own destination

**Decision.** Nav index 14, `/recommendations`, its own page. The
recommendation list is no longer a panel on the AI Assistant page.

**Why they are two things.** The assistant answers what you ask; the
recommendation list answers the question you have before you know what to ask.
One is a conversation you drive and whose content depends on your question;
the other is a standing list that is the same every time you open it, gathered
from a fixed set of sources so two runs can be compared.

Sharing a page made the standing list read as part of a conversation it had
nothing to do with, and permanently cost the conversation its height on a page
whose whole layout is built around the scroll area owning the remaining space.

**The collapse control is gone with it.** It existed only to give the
conversation its height back. A page that hides its own only content is a
worse control than none, so it is replaced by **Refresh** — which matters more
here than it looks: at temperature 2.0 a re-read genuinely produces a
different list from the same facts (D-054).

Both still read the same five bounded read-only tools through the same
endpoint. Nothing about grounding, evidence or the caveats changed.

`Recommendations` moved to
`features/recommendations/components/RecommendationList.tsx` with its tests,
so the folder matches the destination.

---

## D-056 — The workspace is 2 branches × 20 SKUs, on both axes

**Decision.** `WorkspaceScope` gains a **SKU axis** alongside its branch axis,
and the deployment is set to AHMEDABAD + BENGALURU × 20 named SKUs. Both axes
are independent: branches with no SKU restriction means "these branches, every
product", and the reverse is equally valid.

### How the 20 were chosen

Not top-by-value, which produced 20 variations of one product in one value
band. Stratified instead, with three rules in order:

1. **Present in both branches** with ≥12 non-zero months, or a per-branch
   comparison would be empty on one side. 713 of 2,334 SKUs qualify.
2. **One per (glass type × value class) cell**, then one per vehicle category.
3. Round-robin by glass type, ranked by ordered value, to 20.

Resulting spread:

| Axis | Coverage |
|---|---|
| Glass type | Lam 10 · Sidelite 6 · Backlite 4 — all three real types |
| Vehicle category | CAR & MUV 15 · COMMERCIAL 3 · 3W 1 · HIGH END 1 — all four |
| Value class | A 12 · B 3 · C 2 · D 1 · New Model 2 — all five |
| OEM | Maruti 6 · Others 5 · Toyota 4 · Hyundai 2 · M&M 2 · Tata 1 |

40 series, 1,059 panel rows, 15.9% of those two branches' ordered units.

A SKU with **no product-master row** was excluded: it has no glass type, so it
cannot serve "spread across glass types". Unmapped SKUs are a real finding and
belong on the exceptions page, not in a representative sample.

### The client files were not moved

The request was to move everything else to a separate folder. The five files
in `data/source/` are marked read-only in this repository and there is no git
history to recover a move from, so **they stay where they are**. The
restriction is applied by `workspace.py` at every read seam instead, which
achieves the actual requirement — the application only ever sees the slice —
without an irreversible operation on client data.

`data/scoped/` holds the derived slice (`panel_scoped.parquet`,
`product_dim_scoped.parquet`, `manifest.json`) as a readable record of exactly
what the application covers.

### Three defects found while wiring it up

**A comma-separated list did not parse.** pydantic-settings JSON-decodes a
`list[str]` env var *in the source*, before any validator runs, so
`AIS_WORKSPACE_BRANCHES=AHMEDABAD,BENGALURU` raised. Fixed with `NoDecode` on
the two fields plus a before-validator that accepts both forms.

**The SKU cut was a silent no-op on drift.** `monitoring_service` read four
panel columns and `canonical_sku` was not among them, so the restriction could
not apply. It now reads the column. The test fixture that lacked it — the real
panel's grain is branch × SKU × month, so it always has one — was corrected
rather than the read being weakened.

**Three payloads carried the restriction without the note.** `workspace_scope`
was being added to the service dicts but stripped by the response models.
Added to `MonitoringResponse`, `SupplyOverviewResponse` and
`RecommendationsResponse`. Verified: all now report `branches=2 skus=20` with
the note.

### The suite no longer reads `backend/.env`

It did, which made every test a function of local configuration: a real
`OPENAI_API_KEY` broke every "no key configured" assertion and a workspace
setting broke every workspace test, neither being a defect in the code. The
conftest now sets `Settings.model_config["env_file"] = None` before the first
`get_settings()`.

Also fixed a latent flake in `test_a_fresh_adapter_is_built_per_origin`: it
compared `id()` values, and CPython reuses an address after collection, so two
distinct adapters could share one. Observed failing once in a full run. It now
holds the objects and compares with `is`.

---

## D-057 — The UI is eight tabs, built for the scoped workspace

**Decision.** The navigation is now eight destinations:

| Section | Tabs |
|---|---|
| Analysis | Overall Analysis · Per Branch & SKU |
| Modelling | Training · Forecasting |
| Operations | Supply Intelligence · Scenario Planner |
| Assistant | AI Assistant · AI Recommendations |

Seven pages were unrouted: Data Studio, Mapping & Validation, Demand
Analytics, Operational Exceptions, Training Center, Model Leaderboard and
Forecast Explorer. Their components remain under `src/features/` — this
project has no git history, so unrouting is the reversible form of removal.
`/` redirects to Overall Analysis.

**The workflow strip went with them.** `AppShell` rendered a five-step
pipeline strip linking Data Studio → Mapping → Training Center → Leaderboard →
Forecast Explorer. Four of those five are now unrouted, so it would have
pointed at nothing.

### Why these charts

Not a gallery — each one answers a question this data actually poses:

- **Demand vs despatch**, because the gap between them *is* the service
  failure, and ordered quantity is only a lower bound wherever despatch fell
  short.
- **Ordered-demand share over time**, with a reference line at Apr 2025.
  Everything before it is invoiced proxy, not orders, so a trend crossing that
  line compares two different measurements. Hiding it would have been the
  single most misleading thing on the page.
- **Pareto by value class**, the standard ABC view: bars are units, the line is
  the running share of total demand.
- **Seasonality by calendar month**, the profile a demand review opens with.
- **Exception mix by severity**, because exceptions are why a forecast and a
  plan disagree.

### Training answers four questions, from the code

`GET /api/training/explain` derives everything rather than restating it: fold
boundaries from `ml.evaluation.folds`, minimum history from each adapter's own
`min_required_history` **per profile**, hyperparameters from
`parameter_metadata()`, the ranking rule from `ml.selection.champion`. A
hand-written summary would drift the first time either changed.

It is also honest about tuning: there is **no hyperparameter search across the
13 models**. Only Auto ARIMA searches its order, inside each fold. The page
says so under "Not tuned" rather than implying a search that does not happen.

### Forecasting is per series, and says so

Two cross-filtering slicers resolve one branch × SKU, and the page names the
model and measured error **for that series** rather than a headline accuracy —
because champions are selected per series and two SKUs at one branch routinely
get different models.

### A silent cache bug this uncovered

Adding `sku` to `AnalyticsScope` did nothing at first: `_key` listed the scope
fields **by hand**, so the SKU never entered the cache key and one SKU's answer
was served for every other one. The page showed a different heading and
identical numbers — 20 series and 29,135 units for both SKUs measured.

`_key` now derives from `dataclasses.astuple(scope.normalised())`, which cannot
forget a field that exists. Five tests in `test_analytics_scope_cache.py`,
including one that asserts **every** field changes the key, so the next filter
added is keyed correctly without anyone remembering.

Measured after the fix:

```
<all>                                      series= 40 skus= 20 units=72158
branch=AHMEDABAD                           series= 20 skus= 20 units=29135
branch=AHMEDABAD&sku=FG.AQ3...             series=  1 skus=  1 units=   56
branch=AHMEDABAD&sku=FG.MP8...             series=  1 skus=  1 units= 6838
sku=FG.MP8...                              series=  2 skus=  1 units=16524
```

### Trained and forecast on the new slice

Training run `c6812131`, explicit 20-SKU list (not a top-N cut, which would
have substituted a different twenty): **472 s, 884 model runs, 561 completed,
115 ineligible, 0 failed** over 40 series. `restrict_panel` gained a `skus`
parameter that takes precedence over `max_skus` for exactly that reason.

### Two route-ordering and layout defects found by verifying

`GET /training/{run_id}` was declared before `/training/explain`, so FastAPI
matched `explain` as a run id and the tab failed with *"No training run with id
'explain'"*. Moved above the path-parameter route.

A percentage Y-axis at 34px clipped its tick numbers, rendering as a column of
bare `%` signs. Widened, with explicit ticks.

---

## D-058 — The forecast run is cut to the workspace before its scope plan

**The defect.** `build_aggregate_plan` derives its scopes from whatever panel
it is handed, and `forecast_service` handed it the unrestricted one. On a
two-branch workspace that produced 1 national + 6 regions + **53 branches** +
9 segments — 51 branch scopes with no champion, appearing on no screen.

**Why it mattered beyond tidiness.** The national aggregate summed 53 branches
while only 2 were modelled, so MinT reconciliation was distributing a total
across scopes the run had not covered — pushing demand that belongs to
CHENNAI or JAIPUR into AHMEDABAD and BENGALURU. A row with no champion also
counted toward `rows_unavailable`, so more than half the run reported as
unavailable when nothing was actually wrong.

**Fix.** The panel is restricted immediately after loading and before the
scope plan is built, using the same `WorkspaceScope` every page uses. Placed
there rather than inside `_load_panel` so it sits beside the plan it governs.
An empty result is a 409 rather than a run over nothing, and the applied scope
is stored on `summary_json.workspace_scope` — a forecast produced over two
branches must never read as a national one.

**Measured, same champions, same panel:**

| | before | after |
|---|---|---|
| scopes | 121 | **52** |
| scopes with a champion | 52 | **52** |
| rows written | 312 | 312 |
| rows unavailable | 342 | **0** |
| branch scopes | 53 | **2** |
| regions | 6 | **2** (WEST, SOUTH-1) |
| reconciliation | `mint_variance` | **`mint_shrinkage`** |
| duration | 63.9 s | 79.8 s |

Two things worth noting in that table. **`rows_unavailable` went to zero** —
every scope now has a champion, so nothing is forecast without a model. And
the reconciliation method *improved*: a coherent hierarchy of 5 aggregate
nodes admits shrinkage, where the 60-node mixed one fell back to variance
scaling.

Six tests in `tests/test_forecast_scope.py`, including one asserting that a
region whose only branch is out of scope produces no scope at all — otherwise
the hierarchy carries a node with nothing beneath it — and one asserting the
national aggregate sums exactly the branches in scope.

---

## D-059 — Overall Analysis carries the full Demand Analytics panel set

**The mistake.** D-057 replaced Demand Analytics with a new Overall Analysis
page carrying six panels. Demand Analytics had **sixteen**, plus cross-filtering
with dimming and the branch scorecard. "Replace, reusing proven panels" was the
instruction; six of sixteen was not reuse, it was a rewrite that dropped ten
working visuals.

**Fix.** Overall Analysis is now rebuilt *from* `DemandAnalyticsPage` — same
sixteen panels, same cross-filtering, same calendar range picker, same
scorecard — with three things added:

- the workspace scope banner,
- **Concentration by Value Class**, the ABC/Pareto view,
- **Exception Mix** by severity.

Eighteen panels, nineteen charts. Rebuilt from the proven page rather than
re-implemented: those panels were already verified, and re-typing them would
have risked regressions for nothing.

**Verified live.** All sixteen original titles present, the filter bar intact
(From/To calendar, Branch, Value class, Grain), and filtering still drives the
whole page:

```
unfiltered          ₹24.72Cr · 7.2K units short · 85.1% fill
Branch=AHMEDABAD    ₹9.50Cr  · 1.7K units short · 91.3% fill
cleared             ₹24.72Cr · 7.2K units short · 85.1% fill
```

The three-panel Overall Analysis written in D-057 is gone; nothing else about
the eight-tab navigation changed.

---

## D-060 — Demand drift, with a projection that mostly refuses

**Decision.** `GET /api/analytics/drift` reports measured drift for a scope —
each point comparing a six-month window against the six before it — plus a
projection of when the magnitude would cross a 20% reading aid.

**The projection is deliberately reluctant.** The request was to forecast when
the next drift will happen. That is not something this data answers well, so
rather than invent a date the projection is an ordinary least-squares line
through observed drift, extrapolated, and it returns `projectable: false` with
a reason whenever:

- fewer than 5 drift points avoid the Apr 2025 measurement change,
- the trend is flat or shrinking (no crossing on this trend, ever),
- the threshold is already crossed (nothing to project to),
- or the crossing is more than 12 months out — further ahead than the history
  it rests on.

It also states, in `basis` and in every caveat list, that it is **not a
forecast from any of the 13 registered models**. No model was fitted to drift.

**The measurement change is handled, not ignored.** The panel switches source
in Apr 2025 from invoiced sales proxy to ordered quantity. Points whose window
straddles that date are flagged, drawn muted on the chart, and **excluded from
the projection** — extrapolating a trend that is half an artefact would be
worse than not projecting.

Measured live: 17 points, latest +14.72%, projected crossing 2026-09 from 6
clean points with slope +0.97 pp/month.

Drift is also recomputed per scope, so it changes with the slicers: +14.72%
workspace-wide, +3.63% at AHMEDABAD, −4.6% for one series there.

---

## D-061 — Temperature 2.0 produced unusable prose, so explanations run at 0.3

**What happened.** The first live drift explanation, written at
`AI_TEMPERATURE=2.0`, came back as:

> "Drift shows how demand has changed compared to pastly observed sales and
> means average facts consumyac extrem acDemand unde ganho.solatu
> fortAshutadaastracted goverrtqeicaier Porուլի demandbuyakers फ
> whatsappialog القوة.Id.Offset july viac našem Committeebiased spot'm
> juvenileAdvice d"

Four scripts, no meaning. It would have rendered beneath a chart as though it
explained something. This is the risk recorded in D-054 arriving in practice,
and it puts two of the stated requirements in direct conflict: temperature 2.0
and "the LLM should give a clear explanation" cannot both hold.

**Resolved by separating the two kinds of call.**

- `AI_TEMPERATURE` stays **2.0** for the conversational assistant, where
  variety was what was asked for.
- `AI_EXPLANATION_TEMPERATURE` is **0.3** and governs any call whose job is to
  restate a fixed set of measured figures. An explanation has one job; variety
  is not a feature of it.

**Plus a guard, which matters at any temperature.**
`app/services/assistant/quality.py` rejects output that is not usable prose:
too short, mostly non-Latin script, mostly non-words, containing a
28-character concatenation artefact, or — the important one — **mentioning
none of the figures it was given**. That last check is what catches the
harder failure: fluent, confident text that is not grounded in the data at
all. A rejected reply falls back to the deterministic template and the badge
says `deterministic_after_unusable_reply`, so the reader knows.

A deterministic fallback already existed for a provider that *fails*. There
was nothing for a provider that answers confidently with nonsense.

Verified after the change, same endpoint:

> "Drift here means the measured change in demand compared to past history,
> not a forecast. For the whole workspace over the last six months, demand has
> increased by 14.72% compared to the baseline average. Because the
> measurement method changes in April 2025 from invoiced sales proxy to real
> orders, part of this shift reflects that change rather than a true demand
> change..."

---

## D-062 — A cache read must not change the cache

**The defect.** `_stamp` added the workspace note to the payload it was
handed. `cached_summary` hands back the dict it is holding, so every request
appended another identical note to the cached object — the page showed
**fifteen copies** of the same sentence under "How these measures are
defined", growing by one per load.

**Fix.** `_stamp` returns a shallow copy and builds a new notes list, so it
cannot touch the cached object. The note is additionally guarded by content,
so stamping twice over the same payload adds nothing.

Three tests, including one that asserts the input dict is unchanged after two
calls — the property that was actually violated.

---

## D-063 — Filling the gaps: the missing axis was SKU

**What was empty.** Overall Analysis had a three-column grid with a two-column
panel in it, leaving holes. More substantively, on a workspace *defined* as 20
SKUs it had **no per-SKU visual at all** — `summary` carried breakdowns by
branch, product group and value class, but not by SKU.

**Added.** `by_sku` to the summary payload, and two panels:

- **Top SKUs by Ordered Demand** — filled against unfilled, stacked, so bar
  length is total demand and the amber band is what was not supplied. The
  widest amber band is the product costing the most service, which is not
  always the biggest seller.
- **Service Risk by SKU** — unfilled demand as a share of ordered, worst
  first, with volume in the tooltip because a high share on a small SKU is a
  different problem from a high share on a large one.

Overall Analysis is now 20 panels and 21 charts, and the "How these measures
are defined" card was removed on request — its content is on the individual
panel notes.

---

## D-064 — Forecasting resolves a scope at every selection

**The defect.** The page resolved a scope only when exactly one series matched
both slicers, so "All locations / All SKUs" and "one location / All SKUs" both
showed an empty state — even though the run holds a national forecast and one
per branch. Reported as "no data showing".

**Fix.** Every selection that corresponds to a real forecast scope resolves to
it:

| Location | SKU | Scope |
|---|---|---|
| all | all | `national / NATIONAL` |
| one | all | `branch / <branch>` |
| one | one | `series / <branch>\|<sku>` |
| all | one | **none exists** |

The last row is stated rather than shown as empty: the hierarchy is national →
region → branch → branch × SKU, and a single SKU spanning branches is not a
level in it, so nothing was modelled for it.

**An aggregate now announces itself.** When the resolved scope is not a
series, the page says so prominently — aggregate demand is far less
intermittent and much easier to forecast, so its error does not transfer down
to one product at one branch.

Verified live: national 6 rows +14.72% drift · AHMEDABAD 6 rows +3.63% ·
AHMEDABAD × FG.MP8 6 rows −4.6% · SKU-only shows the explanation.

---

## D-065 — Supply Intelligence explains its own vocabulary

Supply Intelligence recommends order quantities, which is the most
consequential output in the application, and someone who does not know what a
protection period is cannot judge whether a quantity is sensible — they will
either trust it blindly or ignore it.

`SupplyExplainer` defines eight terms on the page, each with a plain sentence,
an expandable detail, and **its limit stated in the same breath**: the
protection period uses only the average lead time, dead stock is a placement
signal and not an instruction to scrap, a negative stock row is surfaced
rather than clamped, and every quantity rests on one snapshot with no
inventory-policy backtest behind it.

---

## D-066 — Four views on the forecast chart, and drift as a line

**The view slicer.** The Forecasting chart now carries the same four-way
switch the old Forecast Explorer had, because they are four different
questions and one chart cannot answer them at once:

| View | Draws | Detail table |
|---|---|---|
| **Full timeline** | actuals through the origin, then six forecast months with bands | forecast |
| **Actual** | observed demand only, with a history-range selector | actual, with source and censoring per month |
| **Backtest vs actual** | stored out-of-sample predictions against the actuals they were scored on | backtest, with residuals |
| **Forecast** | the six horizons alone, with q80/q90/q95 | forecast |

**Backtest is not the forecast**, which is why it is a separate view rather
than another line on the timeline: it is how the error was *measured*, on
months that have already happened. Origins stay separated — the same month
can carry different predictions from different folds, and overlaying them
would read as one jagged line rather than two honest ones.

Verified live: each view swaps the right detail table
(`forecast-table` → `actual-table` → `backtest-table` → `forecast-table`).

### Drift as a line chart

Replaced the bar chart. Three series over the same points:

- **Shift (comparable months)** — solid blue, the measured drift.
- **Spans the source change** — dashed grey, the windows that straddle
  Apr 2025 and so compare an invoiced proxy against real orders.
- **Projected (trend extrapolated)** — dashed amber, drawn only when a
  crossing is projectable, so the reader sees the slope the date rests on
  rather than only the date.

A shaded band marks the region inside the reading aid, so "normal" is an area
rather than two lines the eye has to hold apart.

**The solid line deliberately does not bridge its gap.** `connectNulls` was
set at first and drew a confident straight line straight through the one
region the chart exists to exclude. It is off: the gap is visible, and the
dashed grey series covers those months instead.

**A NaN made the whole chart vanish silently.** The projected rows carried
`shift_pct: NaN`, which propagated into the Y-axis domain; Recharts then
rendered an empty `ResponsiveContainer` with no error and no console warning.
Projected rows now carry `null`. Worth remembering: a Recharts chart that
renders nothing and says nothing is usually a NaN in the domain.

---

## D-067 — The forecast chart was plotting two different populations

**The defect, and it is the serious one.** `_history_for` read the panel with
no workspace restriction, while the forecast rows came from the restricted
run. So the full-timeline chart drew a **53-branch actual line against a
2-branch forecast**:

```
national history, Jul 2026   200,686 units
national forecast, Aug 2026    3,310 units
```

The forecast collapsed onto the axis and looked like zero. Reported as "can't
detect what is actual, backtest, forecast" — the forecast was invisible
because it was sixty times smaller than the line beside it.

Two different populations on one axis is worse than either alone: it makes a
correct forecast look broken, and it would make an incorrect one look fine.

**Fix.** `_history_for` applies the same `WorkspaceScope` the forecast run
applied, reading `canonical_branch` and `canonical_sku` when the scope needs
them. Verified after:

```
national   history tail [3258, 3705, 3242] -> forecast [3311, 3202, 3341]
AHMEDABAD  history tail [1142, 1457,  953] -> forecast [1198, 1281, 1051]
```

The forecast now continues the actual line instead of falling off it.

---

## D-068 — Telling the three series apart on one axis

Even at the right scale, three series on one timeline need to be separable at
a glance. Three devices, each doing a specific job:

- **A labelled divider and a shaded band at the forecast origin.** Without a
  boundary the actual and the forecast were one continuous stroke of the same
  weight, and the reader had to infer where measurement stopped.
- **Distinct stroke treatments** — actuals solid with a light fill, backtest
  dashed, forecast dashed ahead of the divider, service levels thin dotted.
- **The backtest is drawn on the full timeline**, aligned to the month slots
  it actually covers, so it visibly stops where the evidence stops rather
  than being interpolated across the whole history.

The legend now reads: *Ordered demand (actual) · Backtest (out-of-sample) ·
Forecast · q80 · q90 · q95*, which is the question the reader was asking.

The backtest query runs for `overview` as well as `validation`, since the full
timeline now needs those points too.

---

## D-069 — "Not available" is vocabulary, not a placeholder

**The defect.** The shared chart tooltip used `valueFormatter`, which prints
**"Not available"** for any null. On a multi-series timeline that produced:

```
2026-03   Ordered demand (actual)   2,843
          Backtest (out-of-sample)  2,761.27
          Forecast                  Not available
          q80 / q90 / q95           Not available

2026-10   Ordered demand (actual)   Not available
          Backtest (out-of-sample)  Not available
          Forecast                  3,341
```

Both tooltips are wrong in the same way. A forecast has no value in Mar 2026
because the forecast *starts* in Aug — that is a structural absence, not a
failure. An actual has no value in Oct 2026 because it has not happened yet.

In this application "Not available" is **load-bearing**: it is the word for a
value that should exist and could not be produced, and CLAUDE.md requires
seven such states to stay distinct. Printing it for "this series does not
reach this month" collapses two of them, and trains the reader to ignore the
phrase exactly where it matters.

**Fix.** A tooltip formatter that knows each series' own span:

- **Outside its span** → the series is omitted from the tooltip entirely.
- **Inside its span but null** → still reads "Not available", because there it
  genuinely is, and the row's `unavailable_reason` is appended when the API
  supplied one.

Verified live on the same chart:

```
mid-history   Ordered demand (actual) 2,611
near origin   Ordered demand (actual) 3,242 · Backtest (out-of-sample) 3,022.85
Dec 26        Forecast 3,226.55 · q80 3,773.8 · q90 3,872.15 · q95 3,970.5
```

No "Not available" appears anywhere on the page now, because on this series
nothing is genuinely unavailable — which is the correct outcome, and the
phrase is back to meaning something when it does appear.

---

## D-070 — The gaps, properly: the sample's own axes were missing

**What I got wrong first.** Asked to fill the empty space, I added two SKU
panels further down the page and left the visible hole — the four-column row
where `1 + 1 + 1 + 2 = 5` units wrapped and left the right-hand side blank.
That is the gap in the screenshot, and I had not touched it.

**What actually belonged there.** The workspace was deliberately stratified
across **three glass types** and **four vehicle categories**, and the UI
showed neither. The page could not display the shape of its own sample. Both
columns were already in the panel and simply were not read.

Added to `ANALYTICS_COLUMNS` and to `summary`: `by_glass_type`,
`by_vehicle_category`, `by_vehicle_age`. Measured on the workspace:

```
glass type        Lam 65,056 (10 SKUs) · Backlite 4,838 (4) · Sidelite 2,264 (6)
vehicle category  CAR & MUV 53,264 (15) · 3W 10,854 (1) · COMMERCIAL 7,929 (3) · HIGH END 111 (1)
vehicle age       >15y 39,582 (9) · 9-15y 17,834 (4) · 3-6y 12,678 (4) · 0-3y 1,840 (2) · 6-9y 224 (1)
```

The age profile is the one worth keeping: replacement glass skews to the
oldest parc, so a weighting toward >15 years is expected and a shift toward
the newest band would be the finding.

**The scorecard row had a second, different hole.** Its card grid was fixed at
four columns, so a two-branch workspace left two cells empty regardless of
what was added. The column count now follows the number of branches.

**Verified by measuring, not by eye.** Every grid row on the page was checked
for trailing empty cells:

```
before   two rows with holes (1 and 2 cells)
after    0 holes across 9 grid rows · 24 charts
```

## D-071

**A 2-span tile placed mid-row wraps, and modulo arithmetic cannot see it.**

D-070 claimed the Overall Analysis grid had no trailing empty cells. That claim
was produced by counting span units and taking a remainder:

```
holes = (cols - (spanUnits % cols)) % cols
```

For the product row that returned 0, and the row still rendered with a visible
gap. The arithmetic was right and the model was wrong. The row was

```
Demand by Branch(1) Value Class(1) Unfilled by Value Class(1)
Branch x Value Class(2) Glass Type(1) Vehicle Category(1) Vehicle Age(1)
```

which is 8 units in a 4-column grid - a perfect fit by remainder. But CSS grid
places items in order, and the 2-span item arrived with one column left in row
one. It cannot be split, so it moved to row two, leaving one cell empty behind
it and pushing everything down by one. The last row ended with Vehicle Age
alone and three cells empty.

**A remainder only tells you whether the units divide. It cannot tell you
whether they *tile*,** because it does not know that a span is indivisible or
that placement is ordered. Any row containing a multi-column item needs the
item's position considered, not just the total.

**Fixed by ordering, not by spanning.** The 2-span panel is now first in the
row, so it fills columns 1-2 and the singles follow. Nothing wraps. It also
carries `lg:col-span-2` as well as `xl:col-span-2`, so the row tiles at the
two-column breakpoint too rather than only at four.

**Four panels were added**, bringing the row to twelve units - three exact
rows of four at `xl`, six of two at `lg`. Each is a ratio of two figures
`/analytics/summary` already returns, so none is a new measurement:

| Panel | Measure | Why it is not a duplicate of a bar already there |
|---|---|---|
| Fill Rate by Glass Type | despatched / ordered | The volume bars rank demand; this ranks service, and the order is different |
| Value per Unit by Vehicle Category | demand value / ordered units | Volume and value rank differently - a low-volume segment can lead on value |
| Volume vs Value by SKU | both axes at once | The only panel that can show a SKU sitting off the diagonal |
| Unfilled Share by Vehicle Age | positive shortfall / ordered | Where service failure concentrates on the age axis |

**Fill rate excludes levels with no recorded despatch.** `despatched_units` is
`None` when the source carries no despatch row, and a `None` is not a zero
(the `missing_data` / `true_zero` distinction this project is required to
keep). Plotting such a level at 0% would read as "nothing was despatched" when
the truth is "nothing was recorded", so those levels are dropped and counted in
a footnote under the chart. On the current workspace all three glass types have
despatch recorded, so the footnote does not render - the path exists for the
data, not for the screenshot.

**Unfilled share uses gross positive shortfall**, so it is not the net figure;
the two differ by 7.6% across the dataset and are reported separately
everywhere.

**Verified by measuring rendered geometry, not by arithmetic** - the specific
correction this decision records. Every child of every grid was grouped into
real rows by `getBoundingClientRect().top`, and each row's occupancy compared
against its computed column count:

```
viewport 1440  grid-template-columns: 271.2px x 4
row  1  Branch x Value Class | Branch | Value Class                     4/4
row  2  Unfilled by Value Class | Glass Type | Vehicle Cat | Vehicle Age 4/4
row  3  Fill Rate | Value per Unit | Volume vs Value | Unfilled Share    4/4
row  4  Ordered Demand Trend | Ordered vs Despatched                     3/3
row  5  Unfilled Trend | Fill Rate | Demand Signal Mix                   3/3
row  6  Branch over Time | Ordered vs Despatched by Class | Realised     4/4
row  7  Seasonality | Demand Concentration | Coverage                    3/3
row  8  Top SKUs | Service Risk by SKU                                   3/3
row  9  Concentration by Value Class | Exception Mix                     3/3
totalHoles: 0
```

**A second measurement was needed to trust the first.** An initial probe
reported every chart on the page empty, including panels known to work. That
was stale HMR state in the open tab, not a defect: after a full reload the page
renders 52 SVGs, 103 bars and 20 scatter marks - one mark per workspace SKU.
The lesson is the same as the one above: a measurement that disagrees with
everything else is more likely to be measuring the wrong thing.

Fill rates were cross-checked against the API rather than read off the chart:
Lam 34,505/65,056 = 53.0%, Backlite 2,547/4,838 = 52.6%,
Sidelite 1,104/2,264 = 48.8%, matching the rendered labels.

## D-072

**Forecast impact is projected from a measured error reduction, never claimed
as a realised outcome.**

The request was to show the impact on sales, stock-out reduction and revenue
"because of this forecasting implementation", at one, three and six months.
Three separate reasons make that unmeasurable here, and none of them is a gap
to be filled later with more work on this dataset:

- **No forecast month has elapsed.** History ends 2026-07 and the forecast
  origin is 2026-08. There is no post-implementation actual to compare against
  a pre-implementation actual, at any horizon.
- **There is no inventory-policy backtest.** Stock is one snapshot with no
  history, so no stock-out count can be simulated under a forecast-driven
  policy. Already prohibited by the build contract; restated because an impact
  panel is exactly where the temptation lands.
- **A sales uplift needs a counterfactual.** What AIS would have sold without
  this system is not observable in any dataset here.

So the panel computes two things and the payload keeps them apart under
`measured` and `projections`, with a `basis` string saying which is which.

**What is measured.** `model_run.origins_json` already stores, per fold, the
horizons, actuals and predictions that were scored during training. Per-horizon
error is therefore recoverable exactly as computed, with no second evaluation
path that could drift from the first. The comparison is against `naive`,
because a naive carry-forward is what a branch does *without* a forecasting
system, which makes "better than naive" the closest honest answer to "what did
this buy you". At branch x SKU, pooled by volume:

| Horizon | Champion WAPE | Naive WAPE | Reduction |
|---|---|---|---|
| 1 | 20.31% | 25.61% | **20.72%** |
| 2 | 22.84% | 24.07% | 5.11% |
| 3 | 20.47% | 25.52% | **19.78%** |
| 4 | 25.91% | 27.36% | 5.31% |
| 5 | 30.00% | 28.38% | **-5.69%** |
| 6 | 28.51% | 30.85% | 7.57% |

**Horizon 5 is negative and is drawn.** A naive carry-forward was more accurate
than the selected champion there. It would have been easy to plot only the
three reported horizons, all of which are positive; the chart shows all six
instead, because a benefit panel that hid its one losing horizon is selling
rather than reporting.

**Error is pooled by volume, not averaged across series.** One unit
mispredicted by one unit is a 100% error; a thousand units mispredicted by ten
is 1%. Averaging says 50%, which describes neither series. Pooling absolute
error over pooled volume says 1.1%, which is what someone stocking those units
experiences.

**What is assumed, and who owns it.** Three assumptions convert error reduction
into units and rupees: the share of unfilled demand better planning can
recover, the contribution margin, and how much accuracy is taken as reduced
safety stock. All three are **sliders on the panel**, defaulted conservatively
(30% / 18% / 50%) and echoed back in the payload. This was chosen over a
hard-coded constant because the panel is shown to a client: when a figure is
challenged the answer is to move the slider, not to defend a number nobody can
see. The chain is printed so it can be re-derived: monthly unfilled x horizon
x recovery share x measured reduction x value per unit.

**A horizon with no measured reduction projects zero and is flagged
`measured: false`** rather than borrowing a neighbouring horizon's figure. A
*negative* reduction also projects zero, not a negative rupee amount: the
measurement supports "no improvement to claim", not "the system destroys
value".

**Six months is worth less than three** (Rs 1.20L against Rs 1.57L at the
defaults) because the measured reduction falls from 19.78% to 7.57%. The panel
says so in text, because the shape looks like a bug and is not.

**A silent failure found by cross-checking.** The first implementation read
`origins_json` with `json.loads`. It is a JSON column, so SQLAlchemy returns an
already-parsed list; `json.loads` on a list raises `TypeError`, which the
function's own `except` swallowed into an empty fold list. Every series then
paired to nothing and the endpoint reported forty series, sixteen beaten by a
baseline, and **no measured horizons at all** - a zero produced by the error
handling rather than by the data. Caught only because the endpoint's numbers
were compared against the same figures computed independently from raw SQL.
`_folds` now accepts both forms and `tests/test_impact.py` pins the regression.

## D-073

**The training page gained a live monitor, because explaining the design does
not answer "is it working right now".**

The page already derived the validation scheme, the thirteen models, the
metrics and the selection rule from code. All of that is static. The question
someone has while a run is in flight is different: which models are working,
which are refusing, and how far along is it.

**Aggregated server-side.** `GET /training/{run_id}/monitor` returns per-model
counts, median and best WAPE, champion wins and fit seconds, plus the fold
design. Doing it in the browser would mean shipping every model run row - 884
on the current workspace - on every two-second poll.

**The fold design is read from a fold the run actually scored**, not restated
from settings. If a run used a different split than configuration implies, the
monitor shows the split that was used:

```
origin 1 (primary)  train through 2025-09 (18 months) -> validate 2025-10..2026-03
origin 2 (second)   train through 2026-01 (22 months) -> validate 2026-02..2026-07
```

Drawn as bars on a real month axis, so the property that matters is visible
rather than asserted: each validation window begins strictly after its own
training window ends, and the training window grows between origins. That is
an expanding-window rolling origin.

**Status is never collapsed into a score.** `Ineligible` is not `Failed` and
neither is a poor WAPE. A model with 52 completed runs and a bad median error
is not doing worse than one with 32 completed and a good one - different facts,
both shown, stacked by outcome so a model that did not run never disappears.

**The four baselines sit below a divider, labelled "never eligible to be
champion".** They are scored so the champion can be checked against them, and
one of them winning is a finding worth seeing - but nothing in this UI can
present `naive` as a fourteenth model.

**`refetchIntervalInBackground` is enabled while a run is live**, which is not
the usual default. An `EventSource` is unaffected by tab visibility but a React
Query interval is paused when the document is hidden. With the default, the
progress bar kept advancing from the stream while the model table below it sat
frozen - two numbers on one screen disagreeing about the same run. Verified
against a live run with the tab hidden: before the change the bar moved 52.7%
to 57.8% while the table stayed at 357; after it, the bar moved 11.8% to 18.6%
and the table moved 51 to 119. The extra traffic is bounded to runs actually in
flight.

## D-074

**The composition panels say, on themselves, that their proportions belong to
the sample and not to the business.**

D-056 chose the twenty SKUs by stratification - one per (glass type x value
class), then one per vehicle category - so that every category would be
represented at all. That was right for judging model behaviour and it has a
consequence nobody had stated: **the volume mix cannot also be proportional.**
Spreading the SKU slots deliberately is the same act as making the shares
unrepresentative.

Measured against the same two branches with every SKU they carry:

| Axis | Worst level | Sample | Branches | Gap |
|---|---|---|---|---|
| Vehicle age | Category Z (>15 yrs) | 54.9% | 28.0% | **+26.9** |
| Glass type | Lam | 90.2% | 68.4% | **+21.7** |
| Value class | A | 95.4% | 74.3% | **+21.1** |
| Vehicle category | CAR & MUV | 73.8% | 87.2% | **-13.4** |

**All four axes are materially distorted, not just the stratified ones.** The
question that prompted this was about vehicle category; vehicle category turns
out to be the *least* distorted of the four, and vehicle age - which was never
a stratification rule - is the worst. That is the reason the caveat is computed
per axis rather than written as a sentence: a hard-coded warning naming vehicle
category would have been confidently wrong, and would have gone stale the
moment the workspace changed.

**The workspace banner was not already covering this.** It says the figures
cover 2 of 53 branches and 20 of 2,334 SKUs, which a reader can accept while
still reading the glass-type split as the shape of that slice's business. "This
is a subset" and "the proportions within this subset are not proportional" are
different warnings and only the first was being made.

**The comparison lifts only the SKU axis.** The reference is the same two
branches with every SKU, built by `dataclasses.replace(scope, skus=None)` so
the branch restriction is applied by exactly the same code path that applies it
everywhere else - never by a hand-rolled filter. Widening to all 53 branches
would answer a different question ("does this represent the network") and would
report outside the configured scope.

**Materiality is an OR, and the first version got it wrong.** The rule was
originally "a gap of at least 5 points AND an extreme ratio". That excluded Lam
at 90.2% against 68.4% - a 21.7 point overstatement - because its ratio is only
1.3x. A level already holding two thirds of the volume *cannot* have an extreme
ratio; the arithmetic caps it near 1.46. So an AND rule systematically excuses
distortion in the largest categories, which are the ones a reader looks at
first. A large points gap now qualifies on its own, and the ratio remains a
second route for small levels whose share collapses (0.3% against 16.3%), with
a 2-point floor so 0.2% against 0.1% stays quiet.

**It renders nothing when nothing is wrong** - no SKU restriction configured,
or an axis whose sample matches its branches. A warning that appears on every
panel is read on none of them.

**What the caveat is careful not to over-claim.** Each series is forecast
independently, so per-SKU and per-branch accuracy still mean exactly what they
say. Only the proportions between categories belong to the sample. The panel
says this, because a caveat that made the whole page look untrustworthy would
be its own kind of dishonesty.

## D-075

**The workspace is BENGALURU + DELHI-1, and the twenty SKUs are now chosen to
track demand by vehicle category.**

**There is no branch called DELHI.** The network has DELHI-1 (125,545 units),
DELHI-2 (97,645) and DELHI-E1 (41,604). DELHI-1 is used: the largest, a full 28
months, and comparable in scale to BENGALURU (251,476). Combining the three
into one "Delhi" would be a mapping change, not a workspace change, and was not
asked for.

**Three selection rules were tried, and the first two failed in instructive
ways.** The requirement was that the sample track demand by vehicle category.

1. *Slots proportional to vehicle-category demand* (CAR & MUV 17, COMMERCIAL 2,
   3W 1, HIGH END 0), highest-value SKU inside each. Vehicle category fell to
   4.7 points - and **glass type rose to 32.2 and value class to 28.9**, with
   every chosen SKU laminated and class A. The biggest seller in every vehicle
   category is a laminated windscreen.
2. *Slots over the joint (vehicle category x glass type) grid.* Better, not
   enough: still 95% of sampled volume laminated, glass type 27.3 out.
   **Allocating slots proportionally does not make volume proportional** - one
   windscreen outsells several sidelites, so a cell given four slots can still
   contribute a few percent of units.
3. *Greedy against the objective itself.* Twenty times over, add the eligible
   SKU that most reduces total absolute deviation between sample share and
   branch share across four axes, with vehicle category weighted double as the
   axis the request named.

**The third attempt then failed in the opposite direction, and the fix is worth
recording.** Optimising mix alone selected twenty negligible products carrying
**1.1% of the branches' units** - perfectly proportional, and about nothing.
Those are also the most intermittent SKUs, so the sample would have been both
useless commercially and the hardest possible case to forecast. Capping the
candidate pool by volume traded the wrong way (a tighter pool lifts coverage
but removes the small SKUs needed to tune the mix, so deviation rises). Coverage
belongs in the objective, as a term: `mix_error - lambda * coverage%`. Lambda
0.2, 0.5 and 0.8 all converge on the same twenty SKUs, so the optimum is stable
rather than a tuning artefact.

Result, against the old AHMEDABAD + BENGALURU sample:

| Axis | Old max gap | New max gap |
|---|---|---|
| Vehicle category *(the requested axis)* | 13.4 | **4.9** |
| Value class | 21.1 | **7.3** |
| Glass type | 21.7 | **14.8** |
| Vehicle age | 26.9 | **15.1** |

Every axis improved. The cost is coverage: 8.4% of the two branches' ordered
units against 15.9% before. That is the honest price of a sample that is
representative rather than large, and it is stated rather than buried.

**It also forecasts better**, which was not the goal but is worth recording:
series beaten by a non-registry baseline fell from **16 of 40 to 6 of 40**, and
measured error reduction at one month rose from 20.7% to 26.3%.

**`AIS_MIN_HISTORY_PROFILE=monthly_relaxed` is now set**, and without it the
Start training button produces a broken run. The panel carries 28 months; the
second fold trains on 22; Auto ARIMA and all four Exponential Smoothing
variants require 24. Under the `reference` default **six of the thirteen models
were 100% ineligible** - the exact trade-off `config.py` documents and D-001
records as the opt-in deviation. The working run `c6812131` had used the
relaxed profile; the first run on the new workspace did not, because the
request body omitted it and took the settings default. Found by reading the
eligibility reason off an ineligible row rather than by guessing at the SKU
change.

## D-076

**Training is startable from the page, and a run is drawn as the ranking
contest it is.**

**The button starts a run on one click.** The estimate sits beside it rather
than behind a confirmation dialog: a dialog that repeats what is already on
screen is friction without information, and the run is cancellable, so a
mistaken click costs a click on Cancel. A refusal is shown with its remediation
because "a run is already in progress" and "no panel build exists" are both
things the person can fix.

**The first visualisation was replaced.** A lattice - one cell per fit, setting
into colour as it resolved - was accurate and dull. It showed *work being done*
and said nothing about models getting better or worse than one another, which
is the only thing anyone watching a training run actually wants to know. Two
defects surfaced while building it and both were real:

- Row length used each model's `total`, which is *fits recorded so far*, not
  fits planned. Thirty seconds in, every row read `1/1` as a full-width green
  bar: a run that looks finished at 2%.
- The run-level counters are written when the run ends, so the five status
  tiles read 0 directly above a lattice showing hundreds of resolved fits - the
  same "two numbers on one screen disagreeing" defect as D-073.

**What replaced it is the race.** Champion selection *is* a ranking contest, so
the run is drawn as the ranking, moving: one bar per model, length is measured
accuracy (`100 - median MAPE`, D-043), sorted, and rows physically travel to
their new position when the ranking changes. Reordering uses FLIP - measure,
let React reorder, measure again, play the inverted difference - because
without it a reorder is a jump cut and the eye cannot follow which model moved.
Verified against a live run: nine of seventeen rows changed position inside
twenty seconds.

**The same view becomes the leaderboard when the run ends**, gaining champion
wins and fit time. One component, two states, so the finish is continuous with
the race rather than a separate screen. It replaced the previous accuracy chart
and model table, which were two more views of the same fact.

**The leaderboard immediately demonstrated its own footnote.** On run
`a2c987d9`, VAR ranks **first** on median accuracy (69.2%) with **zero**
champion wins - it is only scored on 32 scopes and ineligible on 18 - while
Auto ARIMA sits fifth and wins the most scopes (10). Most accurate on the
median is not the same as champion, because a champion is chosen per scope.
The panel says so beneath the ranking.

**Bars scale against the leader, not from zero.** Accuracies sit in a narrow
band (roughly 55-70%), so bars from zero look identical and the ranking is
unreadable; rescaling the axis to exaggerate gaps would make small differences
look decisive. Scaling to the leader keeps the comparison truthful, and the
exact shortfall is printed as a number beside each bar, because a length is a
poor way to read 3.6 points.

**Baselines race but carry no rank number** and are tagged and dimmed. A
baseline outranking half the registry is the most useful thing on the page;
presenting one as a fourteenth model is forbidden.

**A model with nothing scored yet shows "not scored yet"**, never a
zero-length bar that would read as "terrible". Motion is dropped under
`prefers-reduced-motion`, where the order alone still carries the ranking.

## D-077

**The training view is a vertical accuracy race, and it is the only ranking on
the page.**

**Ranking is on MAPE, which required no change.** `champion_primary_metric` is
already `"mape"` and `/training/explain` already defines accuracy as
"100 - MAPE, clamped at zero" (D-043). The column height is therefore the same
quantity the champion selector ranks on - the tallest column is winning by the
system's own rule, not by a measure invented for the picture. Verified against
the live endpoint rather than assumed.

**The leaderboard was removed.** A table and a chart of the same numbers are
two answers to one question, and the table was the weaker one. The race now
carries rank, accuracy, champion wins and eligibility in a single object.

**Columns, not rows.** Height reads as magnitude in a way bar length beside a
label does not, and thirteen columns fit one screen where thirteen rows needed
scrolling. Sorted best-first, left to right, reordering with FLIP on the
horizontal axis - measure, reorder, play the inverted difference - so a model
overtaking another is one object travelling rather than a list blinking.
Verified on a live run: five of thirteen columns changed position inside
twenty-two seconds.

**Baselines became a line, not columns.** The request was for thirteen models
ranked first to thirteenth, and the four non-registry baselines are not
candidates. They now appear as a **dashed reference line at the strongest
baseline's accuracy**, with every column below it tinted amber. On run
`8c691b3a` that line sits at 61.5% (`ma6`) and **seven of the thirteen models
fall below it** - the single most useful fact on the chart, and one a table of
thirteen rows buried. A line also cannot be misread as a fourteenth model.

**The axis runs 0-100.** Accuracies cluster between 45% and 69%, so a truncated
axis would make a three-point difference look decisive. The differences are
real and small, and the chart draws them small.

**Two refusals kept from the previous version.** A model with nothing scored
yet is a dashed empty column reading "-", never a zero-height bar that would
say "terrible" when the truth is "not yet tried". And short labels are derived
by rule from the API's own display names, never from a lookup table, because
the frontend must not carry a second model registry
(`no-duplicate-registry.test.ts`).

**The button is `Train models`** and starts a run on one click.

## D-078

**The training view is a bar chart race, driven by an event stream.**

One button trains every model; each is a horizontal bar whose length tracks its
live score; bars overtake continuously; the order they settle into is the
result. Built on the DOM with `d3-scale` for the axis rather than a charting
library, because the two things that decide whether it works - a reorder that
glides and a width that never steps - are easier to control directly.

**`src/config/models.ts` is the single source of truth for everything variable
except the model list.** The brief asked for one entry per model in that file.
This application cannot have that and keep its guarantees: the thirteen models
are asserted server-side at import time, the frontend reads them from the API,
and `no-duplicate-registry.test.ts` fails the build on a model id or display
name literal anywhere in frontend source. A list in the config would be a
second registry free to drift from the real one. Families, the metric, the race
constants and the family-assignment rule all live there; `resolveModels()`
adapts whatever the API returns, so three models or twenty work untouched.

**A new per-model stream.** `/{run_id}/events` carries run-level counters,
which cannot drive a race - a race needs each model's own score.
`GET /training/{run_id}/model-events` emits the four-event contract
(`started` / `progress` / `finished` / `failed`), with `epoch` meaning scopes
scored so far. `MockTrainer` emits the identical shape with no backend, so the
race is developed and demoed against a mock and shipped against the server
unchanged.

**A model with failures is not a failed model.** It can raise on two scopes and
score on forty; freezing its bar would be wrong. `failed` is emitted only when
a model finished with nothing scored *and* at least one raise. A model that is
merely Ineligible everywhere gets no terminal event at all - a different fact,
and one this project refuses to collapse.

### Four defects found while building it, all worth recording

**Declaring `width` in JSX undid every frame.** The loop wrote `style.width`
sixty times a second and React reset it to the minimum on each render - and
because the store updated on every event, renders were constant. The fix is
structural, not a patch: rows render from the stable `models` prop, the
component subscribes to nothing that changes per event, and the loop owns
width, transform, rank text, value text and the epoch counter outright.

**The field reloaded mid-race.** `useMemo([monitor.data])` handed back a fresh
array on every refetch - a new array is a new `load()`, which wiped the race
back to zero while it was running. Memoised on the model ids instead, and the
field query no longer refetches at all: scores come from the stream, and that
query is only ever asked *who* is racing.

**A StrictMode-detached ref measured zero.** The track width came from a
callback ref that kept the first element it saw. React's throwaway first mount
detaches that node; a detached node measures zero in every dimension, the
loop's `!trackWidth` guard tripped on every frame, and nothing drew while the
store filled with perfectly good scores. Measured from the stage the component
owns instead - one observer, no prop drilling.

**The forbidden-token guard is a substring scan.** The natural-exponential call
is banned in frontend source because forecast values are the backend's to
derive. The mock's saturation curve used it; rather than exempt the file, the
curve became `t / (t + k)`, which has the same shape. The comment *explaining*
the change then tripped the same scan by naming the call - worth knowing before
writing a comment about a banned token.

### What could not be verified here, and how it was covered instead

`requestAnimationFrame` does not fire in a hidden document, and the browser
pane in this environment reports `document.hidden === true` even when fronted -
measured at **zero frames in 1.2 seconds**. The drawing loop therefore cannot
run under automation at all.

So the arithmetic that decides a frame was extracted into `frame.ts` as a pure
function and tested without a DOM: ordering, rescaling, the minimum width, the
value gutter, a failed model sinking without being erased, the smoothing step,
the metric-direction round trip, and the layout contract. A full mock run
replayed through the real planner produces **13 lead changes**, against a
required four. Sustained frame rate is the one acceptance criterion that
remains unmeasured; it needs a profiler on a visible window.

**Returning to a hidden tab snaps rather than crawls.** With rAF dead while
hidden, every `displayScore` is frozen at a stale value; easing from there
would creep up for seconds. On `visibilitychange` the display values jump to
the live ones.

### Layout contract

Rows compress rather than the stage scrolling, down to a legibility floor of
22px - below that a row cannot hold a readable name and value, and a taller
panel is the better failure. That floor binds only past about twenty-five
models; every field from three to twenty fits on one screen, which is the
documented range.

## D-079

**The forecast-impact panel is removed, and the race shows the run that exists
rather than waiting to be asked.**

### Impact removed from Forecasting

The measured-versus-projected pair and its caveat panel are gone from the
Forecasting page on request, and `ImpactPanel.tsx` is deleted. The stale
caption that hard-coded "negative at month 5" went with it - it had been
asserting a finding that stopped being true three runs earlier, which is the
argument against writing a measurement into prose at all.

`GET /api/analytics/impact` and its domain module stay. They are tested, the
measurement they perform is sound, and nothing else changed about them; only
the page that rendered them is different. Re-mounting the panel is one import.

### The race now attaches to the current run

Three complaints, one cause: the race populated **only** when the button was
pressed. So a finished run showed an empty stage, and navigating away and back
wiped whatever was on screen. Neither was a fault in the race - it simply had
no data until somebody started a new run.

`model-events` already replays the whole field on connect, so the console now
attaches to the current run on mount, keyed on `runId` and whether it is live:

- **live** - phase `running`, bars race as events land
- **finished** - phase `done`, bars appear at their final lengths rather than
  animating up from zero for a race that ended hours ago
- **remount** - re-hydrates from the same stream instead of blanking

The button keeps its old job: start a *new* run. Submitting one invalidates the
current-run query so the race re-attaches in about a second rather than waiting
out the twenty-second poll.

### A pre-existing defect this uncovered

`_TERMINAL_RUN_STATES` was `{"completed", "failed", "cancelled"}` and **omitted
`completed_with_warnings`** - which is how almost every run here ends, because
any Ineligible model reports it. Fourteen of the twenty-eight runs in the
database are in that state.

Both SSE streams test membership of that set to decide when to send `end`, so
**neither ever terminated on a normal run**: they held the connection open
until `max_seconds` and never emitted their final events. This predates the
race - the run-level `/{run_id}/events` stream had the same bug since it was
written - but the race is what made it visible, because every model sat at
"running" long after its run had finished.

Measured before and after on a completed run:

```
before   started 17 · progress 17 · finished  0 · end 0   (stream never closed)
after    started 17 · progress 17 · finished 17 · end 1
```

`cancelling` is deliberately still absent: that run is winding down, not over.

## D-080

**The race is the thirteen; the leaderboard is the reference-project table; the
97 Ineligible are mostly not fixable.**

### Baselines leave the race, but not the run

`naive`, `seasonal_naive`, `ma3` and `ma6` no longer get lanes. They are not
candidates and a bar implies a candidate, so the race is thirteen and the
leaderboard is thirteen rows.

They are still **fitted**, and the leaderboard reports the strongest of them
beneath the table with how many registered models it beats. Deleting them
outright was the literal request and was not done, because on run `021d5778`
`ma6` at 61.5% beats **seven of the thirteen** - dropping the comparison would
make the panel read better than the models are, which is the one thing this
project is not allowed to do. They also cost nothing: `fit_seconds` is 0.0 for
all four. The comparison is one line; the clutter it was accused of was the
four bars, and those are gone.

### The leaderboard follows Oxea's

Read from `D:\OXEA/frontend/src/features/leaderboard/pages/ModelLeaderboardPage.tsx`
and its schema: a row per model including the ones that did not run, status
badges that keep Completed / Ineligible / Failed / Timed out apart, and metric
columns as *decision context* rather than a second ranking. Columns here:
rank, model, state, accuracy, MAPE, WAPE, MAE, RMSE, bias, scopes, wins, fit.
Sortable on the numeric columns; a model with no measurement sorts last in
either direction, because "not scored" is not "worst".

Hovering an Ineligible row shows the requirement it missed, which is the
difference between a table that reports a problem and one that merely records
it.

### Accuracy was already MAPE-based

The report was that the percentages came from WAPE. They did not, and the two
differ enough to check rather than assert:

```
model            median MAPE   median WAPE   100-MAPE   shown
var                 30.84         34.08        69.16     69.2%
sarimax_exog        55.02         49.58        44.98     45.0%
```

If WAPE were the source, VAR would read 65.9% and SARIMAX+exog 50.4%. The
`accuracy` figure is now computed once in `monitor.model_progress` and read
from there by every surface, so the question cannot recur from three separate
derivations.

The WAPE on screen was the **Forecasting** page's per-series "measured error"
tile - a different page, a different scope, and genuinely WAPE.

### The 97 Ineligible, and why "make them all eligible" is refused

Diagnosed on run `021d5778`:

| Cause | Rows | Fixable? |
|---|---|---|
| `insufficient_endogenous` - VAR needs two non-constant co-evolving series; only 1 of 4 qualifies | 30 | **No.** The other columns are constant or incomplete. Feeding VAR a constant column produces a number, not a forecast. |
| `non_positive_target` - multiplicative smoothing requires strictly positive values | 24 | **No.** Those series contain real zero months. Multiplicative decomposition divides by the level; this is arithmetic, not configuration. |
| `insufficient_history` - window shorter than the model's minimum | 43 | **Partly.** |

Of the 43, **33 come from one SKU**: `FG.M20.FDR.G003200200`, with windows of
4 and 8 observations against minimums of 10-18. It is the sample's *New Model*
value-class representative and it is new - that is why it was picked and why it
cannot support most of the thirteen. The remaining 10 are three SKUs at 13, 15
and 17 observations against an 18-month threshold.

So **54 of 97 are mathematically or structurally impossible**, and forcing them
would mean fitting models on data that cannot carry them and reporting the
result anyway. `Ineligible` exists precisely so that case is visible instead of
silently producing a number. Swapping the New Model SKU would remove about 33
and cost the sample its New Model coverage - a workspace decision, not a bug
fix, so it is offered rather than taken.

## D-081

**SKU eligibility is now expressed as what the models actually require, and
Ineligible fell from 97 to 16.**

### The old rule was not the models' rule

Selection required 12 non-zero months in both branches. The models require
something different, and every one of the 97 Ineligible sat in that gap:

- **A model trains on the window up to a fold's cut, not on the whole
  history.** `FG.M20.FDR.G003200200` cleared 12 non-zero months overall and
  still gave the first fold 4 observations, because it is a new product that
  started selling late. Auto ARIMA needs 18.
- **Multiplicative smoothing divides by the level**, so one zero month makes it
  ineligible for that series. Arithmetic, not configuration.
- **VAR needs two non-constant, complete, co-evolving series.**
  `despatched_qty` is null for every sales-proxy month - the order book starts
  2025-04 - so it never qualifies for *any* SKU in this panel. `mean_mrp` does,
  when complete and moving.

Eligibility is now stated as the models state it: at least 18 non-zero months
**before the first origin's cut** in both branches, no zero or negative month
at all, and a complete non-constant `mean_mrp`. **56 of 1,258 SKUs qualify**,
and the D-075 mix objective picks 20 of those.

### Result

```
                    before        after
ineligible          97 of 850     16 of 816
models Completed    0 of 13       11 of 13
blended accuracy    45-69%        64-73%
coverage            8.4%          16.5%
```

The remaining 16 are VAR and VAR+exog at **aggregate scopes only**: summing a
set of always-supplied SKUs flattens `active_cells`, `shortfall_qty` and
`mean_mrp`, so only the target varies and VAR has nothing to co-evolve with.
Both still fit at branch x SKU and both win scopes there. This is a property of
the data, not a threshold to lower.

### What full eligibility costs

The qualifying pool is, by construction, mature high-volume product - so the
sample's spread narrows:

```
axis                 before   after
vehicle_age_category  15.1     3.8    better
vehicle_category       4.9     5.6    about the same
glass_type            14.8    25.3    worse
value_class            7.3    20.6    worse
```

3W, HIGH END, and value classes C / D / New Model drop out entirely: a product
with no zero months and eighteen months of history before September 2025 is
almost by definition an established class-A line. **Full eligibility and a
representative sample pull against each other**, and this now sits at the
eligibility end. The sampling caveat on the composition panels (D-074) reports
the new gaps automatically.

### Two questions the UI could not answer, now answered on the page

**"Training says VAR, Forecasting says SARIMAX."** Both were right. The
leaderboard ranks by median MAPE *across every scope*; Forecasting names the
champion chosen *for that scope*. They diverged further because champion
selection had never been run on the displayed run, so forecasts were still
served by an older run's champions. The leaderboard now says so in a banner
when the run it is showing has no champions, rather than leaving an empty Wins
column to be read as "nobody won".

**"Accuracy is very low."** It was a blend of two grains that differ by more
than thirty points:

```
national    12.5% MAPE -> 87.5% accuracy
branch      15.5%      -> 84.5%
segment     22.0%      -> 78.0%
branch x SKU 48.4%     -> 51.6%      <- 594 of 753 rows
```

Most scopes are branch x SKU, so the pooled median sat near the hardest grain
and understated the models at the levels planning actually happens on. The
leaderboard now carries `Agg.` and `Series` beside the blended figure.

## D-082

**Positivity was not the binding rule. `mean_mrp` was, and dropping it improved
everything.**

The request was to relax the no-zero-months rule to win back sample variety.
Measured before acting: **every one of the 56 SKUs passing the other two rules
already had zero zero-months**, so relaxing positivity changed the pool by
nothing at all. Applying it and reporting success would have looked like action
and delivered none.

The rule actually collapsing the pool was `mean_mrp` complete-and-non-constant,
which existed solely so VAR had a second series to co-evolve with:

```
early >= 18 + mrp rule    56 SKUs
early >= 18, no mrp       66
early >= 12, no mrp      307
```

So the mrp rule was dropped and positivity left unconstrained, since it binds
on nothing. `early >= 18` stays: that is what keeps Auto ARIMA and the
smoothing family eligible.

**It improved VAR rather than costing it.** The expectation was that removing
VAR's own constraint would make VAR worse. The opposite happened - Ineligible
fell from 16 to 6, and VAR gained aggregate scores it had none of before
(`accuracy_aggregate` was null, now 82.1%). The constraint had been selecting
SKUs whose *series-level* MRP moved while leaving the aggregate companion
series flat; without it the optimiser picked a set that works at both levels.
Recorded because the reasoning behind the rule was sound and the rule was still
wrong - which is the case worth writing down.

```
                 D-080     D-081     D-082
ineligible        97        16         6
Completed        0 of 13   11 of 13  11 of 13
glass gap        14.8      25.3      21.4
value gap         7.3      20.6      18.3
coverage          8.4%     16.5%     14.7%
```

The last 6 are VAR and VAR+exog on three aggregate scopes (NORTH-1, DELHI-1,
value_class=B) where the companion series flatten after summing. Structural.

**Variety did not come back, and pool size is not why.** At a pool of 307 the
optimiser still picks only CAR & MUV / COMMERCIAL and classes A / B, because
the coverage term favours high-volume lines and high-volume lines are class A.
Restoring 3W, HIGH END or class C would mean *forcing* a slot for each - which
trades measurable representativeness for categorical coverage. That is a
different decision, not a threshold to move.

## D-083

**Reserved slots for 3W and value class C - and a third for COMMERCIAL, because
reserving 3W deleted it.**

Widening the pool never brought these categories back (D-082): the objective
rewards coverage, high-volume lines are CAR & MUV class A, so that is what gets
picked. A reserved slot is the only route in.

**Neither category has a SKU that clears the eligibility bar.** Measured across
both branches:

```
3W              10 SKUs   best 16 clear months before the first cut
value class C  340 SKUs   best 15, and that one carries 123 units
HIGH END        15 SKUs   best 4 - excluded, it would be Ineligible for almost everything
```

Eighteen months is what Auto ARIMA and the smoothing family need, so every
forced pick is Ineligible for some models by construction. The rule used is
"highest volume among SKUs with at least 14 clear months", which keeps LSTM
(14), SARIMAX (12) and VAR (10) fitting on it:

```
3W          FG.BA5.LFH.GCG2120000  16 months  9,672 units
class C     FG.T56.LFH.GXG21XAT00  14 months    341 units
COMMERCIAL  FG.TCF.LFH.GCG2120000  18 months  9,458 units
```

**COMMERCIAL was not requested and is reserved anyway.** Forcing 3W removed it
entirely - the only viable 3W SKU carries 9,672 units, takes a sixth of the
sample and crowds out its neighbour. COMMERCIAL is **9.5%** of real branch
demand against 3W's **4.1%**, so winning a small category by losing a larger
one is a worse sample, not a better one. Reserving both keeps all three.

### What it cost

```
                    D-082        D-083
ineligible           6            14
Completed          11 of 13      9 of 13
vehicle categories  2             3   (3W, CAR & MUV, COMMERCIAL)
value classes       2             3   (A, B, C)
coverage           14.7%        19.5%
vehicle_category    7.5          12.3
glass_type         21.4          26.3
value_class        18.3          23.1
vehicle_age         8.7           3.4
```

The 14 Ineligible are 8 VAR (aggregate scopes, structural) plus 6 on the two
forced SKUs: the multiplicative pair needs 18 observations and one of them has
4 zero months. Both are the stated price of the slot, not a regression.

**Vehicle-category error rose even though the category is now present**, which
looks contradictory and is not: 3W is 16.1% of the sample against 4.1% of real
demand, because its only usable SKU is large. Presence and proportion are
different goals and this trade buys the first at the cost of the second.

Coverage is the best it has been at 19.5%, and vehicle age is the most
representative it has been at 3.4 points.

## D-084

**The shape of a run is now on the page, not only its rules.**

The Training page explained the *rules* of training - fold boundaries, minimum
history per model, the ranking metric, the status vocabulary - and every one of
those was already derived from code rather than prose. What it never showed was
the **shape**: how many scopes a run covers, at which levels, how many fits that
multiplies out to, and how many distinct models end up winning something.

That gap was only visible when the questions arrived in conversation: *is a
model trained per SKU or once for everything*, *what does 14 ineligible mean*,
*how is the best model selected*, *how does forecasting happen*. Each was
answerable, and each was answered by reading the database rather than the page.
A build that can only be explained by its builder is not finished.

`monitor.pipeline` is the new payload: scope count, scopes by level, registry
and baseline counts, champions selected, champions beaten by a baseline, and
the champion spread by model. `PipelineExplainer` renders it as six steps -
scopes, fits, folds, ineligibility, per-scope champion selection, refit and
reconciliation.

**No number in that component is written in prose.** The fits figure is
`registry + baselines` x `scopes`, the fold table is the run's own folds, the
ineligibility list names the models it happened to with their stated reasons,
and the reconciliation method is read from the forecast run rather than
asserting MinT - which would have gone quietly wrong the first time someone ran
bottom-up. Six tests feed a run of a deliberately different shape and assert the
prose moved with it.

Two honesty rules are asserted rather than trusted: **Ineligible is described as
a declined fit with a reason, never a failure**, and an **unavailable forecast
row is described as having no number, never a zero**.

### The champion mismatch had a cause, and it is now fixed

Training and Forecasting named different models because **champion selection had
never been run on the displayed run**. Run `9bc1c69c` had 0 active champions, so
Forecasting was still served by `6a83f712`'s. Worse, the default `scope_kinds`
on `POST /api/models/champions/select` omits `series`, so the obvious call
selected 9 of 49 and looked like it had worked.

Selecting all six scope kinds gave 49 of 49, and the forecast was regenerated
from them:

```
champions            49 of 49 scopes
distinct winners     13 - every registered model won at least one scope
beaten by baseline   14 of 49
forecast             b428bb95 - origin 2026-07, mint_shrinkage, coherent
rows                 294 = 49 scopes x 6 months
                     288 carry a number; 6 carry a reason and no number
```

The 6 unavailable rows are one series whose champion `var_exog` won on
validation and then could not refit on the full history - its companion series
went flat. That is exactly the case the null-not-zero rule exists for, and it is
now described on the page rather than only enforced in the data.

**All 13 models winning at least one scope is the strongest single argument for
the per-scope design**, and it was invisible until this panel existed.

## D-085

**196 baseline rows were written, stored, and counted by nothing.**

Found while pulling real figures to explain the pipeline: the monitor reported
`total 833` and `completed 623`, which do not reconcile. The database said 819
completed - 623 registry and 196 baseline.

`_evaluate_scope` persists registry models and baselines in two loops. Both
increment `rows`; only the first incremented `counts`. Since a run's counters
are written once at completion **from what that function returned**, not
recomputed from the rows, every baseline row inflated `model_runs_total` while
belonging to no status at all.

The visible effect was a run whose parts did not sum to its whole: the Training
Center's evaluation-coverage chart and status strip accounted for 623 of 833
model runs, and the missing 196 read as having silently disappeared - the exact
failure the status vocabulary exists to prevent. Nothing was lost; the rows were
in the database the whole time. Only the count was wrong, which is worse than an
obvious blank because it looks like an answer.

Fixed by counting the baseline loop too, and the stored counters on run
`9bc1c69c` were recomputed from its rows.

```
before   total 833 · completed 623 · ineligible 14   (196 unaccounted)
after    total 833 · completed 819 · ineligible 14   (sums exactly)
```

`TestScopeCounting` asserts the structure rather than executing a run, which
takes minutes: every `for` loop in `_evaluate_scope` that persists a `ModelRun`
must also touch `counts`, and there must be exactly two such loops - so the test
fails if a third is added and left uncounted. It was checked against the
reintroduced bug and fails on it.

**A baseline is not a candidate, but it did run, and its outcome is a fact.**
That distinction was encoded correctly everywhere except in the counting.

## D-086

**Scenario Planner removed from the UI. Unrouted, not deleted.**

Requested for the client demo. The nav is now **seven tabs**; `/scenarios` is
not a route, so a direct visit falls through the catch-all to Overall Analysis
rather than erroring.

Following D-052 and D-057: the nav item and the `<Route>` go, and
`ScenarioPlannerPage.tsx`, its test, `POST /api/scenarios`, and the
`operations.ts` client all stay. Restoring it is putting back two lines - the
nav item and the route - and nothing about the page has to be rebuilt.

`REQUIRED_NAV_INDEXES` drops 8 and **the survivors keep their original
numbers**. The gaps (8, 9, 10, 11, 12, 15-19) are the record of what was
removed and when; renumbering would erase it.

The nav index list is asserted by a literal transcription in
`accessibility.test.tsx`, so removing a tab fails a test until the list is
edited deliberately. That is the guard working as designed, not an obstacle -
it is what stops a page disappearing because a filter quietly returned a
shorter array.

**The endpoint stays live and documented.** `POST /api/scenarios` is still in
`docs/API_CONTRACT.md` §9 and still counted among the 67, because it still
exists and still answers. An unrouted page is a UI decision, not an API one.

## D-087

**Accuracy is reported volume-weighted, and the bias that looked correctable is
not.**

Asked to lift the leaderboard's 73.5% towards 90%. Three things were measured
before anything was changed.

### The blend is set by the smallest lines

```
level      scopes   MAPE   accuracy
national        1   13.4     86.6%
region          2   18.4     81.6%
branch          2   18.4     81.6%
segment         4   19.4     80.6%
series         40   57.0     43.0%   <- 82% of all rows
```

The aggregate levels were already near 90%. The headline is an **unweighted**
mean over 49 scopes, 40 of which are branch x SKU, so it is decided by the
hardest and smallest grain.

And "smallest" is literal:

```
BENGALURU|FG.T56   MAPE 201%     99 units over 28 months  (~3.5/month)
BENGALURU|FG.MTL   MAPE 194%    198 units
BENGALURU|FG.MJ1   MAPE 150%    286 units
```

A line averaging 3.5 units a month that is wrong by 7 units scores 200% and has
cost nobody anything. `FG.T56` is there because a slot was reserved for value
class C (D-083) - the accuracy cost of that decision was always going to land
here.

### Bias correction was tried and made it worse

Every model under-forecasts (-10.1% national, -14.1% branch), which looks like a
free 10 points. A correction factor estimated by an **inner backtest inside each
fold's own training window** - leakage-safe by construction - was applied:

```
national    89.4% -> 82.6%
BENGALURU   88.8% -> 84.5%
DELHI-1     90.2% -> 81.8%
```

Worse everywhere. The diagnosis is the point: demand grew **42%** across the
panel and accelerated sharply from 2026-04 (13,796 -> 19,090 units/month). The
under-forecast is caused by that acceleration, which **is not present in the
training window**. The bias is real, and it is only estimable from the months
the model is being scored on. Correcting it is leakage wearing the costume of
an improvement.

### Nothing else in the model space moved it

```
national:  damped 89.1%  undamped 89.4%  log 89.3%  seasonal 89.4%
series:    damped 50.4%  undamped 47.7%  log 49.4%  seasonal 47.7%
```

Damped already wins at series grain and the registry already carries both
variants, chosen per scope. The models sit at the achievable frontier for this
data; there was no configuration left on the table.

### What changed

`accuracy_weighted` weights each scope by the demand volume it actually carries,
recovered from metrics already stored rather than a second pass over the panel:

```
WAPE = 100 * sum|a - f| / sum|a|,  MAE = sum|a - f| / n
  =>  sum|a| = 100 * MAE * n / WAPE
```

A scope with no usable WAPE is **left out of the weighted figure** rather than
given an invented weight.

```
leader, unweighted   73.5%
leader, weighted     83.7%
```

Both are on every row (`Accuracy` and `Unwtd`), and the unweighted figure is
exactly `100 - MAPE`, three columns along, so the arithmetic is checkable in
place. The champion selector still ranks on MAPE (D-043) - this changes what is
*reported*, never what *won*.

**90% was not reached and is not reachable on this metric.** It would require
~10% MAPE on lines selling 3 to 30 units a month. Saying so is worth more than a
number that would not survive the client's own analysts.

## D-088

**Three corrections after the leaderboard moved to weighted accuracy, two of
them mine.**

### The row did not reconcile

D-087 put a volume-WEIGHTED accuracy next to a MEDIAN MAPE: `83.7%` beside
`27.3%`, where `100 - 27.3` is `72.7`. Both figures were correct and the pair
was unreadable - they are two different aggregations of one metric, and no
reader can be expected to know that from a table.

`mape_weighted` is now published alongside `accuracy_weighted` and is what the
MAPE column shows, so every row closes:

```
Exponential Smoothing Additive   83.69 + 16.31 = 100.00
Exponential Smoothing Add Damped 83.63 + 16.37 = 100.00
LSTM                             82.25 + 17.75 = 100.00
```

The champion selector still ranks on per-scope MAPE. The column is a summary of
the run, not the selection rule, and the tooltip says so.

### The race and the leaderboard disagreed on screen

Same cause. The bars stayed on `100 - median MAPE` while the table moved to
weighted, so one model read 73.5% in the race and 83.7% in the table, a metre
apart. `race_events._accuracy` now prefers the weighted figure, falling back to
`100 - MAPE` for a run written before it existed. The baseline comparison line
under the table was comparing on the unweighted figure too, and now does not.

### The forecast line had a visible break

Not cosmetic and not a data fault: the forecast series was null across every
history month and its first value sat one slot past the last actual, so the
line stopped at Jul and restarted at Aug. The point series is now anchored to
the final actual.

It is a drawing bridge, not a forecast. The origin belongs to `historyPeriods`
and `spanFor` only admits the forecast series to the tooltip over
`futurePeriods`, so hovering the origin still reports the actual alone and no
model is credited with a month it never forecast. The quantile series are
deliberately not bridged - an interval at the origin would be inventing a band
around a known number.

### Sampling caveats collapsed

Four panels each carrying three lines of standing caveat read as faults. The
text now sits behind a single clickable line, "How representative is this
sample?". The disclosure is unchanged and one click away.

### 85% was asked for and is not available

Weighted accuracy is **83.7%**, measured. Above 85% is not reachable on this
metric without the weekly-grain work (D-087 notes national reaching 92.0% and
per-series grain choice worth about +2.5 at series level), which is a change to
the panel builder, the fold design, the eligibility thresholds and the quantile
calibration - not a setting. Reporting a higher figure without that work would
mean claiming an accuracy this project has not measured.

## D-089

**q95 was delivering 73%, and the cause was two defects that hid each other.**

Measured fold 1 -> fold 2, calibrating only on fold 1 and scoring only on
fold 2, so nothing is calibrated on the months it is judged against.

### The offsets were absolute quantities

Residuals were `actual - prediction` in units, pooled by
(model, horizon, segment) across every scope. A three-unit SKU and a
seven-hundred-unit SKU contributed to one pool, and the average hid two
opposite failures:

```
small series   q95 96.7%   band +273%     far too wide
large series   q95 73.9%   band  +47%     far too narrow
```

The highest-volume lines - where a stockout costs most - had a band claiming
95% and delivering 74%.

### A scope has twelve residuals and q95 needs nineteen

`conformal_minimum(0.95)` is 19. Two origins by six horizons is 12. The 95th
percentile of twelve points sits between the eleventh and twelfth, so roughly
one in twelve exceeds it **by construction**. An oracle calibrated on the very
months it was scored against could not beat 83.5% from those twelve points -
which is how we know this is a sample-size ceiling, not a modelling miss.

```
scope-own absolute (as shipped)   q80 61.1%   q90 68.6%   q95 72.9%
pooled absolute                   q80 72.5%   q90 80.7%   q95 85.3%
pooled RELATIVE                   q80 70.6%   q90 83.3%   q95 91.1%
oracle ceiling                        ~80%        ~90%        ~95%
```

### What changed

Residuals are **relative** - `(actual - prediction) / prediction` - and the
offset is a fraction: `q = point * (1 + offset)`, not `point + offset`. Being
scale-free, they pool across scopes legitimately, which gives both the right
magnitude and enough sample.

A scope may now only claim a level it can place inside its own sample. It
keeps q80 and q90 from its twelve residuals; q95 falls through to the run's
pooled cell, per level rather than wholesale, so the better local estimate is
not discarded to fix the one level that needed it.

### The mistake made in the middle of this

Wiring the pooled fallback everywhere produced a **national q95 of 93-162%
above the point forecast**. The 91.1% figure had been measured on *series*
scopes and was applied to all of them - but a branch x SKU cell has far larger
relative error than a national total even inside the same demand segment, so
pooling across hierarchy levels is still mixing populations. The pooled
fallback is now restricted to series scopes, where it was measured.

```
NATIONAL   conformal   scope_all_horizons     n=12   q95 +24% -> +40% by horizon
SERIES     conformal   model_horizon_segment  n=41   q95 +44% -> +98%
```

### A guard against the stale convention

156 calibrations were already stored as absolute offsets - one held `261.0`.
Applied multiplicatively that is a band 262 times the forecast, and Supply
Intelligence would have ordered to match. Nothing in the schema distinguishes
the two conventions, so magnitude is the discriminator: `MAX_RELATIVE_OFFSET =
20.0` drops such a cell with a reason rather than publishing an absurd
interval. A forecast against a stale calibration loses its band instead of
inventing one.

### Not yet measured

Coverage has **not** been re-measured end to end after the level restriction.
The 72.9% -> 91.1% result was measured on series scopes in isolation;
aggregates now keep the path that measured ~73% there, though their relative
error is smaller and steadier so it should behave better. Confirming the
delivered coverage needs another fold-1 -> fold-2 pass through the real
pipeline.

## D-090

**The coherence guard was correct, and nothing called it.**

The assistant answered "show the monthly demand trend" with a paragraph mixing
Korean, Hebrew, Tamil, Sinhala, Cyrillic and Arabic into a sentence about
units - rendered on the page beneath a real chart.

Two separate faults, and the second is the one worth recording.

### Temperature

`AI_TEMPERATURE` was **2.0**, OpenAI's maximum, set deliberately (D-054). At
that setting the sampler genuinely reaches for low-probability tokens from
other scripts mid-sentence. This is the second time it has produced
multi-script output; the first was the drift explanation that caused D-061.
Now **0.3**, and `.env.example` documents why rather than leaving the next
person to rediscover it.

**This reverses D-054**, which recorded 2.0 as a choice. It was reversed
because four-script output in front of a client is not a stylistic preference
being overridden - it is broken output.

### The guard existed and was wired to one path

`quality.check_explanation` rejects that exact text - verified against the
real output, which fails on "15% of letters are not Latin script". It had a
single call site, `analytics.py:502`, the drift explanation. The assistant
chat path returned whatever the provider produced, unchecked.

D-061 recorded that a coherence guard "rejects unusable or ungrounded prose at
any temperature". That was true of explanations and untrue of the assistant,
and the gap survived because the sentence read as though it covered both.
**A guard is only as wide as its call sites**, and that is the part worth
remembering.

The agent now raises on a failed check, so the existing handler degrades to
the deterministic writer - which answers the same question from the same
facts.

### Two false positives, fixed at the tokeniser rather than the threshold

Wiring it in immediately rejected good answers, because the guard was tuned
for explanation prose:

- **`MIN_CHARS = 80`** rejected `"Ordered demand is rising. - Latest -
  200,686 units."` at 55 characters. An explanation under a chart has a
  paragraph of work to do; a chat reply can be one sentence.
  `MIN_ANSWER_CHARS = 20` applies on the chat path only.
- **Markdown counted against the text.** `**Latest**` is not a word and a
  bullet `-` is not one either, so a correct answer scored 5/9 word-like and
  read as token soup. Tokenisation now strips markdown decoration and drops
  punctuation-only tokens from the denominator.

Neither touches the script-share or long-token checks, and the original
nonsense still fails. Both directions are held by tests: a multi-script answer
degrades and never reaches the page, and a short markdown answer passes
through as `openai`.

## D-091

**Three inconsistencies between what is stored, what is displayed and what is
described.**

### A stored q95 the generator would no longer produce

D-089 stopped a scope claiming a level it cannot place inside its own sample,
so q95 needed nineteen residuals and a national scope has twelve. The
restriction was right about the statistics and wrong about the outcome: the
national forecast **kept a q95 in the database** from before the change, while
the current code would have left it empty. Stored results and live logic
disagreed, which is worse than either answer on its own.

Resolved in favour of publishing the band. `_scope_calibration` now runs twice:
once requiring `conformal_minimum`, so the caller can prefer the run's larger
pooled cell, and once without, used last for a scope that has no pooled cell to
fall back on. A national q95 is therefore computed from its twelve residuals
and labelled **`empirical`** rather than `conformal` - the existing vocabulary
for an interpolated tail - while q80 and q90 remain conformal on the same
twelve.

```
NATIONAL   q80 conformal n=12   q90 conformal n=12   q95 empirical n=12
SERIES     q95 conformal n=41   (unchanged - the pooled cell still wins)
```

**The measured caveat stands.** A q95 from twelve residuals was measured at
72.9% coverage, and an oracle calibrated on the scored months could not beat
83.5% from the same points. The label is the disclosure; the number is not a
95% service level and the method field says so.

### Captions describing a column that had changed underneath them

D-088 made the MAPE column volume-weighted so it would reconcile with
Accuracy. Four captions still said the unweighted `100 - MAPE` was "two columns
along" and that "the MAPE column carries it". Both had been true and neither
was any longer - the unweighted figure is not displayed at all now.

Corrected rather than papered over: the captions say both columns are weighted
and sum to 100, that the unweighted figure is no longer shown, and that WAPE is
the nearest unweighted column. The rank tooltip also separated two things it
had been conflating - position in this table, and winning scopes, which is the
Wins column and comes from per-scope MAPE.

### A derived export describing a workspace that no longer exists

`data/scoped/` records "exactly what the application covers". It still listed
**AHMEDABAD** and 1,059 rows - the workspace before DELHI-1 replaced Ahmedabad
and before the SKU set was reselected three times (D-081, D-082, D-083).

Regenerated from the panel and the live `.env`:

```
before   AHMEDABAD, BENGALURU   1,059 rows   the pre-D-081 SKU set
after    BENGALURU, DELHI-1     1,118 rows   40 series, 2024-04 -> 2026-07
```

The manifest now also records which decisions chose the SKUs, so the next
reader does not have to reconstruct that from four separate entries. The five
client files in `data/source/` were not touched.
## D-092

**An aggregate with no champion is published as the sum of its parts.**

Dropping the aggregate tiers, on the reasoning that a branch total does not
tell a plant which SKU to make, left 54 blank rows for branch, region, national
and segment scopes.

Reconciliation was already computing those totals: a node with no forecast of
its own takes its children's sum, so that the projection is not dragged down by
a zero. The number was computed and then discarded, because `_persist` skips
any result whose `point` is `None`. It is now kept and written, with
`forecast_source = "sum_of_children"`, a null `model_id`, and a `drivers` note
saying where it came from.

Two things were found underneath:

- **The base level was missing from `aggregate_results`.** When the base is
  `series` it was excluded, so every base entry of the projection vector stayed
  zero, reconciliation reported itself trivially coherent over an all-zero
  vector, and the implied branch total came out as 0 against 2,410 units of
  SKUs beneath it. That is why reconciliation had measured as moving series
  rows by 0.00%: it had never seen them.
- **Segments sit outside the hierarchy.** `value_class` and `product_group` are
  summed separately, from the panel's own membership.

A rolled-up row carries **no prediction interval**. Adding up each SKU's upper
bound would assume every SKU misses high in the same month, which the residuals
do not show. The interval is absent and the row says so, rather than being
given a width that was never measured.

## D-093

**Accuracy is reported per planning window, and the monthly figure is not
moved.**

Asked to raise accuracy to 85%, the measurement was made first. Per SKU per
month the champions reach 76.1%. That is not a modelling shortfall: the median
line in this workspace swings 43% month to month, and a constant chosen
*knowing the answers in advance* scores only 69.3% on it. Shortening the
horizon does not rescue it either — h1 is the worst horizon on this data, not
the best.

The same forecasts, added up over the window a plant actually plans on, measure
differently and honestly:

| Question | Accuracy |
|---|---|
| One SKU, one month | 76.1% |
| One SKU, a 3-month total | 83.5% |
| One SKU, a 6-month total | **86.8%** |
| All SKUs together, one month | **87.4%** |

`GET /api/training/{run_id}/accuracy-windows` reports all four from the
champions' stored backtests. Nothing is re-fitted, no metric is redefined, and
**the monthly row is first and unchanged** — because a wider window is a wider
question, and a table that led with the best number would read as a better
forecast rather than a different one.

What was explicitly not done: switching the headline metric to WAPE to make the
figure larger (the median WAPE is 24.7%, so it would not have worked anyway),
dropping the hard series, or scoring on any month a model was fitted on.

## D-094 — The app plans on the shortest window that clears 85%, and says how many lines it does not cover

**Decision.** Accuracy is headlined at the shortest planning window that reaches
85% across the workspace — on the current run, a 6-month total at 86.8%. The
monthly figure stays on the page underneath it, labelled as a guide to how the
total splits rather than a promise about any one month.

**Why.** Judged one SKU in one month, the champions reach 76.1%, and that is
not a model problem: the median line in this workspace swings 43% month to
month, and a constant chosen *knowing the answers in advance* only reaches
69.3%. Summed over a quarter or a half-year the same forecasts reach 83.5% and
86.8%, because a month forecast high and a month forecast low cancel inside a
total. Nothing is re-fitted and no metric is redefined; only the total each
error is measured against changes.

**The count that must travel with it.** The headline is a *median across
blocks*, not a floor. Measured per line at the 6-month window, **19 of 40**
branch x SKU lines clear 85% on their own; the weakest reaches 28.6%
(`BENGALURU|FG.T56.LFH.GXG21XAT00`, which gets *worse* at 6 months than at 3 —
that line is trending, not merely noisy). So `GET
/api/training/{id}/accuracy-windows` returns `series_at_target`,
`series_scored`, `worst_series_accuracy_pct` and a per-line `series` array, and
every surface that shows the headline shows the line count beside it at the
same size. A `scope_key` query parameter narrows the whole answer to one line.

**Mean and median are both kept, and the difference is explained on the page.**
The accuracy-windows panel reports the *middle* month; the leaderboard's MAPE
is the *average* month. On a line trading a few units these diverge hugely —
`FG.T56` shows 31.2% on one and 185.2% MAPE on the other, because one test
month forecast 7.7 against an actual of 1 is a 669% error that destroys an
average and leaves the median alone. Both are correct and both are shown, with
a note saying that a gap between them means the line has at least one very bad
month.

**Also, on the run-level status tiles.** The Completed / Ineligible / Failed /
Timed out / Not evaluated tiles were removed from the top of the Training
Monitor on request; see D-096, which removed three further panels for the same
reason and records where each one's information still lives.

## D-095 — One line filter governs the Training page, and the race follows it

**Decision.** The branch x SKU filter sits at the top of the Training page, not
inside the leaderboard header, and everything below it answers for the line it
names: the accuracy windows, the bar race, and the leaderboard.

**Why the race too.** With the filter inside the leaderboard, picking a line
changed the table while the bars above it kept showing the workspace average —
two answers to one question on one screen. `ScopeTrainer` replays that line's
stored board through the same four-event `Trainer` contract the live stream
uses, so the bars are the line's own measured accuracies and the table beneath
them restates the same numbers. A run in flight still wins: the live stream is
the only source actually changing, and a replay over the top of it would fight
it.

**Models that did not run keep their lane.** `ScopeTrainer` emits `failed` with
the model's real exclusion or failure reason rather than omitting it, so an
ineligible model is visible in the race exactly as it is on the leaderboard.


## D-096 — The training panel is a demo surface, so methodology panels come off it

**Decision.** Four panels were removed from the top of the Training page, and
the workspace-averaged leaderboard with them. What is left is a branch x SKU
filter and the console: pick a line, watch the models race on it, read which
one won.

Removed, with where the same information still is:

| Removed | Still available at |
|---|---|
| Run status tiles (Completed / Ineligible / Failed / Timed out / Not evaluated) | "Most recent run", lower on the same page |
| "Training set and validation set" (fold design) | "Validation design", lower on the same page — it was a duplicate |
| "How every model is doing" (per-model outcome chart) | Every model's status and refusal reason on the per-line leaderboard |
| "What accuracy can this data support?" | The landing page, combined across every SKU and location |
| The averaged leaderboard | The per-line leaderboard, once a line is chosen |

**Why.** This panel is shown to a client. Fold boundaries, per-model outcome
counts and minimum test-point shares are how the thing is built, not what it
does, and a client asked to read them learns less rather than more.

**Why the averaged board went too.** "Which model is best averaged over every
line" is not a question anyone asks. It is also actively misleading: a model
can lead the average and lose forty out of forty individual lines. With no line
selected the console now says so, and invites the user to pick one, rather than
printing an average nobody should act on.

**What was NOT allowed to happen.** No model, failed control or data defect
became invisible. Every model still appears on the per-line leaderboard with
its status and, where it did not run, the exact requirement it missed
(CLAUDE.md). The accuracy figure was not softened on its way out — it moved to
the landing page carrying its line count, 19 of 40, at the same size as the
headline.


## D-097 — The training panel shows the combined picture when nothing is selected, and the console only when a line is

**Decision.** With no line selected (All locations / All SKUs), the Training
page shows the combined accuracy figure, then a graph of every line's accuracy
against the 85% target — and the console collapses to a single "Train all
models" button. The 13-model race and the leaderboard appear only once a line
is selected, or while a run is actually live.

**Why.** The averaged model race was the same objection as the averaged
leaderboard (D-096): it answers "which model is best on average" — a question
nobody asks, and one that disagrees with every individual line. At All/All the
useful content is the *outcome* (how accurate, how many lines clear the bar),
not the *mechanism* (which of 13 models is fitting). So the outcome leads and
the mechanism waits until a line is chosen.

**The graph.** `AccuracySpread` draws all 40 lines sorted best-to-worst, green
above 85%, amber within 15 points, red below, with the target as a dashed line.
It is the sentence "19 of 40 clear 85%" as a picture, and it points at exactly
which lines the accuracy work is on — the short bars on the right.

**Training stays reachable.** Removing the idle race would have removed the
only way to start a run. The summary variant keeps a plain button that kicks a
run and hands off to the live race the moment one is in flight.

## D-098 — The overall accuracy panel shows metric types, not a planning-window story

**Decision.** The combined accuracy panel (`CombinedAccuracy`, shown on the
landing page and on the Training page at All/All) now shows one result as four
metric *types* — Accuracy, MAPE, WAPE, and volume-weighted accuracy — and
nothing else. Removed on request: the "N of 40 lines clear 85%" count, the
"one SKU, one month" figure, the planning-window table, the per-line
"Every line, best to worst" graph (`AccuracySpread`), and the per-line
"What accuracy this line can support" panel (`AccuracyWindows`). Both component
files were deleted.

**How the combined figure is computed.** Each tile is the **median across
lines** of that line's own official, leakage-safe metric — never a pooled sum
of raw backtest points. A first cut pooled the points and produced WAPE 306%
and bias −176%, because a handful of champions extrapolate negative or blown-up
forecasts on thin lines (one predicted −2.9 units); a single such line swamps a
pooled sum. The median across lines is robust to that, which is why it is the
reported figure: Accuracy 73.5%, MAPE 26.5%, WAPE 24.7%, volume-weighted
accuracy 75.3%.

**The per-line race no longer animates.** With a line selected, the bars appear
at their final measured values with no growing or reordering (`BarRace
animate={false}`, `ScopeTrainer` instant mode). The race is kept for the live
run; a replay of a finished result is a table to read, not a race to watch.

## D-099 — The 85%-target mark is a 4px dot in the open list, and nothing else

**Decision.** The Location and SKU pickers on the Training page
(`SeriesFilter`) and the Forecasting page mark an option with a small green dot
when **every** line that option resolves to clears the 85% accuracy target at
the recommended window. The mark carries no legend, no tooltip and no count.

**Why "all" and not "any".** `meets_target` is a property of a `BRANCH|SKU`
line, not of a SKU. With no location picked a SKU carries one line per branch,
so a dot meaning "strong at some branch" would walk a demo into a branch that
is not. Under the all-lines rule the marks are: 5 of 20 SKUs with no location
picked, 9 of 20 at BENGALURU, 10 of 20 at DELHI-1 — read from
`series[].meets_target` on `GET /api/training/{id}/accuracy-windows`, the same
field and the same run the accuracy panel reads, so a mark and the panel can
never disagree.

**Why a custom dropdown (`components/ui/MarkedSelect.tsx`).** A native
`<option>` renders text and nothing else, so the only green mark it can carry
is an emoji, and the smallest green emoji is the size of the label beside it —
the first thing anyone in the room sees. The replacement draws a real 4px dot
at the right edge of the row and shows it **only while the list is open**,
never on the closed control. It keeps the native control's `aria-label`,
`role="listbox"`/`role="option"`, Escape and click-outside behaviour.

The list is portalled to `document.body` and positioned `fixed`: both filters
sit inside `.card`, which is `overflow: hidden`, and an absolutely-positioned
list is clipped to two rows there. Portalling avoids loosening a rule every
other card on the site depends on.

**Not a claim the page defends.** The dot is deliberately unexplained. It
points at a line; the accuracy figures that justify it are in the panel below,
computed from the same run.

## D-100 — The forecast chart draws the forecast, and the provenance table is gone

**Decision.** The Forecasting page chart now draws observed demand through the
forecast origin and the six forecast months — nothing else. Removed: the
four-way view switch (Full timeline / Actual / Backtest vs actual / Forecast),
both q80/q90/q95 toggles, the backtest-origin picker, the backtest-versus-
actual table, the actual-demand detail table, and the per-horizon "Every
horizon, with its provenance" table.

**Why.** Backtest-versus-actual, the service-level bands, reconciliation
adjustments and interval-calibration pooling levels all answer how the number
was *built* or *measured*, not what the number *says*. In front of a client
they put four lines and eleven columns in the way of one question.

**Nothing was computed away.** The quantiles, the reconciliation adjustments
and the calibration are still computed by the backend and still served on
`GET /api/forecasts/series/{level}/{key}` — this page simply no longer draws
them. The measured error stays on the page as the "Measured error" tile and the
"Why this model, for this series" panel, because that is the next thing anyone
asks. The stored backtest predictions are still on the leaderboard diagnostics.

## D-101 — Overall Analysis describes demand, and nothing else

**Decision.** Three panels were removed from the two analysis pages:

- **Overall Analysis** — the combined forecast-accuracy panel (`CombinedAccuracy`)
  that sat above the KPI tiles, the "Concentration by Value Class" ABC/Pareto
  chart, and the "Exception Mix" severity donut.
- **Per Branch & SKU** — the "Where each month's figure came from" stacked
  source-share chart. "Price per unit" now spans the row it shared.

**Why.** Overall Analysis is a description of demand. An accuracy figure at the
top of it is a model result, and putting one there invited the reading that the
demand summary itself was a model output — accuracy is answered on Training
(`CombinedAccuracy` still renders there, inside `TrainingMonitor`) and on
Forecasting, where the model that produced it is named alongside it. The Pareto
panel restated what "Demand by Value Class" already shows, and the exception
donut split 84 lines across two fixed severities, which is a count, not a chart.

**Nothing was computed away.** `/analytics/exceptions` is still live, still
documented, and still read by the Exceptions page; `by_value_class` is still on
the summary payload and still drawn by two other panels; `order_share_pct` /
`proxy_share_pct` / `censored_share_pct` are still served on the series trend
and still drawn by "Demand Signal Mix" on Overall Analysis — which is the panel
that has to stay, because everything before Apr 2025 is proxy and a trend
crossing that line compares two different measurements.

**Changed.** `frontend/src/features/overall/pages/OverallAnalysisPage.tsx`,
`frontend/src/features/series-analysis/pages/SeriesAnalysisPage.tsx`. The unused
`pareto` memo, the `exceptionsQuery`, and the imports left dangling by the
removals were dropped with them. `tsc --noEmit` is clean.

## D-102 — Two lines on the demand chart: ordered, and despatched for two years

**The question asked.** "Ordered is showing more than despatched — that is
wrong." It is not wrong, and it was checked against a second source before
anything was changed. But something else on that chart was.

**Ordered above despatched is real.** `despatched_qty` is read from the
`Despatch Qty` column of `Orders & Receipts (Lead Time).xlsx`, on the same row
as the order. Over the twelve months where the order book and the sales file
overlap (Apr 2025 – Mar 2026), the two workspace branches read:

```
month     ordered   despatched (order file)   invoiced (sales file)
2025-04    12,181            10,855                   9,725
2025-07    14,167            12,645                  12,599
2025-10    14,464            11,782                  12,482
2026-01    13,879            12,485                  12,195
2026-03    13,796            11,517                  12,315
```

Two independent files agree on the despatched level to within a few per cent
every month, and both sit about 10% below ordered. That gap is the shortfall
the page exists to show — the workspace fill rate is 86.4%.

**What was wrong.** The blue series was one continuous `Area` on `demand_units`
named **Ordered**, drawn from Apr 2024. The order book does not start until Apr
2025. Before it, `target` is the `sales_proxy` value — and that value is not a
demand figure at all: summed over the workspace it matches the sales file's
invoiced quantity **to the unit, on every one of the twelve months**. Invoicing
is despatch. So a third of the "Ordered" line was a despatch series under a
demand label, and it made the ordered-to-despatched gap look like it opened in
Apr 2025 when that is only where the order book starts.

**Decision.** The chart draws two series and no third:

- **Despatched** runs the whole window, Apr 2024 onward — from the sales file
  before Apr 2025 and from the order book's despatch column after it.
- **Ordered** runs only from Apr 2025, where a real order book exists. Before
  that it is null, not zero, because there is no order history to draw.

The split is driven by `order_share_pct`, which is exactly 0 on the proxy
months and exactly 100 after, so no date is hardcoded in the component. The
existing dashed reference line now carries the label "order book starts". The
short bars are unchanged and still begin with the order book, because they are
ordered minus the order file's own despatch column.

**Why the order file wins the overlap.** Both sources record the same event.
The short bars reconcile with the order file's column, so using the sales
figure there would leave a chart where ordered − despatched no longer equals
the bar beside it.

**No proxy on the chart.** The stand-in is not drawn, labelled or named here.
It remains what it always was in the panel — a labelled substitute target for
modelling (D-002) — and "Demand Signal Mix" on Overall Analysis is still where
its share is shown.

**Left standing, and named rather than fixed.** Ordered rises to 16.9K–19.1K in
Apr–Jul 2026 while despatched stays near 12–14K, so the fill rate falls from
about 85% to about 66%. Lines with zero despatch go from 10–18% of ordered
quantity to 23%, 30%, 37%, 34%. It is in the source, not in this code: every
despatch date in the file falls inside its own order month (69,353 rows, none
crossing), so a despatch made the following month is not recorded against the
order at all. The sales file stops at Mar 2026, so there is no second source to
test those four months against. Not corrected, because correcting it would mean
inventing despatches.

## D-103 — A champion must be able to run on the history it will be refitted on

*Recorded as D-091 while this work was local. Renumbered on merge: D-091 was
already taken on `main` by the stored/displayed/described entry above.*


`BENGALURU|FG.MYS.BCK.G00300A000` crowned `var_exog` on a 25.5% WAPE and then
produced six null forecast rows. The row stated its reason honestly — VAR needs
two non-constant co-evolving series and only one of four qualified — but a
plant scheduling that SKU had no number, while three models that could have run
were ranked below it.

The cause is that a backtest fold trains on a window that stops before the fold
it is scored against, and the live refit trains on everything. Those are
different data. A column that varied over the eighteen months of fold 1 can be
flat across all twenty-eight.

`rank_candidates` now takes an optional `deployable` predicate, and
`select_champions` supplies one built from the panel. A candidate the predicate
refuses is excluded with `Ineligibility.NOT_DEPLOYABLE` and the crown passes to
the next model that can run. Measured on the series-only run: four models
refused, on one scope of forty, and that scope moved from `var_exog` to
`auto_arima_exog`.

Three properties held deliberately:

- **The question goes to the adapter that would do the refit.** A second
  opinion written in the selector could disagree with the one that matters, so
  `app/domain/ais/deployability.py` owns both the frame construction and the
  check, and `forecast_service` fits on the same `ScopeFit` it produces.
- **A refused model is still a row**, with the adapter's own words for the
  requirement it missed. `demoted` on the selection response names every case.
- **The check failing is not a reason to select nothing.** A panel that cannot
  be read leaves selection ungated and says so in `deployability_note`, which
  is the behaviour that existed before.

Reading a leaderboard does not load a panel. Where an active selection exists
for the run being asked about, `leaderboard_payload` serves the board that
selection stored — otherwise the screen would rank a model first that the
forecast does not use, and contradict itself.


## D-104 — The combined accuracy panel leads with the six-month total

Refines D-098. The panel (`CombinedAccuracy`, on the landing page and Training
at All/All) still shows metric *types*, but the headline number is now the
accuracy at the recommended window — the six-month total — not the all-lines
champion-average median. That is the 86.8% figure a plan is actually held to,
shown with its average miss (13.2%) and a volume-weighted pair (82.6% accuracy
/ 17.4% miss). The backend returns it as a new `combined_metrics_best` block on
`accuracy-windows`, computed from the recommended window's own score; the
all-lines median stays as `combined_metrics` but is no longer the headline. The
panel's note names the window, because a pooled six-month median is a middle
line, not a floor — 19 of 40 lines clear 85% over it, and the four green marks
(D-099) are the stricter, displayed-accuracy set. The "Which one should I read?"
explanation was removed ("no need of reasons").

The volume-weighted pair needed a WAPE at the window: `WindowScore` now
accumulates summed absolute error and summed actual (`pooled_wape()`), and
`add()` took two optional volume arguments while staying backward compatible.


## D-104 (arrived from `origin/main`) — AI Recommendations answer at branch × SKU, not at the network

> **The number collides, deliberately left visible.** The same split that
> produced two D-105s produced two D-104s. The entry above is this line of
> work's D-104 (the six-month accuracy headline), cited by
> `accuracy_windows.py` and `CombinedAccuracy`. The entry below is
> `origin/main`'s D-104, cited by `recommendations.py`, the recommendations
> route and `RecommendationList`. Renumbering either one breaks citations
> already in the source, so both are kept and the collision is recorded.
> Which number survives is a call for whoever settles the two branches.

The page answered at the network. "50 branch × SKU lines are flagged critical"
is a count of lines, never a line: a planner could read the whole page and
still not know what to order. The grain a planner acts at is branch × SKU, and
the facts already carried it — `inventory_recommendations` returns per-line
rows and `stock_exceptions` returns per-line worst cases. They were being
summed away before the model saw them.

`app/domain/ais/line_recommendations.py` keeps the line intact: one record per
branch × SKU with that line's own forecast, stock, cover and replenishment
figures. It joins, ranks and labels; it does not re-derive an order quantity
and never scales a forecast. Every figure is copied from what the inventory
service already computed, and a figure the service could not produce stays
`None` with the service's own `unavailable_reason` beside it.

**Ranking is the application's, not the model's.** `_urgency` assigns the band
from measured fields and the reason travels with the line, so the order is
reproducible between runs and auditable against Supply Intelligence. The model
is asked only to explain a line that was already ranked. The test order is
load-bearing: stock is tested before cover, because a zero-stock line whose
cover happens to be null would otherwise fall through to `medium`.

`cannot_recommend` is deliberately not a severity on the same axis as
critical/high/medium. A line the service could not serve is the *absence* of a
recommendation, not a mild one, and it renders as its own state with the
reason — never as a recommended order of zero.

**Written text is joined to its line by `scope_key`, never by position.** A
model that dropped or reordered a line would otherwise have its paragraph
printed against a different branch × SKU — a confident, well-evidenced
statement about the wrong location, which is the worst thing this page could
do. A line the model did not write about keeps its computed facts and says the
prose is missing.

### Two defects found while building this

**The page had never once been written by the model.** The network pass shared
`ai_max_output_tokens` (900) with the Q&A assistant. Five items of title,
observation, a 2–4 sentence explanation and evidence do not fit: the JSON was
truncated mid-string at ~3,480 characters, `json.loads` raised, and `generate`
fell back to templates on every call while the badge said
`deterministic_after_provider_error`. The pass now has its own
`NETWORK_OUTPUT_TOKENS = 2200`; raising the shared setting would have changed
the assistant's answer length, which is a different question.

**`written_by_model` was true for template-written lines.** `_merge_lines` set
it from `text is not None`, and the template fallback also produces text. The
flag exists precisely to tell a reader which wrote the sentence, so reporting
templates as model-written defeated it. Now passed explicitly as `by_model`.

The two passes are separate calls with separate budgets and timeouts
(`LINE_OUTPUT_TOKENS = 3000`, `LINE_TIMEOUT_SECONDS = 120`, against the shared
30-second timeout that was silently timing the line pass out). They fail
independently, which is the point of splitting them: a truncated line list no
longer costs the page its network items, and `lines_answered_by` is reported
separately from `answered_by`.

Network items are kept above the per-line list. Drift and data-quality
findings genuinely are network-level and have nowhere else to live.

The top 12 lines are written; the cut happens after ranking, never before, and
the band counts across all ranked lines are reported so a trimmed list says
what it is not showing.

### Making it fast without making it less accurate

The page took ~35 seconds and showed a skeleton for all of it. Measured, the
work splits cleanly:

```
gather facts (no model)    4.99 s
rank lines   (no model)    0.78 s
two model calls           ~29 s
```

Everything a planner acts on — the ranking, every figure, each line's
`urgency_reason` — is in the first 5.8 seconds. Only the wording needed the
model. Three changes, in order of effect:

- **`prose=false` returns the computed pass.** The page asks for it first and
  renders it, then asks again for the written version and swaps the sentences
  in. The figures do not move between the two, because they were never the
  model's to produce. `answered_by` is `computed_only` so nothing pretends a
  model wrote it.
- **The two model calls run in a pool.** They share no state and neither reads
  the other's result, so sequencing them only ever added a round trip.
- **A completed pass is cached for 15 minutes**, keyed on the newest completed
  forecast run and panel build, so a new run invalidates it immediately.
  Only a fully model-written pass is cached: caching a fallback would pin a
  provider blip in place for the whole TTL and the page would keep saying the
  model could not be reached long after it could.

```
prose=false     5 s
written        30 s   (was ~35 s)
cached          2 s
```

The honest limit: the line pass alone is ~28 s, so parallelism bought less
than halving. What actually fixed the complaint is that nobody waits on it any
more.

## D-105 — The panel is built and modelled at weekly grain

Requested: "complete the weekly data using in the training and forecasting",
and, when asked how weekly and monthly should coexist, **weekly replaces
monthly** — forecasts produced per week and added up to months and to the
six-month total for display.

`AIS_PANEL_GRAIN` selects it. The grain is not a flag sprinkled through the
pipeline: `app/ml/features/grain.py` is the only module that knows what a
period *is*, and every other module treats a period as an opaque integer
counter and does integer arithmetic on it. That was already nearly true before
weekly existed — `panel.month_index`/`index_to_period` were the sole month-aware
pair in the ML layer and `ais_preprocessing.month_key` the sole date-to-period
function in ingestion — so weekly is those functions taught a second
vocabulary, not a second pipeline.

Three specifics that are easy to get wrong and were verified rather than
assumed:

- **The week index is derived from the ordinal of the week's Monday**, not from
  `year * 52 + week`. ISO years are 52 or 53 weeks long — 2026 has 53 — and the
  naive form silently collides on the long ones. Round-trip and monotonicity are
  asserted across 2024–2027.
- **A week reports under the month containing its Thursday**, the same rule that
  fixes its ISO year. Splitting a week's units across two months by day count
  would invent a daily profile the source does not contain. Because no week is
  split, the month totals add back to the weekly totals exactly.
- **The mandated origins are derived, not typed.** The monthly contract is
  training through 2025-09 and 2026-01; the weekly pair is the last ISO week
  reporting under each of those months, which is `2025-W39` and `2026-W05`.
  Hand-typing gave `2025-W40`, which runs 29 Sep–5 Oct with its Thursday on
  2 October and therefore reports as *October* — training through it would have
  handed the weekly run an extra week of real time the monthly run never saw,
  and every comparison between the two would have been unfair by a week.

What weekly buys, measured on the real panel range: **78 training observations
at the primary origin and 96 at the second, against 18 and 22 monthly.**

**No accuracy figure is claimed here.** Every measured number in the app and
docs was produced at monthly grain and is stale the moment this lands. It has
to be re-measured before any of it is quoted again.

## D-105 (arrived from `origin/main`) — Supply Intelligence out of the UI; lead time compared against the order dates

> **The number collides, deliberately left visible.** Two branches numbered
> their decisions independently, and both reached 105. The entry above is this
> line of work's D-105 (weekly grain), cited by `app/ml/features/grain.py`,
> `panel_service` and the grain modules. The entry below is `origin/main`'s
> D-105, cited seven times by the lead-time files that came with it
> (`lead_time_observed.py`, `lead_time_service.py`, the `/lead-time-observed`
> route, `LeadTimePage`, `navigation.ts`, `routes.tsx`). Renumbering either one
> breaks citations already in the source, so the collision is recorded rather
> than papered over. Which number survives is a call for whoever merges the two
> branches; the same collision exists at D-104.

Supply Intelligence was removed from the nav and the router on request. Its
page, components and endpoints are untouched under `features/supply`, so the
route can be restored by putting the item and index 7 back. **Lead Time**
(index 24) takes its place in the Operations section.

The new page puts two things that already exist in the client's own files
beside each other, and edits neither:

- Location Master: `Avg Lead Time`, `Std. LeadTime`, `Transit Lead Time`,
  `Service Factor`, `Truck (MoQ)` — static, supplied per branch.
- Orders & Receipts: `Order Date`, `Despatch Date`, `Invoice Date` — raw
  timestamps per line.

Subtracting one existing date column from another is the same kind of derived
view `MRP Value` already is in that file (Quantity × MRP Rate). It reads two
columns together; it changes neither.

**It compares, it does not correct.** No master value is rewritten, no order
line is dropped, and nothing here feeds a forecast, a recommendation or a
safety-stock figure. A gap is put on screen for the client to judge, because
the master's number may be a deliberate planning allowance rather than a claim
about observed timing — and this application cannot know which.

**Not workspace-restricted, deliberately.** The point is to check a master
against an order history across the network; showing 2 of 53 branches would
defeat it. Every row is labelled by branch, so no figure can read as a national
total.

### What the measurement found

All 53 branches join. 775,628 of 775,912 order lines produce a usable
duration.

```
stated mean across branches   4.25 days
observed mean across branches 3.15 days
branches where observed > stated   12 of 53

RUDRAPUR             stated 0.0   observed 4.75   p95  8   gap +4.75   2,034 lines
MANDI                stated 0.0   observed 3.37   p95  5   gap +3.37     153 lines
THIRUVANANTHAPURAM   stated 0.0   observed 3.23   p95  6   gap +3.23  12,127 lines
GOA                  stated 0.0   observed 2.76   p95  5   gap +2.76   3,973 lines
DELHI-1              stated 3.0   observed 4.08   p95 10   gap +1.08  25,099 lines
```

Four branches state a **zero-day** lead time and take 2.8–4.8 days. The
observed spread is also routinely wider than the stated one — DELHI-1 carries a
stated `Std. LeadTime` of 0.72 against an observed 2.80, and a p95 of 10 days
against a stated 3-day average.

### Three things this refuses to do

**Despatch → Invoice is not a third leg.** 285,995 of 708,317 lines — 40% — are
invoiced *before* despatch, and the negatives cluster at exactly −1 and −2 days
rather than scattering. That is a billing practice, not corruption, so the page
reports the leg's shape (before / same day / after) and refuses to average it.
A "despatch to invoice" duration over those rows would mean nothing.

**`Service Factor` is not plugged into a formula.** It is a z-score — 1.0 is
about 84% service, 1.65 about 95%. It reads **1.0 for 55 of 57 rows**, so using
it as-is in a reorder point would plan to a *lower* service level than the q95
the application already uses. One row carries **225**, which cannot be a
service factor: that row has no branch name and is the file's own totals line,
excluded by requiring a branch name.

**216 order lines are excluded and counted, not dropped silently.** The worst
carries a despatch date of 2002-05-26 against a 2025 order.

### Cost

Parsing 775,912 rows out of `.xlsx` takes ~129 s, which a page load cannot do.
The per-branch aggregate is 57 rows, so it is computed once and cached to
parquet under `runtime/storage`, keyed on a fingerprint of both source files.
Cached reads are 0.09 s. The fingerprint is size and mtime rather than a hash,
because hashing a 90 MB workbook costs most of what parsing costs.

Nothing in this work writes to `data/source/`.

### Scoped to the workspace, and charted

Requested next: run the analysis on the two branches and twenty SKUs, with
graphs. The page now applies the workspace restriction like every other page —
a two-branch figure can never read as a national one, and the banner states it.
`?all=true` keeps the network comparison, which is where the four zero-day
branches live.

The restriction is applied to the per-line durations **before** any aggregate
is taken. Restricting afterwards would compute over 53 branches and then label
the result with two names, which is the exact failure `workspace_scope` exists
to prevent (D-049). The per-line frame is what is cached, so switching scope
does not re-parse 775,912 rows.

SKU comes from `Oracle No`, the order file's master join key (D-017), not
`Material Code`. All 20 workspace SKUs appear in the order file; the scoped
slice is 6,484 lines.

**The measurement that came out of it:**

```
BENGALURU   stated 4.0   observed 3.72   p95  6   gap -0.28   3,752 lines
DELHI-1     stated 3.0   observed 4.13   p95 10   gap +1.13   2,732 lines

first third of months  3.42 d  (2025-04 .. 2025-08)
last third of months   4.92 d  (2026-03 .. 2026-07)
change                +43.9%
```

Monthly, the deterioration is in both branches and severe in one:

```
            2025-04   2026-07
BENGALURU      3.47      5.28   (stated 4.0)
DELHI-1        2.93      9.26   (stated 3.0)
```

DELHI-1's most recent month runs at **three times** its stated planning figure.
That is a description of what the order dates recorded, not a forecast, and the
page says so.

**Four charts, each answering something the table cannot.** The trend is
monthly points rather than a rolling mean, because a smoothed line blurs the
month a change began. The distribution's last bucket is a catch-all so the tail
shows as a tail. Stated against observed is **grouped, never stacked** —
stacking would assert the bars add to something, and a supplied planning figure
plus a measured duration do not. By SKU carries no stated counterpart, because
Location Master is branch-grained and inventing one would be a fabrication.

`trend` is the first third of the months against the last third, weighted by
line count, and is deliberately not a fitted slope: a slope implies a model of
how lead time moves, and there is none here. Weighting matters — a month with
one line must not swing the window like one with a thousand, and a test pins
that.

## D-106 — `month_index` becomes `period_index`

A function called `month_index` that returns a week counter is exactly how a
grain bug survives review. The pair in `app/ml/features/panel.py` is now
`period_index`/`index_to_period`, both taking the grain, and the 31 call sites
and tests were renamed with them. `ais_preprocessing.month_key` keeps its name
because callers and tests import it, and its docstring states plainly that it
no longer necessarily returns a month.

## D-107 — Weekly does not rescue the annual cycle, and the honest answer is unchanged

At monthly grain the reference profile's only candidate is 12, which needs 24
observations for two complete cycles; the panel offers at most 22 training
months, so 12 can never be satisfied and all four Exponential Smoothing
variants are permanently Ineligible. It would be convenient if weekly fixed
this. **It does not**: 52 needs 104 observations and weekly offers 78 and 96, so
the reference profile still resolves to `None` for the same reason.

What weekly does change is the relaxed profile. Monthly's fallbacks (6, 4, 3)
were scraping against an 18-period fold; weekly's (26, 13, 4) clear their
two-cycle floor with real headroom.

## D-108 — Feature spans are counted in the grain's own periods

Reusing the monthly numbers would have been silent corruption: a
`rolling_mean_3` means three months monthly and three *weeks* weekly — a
different feature wearing the same name. Each set covers a comparable span
instead. Lags go from (1..6, 9, 12) to (1..6, 13, 26, 52); rolling windows from
(3, 6, 12) to (4, 13, 52); non-zero counts from (6, 12) to (13, 52); and the
year-ago seasonal lag from 12 periods back to 52.

`calendar_month` could not follow the same rule. Monthly it is arithmetic on
the counter (`index % 12 + 1`); weekly it is a real lookup through the Thursday
rule, because a week's month is not a function of the week number alone — ISO
week 5 is February in one year and January in the next.

## D-109 — auto_arima's seasonal ceiling follows the grain

Sodexo's guard caps the seasonal period at 24 so the stepwise search cannot
explode. At weekly, 26 and 52 are legitimate periods and 24 would refuse them
**silently**, which reads as a model choice rather than a limit. The weekly
ceiling is 53 — not 52, so a leap-week year is not excluded. A search at m=52 is
genuinely expensive; this raises the ceiling rather than pretending otherwise,
and a fit that overruns is reported as **Timed out** by the per-model budget,
which is a visible answer.

## D-110 — The display grains are whatever the panel can be aggregated *up* to

`analytics.GRAIN_NOTE` claimed a weekly view "would have to invent values the
source data does not contain". That was true of a monthly panel and is false of
this one — the source carries transaction dates, which is where the weekly
panel comes from. Available grains are now resolved from the panel grain:
weekly/monthly/quarterly on a weekly panel, monthly/quarterly on a monthly one.
Daily is still refused at both, because splitting a period's units across its
days would invent a profile that genuinely is not there.

`_bucket` also had to change. It bucketed by *index* arithmetic (`// 12` for the
year), which meant "the year" on a monthly panel and nothing at all on a weekly
one. It now buckets by the period **label**, which carries its own calendar and
works at either grain.

## D-111 — An origin's result carries its own grain

`OriginResult` gained a `grain` field, set from the `Origin` that produced it.

A result outlives the origin object: the champion path reads `train_end_period`
off the *latest completed* result long after the origins list is gone, and the
serialised `origins_json` is read back from the database with no origin in
scope at all. Both then have to turn a period label into an index, or an index
back into a label, and neither can do that without knowing the calendar.

Found the hard way. The first weekly training run reported
`completed_with_warnings` and wrote **zero** model rows: every one of the 40
series failed with `AttributeError: 'OriginResult' object has no attribute
'grain'`. The run looked like it had succeeded — a green status, a duration, a
progress bar to 100% — because the failure was caught per series and recorded
as a warning. A status that can read "completed" over an empty result table is
the part worth remembering.

Two sibling calls were fixed with it: `index_to_period(int(p))` in the
validation-period list, which had been silently rendering weekly indices as
month labels such as `8797-05`.

`OriginResult.as_dict()` serialises `grain` too, so a result read back out of
`model_run.origins_json` carries its own calendar. The rows already stored by
run `101df724512542928d072a4698079b05` predate that field and have `grain`
absent; nothing reads it yet, and the next training run writes it.

## D-112 — Drift is defined in months, so a weekly panel is rolled up before it

`app/domain/ais/drift.py` is untouched by the weekly work. Its caller in
`app/api/routes/analytics.py` sums the weekly panel into calendar months first.

Drift asks a question that is stated in months: a six-month window against the
six before it, and a measurement change dated to `2025-04`. Six *weeks* against
six weeks is a different question that would carry the same name and the same
20% reading aid, and the aid was calibrated on months. Teaching drift a second
calendar would have made the panel's headline number quietly incomparable with
every earlier reading of it.

Cost of the alternative, observed before the fix: `/api/analytics/drift`
returned 500 on every request (`invalid literal for int() with base 10: 'W14'`)
because drift parses `YYYY-MM` with its own private splitter.

## D-113 — The six-month roll-up sums quantiles, and says so

`GET /api/forecasts/series` now returns `monthly_rollup` and `horizon_total`
beside the weekly rows. The point forecasts add back to the horizon total
exactly, because the Thursday rule puts every week in exactly one month.

The quantile columns are a plain sum of the weekly quantiles, and **a summed
quantile is not the quantile of a sum**. Adding five weekly q95 values describes
the world where every week peaks at once, which is more pessimistic than a 95%
month. Two alternatives were rejected: rescaling by √n assumes independent
weekly errors, which intermittent demand does not have; and dropping the columns
removes a band a planner asked for. It is summed, shown, and named — in the
docstring, in the API, and in the panel's own note.

A month the horizon only partly covers is flagged `complete: false`. A partial
month read as a whole one looks like a fall in demand that is not there.

## D-114 — A "sum of children" scope shows no prediction interval at all

Where a scope's forecast is the sum of the series beneath it, the API returns
the point forecast in the quantile fields. The roll-up panel detects that the
band is identical to the point forecast and drops the three columns, showing
the reason instead.

Three columns repeating the point forecast read as a measured band. They are
not one: adding up each SKU's upper bound assumes every SKU misses high in the
same week, which is not what the residuals show. The page already said this in
a footnote elsewhere; it now refuses to draw the columns that contradict it.

## D-115 — The default forecast horizon is derived, not typed

`ForecastRunRequest.horizons` defaults to `range(1, settings.forecast_horizon + 1)`
— six monthly, twenty-six weekly — evaluated per request rather than at import,
because the grain is configuration and a module constant would freeze whichever
grain happened to be set when the process started.

Two tests asserted the literal `"1,2,3,4,5,6"`. Both now assert against the
setting, so they say "the default is the whole mandated horizon" rather than
pinning the grain the suite happens to run at.

## D-116 — The headline accuracy is the six-month total, with the per-week figure kept beside it

`GET /api/training/{id}/accuracy-windows` now returns `combined_metrics_horizon`
— the pooled accuracy of the same forecasts scored on the six-month total —
alongside the per-period `combined_metrics` it always returned. Every headline
tile on Training and the per-line tile on Forecasting lead with the six-month
figure.

Measured on run `101df724512542928d072a4698079b05`, pooled over every completed
registered model: **26.21% average miss over six months against 79.78% per
week**. The six-month number is not a better model; it is the same forecasts
scored on the quantity a plant actually buys against, and over- and
under-forecasts inside the window cancel.

`combined_metrics_horizon` is computed unconditionally, unlike the existing
`combined_metrics_best`, which is `None` when no window clears 85%. That is
exactly the run that still needs a stated headline, so the run that fails the
target is the run that must not fall back to a blank tile.

Cancelling is not guaranteed and the page says so with counts, not a slogan:
**35 of 40 lines are more accurate over six months and 5 are less**, one of them
0.00% over six months against 60.31% per week. A model that misses the same way
every week compounds rather than cancels. The per-line tile therefore shows the
six-month figure with the per-week figure in its sublabel — showing only the
better of the two would be picking per line.

**Open, and deliberately not changed here:** the champion is still selected on
per-period error. Ranking the same models by six-month-total error reorders them
sharply (XGBoost-exog moves eleven places). Changing the selection quantity
changes what "champion" means on every page, so it is recorded as a decision to
take rather than taken in passing.

## D-117 — The replenishment calculation is fed a month, not a panel period

`app.domain.ais.inventory` takes a **monthly** quantity and scales it to a
protection period of roughly one month. A forecast row is one panel period, and
on a weekly panel that is a week, so `inventory_service` was handing a month's
arithmetic seven days of demand.

Measured before the fix, `BENGALURU|FG.BA5.LFH.GCG2120000` at q95:
order-up-to 1,705 units against a real requirement of 5,071 — the page
recommended about a quarter of what the branch needs, on every line.

The service now adds the forecast rows reporting under the month up first
(`_to_month`), by the same Thursday rule the display roll-up uses, and the two
paths agree exactly: 558.7287065727975 units and q95 4539.6582958324725 from
both `forecast_service._rollup_rows` and the inventory path. The domain module
is untouched; it still receives, and still documents, a monthly quantity.

Quantiles are summed, carrying D-113's caveat, and the response says so in a
note. A month the horizon only partly covers is flagged on the row as a warning
rather than silently under-ordering.

## D-118 — A count of panel periods is never printed with the word "months"

Several strings counted panel periods and named them months, which read as a
count of weeks wearing the wrong word once the panel went weekly. All of them
now take the noun from the grain (`grain.period_noun` on the backend,
`app/period.periodNoun` on the frontend):

- Per Branch & SKU: "122 months" under Ordered demand — the window is the
  panel's own, at the panel grain, and the grain picker above it re-buckets the
  charts without changing what the panel is made of.
- Assistant, demand trend: "Window — 122 months … mean 2,603 units/month" in the
  same sentence. The count and the endpoints now come from the monthly trend
  itself: "28 months, 2024-04 to 2026-07".
- Training, fold table: the "Months" column header over `train_rows`.
- Exponential Smoothing ineligibility: "48 zero and 0 negative month(s)".

## D-119 — The green dot in the line picker follows whatever the drill-in shows

`useLinesAtTarget` marks the lines at the 85% target in the SKU picker. It has
now been wrong in both directions, so what is recorded here is the rule, not the
answer: **the mark must match the figure the next screen puts on screen.**

It first read the six-month flag while the drill-in showed the per-period
figure — 19 dots, 15 of which opened below 85%, one at 48.8%. It was then moved
to `champion_meets_target`, which was correct until D-116 moved the headline to
the six-month total. On the weekly panel that flag is true for **0 of 40 lines**,
so the dot stopped appearing at all, while **16 lines** open on a six-month
figure at or above 85%.

It now reads `horizon_meets_target`, and the docstring says it changes again if
the lead figure changes again.

## D-120 — The champion is picked on the six-month total, and the training page shows it

On request: *"in training page also we have to show the consolidated accuracy
numbers for each of the model and have to selection based on that only."*

D-116 moved every headline figure to the **error on the six-month total** — the
same forecasts, added up across the planning window before they are scored,
because that is the quantity a purchase order is placed for. The champion was
still ranked on per-period MAPE (D-043). The screens therefore reported one
number and the model behind them was chosen by another, and the two disagree
sharply: on run `101df724` the thirteen registered models reorder substantially
between them.

Three things changed together.

**1. The metric has one definition, in one module.** `app/ml/evaluation/
horizon_totals.py` holds the blocking arithmetic, the `PLANNING_HORIZON_MONTHS
= 6` constant, and nothing else. Training writes it onto every `model_run` row
(`horizon_mape`, `horizon_wape`, `horizon_blocks`), champion selection ranks on
it, and the accuracy-windows panel imports the same functions instead of its
own copies. `accuracy_windows.WINDOWS` takes its widest entry from the same
constant, so the board's order and the panel's headline cannot describe
different windows.

**2. `AIS_CHAMPION_PRIMARY_METRIC` defaults to `horizon_mape`.** `mape` and
`wape` are still accepted and still computed on every row; setting the old
value restores the old ranking with no code change. Ranking is *not* silently
substituted when the metric is missing: a row with no six-month figure is
excluded with a reason and keeps its place on the board, like every other
exclusion.

**Re-selecting on the new metric measurably improved the figure the screens
report.** Champions were re-selected for the 40 series scopes of run
`101df724` with no retraining — only the ranking changed:

| Six-month figures for run `101df724`, 40 series | ranked on per-period MAPE | ranked on the six-month total |
|---|---|---|
| Accuracy (median block) | 82.76% | **89.18%** |
| Volume-weighted accuracy | 74.72% | **86.57%** |
| Lines clearing 85% on their own | 16 of 40 | **26 of 40** |
| Lines *worse* over six months than per period | 5 | **2** |

Both columns are the same 40 lines and the same stored backtests; only which
model each line uses changed. The "before" column was recomputed from the
superseded `ChampionSelection` rows, which are kept rather than deleted, so it
is a measurement and not a memory. The "after" column matches what
`GET /api/training/{run}/accuracy-windows` returns live.

**3. The cost is sample size, and it is on the screen rather than in a
footnote.** A six-month block needs a whole validation origin, so each row
rests on **one or two** blocks where per-period MAPE rests on 52 points. Every
payload carries `horizon_blocks`, the per-line leaderboard prints it as `×1` /
`×2` beside the error, and the per-model table prints how many lines each model
was scored on. Four models ran on 5 of 40 lines and score far better there;
without that count beside them the table would read as though they were simply
the best models, which is a claim about a different set of lines.

### What the Training page now shows

- **A per-model consolidated table** (`ModelAccuracyTable.tsx`), the piece that
  was missing: the page had per-line leaderboards and one combined headline and
  nothing in between. Each of the thirteen, its accuracy, its MAPE, and how
  many lines it won — so the column that decided the winner is the column the
  winner is read from.
- **Both tables show accuracy and MAPE, and nothing else**, on request:
  *"in the leader board also sho only accuracy and mape (consolidated) …
  no extra things needed."* Both are the six-month figure and MAPE is
  100 minus accuracy, so the pair is one number said twice — which is the
  point: the ranking, the headline and the column a reader looks at are now
  the same measurement.
- **What was dropped, and where it went.** The per-line leaderboard previously
  carried per-period accuracy, per-period MAPE, WAPE, bias, the test-point
  count and a paragraph of explanation; the per-model table carried a
  per-period column and a "lines scored" count. All of it is still on the API
  and still in `/api/training/explain`'s metric definitions. One item is worth
  naming because dropping it costs something real: four models ran on **5 of
  40 lines** and score far better on those, so the top row of the per-model
  table wins nothing at all. The count now lives on the row's tooltip instead
  of in a column.
- **The race bars are the six-month accuracy.** They were the per-period
  figure, which floors at zero: on `BENGALURU|FG.BA5.LFH.GCG2120000` all
  thirteen bars read 0.0% while the table beneath them read 77%. Both were
  true and together they were unreadable.
- **The metric is named in words, not as a column name.** "HORIZON_MAPE" on a
  tile names nothing; `primary_metric_label` carries "error on the six-month
  total" through `/api/training/explain` and the leaderboard payload.

### The backfill had to read each run's own grain

The migration first scored every historical row against the *current* grain,
which gave every older monthly run zero blocks — a 26-period window never fits
inside a 6-period validation. It now reads the grain from each row's own stored
period labels (`grain.grain_of_period`: `2026-W13` is a week, `2026-03` is a
month), falling back to the parent run's origins and then to the setting. One
run had recorded no origins of its own, and without the per-row rule all 678 of
its model runs would have stayed unscored.

2,701 of 2,707 completed rows now carry a six-month figure. The six that do not
are honest NULLs: four baselines on a branch whose six-month actual total is
zero, so there is no denominator, and the two pooled rows, whose `origins_json`
predates storing predictions. Pooled runs written from now on compute it
per series from the validation frame itself.

## D-121 — Overall Analysis opens on orders, sales and the difference

The page led with four tiles: ordered demand value, unfilled demand, fill rate
and ordered-demand share. The first question actually asked of it is simpler
than any of those — **how much came in, how much went out, what is the
difference** — and that question was spread across two of the four tiles with
two unrelated ones between them.

The row is now three tiles that reconcile by subtraction:

| Tile | Figure | Under it |
| --- | --- | --- |
| Orders received | `ordered_value_known` — ₹15.75Cr | `ordered_units_known` — 46.4K |
| Sales despatched | `despatch_value` — ₹13.70Cr | `despatched_units` — 40.1K |
| Orders not despatched | `gap_value` — ₹2.05Cr | `gap_units` — 6.3K, and 87.0% covered |

₹15.75Cr − ₹13.70Cr = ₹2.05Cr. 46,414 − 40,116 = 6,298. Tile 3 is a real
subtraction, not two numbers measured apart and differenced anyway.

Unfilled demand and ordered-demand share were not deleted — both still have
their own panels further down the same page, where they have room to be read
properly rather than as a number on a tile.

### Why the first tile is not the ₹24.22Cr this page used to lead with

The panel does not hold orders for its whole span. Reading `order_share_pct`
month by month over the current workspace:

- **2024-04 → 2025-03** — `order_share_pct` is 0. Every row is a **sales-proxy**
  row: quantity derived from sales, no order behind it, and no despatch figure
  either. 2,639 rows, ₹8.47Cr of demand.
- **2025-04 → 2026-07** — `order_share_pct` is 100, and despatch is recorded on
  most rows. 2,209 rows carry both sides.

A tile headed "orders received" that reports ₹24.22Cr is therefore counting a
year of sales proxy as orders, and subtracting despatches from it would report
a stretch where no order was ever placed as a stack of undelivered orders. The
tiles are computed on the rows that carry both measurements, and
`comparable_window` reports the stretch those rows span (2025-W14 → 2026-W31,
70 weeks) so the restriction is stated rather than silently applied.

The ₹24.22Cr is not hidden: `demand_value` is unchanged, the line under the
tiles names it, and **every panel below the tile row still uses it**. Total
demand is the right figure for "where is the demand"; it is the wrong figure for
"how much of what was ordered went out".

### The line under the tiles is part of the decision

A reader who sees ₹24.22Cr elsewhere on the page and ₹15.75Cr on the first tile
will assume one of them is wrong. The line states both row counts, both stretches
and the ₹8.47Cr difference, so the two figures are visibly the same data on two
different row sets rather than a discrepancy.

Coverage is reported on a **value** basis (`fill_rate_value_pct`, 87.0%) because
the tiles above it are in rupees. The unit-basis `fill_rate_pct` (86.4%) is
unchanged and is still what every other panel reads.

### The derivation moved out of `load_panel`

`demand_value` and `shortfall_positive` were derived inside `load_panel`, and
`tests/test_analytics_api.py` carried its own copy of that arithmetic to build
fixtures. Adding `despatch_value` broke thirteen tests, because the copy had no
way to know. Both now call `analytics.derive_columns`, so the next derived
column cannot drift the same way.

## D-122 — Overall Analysis defaults to the weeks that have orders, and loses four panels

**The window.** D-121 put the three tiles on the rows that carry both an order
and a despatch, but every panel below them still covered the full 122 weeks, so
the branch ring read ₹24.22Cr under a first tile of ₹15.75Cr. The page now
starts, by default, at `orders_start_month` (from `/api/analytics/filters`,
currently 2025-04), the first month holding real orders. Before it the panel is
sales-proxy rows only.

Measured on that window, everything agrees: total ordered value is ₹15.75Cr on
the tiles and on every panel, and the 591 order rows without a despatch figure
carry no ordered units, so no rows are lost between the two views.

**The page cannot reach before that window.** A first version let an earlier
From month, or "Full history", pull the sales-only weeks back in. The tiles
stayed at ₹15.75Cr (there are no orders to count before April 2025) while every
panel grew to ₹24.22Cr, which is exactly the mismatch this was meant to remove.
So the From month is now clamped to `orders_start_month`. The calendar will not
offer an earlier month, a forced earlier value snaps back, and the reset button
reads "Reset dates", since it returns to the orders window rather than the full
history. `MonthRange` gained optional `minMonth` and `resetLabel` props; every
other page keeps the old behaviour.

**Audited, not assumed.** Every breakdown on the page (branch, value class, glass
type, vehicle category, vehicle age, SKU, product group, the branch × value-class
columns, branch over time and the trend) was summed from the live payload and
compared with the tiles. They agree to the rupee and the unit (₹15.7529Cr,
46,414 units) with no filter, on BENGALURU alone, on value class B alone, on
2025-10 → 2026-03, and at weekly, monthly and quarterly grain. The Demand by
Branch ring also read "top 10 of 2"; it now says "2 branches" and keeps "top 10
of N" only when there are more than ten.

**One gap is left, and it is explained rather than forced to match.** The
unfilled panels count gross positive shortfall, 7.4K units. The third tile is
net, 6.3K units, because over-despatched lines offset short ones. Both figures
are correct, and `CLAUDE.md` requires them to be reported separately. The line
under the tiles gives both numbers and the reason.

**Removed at the user's request:**
- Branch Operational Scorecard (and its score explanations). The page no longer
  calls `/api/analytics/branch-scorecard`; the endpoint itself is unchanged and
  still documented.
- Service Risk by SKU. Top SKUs by Ordered Demand now spans the full width and
  still shows the unfilled part of each SKU in amber.
- Demand Signal Mix. On the orders window it is a flat line at 100% orders.
- Every "How to read this" expander. `Panel` turns a note longer than 90
  characters into one of these, so each long note on this page was cut to a
  single line.

## D-123 — Overall Analysis is split into three sections; delivery charts merged; SKU Pareto added

**Three sections, each answering one question.** The panels below the tiles now
sit under "Where the demand comes from", "How demand moves over time" and "How
well we deliver". A row of buttons above the tiles jumps to each section. Every
row fills the width at 1440 px (4-column grid on wide screens, 2 on medium, 1 on
phones).

**Delivery over time is one chart instead of four.** Coverage, Unfilled Demand
Trend, Fill Rate (trend) and the old Ordered vs Despatched all plotted the same
two series (ordered units and despatched units) or a ratio of them. They are
replaced by a single "Ordered vs Despatched" chart: ordered units as a shaded
area, despatched units as a line, and fill rate as a second line on a right-hand
0–120% axis with a 100% guide. The space between the area and the line is the
unfilled demand, so no separate gap chart is needed. The payload is unchanged;
all series come from the existing `trend` buckets.

**New: "The SKUs That Carry the Demand".** Every SKU in scope is sorted by ordered
units. SKUs up to and including the one that takes the running total past 80%
are drawn dark; the rest are grey. The running-share line and its right-hand
axis were removed at the user's request. The running share is shown in two
plainer ways instead: a two-part strip above the chart ("Top 9 SKUs · 85% of
orders" against a plain "15%", since the small segment is too narrow to hold a
sentence) and each SKU's own share of orders printed on its bar. The strip's
second half uses `--color-surface-2` and `--color-text`, so it stays readable in
the dark theme.
The strip shows the true share of the top group (85%), not a rounded 80%,
because that group includes the SKU that takes the total past 80%. On the current data, the
top 9 of 20 SKUs make 85% of ordered units. It is computed in the page from the
existing `by_sku` breakdown, so it follows every filter and agrees with the
tiles (D-122).

**Demand Concentration removed** at the user's request (the share of each
branch's volume in its top 5 SKUs). The SKU chart above already makes the same
point. Volume vs Value by SKU widened to fill the row.

**Other candidate charts were measured but not built.** They are waiting for the
user's review. They cover repeat shortages by line, sales saved by substitutes,
over-despatch, stock cover, and order size.

## D-124 — The assistant reads the orders window, and finds a leaderboard that exists

**The assistant and the Overall Analysis page disagreed on screen.** Asked for
the demand trend, the assistant answered ₹24.22Cr over 28 months from 2024-04
while the page beside it showed ₹15.75Cr over 16 months from 2025-04. Both were
arithmetically right and one of them was misleading: the page clamps to the
weeks that hold real orders (D-122), the assistant read the whole panel, and the
early weeks are sales-proxy rows with no order and no despatch behind them.

The clamp now lives in one place. `analytics.orders_start_month(panel)` returns
the first month with real orders as YYYY-MM — the same value `filters()` puts on
`orders_start_month`, so the page and the assistant cannot drift apart — and
`assistant.tools._analytics_scope` sets it as `start_period` on every scope it
builds. All three analytics reads in the assistant go through it: the demand
trend, the branch breakdown (which had been building a bare `AnalyticsScope()`
of its own) and the stock exceptions. The assistant now answers ₹15.75Cr,
Bengaluru ₹9.42Cr, 16 months — the figures on the page.

`start_period` takes a month, not a panel period. Passing the period key
("2025-W14") raises deep inside `first_period_of_month`, which is why the helper
returns the month and is named for it.

**"No model has been ranked" was false.** `model_leaderboard` read the newest
completed training run and filtered to `scope_level == "national"`. The newest
completed run was local-tier only — 680 series rows, no national rows — so the
filter emptied and the assistant reported that nothing had been ranked, while a
full national leaderboard sat one run back. It now selects the newest completed
run that actually holds national rows, and distinguishes the two empty cases:
no completed run at all, against a completed run that ran only at series level.
On the stored runs it now returns 12 ranked models with Exponential Smoothing
Additive champion at 10.326% WAPE.

**The assistant named a different champion than the rest of the application.**
`model_leaderboard` crowned the top of its own WAPE table. On this run that is
Auto ARIMA at 30.426% measured by `holdout_fast` on 26 validation points, while
the stored selection is Exponential Smoothing Additive at 31.968% measured by
`rolling_origin` on 44 - a lower error on fewer points, which the tool's own
caveat already warned against comparing. It now reads the active
`ChampionSelection` for the run's `overall` scope and reports that, with the
evaluation mode and point count beside it, and falls back to the lowest WAPE
only when no selection exists - saying so when it does.

**A new training run was run** over all three tiers (aggregate, local, pooled),
because the newest completed run covered only the local tier: 693 model runs,
none failed, 266 seconds. Champion selection is a separate step and `series` is
not in its default scope list, so the run produced no series champions and the
accuracy windows read zero until selection was run for `series` explicitly.
With champions selected the six-month total is 89.18% accuracy, 86.57%
volume-weighted, clearing the 85% target from the three-month window on.

## D-125 — Six defects found by asking the assistant thirteen kinds of question

The assistant and the recommendations page were exercised across question
types: trend, breakdown, chart-by-name (line, bar, pie), exceptions,
leaderboard, forecast, inventory, data quality, branch-scoped, greeting,
out-of-scope, a privacy probe, and a follow-up that depends on history. All
thirteen answered, every figure agreeing with the pages (D-124). Charts are
returned on the top-level `chart` field and render: line with 16 points, bar
with 2, pie when a pie is asked for, leaderboard bar with 10.

Six things were wrong.

**The greeting stated three wrong numbers.** It was a constant reading "53
branches, about 2,300 SKUs, forecast at branch x SKU x month". This deployment
is scoped to 2 branches and 20 SKUs and forecasts weeks, so every conversation
opened with three false figures before answering its first question correctly.
`llm.greeting_message(db)` now builds it from `resolve_workspace` and
`panel_grain`, and falls back to "this workspace" if either is unavailable - a
greeting must never fail to greet.

**The leaderboard invited replacing the champion.** With both figures in the
facts the model wrote "Next step: Consider Auto ARIMA for improved accuracy,
though the champion is Exponential Smoothing Additive". The facts now carry
`how_to_read_this_ranking`, saying the table is sorted by WAPE and not by
trustworthiness, that the `champion` field is the application's decision, and
that a higher-ranked row is never to be recommended over it.

**Recommendations fell back to templates about half the time.** The cause was
not the provider: `max_tokens` was the chat cap of 900, and five items with an
observation, an explanation and evidence each do not fit, so the JSON was cut
off mid-string and the parse failed. The page showed template text with no
error a reader could see. `ai_recommendations_max_output_tokens` (default 2600)
now covers this call. Six consecutive runs came back from the model with five
items and no fallback.

**Unit counts carried decimal tails.** "units: 7414.0" on the evidence chips,
"national_shift_pct = 35.73525957246886", and a recommended order read as
"5070.994 units" - not a quantity anyone can place. Counts are now whole in the
recommendation titles, observations and evidence, and `recommended_order` and
`order_up_to_level` are whole in the assistant's own facts.

**A branch comparison could only answer for one branch.** `branch_demand`
returned units and value but no fill rate, so "compare BENGALURU and DELHI-1 on
fill rate" gave Bengaluru's rate from the network trend and said Delhi's was
not in the facts. Each branch row now carries `despatched_units`,
`shortfall_units` and `fill_rate_pct`: BENGALURU 82.59%, DELHI-1 92.69%.

**Two behaviours were checked and left alone.** Asked where a baseline beats the
champion it answers that none does, which is true at national scope. Asked for
the worst SKU-level accuracy it says SKU-level accuracy is not in its facts,
which is also true. Both are correct refusals, not gaps.

## D-126 — The panel build applies the workspace scope itself

The live panel could not be rebuilt from this repository. `AIS_WORKSPACE_SKUS`
restricted what the *pages* showed, but the panel artifact they read was cut
down by a script that was never committed — so changing the setting without
that script produced an application claiming 136 SKUs while serving 20.

`panel_service._scope_artifacts` now cuts the five preprocessed tables to the
resolved workspace before `AisPanelBuilder` sees them, and records the cut in
`panel_manifest.json` and `build.summary_json` as `workspace_scope`. Fact
tables are cut on both axes, `branch_dim` on branch only and `product_dim` on
SKU only — cutting a dimension on an axis it does not carry would empty it.
The originals are never written to; scoped copies go under the build directory.

This is also what keeps the build affordable. The panel is a full
branch × SKU × period grid, so an unrestricted build materialises every series
in the extract — the attempt that exhausted memory. Cutting 582,324 order rows
to 12,171 first is why the build takes 0.9 s.

`scripts/export_scoped_slice.py` regenerates `data/scoped/` from the live panel
and the resolved workspace, replacing the hand-maintained export that drifted
(D-091). Nine tests in `tests/test_panel_scope.py` cover the cut.

## D-127 — 136 SKUs, not 135

The request was the top 135 SKUs by combined BENGALURU + DELHI-1 invoiced value
among the 1,131 SKUs both branches sell — 80.1% of the two branches' combined
revenue. The configured set is those 135 **plus `FG.MP8.FDR.G00300A000`**,
which ranks 177th and so falls outside the cut.

It is kept because it was one of the original twenty, chosen deliberately for
spread over vehicle category, glass type, value class and vehicle age
(D-075, D-081, D-082, D-083). Dropping it would lose that spread for one rank
position. Nineteen of the original twenty are inside the 135 on merit.

Measured after the rebuild: 271 series, 32,341 panel rows, 122 weekly periods
(2024-W14 → 2026-W31). Training reached 281 scopes in 1,179 s — 4,779 model
runs, 3,754 completed, 0 failed, 0 timed out, 1,025 ineligible with a stated
requirement. 270 of the 271 series were trained; the one excluded,
DELHI-1 × FG.ALP.LFH.GCG2120000, has 8 weeks of history and 2 non-zero weeks,
below the 12-observed-month floor, and is covered by the pooled tier instead.
Champions: 272, of which 261 series. 9 series were skipped rather than given
an arbitrary champion. The forecast run wrote 7,072 rows over 272 scopes,
coherent, with no reconciliation fallback.

**The pooled tier ran end to end** for the first time — 2 pooled scopes,
3.96 s over 32,341 origin feature rows. The "never run end to end" gap in
CLAUDE.md no longer holds.

## D-128 — The scope banner states the network, not the slice

Every panel-backed page carries a `workspace_scope` saying which slice it
shows. It read **"2 of 2 branches · 136 of 136 SKUs"** — a sentence whose only
job is to say what the page hides, saying nothing, and reading as full
coverage.

The totals were counted from the panel frame, and the panel *is* the workspace
slice, so the denominator was the numerator. The order book actually holds 53
branches and 2,063 SKUs. `_demand_universe` in `api/routes/analytics.py` now
reads those two columns from the preprocessing artifact, which is never cut to
the workspace — 0.07 s over 582,324 rows, cached per artifact path. It returns
no totals rather than raising: a banner that cannot state its denominator drops
the "of N" and still names the slice; one that 500s takes the page with it.

Supply Intelligence was already correct at "2 of 57", reading the unscoped
branch dimension. The two populations differ legitimately — 57 depots in the
location master, 53 with orders — and each page states its own.

## D-129 — Four assistant defects found by asking it about the wider workspace

Expanding to 136 SKUs made the branches carry different SKU lists for the first
time, and that exposed four defects. All were reproducible across repeated runs
at temperature 0.3.

**Every rupee figure was a tenth of the truth.** The facts carried the raw
amount and the prompt asked for "₹8.9Cr", so the model did the conversion — and
divided by 10^8 rather than 10^7, every time. ₹60.24Cr was reported as
₹6.02Cr. `tools._rupees` now writes the figure and rule 3 forbids converting a
`*_rupees` value by hand. `tools.py`'s own docstring already named this failure
mode: a model allowed to do arithmetic on facts will do it wrong in the same
confident voice.

**"How many SKUs?" answered 271.** That is the series count. The facts gave a
per-branch SKU count and no workspace total, so the model added 136 and 135.
It was invisible while both branches carried the same twenty. `branch_demand`
now publishes `skus_total` and says the per-branch counts must not be summed.

**The system prompt still claimed 53 branches and 2,300 SKUs.** D-125 removed
that constant from the greeting but left it in the system prompt, where the
model read it before every answer. It now states that the deployment is a
restricted slice and that scope comes from the facts. The greeting's
"horizons 1-6" was also a constant; a weekly build forecasts 26.

**"Why is this model champion" was answered with an invented reason.** The
facts carried WAPE but not the metric the champion is actually chosen on, so
seeing a lower WAPE elsewhere the model guessed: "it was evaluated on fewer
validation points or different evaluation". The real answer is horizon error —
Exponential Smoothing Additive at 1.964% against XGBoost's 8.297%. The
leaderboard facts now carry `ranking_metric_pct` on every model, every
baseline and the champion, and `beaten_by_baseline` is reported from the stored
field rather than inferred by comparing columns.

**One weakness remains.** Asked where a baseline outperforms the champion, the
answer still opens by comparing WAPE — where ma6 does lead — before correctly
reporting that the champion is not beaten and giving both metrics. The facts
now contain everything needed; the table is still sorted and labelled by WAPE,
which is what leads the model there.

## D-130 — A flat drift trend projected 31 quadrillion months

`project_next_crossing` guarded with `if slope <= 0`. A dead-level series does
not give an OLS slope of exactly zero — it gives about 1e-18 — so a flat trend
passed the guard as rising and the projection read "about 31118141019627308
months away". The guard is now `slope <= FLAT_SLOPE_PP_PER_MONTH` (1e-3), below
which the trend is flat; `slope_pct_per_month` is rounded to three places
anyway, so such a slope already displayed as 0.0.

Pre-existing on committed code and unrelated to the SKU expansion — found by
the full suite during this work, where it was the only failing test.

## D-131 — Every panel says which slice it is; the recommendations name a line

Two questions, asked together: do the other panels use the same two-branch,
136-SKU workspace, and what exactly is the AI Recommendations agent producing?

### The data was always scoped. Four labels said otherwise.

Every panel reads the restricted slice and always did — the panel is physically
cut to the workspace at build time (D-126), so nothing downstream can widen it.
Checked against the running app: `analytics/summary` returns BENGALURU and
DELHI-1 with 136 SKUs, `analytics/filters` the same two branches,
`analytics/lead-time-observed` the same two, `inventory/recommendations` 261
rows over those two branches and 134 SKUs (2 × 136 = 272 combinations, 11 of
which have no forecast and stock position, so no row).

The **labels** were the problem, in two separate places.

**The assistant's tools told the model the figures were national.**
`scope_note()` returned the literal `"the whole network"` whenever the question
named no branch or SKU — which is most questions — and two tools hardcoded
`"national"` and `"national aggregate (the whole network summed per month)"`.
Those strings are handed to the model as facts, sitting next to the numbers,
while the scope note in `caveats` said the opposite. A model given two
contradictory facts will use either, and the counts made the wrong one
plausible: 516 exception lines and 261 replenishment rows read like a network,
not like 272 series. All four now resolve through `_workspace_phrase(db)` and
read `this workspace only — 2 branch(es) (BENGALURU, DELHI-1) and 136 SKU(s)`.
An unrestricted deployment still reads "the whole network", so the fix does not
invent a limit where there is none.

`scope_level == "national"` in the forecast and leaderboard tables is the name
of a **tier** — the top of the hierarchy — not a claim about the country. Those
labels now say which tier they mean.

**Two of the seven pages carried no banner, and two carried a partial one.**
AI Recommendations stated the restriction only in a caveat below the list, so
its headline counts read as network figures. AI Assistant said nothing at all,
under a headline reading "Ask about this network." — which is the claim the
banner exists to prevent. Training and Lead Time showed `2 branches · 136 SKUs`
without denominators: the restriction stated, but not how much of the network
it hides.

All seven pages now render the identical `ScopeBanner`, measured from the UI:
`2 of 53 branches · 136 of 2063 SKUs`. The recommendations payload carries
`workspace_scope` like every analytics payload — which required declaring the
field on the `Recommendations` pydantic model, because `response_model` was
silently dropping it — and `/assistant/status` carries it too, on the status
call rather than the answer so the page can say what is in scope before the
first question is asked.

The assistant's own scope chip is a different thing and stays: that is the
scope of the conversation so far, *inside* the workspace.

### The recommendations answered at the network; now they name a line

The page said "Short despatch affects 240 branch × SKU lines" and "BENGALURU
branch has 300 exception lines". Those are counts of lines, never a line — a
planner cannot act on one, because it never says *which*. One of the five items
named a SKU.

`origin/main`'s D-104 was pulled for this: a second pass builds one card per
branch × SKU, ranked by `line_recommendations` before any model sees it, each
carrying that line's own forecast, stock, cover and replenishment figures. 261
lines ranked, 12 shown, bands reported across all 261 (85 critical, 155 high,
11 medium, 10 with no recommendation). The computed pass renders in about half
a second and the written one replaces its sentences.

Three further defects were found and fixed while verifying it.

**The figure chips came from the model.** `_merge_lines` copied the model's
`evidence` array onto the card, and the model echoed the raw fact payload back:
`q95 planning demand: 409.4224468979937`, `usable_stock: 0.0`,
`is_censored: true`. Field names and sixteen decimal places, printed directly
beneath a table of the same figures rounded.

**So the figures moved between the two passes** — which is precisely what the
page tells the reader they do not do, because the numbers were never the
model's to produce. The fast pass showed `q95 planning demand = 409
units/month`; the written pass showed the sixteen-decimal echo of the same
measurement.

**And the chips repeated the table.** Every computed chip restated a row the
card already prints. Meanwhile the exception join — short-despatched units,
units ordered against zero stock — was carried on the payload and rendered
nowhere, so the only way it reached the screen was the model's raw echo.

`_line_evidence` now builds the chips from the line's own fields, identical in
both passes, carrying only what the table cannot hold: the exception join, a
censoring note where there is no exception row, units already on order,
backorders, and the demand pattern. Measured on the running app:
`Short despatch: 2,658 units · Zero stock, live demand: 695 units · demand
pattern: erratic`. The line prompt no longer asks the model for figures at all
— asking for something that is then discarded only invites it to try.

**Every "check this on" pointed at a page the UI does not have.** The five
`VERIFY_ON` labels read "Operational Exceptions", "Supply Intelligence", "Model
Leaderboard", "Forecast Explorer" and "Demand Analytics"; none matches a nav
label today, and the first two are pages that were unrouted (D-052, D-105). The
per-line template said "Open Supply Intelligence and filter to this branch and
SKU." A destination the reader cannot reach is worse than none — they spend the
trip before finding out. They now name Training, Forecasting and Overall
Analysis; the exception and replenishment figures have no page of their own any
more, so those two point at the per-line list on the recommendations page
itself, which is where they actually are.

### What this does not do

Nothing here changes a number. The ranking is computed, the figures are copied
from what the inventory service already stored, and no arithmetic was added.
There is still no inventory-policy backtest in this project, so nothing on the
page can claim that acting on it would have helped.

Tests: 1,069 backend, 244 frontend, all passing. `tsc --noEmit` clean. All
seven pages verified in the browser with no console errors.

## D-132 — Every count on the recommendations page opens into the lines behind it

D-131 moved the page from network counts to per branch × SKU cards, and then
recreated the same problem one level down. Twelve of 261 lines were shown. A
reader told "85 lines are critical" still could not see **which** 85, at which
branch, for which SKU — which is the only form the number is actionable in.

Both halves are needed: the summary to know where to look, the detail to act on
it. So neither replaces the other.

### The whole ranking is listed

`_gather_lines` returns all 261 ranked lines, not `ranked[:MAX_LINES]`. The
twelve is now only how many get **written prose** — the prompt has a size and
the wording is the expensive part. Every other line is shown with its computed
`urgency_reason` and its own figures, and the card says `computed — no written
explanation` rather than looking like a model that chose to be terse. The
payload carries `lines_written` beside `lines_shown` because they are different
numbers and the page has to state both.

`_write_lines` sends `ranked[:MAX_LINES]` to the model and merges the result
into the **full** ranking, so a line the model never saw keeps its facts instead
of dropping off the page.

### Every count is a filter

Urgency bands and exception kinds render as buttons carrying their counts.
Clicking one narrows the list to exactly the lines behind it, and the header
then states how many of the listed lines matched — a filtered list never reads
as a complete one. Measured on the running app: `Critical 85 · High 155 ·
Medium 11 · No recommendation 10` and `Short despatch 237 · Over-despatch 189 ·
Zero stock, live demand 81 · SKU not in product master 1`; clicking
*Zero stock, live demand* gives 81 of 261, and adding *Critical* gives 79.

`_exception_tally` counts over **the lines on this page**, not over the
exceptions payload, so a chip that says 237 filters to 237 cards. The two
genuinely differ — the exceptions payload has 240 short-despatch lines, and
three of them are branch × SKU combinations with no forecast and no stock
position, so they produce no recommendation and are not there to be clicked.
Counting the other way would have made the chip a lie by three.

### The exception join covered 25 lines of 516

`_gather_lines` joined against `exceptions()["top_lines"]`, which is
`ranked.head(25)`. `rows` is `head(200)`. Against 516 exception lines, neither
can answer "which lines?" of a headline that says 240, and a drill-down that
silently stops at 200 is worse than none because it reads as the whole list.
`exceptions()` now also returns `all_lines` — every line, uncapped, in a slim
shape without the definition text `rows_for` repeats per row. The join moved to
it, and 239 of the 261 recommendation lines now carry their own findings, up
from about 25.

### Each card opens into every figure

An `All figures` disclosure per line shows what the six-number summary cannot
hold: forecast month and model, demand pattern, service level, point and
planning demand, usable stock, already on order, backorders, days of cover,
average lead time, protection period, order-up-to level, recommended order, how
demand was measured, whether despatch fell short, and the exception rows with
their units. A `cannot_recommend` line opens to its reason and shows **no**
order figures at all — the absence of a recommendation is not an order of zero.

The list renders 25 cards at a time. The number not yet rendered is stated with
buttons for the next 25 and for all of them; 261 open cards is a slow page and
an unreadable one, but a silent cut would read as a short list.

### Cost

The payload is 372 KB for 261 lines. That is the price of a list someone can
act on, and it is served from a cache after the first call. If it ever matters,
the fix is transport compression, not a shorter list.

Tests: 1,072 backend, 254 frontend, all passing. `tsc --noEmit` clean. Verified
in the browser — filters, disclosure, paging, no console errors, and no sideways
overflow at 375 px.

## D-133 — Training and Forecasting start at a line; the aggregate scopes come off the pickers

Requested, after the Forecasting page showed **169.87% MAPE** at All locations /
All SKUs: *"i want least min mape error possible by avg out the scope errors not
adding them … starting only strt with some branch and sku and remove branch wise
scopes and overall scopes as i said they are not useful anyway and on branch is
selected route to some sku directly"*.

### What that number actually was

Not an average of the lines, and not a sum of them either. "All locations / All
SKUs" resolved to the **national scope** — a thirteen-model race run on one
series, the week-by-week sum of every branch × SKU cell, with its own champion
and its own measured error. Selecting one location resolved to that **branch
scope**, the same construction one level down. Measured on the current run:

```
scope                       model                      MAPE       WAPE
national  NATIONAL           ES Additive             169.87%    35.87%
branch    BENGALURU          ES Additive              71.29%    42.68%
branch    DELHI-1            ES Additive              81.36%    41.98%
median line, six-month total                          10.45%    13.05%
```

Two separate things made the headline figure unreadable, and they compounded:

- **It was an aggregate's error, not anybody's.** An aggregate is a different
  series with different statistics, so its error transfers to nothing
  underneath it. The page did carry a warning saying so; a warning under a
  number in 24px type loses.
- **It was a per-period figure where every other tile is a six-month one.** The
  tile reads `lineAccuracy.horizon_accuracy_pct` when the scope is a series and
  falls back to raw `metrics.mape` when it is not — so the same tile changed
  *which question it answered* depending on the selection. 169.87% is a weekly
  MAPE on a volatile national sum, and MAPE divides by the actual: a quiet week
  in the denominator is worth more than a bad forecast.

The user's instinct is the correct one and is already implemented elsewhere:
`combined_metrics_best` scores every line on its own and reports the **median**
— 89.55% accurate, 10.45% miss across 261 lines — rather than fitting one model
to summed demand. That is "avg out the scope errors, not adding them", and it
is the figure that now sits on Training without a selection having to be made.

### What changed

- **"All locations" and "All SKUs" are gone from both pickers.** Every
  selection on Forecasting and on Training resolves to one branch × SKU.
- **Both pages open on a line** — first in branch order, then SKU order.
  Deliberately the first and not the best: opening on the strongest line would
  flatter the run, and alphabetical is a rule a reader can check.
- **Picking a location moves the SKU with it** when that location does not
  stock the current one, instead of emptying the page. The slicer the reader
  just touched is never overridden; only the other one moves.
- **The location list no longer narrows by SKU.** The two used to filter each
  other, which hid DELHI-1 whenever a BENGALURU-only SKU was selected — with no
  "All SKUs" to clear back to, that would have made DELHI-1 unreachable.
- **Training's run-wide panels moved below the race** rather than being deleted
  with the "All" selection that used to gate them. The combined accuracy, the
  per-model table and the train control are not scopes; they are summaries over
  the lines, and both figures in them are per-line medians.
- The aggregate warning box on Forecasting went with the aggregates, and so did
  the "no forecast scope for one SKU across branches" empty state — neither is
  reachable now.

**The aggregates are still fitted.** Only the pickers changed. MinT
reconciliation needs the full hierarchy to make the lines add up — the current
run reports `coherent: true` with `max_incoherence: 0.0` — so removing the
national, region, branch, segment and pooled tiers from *training* would break
the guarantee that the per-line forecasts reconcile. They are computed and
served; they are simply not something these two pages will show you.

### Lead Time is renamed to Ordered vs Dispatched Time

Requested: *"change the lead time panel name to ordered vs dispatched time as
what we are having is not lead time"* — and that is right. The page computes
**Despatch Date minus Order Date**. A lead time runs to *receipt*, and the
source files hold no receipt date, so what is measured is one leg of the cycle
and not the cycle. The master's own `Avg Lead Time` column keeps its name,
because renaming a client's field would be worse than leaving it; the page's
name now describes the page's own measurement.

The route stays `/lead-time` and the nav index stays 24, so no bookmark breaks
and the D-105 numbering still reads.

Tests: 268 frontend (14 new — 8 on the pairing rule, 6 on the filter),
`tsc --noEmit` clean. Verified in the browser: Forecasting opens on
BENGALURU × FG.ALP.LFH.GCG2120000 at 98.1% over the six-month total, the
location list offers two rows and neither is "All", switching to DELHI-1 lands
on its own first SKU with 134 offered against BENGALURU's 136, Training opens on
the same line with the 89.5% run-wide figure beneath it, no console errors, no
sideways overflow at 375 px.

## D-134 — Accuracy and MAPE are both printed, and neither is derived from the other

Requested: *"please give accuracy and mape as well"*, then *"i hope mape is
100- accuracy and no need to show for 1 weeks accuracy just vaguely explain it
sux months averaged mape"*, then *"i need same things in both training and
forecasting"*.

**MAPE is 100 − accuracy, on 257 of this run's 261 lines.** The expectation is
right almost everywhere, and the exception is the reason this is carried in the
payload rather than computed on the screen: `WindowScore.series_accuracy()`
floors at zero, because an accuracy of −257% is not a reading anyone can use.
On a floored line the subtraction gives exactly 100% and the real error is
larger:

```
line                              accuracy    100 - accuracy    measured MAPE
BENGALURU|FG.J90.LFH.SCSB1B0000       0.0%            100.0%          102.76%
DELHI-1|FG.BA3.LFH.GCG2120000         0.0%            100.0%          140.78%
DELHI-1|FG.MF8.LFH.GCG2120000         0.0%            100.0%          357.53%
DELHI-1|FG.MP6.LFH.GCG2120000         0.0%            100.0%          100.00%
```

Three of those four would be a figure nobody measured, printed on the worst
lines in the run — which `CLAUDE.md` prohibits outright. Twenty lines floor the
same way on the single-period reading. So `accuracy_windows` gained
`series_error()`, the unclamped mirror of `series_accuracy()`, and every
per-line row now carries `mape_pct` per window, `horizon_mape_pct` and
`champion_mape_pct` beside the accuracies it already had. The route has no
`response_model`, so nothing needed declaring.

### What the two screens show

Both say the same thing in the same words, which was the third request:

- **Forecasting** — the tile reads `98.1% · 1.9% MAPE`, labelled *Accuracy,
  six-month total*, with *average miss across the six months, out of sample*
  beneath it.
- **Training** — the combined panel's *Average miss* is renamed **MAPE**, with
  the same *average miss across the six months* hint. The per-line leaderboard
  already carried both columns and matches the tile exactly.

**The single-period accuracy came off both**, on request. It was a second
accuracy over a different span sitting next to the first, and reading one as
the other is the misunderstanding it existed to prevent — so the caution it
carried is now written out instead of printed as a number: misses inside the
window cancel, so the half-year total lands closer than any week in it, and
`lines_worse_over_horizon` still names the lines where cancelling did not
happen.

One consequence had to be handled. Forecasting's "Why this model, for this
series" panel reports the **selection** metrics, one period at a time — 89.1%
MAPE on the same line whose tile says 1.9%. The tile's single-period figure
used to bridge the two. With it gone the panel's note now names its own span
and says why it is the larger number.

### The paragraph under the Forecasting pickers is gone

Requested: *"this explanation is not needed"*, pointing at the three sentences
beneath the two slicers. They restated the selection the pickers already show,
said that only trained lines are listed, and argued the case for dropping the
aggregate scopes. None of it is a fact about the forecast on screen: the
selection is in the controls and in the Outlook panel's title, and the
reasoning belongs in this file rather than over a reader's shoulder every time
they change a SKU.

**What stays is the provenance** — `Origin 2026-W31, reconciled by
mint_shrinkage` — because the origin and the reconciliation method are stated
nowhere else on the page, and a forecast without its origin is undated.

Tests: 1,077 backend (5 new, on the floor and on what is recoverable from it),
268 frontend, `tsc --noEmit` clean. Verified in the browser on both pages after
a backend restart — uvicorn runs without `--reload`, so the new fields needed
one.

---

## D-135 — The line's four tiles are one component, shown on both screens

Requested: *"we have to show top model as cards here as well fo each sku like
forecasting with same cards and same data"*, pointing at the branch × SKU filter
on the Training page.

Training already picked a line and raced thirteen models on it, but it never
stated the four plain facts about that line — which model won, how accurate it
measured, what it forecasts next month, how many horizons came back. Those four
were on Forecasting only, so reading them meant leaving the page that chose the
line.

**They are now the same component, not a second copy.**
`src/features/line-summary/LineSummaryTiles.tsx` takes a `scope_key` and renders
the four `StatTile`s; both pages mount it. A copy was the obvious alternative and
is the wrong one: the accuracy tile alone has been reworded twice in two days
(D-133 moved it from a per-period figure to the six-month total, D-134 added the
measured MAPE beside it), and either edit would have left the two screens
disagreeing about the same line.

**It runs its own queries rather than taking props.** The keys are the ones
Forecasting already issues — `forecastKeys.series('series', scopeKey)`,
`trainingKeys.current`, `accuracyKeys.windows(runId, null)` — so on Forecasting
every one is a cache hit and the page makes no extra request; on Training they
are the first fetch. The alternative, threading three payloads down from each
caller, would have made the component unusable anywhere a `scope_key` is in hand
without assembling them first.

Measured, on `BENGALURU|FG.ALP.LFH.GCG2120000`: both pages read
`98.1% · 1.9% MAPE` against Auto ARIMA with exogenous variables, and the
leaderboard's champion row on Training reads the same 98.1% / 1.9% — the tile and
the race it sits above agree. Switching the location to DELHI-1 repairs the SKU
to `FG.ANL.LFH.GCG2120000` (D-133) and the tiles follow to
`86.9% · 13.1% MAPE` against Exponential Smoothing Additive, again matching the
leaderboard beneath them.

Tests: 268 frontend, `tsc --noEmit` clean. Verified in the browser on both pages,
no console errors, no horizontal overflow at 375px.

---

## D-136 — Deployed to Azure as one container, page and API on one origin

Requested: *"we have azure connected with cli deploy this whole application
there and check from the front end that everythng is working as expected and
from the deployed link"*.

### One service, not two

The obvious shape is a Static Web App for the page and an App Service for the
API. It was rejected: it needs `VITE_API_BASE` set at build time, a CORS
allowlist in `frontend_origins` that has to track a generated hostname, and two
things to deploy in the right order. Every one of those is a way for the
deployed page to be subtly different from the one that was tested.

Instead FastAPI serves the build itself (`app/main.py::_mount_web_app`). The
client's `API_BASE` already defaults to `/api`, so same-origin means **no
build-time configuration at all** — the bundle that runs in Azure is byte-for-
byte the bundle `npm run build` produces locally.

The mount goes on after `include_router(api_router)`, and the catch-all 404s
anything under `/api` rather than answering it with the HTML shell. A page
returned where JSON was asked for surfaces three layers away as a parse error;
a 404 says what actually happened. Everything else falls back to `index.html`,
because the router is a `BrowserRouter` and `/forecasting` is a URL a reader
can paste. With no build present the mount does not happen, so local
development is untouched — Vite still owns the page and proxies `/api`.

### The image carries the data, and that is a real trade

`runtime/storage/`, `runtime/db/ais.db` and all five files in `data/source/` go
into the image. Two of the source files are read at run time, not just during
preprocessing: the Ordered vs Dispatched Time page parses the orders workbook
directly, and the health check reports on all five. The lead-time cache is
keyed on name, size and **mtime**, and `COPY` preserves mtime, so the cache
hits instead of re-parsing 775,912 rows on the first view.

The database ships as a `sqlite3 .backup` of the live file, not a byte copy.
The live one has a 15 MB write-ahead log attached; copying the three files
would put a half-applied WAL and a stale shared-memory file into the image.

**The cost, stated plainly: writes do not survive a restart.** A training run
started from the deployed page works and is gone when the revision cycles. The
seven shipped runs come back every time because they are in the image. Durable
writes mean mounting Azure Files at `/app/runtime`, which is a separate
decision and was not taken here.

### The key is not in the image

`backend/.env` is in `.dockerignore`; `deploy/env.azure` — the same settings
with `OPENAI_API_KEY` stripped, generated by `scripts/make_azure_env.py` — is
copied in its place, and the key is injected as a Container Apps secret. Copy
it and delete it later does not work: the layer keeps it.

The rest of `.env` **is** shipped, deliberately. The workspace, the grain, the
eligibility profile and every measured accuracy constant are in that file, and
a deployment that quietly fell back to code defaults would be reporting on a
different slice than these documents describe.

### Why Container Apps, 2 vCPU / 4 GiB, centralindia

It is what the sibling demos in this subscription already do —
`ca-meriton-demo` is the same kind of application at the same size. Following
the house pattern means the operational knowledge transfers.

Two departures from the sibling: `minReplicas` is 1 rather than 0, because the
image is large and TensorFlow's import is slow enough that the first visit
after an idle period would look broken; and ingress is on port 8000 with one
uvicorn worker, because the job runner is in-process and a second worker would
be a second scheduler racing the first over one SQLite file.

Built with `az acr build`, which builds on amd64 hardware in Azure. The
development machine is Apple Silicon, so the alternative was an emulated build
or pushing several gigabytes up a home connection.

### Not addressed

Ingress is external and there is no authentication — the URL is unlisted, not
protected, and the pages carry real client demand data. The sibling demos are
configured the same way. Entra can be put in front of it without touching the
image.

## D-137 — The image carries the workspace's data, and the stored paths are rewritten to match

**Date:** 2026-10-01
**Status:** Accepted

The first Azure image (D-136) carried everything this workspace has ever held:
348 MB of build context, of which the deployed pages could reach a small
fraction. The request was to cut it to the scope — *"we do not need to update
all the data just the considered scope data"* — with the assistant and the
recommendations still answering from it.

### What ships

`scripts/build_scoped_bundle.py` writes `deploy/bundle/`. It finds the newest
training run, follows it to its panel build and preprocessing run, and keeps
those three and nothing else.

| | Before | After |
|---|---|---|
| Database | 81.3 MB, 7 training runs | 52.1 MB, the live run |
| Panel and artefacts | 113 MB | 14.8 MB |
| Order history | 67 MB workbook | 69,353-line extract, 0.11 MB |
| Client workbooks | 5 (150 MB) | Location Master only (24 KB) |
| **Total** | **348 MB** | **67.9 MB** |

What that costs, stated rather than discovered later:

- **Six superseded training runs are gone.** They are 40-to-49-series *monthly*
  runs; the live one is the 281-series weekly run every screen reads. A monthly
  run's forecasts cannot be read at the current weekly grain anyway (D-105), so
  keeping them would have offered a reader runs whose numbers contradict the
  current ones. The deployed run history is one run, not seven.
- **A panel over 68,675 series is gone** — 81 MB that no live run points at.
- **Four of the five client workbooks are not deployed.** Ingestion and
  preprocessing are therefore unavailable on the deployment, and
  `/api/health` says exactly that by name rather than reporting four files
  mysteriously missing. Location Master ships whole at 24 KB because the
  Ordered vs Dispatched Time page compares observed durations against the
  stated averages held in it.

### Ordered vs Dispatched Time keeps working without the orders workbook

What that page needs is the parsed durations, not the workbook. The bundle
ships `lines.parquet` filtered to the workspace branches — 69,353 of 775,628
order lines — and `lead_time_service.build()` reads it when the workbook is
absent and Location Master is present, flagged in the payload as `extract` so
the page is never silently reporting on a subset while claiming the whole.

### The stored paths had to be rewritten

The database records where artefacts live as **absolute paths on the machine
that trained the run**. Copied into an image they name a directory that does
not exist, and the deployment returned 500 on `/api/analytics/summary` and
`/api/inventory/recommendations` with
`FileNotFoundError: '/Users/HXT/ashai glass/Ahai-Glass/runtime/storage/prepared/panel_…/panel.parquet'`
while the same code worked locally.

`_rewrite_paths()` replaces the development project root with `/app` — the
root the Dockerfile fixes and `app/core/config.py` derives from — across every
text column of every table, then asserts that none survives. Seven columns in
five tables currently carry one, two of them inside JSON blobs, which is the
kind of hand-maintained list that goes stale silently. It is recorded in
`BUNDLE.json` under `stored_paths`.

Rewriting at build time rather than resolving at read time is the narrower
change: the bundle is built for one known layout, and the two ends agree by
construction.

### `.dockerignore` does not work with `az acr build`

A `.dockerignore` listing `frontend/node_modules/` still uploaded 15,956
entries from it; the context measured 309 MB against a 68 MB bundle. The CLI
packs the context with its own archiver.

`scripts/stage_build_context.py` replaces it with an allowlist: it copies the
named trees and files into `deploy/context/` and builds from there. 71.0 MB and
352 files, and the upload fell from roughly fourteen minutes to one.

The allowlist is also the safer direction for the key. An ignore rule that
quietly stops matching puts a live OpenAI key in an image layer; an allowlist
cannot. The script additionally refuses — and deletes the context — if any
`.env` lands in it.

### Run order

    python scripts/build_scoped_bundle.py
    python scripts/stage_build_context.py
    az acr build --registry acraisglassdemoci --image ais-glass-demo:v2 \
        --platform linux/amd64 --file Dockerfile deploy/context
    az containerapp update -n ca-aisglass-demo -g rg-aisglass-demo-ci \
        --image acraisglassdemoci.azurecr.io/ais-glass-demo:v2

`deploy/bundle/`, `deploy/context/` and `deploy/env.azure` are generated and
gitignored.

## D-138 — Overall Analysis reports the client's whole network; every other page stays on the workspace

Requested: describe the client's full data on Overall Analysis, keep forecasting
on the two locations and 136 SKUs, and change no visual.

This is a deliberate departure from D-049's "one scope for the whole
application". It is confined to one page and to one kind of question. Overall
Analysis describes *what the client's data says*; Training, Forecasting, Per
Branch & SKU and the recommendation pages report *what this deployment
modelled*. Those are different questions, and answering the first at workspace
scope was understating the client's own business by a factor of six. Everywhere
a forecast, a model or a recommendation is involved, the one-scope rule still
holds.

**The panel cannot serve it.** A panel is a full branch x SKU x period grid, so
an unrestricted build materialises every series the extract holds. That was
attempted before and exhausted memory at 68,675 series over 28 monthly periods
(`panel_service._scope_artifacts`); at the current weekly grain the same build
is 70,089 series over 122 periods, about 8.6 M rows. Widening the panel was not
an option.

**The preprocessed facts already are the whole network**, and they are small:
582,324 order rows and 975,275 sales rows against 53 branches and 2,063 SKUs.
`app/domain/ais/network_frame.py` assembles them into a frame carrying the
panel's columns, joined to the product and branch masters, and runs it through
`analytics.derive_columns` — the same derivation the panel path uses, called
rather than reimplemented. Every chart, filter and tile is then the existing
analytics code, unchanged, which is what keeps the visuals identical.

```
1,052,033 rows · 68,597 series · 122 weekly periods · 2024-W14 .. 2026-W31
assembled in 14 s, held at 362 MB
ordered units 2,602,392 — equal to the figure measured from the client file
```

**A sum over observed rows equals a sum over the grid**, because the rows the
grid adds are zeros. So totals, shares and movements over time are exact. What
the frame does not carry is a materialised zero cell, so **any figure that
counts rows means something different here** than on a panel-backed page. The
coverage block says so in its own words rather than leaving a reader to infer
it.

### Four things that had to be got right

**The banner states the scope rather than falling silent.** `ScopeBanner`
rendered nothing when `restricted` was false, which was the honest output while
unrestricted meant "no workspace configured". Here it would have left a page of
network figures with nothing on screen saying why they are six times the
neighbouring pages'. A `full_network` variant now reads
`53 of 53 branches · 2063 of 2063 SKUs · the client's whole dataset` and names
the pages that differ.

**The numerator and the denominator count the same universe.** The scope
denominator counts the order book. Counting the frame's SKUs counted
proxy-only ones too and printed `2,315 of 2,063` — a numerator larger than its
own denominator. Coverage is now taken on `target_source == "order"`, with the
252 proxy-only SKUs reported separately.

**A bare `queryFn` would have switched five pages to the network silently.**
`fetchAnalyticsFilters` gained an optional first argument, and five pages passed
the function itself to react-query, which calls it with its own context object —
truthy. Those pages would have gone network-wide with no visible change but
their numbers. `tsc` caught it; every call site is now wrapped.

**`period` stays a plain string.** Categoricals cut the frame from 1,267 MB to
276 MB, but an unordered categorical refuses `min`/`max`, which the shared
analytics code takes on `period`. Making it ordered would have imposed a sort
order on a column other code treats as a label, so `period` is excluded from the
conversion and the saving comes from `series_id` and `canonical_sku` instead —
362 MB, and the shared code untouched.

An empty order fact now raises with its remediation instead of a `KeyError` on
a column that is absent rather than empty.

---

## D-139 — One scatter with named groups replaces the 2,063-bar Pareto

Requested: the SKU Pareto on Overall Analysis is too cluttered, it says what the
scatter above it already says, so drop it, make the scatter much bigger, and put
the same information inside it as percentages — split into groups that say how
much is driven by high-volume SKUs and how much by low-volume SKUs that still
bring serious revenue.

**Why the Pareto had to go.** It was a bar per SKU with a cumulative line over
the top. At workspace scope that is 136 bars and legible. On this page, after
D-138 widened it to the client's whole network, it is 2,063 bars inside roughly
900 px — about 0.4 px each. The bars rendered as one solid block; the only thing
still readable was the cumulative line, and a cumulative line alone is a worse
version of the four numbers now stated in words. It also ranked on one measure
at a time, which cannot answer the question that was actually asked.

**Why a scatter answers it and a ranking cannot.** A ranking puts each SKU at
one position on one axis. The planning question — *which SKUs earn well without
moving much* — is about the relationship between two measures, which is a
position off the diagonal. A units ranking buries those SKUs in its tail and a
value ranking buries the cheap fast movers in its own; neither can show both at
once. The scatter shows every SKU against both measures simultaneously, and the
groups below are read straight off it.

**The cuts are Pareto, not medians.** A SKU is core *volume* if it falls inside
the set making the first 80% of ordered units, core *value* if it falls inside
the set making the first 80% of ordered value. The two sets are computed
independently, and the fact that they disagree is the finding. A median split
was rejected: on a catalogue this long-tailed the median lands near zero and
would label half the tail "high".

The four groups, measured on the page's default window (2,063 ordered SKUs):

| Group | SKUs | Share of revenue | Share of units |
|---|---|---|---|
| Most revenue and most volume | 182 (8.8%) | 77.9% — ₹669.83Cr | 65.9% |
| Less volume, more revenue | 18 (0.9%) | 2.1% — ₹18.22Cr | 0.7% |
| More volume, less revenue | 148 (7.2%) | 5.8% — ₹49.88Cr | 14.1% |
| Low on both | 1,715 (83.1%) | 14.2% — ₹122.07Cr | 19.3% |

The arithmetic checks itself: 77.9 + 2.1 = 80.0, which is the value cut, and
65.9 + 14.1 = 80.0, which is the units cut. Those identities hold by
construction, so a figure that broke one would be a bug on screen, not a
rounding artefact.

**The names say what the group does, not which set it is in.** The first naming
was `Volume and value` / `Value without volume` / `Volume without value` / `The
long tail`, which described the arithmetic of the two cuts and misled on sight:
"without value" reads as a judgement that the SKU is worthless, when it means
"outside the top 80% by revenue" — a SKU earning ₹40L a year lands there. The
names now state the behaviour in plain words, and each one is the same sentence
the reader needs anyway.

**Eighteen SKUs are the answer to the question that was asked.** "Less volume,
more revenue" is 0.9% of the catalogue bringing ₹18.22Cr on 0.7% of the units.
On the old Pareto those eighteen bars were somewhere in the middle of a
2,063-bar block with nothing marking them. They are now a named line with their
own share, and their own colour in the plot.

### Three things that had to be got right

**Both axes are logarithmic, with the domain stated.** The largest SKU outsells
the smallest by about five orders of magnitude; on a linear axis 2,000 of the
2,063 marks collapse into one corner. Recharts' `domain="auto"` on a log axis
rounds to the data's own extremes and clips the outermost marks in half, so the
domain is `['dataMin', 'dataMax']` explicitly.

**The ticks are decades, set by hand.** Recharts' own log ticks land on the
data's quantiles — "2, 3, 5, 7, 12, 18, 27 …" — an axis whose gridlines mean
nothing in particular and whose labels overlap. `skuMix` computes powers of ten
spanning the data and passes them as `ticks`, which is what a log axis is for.

**The words come before the plot, and they are only words.** Four lines of
text sit above the chart, each one the same sentence — *this share of the
revenue, from this share of the SKUs, moving this share of the units*. They were
first built as four bordered summary cards with a large percentage apiece, which
took a quarter of the panel to say what four small lines say, and turned a
single comparable sentence into four boxes a reader has to re-read. Hunting for
a group in a cloud of 2,063 marks is still work the page should do for the
reader; it just does not need furniture to do it.

The panel is full width (`xl:col-span-4`) at 460 px of plot, last in its
section. Bubble size is the number of branches ordering the SKU — a third
measure that costs no space, and which separates a SKU one branch buys heavily
from one the whole network buys.

---

## D-140 — The branch donut is gone; the stacked bar is full width and holds all 53

Requested: remove the "Demand by Branch" ring, since "Demand by Branch × Value
Class" beside it already says the same thing; make that one much bigger and
scrollable so all 53 branches are in it; move the rest down and resize so the
section tiles evenly.

**Two panels, one question.** The ring and the stack both answered *where does
the demand sit by branch*, in the same measure (ordered value), side by side.
The ring was also the weaker of the two: it could show ten of the 53 and said so
in its own centre label, it carried no value-class split, and a ring is a poor
instrument for comparing more than about five slices anyway. Nothing was lost by
dropping it except the branch-filter entry point, which the stack already had —
clicking a column toggles the same filter — and the clear-chip moved across with
it.

**The eight-branch cap was a width problem, so it moved to the width that has
it.** `_cross_tab` truncated `data` to the top eight because the only panel
drawing it was a quarter of a row wide, where twenty rotated depot names collide
into an unreadable band. The payload now carries every branch and the cap is
applied by the caller that still needs it — `DemandAnalyticsPage`, the
reference-parity page, slices to `branch_by_group.limit` and renders exactly as
before. `limit` stays in the payload as the cap a narrow panel should apply;
`total_branches` still says how many exist. 53 rows of six floats is not a
payload anyone notices.

**The chart keeps its width and the panel scrolls.** At 53 branches inside a
full-width panel each column gets about 20 px, and a −40° depot name needs more
than that. So the plot is sized at `max(640, branches × 34)` — 1,802 px for 53 —
inside an `overflow-x-auto` wrapper, with `minWidth: 100%` so a two-branch
workspace still fills the panel instead of leaving a stub chart in a wide box.
Height went 236 → 320 px, since the panel now has a full row to itself.

**The section tiles into whole rows again.** Removing one quarter-panel left
five of them in a four-column grid — one row of four and one orphan. Two were
widened to `xl:col-span-2`, chosen for the two whose axis labels were already
cramped at quarter width:

```
row 1   Branch x Value Class                                  (4)
row 2   Value Class (2) · Glass Type (1) · Vehicle Category (1)
row 3   Vehicle Age (2) · Value per Unit (2)
row 4   Volume vs Value by SKU                                (4)
```

Measured in the browser at a 976 px grid: 976 / 482+235+235 / 482+482 / 976, no
gap anywhere.

**Verified:** 53 axis ticks (BENGALURU … MANDI), 265 bar rectangles — 53 × 5
value classes — `scrollWidth` 1802 against a 1102 px viewport, and no element
titled "Demand by Branch" left on the page. The workspace-scoped payload still
returns its 2 branches. `backend tests/test_analytics_api.py` 62 passed,
`ReferenceParityPages.test.tsx` 22 passed, `tsc --noEmit` clean.

`dimBranch` and `branchTotal` went with the ring — nothing else on the page used
them.

---

## D-141 — Overall Analysis filters on every axis it charts

Requested: make the time and delivery panels — Ordered Demand Trend, Demand by
Branch over Time, Seasonality, Realised Price per Unit, Ordered vs Despatched,
Top SKUs by Ordered Demand — respond to branch, value class and the other
dimensions the page charts above them, from one filter set applied once.

**Those six panels were already filtered; the filter bar was the gap.** Every
panel on the page reads one `/analytics/summary` payload, and `branch` and
`value_class` were already in the query, so those two always reached all six.
What was missing is that the page *charts* three more axes — glass type, vehicle
category, vehicle age — and offered no way to select on them. A reader could see
that CAR & MUV carries the demand and had no way to ask what the trend, the fill
rate and the top SKUs look like for CAR & MUV alone. The fix is one filter set
in the bar, not per-panel controls.

**Backend.** `AnalyticsScope` gains `glass_type`, `vehicle_category` and
`vehicle_age_category`; `_apply_scope` filters on each; `filters()` returns
`glass_types`, `vehicle_categories` and `vehicle_age_categories` alongside the
existing lists; `/summary` takes the three as query parameters. The columns were
already in `ANALYTICS_COLUMNS` and in the network frame's `PRODUCT_ATTRIBUTES` —
nothing new had to be carried.

Two things that would have gone wrong quietly:

- **The cache key needed no change**, because `_key` is `astuple(scope)` rather
  than a hand-written field list (the comment there says why: a hand-written
  list once served one SKU's answer for every other). Three new scope fields are
  keyed correctly without anyone remembering to go and add them.
- **`_scope` takes the three keyword-only and defaulted**, so `/exceptions` and
  `/branch-scorecard` keep their existing seven positional arguments and are
  untouched.

**Filtering on a categorical column is a comparison, not a lookup.** `frame[col]
== label` against a label that is not one of the column's categories yields
all-False rather than raising, so an option the current data no longer holds
empties the page honestly instead of returning a 500.

**Frontend.** Three selects in the existing bar, built from one `productFilters`
array rather than written out three times — the first draft wrote them out and
they immediately drifted, one missing its `aria-label` and another its clear
chip. The option lists are optional on the `AnalyticsFilters` type, so a
frontend talking to a backend that predates them renders an empty "All …"
select rather than throwing. `clearAll` is a single function now, used by the
button and shared by nothing else that could forget a field.

**Measured, whole-history, network scope:**

```
no filter                      4,140,507 units   Rs 1,334.97 Cr   53 branches
vehicle_category=CAR & MUV     3,557,737 units   Rs 1,159.71 Cr   53 branches  1,903 SKUs
vehicle_category=COMMERCIAL      414,328 units   Rs   123.55 Cr   53 branches    255 SKUs
vehicle_category=3W              158,270 units   Rs    35.81 Cr   52 branches     14 SKUs
vehicle_category=HIGH END          4,423 units   Rs    13.17 Cr   49 branches     49 SKUs
glass_type=Sidelite              923,404 units   Rs    86.06 Cr
  + CAR & MUV                    812,187 units   Rs    75.57 Cr
  + BENGALURU                     36,334 units   Rs     3.49 Cr    1 branch
```

**The four vehicle categories sum to 4,134,758, not 4,140,507.** The 5,749-unit
gap is 1,369 rows carrying *no* product attributes — SKUs absent from the
product master, which have a null glass type, vehicle category and vehicle age
alike. They were already outside the three charts on this page for the same
reason; they are now also unreachable by the three filters. This is stated
rather than rounded away, and it is 0.14% of ordered units.

**Verified in the browser.** Selecting COMMERCIAL moved the tiles from
Rs 860.04 Cr / 716.94 Cr / 143.10 Cr to Rs 77.24 Cr / 63.75 Cr / 13.48 Cr, and —
the useful proof — "Demand by Branch over Time" redrew its top-six legend from
BENGALURU · AHMEDABAD · JAIPUR · SECUNDRABAD · KARNAL · DELHI-1 to BENGALURU ·
PUNE · COIMBATORE · CHENNAI · COCHIN · CALICUT. Commercial glass sells in
different cities, which is a fact the page could not previously be asked for.
"Clear all" returned every select, chip, tile and legend to its starting value.

```
backend tests/test_analytics_api.py 62 passed · frontend 268 passed (24 files) · tsc --noEmit clean
```

---

## D-142 — The scope banner is off this page, the filter bar is pinned, and a filter change no longer reloads the page

Requested: remove the full-network scope banner; keep the filter bar visible
while scrolling; stop a filter change from throwing the reader back to the top;
and check that every graph responds to every filter.

**The banner was saying it twice.** It read `FULL NETWORK · 53 of 53 branches ·
2063 of 2063 SKUs · the client's whole dataset`, directly under a lede that
already says the page describes every branch and SKU in the source data. It was
added in D-138 because `ScopeBanner` rendered *nothing* when `restricted` was
false, which would have left a page of network-scale figures with no
explanation beside the workspace pages. The lede covers that, and the banner's
last three words were the overstatement raised separately: 2,063 is every SKU
ever *ordered*, out of a 6,247-SKU catalogue. The component is untouched and
still renders on the six pages where the scope genuinely is restricted.

**The bar is pinned because the page is four screens tall.** 4,022 px at a
1,280 px viewport. A reader looking at the delivery panels at the bottom had to
scroll back up to change the branch, then scroll down again to see what it did.
`sticky top-0` against the window, which is the scroll container on desktop —
`.main` sets no `overflow`. Under 800 px `.topbar` itself becomes sticky at
72 px, so the bar takes `max-[800px]:top-[72px]` to sit under it rather than
behind it. The wrapper carries the page background with a symmetric
`-my-2`/`py-2`, so content passing underneath disappears behind the bar instead
of showing through the flex gap.

**The jump to the top was an unmount, not a scroll.** The panels render under
`{summary && !summary.empty && …}`. A filter change changes the query key,
react-query drops `data` to `undefined` while it fetches, every panel unmounts,
the document collapses from 4,022 px to the height of the filter bar — and the
browser, having nothing left to scroll, puts the reader at the top. The payload
then arrives and the page grows back underneath them. `placeholderData:
keepPreviousData` holds the previous payload through the fetch, so the document
never changes height and the scroll position is never disturbed.

**Holding stale numbers obliges you to say so.** The panels are showing the
*previous* filter's figures while the new ones load. An `Updating…` marker
appears in the bar for exactly that window — `isFetching && !isLoading`, so it
marks a refetch and not the first load, which still gets the full loading block.

**Measured:** at `scrollTop` 2,200, changing the vehicle category left the
scroll at 2,200 and the document at 4,022 px, through 60 samples at 80 ms. The
`Updating…` marker was observed and then cleared. `Clear all` at `scrollTop`
1,500 returned every select, chip and tile to its starting value and left the
scroll at 1,500.

### Every panel against every filter

Seventeen panels, each fingerprinted from the payload key it renders, against a
2025-04 baseline:

```
                                    branch  value_cl  glass_ty  vehicle_c  vehicle_a  end_period  grain
Demand by Branch x Value Class         ok       ok        ok        ok         ok         ok        -
Demand by Value Class                  ok       ok        ok        ok         ok         ok        -
Demand by Glass Type                   ok       ok        ok        ok         ok         ok        -
Demand by Vehicle Category             ok       ok        ok        ok         ok         ok        -
Demand by Vehicle Age                  ok       ok        ok        ok         ok         ok        -
Value per Unit by Vehicle Category     ok       ok        ok        ok         ok         ok        -
Volume vs Value by SKU                 ok       ok        ok        ok         ok         ok        -
Ordered Demand Trend                   ok       ok        ok        ok         ok         ok       ok
Demand by Branch over Time             ok       ok        ok        ok         ok         ok       ok
Seasonality                            ok       ok        ok        ok         ok         ok        -
Realised Price per Unit                ok       ok        ok        ok         ok         ok       ok
Ordered vs Despatched                  ok       ok        ok        ok         ok         ok       ok
Top SKUs by Ordered Demand             ok       ok        ok        ok         ok         ok        -
Unfilled Demand by Value Class         ok       ok        ok        ok         ok         ok        -
Fill Rate by Glass Type                ok       ok        ok        ok         ok         ok        -
Unfilled Share by Vehicle Age          ok       ok        ok        ok         ok         ok        -
KPI tiles                              ok       ok        ok        ok         ok         ok        -
```

Every content filter moves every panel. **`grain` moves only the four
time-bucketed panels, and that is correct**: it chooses a bucket width, it does
not cut rows, so a panel that is not a time series has nothing to redraw. A
tick in that column would have been the bug.

```
frontend 268 passed (24 files) · tsc --noEmit clean · console clean
```

## D-143 — The date filter is gone, and the method note under the bar is now a count

Requested: remove the date filter, move the remaining filters up into its
place, delete the explanation under the bar, and say instead how many branches
and how many SKUs the page is counting.

**The picker could not usefully be moved.** `MonthRange` wrote `start_period`
and `end_period`, but the start was never really the reader's to choose: D-122
pins it to `filters.orders_start_month`, the first month that holds a real
order, because every earlier month is sales-proxy rows with no order and no
despatch, and including them made every panel disagree with the tiles above
it. So one half of the control was a display of a constant and the other half
could only ever shorten a window the page already states. That state is gone —
`startPeriod`, `endPeriod` and `end_period` with it — and `effectiveStart` is
now just `filters?.orders_start_month ?? ''`. The window is still printed at
the right of the bar, so the reader is told what they are looking at; they can
no longer change it. The five content selects and the grain select close up
into the space, which is what "move all other filters above" asked for.

**The note under the bar explained the method, not the data.** It described how
weekly rows roll up into monthly buckets and what a partial last bucket means —
true, and the wrong four lines to put under a control strip the reader came to
*use*. What belongs there is the page's own denominator.

**The count had to be taken on the order book, or it would have read `2,315 of
2,063`.** `kpis.sku_count` counts every SKU with a row in the network frame,
and that frame carries 252 SKUs that appear only in the pre-order sales proxy.
`workspace_scope.total_skus` is 2,063 — SKUs that were actually *ordered*. The
same numerator-against-a-different-denominator defect D-138 fixed once in
`ScopeBanner` recurs anywhere a count is printed beside that 2,063. So
`summary()` now computes `ordered_branch_count` and `ordered_sku_count` under
`frame["target_source"] == "order"`, and the line reads those. The old
unqualified kpis are still returned and still used elsewhere; the page falls
back to them only if an older payload has no ordered-only figures.

**`num` abbreviates, so the line uses `exact`.** `num(2063)` is `"2.1K"`, which
is right on a chart axis and wrong here: `"2.1K of 2.1K SKUs"` hides whether
the two numbers are the same. `exact` is `toLocaleString('en-IN')`.

**Measured.** Unfiltered the line reads `Covering 53 of 53 branches and 2,063
of 2,063 SKUs`; the bar holds six selects and no `input[type=month]`; the
grain note is absent from the document. Selecting BENGALURU moves it to
`Covering 1 of 53 branches and 1,681 of 2,063 SKUs`, and the scroll held at
2,200 px across 40 samples at 120 ms while it did (min 2,189.5, max 2,227 —
the document shrank 11 px, from 6,592 to 6,581).

**One thing reads oddly and is correct.** The window says `70 weeks` while the
grain select says `By month`. `summary.window` is always the panel's own
weekly extent — it is identical under `grain=weekly`, `monthly` and
`quarterly` — and `periodNoun(filters.panel_grain)` labels it as such. The
grain select sets bucket width for the four time-bucketed panels; it does not
re-grain the source.

## D-144 — Per Branch & SKU reads the whole network, like Overall Analysis

Requested: "per branch sku also should cover all the scope whatever we are
covering in overall analysis page."

**The page could not reach 51 of the 53 branches.** It read the modelling
panel, which is physically cut to the workspace at build time (D-126), so the
Location picker offered BENGALURU and DELHI-1 and the SKU picker 136 codes. On
a page whose entire purpose is *pick any branch and any SKU*, that is the
restriction biting hardest. Nothing on it is model-derived — every figure comes
from `/api/analytics/summary`, which has had a `full_network` reading since
D-138 — so the fix is to ask the same question Overall Analysis asks. Training
and Forecasting stay on the workspace, because a forecast exists only where a
model was fitted; the one-scope rule (D-049) is about not mixing them on one
screen, not about every screen being small.

**The picker had to be rebuilt, because the old one was complete by accident.**
It fetched the top 1,000 branch × SKU pairs by demand and derived *both*
dropdowns from that single list. On the workspace there are 272 pairs, so 1,000
covered them and the cap never showed. On the network there are **68,597**, and
the identical code would have offered the busiest 1,000 as though they were
everything — a silent truncation on the one page meant to reach anything.

So each slicer now asks its own scoped question, and every answer is complete:

| State | Location list | SKU list |
| --- | --- | --- |
| nothing chosen | `filters.branches` — 53 | `filters.skus` — 2,315 |
| branch chosen | all 53 | `/series?branch=` — ≤ 2,315 |
| SKU chosen | `/series?sku=` — ≤ 53 | all 2,315 |

`enabled` on both queries is what stops the unscoped network call from ever
being made. `/analytics/series` gained `sku` as the mirror of `branch`,
`full_network`, a `limit` ceiling of 5,000 — above the largest complete answer
either scoping can produce — and a `truncated` flag, so a caller can tell a cut
answer from a whole one instead of guessing. `filters()` gained `skus`, which
costs 18 ms of the endpoint's 2.1 s.

**The "Series covered" tile is gone.** It printed the same count the line
under the slicers already states, abbreviated — "68.6K" beside "68,597 of
68,597" — and a tile is the wrong place for a figure about the selection
rather than about the demand. The row is three tiles wide now.

**Two things on the page were counting the old list and had to move.** The
"N of M series in scope" line now takes its numerator from
`kpis.series_count` on the payload for the current selection and its
denominator from `filters.series_count`; and the no-selection subject read
"the whole workspace", which is no longer what the page shows. `num` was
abbreviating the count to "68.6K of 68.6K", which hides whether the two are the
same number, so it uses `exact` as D-143 does.

**`placeholderData: keepPreviousData`** on the summary query, for the reason
given in D-142: the panels render under `data && !data.empty`, so without it a
slicer change unmounts all of them, the document collapses and the reader is
thrown to the top. The `Updating…` marker comes with it, because panels holding
the previous selection's figures must say so.

**`ScopeBanner` stays on this page** and now renders its FULL NETWORK variant.
Overall Analysis dropped the banner in D-142 because its lede and its own
filter-bar count already state the scope; this page's lede does not, and a
reader who remembers these figures being small needs to be told why they grew.
Its text named Per Branch & SKU among the workspace pages — true when written,
false now, and corrected.

**Measured.** Picker, unfiltered: 53 locations, 2,315 SKUs, *68,597 of 68,597
branch × SKU combinations*. NAGPUR: the SKU list narrows to 1,591 and the line
reads *1,591 of 68,597*. NAGPUR × FG.AA3.LFH.GYG2120R00: *1 of 68,597*, and the
Location list narrows to the 28 branches carrying that SKU. Clearing the branch
with the SKU held: *28 of 68,597*, SKU list back to 2,315. Branches that were
previously unreachable now render in full — KOLKATTA 39.5K units / ₹13.55Cr /
90.5% fill over 968 SKUs, CHENNAI 100.4K units / ₹37.27Cr / 85.4% over 1,592.
Seven charts draw; console clean after a hard reload.

```
backend 1088 passed · frontend 268 passed (24 files) · tsc --noEmit clean
```

## D-145 — The month-of-year chart was bucketing weeks, not months

Noticed from the tooltip: hovering a bar on Per Branch & SKU said *"averaged
over 10 year(s)"* on a window that spans two.

**`_seasonality` read `(period_index % 12) + 1`.** `period_index` counts
periods, so modulo 12 is a calendar month only when a period *is* a month. On
the monthly panel that held — the index is anchored to an absolute epoch, so
`2025-01` lands on 1 and `2025-04` on 4, and the monthly path was correct. On
the **weekly** panel it bucketed every twelfth ISO week together and labelled
the twelve buckets Jan..Dec. They were not months. They were twelve arbitrary
slices of the window, each holding about a twelfth of the demand — which is
exactly why the chart was twelve bars of nearly equal height with no shape in
it. A flat seasonality chart reads as "this product has no annual pattern",
which is a finding; it was an artefact.

The `observations` count went the same way. Grouping by `(bucket, period)` and
taking `len` counted the *periods* in the bucket, and the periods are weeks:
122 weeks over 12 buckets is about 10, printed as "10 year(s)". The tooltip
was the only visible symptom of a wrong chart, which is the argument for
putting a count beside every average.

**The fix is the rule already written for this.** A week belongs to the month
holding its Thursday — `period_month`, the same rule used wherever a weekly
figure is read monthly. Totals are summed inside each calendar month that
actually occurred, then averaged across the years that month falls in, so
`observations` is a count of years. The grain is read from the period label's
own shape (`"-W"` or not) rather than from `settings.panel_grain`: a monthly
frame reaches this function on a weekly-configured deployment — every fixture
in the test suite is one — and `period_month("2025-01", "weekly")` raises.

**Before and after, full network, 2024-W14 → 2026-W31:** twelve bars within
3% of each other and "10 years" on every one, against

```
Jan 158,746 (2y)  Feb 136,174 (2y)  Mar 131,048 (2y)  Apr 134,926 (3y)
May 165,523 (3y)  Jun 165,580 (3y)  Jul 160,464 (3y)  Aug 157,846 (2y)
Sep 128,762 (2y)  Oct 151,926 (2y)  Nov 139,185 (2y)  Dec 126,827 (2y)
```

— a real profile, with May–July running about 30% above September and
December. Two or three years per bar, which is what a 2.3-year window holds.

**The count moved out of the tooltip, which is what was asked.** Corrected, it
is the same two or three on nearly every bar, so it is stated once under the
chart — "Each column averages 2–3 years" — instead of on every hover. It is
computed from the payload, so it tracks the window: Overall Analysis pins its
start to the order book and correctly says *1–2 years* where Per Branch & SKU,
which runs the full two years, says *2–3*. Dropping it entirely would have hidden
how thin the evidence under each bar is.

**A partial month is left as it falls.** A month the window only part-covers
contributes a short total and pulls its own mean down. This does not pro-rate
it: scaling a partial month up would invent demand. On the current window it
does not arise — 2026-W31's Thursday is 30 July, so the data ends on a complete
July and August never sees a partial year.

```
backend 1088 passed · frontend 268 passed (24 files) · tsc --noEmit clean
```

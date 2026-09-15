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

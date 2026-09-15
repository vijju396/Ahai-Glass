# MODEL_INVENTORY.md

**Status: locked in Phase 1. Verified by direct source-code inspection of both
reference projects, not from their documentation.**

Reference roots (read-only — never edited, formatted, moved, or installed into):

- Oxea: `D:\OXEA`
- Meriton: `D:\Meriton forecast`
- Sodexo: `D:\Labour_AI forecast`

Oxea's own `docs/MODEL_INVENTORY.md` is the authoritative description of the
shared 13-model system and was read in full. Every claim it makes about the
model layer was then re-verified against the live Meriton/Sodexo source before
being carried into this document. Where this file cites a file and line, that
line was opened and read.

---

## 0. The official 13

Both reference projects implement the same 13 models with identical display
names. Verified:

| Source | Location | Finding |
|---|---|---|
| Meriton | `services/training_service.py:27-40` `MODEL_SPECS` | 13 entries; IDs suffixed `_Predictions` |
| Sodexo | `backend_sodexo/app/services/forecasting/contract.py:96-110` `MODEL_SPECS` | 13 entries; clean snake_case IDs |
| Sodexo | `backend_sodexo/app/services/forecasting/models.py:333-347` `FITTERS` | 13 fitter bindings, same IDs |
| Oxea | `backend/app/ml/registry/model_registry.py` | 13 adapters + import-time assertions |

AIS adopts **Sodexo's snake_case IDs** (as Oxea did) and preserves both
projects' **display names verbatim**.

| # | `model_id` | Display name | Meriton ID | Sodexo ID |
|---|---|---|---|---|
| 1 | `sarimax` | SARIMAX | `sarimax_Predictions` | `sarimax` |
| 2 | `sarimax_exog` | SARIMAX with exogenous variables | `sarimax_exog_Predictions` | `sarimax_exog` |
| 3 | `auto_arima` | Auto ARIMA | `autoArima_Predictions` | `auto_arima` |
| 4 | `auto_arima_exog` | Auto ARIMA with exogenous variables | `autoArima_exog_Predictions` | `auto_arima_exog` |
| 5 | `xgboost` | XGBoost | `xgboost_Predictions` | `xgboost` |
| 6 | `xgboost_exog` | XGBoost with exogenous variables | `xgboost_exog_Predictions` | `xgboost_exog` |
| 7 | `exp_additive` | Exponential Smoothing Additive | `exp_additive_Predictions` | `exp_additive` |
| 8 | `exp_additive_damped` | Exponential Smoothing Additive Damped | `exp_additive_damped_Predictions` | `exp_additive_damped` |
| 9 | `exp_multiplicative` | Exponential Smoothing Multiplicative | `exp_multiplicative_Predictions` | `exp_multiplicative` |
| 10 | `exp_multiplicative_damped` | Exponential Smoothing Multiplicative Damped | `exp_multiplicative_damped_Predictions` | `exp_multiplicative_damped` |
| 11 | `var` | VAR | `var_Predictions` | `var` |
| 12 | `var_exog` | VAR with exogenous variables | `var_exog_Predictions` | `var_exog` |
| 13 | `lstm` | LSTM | `lstm_Predictions` | `lstm` |

The single source of truth in this codebase is
`backend/app/ml/registry/canonical_models.py`. It asserts the count, order,
uniqueness, display-name coverage and dependency coverage **at import time**,
and `backend/app/ml/registry/model_registry.py` re-asserts that the bound
adapter classes agree with it. `backend/tests/test_model_registry.py` asserts
the same independently. The frontend never carries a second model list; it
reads `GET /api/models`.

### Explicitly not part of the 13

- **Baselines** — `naive`, `seasonal_naive`, `ma3`, `ma6`. Reported alongside
  the leaderboard and used as the MASE denominator. Never counted among the 13,
  never eligible to be champion. Held in `BASELINE_METHOD_IDS`, a separate
  tuple, and `assert_canonical_registry()` fails if the two sets ever overlap.
- **Prophet, Random Forest, LightGBM, Croston, SBA, TSB** — not substituted for
  anything. The HTML analysis document proposes Croston/SBA/TSB; that proposal
  is *not* implemented, because it is not part of the verified 13.
- Sodexo `scripts/train_sodexo_forecast.py` — orphaned RandomForest prototype,
  not wired into the live app. Confirmed still dead.
- Sodexo `services/predictions/employee_risk.py` — GradientBoostingClassifier,
  classification not forecasting.
- Meriton `services/advisor_service.py` — an OpenAI-backed chat feature.

---

## 1. The common adapter contract

Every model is wrapped by one `ForecastModelAdapter`
(`backend/app/ml/adapters/base.py`, Phase 5) exposing:

| Member | Purpose |
|---|---|
| `model_id` | Registry key, matches `CANONICAL_MODEL_IDS` |
| `display_name` | Verbatim reference-project label |
| `min_required_history` | Minimum training rows (per-model, table below) |
| `requires_exogenous` | Whether an exog design matrix is mandatory |
| `validate_eligibility(...)` | Returns `(eligible, reason, remediation)` — never raises |
| `fit(train_df, context)` | Fit from scratch |
| `predict(horizon_df, context)` | Length-checked point forecast |
| `predict_quantiles(...)` | Residual-calibrated q80/q90/q95 |
| `save(path)` / `load(path)` | Real persistence (new work — see §4) |
| `parameter_metadata()` | Resolved hyperparameters actually used |
| `feature_metadata()` | Feature names actually fed to the model |
| `failure_reason` | Populated on failure, distinct from ineligibility |
| `training_duration_ms` / `inference_duration_ms` | Measured, persisted |

Shared behaviour, from both references:

- Output length is enforced to equal `len(horizon_df)` exactly (Sodexo's
  `_clean_predictions`, `models.py:80-84`), with `±inf` mapped to `NaN`.
- **Failure isolation** — one model's exception never stops the others
  (Meriton `training_service.py:441-451`; Sodexo `engine.py:106-123`).
- **Ineligible ≠ Failed.** A model that fails a data gate is reported
  `Ineligible` with a reason and remediation, and stays on the leaderboard.
- Prediction intervals are **never model-native** in either reference. Both
  compute empirical percentiles of backtest residuals with a 5-residual
  minimum. AIS keeps that approach and extends it to q80/q90/q95 (see §3).

---

## 2. Per-model implementation decisions

Each row records which reference project AIS ports from and why. Verified
against source at the cited lines.

### `sarimax`, `sarimax_exog` — from **Sodexo** (`models.py:89-110`)

| Field | Meriton | Sodexo | AIS |
|---|---|---|---|
| Order | fixed `(2,1,1)` | `(ar_order,1,1)`, `ar_order=1` if `use_seasonal and period<=2` else `2` | **Sodexo** |
| Seasonal order | `(0,0,0,p)` if `len>=p*2` | `(1,0,1,p)` if `len>=p*3` | **Sodexo** |
| `enforce_stationarity` / `enforce_invertibility` | `False` / `False` | `False` / `False` | `False` / `False` |
| Min rows | 12 | 12 | 12 |

Sodexo's dynamic `ar_order` is a genuine safety fix Meriton lacks: statsmodels
rejects a model whose non-seasonal AR lag coincides with a seasonal one, which
happens at `period == 2`. AIS adopts the guard. Sodexo's fuller `(1,0,1,p)`
seasonal order is adopted too, but both are configurable rather than
hardcoded.

### Exogenous handling — from **Sodexo** + **Meriton**, additively

Sodexo `_exog_pair` (`models.py:65-77`) and `_independent_exog_columns`
(`models.py:34-62`); Meriton `_exog_pair` (`training_service.py:1875-1904`) and
`_fit_source_exog_schema` (`:1915-1937`).

- **Train-only standardization.** Mean and `std(ddof=0)` computed on the
  training fold only, zero-std replaced by `1.0`, applied to both train and
  output. Non-finite result raises.
- **Collinearity and rank guard (Sodexo).** A column is kept only if it varies,
  is not `>0.95` correlated with a column already kept, and genuinely raises the
  rank of `[intercept | kept…]`. The intercept is inside the rank test
  specifically to catch the dummy-variable trap, which the dummies alone would
  pass.
- **Categorical encoding (Meriton).** One-hot with a cardinality cap
  (`FORECAST_MAX_EXOG_CATEGORIES`, default 50); exceeding it raises rather than
  silently truncating.
- **XGBoost exog stays raw/unstandardized** in both references — a deliberate
  asymmetry, preserved rather than "fixed".
- **Future-known only.** For AIS the exogenous set is calendar features,
  forecast horizon, and static branch/product attributes. `mrp` is *not*
  future-known and is used as a historical driver only. A `future_known_driver`
  with a missing future value is a validation error, mirroring Meriton's
  `FutureExogenousUnavailable`.

### `auto_arima`, `auto_arima_exog` — from **Sodexo** (`models.py:115-131`)

| Field | Meriton | Sodexo | AIS |
|---|---|---|---|
| Information criterion | default (AIC) | `"aicc"` | **`aicc`** |
| Seasonal search | `max_P/D/Q = 1/1/1` | `max_P=2, max_D=1, max_Q=2` | **Sodexo** |
| Shared | `start_p/q=1, max_p/q=3, max_d=2, max_order=8, stepwise=True, error_action="ignore", suppress_warnings=True` | same | same |
| Min rows | 24 | 24 | 24 |
| Evaluation | 3-fold CV | forced single holdout | **forced holdout** |

AICc is bias-corrected for small samples, which matters at 22–28 monthly
observations. An explicit runtime limit is applied on top (Oxea's soft
per-model timeout pattern). **See §5 — at AIS's monthly grain this model's
24-row minimum is frequently unmet, and it is then `Ineligible`, not failed.**

### `xgboost`, `xgboost_exog` — from **Meriton** (`training_service.py:1099-1131`)

| Field | Meriton | Sodexo | AIS |
|---|---|---|---|
| Hyperparameters | `GridSearchCV`, `cv=2` over `learning_rate[0.05,0.1] × max_depth[3,5] × n_estimators[100,200]`, `min_child_weight=1, subsample=0.8, colsample_bytree=0.8` | fixed `lr=0.1, depth=4, n=100, subsample=0.8, colsample=0.8` | **both**, as a training profile |
| `random_state` | 42 | 42 | **42** |
| Forecast mode | recursive | recursive | recursive |
| Min lagged rows | 5 | 5 | 5 |

AIS exposes both as an explicit `training_profile`:

- `thorough` — Meriton's grid search. Default for the aggregate tier and the
  high-value local tier.
- `fast` — Sodexo's fixed parameters. Default for pooled full-network runs,
  where 63,210 series make a grid search indefensible.

Two AIS-specific requirements on top:

- **Dtype stability.** Feature frames are built once and reindexed to a stored
  column order with `fill_value=0.0`, then cast to a single fixed dtype. Mixed
  or shifting dtypes change XGBoost's `hist` binning and silently move
  predictions; a test asserts the training and inference matrices share an
  identical dtype signature.
- **Pooled global mode.** For full-network scoring, `xgboost`/`xgboost_exog`
  train once over the whole branch × SKU panel with branch, region, zone, hub,
  tier, product-hierarchy, glass-type, vehicle-age, OEM-status and
  **forecast-horizon** features added. Horizon is a feature, so one fit answers
  all six horizons (direct multi-horizon). Local per-series mode is retained
  unchanged for the aggregate and high-value tiers.

### `exp_additive`, `exp_additive_damped`, `exp_multiplicative`, `exp_multiplicative_damped` — from **Sodexo** (`models.py:217-233`)

The model code is functionally identical in both references. Verified
identical: `trend="add"` always, `initialization_method="estimated"`,
`optimized=True`, and a `TypeError` fallback from `damped_trend=` to the legacy
`damped=` kwarg.

Eligibility, all four:

- Minimum **24** training rows.
- Seasonal period resolved and `len >= period * 2` — checked against the
  **smallest rolling-origin fold's** training size, not the full window
  (Sodexo `validation_plan.smallest_fold_train_size`). A period that only fits
  the full series makes every fold's fit fail at runtime.
- Multiplicative variants are **ineligible if any target value is `<= 0`**.
  With 62% of AIS series intermittent, this legitimately disqualifies most of
  them. No positive floor, epsilon, or shifted target is ever introduced to
  manufacture eligibility.

**See §5 — these four are frequently `Ineligible` at AIS's monthly grain.**

### `var`, `var_exog` — from **Meriton** (`training_service.py:1181-1204`, `_prepare_var_endog` `:1964-1977`)

Meriton's design is genuinely multivariate across series dimensions; Sodexo's
is a narrower bivariate `target + var_pair`. AIS takes **Meriton's generalized
multi-endogenous design**, verified behaviour:

- Constant columns are dropped and their last value carried as an additive
  `constant_total` offset.
- Requires `>= 2` non-constant aligned endogenous columns, else **ineligible
  with a reason** — not a failure.
- Non-finite endogenous values raise.
- Lag order `min(7, len // 10)`, bounded by
  `(len - exog_count - 2) // (k + 1)`; `ic=None`, `trend="c"`.
- `var_exog` drops non-varying exogenous columns and requires at least one
  survivor, else ineligible.

**AIS decision (docs/DECISIONS.md-004):** the second endogenous series at
branch × SKU grain is `despatched_qty`, which genuinely co-evolves with
ordered quantity. It is supply-censored, and that is recorded in
`parameter_metadata()` and shown in the UI — it is a co-movement signal, not a
second demand truth. At aggregate levels additional endogenous candidates
(`mrp_value`, `shortfall_qty`) are available. Most sparse series will have a
constant pair and VAR will be ineligible there, with the reason stated.

### `lstm` — from **Meriton** (64 units) + **Sodexo** (EarlyStopping)

| Field | Meriton `:1206-1260` | Sodexo `:277-330` | AIS |
|---|---|---|---|
| Architecture | `LSTM(64) → Dense(1)` | `LSTM(32) → Dense(1)` | **`LSTM(64) → Dense(1)`**, units configurable |
| Early stopping | none | `EarlyStopping(monitor="loss", patience=8, restore_best_weights=True)` | **Sodexo's** |
| Epochs / batch | 25 / 32 | 80 / 16 | 80 / 16 |
| `shuffle` | `False` | `False` | **`False`** |
| Scaling | `MinMaxScaler` on target, train-fit only | same | same |
| Window | `min(30, max(3, len//4))` | `min(42, max(3, len//4))` | `min(12, max(3, len//4))` — monthly grain |
| Determinism | `set_random_seed(42)` + `enable_op_determinism()` | identical | identical |
| Evaluation | 3-fold CV | forced holdout | **forced holdout** |
| Exog sibling | none | none | **none** — the only model of the 13 without one |

64 units is safe precisely because EarlyStopping bounds the overfitting risk.
Strict wall-clock and memory limits are applied, and the measured 5.75 s per
fit at AIS's series length is what forces the tiered training budget in
`docs/ARCHITECTURE.md`.

---

## 3. Quantiles are outputs, not models

The 13 are point-forecast algorithms. **q80/q90/q95 are never additional
models and never appear on the leaderboard as models.**

Both references compute a single empirical interval from backtest residuals
(Meriton 2.5/97.5, Sodexo 10/90, both with a 5-residual minimum). AIS extends
the same idea:

- Residuals are collected **out-of-sample only**, from validation folds.
- Calibrated per **model × forecast horizon × demand segment**. Per-series
  calibration is not attempted: one origin × six validation months yields six
  residuals per series, below any honest threshold. The pooling level is
  reported alongside the coverage figure.
- Conformal calibration where enough residuals exist; empirical percentiles
  otherwise. Which one was used is recorded per row.
- **`point <= q80 <= q90 <= q95` is enforced.** Crossings are corrected by
  monotone sorting and **logged with a count**, never silently.
- Achieved coverage and pinball loss are measured and reported against target.

---

## 4. Gaps against the references (new work, not ports)

| Concern | Meriton | Sodexo | AIS |
|---|---|---|---|
| Trained-model persistence | **none** — refits every run | **none** | Real `save`/`load` per adapter + MLflow tracking. New work. |
| sMAPE, MASE | absent | absent | Implemented. New work. |
| Pinball loss, quantile coverage | absent | absent | Implemented. New work. |
| Hierarchical reconciliation | absent | absent | MinT variants + fallbacks. New work. |
| Output persistence | flat JSON/CSV under session UUIDs | SQLite via SQLAlchemy | **Sodexo's relational pattern**, extended |
| Orchestration | Flask + daemon thread + global lock | FastAPI + daemon thread + global lock | Thread-pool job runner with a jobs table, cancellation tokens, SSE progress |
| Champion scope | global/aggregate only | per-series only | **both**, plus branch / ABC / behaviour segment |

---

## 5. AIS-specific eligibility reality, measured

Measured on the real 24-month AIS national series with `train=18, period=12`,
using each reference's own fitter configuration:

| Model | Single-fit time | Outcome at the mandated origin |
|---|---|---|
| `sarimax`, `sarimax_exog` | 0.06 s | eligible |
| `auto_arima`, `auto_arima_exog` | 0.47 s | **ineligible** — needs 24 rows, has 18 |
| `xgboost` (grid) | 0.32 s | eligible |
| `xgboost` (fast) | 0.014 s | eligible |
| `exp_*` (all four) | — | **ineligible** — `Cannot compute initial seasonals … with less than two full seasonal cycles` |
| `var`, `var_exog` | 0.01 s | eligible where the pair varies |
| `lstm` | 5.75 s | eligible |

This is arithmetic, not a defect. At monthly grain the union panel spans 28
periods (Apr 2024 – Jul 2026); a 6-month holdout leaves at most 22 training
rows, and `auto_arima` and `exp_*` need 24. **There is no origin in this
dataset where those six models are eligible with a 6-month validation
window.**

Resolution (`docs/DECISIONS.md-001`), both paths shipped:

- **`min_history_profile: reference` (default).** Reference thresholds are
  honoured exactly. Six models report `Ineligible` with the precise unmet
  requirement and its remediation. Nothing is hidden, nothing is faked.
- **`min_history_profile: monthly_relaxed` (opt-in).** Documented, clearly
  labelled deviation lowering the ES/Auto-ARIMA minimum to 18 rows and allowing
  a shorter seasonal period, so all 13 can be compared. The leaderboard states
  which profile produced each row, and metrics from different profiles are never
  blended.

Neither path reduces the model count, substitutes an algorithm, or reports an
ineligible model as failed.


---

## 6. Phase 5 implementation status

Every model is implemented as a `ForecastModelAdapter` subclass under
`backend/app/ml/adapters/`, registered in
`backend/app/ml/registry/model_registry.py` in the exact order of the SS0
table, and covered by `backend/tests/test_ml_adapters.py` (91 tests).

`assert_registry_bound()` runs at **import time** and again at application
startup. It checks the id list, the order, the count, and per adapter its
`model_id`, `display_name`, `dependency_module`, `requires_exogenous`,
`supports_pooled_training` and `uses_fast_holdout` - so a renamed display name
or a capability flag disagreeing with the registry stops the process.

| # | `model_id` | Adapter class | Ported from | Min rows | Save format |
|---|---|---|---|---|---|
| 1 | `sarimax` | `SarimaxAdapter` | Sodexo (AR-collision guard, (1,0,1,p) seasonal) | 12 | pickle |
| 2 | `sarimax_exog` | `SarimaxExogAdapter` | Sodexo + Meriton categorical encoding | 12 | pickle |
| 3 | `auto_arima` | `AutoArimaAdapter` | Sodexo (`aicc`, wider seasonal search) | 24 | pickle |
| 4 | `auto_arima_exog` | `AutoArimaExogAdapter` | Sodexo | 24 | pickle |
| 5 | `xgboost` | `XGBoostAdapter` | Meriton (`GridSearchCV`) + Sodexo fast profile | 6 | XGBoost JSON |
| 6 | `xgboost_exog` | `XGBoostExogAdapter` | as above, exogenous raw/unstandardised | 6 | XGBoost JSON |
| 7 | `exp_additive` | `ExpAdditiveAdapter` | Sodexo (identical to Meriton) | 24 + 2 cycles | pickle |
| 8 | `exp_additive_damped` | `ExpAdditiveDampedAdapter` | Sodexo | 24 + 2 cycles | pickle |
| 9 | `exp_multiplicative` | `ExpMultiplicativeAdapter` | Sodexo | 24 + 2 cycles, target > 0 | pickle |
| 10 | `exp_multiplicative_damped` | `ExpMultiplicativeDampedAdapter` | Sodexo | 24 + 2 cycles, target > 0 | pickle |
| 11 | `var` | `VarAdapter` | Meriton (generalized multi-endogenous) | 10 + 2 endogenous | pickle |
| 12 | `var_exog` | `VarExogAdapter` | Meriton, generalized | 10 + 2 endogenous | pickle |
| 13 | `lstm` | `LstmAdapter` | Meriton 64 units + Sodexo EarlyStopping | 14 | Keras `.keras` |

### Measured on real AIS data

A real 28-month series (`DELHI-2|FG.M1C.LFH.GCG2120000`) on a trailing
six-month holdout — 22 training months, i.e. train through Jan 2026. That is
the *second* mandated origin, not the primary Sep 2025 cut, which leaves 18:

| Profile | Completed | Ineligible | Resolved period |
|---|---|---|---|
| `reference` | **7** | **6** | None (12 needs 24 obs) |
| `monthly_relaxed` | **13** | 0 | 6 (autocorrelation 0.242) |

The six ineligible under the default are exactly `auto_arima`,
`auto_arima_exog` and the four `exp_*` variants, all `insufficient_history` -
which is what SS5 predicted before any adapter existed.

Fit times on that series: `sarimax` 2.0 s, `sarimax_exog` 0.13 s, `xgboost`
1.4 s, `var` 0.37 s, `var_exog` 0.03 s, `lstm` 10.9 s.

**Save/load round-trips exactly** for all 9 models eligible on that series -
LSTM included - which neither reference project can do at all.

### Deviations from the references, each recorded

| Deviation | Reason |
|---|---|
| XGBoost defaults to direct multi-horizon, not recursion | Both references' recursive loops consume actuals from the validation window, making a fold one-step-ahead (D-031) |
| LSTM recursion feeds its own predictions | Same reason; LSTM has no direct-multi-horizon form |
| VAR reads the target from column 0 rather than summing | AIS's endogenous columns are different quantities, not slices of one target (D-034) |
| LSTM window ceiling 12, not 30/42 | Both reference values are sized for daily/half-day grain (D-033) |
| Relaxed profile resolves a shorter seasonal period | Otherwise the profile could not deliver what D-001 promised (D-033) |

No model was added, removed, renamed, reordered or substituted to accommodate
any of this.


---

## 7. Phase 6 measured evaluation

### Metric provenance

| Metric | Meriton | Sodexo | AIS |
|---|---|---|---|
| MAPE, accuracy, MAE, RMSE, WAPE, bias | `metrics_service.py:7-41` | `metrics.py:9-43` (identical) | **Parity port** in `reference_metrics`, quirks included |
| sMAPE, MASE | absent | absent | New work in `evaluate` |
| Pinball loss, quantile coverage | absent | absent | New work in `evaluate` |

`reference_metrics` reproduces the references exactly - including that MAPE
drops zero actuals, that `accuracy` is `max(100 - mape, 0)`, that WAPE and bias
divide by the **signed** sum of actuals, that every value is rounded to two
decimals, and that `±inf` passes their coercion where NaN does not.
`tests/test_metrics.py` re-implements the reference algorithm inside the test
and compares, so parity is checked against Meriton/Sodexo rather than against
our own port.

`evaluate` is the AIS set and deviates in one deliberate place: WAPE and bias
divide by the sum of **absolute** actuals. With non-negative actuals - which
ordered quantity is - the two agree exactly; a signed denominator can be driven
toward zero by cancellation and produce an absurd percentage. Both forms are
available, and the legacy ranking uses the legacy form.

### Undefined is a value

A metric with no defined value returns `None` with a stated reason, never 0,
never 100, never a sentinel. On this dataset that is the common case, not an
edge case: 61.96% of series are intermittent (measured), so a validation window
of all zeros - which has no WAPE and no MAPE - is routine.

### Measured accuracy

**First measured figures in this project.** 60-series stratified sample, two
mandated origins, `monthly_relaxed`, median pooled WAPE:

| | Median WAPE | n of 60 |
|---|---|---|
| `var` | 64.55 | 6 |
| **`ma6` (non-registry baseline)** | **90.69** | 46 |
| `ma3` (baseline) | 91.93 | 46 |
| `exp_additive_damped` | 93.22 | 42 |
| `naive` (baseline) | 100.00 | 46 |
| `xgboost` | 102.76 | 46 |
| `seasonal_naive` (baseline) | 108.47 | 46 |
| `sarimax` | 116.35 | 46 |

The registered models do not beat a six-month moving average on the median
sampled series. `var` is ahead of `ma6` but completed on 6 of 60 series, so its
figure describes an easier subpopulation. The sample is stratified by segment
rather than drawn in population proportion, and no figure here is an aggregate
over the full panel.

### Quantile calibration, measured out of sample

Residuals from the `primary` origin only, applied to the `second` origin's
forecasts, which the calibration never saw:

| Level | Target | Achieved | Mean pinball | Cells past the finest pool |
|---|---|---|---|---|
| q80 | 80% | **79.72%** | 1.622 | 24 of 96 |
| q90 | 90% | **89.06%** | 1.368 | 24 of 96 |
| q95 | 95% | **93.07%** | 1.125 | 84 of 96 |

Every offset was `conformal` rather than interpolated. q95 under-covers by 1.9
points, consistent with 84 of its 96 cells falling back from
`model_horizon_segment` to `model_horizon` - it needs 19 residuals for a
genuine order statistic and the sample rarely provided them per segment.

196 of 996 rows (19.7%) required a monotonicity correction, counted and
reported rather than silently sorted.

### Inherited divergence risk

Both references fit SARIMAX with `enforce_stationarity=False`. On AIS's short
intermittent series that occasionally yields an explosive forecast: measured
3.67e11 units against actuals of 0-10, on a panel whose largest observed value
anywhere is 745. The fitter is unchanged - parity is preserved - and a guard at
the evaluation boundary reports such a forecast `FAILED` with its magnitude
rather than scoring it (D-041).

---

## 8. Phases 7–12: what the models actually did at scale

Three training runs over the real panel. Everything below is measured.

### Registry integrity, across 5,219 evaluations

| | |
|---|---|
| `model_run` rows | 5,219 |
| Distinct models seen | 17 — the 13 registered plus 4 non-registry baselines |
| Completed | 3,308 |
| **Ineligible** | **1,911** |
| **Failed** | **0** |
| Timed out | 0 |
| Not evaluated (budget) | 0 |
| Registry models missing from any scope | **0** |

Every scope's leaderboard carries all thirteen. `models_missing` has been empty
on every run, and it is returned rather than assumed so an omission could not
be silent.

### Which models win, and where

Champion across 166 real scopes:

| Model | Scopes won |
|---|---|
| `lstm` | 42 |
| `sarimax_exog` | 33 |
| `var_exog` | 27 |
| `var` | 20 |
| `sarimax` | 19 |
| `xgboost` | 16 |
| `xgboost_exog` | 9 |

No model dominates. That is the case for segment-level champions rather than a
single global winner, and it is why the champion table is keyed by scope.

The six ineligible models won nothing, because they ran nowhere: 24 training
observations against 22 available, at every origin.

### National aggregate, the one scope with a clean comparison

```
var_exog       4.578%   <- champion
sarimax_exog   6.192%
var            9.603%
ma6            9.939%   <- best baseline
ma3           10.314%
xgboost_exog  10.603%
xgboost       11.156%
naive         11.835%
seasonal_naive 11.835%
sarimax       13.157%
lstm          14.661%   (holdout_fast, 6 points vs 10)
```

At national level the registered models beat the baselines: a **53.9%**
improvement over `ma6`. Phase 6 found the opposite on the median *individual
series*, and both are true — an aggregate is far less intermittent than the
cells beneath it, so neither result transfers to the other level. The
application never presents one as evidence for the other.

**Across all 166 scopes a baseline beats the champion in 47.** Recorded on the
selection row, surfaced on the leaderboard in words, and counted on the
monitoring page.

### VAR, which the reference design nearly made unusable

`var` and `var_exog` together win 47 of 166 scopes and `var_exog` is the
national champion. That only happened because the aggregate tier pairs the
target with `active_cells` rather than `despatched_qty` (D-042): the latter is
null on every sales-proxy row, so strict aggregation makes it null for half the
panel's months and VAR would have been `ineligible` almost everywhere.

On individual series the original problem stands — `var` is ineligible on 54 of
60 sampled series for exactly that reason. That is a property of the data, and
VAR's series-level metrics are drawn from an easier subpopulation. The
leaderboard's `validation_points` column is what makes that visible.

### LSTM at scale

42 scope wins, evaluated on a single chronological holdout (D-037) so it
reports 6 validation points where rolling-origin models report 10. Phase 8 had
to decide whether that disqualifies it; D-044 records the answer — comparability
is assessed within an evaluation mode, both counts travel on the row, and the
response carries a mixed-mode note.

Measured fit cost: 10.9 s per series. At 68,675 series that is 208 hours, which
is why the tiering in `docs/ARCHITECTURE.md` §6 is load-bearing rather than an
optimisation.

### Persistence, verified

Per-origin **actuals and predictions** are now stored on every `model_run`
(added in Phase 7 — `as_dict()` had been dropping them, so no
actual-versus-predicted chart could be drawn from a stored run). That is what
makes `GET /api/models/{model_id}/diagnostics` serve a real residual chart and
horizon-level performance rather than a recomputation.

The endpoint distinguishes two empty cases, because they are not the same
statement: a model that never produced predictions, and a model that completed
under a run predating this persistence. The second must not read as the model's
fault.

### Interval calibration, corrected

Phase 6 pooled residuals by model × horizon × segment across all scopes, as
absolute offsets. Phase 9 measured what that does across an aggregate tier
spanning a fifty-fold magnitude range: the national q95 landed **3.2%** above
the point forecast while that model's national WAPE was **4.58%**.

An interval narrower than the model's own average error is broken, and it would
have driven every order-up-to level in Phase 10. Calibration now uses each
scope's **own** residuals (D-045), which puts the national q95 at **7.7%** —
consistent with the measured error. The honesty cost is on every row: 12
residuals is below the 19 a conformal q95 needs, so the method reads
`empirical / scope_all_horizons` rather than `conformal`.

# CLAUDE.md

Operating contract for this repository. Read `docs/STATUS.md` before starting
any work.

**All twelve phases are complete**, plus a reference-led UI parity pass
(`docs/UI_VISUAL_PARITY.md`). 1,345 tests pass (1,077 backend, 268 frontend);
65 API endpoints are documented and cross-checked against the running app. The
work from here is maintenance and extension, not phase delivery — so the
discipline below applies to any change, not just to a phase boundary.

## Project

AIS Glass Forecast & Inventory Intelligence. Demand forecasting and inventory
recommendation at branch × SKU × month, 63,210 series, 13 registered models.

## Read-only reference projects

`D:\OXEA`, `D:\Meriton forecast`, `D:\Labour_AI forecast`.

**Never** edit, format, move, delete, rename, commit to, install packages into,
or create files inside them. Read them freely; write nothing.

Oxea's `docs/MODEL_INVENTORY.md` is the authoritative description of the shared
13-model system. Verify every claim against the actual Meriton and Sodexo
source before relying on it — this repo's `docs/MODEL_INVENTORY.md` cites file
and line for each decision, and those citations were opened and read.

## Never modify the AIS source files

`data/source/` holds the five client files. Read-only, always. The same applies
to `AIS-forecasting-analysis.html` and `OneDrive_1_08-09-2026.zip` at the root.

## The 13 models

Exactly thirteen, registered once, in the order defined by
`backend/app/ml/registry/canonical_models.py`. That module asserts count,
order, uniqueness and display-name coverage at import time; `app.main` calls
`assert_canonical_registry()` at startup; `tests/test_model_registry.py`
asserts it independently with a literal transcription rather than an import.

Rules:

- Do not add a 14th model, remove one, rename one, or reorder them.
- Do not substitute Prophet, Random Forest, LightGBM, Croston, SBA, TSB,
  moving averages, or anything else for one of the 13. The HTML analysis
  document proposes Croston/SBA/TSB; that proposal is not implemented.
- `naive`, `seasonal_naive`, `ma3`, `ma6` are **non-registry baselines**. Never
  count them among the 13; never let one be champion.
- **MAPE is the primary ranking metric** (D-043), so the leaderboard order
  agrees with the reported accuracy of `100 - MAPE`. WAPE is still computed
  and shown on every row. Switch with `AIS_CHAMPION_PRIMARY_METRIC=wape`.
- q80/q90/q95 are **forecast outputs**, not models. They never appear on the
  leaderboard as models.
- Reuse the reference algorithms through adapters. Do not reinvent a fitter.
- Preserve user-visible display names verbatim.

## Status vocabulary is load-bearing

`Ineligible`, `Failed`, `Timed out` and `Not evaluated (budget)` mean different
things and must render differently:

- **Ineligible** — a *validated* data requirement is unmet. Show the exact
  requirement and its remediation.
- **Failed** — the fit raised. Show the reason.
- **Timed out** — exceeded its per-model budget. The run continues.
- **Not evaluated (budget)** — a tier did not reach this series.

A model that did not run **never disappears from the leaderboard** and is
**never replaced by a zero forecast**. One model's failure never stops the
others.

## Data honesty

Distinguish these seven states; never collapse them: `true_zero`,
`missing_data`, `zero_stock`, `not_applicable`, `model_ineligible`,
`model_failed`, `out_of_budget`.

- Ordered quantity is the target. `sales_proxy` is a labelled substitute; never
  call the two equivalent.
- Report net shortfall and gross positive shortfall separately. They differ by
  7.6% because 9,498 lines were over-despatched.
- Never continue silently past a failed structural control. Raise, surface it
  in Data Studio, and record it in `docs/VALIDATION_REPORT.md`.
- No GSTIN, PAN, customer name, email, mobile or address in the modelling panel
  or any API payload.
- Inventory recommendations are current-snapshot estimates. Do not claim a
  historical inventory-policy backtest — there is no stock history to run one
  against.

## Architectural boundaries

- `app/ml/` and generic `app/services/` must not contain a single AIS column
  name. They operate on the canonical schema in `docs/DATA_CONTRACT.md` §3.
- AIS business rules live only in `app/domain/ais/`.
- The frontend performs no forecasting arithmetic and carries no second model
  registry. It reads model identity from `GET /api/models`.
  `src/test/no-duplicate-registry.test.ts` enforces both by scanning source.
- No long-running work in a request handler. Training returns a job ID.

## Validation must be leakage-safe

- Chronological rolling-origin or expanding-window only. **Never** a random
  split.
- Fit imputation, scaling, encoding, feature selection and hyperparameter
  tuning **independently inside every fold**.
- Build lag and rolling features only from months strictly before the origin.
- Never treat a historical-only driver as a future-known regressor. MRP is
  historical: its future value is not known.

## Delivery discipline

At the end of any piece of work:

1. Run the relevant tests and report the **actual output**.
2. Report created and changed files.
3. Update `docs/STATUS.md`, and `docs/DECISIONS.md` if a decision was made.
4. Stop and name any blocker plainly.

Never claim completion because code exists. If something is partially blocked,
finish everything else and say explicitly what was left and why.

Two checks worth keeping, because both catch silent rot:

- **Endpoint drift** — every route in the running app must appear in
  `docs/API_CONTRACT.md` and vice versa. Measured from the running app's own
  `/api/openapi.json`: **69 paths, 74 operations**. The old "65 = 65" and the
  contract's "55 routes" were both stale and counted differently; count paths
  and operations separately when you check it.
- **Decision citations** — every `D-nnn` cited in code must exist in
  `docs/DECISIONS.md`. A missing one was found this way (D-042 was cited by
  `scope_builder.py` but never written).

### Known gaps, stated rather than buried

- The **pooled tier has now run end to end** (D-127): 2 scopes, 3.96 s over
  32,341 origin feature rows, in the 136-SKU run. It is what covers a series
  with too little history for the local tier — one series in that run. Older
  measurements in these docs still come from the aggregate and local tiers only.
- **Error deterioration has never been measured** — the forecast origin is the
  last observed month, so nothing is observable yet. The endpoint returns
  `computable: false` with that reason.
- **No lint has run.** `ruff` is configured but not installed.
- **The assistant writes at temperature 2.0** (`AI_TEMPERATURE`, D-054), set on
  request. **Explanations run at 0.3** (`AI_EXPLANATION_TEMPERATURE`, D-061):
  at 2.0 the first live drift explanation was four-language nonsense. A
  coherence guard in `app/services/assistant/quality.py` rejects unusable or
  ungrounded prose at any temperature and falls back to a template. It is OpenAI's maximum: the same facts give a different answer each
  run, and the prompt's grounding rules are followed less consistently than at
  0. `_clean` drops unevidenced recommendation items, but it cannot detect a
  plausible figure that was never in the facts. `AI_TEMPERATURE=0.3` reverses
  it. Tool selection is a separate setting held at 0.
- **An OpenAI key is now configured** in `backend/.env`, so the AI Assistant
  and AI Recommendations pages make live paid calls at temperature 2.0. Every
  model path is still tested against a stub.
- **Thirteen pages are unrouted but not deleted** (D-052, D-057, D-086, D-105,
  D-161). The UI is six tabs in three sections — Analysis, Modelling,
  Assistant; the removed components still exist under `src/features/`, so the
  suite covers unreachable pages. **Ordered vs Dispatched Time was the most
  recent to go** (D-161), and the Operations section went with it because it
  held nothing else. Its page and components are untouched under
  `features/lead-time`, as is `/analytics/lead-time-observed`; `/lead-time`
  falls through to `/overall`, and one nav block plus one route line plus index
  24 restore it. Supply Intelligence went before it — untouched under
  `features/supply`, `/supply` falls through the same way — and Scenario
  Planner before that, with `POST /api/scenarios` still live and documented
  behind it.
- **Three pages were unrouted earlier.** Executive Command Center,
  Data & Model Monitoring and Connections & Settings were removed from the nav
  and the router on request (D-052). Their components and tests still exist
  under `src/features/`, so the suite covers three unreachable pages. The
  backend endpoints they read are untouched and still documented.
- **The whole application is scoped to one set of locations and SKUs.**
  `app/domain/ais/workspace.py` resolves it from `AIS_WORKSPACE_BRANCHES` and
  `AIS_WORKSPACE_SKUS`, else the active training run's restriction, else
  unrestricted. It currently resolves to **BENGALURU and DELHI-1 with 136
  SKUs**, so every page hides 51 of the 53 ordering branches and all but 136 of
  the 2,063 ordered SKUs — deliberate, requested, and stated on every payload
  as `workspace_scope` plus a note (D-049, D-127, D-128). **Every routed page
  renders the identical banner** — `2 of 53 branches · 136 of 2063 SKUs` —
  which D-131 established across the seven tabs there were then: AI Assistant
  and AI Recommendations had none, and Training and Ordered vs Dispatched Time
  stated the restriction without its denominators. Six tabs remain (D-161), and
  the two Analysis tabs report `full_network` instead (D-138, D-146), which is
  the one unrestricted scope that still states itself. The data was always scoped correctly; the labels were what lied.
  The assistant's tools in particular told the model `"the whole network"` on
  any question that named no branch; they now name the workspace.
  Changing the setting is **not** enough on its own: the panel is physically
  cut to the workspace at build time (D-126), so the pipeline must be re-run —
  preprocessing (if the grain changed), panel build, training, champion
  selection **including `series`**, then a forecast run.
- **A training run can be scoped** to named branches and top-N SKUs
  (`branches`, `max_skus`). A scoped run stores and warns about exactly what it
  covered — its leaderboard is not a network result (D-044). The full-network
  run has not been repeated since.
- **Lead-time variability is surfaced but unused.** `std_lead_time_days` is
  shown on the (now unrouted) Supply Intelligence page, and the protection
  period still uses only the
  average lead time — so a branch with a 3-day mean and a 2.19-day spread
  (NORTH 24 PARAGANAS, 73% variability) gets the same cover as a stable 3-day
  branch. Feeding it into safety stock would change every recommended
  quantity; that is a decision, not a fix. The **Ordered vs Dispatched Time**
  page — called **Lead Time** until D-133 — compares the master's stated
  average against the mean of Despatch Date minus Order Date and does not feed
  safety stock either: it compares, it does not correct (D-105). The rename is
  the honest one, because that difference stops at despatch and never reaches
  receipt, so it is one leg of a lead time and not the whole of it. **That page
  is now unrouted too** (D-161), along with the Operations section it was the
  only member of; the code is intact, the route would be `/lead-time`, and the
  index is still 24 and not reused.
- **AI Recommendations answers at branch × SKU, and the figures are never the
  model's.** All 261 ranked lines are listed; 12 of them carry model-written
  prose and the rest carry their computed reason, labelled as such. Every
  urgency and exception count on the page is a filter into the lines behind it,
  and each card opens into every figure held for that line (D-132). A count
  shown without a way to see what it counts is the defect. The model writes
  sentences only:
  `_merge_lines` builds every figure chip from the line's own fields, so a chip
  reads the same in the fast computed pass and the written one. Do not pass a
  model-supplied number onto a card — that was the defect (D-104, D-131).
- **Training and Forecasting have no "All locations" and no "All SKUs".** Both
  resolved to an aggregate *scope* — the national and per-branch series, each a
  separate thirteen-model race fitted to summed demand. The national scope
  reports 169.87% MAPE on the current run against 10.45% for the median line
  over the same six-month total, and the tile silently switched from a
  six-month figure to a raw per-period one when the scope was not a series.
  Both pages now open on one branch × SKU, and picking a location that does not
  stock the current SKU moves the SKU rather than emptying the page (D-133).
  **The aggregates are still fitted** — MinT reconciliation needs the hierarchy
  to make the lines add up, and the run reports `coherent: true` with
  `max_incoherence: 0.0`. Do not "fix" a cross-line figure by fitting a model
  to summed demand: score each line on its own and report the median, which is
  what `combined_metrics_best` does.
- **Never derive MAPE from accuracy, or accuracy from MAPE.** Accuracy is
  floored at zero (`series_accuracy()`), so on a line whose error exceeds 100%
  the subtraction prints exactly 100% and hides the real figure — four lines of
  this run read 0% six-month accuracy against measured MAPEs of 102.8%, 140.8%,
  357.5% and 100.0%, and twenty floor the same way per period. Both figures are
  carried on the payload (`mape_pct`, `horizon_mape_pct`, `champion_mape_pct`)
  and both screens print both (D-134). The two do agree on 257 of 261 lines,
  which is exactly why the shortcut survives casual testing.
- **The four line tiles are one component, mounted twice.** Next-month
  forecast, chosen model, six-month accuracy and six-month MAPE are rendered by
  `features/line-summary/LineSummaryTiles.tsx` on both Training and Forecasting
  (D-135). Accuracy and MAPE are **one tile each**, and each reads its own
  payload field — never the other minus 100 (D-134, D-160). "Horizons
  available" was removed on request; a horizon with no forecast still says why
  in the forecast table (D-160). Do not copy these onto a third screen — mount
  the component. It issues its own queries under the keys Forecasting already
  uses, so the second mount costs no request.
- **The deployed image carries the workspace's data, not the repository's.**
  `scripts/build_scoped_bundle.py` ships one training run, its panel, its
  fitted models, a branch-restricted extract of the order durations and
  Location Master — 67.9 MB against 348 MB (D-137). Four client workbooks are
  **not** deployed, so ingestion, preprocessing and starting a training run are
  unavailable there, and `/api/health` says so by name. The deployed run
  history is one run, not seven. Two things bite if forgotten: the database
  stores **absolute development-machine paths**, which the script rewrites to
  `/app` and then asserts are gone — without it every page that opens the panel
  returns 500; and `az acr build` **does not honor `.dockerignore`**, so the
  context is assembled by `scripts/stage_build_context.py` and the build runs
  against `deploy/context`, never `.`.
- **A "check this on" label must name a tab that exists.** Five of them named
  unrouted or renamed pages. `VERIFY_ON` and the per-line `next_step` are
  checked by `tests/test_line_evidence_is_computed.py`; update them whenever a
  page is routed or unrouted.
- **Two branches both numbered decisions to 105.** This tree's D-104 and D-105
  are the six-month accuracy panel and weekly grain; `origin/main`'s D-104 and
  D-105 are branch × SKU recommendations and the lead-time comparison. The
  incoming D-105 sits beside the existing one in `docs/DECISIONS.md` with the
  collision stated, because renumbering either breaks citations already in the
  source. Resolve it when the branches are merged, not by a silent edit.
- **The pre-flight cost estimate is 54% high** on the aggregate tier (424 s
  estimated against 275.8 s actual). Conservative is the right direction for a
  warning, but `cost_model.MEASURED_FIT_SECONDS` is derived from a 28-month
  series and aggregate series fit faster. Re-derive from `model_run.fit_seconds`
  once more than three runs exist.
- **A run orphaned by a restart used to report `running` forever.** Fixed by
  `reconcile_orphaned_runs()` in the app lifespan — but the underlying cause
  stands: the job runner is in-process, so any restart still loses in-flight
  work. Reconciliation makes the loss visible, not survivable.

## Prohibited

- Editing anything in a reference project.
- Modifying the AIS source files.
- Committing or pushing unless explicitly asked.
- Mock or placeholder values on a page once a real endpoint exists. An honest
  empty state naming the delivering phase is correct; fabricated numbers are
  not.
- Hiding a model, a failed control, or a data defect.
- Claiming an accuracy figure that was not measured in this project.

# AIS demand & supply intelligence — frontend redesign

## Structure studied

- `frontend/src/app`: ten React Router destinations and shared query client.
- `frontend/src/api`: typed Axios wrappers for FastAPI; sole data boundary.
- `frontend/src/types`: API contracts, not model identities or calculations.
- `frontend/src/features`: data ingestion, mapping, training, leaderboard,
  forecasts, supply, scenarios, monitoring and settings workspaces.
- `backend/app/api/routes`: HTTP contracts; schemas and service orchestration.
- `backend/app/services`: ingestion/panel construction, training, champions,
  forecast generation, reconciliation, inventory, monitoring and scenarios.
- `backend/app/repositories` and `runtime`: persisted runs, database, Parquet,
  model artifacts and MLflow records. Left unchanged.
- `data`, client HTML and ZIP: immutable sources, not frontend seed data.

## Visual system

Official source: https://www.aisglass.com/ (inspected 9 September 2026).
Logo: https://www.aisglass.com/wp-content/uploads/2024/05/logo-desktop.jpg.png
Local copy: `frontend/public/ais-logo.png`; no external runtime asset dependency.

Website colors observed in computed styles: #005BAB corporate blue, #0F2754
navy, white. The supplied logo retains its original red diamond. Supporting
actual/forecast/status colors are a purpose-designed analytics palette.

`src/styles/ais.css` defines the redesigned tokens and shared UI surfaces.
`components/layout` provides the navy navigation, responsive mobile menu,
workflow strip, system status and theme toggle. Existing navigation labels,
skip link, keyboard focus and all operational controls remain available.

`components/charts` centralizes ECharts appearance and reads CSS tokens again on
theme changes. DemandChart handles visual selection only; ComparisonBars charts
server-supplied quantities. Icon.tsx contains UI symbols, not a recreation of
the corporate logo.

## Data provenance

| Visual | API source | Meaning |
| --- | --- | --- |
| Demand timeline | `/api/forecasts/series` | History and reconciled future values |
| Actual vs forecast | `/api/models/{id}/diagnostics` | Persisted held-out predictions from a selected origin |
| Model benchmark | `/api/models/leaderboard` | API-ranked national WAPE; baseline distinction retained |
| Region outlook | `/api/forecasts?scope_level=region` | Selected forecast month; bars drill into Explorer |
| Stock exposure | `/api/inventory/overview` | Snapshot estimates, not live stock |
| Source footprint | Dataset profile endpoint | Measured rows from client sources |
| Evaluation coverage | Current training run | Completed, ineligible, failed, timed-out and budget states |
| Scenario comparison | `/api/scenarios` | Read-only transformation of the persisted baseline |

The Forecast Explorer offers a full timeline plus the three requested views:
Actual, Actual vs forecast, and Forecast. It preserves source/censoring labels,
calibration residual counts, reconciliation adjustments and missing-value reasons.
CSV exports the selected view; Actual vs forecast exports the selected origin.

The source API caps history at 120 months. Current client history is 28 months.
No artificial actuals are plotted for future forecast months. Quantile lines
are service-level quantities, not a fabricated confidence ribbon.

## Changed areas

- New shared charts, icon component and AIS stylesheet.
- Rebuilt application shell and executive dashboard.
- Reworked Explorer and its history request; five new interaction regressions.
- New visuals in Data Studio, mapping, training, supply, scenarios and monitoring.
- Restyled leaderboard charts, theme-aware diagnostics and brand-source settings.
- Local official logo, favicon and HTML metadata.
- Updated dashboard tests, STATUS and DECISIONS.

## Verification and running

`npm test`: 157 passing tests in 15 files. Existing data-honesty, registry,
navigation, mapping, training and inventory contracts remain covered.
`npm run build`: TypeScript and Vite pass. The existing full ECharts import
produces a non-blocking large-bundle warning; no dependency changes were made.

Browser checks covered all ten routes, rendered data charts, actual/backtest
selection, scenario evaluation, light/dark appearance and mobile layouts.
The scenario check did not overwrite its baseline. No training, ingestion,
champion selection or forecast generation was triggered during the redesign.

Frontend: http://127.0.0.1:5173/ ; FastAPI: http://127.0.0.1:8000/api/docs .
Development servers already running; frontend hot reload picks up these files.
Original replaced files are backed up under
`runtime/backups/frontend-redesign-20260909-171111`, with incremental refinement
backups alongside it. Backend and client sources were not changed.

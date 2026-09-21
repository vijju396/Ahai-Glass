/**
 * Forecasting — one branch × SKU at a time, and independent by construction.
 *
 * The independence is the point, so the page states it and then shows it:
 * every series is evaluated, has its champion chosen, and is forecast on its
 * own. Two SKUs at the same branch can and do end up with different models,
 * and this page names the model and the measured error for whichever series
 * you selected rather than a single headline accuracy.
 *
 * Three things it refuses to blur:
 *
 * - **q80/q90/q95 are service levels, not a confidence band.** q95 is the
 *   quantity demand is not expected to exceed 95% of the time.
 * - **A horizon with no interval renders as a point with no band**, and says
 *   which pooling level the calibration fell back to. A fabricated band would
 *   be worse than none.
 * - **The reconciliation adjustment stays a separate column** from the
 *   forecast it adjusted.
 */
import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { DemandChart, type DemandView } from '@/components/charts/DemandChart';
import { monthLabel } from '@/components/charts/Chart';
import { ApiError } from '@/api/client';
import { fetchCurrentForecastRun, fetchSeriesForecast, forecastKeys } from '@/api/forecasts';
import { fetchDiagnostics, fetchScopes, leaderboardKeys } from '@/api/leaderboard';
import {
  analyticsKeys,
  driftKeys,
  fetchAnalyticsFilters,
  fetchDrift,
  type DriftPayload,
} from '@/api/analytics';
import {
  AMBER,
  BLUE,
  GREEN,
  Panel,
  SLATE,
  StatTile,
  TEAL,
  TICK,
  TOOLTIP,
  num,
} from '@/components/ui/Dashboard';
import { Card } from '@/components/ui/Card';
import { ScopeBanner } from '@/components/ui/ScopeBanner';
import { EmptyState, ErrorState, LoadingBlock } from '@/components/ui/States';
import { formatInt } from '@/components/ui/format';

const SELECT =
  'rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-2.5 py-1.5 text-xs text-[var(--color-text)]';

/** The four questions this chart can answer, and what each one draws. */
const VIEWS: ReadonlyArray<readonly [DemandView, string]> = [
  ['overview', 'Full timeline'],
  ['actual', 'Actual'],
  ['validation', 'Backtest vs actual'],
  ['forecast', 'Forecast'],
];

const VIEW_NOTE: Record<string, string> = {
  overview:
    'Everything on one axis: observed actuals through the forecast origin, then six forecast months with their service-level bands. The bands are not a confidence interval — q95 is the quantity demand is not expected to exceed 95% of the time.',
  actual:
    'Observed ordered demand only, with no forecast drawn. Where a month is censored the ordered figure is a lower bound on true demand, because despatch fell short of the order.',
  validation:
    'Stored out-of-sample backtest predictions against the actuals they were scored on. This is how the error on this series was measured — it is not the future forecast, and each origin is shown separately because the same month can carry different predictions from different folds.',
  forecast:
    'The six forecast months on their own, with q80/q90/q95. A horizon with a point but no band had too few out-of-sample residuals to calibrate one at any pooling level; the point is drawn without a band rather than with a fabricated one.',
};

function splitSeries(id: string): { branch: string; sku: string } | null {
  const cut = id.indexOf('|');
  if (cut <= 0 || cut === id.length - 1) return null;
  return { branch: id.slice(0, cut), sku: id.slice(cut + 1) };
}

export function ForecastingPage() {
  const [branch, setBranch] = useState('');
  const [sku, setSku] = useState('');
  const [quantiles, setQuantiles] = useState(true);
  /** Which slice of the timeline the chart draws. `overview` is everything;
   *  `validation` is stored out-of-sample backtest predictions against the
   *  actuals they were scored on, which is a different question from the
   *  future forecast and deserves its own view. */
  const [view, setView] = useState<DemandView>('overview');
  const [range, setRange] = useState(0);
  const [origin, setOrigin] = useState('');

  const filters = useQuery({
    queryKey: analyticsKeys.filters,
    queryFn: fetchAnalyticsFilters,
    retry: false,
  });
  const run = useQuery({
    queryKey: forecastKeys.current,
    queryFn: fetchCurrentForecastRun,
    retry: false,
  });
  const scopes = useQuery({
    queryKey: leaderboardKeys.scopes('series'),
    queryFn: () => fetchScopes('series'),
    retry: false,
  });

  // Two slicers that filter each other. A branch × SKU pair *is* the series,
  // so the pair resolves the scope and no third picker is needed.
  const parsed = useMemo(
    () =>
      (scopes.data?.items ?? []).flatMap((s) => {
        const parts = splitSeries(s.scope_key);
        return parts ? [{ scope_key: s.scope_key, ...parts }] : [];
      }),
    [scopes.data],
  );
  const branchOptions = useMemo(
    () => [...new Set(parsed.filter((r) => !sku || r.sku === sku).map((r) => r.branch))].sort(),
    [parsed, sku],
  );
  const skuOptions = useMemo(
    () => [...new Set(parsed.filter((r) => !branch || r.branch === branch).map((r) => r.sku))].sort(),
    [parsed, branch],
  );
  const matching = parsed.filter((r) => (!branch || r.branch === branch) && (!sku || r.sku === sku));

  /** Which forecast scope the current selection addresses.
   *
   *  The page used to resolve only when exactly one series matched, so "All
   *  locations / All SKUs" and "one location / All SKUs" both showed nothing
   *  — even though the run holds a national forecast and one per branch.
   *  Every selection that corresponds to a real forecast scope now resolves
   *  to it, and the level is named on screen so an aggregate figure is never
   *  mistaken for a cell.
   *
   *  The one combination with no scope is a single SKU across branches: the
   *  hierarchy has no SKU level, so nothing was modelled for it. That is
   *  stated rather than silently shown as empty. */
  const resolved = useMemo((): { level: string; key: string; label: string } | null => {
    if (branch && sku) {
      const hit = matching.find((r) => r.branch === branch && r.sku === sku);
      return hit ? { level: 'series', key: hit.scope_key, label: `${branch} × ${sku}` } : null;
    }
    if (branch && !sku) return { level: 'branch', key: branch, label: `all SKUs at ${branch}` };
    if (!branch && !sku)
      return { level: 'national', key: 'NATIONAL', label: 'every branch and SKU in scope' };
    return null;
  }, [branch, sku, matching]);

  const scopeLevel = resolved?.level ?? '';
  const scopeKey = resolved?.key ?? '';
  const isAggregate = Boolean(resolved) && resolved!.level !== 'series';

  const series = useQuery({
    queryKey: forecastKeys.series(scopeLevel, scopeKey),
    queryFn: () => fetchSeriesForecast(scopeLevel, scopeKey),
    enabled: Boolean(scopeKey),
    retry: false,
  });

  const drift = useQuery({
    queryKey: driftKeys.scope(branch || undefined, sku || undefined),
    queryFn: () => fetchDrift(branch || undefined, sku || undefined),
    retry: false,
  });

  const data = series.data;
  const history = data?.history ?? [];
  const forecasts = data?.forecasts ?? [];
  const metrics = data?.validation_metrics;

  // Backtest predictions, fetched only for the view that draws them.
  const modelId = metrics?.model_id ?? '';
  const diagnosticQuery = {
    training_run_id: data?.training_run_id,
    scope_level: scopeLevel,
    scope_key: scopeKey,
  };
  const diagnostics = useQuery({
    queryKey: leaderboardKeys.diagnostics(modelId, diagnosticQuery),
    queryFn: () => fetchDiagnostics(modelId, diagnosticQuery),
    // Also on `overview`: the full timeline shows all three series, so it
    // needs the backtest points as well as the forecast.
    enabled: (view === 'validation' || view === 'overview') && Boolean(modelId),
    retry: false,
  });

  /** Origins are kept apart: the same month can carry different predictions
   *  from different folds, and overlaying them would read as one jagged line
   *  rather than two honest ones. */
  const originKey = (p: { origin_name: string | null; fold_index: number | null }) =>
    `${p.origin_name ?? 'Origin'} · fold ${p.fold_index ?? 0}`;
  const origins = [...new Set((diagnostics.data?.points ?? []).map(originKey))];
  const selectedOrigin = origins.includes(origin) ? origin : (origins[origins.length - 1] ?? '');
  const validationPoints = (diagnostics.data?.points ?? [])
    .filter((p) => originKey(p) === selectedOrigin)
    .sort((a, b) => (a.period ?? '').localeCompare(b.period ?? ''));
  const withoutInterval = forecasts.filter((r) => r.point_forecast !== null && r.q95 === null);

  return (
    <div className="flex flex-col gap-4">
      <header>
        <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[var(--color-primary)]">
          Forecasting
        </p>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight text-[var(--color-text)]">
          Six months ahead, per branch and SKU.
        </h1>
        <p className="mt-1 max-w-3xl text-sm text-[var(--color-text-muted)]">
          Every series is validated, has its champion chosen, and is forecast{' '}
          <strong>independently</strong>. Two SKUs at the same branch routinely end up with
          different models, so the model and the measured error shown below belong to the
          series you selected — there is no single headline accuracy.
        </p>
      </header>

      <ScopeBanner scope={filters.data?.workspace_scope} />

      <Card>
        <div className="flex flex-wrap items-end gap-2.5">
          <label className="inline-flex flex-col gap-0.5">
            <span className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--color-text-muted)]">
              Location
            </span>
            <select aria-label="Location" className={SELECT} value={branch} onChange={(e) => setBranch(e.target.value)}>
              <option value="">All locations</option>
              {branchOptions.map((b) => (
                <option key={b} value={b}>
                  {b}
                </option>
              ))}
            </select>
          </label>
          <label className="inline-flex flex-col gap-0.5">
            <span className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--color-text-muted)]">
              SKU
            </span>
            <select aria-label="SKU" className={SELECT} value={sku} onChange={(e) => setSku(e.target.value)}>
              <option value="">All SKUs</option>
              {skuOptions.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>
          <label className="inline-flex items-center gap-1.5 pb-2 text-[11px] text-[var(--color-text)]">
            <input type="checkbox" checked={quantiles} onChange={(e) => setQuantiles(e.target.checked)} />
            Show q80 / q90 / q95
          </label>
        </div>
        <p className="mt-2 text-[11px] text-[var(--color-text-muted)]">
          {resolved ? (
            <>
              Forecasting <strong>{resolved.label}</strong> — the{' '}
              <strong>{resolved.level}</strong> scope{' '}
              <span className="mono text-[10px]">{scopeKey}</span>.
            </>
          ) : (
            <>
              <strong>{sku}</strong> is stocked at {matching.length} branches, and the
              forecast hierarchy has no SKU level — nothing was modelled for one SKU across
              branches. Pick a location too, or clear the SKU.
            </>
          )}{' '}
          Only scopes a training run actually reached are listed — one it did not reach does
          not appear here.
          {run.data && (
            <>
              {' '}Origin {monthLabel(run.data.origin_period)}, reconciled by{' '}
              {run.data.reconciliation_method}.
            </>
          )}
        </p>
        {run.isError && run.error instanceof ApiError && (
          <p className="hint mt-1">
            {run.error.message} {run.error.remediation}
          </p>
        )}
      </Card>

      {!resolved && (
        <>
          <DriftPanel query={drift} />
        </>
      )}

      {!resolved && (
        <Card>
          <EmptyState title="No forecast scope for one SKU across branches">
            The hierarchy is national → region → branch → branch × SKU. A single SKU spanning
            several branches is not a level in it, so no model was fitted and no forecast
            exists. Choose a location as well, or clear the SKU for the national view.
          </EmptyState>
        </Card>
      )}

      {scopeKey && series.isPending && (
        <Card>
          <LoadingBlock rows={8} label="Loading the forecast" />
        </Card>
      )}
      {scopeKey && series.isError && (
        <Card>
          {series.error instanceof ApiError && series.error.status === 404 ? (
            <EmptyState title="No forecast for this series">
              {series.error.message} {series.error.remediation}
            </EmptyState>
          ) : (
            <ErrorState error={series.error} onRetry={() => series.refetch()} />
          )}
        </Card>
      )}

      {data && (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <StatTile
              label="Next-month forecast"
              value={formatInt(forecasts[0]?.point_forecast)}
              sublabel={forecasts[0] ? `${monthLabel(forecasts[0].period)} · reconciled units` : 'unavailable'}
              tint="blue"
              accent
            />
            <StatTile
              label="Model chosen for this series"
              value={metrics?.display_name ?? '—'}
              sublabel="selected on this series alone"
              tint="navy"
            />
            {/* MAPE, not WAPE. MAPE is the metric the champion for this series
                was selected on (D-043), so the error quoted beside the model
                name is the error that chose it. WAPE is still computed and
                still on the leaderboard; quoting it here named one metric while
                the selection used another. */}
            <StatTile
              label="Measured error"
              value={metrics?.mape == null ? '—' : `${metrics.mape.toFixed(2)}% MAPE`}
              sublabel={`out of sample · ${formatInt(metrics?.validation_points)} points`}
              tint="teal"
            />
            <StatTile
              label="Horizons available"
              value={`${forecasts.filter((f) => f.point_forecast !== null).length} / ${forecasts.length}`}
              sublabel="a horizon with no forecast says why"
              tint="amber"
            />
          </div>

          <Panel
            title={`Outlook — ${scopeKey}`}
            accent={BLUE}
            note={VIEW_NOTE[view]}
          >
            <div className="chart-toolbar">
              <div className="segmented" role="group" aria-label="Chart view">
                {VIEWS.map(([id, label]) => (
                  <button
                    key={id}
                    type="button"
                    aria-pressed={view === id}
                    onClick={() => setView(id)}
                  >
                    {label}
                  </button>
                ))}
              </div>
              {(view === 'actual' || view === 'overview') && (
                <label className="field">
                  <span className="visually-hidden">History range</span>
                  <select
                    aria-label="History range"
                    value={range}
                    onChange={(e) => setRange(Number(e.target.value))}
                  >
                    <option value={0}>All history</option>
                    <option value={12}>Last 12 months</option>
                    <option value={6}>Last 6 months</option>
                  </select>
                </label>
              )}
              {view === 'validation' && origins.length > 0 && (
                <label className="field">
                  <span>Backtest origin</span>
                  <select
                    aria-label="Backtest origin"
                    value={selectedOrigin}
                    onChange={(e) => setOrigin(e.target.value)}
                  >
                    {origins.map((o) => (
                      <option key={o}>{o}</option>
                    ))}
                  </select>
                </label>
              )}
              {(view === 'forecast' || view === 'overview') && (
                <label className="check-row">
                  <input
                    type="checkbox"
                    checked={quantiles}
                    onChange={(e) => setQuantiles(e.target.checked)}
                  />
                  Show q80 / q90 / q95
                </label>
              )}
            </div>

            {view !== 'validation' ? (
              <DemandChart
                data={data}
                view={view}
                points={view === 'overview' ? validationPoints : []}
                quantiles={quantiles}
                range={range}
                height={330}
              />
            ) : diagnostics.isFetching ? (
              <LoadingBlock rows={8} label="Loading backtest predictions" />
            ) : diagnostics.isError ? (
              <ErrorState error={diagnostics.error} onRetry={() => diagnostics.refetch()} />
            ) : validationPoints.length ? (
              <DemandChart data={data} view="validation" points={validationPoints} height={330} />
            ) : (
              <EmptyState title="No backtest predictions stored for this series">
                {diagnostics.data?.unavailable_reason ??
                  'The model used on this scope has no stored out-of-sample predictions. Nothing is drawn rather than a fabricated comparison.'}
              </EmptyState>
            )}
            {data.history_unavailable_reason && (
              <p className="chart-note">{data.history_unavailable_reason}</p>
            )}
            {withoutInterval.length > 0 && (
              <p className="chart-note">
                {withoutInterval.length} horizon(s) have a point forecast but no interval: the
                calibration had too few out-of-sample residuals at any pooling level. The point
                is shown without a band rather than with a fabricated one.
              </p>
            )}
            <p className="chart-note">{data.snapshot_caveat}</p>
          </Panel>

          {isAggregate && (
            <div className="rounded-lg border border-[var(--color-warning,#a15c07)]/35 bg-[var(--color-warning,#a15c07)]/5 px-3 py-2">
              <p className="text-[11px] leading-relaxed text-[var(--color-text)]">
                <strong>This is an aggregate.</strong> Aggregate demand is far less
                intermittent than a single branch × SKU cell and much easier to forecast, so
                this error does <strong>not</strong> transfer down — do not read it as the
                accuracy you would get on one product at one branch. Pick a location and a
                SKU for that.
              </p>
            </div>
          )}

          {view === 'validation' && validationPoints.length > 0 && (
            <Panel
              title={`Backtest against actual — ${selectedOrigin}`}
              accent={GREEN}
              note="Stored out-of-sample predictions and the actuals they were scored against. Residual is actual minus forecast, so a negative residual means the model forecast above what happened."
            >
              <div className="table-scroll max-h-[280px]">
                <table className="data" data-testid="backtest-table">
                  <thead>
                    <tr>
                      <th>Month</th>
                      <th className="num">Horizon</th>
                      <th className="num">Actual</th>
                      <th className="num">Backtest forecast</th>
                      <th className="num">Residual</th>
                    </tr>
                  </thead>
                  <tbody>
                    {validationPoints.map((p, i) => (
                      <tr key={`${p.period}-${p.horizon}-${i}`}>
                        <td>{monthLabel(p.period ?? '')}</td>
                        <td className="num">{p.horizon}</td>
                        <td className="num">{formatInt(p.actual)}</td>
                        <td className="num">{formatInt(p.predicted)}</td>
                        <td className="num">{formatInt(p.residual)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Panel>
          )}

          {view === 'actual' && history.length > 0 && (
            <Panel
              title="Actual demand detail"
              accent={SLATE}
              note="Historical quantities with the source each came from and whether despatch fell short. A censored month means the ordered figure is a lower bound on what was really wanted."
            >
              <div className="table-scroll max-h-[280px]">
                <table className="data" data-testid="actual-table">
                  <thead>
                    <tr>
                      <th>Month</th>
                      <th className="num">Actual units</th>
                      <th>Source</th>
                      <th>Censored</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(range ? history.slice(-range) : history).map((p) => (
                      <tr key={p.period}>
                        <td>{monthLabel(p.period)}</td>
                        <td className="num">{formatInt(p.actual)}</td>
                        <td>{p.target_source ?? 'Not recorded'}</td>
                        <td>{p.is_censored ? 'Yes' : 'No'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Panel>
          )}

          <Panel
            title="Every horizon, with its provenance"
            accent={TEAL}
            note="The reconciliation adjustment is its own column, never folded into the forecast. 'Interval from' names the calibration method, the pooling level it fell back to, and how many residuals backed it."
          >
            <div className="table-scroll">
              <table className="data" data-testid="forecast-table">
                <thead>
                  <tr>
                    <th>Period</th>
                    <th className="num">h</th>
                    <th className="num">Point</th>
                    <th className="num">q80</th>
                    <th className="num">q90</th>
                    <th className="num">q95</th>
                    <th className="num">Pre-reconciliation</th>
                    <th className="num">Adjustment</th>
                    <th>Interval from</th>
                    <th>Model</th>
                    <th>Reason</th>
                  </tr>
                </thead>
                <tbody>
                  {forecasts.map((row) => (
                    <tr key={row.id}>
                      <td className="mono">{row.period}</td>
                      <td className="num">{row.horizon}</td>
                      <td className="num">{formatInt(row.point_forecast)}</td>
                      <td className="num">{formatInt(row.q80)}</td>
                      <td className="num">{formatInt(row.q90)}</td>
                      <td className="num">{formatInt(row.q95)}</td>
                      <td className="num">{formatInt(row.base_forecast)}</td>
                      <td className="num">{formatInt(row.reconciliation_adjustment)}</td>
                      <td className="text-[10px]">
                        {row.quantile_method
                          ? `${row.quantile_method} · ${row.quantile_pooling_level} · ${formatInt(row.quantile_residual_count)} residuals`
                          : '—'}
                      </td>
                      <td className="text-[10px]">{row.model_display_name ?? row.model_id ?? '—'}</td>
                      <td className="text-[10px]">{row.unavailable_reason ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>

          {metrics && (
            <Panel
              title="Why this model, for this series"
              accent={GREEN}
              note="Measured out of sample on this series only. Aggregate error does not transfer down: an aggregate is far less intermittent and much easier to forecast than a single branch × SKU cell."
            >
              <div className="metric-row">
                {[
                  ['Model', metrics.display_name],
                  // MAPE first: it is the selection metric, and the table did
                  // not carry it at all while the tile above quoted WAPE.
                  ['MAPE %', metrics.mape?.toFixed(3) ?? '—'],
                  ['WAPE %', metrics.wape?.toFixed(3) ?? '—'],
                  ['MAE', formatInt(metrics.mae)],
                  ['RMSE', formatInt(metrics.rmse)],
                  ['MASE', metrics.mase?.toFixed(3) ?? '—'],
                  ['Bias %', metrics.bias?.toFixed(2) ?? '—'],
                  ['Validation points', formatInt(metrics.validation_points)],
                  ['Evaluation mode', metrics.evaluation_mode ?? '—'],
                ].map(([label, value]) => (
                  <div className="metric" key={String(label)}>
                    <span className="metric-label">{label}</span>
                    <span className="metric-value">{value}</span>
                  </div>
                ))}
              </div>
              <p className="mt-2 text-[11px] leading-relaxed text-[var(--color-text-muted)]">
                A negative bias means this model forecasts below actual demand on this series.
                For an inventory decision that is the direction that causes a stockout, which
                is why replenishment sizes on q80/q90/q95 rather than on the point forecast.
              </p>
            </Panel>
          )}

                    <DriftPanel query={drift} />

          {data.drivers && (
            <Panel title="What the model was given" accent={SLATE} note="The inputs and the values it resolved for this series.">
              <div className="table-scroll">
                <table className="data">
                  <tbody>
                    {Object.entries(data.drivers).map(([key, value]) => (
                      <tr key={key}>
                        <th style={{ textAlign: 'left', width: '30%' }}>{key.replace(/_/g, ' ')}</th>
                        <td className="mono text-[11px]">
                          {typeof value === 'object' && value !== null ? JSON.stringify(value) : String(value)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Panel>
          )}
        </>
      )}
    </div>
  );
}


const WRITER_LABEL: Record<string, string> = {
  openai: 'Explained by the model from these figures',
  deterministic_no_key: 'Explained from templates — no API key configured',
  deterministic_after_provider_error: 'Explained from templates — the provider failed',
  deterministic_after_unusable_reply:
    'Explained from templates — the model’s reply was not usable prose',
};

/**
 * Demand drift, and when it would next cross the reading aid.
 *
 * Drift is **measured** from the panel: each point compares a six-month
 * window against the six before it. The projection is a straight line through
 * those points, extrapolated — it is not a forecast from any of the thirteen
 * models, and it refuses to give a date far more often than it gives one.
 *
 * Points whose window straddles Apr 2025 are drawn in a muted colour, because
 * the panel changes source there from invoiced sales proxy to real orders:
 * part of the shift across that boundary is a change of measurement, not of
 * demand. The projection excludes them.
 */
function DriftPanel({
  query,
}: {
  query: { data?: DriftPayload; isPending: boolean; isError: boolean; error: unknown };
}) {
  const d = query.data;

  if (query.isPending) {
    return (
      <Card>
        <LoadingBlock rows={5} label="Measuring demand drift" />
      </Card>
    );
  }
  if (query.isError || !d) {
    return (
      <Card>
        <ErrorState error={query.error} />
      </Card>
    );
  }
  if (d.empty) {
    return (
      <Card>
        <h2 className="text-[11px] font-semibold uppercase tracking-[0.06em] text-[var(--color-primary)]">
          Demand drift
        </h2>
        <p className="mt-1 text-[11px] leading-relaxed text-[var(--color-text-muted)]">{d.reason}</p>
      </Card>
    );
  }

  const projection = d.projection ?? { projectable: false };
  const explanation = d.explanation;

  /** Two columns over the same points so the line can change character where
   *  the data does. A measured month and a month whose window straddles the
   *  source change are not the same kind of evidence, and one continuous
   *  stroke would say they were. The overlap month is written to both so the
   *  segments join rather than leaving a visible break. */
  const raw = d.points ?? [];
  const points = raw.map((p, i) => {
    const prev = raw[i - 1];
    const next = raw[i + 1];
    const touchesStraddle =
      p.straddles_measurement_change ||
      Boolean(prev?.straddles_measurement_change) ||
      Boolean(next?.straddles_measurement_change);
    return {
      ...p,
      label: p.period.slice(2),
      clean_pct: p.straddles_measurement_change ? null : p.shift_pct,
      straddling_pct: touchesStraddle ? p.shift_pct : null,
      projected_pct: null as number | null,
    };
  });

  /** The projection drawn as a path from today's drift to the crossing, so
   *  the reader sees the slope the date rests on rather than only the date. */
  const changeLabel = raw.find((p) => p.straddles_measurement_change)?.period.slice(2) ?? null;
  if (projection.projectable && points.length > 0 && projection.months_ahead) {
    const last = points[points.length - 1]!;
    last.projected_pct = last.shift_pct;
    const step = Math.max(1, Math.round(projection.months_ahead));
    for (let m = 1; m <= step; m += 1) {
      const [y, mo] = last.period.split('-').map(Number);
      const idx = (y ?? 0) * 12 + (mo ?? 1) - 1 + m;
      const period = `${Math.floor(idx / 12)}-${String((idx % 12) + 1).padStart(2, '0')}`;
      points.push({
        ...last,
        period,
        label: period.slice(2),
        // `null`, never NaN: a NaN here propagates into the Y-axis domain and
        // Recharts then renders an empty container with no error.
        shift_pct: null as unknown as number,
        clean_pct: null,
        straddling_pct: null,
        projected_pct: last.shift_pct + (projection.slope_pct_per_month ?? 0) * m,
      });
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatTile
          label="Drift now"
          value={`${(d.latest?.shift_pct ?? 0) > 0 ? '+' : ''}${d.latest?.shift_pct ?? '—'}%`}
          sublabel={`last ${d.window_months} months vs the ${d.window_months} before`}
          tint={d.latest?.is_material ? 'amber' : 'teal'}
          accent
        />
        <StatTile
          label="Recent average"
          value={`${num(d.latest?.recent_mean)} units`}
          sublabel={`baseline ${num(d.latest?.baseline_mean)} units`}
          tint="blue"
        />
        <StatTile
          label="Reading aid"
          value={`${d.threshold_pct}%`}
          sublabel="a stated line, not a statistical result"
          tint="navy"
        />
        <StatTile
          label="Next crossing"
          value={projection.projectable ? (projection.expected_period ?? '—') : 'Not projectable'}
          sublabel={
            projection.projectable
              ? `~${projection.months_ahead} months, on the observed trend`
              : 'the data does not support a date'
          }
          tint={projection.projectable ? 'amber' : 'teal'}
        />
      </div>

      <Panel
        title="Demand Drift — measured, with a projected crossing"
        accent={AMBER}
        note={`Each point compares a ${d.window_months}-month window against the ${d.window_months} before it. Muted bars straddle ${d.measurement_change}, where the panel changes from invoiced sales proxy to real orders — part of that shift is a change of measurement, not of demand, so the projection excludes them.`}
      >
        <ResponsiveContainer width="100%" height={280}>
          <LineChart data={points} margin={{ top: 10, right: 16, left: -6, bottom: 0 }}>
            <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="var(--color-border)" />
            <XAxis dataKey="label" tick={{ ...TICK, fontSize: 9 }} tickLine={false} interval={0} />
            <YAxis tick={TICK} width={50} unit="%" />
            <Tooltip
              contentStyle={TOOLTIP}
              formatter={(v: number) => [`${v}%`, 'Shift vs baseline']}
              labelFormatter={(label) => {
                const row = points.find((p) => p.label === label);
                return row
                  ? `${row.period} — ${num(row.recent_mean)} vs ${num(row.baseline_mean)} units`
                  : String(label);
              }}
            />
            <Legend wrapperStyle={{ fontSize: 9 }} />

            {/* The band inside the reading aid, so "normal" is a region rather
                than a pair of lines the eye has to hold apart. */}
            <ReferenceArea
              y1={-(d.threshold_pct ?? 20)}
              y2={d.threshold_pct ?? 20}
              fill={TEAL}
              fillOpacity={0.06}
            />
            <ReferenceLine y={0} stroke={SLATE} />
            <ReferenceLine
              y={d.threshold_pct}
              stroke={AMBER}
              strokeDasharray="5 4"
              label={{ value: `+${d.threshold_pct}%`, position: 'right', fill: AMBER, fontSize: 9 }}
            />
            <ReferenceLine
              y={-(d.threshold_pct ?? 0)}
              stroke={AMBER}
              strokeDasharray="5 4"
              label={{ value: `-${d.threshold_pct}%`, position: 'right', fill: AMBER, fontSize: 9 }}
            />

            {/* Where the source changes. A line crossing it compares an
                invoiced proxy with real orders. */}
            {changeLabel && (
              <ReferenceLine
                x={changeLabel}
                stroke={SLATE}
                strokeDasharray="3 3"
                label={{
                  value: 'source changes',
                  position: 'insideTopLeft',
                  fill: SLATE,
                  fontSize: 9,
                }}
              />
            )}

            {/* Two series over the same points: the muted one covers the
                windows that straddle the source change, so the solid line is
                only ever drawn over comparable months. */}
            <Line
              type="monotone"
              dataKey="clean_pct"
              name="Shift (comparable months)"
              stroke={BLUE}
              strokeWidth={2.5}
              // Deliberately NOT connectNulls. The gap is where the windows
              // straddle the source change and the comparison is not
              // like-for-like; bridging it would draw a confident straight
              // line through the one region this chart exists to exclude.
              // The dashed grey series covers those months instead.
              dot={{ r: 2.5, fill: BLUE }}
              activeDot={{ r: 4 }}
              isAnimationActive={false}
            />
            <Line
              type="monotone"
              dataKey="straddling_pct"
              name="Spans the source change"
              stroke={SLATE}
              strokeWidth={2}
              strokeDasharray="4 3"
              connectNulls
              dot={{ r: 2, fill: SLATE }}
              isAnimationActive={false}
            />

            {/* The projected path to the threshold, drawn as what it is: a
                dashed extrapolation, visually distinct from measurement. */}
            {projection.projectable && (
              <Line
                type="linear"
                dataKey="projected_pct"
                name="Projected (trend extrapolated)"
                stroke={AMBER}
                strokeWidth={2}
                strokeDasharray="2 4"
                connectNulls
                dot={false}
                isAnimationActive={false}
              />
            )}
          </LineChart>
        </ResponsiveContainer>

        <div className="mt-2 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-2)] px-3 py-2">
          <div className="flex flex-wrap items-baseline gap-2">
            <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--color-primary)]">
              What this means
            </span>
            {explanation && (
              <span className="text-[9px] text-[var(--color-text-muted)]">
                {WRITER_LABEL[explanation.answered_by] ?? explanation.answered_by}
              </span>
            )}
          </div>
          <p className="mt-1 text-[11.5px] leading-relaxed text-[var(--color-text)]">
            {explanation?.text ?? 'No explanation is available.'}
          </p>
          {projection.projectable === false && projection.reason && (
            <p className="mt-1 text-[10px] leading-relaxed text-[var(--color-text-muted)]">
              <strong>No date projected:</strong> {projection.reason}
            </p>
          )}
          {projection.projectable && (
            <p className="mt-1 text-[10px] leading-relaxed text-[var(--color-text-muted)]">
              Fitted on {projection.points_used} points, slope{' '}
              {projection.slope_pct_per_month} pp/month
              {projection.r_squared != null && <>, R² {projection.r_squared}</>}. {projection.basis}
            </p>
          )}
        </div>

        <ul className="mt-2 flex flex-col gap-1">
          {(d.caveats ?? []).map((c) => (
            <li key={c} className="text-[10px] leading-relaxed text-[var(--color-text-muted)]">
              {c}
            </li>
          ))}
        </ul>
      </Panel>
    </div>
  );
}

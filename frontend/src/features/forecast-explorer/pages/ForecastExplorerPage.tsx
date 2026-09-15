/**
 * Forecast Explorer.
 *
 * History and six horizons for one scope, with the q80/q90/q95 bands, the model
 * that produced them, its validation metrics, the drivers, and the
 * reconciliation adjustment.
 *
 * No arithmetic happens here. The point forecast, every quantile and the
 * adjustment all arrive computed; this page selects, formats and charts them.
 * `src/test/no-duplicate-registry.test.ts` asserts that separation by scanning
 * for forecasting code in the frontend.
 *
 * A horizon with no interval renders as a **point with no band**, and says
 * which pooling level the calibration fell back to. A fabricated band would be
 * worse than none.
 */
import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { DemandChart, type DemandView } from '@/components/charts/DemandChart';
import { MetricCard, monthLabel } from '@/components/charts/Chart';
import { Icon } from '@/components/ui/Icon';
import { useQuery } from '@tanstack/react-query';
import { ApiError } from '@/api/client';
import { fetchCurrentForecastRun, fetchSeriesForecast, forecastKeys } from '@/api/forecasts';
import { fetchDiagnostics, fetchScopes, leaderboardKeys } from '@/api/leaderboard';
import { Card } from '@/components/ui/Card';
import { EmptyState, ErrorState, LoadingBlock } from '@/components/ui/States';
import { formatInt } from '@/components/ui/format';
import type { ForecastRow, HistoryPoint } from '@/types/phase7';

const SCOPE_LEVELS = ['national', 'region', 'branch', 'segment', 'series'] as const;

/**
 * A series scope key is `BRANCH|SKU`. Splitting it is how the branch and SKU
 * filters below are populated: they are read off the scopes that were actually
 * trained, so the two dropdowns can never offer a combination the run does not
 * hold. Nothing is fetched for them and nothing is computed - a split on a
 * delimiter is not forecasting arithmetic.
 */
function splitSeriesKey(scopeKey: string): { branch: string; sku: string } | null {
  const cut = scopeKey.indexOf('|');
  if (cut <= 0 || cut === scopeKey.length - 1) return null;
  return { branch: scopeKey.slice(0, cut), sku: scopeKey.slice(cut + 1) };
}

function toCsv(history: HistoryPoint[], forecasts: ForecastRow[]): string {
  const head = [
    'period',
    'kind',
    'actual',
    'point_forecast',
    'q80',
    'q90',
    'q95',
    'base_forecast',
    'reconciliation_adjustment',
    'model_id',
    'target_source',
    'is_censored',
    'unavailable_reason',
  ].join(',');
  const escape = (value: unknown) =>
    value === null || value === undefined
      ? ''
      : `"${String(value).replace(/"/g, '""')}"`;
  const historyRows = history.map((point) =>
    [
      point.period,
      'actual',
      point.actual,
      '',
      '',
      '',
      '',
      '',
      '',
      '',
      point.target_source ?? '',
      point.is_censored,
      '',
    ]
      .map(escape)
      .join(','),
  );
  const forecastRows = forecasts.map((row) =>
    [
      row.period,
      'forecast',
      '',
      row.point_forecast,
      row.q80,
      row.q90,
      row.q95,
      row.base_forecast,
      row.reconciliation_adjustment,
      row.model_id ?? '',
      row.target_source ?? '',
      row.is_censored ?? '',
      row.unavailable_reason ?? '',
    ]
      .map(escape)
      .join(','),
  );
  return [head, ...historyRows, ...forecastRows].join('\n');
}

export function ForecastExplorerPage() {
  const [search] = useSearchParams();
  // Series is the landing level. It is the grain the whole application
  // forecasts at, and the only level where a location and a SKU are separate
  // choices - so it is where the filters belong and where a reader arrives.
  const initialLevel = search.get('level') ?? 'series';
  const [scopeLevel, setScopeLevel] = useState<string>(SCOPE_LEVELS.includes(initialLevel as typeof SCOPE_LEVELS[number]) ? initialLevel : 'series');
  const [scopeKey, setScopeKey] = useState<string>(
    search.get('scope') ?? (initialLevel === 'national' ? 'NATIONAL' : ''),
  );
  const [branchFilter, setBranchFilter] = useState('');
  const [skuFilter, setSkuFilter] = useState('');
  const [view, setView] = useState<DemandView>('overview');
  const [quantiles, setQuantiles] = useState(true);
  const [range, setRange] = useState(0);
  const [origin, setOrigin] = useState('');

  const run = useQuery({
    queryKey: forecastKeys.current,
    queryFn: fetchCurrentForecastRun,
    retry: false,
  });
  const scopes = useQuery({
    queryKey: leaderboardKeys.scopes(scopeLevel),
    queryFn: () => fetchScopes(scopeLevel),
    retry: false,
  });
  const allScopes = scopes.data?.items ?? [];
  const isSeries = scopeLevel === 'series';
  const parsedScopes = isSeries
    ? allScopes.flatMap((scope) => {
        const parts = splitSeriesKey(scope.scope_key);
        return parts ? [{ ...scope, ...parts }] : [];
      })
    : [];

  // Two slicers that filter each other, both ways.
  //
  // Location lists the branches that stock the selected SKU; SKU lists the
  // SKUs the selected location stocks. Neither list can ever offer a value
  // that would produce an empty result, in either direction - which is the
  // behaviour of a cross-filtered slicer and the reason there is no third
  // dropdown.
  const matching = parsedScopes.filter(
    (row) =>
      (!branchFilter || row.branch === branchFilter) &&
      (!skuFilter || row.sku === skuFilter),
  );
  const branchOptions = [
    ...new Set(
      parsedScopes.filter((row) => !skuFilter || row.sku === skuFilter).map((row) => row.branch),
    ),
  ].sort();
  const skuOptions = [
    ...new Set(
      parsedScopes
        .filter((row) => !branchFilter || row.branch === branchFilter)
        .map((row) => row.sku),
    ),
  ].sort();

  // A location and a SKU together *are* the series, so the pair resolves the
  // scope on its own. A separate "Branch x SKU" dropdown would have restated
  // the two choices already made, and been the only way to contradict them.
  const effectiveScopeKey = isSeries
    ? matching.length === 1
      ? matching[0]!.scope_key
      : ''
    : scopeKey;

  const series = useQuery({
    queryKey: forecastKeys.series(scopeLevel, effectiveScopeKey),
    queryFn: () => fetchSeriesForecast(scopeLevel, effectiveScopeKey),
    enabled: Boolean(effectiveScopeKey),
    retry: false,
  });

  const data = series.data;
  const history = data?.history ?? [];
  const forecasts = data?.forecasts ?? [];
  const modelId = data?.validation_metrics?.model_id ?? '';
  const diagnosticQuery = { training_run_id: data?.training_run_id, scope_level: scopeLevel, scope_key: effectiveScopeKey };
  const diagnostics = useQuery({
    queryKey: leaderboardKeys.diagnostics(modelId, diagnosticQuery),
    queryFn: () => fetchDiagnostics(modelId, diagnosticQuery),
    enabled: view === 'validation' && Boolean(modelId), retry: false,
  });
  // Keep origins separate: a month can have different predictions at different horizons.
  const originKey = (p: { origin_name: string | null; fold_index: number | null }) => `${p.origin_name ?? 'Origin'} · fold ${p.fold_index ?? 0}`;
  const origins = [...new Set((diagnostics.data?.points ?? []).map(originKey))];
  const selectedOrigin = origins.includes(origin) ? origin : origins[origins.length - 1] ?? '';
  const validationPoints = (diagnostics.data?.points ?? []).filter(p => originKey(p) === selectedOrigin).sort((a, b) => (a.period ?? '').localeCompare(b.period ?? ''));

  const download = () => {
    if (!data) return;
    const csv = view === 'validation'
      ? ['period,origin,fold,horizon,actual,backtest_forecast,residual', ...validationPoints.map(p => [p.period, p.origin_name, p.fold_index, p.horizon, p.actual, p.predicted, p.residual].map(v => `"${String(v ?? '').replace(/"/g, '""')}"`).join(','))].join('\n')
      : toCsv(view === 'forecast' ? [] : range ? history.slice(-range) : history, view === 'actual' ? [] : forecasts);
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `${view}_${scopeLevel}_${effectiveScopeKey.replace(/[^\w.-]+/g, '_')}.csv`;
    anchor.click();
    URL.revokeObjectURL(url);
  };

  const withoutInterval = forecasts.filter(
    (row) => row.point_forecast !== null && row.q95 === null,
  );

  return (
    <div className="stack">
      <div className="page-head page-head-row"><div>
        <div className="eyebrow">06 &middot; Forecast Explorer</div>
        <h1>Forecast Explorer</h1>
        <p className="lede">
          Understand what happened. Validate what was predicted. Explore what comes next.
        </p>
      </div><span className="pill pill-info">Monthly demand intelligence</span></div>

      <Card title="Selection" subtitle={run.data ? `Origin ${monthLabel(run.data.origin_period)} · reconciled by ${run.data.reconciliation_method}` : 'Loading the latest forecast run'}>
        <div className="field-row">
          <label className="field">
            <span>Level</span>
            <select
              value={scopeLevel}
              onChange={(event) => {
                setScopeLevel(event.target.value);
                setScopeKey(event.target.value === 'national' ? 'NATIONAL' : '');
                setBranchFilter('');
                setSkuFilter('');
                setOrigin('');
              }}
            >
              {SCOPE_LEVELS.map((level) => (
                <option key={level} value={level}>
                  {level}
                </option>
              ))}
            </select>
          </label>
          {isSeries ? (
            <>
              <label className="field">
                <span>Location</span>
                <select
                  aria-label="Location"
                  value={branchFilter}
                  onChange={(event) => {
                    setBranchFilter(event.target.value);
                    setOrigin('');
                  }}
                >
                  <option value="">All locations</option>
                  {branchOptions.map((branch) => (
                    <option key={branch} value={branch}>
                      {branch}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span>SKU</span>
                <select
                  aria-label="SKU"
                  value={skuFilter}
                  onChange={(event) => {
                    setSkuFilter(event.target.value);
                    setOrigin('');
                  }}
                >
                  <option value="">All SKUs</option>
                  {skuOptions.map((sku) => (
                    <option key={sku} value={sku}>
                      {sku}
                    </option>
                  ))}
                </select>
              </label>
            </>
          ) : (
            <label className="field">
              <span>Scope</span>
              <select
                aria-label="Scope"
                value={scopeKey}
                onChange={(event) => setScopeKey(event.target.value)}
              >
                <option value="">Select…</option>
                {allScopes.map((scope) => (
                  <option key={scope.scope_key} value={scope.scope_key}>
                    {scope.scope_key}
                  </option>
                ))}
              </select>
            </label>
          )}
          <button
            type="button"
            className="btn btn-primary"
            onClick={download}
            disabled={!data || (view === 'validation' ? validationPoints.length === 0 : view === 'actual' ? history.length === 0 : forecasts.length === 0)}
          >
            <Icon name="download" size={16} /> Download CSV
          </button>
        </div>
        {run.isError && run.error instanceof ApiError && (
          <p className="hint">{run.error.message} {run.error.remediation}</p>
        )}
        {scopes.isError && <ErrorState error={scopes.error} onRetry={() => scopes.refetch()} />}
        {isSeries && (
          <p className="hint">
            {effectiveScopeKey ? (
              <>
                Showing <strong>{effectiveScopeKey}</strong>, resolved from the two
                slicers above.{' '}
              </>
            ) : (
              <>
                {matching.length} of {allScopes.length} trained series match. Narrow
                to one with both slicers.{' '}
              </>
            )}
            Only scopes a training run actually covered are listed — a branch or
            SKU the run did not reach does not appear here.
          </p>
        )}
        <p className="hint">CSV exports the selected chart view. Historical actuals retain source and censoring information.</p>
      </Card>

      {series.isPending && effectiveScopeKey && (
        <Card>
          <LoadingBlock rows={8} label="Loading forecast" />
        </Card>
      )}
      {!effectiveScopeKey && (
        <Card>
          <EmptyState title={isSeries ? 'Choose a location and a SKU' : 'Choose a scope'}>
            {isSeries
              ? 'The two slicers above narrow the trained series to one. Nothing here is populated with placeholder figures.'
              : 'Pick a level and a scope above. Nothing here is populated with placeholder figures.'}
          </EmptyState>
        </Card>
      )}
      {series.isError && (
        <Card>
          {series.error instanceof ApiError && series.error.status === 404 ? (
            <EmptyState title="No forecast for this scope">
              {series.error.message} {series.error.remediation}
            </EmptyState>
          ) : (
            <ErrorState error={series.error} onRetry={() => series.refetch()} />
          )}
        </Card>
      )}

      {data && (
        <>
          <div className="kpi-grid">
            <MetricCard label="Latest actual" value={formatInt(history[history.length - 1]?.actual)} note={history.length ? `${monthLabel(history[history.length - 1]!.period)} · units` : 'History unavailable'} />
            <MetricCard label="Next-month forecast" value={formatInt(forecasts[0]?.point_forecast)} note={forecasts[0] ? `${monthLabel(forecasts[0].period)} · reconciled units` : 'No forecast available'} tone="red" />
            <MetricCard label="Validation WAPE" value={data.validation_metrics?.wape == null ? '—' : `${data.validation_metrics.wape.toFixed(2)}%`} note="Out-of-sample error · lower is better" tone="teal" />
            <MetricCard label="Forecast coverage" value={`${forecasts.filter(f => f.point_forecast !== null).length} / ${forecasts.length}`} note="Horizons with available predictions" tone="gold" />
          </div>
          <Card
            title="Demand outlook"
            subtitle={`${scopeLevel} / ${effectiveScopeKey} · ${history.length} observed month(s) · ${forecasts.length} forecast month(s)`}
            actions={<span className="pill pill-info">{data.validation_metrics?.display_name ?? 'Model unavailable'}</span>}
          >
            <div className="chart-toolbar">
              <div className="segmented" role="group" aria-label="Chart view">
                {([['overview', 'Full timeline'], ['actual', 'Actual'], ['validation', 'Actual vs forecast'], ['forecast', 'Forecast']] as const).map(([id, label]) => <button key={id} type="button" aria-pressed={view === id} onClick={() => setView(id)}>{label}</button>)}
              </div>
              {view === 'actual' || view === 'overview' ? <label className="field"><span className="visually-hidden">History range</span><select aria-label="History range" value={range} onChange={e => setRange(Number(e.target.value))}><option value={0}>All history</option><option value={12}>Last 12 months</option><option value={6}>Last 6 months</option></select></label> : null}
              {view === 'validation' && origins.length > 0 && <label className="field"><span>Backtest origin</span><select value={selectedOrigin} onChange={e => setOrigin(e.target.value)}>{origins.map(o => <option key={o}>{o}</option>)}</select></label>}
              {(view === 'forecast' || view === 'overview') && <label className="check-row"><input type="checkbox" checked={quantiles} onChange={e => setQuantiles(e.target.checked)} />Show q80 / q90 / q95</label>}
            </div>
            {view !== 'validation' ? <DemandChart data={data} view={view} quantiles={quantiles} range={range} height={390} /> : diagnostics.isFetching ? <LoadingBlock rows={8} label="Loading backtest predictions" /> : diagnostics.isError ? <ErrorState error={diagnostics.error} onRetry={() => diagnostics.refetch()} /> : validationPoints.length ? <DemandChart data={data} view="validation" points={validationPoints} height={390} /> : <EmptyState title="No backtest predictions available">{diagnostics.data?.unavailable_reason ?? 'No stored validation predictions are available for the model used on this scope.'}</EmptyState>}
            <div className="legend-note"><span>{view === 'validation' ? 'Out-of-sample validation · one origin at a time · not fitted training values' : `Actuals through ${monthLabel(data.origin_period)} · future forecasts have no observed actuals yet`}</span><span>Drag the lower slider to zoom · click legend entries to compare</span></div>
            {(view === 'forecast' || view === 'overview') && quantiles && <p className="chart-note">q80, q90 and q95 are service-level demand quantities, not a symmetric confidence interval. Calibration method and residual counts are available in Forecast detail below.</p>}
            {data.history_unavailable_reason && (
              <p className="chart-note">{data.history_unavailable_reason}</p>
            )}
            {withoutInterval.length > 0 && (
              <p className="chart-note">
                {withoutInterval.length} horizon(s) have a point forecast but no
                interval: the calibration had too few out-of-sample residuals at
                any pooling level. The point is shown without a band rather than
                with a fabricated one.
              </p>
            )}
            <p className="chart-note">{data.snapshot_caveat}</p>
          </Card>

          {view === 'actual' && <Card title="Actual demand detail" subtitle="Historical quantities with their original source and censoring flag"><div className="table-scroll"><table className="data" data-testid="actual-table"><thead><tr><th>Month</th><th className="num">Actual units</th><th>Source</th><th>Censored</th></tr></thead><tbody>{(range ? history.slice(-range) : history).map(p => <tr key={p.period}><td>{monthLabel(p.period)}</td><td className="num">{formatInt(p.actual)}</td><td>{p.target_source ?? 'Not recorded'}</td><td>{p.is_censored ? 'Yes' : 'No'}</td></tr>)}</tbody></table></div></Card>}
          {view === 'validation' && validationPoints.length > 0 && <Card title="Actual vs forecast detail" subtitle={`Stored out-of-sample predictions · ${selectedOrigin}`}><div className="table-scroll"><table className="data" data-testid="backtest-table"><thead><tr><th>Month</th><th className="num">Horizon</th><th className="num">Actual</th><th className="num">Backtest forecast</th><th className="num">Residual</th></tr></thead><tbody>{validationPoints.map((p, i) => <tr key={`${p.period}-${p.horizon}-${i}`}><td>{monthLabel(p.period ?? '')}</td><td className="num">{p.horizon}</td><td className="num">{formatInt(p.actual)}</td><td className="num">{formatInt(p.predicted)}</td><td className="num">{formatInt(p.residual)}</td></tr>)}</tbody></table></div></Card>}

          <Card title="Forecast detail" subtitle="Point, q80, q90, q95, and the reconciliation adjustment kept separate from the number">
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
                    <th>Method</th>
                    <th>Interval from</th>
                    <th>Model</th>
                    <th>Source</th>
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
                      <td>{row.reconciliation_method ?? '—'}</td>
                      <td>
                        {row.quantile_method
                          ? `${row.quantile_method} · ${row.quantile_pooling_level} · ${formatInt(row.quantile_residual_count)} residuals`
                          : '—'}
                      </td>
                      <td>{row.model_display_name ?? row.model_id ?? '—'}</td>
                      <td>
                        {row.target_source ?? '—'}
                        {row.is_censored ? ' · censored' : ''}
                      </td>
                      <td>{row.unavailable_reason ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

          {data.validation_metrics && (
            <Card
              title="Validation metrics for the model used"
              subtitle="Measured out of sample on this scope, not on the forecast itself"
            >
              <div className="metric-row">
                {[
                  ['Model', data.validation_metrics.display_name],
                  ['WAPE %', data.validation_metrics.wape?.toFixed(3) ?? '—'],
                  ['MAE', formatInt(data.validation_metrics.mae)],
                  ['RMSE', formatInt(data.validation_metrics.rmse)],
                  ['MASE', data.validation_metrics.mase?.toFixed(3) ?? '—'],
                  ['Bias', data.validation_metrics.bias?.toFixed(2) ?? '—'],
                  ['Points', formatInt(data.validation_metrics.validation_points)],
                  ['Mode', data.validation_metrics.evaluation_mode ?? '—'],
                ].map(([label, value]) => (
                  <div className="metric" key={String(label)}>
                    <span className="metric-label">{label}</span>
                    <span className="metric-value">{value}</span>
                  </div>
                ))}
              </div>
            </Card>
          )}

          {data.drivers && (
            <Card title="Forecast drivers" subtitle="What the model was given, and what it resolved">
              <div className="table-scroll">
                <table className="data">
                  <tbody>
                    {Object.entries(data.drivers).map(([key, value]) => (
                      <tr key={key}>
                        <th style={{ textAlign: 'left', width: '28%' }}>
                          {key.replace(/_/g, ' ')}
                        </th>
                        <td className="mono">
                          {typeof value === 'object' && value !== null
                            ? JSON.stringify(value)
                            : String(value)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          )}
        </>
      )}
    </div>
  );
}

import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { fetchHealth, healthKeys } from '@/api/health';
import { fetchModelRegistry, modelKeys } from '@/api/models';
import { fetchCurrentForecastRun, fetchForecastRows, fetchSeriesForecast, forecastKeys } from '@/api/forecasts';
import { fetchLeaderboard, leaderboardKeys } from '@/api/leaderboard';
import { fetchCurrentRun, trainingKeys } from '@/api/training';
import { fetchSupplyOverview, inventoryKeys } from '@/api/inventory';
import { fetchCurrentPanel, panelKeys } from '@/api/panel';
import { Card } from '@/components/ui/Card';
import { EmptyState, ErrorState, LoadingBlock } from '@/components/ui/States';
import { HealthPill, StatusPill } from '@/components/ui/StatusPill';
import { formatInt } from '@/components/ui/format';
import { Icon } from '@/components/ui/Icon';
import { Chart, MetricCard, monthLabel, useChartColors } from '@/components/charts/Chart';
import { DemandChart } from '@/components/charts/DemandChart';

export function CommandCenterPage() {
  const c = useChartColors();
  const navigate = useNavigate();
  const [month, setMonth] = useState('');
  const health = useQuery({ queryKey: healthKeys.all, queryFn: fetchHealth });
  const registry = useQuery({ queryKey: modelKeys.registry, queryFn: fetchModelRegistry });
  const training = useQuery({ queryKey: trainingKeys.current, queryFn: fetchCurrentRun, retry: false });
  const boardQuery = { scope_level: 'national', scope_key: 'NATIONAL' };
  const board = useQuery({ queryKey: leaderboardKeys.board(boardQuery), queryFn: () => fetchLeaderboard(boardQuery), retry: false });
  const forecast = useQuery({ queryKey: forecastKeys.current, queryFn: fetchCurrentForecastRun, retry: false });
  const supply = useQuery({ queryKey: inventoryKeys.overview(undefined), queryFn: () => fetchSupplyOverview(undefined, 25), retry: false });
  const national = useQuery({ queryKey: forecastKeys.series('national', 'NATIONAL'), queryFn: () => fetchSeriesForecast('national', 'NATIONAL'), retry: false });
  const panel = useQuery({ queryKey: panelKeys.current, queryFn: fetchCurrentPanel, retry: false });
  const regionQuery = { scope_level: 'region', limit: 500 };
  const regions = useQuery({ queryKey: forecastKeys.rows(regionQuery), queryFn: () => fetchForecastRows(regionQuery), retry: false });
  const champion = board.data?.rows.find(r => r.is_champion);
  const forecasts = national.data?.forecasts ?? [];
  const period = forecasts.some(f => f.period === month) ? month : forecasts[0]?.period ?? '';
  const selectedForecast = forecasts.find(f => f.period === period);
  const regionRows = (regions.data?.items ?? []).filter(r => r.period === period).sort((a,b) => (b.point_forecast ?? -1) - (a.point_forecast ?? -1));
  const modelRows = (board.data?.rows ?? []).filter(r => r.wape !== null && r.ranked).sort((a,b) => a.wape! - b.wape!).slice(0, 6);
  const axis = { axisLine: { show: false }, axisTick: { show: false }, axisLabel: { color: c['ink-3'], fontSize: 11 }, splitLine: { lineStyle: { color: c.rule, type: 'dashed' } } };

  return <div className="stack">
    <div className="page-head page-head-row"><div><div className="eyebrow">Executive command center</div><h1>A clearer view of what’s next.</h1><p className="lede">Demand, model performance and inventory exposure — one connected view of the AIS network.</p><div className="page-context"><span>Consumer Glass Solutions</span><span>Branch × SKU × month</span>{forecast.data && <span>Origin {monthLabel(forecast.data.origin_period)}</span>}</div></div><Link to="/forecasts" className="btn btn-primary">Explore forecasts <Icon name="arrow" size={16} /></Link></div>

    <div className="kpi-grid">
      <MetricCard label="Next-month demand forecast" value={formatInt(forecasts[0]?.point_forecast)} note={forecasts[0] ? `${monthLabel(forecasts[0].period)} · national units` : 'Awaiting a completed forecast'} />
      <MetricCard label="National champion WAPE" value={champion?.wape == null ? '—' : `${champion.wape.toFixed(2)}%`} note={champion?.display_name ?? 'No champion selected'} tone="teal" />
      <MetricCard label="Dead / slow stock value" value={supply.data?.totals.dead_stock_value == null ? '—' : `₹${Intl.NumberFormat('en-IN', { notation: 'compact', maximumFractionDigits: 1 }).format(supply.data.totals.dead_stock_value)}`} note={supply.data ? `${formatInt(supply.data.totals.dead_or_slow_positions)} branch × SKU positions` : 'Awaiting stock snapshot'} tone="gold" />
      <MetricCard label="Zero stock, live demand" value={formatInt(supply.data?.totals.zero_stock_live_demand_positions)} note="Positions requiring a placement review" tone="red" />
    </div>

    <div className="insight-grid">
      <Card title="Demand performance & outlook" subtitle="Historical actuals and the next six forecast horizons" actions={<Link className="text-link" to="/forecasts">Open explorer <Icon name="arrow" size={14} /></Link>}>
        {national.isPending && <LoadingBlock rows={8} label="Loading demand history" />}
        {national.isError && <ErrorState error={national.error} onRetry={() => national.refetch()} />}
        {national.data && <><DemandChart data={national.data} quantiles={false} height={325} /><div className="insight-footer"><span>Ordered demand · units</span><span>Dashed line = future forecast</span></div></>}
      </Card>
      <Card title="Planning pulse" subtitle="What deserves your attention">
        <div className="mini-heading">Model confidence</div>
        <div className="stat-list"><div><span>Champion error</span><strong>{champion?.wape == null ? '—' : `${champion.wape.toFixed(2)}%`}</strong></div><div><span>Best baseline error</span><strong>{board.data?.best_baseline_wape == null ? '—' : `${board.data.best_baseline_wape.toFixed(2)}%`}</strong></div><div><span>Official models</span><strong>{registry.data?.official_model_count ?? '—'}</strong></div><div><span>Panel series</span><strong>{formatInt(panel.data?.series_count)}</strong></div><div><span>History window</span><strong>{panel.data ? `${panel.data.period_count} months` : '—'}</strong></div><div><span>Stock snapshot</span><strong>{supply.data?.stock_snapshot_date ?? '—'}</strong></div></div>
        {board.data && <div className={`callout ${board.data.beaten_by_baseline ? 'warn' : ''}`} style={{ marginTop: 18 }}><div className="h">{board.data.beaten_by_baseline ? 'Baseline outperforms champion' : 'Champion leads the national baseline'}</div><p>{board.data.beaten_by_baseline ? 'Review the baseline before committing to this model.' : 'National performance is not a guarantee at every branch. Review the scope-level leaderboard.'}</p></div>}
      </Card>
    </div>

    <div className="grid-2">
      <Card title="Regional demand outlook" subtitle="Reconciled point forecast · select a bar to explore the region" actions={<label className="field" style={{ margin: 0 }}><span className="visually-hidden">Forecast month</span><select aria-label="Forecast month" value={period} onChange={e => setMonth(e.target.value)}>{forecasts.map(f => <option key={f.period} value={f.period}>{monthLabel(f.period)}</option>)}</select></label>}>
        {regions.isPending && <LoadingBlock rows={5} label="Loading regional forecasts" />}{regions.isError && <ErrorState error={regions.error} onRetry={() => regions.refetch()} />}
        {regionRows.length > 0 ? <Chart label="Regional forecast units for the selected month; bars open regional Forecast Explorer" height={280} onEvents={{ click: p => navigate(`/forecasts?level=region&scope=${encodeURIComponent(p.name)}`) }} option={{ grid: { left: 100, right: 40, top: 15, bottom: 36 }, xAxis: { ...axis, type: 'value', name: 'Units', nameLocation: 'middle', nameGap: 25, axisLabel: { color: c['ink-3'], formatter: (v: number) => Intl.NumberFormat('en', { notation: 'compact' }).format(v) } }, yAxis: { ...axis, type: 'category', inverse: true, data: regionRows.map(r => r.scope_key), splitLine: { show: false } }, series: [{ name: 'Forecast units', type: 'bar', barMaxWidth: 19, data: regionRows.map(r => r.point_forecast), itemStyle: { color: c.s1, borderRadius: [0, 4, 4, 0] } }] }} /> : !regions.isPending && !regions.isError && <EmptyState title="No regional forecasts">Complete a forecast run to see the regional split.</EmptyState>}
        <div className="insight-footer"><span>{selectedForecast ? `National total: ${formatInt(selectedForecast.point_forecast)} units` : 'No national total available'}</span><Link className="text-link" to="/forecasts">View hierarchy <Icon name="arrow" size={13} /></Link></div>
      </Card>
      <Card title="Model performance benchmark" subtitle="National scope · top six ranked entries · lower WAPE is better" actions={<Link to="/leaderboard" className="text-link">All models <Icon name="arrow" size={14} /></Link>}>
        {board.isPending && <LoadingBlock rows={5} label="Loading model benchmark" />}{board.isError && <ErrorState error={board.error} onRetry={() => board.refetch()} />}
        {modelRows.length > 0 && <Chart label="Top ranked national model WAPE percentages, baseline comparisons included" height={280} option={{ grid: { left: 155, right: 55, top: 15, bottom: 36 }, xAxis: { ...axis, type: 'value', name: 'WAPE %', nameLocation: 'middle', nameGap: 25, axisLabel: { color: c['ink-3'], formatter: '{value}%' } }, yAxis: { ...axis, type: 'category', inverse: true, data: modelRows.map(r => r.display_name), axisLabel: { color: c['ink-2'], width: 140, overflow: 'truncate', fontSize: 10 }, splitLine: { show: false } }, series: [{ name: 'WAPE %', type: 'bar', barMaxWidth: 19, data: modelRows.map(r => ({ value: r.wape, itemStyle: { color: r.is_champion ? c.s3 : r.is_baseline ? c.s4 : c.s1 } })), itemStyle: { borderRadius: [0,4,4,0] }, label: { show: true, position: 'right', color: c['ink-2'], formatter: (p: { value: number }) => `${p.value.toFixed(2)}%`, fontSize: 10 } }] }} />}
        <div className="insight-footer"><span>Teal: champion · amber: baseline · blue: registered model</span><span>{board.data ? `${board.data.excluded_count} excluded with reasons` : 'Awaiting evaluation'}</span></div>
      </Card>
    </div>

    <div className="insight-banner"><Icon name="overview" /><p><strong>Demand, not just dispatch.</strong> Forecasts target <strong>ordered quantity</strong>. Units never despatched represent unmet demand, not an absence of demand. Sales-proxy history remains explicitly labelled in the Explorer.</p></div>

    <Card title="From source to decision" subtitle="Current pipeline state · existing runs are preserved" actions={<Link to="/monitoring" className="text-link">Open monitoring <Icon name="arrow" size={14} /></Link>}><div className="pipeline-steps"><div className="pipeline-step"><strong>01 / Prepare data</strong>{panel.data ? <><StatusPill status={panel.data.status} /><p>{formatInt(panel.data.panel_rows)} panel rows across {formatInt(panel.data.series_count)} series.</p></> : <p>{panel.isError ? 'Panel unavailable. Review Mapping & Validation.' : 'Checking the modelling panel…'}</p>}<Link to="/data-studio" className="text-link">Data Studio</Link></div><div className="pipeline-step"><strong>02 / Evaluate models</strong>{training.data ? <><StatusPill status={training.data.status} /><p>{formatInt(training.data.model_runs_completed)} completed · {formatInt(training.data.model_runs_ineligible)} ineligible · {formatInt(training.data.model_runs_failed)} failed · {formatInt(training.data.model_runs_timed_out)} timed out · {formatInt(training.data.model_runs_not_evaluated)} not evaluated (budget).</p></> : <p>{training.isError ? 'No training state available.' : 'Checking training…'}</p>}<Link to="/training" className="text-link">Training Center</Link></div><div className="pipeline-step"><strong>03 / Plan demand</strong>{forecast.data ? <><StatusPill status={forecast.data.status} /><p>{formatInt(forecast.data.rows_written)} forecast rows · {formatInt(forecast.data.rows_unavailable)} unavailable. Hierarchy: {forecast.data.coherent ? 'coherent at the reconciliation base level' : 'requires review'}.</p></> : <p>{forecast.isError ? 'No forecast state available.' : 'Checking forecasts…'}</p>}<Link to="/supply" className="text-link">Supply Intelligence</Link></div></div></Card>

    <details className="audit-details"><summary>Service health & technical provenance</summary><div>{health.isPending && <LoadingBlock rows={3} label="Checking service health" />}{health.isError && <ErrorState error={health.error} onRetry={() => health.refetch()} />}{health.data && <div className="table-scroll"><table className="data"><thead><tr><th>Component</th><th>Status</th><th>Detail</th></tr></thead><tbody>{health.data.components.map(component => <tr key={component.name}><td>{component.name}</td><td><HealthPill status={component.status} /></td><td>{component.detail ?? '—'}</td></tr>)}</tbody></table></div>}{registry.isError && <ErrorState error={registry.error} onRetry={() => registry.refetch()} />}<p className="hint">Values are read from the API. Empty or failed stages remain unavailable, never zero-filled. Stock values are snapshot estimates, not real-time balances.</p></div></details>
  </div>;
}

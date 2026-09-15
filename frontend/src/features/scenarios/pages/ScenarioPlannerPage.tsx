/**
 * Scenario Planner.
 *
 * A scenario is a transformation of a stored forecast, and this page says so
 * out loud: the baseline is read-only, the levers are shown beside their
 * baseline values, and a scope with no baseline forecast stays in the table
 * with its reason rather than being scaled from nothing.
 *
 * All arithmetic is the API's. This page sends three scalars and renders the
 * comparison it gets back.
 */
import { useState } from 'react';
import { ComparisonBars } from '@/components/charts/ComparisonBars';
import { useMutation } from '@tanstack/react-query';
import { ApiError } from '@/api/client';
import { evaluateScenario } from '@/api/operations';
import { Card } from '@/components/ui/Card';
import { EmptyState, ErrorState, LoadingBlock } from '@/components/ui/States';
import { formatDays, formatInt } from '@/components/ui/format';
import type { ScenarioResponse } from '@/types/operations';

const SERVICE_LEVELS = [80, 90, 95] as const;
const SCOPE_LEVELS = ['branch', 'region', 'national', 'series'] as const;

function delta(value: number | null): string {
  if (value === null) return '—';
  const sign = value > 0 ? '+' : '';
  return `${sign}${value.toFixed(1)}%`;
}

export function ScenarioPlannerPage() {
  const [name, setName] = useState('Peak season');
  const [multiplier, setMultiplier] = useState(1.2);
  const [serviceLevel, setServiceLevel] = useState(95);
  const [leadTime, setLeadTime] = useState<string>('');
  const [scopeLevel, setScopeLevel] = useState<string>('branch');

  const run = useMutation<ScenarioResponse, unknown>({
    mutationFn: () =>
      evaluateScenario({
        name,
        demand_multiplier: multiplier,
        service_level: serviceLevel,
        lead_time_days: leadTime === '' ? null : Number(leadTime),
        scope_level: scopeLevel,
        limit: 120,
      }),
  });

  const data = run.data;

  return (
    <div className="stack">
      <div className="page-head">
        <div className="eyebrow">08 &middot; Scenario planner</div>
        <h1>Scenario Planner</h1>
        <p className="lede">
          What a change in demand, service level or lead time would imply for
          the order position. The baseline forecast is{' '}
          <strong>read-only</strong> &mdash; a scenario is computed on top of it
          and never written back over it.
        </p>
      </div>

      <Card title="Levers" subtitle="Three scalars; the API does the arithmetic">
        <div className="field-row">
          <label className="field">
            <span>Scenario name</span>
            <input value={name} onChange={(event) => setName(event.target.value)} />
          </label>
          <label className="field">
            <span>Demand multiplier</span>
            <input
              type="number"
              step={0.05}
              min={0.1}
              max={5}
              value={multiplier}
              onChange={(event) => setMultiplier(Number(event.target.value) || 1)}
            />
            <span className="hint">
              Scales the point forecast and its quantiles together. It does not
              re-fit any model, so it cannot tell you whether the scaled demand
              is plausible &mdash; only what it would imply.
            </span>
          </label>
          <label className="field">
            <span>Service level</span>
            <select
              value={serviceLevel}
              onChange={(event) => setServiceLevel(Number(event.target.value))}
            >
              {SERVICE_LEVELS.map((level) => (
                <option key={level} value={level}>
                  q{level}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Lead time (days)</span>
            <input
              type="number"
              min={0}
              value={leadTime}
              placeholder="baseline"
              onChange={(event) => setLeadTime(event.target.value)}
            />
            <span className="hint">
              Blank uses the baseline lead time. Changing it affects the order
              quantity without touching the forecast.
            </span>
          </label>
          <label className="field">
            <span>Level</span>
            <select
              value={scopeLevel}
              onChange={(event) => setScopeLevel(event.target.value)}
            >
              {SCOPE_LEVELS.map((level) => (
                <option key={level} value={level}>
                  {level}
                </option>
              ))}
            </select>
          </label>
        </div>
        <div className="actions">
          <button
            type="button"
            className="btn btn-primary"
            disabled={run.isPending}
            onClick={() => run.mutate()}
          >
            {run.isPending ? 'Evaluating…' : 'Evaluate scenario'}
          </button>
        </div>
      </Card>

      {run.isPending && (
        <Card>
          <LoadingBlock rows={4} label="Evaluating scenario" />
        </Card>
      )}
      {run.isError && (
        <Card>
          {run.error instanceof ApiError && run.error.status === 404 ? (
            <EmptyState title="No baseline to build on">
              {run.error.message} {run.error.remediation}
            </EmptyState>
          ) : (
            <ErrorState error={run.error} onRetry={() => run.mutate()} />
          )}
        </Card>
      )}
      {!data && !run.isPending && !run.isError && (
        <Card>
          <EmptyState title="No scenario evaluated yet">
            Set the levers above and evaluate. Nothing is shown until the API
            has computed a real comparison against a stored forecast.
          </EmptyState>
        </Card>
      )}

      {data && (
        <>
          <Card
            title={`${data.name} versus baseline`}
            subtitle={`Baseline forecast run ${data.baseline_forecast_run_id.slice(0, 8)} · origin ${data.baseline_origin_period}`}
          >
            <div className="tiles">
              <div className="tile">
                <div className="k">Baseline demand</div>
                <div className="v">{formatInt(data.totals.baseline_demand)}</div>
                <div className="s">units across {data.rows_returned} row(s)</div>
              </div>
              <div className="tile">
                <div className="k">Scenario demand</div>
                <div className="v">{formatInt(data.totals.scenario_demand)}</div>
                <div className="s">{delta(data.totals.demand_delta_pct)}</div>
              </div>
              <div className="tile">
                <div className="k">Baseline order</div>
                <div className="v">
                  {formatInt(data.totals.baseline_order_quantity)}
                </div>
                <div className="s">
                  q{data.levers.service_level} ·{' '}
                  {formatDays(data.levers.baseline_lead_time_days)} lead
                </div>
              </div>
              <div
                className={
                  (data.totals.order_delta_pct ?? 0) > 0 ? 'tile is-warn' : 'tile'
                }
              >
                <div className="k">Scenario order</div>
                <div className="v">
                  {formatInt(data.totals.scenario_order_quantity)}
                </div>
                <div className="s">{delta(data.totals.order_delta_pct)}</div>
              </div>
            </div>

            <div className="metric-row">
              <div className="metric">
                <span className="metric-label">Demand multiplier</span>
                <span className="metric-value">
                  &times;{data.levers.demand_multiplier}
                </span>
              </div>
              <div className="metric">
                <span className="metric-label">Service level</span>
                <span className="metric-value">q{data.levers.service_level}</span>
              </div>
              <div className="metric">
                <span className="metric-label">Lead time</span>
                <span className="metric-value">
                  {formatDays(
                    data.levers.lead_time_days ?? data.levers.baseline_lead_time_days,
                  )}
                </span>
              </div>
              <div className="metric">
                <span className="metric-label">Review period</span>
                <span className="metric-value">
                  {formatDays(data.levers.review_period_days)}
                </span>
              </div>
            </div>

            {data.rows_without_baseline > 0 && (
              <div className="callout warn">
                <p>
                  {data.rows_without_baseline} row(s) have no baseline forecast,
                  so nothing was scaled for them. A scenario cannot invent a
                  forecast that does not exist.
                </p>
              </div>
            )}
          </Card>

          <Card title="Scenario impact" subtitle="Stored baseline compared with API-calculated scenario totals"><ComparisonBars labels={['Demand quantity', 'Order quantity']} series={[{ name: 'Baseline', values: [data.totals.baseline_demand, data.totals.baseline_order_quantity] }, { name: data.name, values: [data.totals.scenario_demand, data.totals.scenario_order_quantity] }]} /><p className="chart-note">Totals cover the {data.rows_returned} returned rows only. This is a what-if transformation, not a new trained forecast.</p></Card>
          <Card title="Row detail" subtitle="Baseline beside scenario, per period">
            <div className="table-scroll">
              <table className="data" data-testid="scenario-table">
                <thead>
                  <tr>
                    <th>Scope</th>
                    <th>Period</th>
                    <th className="num">h</th>
                    <th className="num">Baseline point</th>
                    <th className="num">Scenario point</th>
                    <th className="num">Baseline q{data.levers.service_level}</th>
                    <th className="num">Scenario q{data.levers.service_level}</th>
                    <th className="num">Baseline order</th>
                    <th className="num">Scenario order</th>
                    <th>Reason</th>
                  </tr>
                </thead>
                <tbody>
                  {data.rows.map((row) => (
                    <tr key={`${row.scope_key}-${row.period}`}>
                      <td className="mono">{row.scope_key}</td>
                      <td className="mono">{row.period}</td>
                      <td className="num">{row.horizon}</td>
                      <td className="num">{formatInt(row.baseline_point)}</td>
                      <td className="num">{formatInt(row.scenario_point)}</td>
                      <td className="num">{formatInt(row.baseline_quantile)}</td>
                      <td className="num">{formatInt(row.scenario_quantile)}</td>
                      <td className="num">
                        {formatInt(row.baseline_recommended_order)}
                      </td>
                      <td className="num">
                        {formatInt(row.scenario_recommended_order)}
                      </td>
                      <td>{row.unavailable_reason ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

          <Card title="What this comparison does and does not say">
            <ul>
              {data.caveats.map((caveat) => (
                <li key={caveat} style={{ marginBottom: 6 }}>
                  {caveat}
                </li>
              ))}
            </ul>
          </Card>
        </>
      )}
    </div>
  );
}

/**
 * Data & Model Monitoring.
 *
 * The rule this page is built around: **"not measured" renders differently
 * from "measured, and fine"**. Error deterioration on this dataset cannot be
 * computed at all — the forecast origin is the last observed month — and the
 * page shows the API's reason rather than a green tick or a zero. A zero here
 * would assert that the champion is holding up when nothing has been checked.
 *
 * No thresholds are applied. Each measure arrives with its window and its
 * counts, and the reader applies their own judgement.
 */
import { useQuery } from '@tanstack/react-query';
import { ComparisonBars } from '@/components/charts/ComparisonBars';
import { fetchMonitoring, operationsKeys } from '@/api/operations';
import { Card } from '@/components/ui/Card';
import { EmptyState, ErrorState, LoadingBlock } from '@/components/ui/States';
import { formatInt } from '@/components/ui/format';

function pct(value: number | null | undefined, digits = 1): string {
  return value === null || value === undefined ? '—' : `${value.toFixed(digits)}%`;
}

export function MonitoringPage() {
  const { data, isPending, isError, error, refetch } = useQuery({
    queryKey: operationsKeys.monitoring,
    queryFn: fetchMonitoring,
    retry: false,
  });

  return (
    <div className="stack">
      <div className="page-head">
        <div className="eyebrow">09 &middot; Data &amp; model monitoring</div>
        <h1>Data &amp; Model Monitoring</h1>
        <p className="lede">
          Freshness, input drift, champion age and error deterioration. Nothing
          here raises an alert: each measure arrives with its window and its
          counts so you apply your own threshold, and a measure that could not
          be computed says so rather than reporting zero.
        </p>
      </div>

      {isPending && (
        <Card>
          <LoadingBlock rows={6} label="Loading monitoring snapshot" />
        </Card>
      )}
      {isError && (
        <Card>
          <ErrorState error={error} onRetry={() => refetch()} />
        </Card>
      )}

      {data && (
        <>
          <Card title="Data freshness" subtitle="Demand history and stock are reported separately, because they do not end at the same month">
            <div className="tiles">
              <div className="tile">
                <div className="k">Demand history ends</div>
                <div className="v">{data.freshness.demand_history_end ?? '—'}</div>
                <div className="s">
                  {data.freshness.demand_history_age_months === null
                    ? 'age unknown'
                    : `${data.freshness.demand_history_age_months} month(s) old`}
                </div>
              </div>
              <div className="tile">
                <div className="k">Stock snapshot</div>
                <div className="v">{data.freshness.stock_snapshot_date}</div>
                <div className="s">
                  {data.freshness.stock_snapshot_age_months === null
                    ? 'age unknown'
                    : `${data.freshness.stock_snapshot_age_months} month(s) old`}
                </div>
              </div>
              <div className="tile">
                <div className="k">Panel rows</div>
                <div className="v">{formatInt(data.freshness.panel_rows)}</div>
                <div className="s">
                  built{' '}
                  {data.freshness.panel_built_at
                    ? new Date(data.freshness.panel_built_at).toLocaleDateString()
                    : '—'}
                </div>
              </div>
            </div>
            <div className="callout">
              <p>{data.freshness.note}</p>
            </div>
          </Card>

          <Card
            title="Input drift"
            subtitle={
              data.drift.available
                ? `Last ${data.drift.window_months} month(s) against the earlier history`
                : 'Not measurable'
            }
          >
            {!data.drift.available && (
              <EmptyState title="Drift could not be measured">
                {data.drift.reason}
              </EmptyState>
            )}
            {data.drift.available && data.drift.national && (
              <>
                <div className="metric-row">
                  <div className="metric">
                    <span className="metric-label">Earlier mean / month</span>
                    <span className="metric-value">
                      {formatInt(data.drift.national.earlier.mean_monthly_demand)}
                    </span>
                  </div>
                  <div className="metric">
                    <span className="metric-label">Recent mean / month</span>
                    <span className="metric-value">
                      {formatInt(data.drift.national.recent.mean_monthly_demand)}
                    </span>
                  </div>
                  <div className="metric">
                    <span className="metric-label">Shift</span>
                    <span className="metric-value">
                      {pct(data.drift.national.shift_pct)}
                    </span>
                  </div>
                  <div className="metric">
                    <span className="metric-label">Months compared</span>
                    <span className="metric-value">
                      {data.drift.national.earlier.months} vs{' '}
                      {data.drift.national.recent.months}
                    </span>
                  </div>
                </div>

                {data.drift.target_source_changed && (
                  <div className="callout warn">
                    <div className="h">Part of this shift is a change of measurement</div>
                    <p>
                      The target source differs between the two windows:{' '}
                      {data.drift.target_sources_earlier.join(', ')} then{' '}
                      {data.drift.target_sources_recent.join(', ')}. A shift
                      across that boundary is partly a change in what is being
                      measured, not only in demand.
                    </p>
                  </div>
                )}

                <ComparisonBars labels={['National mean / month']} series={[{ name: 'Earlier history', values: [data.drift.national.earlier.mean_monthly_demand] }, { name: 'Recent history', values: [data.drift.national.recent.mean_monthly_demand] }]} />

                {data.drift.rows.length > 0 && (
                  <div className="table-scroll">
                    <table className="data" data-testid="drift-table">
                      <thead>
                        <tr>
                          <th>Scope</th>
                          <th className="num">Earlier mean</th>
                          <th className="num">Recent mean</th>
                          <th className="num">Shift</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.drift.rows.map((row) => (
                          <tr key={`${row.scope_level}-${row.scope_key}`}>
                            <td>{row.scope_key}</td>
                            <td className="num">
                              {formatInt(row.earlier_mean_monthly_demand)}
                            </td>
                            <td className="num">
                              {formatInt(row.recent_mean_monthly_demand)}
                            </td>
                            <td className="num">{pct(row.shift_pct)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
                {data.drift.note && <p className="hint">{data.drift.note}</p>}
              </>
            )}
          </Card>

          <Card
            title="Champion age"
            subtitle={`${data.champions.active_champions} active selection(s)`}
          >
            <div className="tiles">
              <div className="tile">
                <div className="k">Active champions</div>
                <div className="v">{formatInt(data.champions.active_champions)}</div>
                <div className="s">one per scope</div>
              </div>
              <div
                className={
                  data.champions.champions_from_older_runs > 0
                    ? 'tile is-warn'
                    : 'tile is-ok'
                }
              >
                <div className="k">From an older run</div>
                <div className="v">
                  {formatInt(data.champions.champions_from_older_runs)}
                </div>
                <div className="s">newer training exists</div>
              </div>
              <div
                className={
                  data.champions.champions_beaten_by_a_baseline > 0
                    ? 'tile is-crit'
                    : 'tile is-ok'
                }
              >
                <div className="k">Beaten by a baseline</div>
                <div className="v">
                  {formatInt(data.champions.champions_beaten_by_a_baseline)}
                </div>
                <div className="s">in their own scope</div>
              </div>
            </div>
            <div className="callout">
              <p>{data.champions.note}</p>
            </div>
            {data.champions.rows.length > 0 && (
              <div className="table-scroll">
                <table className="data" data-testid="champion-age-table">
                  <thead>
                    <tr>
                      <th>Scope</th>
                      <th>Champion</th>
                      <th>Source</th>
                      <th className="num">Age (days)</th>
                      <th>From newest run</th>
                      <th>Beaten by baseline</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.champions.rows.slice(0, 40).map((row) => (
                      <tr key={`${row.scope_kind}-${row.scope_key}`}>
                        <td className="mono">
                          {row.scope_kind}/{row.scope_key}
                        </td>
                        <td>{row.champion_model_id}</td>
                        <td>{row.selection_source}</td>
                        <td className="num">
                          {row.age_days === null ? '—' : row.age_days.toFixed(1)}
                        </td>
                        <td>{row.from_newest_training_run ? 'Yes' : 'No'}</td>
                        <td>{row.beaten_by_baseline ? 'Yes' : 'No'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>

          <Card
            title="Error deterioration"
            subtitle={
              data.deterioration.computable
                ? `Measured on ${data.deterioration.observed_forecast_periods.length} observed forecast month(s)`
                : 'Not yet computable'
            }
          >
            {!data.deterioration.computable && (
              <EmptyState title="This has not been checked yet">
                {data.deterioration.reason}
              </EmptyState>
            )}
            {data.deterioration.computable && (
              <>
                <div className="table-scroll">
                  <table className="data" data-testid="deterioration-table">
                    <thead>
                      <tr>
                        <th>Scope</th>
                        <th>Period</th>
                        <th>Model</th>
                        <th className="num">Actual</th>
                        <th className="num">Forecast</th>
                        <th className="num">Accrued WAPE</th>
                        <th className="num">Backtest WAPE</th>
                        <th className="num">Deterioration</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.deterioration.rows.slice(0, 40).map((row) => (
                        <tr key={`${row.scope_key}-${row.period}`}>
                          <td>{row.scope_key}</td>
                          <td className="mono">{row.period}</td>
                          <td>{row.model_id ?? '—'}</td>
                          <td className="num">{formatInt(row.actual)}</td>
                          <td className="num">{formatInt(row.point_forecast)}</td>
                          <td className="num">{pct(row.accrued_wape, 2)}</td>
                          <td className="num">{pct(row.backtest_wape, 2)}</td>
                          <td className="num">{pct(row.deterioration_pct, 2)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {data.deterioration.note && (
                  <p className="hint">{data.deterioration.note}</p>
                )}
              </>
            )}
          </Card>

          <div className="callout">
            <p>{data.note}</p>
          </div>
        </>
      )}
    </div>
  );
}

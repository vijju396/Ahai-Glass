/**
 * Forecasting — one branch × SKU at a time, and independent by construction.
 *
 * The independence is the point, so the page states it and then shows it:
 * every series is evaluated, has its champion chosen, and is forecast on its
 * own. Two SKUs at the same branch can and do end up with different models,
 * and this page names the model and the measured error for whichever series
 * you selected rather than a single headline accuracy.
 *
 * There is no "All locations" and no "All SKUs". Both used to resolve to a
 * real forecast — the national and per-branch *aggregate* scopes — and both
 * were removed on request, because an aggregate is a separate model fitted to
 * summed demand and its error transfers to nothing underneath it. On this run
 * the national scope reported 169.87% MAPE while the median line was 10.45%
 * over the six-month total; the first number described a weekly national sum
 * and was read as the accuracy of the forecast. The aggregates are still
 * fitted — MinT reconciliation needs the hierarchy to make the lines add up —
 * they are simply not a thing this page will show you (D-133).
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
import { useEffect, useMemo, useState } from 'react';
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
import { DemandChart } from '@/components/charts/DemandChart';
import { useLinesAtTarget } from '@/features/training-race/useLinesAtTarget';
import { MarkedSelect } from '@/components/ui/MarkedSelect';
import { monthLabel } from '@/components/charts/Chart';
import { ApiError } from '@/api/client';
import { fetchCurrentForecastRun, fetchSeriesForecast, forecastKeys } from '@/api/forecasts';
import { periodNounOne } from '@/app/period';
import { firstPair, repair } from '@/app/seriesPair';
import { LineSummaryTiles } from '@/features/line-summary/LineSummaryTiles';
import { fetchScopes, leaderboardKeys } from '@/api/leaderboard';
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
import { Explain } from '@/components/ui/Explain';

const SELECT =
  'rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-2.5 py-1.5 text-xs text-[var(--color-text)]';



/**
 * The chart draws one thing: what actually happened, then what we forecast
 * happens next. It used to carry three more layers behind a view switch —
 * backtest-versus-actual, and the q80/q90/q95 service-level bands — which
 * answer how the error was *measured* rather than what the forecast *is*, and
 * put four lines in front of someone reading for one. The per-horizon
 * provenance table went with them, for the same reason: reconciliation
 * adjustments and interval-calibration pooling levels are how the number was
 * built, not what the number says.
 *
 * The forecast itself is unchanged — the quantiles, the adjustments and the
 * calibration are all still computed and still served by the API; this page
 * simply no longer puts them on screen. The measured error stays, as the tile
 * and the panel beneath the chart, because that is what someone asks next.
 */
const CHART_NOTE =
  'Observed demand through the forecast origin, then the six forecast months. The shaded stretch is the forecast; everything left of it is what actually happened.';

function splitSeries(id: string): { branch: string; sku: string } | null {
  const cut = id.indexOf('|');
  if (cut <= 0 || cut === id.length - 1) return null;
  return { branch: id.slice(0, cut), sku: id.slice(cut + 1) };
}

export function ForecastingPage() {
  const [branch, setBranch] = useState('');
  const [sku, setSku] = useState('');
  const [range, setRange] = useState(0);

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
        return parts ? [{ key: s.scope_key, ...parts }] : [];
      }),
    [scopes.data],
  );

  /* The page opens on a line rather than on nothing. Every location is offered
     whatever the SKU says, because picking one now *moves* the SKU rather than
     filtering it away — a list that shrank as you chose would hide locations
     that are perfectly selectable. */
  useEffect(() => {
    if (branch || parsed.length === 0) return;
    const start = firstPair(parsed);
    setBranch(start.branch);
    setSku(start.sku);
  }, [parsed, branch]);

  const branchOptions = useMemo(
    () => [...new Set(parsed.map((r) => r.branch))].sort(),
    [parsed],
  );
  const skuOptions = useMemo(
    () => [...new Set(parsed.filter((r) => r.branch === branch).map((r) => r.sku))].sort(),
    [parsed, branch],
  );

  /* Changing either slicer repairs the other, so the pair always names a line
     the run trained. Picking a location whose SKU list does not include the
     current one lands on that location's first SKU (D-133). */
  const pick = (next: { branch: string; sku: string }, changed: 'branch' | 'sku') => {
    const fixed = repair(parsed, next, changed);
    setBranch(fixed.branch);
    setSku(fixed.sku);
  };

  /* A small green dot trails an option whose lines *all* clear 85% accuracy on their
     own, narrowed by whatever the other slicer already says. "All" rather than
     "any": with no location picked a SKU carries one line per branch, and a dot
     meaning "strong somewhere" would walk a demo into a branch that is not. */
  const atTarget = useLinesAtTarget();
  const strong = useMemo(() => {
    const mark = (candidates: { key: string }[]) =>
      candidates.length > 0 && candidates.every((r) => atTarget.has(r.key));
    return {
      branch: (b: string) => mark(parsed.filter((r) => r.branch === b)),
      sku: (s: string) => mark(parsed.filter((r) => r.sku === s && r.branch === branch)),
    };
  }, [parsed, atTarget, branch]);

  /** The line the current selection addresses — always a series, never an
   *  aggregate.
   *
   *  The page used to also resolve "All locations" to the **national** scope
   *  and "one location / All SKUs" to that **branch** scope. Both are real
   *  forecasts, but they are separately fitted models over *summed* demand,
   *  and their error is not the error of anything underneath them: the
   *  national scope on this run reports 169.87% MAPE against 10.45% for the
   *  median line over the same horizon, because weekly national demand is
   *  volatile and MAPE punishes small denominators. Showing that number
   *  beside a model name invited exactly one reading — "the forecast is 170%
   *  wrong" — and it was never true of any line a planner orders against.
   *  Both aggregate levels are gone from the picker; they are still fitted,
   *  because MinT reconciliation needs the hierarchy to make the lines add up
   *  (D-133). */
  const resolved = useMemo((): { key: string; label: string } | null => {
    if (!branch || !sku) return null;
    const hit = parsed.find((r) => r.branch === branch && r.sku === sku);
    return hit ? { key: hit.key, label: `${branch} × ${sku}` } : null;
  }, [branch, sku, parsed]);

  const scopeKey = resolved?.key ?? '';

  const series = useQuery({
    queryKey: forecastKeys.series('series', scopeKey),
    queryFn: () => fetchSeriesForecast('series', scopeKey),
    enabled: Boolean(scopeKey),
    retry: false,
  });

  const drift = useQuery({
    queryKey: driftKeys.scope(branch || undefined, sku || undefined),
    queryFn: () => fetchDrift(branch || undefined, sku || undefined),
    retry: false,
  });

  const data = series.data;
  const forecasts = data?.forecasts ?? [];
  const metrics = data?.validation_metrics;
  // The roll-up is only worth a panel when a period is not already a month.
  const rollup = data?.panel_grain === 'weekly' ? (data?.monthly_rollup ?? []) : [];
  // A "sum of children" aggregate carries no prediction interval of its own,
  // and the API returns the point forecast in the quantile fields rather than
  // null. Three columns repeating the point forecast read as a band that was
  // measured; they are dropped instead, with the reason shown.
  const rollupHasBand = rollup.some(
    (m) => m.q95 != null && m.q95 !== m.point_forecast,
  );

  return (
    <div className="flex flex-col gap-4">
      <header>
        <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[var(--color-primary)]">
          Forecasting
        </p>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight text-[var(--color-text)]">
          Six months ahead, per branch and SKU.
        </h1>
        <Explain label="About this page" variant="note">
          Every series is validated, has its champion chosen, and is forecast{' '}
          <strong>independently</strong>. Two SKUs at the same branch routinely end up with
          different models, so the model and the measured error shown below belong to the
          series you selected — there is no single headline accuracy.
        </Explain>
      </header>

      <ScopeBanner scope={filters.data?.workspace_scope} />

      <Card>
        <div className="flex flex-wrap items-end gap-2.5">
          <label className="inline-flex flex-col gap-0.5">
            <span className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--color-text-muted)]">
              Location
            </span>
            <MarkedSelect
              label="Location"
              className={SELECT}
              value={branch}
              onChange={(next) => pick({ branch: next, sku }, 'branch')}
              options={branchOptions.map((b) => ({
                value: b,
                label: b,
                marked: strong.branch(b),
              }))}
            />
          </label>
          <label className="inline-flex flex-col gap-0.5">
            <span className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--color-text-muted)]">
              SKU
            </span>
            <MarkedSelect
              label="SKU"
              className={SELECT}
              value={sku}
              onChange={(next) => pick({ branch, sku: next }, 'sku')}
              options={skuOptions.map((s) => ({ value: s, label: s, marked: strong.sku(s) }))}
            />
          </label>
          <span className="pb-1.5 text-[10px] text-[var(--color-text-muted)]">
            {skuOptions.length} SKUs at this location
          </span>
        </div>
        {/* Provenance only. This used to carry three sentences of explanation
            under the two pickers — a restatement of the selection the pickers
            already show, a note that only trained lines are listed, and the
            reasoning for dropping the aggregate scopes — and it was removed on
            request. The selection is visible in the controls above it and in
            the Outlook panel's own title; the reasoning belongs in D-133, not
            over the reader's shoulder every time they change a SKU.

            What stays is the pair of facts that are *not* stated anywhere else
            on the page: which origin this forecast was made from, and how it
            was reconciled (D-134). */}
        {run.data && (
          <p className="mt-2 text-[11px] text-[var(--color-text-muted)]">
            Origin {monthLabel(run.data.origin_period)}, reconciled by{' '}
            {run.data.reconciliation_method}.
          </p>
        )}
        {run.isError && run.error instanceof ApiError && (
          <p className="hint mt-1">
            {run.error.message} {run.error.remediation}
          </p>
        )}
      </Card>

      {parsed.length === 0 && scopes.isSuccess && (
        <Card>
          <EmptyState title="No trained line to forecast">
            This run reached no branch × SKU line, so there is nothing to show. Train a run
            from the Training page and this page fills in.
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
          <LineSummaryTiles scopeKey={scopeKey} />

          <Panel
            title={`Outlook — ${scopeKey}`}
            accent={BLUE}
            note={CHART_NOTE}
          >
            <div className="chart-toolbar">
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
            </div>

            <DemandChart
              data={data}
              view="overview"
              points={[]}
              quantiles={false}
              range={range}
              height={330}
            />
            {data.history_unavailable_reason && (
              <Explain variant="note">{data.history_unavailable_reason}</Explain>
            )}
            <Explain variant="note">{data.snapshot_caveat}</Explain>
          </Panel>

          {rollup.length > 0 && (
            <Panel
              title="The six months, added up from the weeks"
              accent={BLUE}
              note="Forecast per ISO week, then added into the calendar months. A week is reported under the month containing its Thursday, so no week is split and the months add back to the horizon total exactly."
            >
              <div className="table-scroll">
                <table className="data">
                  <thead>
                    <tr>
                      <th>Month</th>
                      <th className="num">Weeks</th>
                      <th className="num">Point forecast</th>
                      {rollupHasBand && (
                        <>
                          <th className="num">q80</th>
                          <th className="num">q90</th>
                          <th className="num">q95</th>
                        </>
                      )}
                    </tr>
                  </thead>
                  <tbody>
                    {rollup.map((m) => (
                      <tr key={m.month}>
                        <td className="mono text-[11px]">
                          {m.month}
                          {!m.complete && (
                            <span
                              className="ml-1.5 text-[10px] text-[var(--color-text-muted)]"
                              title="The horizon covers only part of this month, so this is a partial total - not a forecast of a short month."
                            >
                              part month
                            </span>
                          )}
                        </td>
                        <td className="num">{m.periods}</td>
                        <td className="num">{formatInt(m.point_forecast)}</td>
                        {rollupHasBand && (
                          <>
                            <td className="num">{formatInt(m.q80)}</td>
                            <td className="num">{formatInt(m.q90)}</td>
                            <td className="num">{formatInt(m.q95)}</td>
                          </>
                        )}
                      </tr>
                    ))}
                    <tr className="font-semibold">
                      <td>Six-month total</td>
                      <td className="num">{forecasts.length}</td>
                      <td className="num">{formatInt(data.horizon_total)}</td>
                      {rollupHasBand && (
                        <>
                          <td className="num">—</td>
                          <td className="num">—</td>
                          <td className="num">—</td>
                        </>
                      )}
                    </tr>
                  </tbody>
                </table>
              </div>
              <p className="mt-2 text-[11px] leading-relaxed text-[var(--color-text-muted)]">
                {rollupHasBand ? (
                  <>
                    <strong>The quantile columns are sums, and a summed quantile is not the
                    quantile of the sum.</strong> Adding five weekly q95 values describes the
                    case where every week peaks at once, which is more pessimistic than a 95%
                    month. Size a month&rsquo;s cover from the point forecast and the
                    series&rsquo; own error, not from this column.
                  </>
                ) : (
                  <>
                    <strong>No prediction interval is shown.</strong> This scope is the sum of
                    the series beneath it and carries no interval of its own — adding up each
                    SKU&rsquo;s upper bound would assume every SKU misses high in the same
                    week. Pick a location and a SKU for a band that was measured.
                  </>
                )}
              </p>
            </Panel>
          )}

          {metrics && (
            <Panel
              title="Why this model, for this series"
              accent={GREEN}
              /* The span has to be named here, because this MAPE and the one
                 on the tile above are different numbers for the same line —
                 89.1% against 1.9% — and the tile no longer carries the
                 single-period reading that used to bridge them. These are the
                 selection metrics: one period at a time, which is what the
                 champion was chosen on. The tile is the six-month total, where
                 the misses cancel (D-134). */
              note={`Measured out of sample on this series only, one ${periodNounOne(
                data.panel_grain,
              )} at a time — these are the figures the champion was selected on, so this MAPE is larger than the six-month one in the tile above. Aggregate error does not transfer down either: an aggregate is far less intermittent and much easier to forecast than a single branch × SKU cell.`}
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

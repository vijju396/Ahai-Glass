/**
 * Per Branch & SKU Analysis — one combination at a time.
 *
 * The filters are slicers, not a cascade: Location narrows the SKU list and
 * SKU narrows the Location list, so neither can offer a value that yields an
 * empty page. Value class and glass-type filters narrow both.
 *
 * Analysis appears as the selection narrows rather than only when it reaches
 * one series. Branch alone is a real question ("how is AHMEDABAD doing?"), so
 * the page answers whatever the current combination addresses and says which
 * that is — a page that stayed blank until two dropdowns matched would hide
 * data it already had.
 */
import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  Area,
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import {
  analyticsKeys,
  fetchAnalyticsFilters,
  fetchAnalyticsSummary,
  fetchExceptions,
  fetchSeriesOptions,
  seriesKeys,
  type AnalyticsQuery,
} from '@/api/analytics';
import {
  BLUE,
  Panel,
  RED,
  SLATE,
  StatTile,
  TICK,
  TOOLTIP,
  YELLOW,
  inr,
  num,
  pct,
} from '@/components/ui/Dashboard';
import { Card } from '@/components/ui/Card';
import { ScopeBanner } from '@/components/ui/ScopeBanner';
import { ErrorState, LoadingBlock } from '@/components/ui/States';

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const shortPeriod = (period: string) => {
  const [y, m] = period.split('-');
  return `${MONTHS[Number(m) - 1] ?? m} ${y?.slice(2) ?? ''}`;
};

const SELECT =
  'rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-2.5 py-1.5 text-xs text-[var(--color-text)]';

function splitSeries(id: string): { branch: string; sku: string } | null {
  const cut = id.indexOf('|');
  if (cut <= 0 || cut === id.length - 1) return null;
  return { branch: id.slice(0, cut), sku: id.slice(cut + 1) };
}

export function SeriesAnalysisPage() {
  const [branch, setBranch] = useState('');
  const [sku, setSku] = useState('');
  const [valueClass, setValueClass] = useState('');
  const [grain, setGrain] = useState('monthly');

  const filters = useQuery({
    queryKey: analyticsKeys.filters,
    queryFn: fetchAnalyticsFilters,
    retry: false,
  });
  const series = useQuery({
    queryKey: seriesKeys.options(),
    queryFn: () => fetchSeriesOptions(),
    retry: false,
  });

  // Slicers that filter each other, both ways.
  const parsed = useMemo(
    () =>
      (series.data?.items ?? []).flatMap((row) => {
        const parts = splitSeries(row.series_id);
        return parts ? [{ ...row, ...parts }] : [];
      }),
    [series.data],
  );
  const branchOptions = useMemo(
    () => [...new Set(parsed.filter((r) => !sku || r.sku === sku).map((r) => r.branch))].sort(),
    [parsed, sku],
  );
  const skuOptions = useMemo(
    () =>
      [...new Set(parsed.filter((r) => !branch || r.branch === branch).map((r) => r.sku))].sort(),
    [parsed, branch],
  );
  const matching = parsed.filter(
    (r) => (!branch || r.branch === branch) && (!sku || r.sku === sku),
  );

  const query: AnalyticsQuery = {
    branch: branch || undefined,
    sku: sku || undefined,
    value_class: valueClass || undefined,
    grain,
  };
  const summary = useQuery({
    queryKey: analyticsKeys.summary(query),
    queryFn: () => fetchAnalyticsSummary(query),
    retry: false,
  });
  const exceptions = useQuery({
    queryKey: analyticsKeys.exceptions(query),
    queryFn: () => fetchExceptions(query),
    retry: false,
  });

  const data = summary.data;
  const trend = useMemo(
    () => (data?.trend ?? []).map((p) => ({ ...p, label: shortPeriod(p.period) })),
    [data],
  );

  /** What the current combination actually addresses. Printed, so no figure
   *  is ambiguous about its subject. */
  const subject =
    branch && sku
      ? `one series — ${branch} × ${sku}`
      : branch
        ? `every SKU at ${branch}`
        : sku
          ? `${sku} across every branch in scope`
          : 'the whole workspace';

  return (
    <div className="flex flex-col gap-4">
      <header>
        <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[var(--color-primary)]">
          Per Branch &amp; SKU
        </p>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight text-[var(--color-text)]">
          One combination at a time.
        </h1>
        <p className="mt-1 max-w-3xl text-sm text-[var(--color-text-muted)]">
          Pick a location, a SKU, or both. The two slicers narrow each other, so a
          combination that would return nothing is never offered.
        </p>
      </header>

      <ScopeBanner scope={filters.data?.workspace_scope} />

      <Card>
        <div className="flex flex-wrap items-end gap-2.5">
          <label className="inline-flex flex-col gap-0.5">
            <span className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--color-text-muted)]">
              Location
            </span>
            <select
              aria-label="Location"
              className={SELECT}
              value={branch}
              onChange={(e) => setBranch(e.target.value)}
            >
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
            <select
              aria-label="SKU"
              className={SELECT}
              value={sku}
              onChange={(e) => setSku(e.target.value)}
            >
              <option value="">All SKUs</option>
              {skuOptions.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>
          <label className="inline-flex flex-col gap-0.5">
            <span className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--color-text-muted)]">
              Value class
            </span>
            <select
              aria-label="Value class"
              className={SELECT}
              value={valueClass}
              onChange={(e) => setValueClass(e.target.value)}
            >
              <option value="">All value classes</option>
              {(filters.data?.value_classes ?? []).map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </label>
          <label className="inline-flex flex-col gap-0.5">
            <span className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--color-text-muted)]">
              Grain
            </span>
            <select
              aria-label="Grain"
              className={SELECT}
              value={grain}
              onChange={(e) => setGrain(e.target.value)}
            >
              {(filters.data?.available_grains ?? ['monthly']).map((g) => (
                <option key={g} value={g}>
                  {g}
                </option>
              ))}
            </select>
          </label>
          {(branch || sku || valueClass) && (
            <button
              type="button"
              className="link-button pb-2 text-[11px]"
              onClick={() => {
                setBranch('');
                setSku('');
                setValueClass('');
              }}
            >
              Clear
            </button>
          )}
        </div>
        <p className="mt-2 text-[11px] text-[var(--color-text-muted)]">
          Showing <strong>{subject}</strong> — {matching.length} of {parsed.length} series in
          scope. Only combinations present in the panel are listed.
        </p>
      </Card>

      {summary.isPending && (
        <Card>
          <LoadingBlock rows={8} label="Reading this combination" />
        </Card>
      )}
      {summary.isError && (
        <Card>
          <ErrorState error={summary.error} onRetry={() => summary.refetch()} />
        </Card>
      )}
      {data?.empty && (
        <Card>
          <p className="hint">
            {data.reason ?? 'Nothing in the panel matches this combination.'}
          </p>
        </Card>
      )}

      {data && !data.empty && (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <StatTile
              label="Ordered demand"
              value={`${num(data.kpis.demand_units)} units`}
              sublabel={`${inr(data.kpis.demand_value)} · ${data.window.periods} months`}
              tint="blue"
              accent
            />
            <StatTile
              label="Unfilled"
              value={`${num(data.kpis.shortfall_units)} units`}
              sublabel={`${num(data.kpis.censored_rows)} short-despatched rows`}
              tint="amber"
            />
            <StatTile
              label="Fill rate"
              value={pct(data.kpis.fill_rate_pct)}
              sublabel="despatched ÷ ordered, where recorded"
              tint="green"
            />
            <StatTile
              label="Series covered"
              value={num(data.kpis.series_count)}
              sublabel={`${num(data.kpis.branch_count)} branch(es) · ${num(data.kpis.sku_count)} SKU(s)`}
              tint="navy"
            />
          </div>

          <Panel
            title={`Demand over time — ${subject}`}
            accent={BLUE}
            note="Ordered against despatched. Where the bar is tall the order was not filled, and the ordered figure on that month is a lower bound on what was really wanted."
          >
            <ResponsiveContainer width="100%" height={280}>
              <ComposedChart data={trend} margin={{ top: 8, right: 8, left: -10, bottom: 0 }}>
                <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="var(--color-border)" />
                <XAxis dataKey="label" tick={{ ...TICK, fontSize: 9 }} tickLine={false} interval={grain === 'monthly' ? 1 : 0} />
                <YAxis tick={TICK} width={46} />
                <Tooltip contentStyle={TOOLTIP} formatter={(v: number) => num(v)} />
                <Legend wrapperStyle={{ fontSize: 9 }} />
                <ReferenceLine x={shortPeriod('2025-04')} stroke={SLATE} strokeDasharray="4 4" />
                <Area
                  type="monotone"
                  dataKey="demand_units"
                  name="Ordered"
                  stroke={BLUE}
                  fill={BLUE}
                  fillOpacity={0.12}
                  strokeWidth={2}
                  isAnimationActive={false}
                />
                <Line
                  type="monotone"
                  dataKey="despatched_units"
                  name="Despatched"
                  stroke={YELLOW}
                  strokeWidth={2}
                  dot={false}
                  connectNulls={false}
                  isAnimationActive={false}
                />
                <Bar dataKey="shortfall_units" name="Short" fill={RED} barSize={8} isAnimationActive={false} />
              </ComposedChart>
            </ResponsiveContainer>
          </Panel>

          <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
            <Panel
              title="Monthly detail"
              accent={SLATE}
              note="Every month in the window, with the source and censoring of each. A blank despatch means it was not recorded, which is why it is excluded from the fill rate rather than counted as zero."
            >
              <div className="table-scroll max-h-[300px]">
                <table className="data">
                  <thead>
                    <tr>
                      <th>Period</th>
                      <th className="num">Ordered</th>
                      <th className="num">Despatched</th>
                      <th className="num">Short</th>
                      <th className="num">Fill</th>
                      <th className="num">Order %</th>
                    </tr>
                  </thead>
                  <tbody>
                    {trend.map((p) => (
                      <tr key={p.period}>
                        <td>{p.label}</td>
                        <td className="num">{num(p.demand_units)}</td>
                        <td className="num">
                          {p.despatched_units === null ? '—' : num(p.despatched_units)}
                        </td>
                        <td className="num">{num(p.shortfall_units)}</td>
                        <td className="num">{pct(p.fill_rate_pct)}</td>
                        <td className="num">{pct(p.order_share_pct)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Panel>

            <Panel
              title="Exceptions in this selection"
              accent={RED}
              note={
                exceptions.data && !exceptions.data.empty
                  ? `${num(exceptions.data.kpis.total_lines)} flagged line(s).`
                  : 'Nothing flagged for this combination.'
              }
            >
              {exceptions.isPending && <LoadingBlock rows={4} label="Reading exceptions" />}
              {exceptions.data && !exceptions.data.empty ? (
                <div className="table-scroll max-h-[300px]">
                  <table className="data">
                    <thead>
                      <tr>
                        <th>Type</th>
                        <th>Branch</th>
                        <th>SKU</th>
                        <th className="num">Units</th>
                      </tr>
                    </thead>
                    <tbody>
                      {exceptions.data.top_lines.map((row, i) => (
                        <tr key={`${row.series_id}-${row.type}-${i}`}>
                          <td>{row.label}</td>
                          <td>{row.branch}</td>
                          <td className="mono text-[10px]">{row.sku}</td>
                          <td className="num">{num(row.units)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                !exceptions.isPending && (
                  <p className="py-3 text-[11px] text-[var(--color-text-muted)]">
                    No exception condition applies here.
                  </p>
                )
              )}
            </Panel>
          </div>
        </>
      )}
    </div>
  );
}

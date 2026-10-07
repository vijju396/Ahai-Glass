/**
 * Per Branch & SKU Analysis — one combination at a time.
 *
 * The filters are slicers, not a cascade: Location narrows the SKU list and
 * SKU narrows the Location list, so neither can offer a value that yields an
 * empty page.
 *
 * Analysis appears as the selection narrows rather than only when it reaches
 * one series. Branch alone is a real question ("how is AHMEDABAD doing?"), so
 * the page answers whatever the current combination addresses and says which
 * that is — a page that stayed blank until two dropdowns matched would hide
 * data it already had.
 *
 * **Scope: the whole client network**, the same 53 branches and 2,063 ordered
 * SKUs Overall Analysis reports (D-144). It used to read the modelling panel,
 * which is physically cut to the workspace, so the picker offered 2 branches
 * and 136 SKUs — a page whose entire purpose is "pick any branch and SKU"
 * could not reach 51 branches of the client's own data. Nothing here is
 * model-derived: every figure comes from `/api/analytics/summary`, which has
 * a `full_network` reading. Training and Forecasting stay on the workspace,
 * because a forecast only exists where a model was fitted.
 */
import { useMemo, useState } from 'react';
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import {
  Area,
  Bar,
  CartesianGrid,
  Cell,
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
  fetchSeriesOptions,
  seriesKeys,
  type AnalyticsQuery,
} from '@/api/analytics';
import {
  BLUE,
  GREEN,
  NAVY,
  Panel,
  RED,
  SLATE,
  StatTile,
  TEAL,
  TICK,
  TOOLTIP,
  VIOLET,
  YELLOW,
  inr,
  num,
  pct,
} from '@/components/ui/Dashboard';
import { Card } from '@/components/ui/Card';
import { ScopeBanner } from '@/components/ui/ScopeBanner';
import { ErrorState, LoadingBlock } from '@/components/ui/States';
import { Explain } from '@/components/ui/Explain';
import { periodNoun, shortPeriod } from '../../../app/period';


/* `inr` rounds anything over a thousand to "K", which is right for a demand
   value and wrong for a unit price: a 1,575 and a 1,700 both read "\u20B92K" and the
   step between them disappears. Prices here are plain rupees, so show them
   whole. */
const rupees = (n: number | null | undefined): string =>
  n == null || !Number.isFinite(n) ? '\u2014' : `\u20B9${Math.round(n).toLocaleString('en-IN')}`;

const SELECT =
  'rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-2.5 py-1.5 text-xs text-[var(--color-text)]';

/* `num` abbreviates: 68,597 reads "68.6K", and "68.6K of 68.6K" hides whether
   the two are the same number. A count the reader is asked to take literally
   gets its digits (D-143). */
const exact = (n: number) => n.toLocaleString('en-IN');

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
    queryKey: analyticsKeys.networkFilters,
    queryFn: () => fetchAnalyticsFilters(true),
    retry: false,
  });

  /* Two scoped pair queries, never one unscoped list.
   *
   * The old page fetched the top 1,000 pairs by demand and derived both
   * dropdowns from it. On the workspace that was all 272 pairs, so it was
   * complete by accident. On the network there are 68,597, and the same code
   * would have offered the busiest 1,000 as if they were everything — a
   * silent cap on the one page whose job is to let you reach any combination
   * (D-144).
   *
   * So each slicer asks its own question, and each answer is complete:
   * "which SKUs does this branch carry?" is at most 2,315 rows, and "which
   * branches carry this SKU?" is at most 53. With neither chosen, the lists
   * come from `/filters`, which returns every branch and every SKU outright.
   * `enabled` is what keeps the unscoped call from ever being made. */
  const skusAtBranch = useQuery({
    queryKey: seriesKeys.options(branch, undefined, true),
    queryFn: () => fetchSeriesOptions(branch, undefined, true),
    enabled: !!branch,
    retry: false,
    placeholderData: keepPreviousData,
  });
  const branchesForSku = useQuery({
    queryKey: seriesKeys.options(undefined, sku, true),
    queryFn: () => fetchSeriesOptions(undefined, sku, true),
    enabled: !!sku,
    retry: false,
    placeholderData: keepPreviousData,
  });

  const allBranches = useMemo(
    () => (filters.data?.branches ?? []).map((o) => o.value).sort(),
    [filters.data],
  );
  const allSkus = useMemo(
    () => (filters.data?.skus ?? []).map((o) => o.value).sort(),
    [filters.data],
  );
  const branchOptions = useMemo(() => {
    if (!sku) return allBranches;
    const rows = branchesForSku.data?.items ?? [];
    return [...new Set(rows.flatMap((r) => splitSeries(r.series_id)?.branch ?? []))].sort();
  }, [sku, allBranches, branchesForSku.data]);
  const skuOptions = useMemo(() => {
    if (!branch) return allSkus;
    const rows = skusAtBranch.data?.items ?? [];
    return [...new Set(rows.flatMap((r) => splitSeries(r.series_id)?.sku ?? []))].sort();
  }, [branch, allSkus, skusAtBranch.data]);

  const query: AnalyticsQuery = {
    branch: branch || undefined,
    sku: sku || undefined,
    value_class: valueClass || undefined,
    grain,
  };
  const summary = useQuery({
    queryKey: analyticsKeys.networkSummary(query),
    queryFn: () => fetchAnalyticsSummary(query, true),
    retry: false,
    /* The panels render under `data && !data.empty`. Without this a slicer
       change unmounts every one of them, the document collapses and the
       reader is thrown to the top — the same defect fixed on Overall Analysis
       in D-142, and the same fix. */
    placeholderData: keepPreviousData,
  });
  const data = summary.data;
  /* Two lines, and the proxy months belong to the despatched one.

     A `sales_proxy` month's `target` is not a demand figure at all: it is the
     invoiced quantity, copied across unchanged - summed over the workspace it
     matches the sales file to the unit, every month. Invoicing is despatch.
     Drawing it as "Ordered" put a despatch series under a demand label for a
     third of the window, and made the ordered-to-despatched gap look like it
     opened in Apr 2025 when that is only where the order book starts.

     So despatch is the long series - two years of it, Apr 2024 onward, read
     from the sales file before Apr 2025 and from the order file's despatch
     column after - and ordered is the short one, sixteen months, drawn only
     where a real order book exists. The two despatch sources are two records
     of the same event and agree within a few per cent on every month they
     share; the order file wins the overlap, because the short bars are
     ordered minus that same column and have to reconcile with it.

     `order_share_pct` is exactly 0 on the proxy months and exactly 100 after,
     so the split needs no hardcoded date. */
  const trend = useMemo(
    () =>
      (data?.trend ?? []).map((p) => {
        const isProxy = (p.order_share_pct ?? 0) < 50;
        return {
          ...p,
          label: shortPeriod(p.period),
          ordered_units: isProxy ? null : p.demand_units,
          despatched_shown: isProxy ? p.demand_units : p.despatched_units,
        };
      }),
    [data],
  );

  /* The four views below answer the questions worth asking about a SKU before
     any forecast of it is worth reading: does it repeat every year, is it
     steady or jumpy, is the history a real order or a stand-in, and is the
     price moving under it. All four read fields `/api/analytics/summary`
     already returns for the current selection. The only figure derived here is
     the period-over-period percentage change, which is a way of drawing the
     ordered column, not a second calculation of it. */
  const seasonality = data?.seasonality ?? [];
  /* How many years each bar averages, stated once instead of on every hover.
     The window is short enough that it is always two or three. */
  const seasonSpan = useMemo(() => {
    const years = seasonality.map((m) => m.observations).filter((n) => n > 0);
    if (!years.length) return 'Each bar averages the years in the window';
    const low = Math.min(...years);
    const high = Math.max(...years);
    return low === high
      ? `Each bar averages ${low} year${low === 1 ? '' : 's'}`
      : `Each bar averages ${low}–${high} years, depending on how many times that month falls inside the window`;
  }, [seasonality]);
  const change = useMemo(
    () =>
      trend.slice(1).map((p, i) => {
        const previous = trend[i]?.demand_units ?? 0;
        return {
          label: p.label,
          demand_units: p.demand_units,
          change_pct: previous ? ((p.demand_units - previous) / previous) * 100 : null,
        };
      }),
    [trend],
  );

  /** What the current combination actually addresses. Printed, so no figure
   *  is ambiguous about its subject. */
  const subject =
    branch && sku
      ? `one series — ${branch} × ${sku}`
      : branch
        ? `every SKU at ${branch}`
        : sku
          ? `${sku} across every branch that carries it`
          : 'every branch and every SKU';

  return (
    <div className="flex flex-col gap-4">
      <header>
        <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[var(--color-primary)]">
          Per Branch &amp; SKU
        </p>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight text-[var(--color-text)]">
          One combination at a time.
        </h1>
        <Explain label="About this page" variant="note">
          Pick a location, a SKU, or both. The two slicers narrow each other, so a
          combination that would return nothing is never offered.
        </Explain>
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
          {/* The panels below are holding the PREVIOUS selection's figures
              while this runs (D-142). Saying so is the price of not
              unmounting them. */}
          {summary.isFetching && !summary.isLoading && (
            <span className="ml-auto pb-2 text-[11px] font-medium text-[var(--color-primary)]">
              Updating…
            </span>
          )}
        </div>
        {/* The series count comes from the payload for this selection and the
            total from `/filters`, both at network scope. It used to be
            `matching.length of parsed.length` over a fetched pair list, which
            only ever worked because the workspace's 272 pairs fitted inside
            the fetch (D-144). */}
        <p className="mt-2 text-[11px] text-[var(--color-text-muted)]">
          Showing <strong>{subject}</strong> —{' '}
          {data && !data.empty ? exact(data.kpis.series_count) : '0'} of{' '}
          {exact(filters.data?.series_count ?? 0)} branch × SKU combinations
          {filters.data?.workspace_scope?.total_branches
            ? `, across all ${filters.data.workspace_scope.total_branches} branches in the client's data`
            : ''}
          . Only combinations the data actually holds are listed.
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
          <Explain variant="hint">
            {data.reason ?? 'Nothing in the panel matches this combination.'}
          </Explain>
        </Card>
      )}

      {data && !data.empty && (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-3">
            <StatTile
              label="Ordered demand"
              value={`${num(data.kpis.demand_units)} units`}
              /* The window is the panel's own, always at the panel grain - the
                 grain picker above re-buckets the charts, it does not change
                 what the panel is made of - so the noun comes from
                 `panel_grain` and not from the picker. It read "122 months" on
                 a weekly panel, which is a count of weeks wearing the wrong
                 word. */
              sublabel={`${inr(data.kpis.demand_value)} · ${data.window.periods} ${periodNoun(data.panel_grain)}`}
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
            {/* "Series covered" was removed: it printed the same count the
                line under the slicers already states, abbreviated - "68.6K"
                beside "68,597 of 68,597" - and a tile is the wrong place for
                a figure about the selection rather than about the demand. */}
          </div>

          <Panel
            title={`Demand over time — ${subject}`}
            accent={BLUE}
            note="Ordered against despatched. Despatch runs the full two years, because an invoice is a despatch: before Apr 2025 it is read from the sales file and after it from the order book, and on the months both cover they agree within a few per cent. Ordered runs only from Apr 2025, which is where the order book starts - there is no order history before it. Ordered sits above despatched in almost every month, and that gap is the point of the chart: it is demand that was recorded but not filled, so the ordered figure is a lower bound on what was really wanted."
          >
            <ResponsiveContainer width="100%" height={280}>
              <ComposedChart data={trend} margin={{ top: 8, right: 8, left: -10, bottom: 0 }}>
                <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="var(--color-border)" />
                <XAxis dataKey="label" tick={{ ...TICK, fontSize: 9 }} tickLine={false} interval={grain === 'monthly' ? 1 : 0} />
                <YAxis tick={TICK} width={46} />
                <Tooltip contentStyle={TOOLTIP} formatter={(v: number) => num(v)} />
                <Legend wrapperStyle={{ fontSize: 9 }} />
                <ReferenceLine
                  x={shortPeriod('2025-04')}
                  stroke={SLATE}
                  strokeDasharray="4 4"
                  label={{
                    value: 'order book starts',
                    position: 'insideTopLeft',
                    fontSize: 9,
                    fill: 'var(--color-text-muted)',
                  }}
                />
                <Area
                  type="monotone"
                  dataKey="ordered_units"
                  name="Ordered"
                  stroke={BLUE}
                  fill={BLUE}
                  fillOpacity={0.12}
                  strokeWidth={2}
                  connectNulls={false}
                  isAnimationActive={false}
                />
                <Line
                  type="monotone"
                  dataKey="despatched_shown"
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
              title="Month-of-year pattern"
              accent={VIOLET}
              note={`The average ordered quantity for each calendar month, across every year in the window. A repeating shape here is what a seasonal model has to work with; bars of roughly equal height mean there is no annual pattern to lean on. ${seasonSpan} — too few for any bar to be a season on its own, so read the shape, not the heights.`}
            >
              <ResponsiveContainer width="100%" height={230}>
                <ComposedChart data={seasonality} margin={{ top: 8, right: 8, left: -10, bottom: 0 }}>
                  <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="var(--color-border)" />
                  <XAxis dataKey="name" tick={{ ...TICK, fontSize: 9 }} tickLine={false} />
                  <YAxis tick={TICK} width={46} />
                  {/* The tooltip used to append "averaged over N year(s)" to
                      every label. It said 10 on a two-year window, because the
                      count was of periods and the periods are weeks (D-145);
                      and once corrected it is the same two or three on every
                      bar, which belongs in the note once rather than on each
                      hover. */}
                  <Tooltip
                    contentStyle={TOOLTIP}
                    formatter={(v: number) => `${num(v)} units`}
                  />
                  <Bar
                    dataKey="mean_demand_units"
                    name="Average ordered"
                    fill={VIOLET}
                    barSize={16}
                    isAnimationActive={false}
                  />
                </ComposedChart>
              </ResponsiveContainer>
            </Panel>

            <Panel
              title="Month-on-month change"
              accent={TEAL}
              note="How much the ordered quantity moved against the month before it, as a percentage. Small bars either side of the line mean a steady series that is straightforward to forecast. Tall bars in both directions mean a jumpy one, where any single month's forecast will carry a wide range around it."
            >
              <ResponsiveContainer width="100%" height={230}>
                <ComposedChart data={change} margin={{ top: 8, right: 8, left: -10, bottom: 0 }}>
                  <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="var(--color-border)" />
                  <XAxis dataKey="label" tick={{ ...TICK, fontSize: 9 }} tickLine={false} interval={1} />
                  <YAxis tick={TICK} width={46} unit="%" />
                  <Tooltip
                    contentStyle={TOOLTIP}
                    formatter={(v: number) => (v === null || v === undefined ? 'no previous month' : pct(v))}
                  />
                  <ReferenceLine y={0} stroke={SLATE} />
                  <Bar dataKey="change_pct" name="Change" barSize={10} isAnimationActive={false}>
                    {change.map((p) => (
                      <Cell key={p.label} fill={(p.change_pct ?? 0) >= 0 ? GREEN : RED} />
                    ))}
                  </Bar>
                </ComposedChart>
              </ResponsiveContainer>
            </Panel>
          </div>

          <div className="grid grid-cols-1 gap-3">
            <Panel
              title="Price per unit"
              accent={NAVY}
              note="The average listed price per unit for this selection, month by month. It is here because a step in price often explains a step in demand that otherwise looks random. It is a record of what happened, not a driver: the price of a future month is not known, so no model is ever given it."
            >
              <ResponsiveContainer width="100%" height={230}>
                <ComposedChart data={trend} margin={{ top: 8, right: 8, left: -4, bottom: 0 }}>
                  <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="var(--color-border)" />
                  <XAxis dataKey="label" tick={{ ...TICK, fontSize: 9 }} tickLine={false} interval={1} />
                  <YAxis
                    tick={TICK}
                    width={58}
                    domain={['auto', 'auto']}
                    tickFormatter={rupees}
                  />
                  <Tooltip contentStyle={TOOLTIP} formatter={(v: number) => rupees(v)} />
                  <Line
                    type="monotone"
                    dataKey="price_per_unit"
                    name="Price per unit"
                    /* Not NAVY, which is the panel's accent: at #0F2754 a thin
                       line all but vanishes against the dark surface. */
                    stroke={BLUE}
                    strokeWidth={2}
                    dot={{ r: 2 }}
                    connectNulls={false}
                    isAnimationActive={false}
                  />
                </ComposedChart>
              </ResponsiveContainer>
            </Panel>
          </div>

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
                        {p.despatched_units === null ? '\u2014' : num(p.despatched_units)}
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
        </>
      )}
    </div>
  );
}

/**
 * Overall Analysis — every demand visual, for the whole workspace.
 *
 * This is the Demand Analytics page: the same sixteen panels, the same
 * cross-filtering, the same calendar range picker and branch scorecard. It
 * was rebuilt from that page rather than re-implemented, because those panels
 * were already verified and re-typing them would have risked regressions for
 * nothing.
 *
 * Three panels are added on top, because the earlier rewrite of this page
 * introduced them and they answer questions the original set did not:
 *
 * - **Concentration by value class** — the ABC/Pareto view: bars are ordered
 *   units, the line is the running share of total demand. It answers "how
 *   much of demand sits in how few products" in one line.
 * - **Which measurement?** — the share of rows sourced from a real purchase
 *   order rather than the invoiced proxy. Everything before Apr 2025 is
 *   proxy, so a trend crossing that line compares two different
 *   measurements. This is the single most misleading thing on the page if it
 *   is not shown.
 * - **Exception mix** — because exceptions are the reason a forecast and a
 *   plan disagree.
 *
 * Everything is read from `/analytics/summary`, `/analytics/branch-scorecard`
 * and `/analytics/exceptions`, all already cut to the workspace. This page
 * computes no forecast and no metric; it selects, formats and draws.
 */
import { useMemo, useState } from 'react';
import { MonthRange } from '@/components/ui/MonthRange';
import { ScopeBanner } from '@/components/ui/ScopeBanner';
import { SampleMixCaveat } from '@/components/ui/SampleMixCaveat';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  LabelList,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
  ComposedChart,
} from 'recharts';
import {
  analyticsKeys,
  fetchAnalyticsFilters,
  fetchAnalyticsSummary,
  fetchExceptions,
  fetchBranchScorecard,
  type AnalyticsQuery,
  type ScorecardBranch,
} from '@/api/analytics';
import {
  AMBER,
  BLUE,
  Card,
  ClearChip,
  GREEN,
  LABEL,
  MiniTable,
  NAVY,
  Panel,
  RED,
  SERIES_COLORS,
  SLATE,
  StatTile,
  TEAL,
  TICK,
  TOOLTIP,
  VIOLET,
  inr,
  num,
  pct,
} from '@/components/ui/Dashboard';
import { ErrorState, LoadingBlock } from '@/components/ui/States';

const SELECT_CLASS =
  'rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-2.5 py-1.5 text-xs text-[var(--color-text)]';

/** `2026-07` → `Jul 26`; a quarterly bucket is already short enough. */
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
function shortPeriod(period: string): string {
  if (period.includes('Q')) return period.replace('-Q', ' Q');
  const [year, month] = period.split('-');
  return `${MONTHS[Number(month) - 1] ?? month} ${year?.slice(2) ?? ''}`;
}

export function OverallAnalysisPage() {
  const [branch, setBranch] = useState('');
  const [valueClass, setValueClass] = useState('');
  const [startPeriod, setStartPeriod] = useState('');
  const [endPeriod, setEndPeriod] = useState('');
  const [grain, setGrain] = useState('monthly');

  const filtersQuery = useQuery({ queryKey: analyticsKeys.filters, queryFn: fetchAnalyticsFilters });
  const filters = filtersQuery.data;

  const query: AnalyticsQuery = useMemo(
    () => ({
      branch: branch || undefined,
      value_class: valueClass || undefined,
      start_period: startPeriod || undefined,
      end_period: endPeriod || undefined,
      grain,
    }),
    [branch, valueClass, startPeriod, endPeriod, grain],
  );

  const summaryQuery = useQuery({
    queryKey: analyticsKeys.summary(query),
    queryFn: () => fetchAnalyticsSummary(query),
    enabled: !!filters,
  });
  const exceptionsQuery = useQuery({
    queryKey: analyticsKeys.exceptions(query),
    queryFn: () => fetchExceptions(query),
    enabled: !!filters,
    retry: false,
  });
  const scorecardQuery = useQuery({
    queryKey: analyticsKeys.scorecard({ value_class: query.value_class, start_period: query.start_period, end_period: query.end_period }),
    queryFn: () =>
      fetchBranchScorecard({
        value_class: query.value_class,
        start_period: query.start_period,
        end_period: query.end_period,
      }),
    enabled: !!filters,
  });

  const summary = summaryQuery.data;

  /** Cross-filter: clicking a slice, column or legend entry sets the matching
   *  page filter, and clicking the already-selected item clears it. Same
   *  behaviour as the reference, which is what makes the dimming below read as
   *  a selection rather than a bug. */
  const toggleBranch = (name: string) => setBranch((current) => (current === name ? '' : name));
  const toggleValueClass = (name: string) => setValueClass((current) => (current === name ? '' : name));

  const dimBranch = (name: string) => (branch && name !== branch ? 0.28 : 1);
  const dimClass = (name: string) => (valueClass && name !== valueClass ? 0.28 : 1);

  const trend = useMemo(
    () => (summary?.trend ?? []).map((point) => ({ ...point, label: shortPeriod(point.period) })),
    [summary],
  );
  const branchOverTime = useMemo(
    () => (summary?.branch_over_time?.data ?? []).map((row) => ({ ...row, label: shortPeriod(String(row.period)) })),
    [summary],
  );
  const branchTotal = useMemo(
    () => (summary?.by_branch ?? []).reduce((sum, row) => sum + row.demand_value, 0),
    [summary],
  );
  const averagePrice = useMemo(() => {
    const values = trend.map((point) => point.price_per_unit).filter((v): v is number => v != null);
    return values.length ? values.reduce((sum, v) => sum + v, 0) / values.length : null;
  }, [trend]);
  const orderedVsDespatched = useMemo(
    () =>
      (summary?.by_value_class ?? []).map((row) => ({
        name: row.name,
        ordered: row.demand_units,
        despatched: row.despatched_units ?? 0,
      })),
    [summary],
  );

  /** The ABC curve: value classes sorted by demand, with the running share
   *  of the total. A cumulative sum over values the API already returned -
   *  not a new measurement. */
  const pareto = useMemo(() => {
    const rows = [...(summary?.by_value_class ?? [])];
    const total = rows.reduce((sum, r) => sum + (r.demand_units || 0), 0);
    let running = 0;
    return rows
      .sort((a, b) => (b.demand_units || 0) - (a.demand_units || 0))
      .map((r) => {
        running += r.demand_units || 0;
        return {
          name: r.name,
          demand_units: r.demand_units,
          sku_count: r.sku_count,
          cumulative_pct: total > 0 ? Math.round((running / total) * 1000) / 10 : 0,
        };
      });
  }, [summary]);

  /** SKUs ranked by ordered demand, with their unfilled share. The page had
   *  no SKU visual at all, which on a twenty-product workspace left out the
   *  axis the whole scope is defined on. */
  const skuRows = useMemo(() => {
    const rows = [...(summary?.by_sku ?? [])];
    return rows
      .sort((a, b) => (b.demand_units || 0) - (a.demand_units || 0))
      .slice(0, 12)
      .map((r) => ({
        name: r.name,
        short: r.name.replace(/^FG\./, '').slice(0, 17),
        demand_units: r.demand_units,
        shortfall_units: r.shortfall_units,
        filled_units: Math.max((r.demand_units || 0) - (r.shortfall_units || 0), 0),
        unfilled_share_pct:
          (r.demand_units || 0) > 0
            ? Math.round((1000 * (r.shortfall_units || 0)) / (r.demand_units || 0)) / 10
            : 0,
      }));
  }, [summary]);

  /** The product axes this workspace was actually selected on. The sample
   *  was stratified across three glass types and four vehicle categories,
   *  and until now the page showed neither — so it could not show the shape
   *  of its own sample. */
  const glassRows = useMemo(
    () =>
      (summary?.by_glass_type ?? [])
        .filter((r) => r.name && r.name !== 'UNKNOWN')
        .sort((a, b) => (b.demand_units || 0) - (a.demand_units || 0)),
    [summary],
  );
  const vehicleRows = useMemo(
    () =>
      (summary?.by_vehicle_category ?? [])
        .filter((r) => r.name && r.name !== 'UNKNOWN')
        .sort((a, b) => (b.demand_units || 0) - (a.demand_units || 0)),
    [summary],
  );

  /** Replacement glass skews heavily to older vehicles, so the age profile
   *  is a real planning signal rather than a curiosity: it says which parc
   *  the demand is coming from. Labels are long, so the chart is horizontal. */
  const ageRows = useMemo(
    () =>
      (summary?.by_vehicle_age ?? [])
        .filter((r) => r.name && r.name !== 'UNKNOWN')
        .map((r) => ({ ...r, short: r.name.replace(/^Category /, '').replace(/[()]/g, '').trim() }))
        .sort((a, b) => (b.demand_units || 0) - (a.demand_units || 0)),
    [summary],
  );

  /** Four cross-sections built from figures `/analytics/summary` already
   *  returns for every dimension. Nothing here is a new measurement - each
   *  one is a ratio of two numbers already on the payload.
   *
   *  Fill rate is only defined where a despatch was actually recorded.
   *  `despatched_units` is null when the source carries no despatch row for
   *  that level, and a null is not a zero: drawing it as 0% would read as
   *  "nothing was despatched" when the truth is "nothing was recorded". Those
   *  levels are dropped and counted, never plotted at zero. */
  const glassFill = useMemo(() => {
    const usable = glassRows.filter(
      (r) => r.despatched_units != null && (r.demand_units || 0) > 0,
    );
    return {
      rows: usable
        .map((r) => ({
          name: r.name,
          fill_pct:
            Math.round((1000 * (r.despatched_units as number)) / r.demand_units) / 10,
          demand_units: r.demand_units,
          despatched_units: r.despatched_units as number,
        }))
        .sort((a, b) => a.fill_pct - b.fill_pct),
      unrecorded: glassRows.length - usable.length,
    };
  }, [glassRows]);

  /** Value per unit, by where the glass ends up. Demand value divided by
   *  ordered units - a realised figure from what was actually ordered, not
   *  MRP, which is historical and never used as a forward driver. */
  const vehicleValue = useMemo(
    () =>
      vehicleRows
        .filter((r) => (r.demand_units || 0) > 0)
        .map((r) => ({
          name: r.name,
          short: r.name.length > 16 ? `${r.name.slice(0, 15)}…` : r.name,
          per_unit: Math.round((r.demand_value / r.demand_units) * 100) / 100,
          demand_value: r.demand_value,
          demand_units: r.demand_units,
        }))
        .sort((a, b) => b.per_unit - a.per_unit),
    [vehicleRows],
  );

  /** Volume against value, one mark per SKU. The bar charts rank on one axis
   *  at a time and so cannot show the thing that actually matters for
   *  planning: a low-volume SKU can sit high on value, and it is the position
   *  off the diagonal that identifies it. */
  const skuScatter = useMemo(
    () =>
      (summary?.by_sku ?? [])
        .filter((r) => (r.demand_units || 0) > 0 && r.demand_value > 0)
        .map((r) => ({
          name: r.name,
          short: r.name.replace(/^FG\./, '').slice(0, 20),
          demand_units: r.demand_units,
          demand_value: r.demand_value,
          per_unit: Math.round((r.demand_value / r.demand_units) * 100) / 100,
          series_count: r.series_count,
        })),
    [summary],
  );

  /** Where service failure concentrates on the age axis. Gross positive
   *  shortfall over ordered units - over-despatched lines are excluded from
   *  the numerator, so this is not the net figure and the two are reported
   *  separately everywhere on this page. */
  const ageRisk = useMemo(
    () =>
      ageRows
        .filter((r) => (r.demand_units || 0) > 0)
        .map((r) => ({
          name: r.name,
          short: r.short,
          unfilled_share_pct:
            Math.round((1000 * (r.shortfall_units || 0)) / r.demand_units) / 10,
          shortfall_units: r.shortfall_units,
          demand_units: r.demand_units,
        }))
        .sort((a, b) => b.unfilled_share_pct - a.unfilled_share_pct),
    [ageRows],
  );

  const exceptions = exceptionsQuery.data;

  const anyFilter = branch || valueClass || startPeriod || endPeriod;
  const rangeInvalid = !!(startPeriod && endPeriod && startPeriod > endPeriod);

  return (
    <div className="flex flex-col gap-5">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[var(--color-primary)]">
            Overall Analysis
          </p>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight text-[var(--color-text)]">
            Where the demand actually is.
          </h1>
          <p className="mt-1 max-w-2xl text-sm text-[var(--color-text-muted)]">
            Ordered demand by branch, value class and month, against what was despatched. Click
            any column, slice or legend entry to filter the whole page, or{' '}
            <Link to="/series" className="text-link">
              go per branch and SKU
            </Link>{' '}
            for one series at a time.
          </p>
        </div>
        <Link
          to="/assistant"
          className="rounded-lg border border-[var(--color-primary)] px-3 py-1.5 text-xs font-medium text-[var(--color-primary)] hover:bg-[var(--color-primary)]/10"
        >
          Ask the assistant
        </Link>
      </header>

      <ScopeBanner scope={filters?.workspace_scope} />

      {/* Filter bar */}
      <Card className="!py-2.5">
        <div className="flex flex-wrap items-center gap-2 text-xs">
          {/* Calendar pickers rather than two 28-entry dropdowns, bounded by
              the panel's own first and last month so the calendar cannot
              offer a month the data does not cover. Month grain, not day:
              the panel has no day-level values to return. */}
          <MonthRange
            from={startPeriod}
            to={endPeriod}
            onFromChange={setStartPeriod}
            onToChange={setEndPeriod}
            first={filters?.period_range?.min}
            last={filters?.period_range?.max}
            months={filters?.periods.length}
          />
          <select
            value={branch}
            onChange={(event) => setBranch(event.target.value)}
            className={SELECT_CLASS}
            aria-label="Branch"
          >
            <option value="">All branches</option>
            {filters?.branches.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          <select
            value={valueClass}
            onChange={(event) => setValueClass(event.target.value)}
            className={SELECT_CLASS}
            aria-label="Value class"
          >
            <option value="">All value classes</option>
            {filters?.value_classes.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          <select
            value={grain}
            onChange={(event) => setGrain(event.target.value)}
            className={SELECT_CLASS}
            aria-label="Grain"
          >
            {(filters?.available_grains ?? ['monthly']).map((option) => (
              <option key={option} value={option}>
                {option === 'monthly' ? 'By month' : 'By quarter'}
              </option>
            ))}
          </select>

          {branch && <ClearChip label={branch} onClear={() => setBranch('')} />}
          {valueClass && <ClearChip label={valueClass} onClear={() => setValueClass('')} />}
          {anyFilter && (
            <button
              type="button"
              onClick={() => {
                setBranch('');
                setValueClass('');
                setStartPeriod('');
                setEndPeriod('');
              }}
              className="text-[10px] font-medium text-[var(--color-text-muted)] underline"
            >
              Clear all
            </button>
          )}

          {summary && !summary.empty && (
            <span className="ml-auto text-[11px] text-[var(--color-text-muted)]">
              {summary.window.start} → {summary.window.end} · {summary.window.periods} months
            </span>
          )}
        </div>
        <p className="mt-1.5 text-[10px] text-[var(--color-text-muted)]">{filters?.grain_note}</p>
        {rangeInvalid && (
          <p className="mt-1.5 text-[10px] font-medium text-[var(--color-danger)]">
            The start month must be on or before the end month.
          </p>
        )}
      </Card>

      {(filtersQuery.isLoading || summaryQuery.isLoading) && <LoadingBlock label="Aggregating the panel" />}
      {filtersQuery.isError && <ErrorState error={filtersQuery.error} />}
      {summaryQuery.isError && <ErrorState error={summaryQuery.error} />}

      {summary?.empty && (
        <Card>
          <p className="text-sm text-[var(--color-text)]">{summary.reason}</p>
        </Card>
      )}

      {summary && !summary.empty && (
        <>
          {/* KPI tiles */}
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <StatTile
              label="Ordered demand value"
              value={inr(summary.kpis.demand_value)}
              sublabel={`${num(summary.kpis.demand_units)} units ordered`}
              spark={trend}
              sparkKey="demand_value"
              tint="blue"
              accent
            />
            <StatTile
              label="Unfilled demand"
              value={`${num(summary.kpis.shortfall_units)} units`}
              sublabel={`${summary.kpis.censored_rows.toLocaleString()} short-despatched rows`}
              spark={trend}
              sparkKey="shortfall_units"
              tint="amber"
            />
            <StatTile
              label="Fill rate"
              value={pct(summary.kpis.fill_rate_pct)}
              sublabel="despatched ÷ ordered, where despatch is recorded"
              spark={trend}
              sparkKey="fill_rate_pct"
              tint="green"
            />
            <StatTile
              label="Ordered-demand share"
              value={pct(summary.kpis.order_share_pct)}
              sublabel="rest is labelled sales proxy"
              spark={trend}
              sparkKey="order_share_pct"
              tint="teal"
            />
          </div>

          {/* Breakdown row */}
          {/* The 2-span panel goes FIRST so the row tiles exactly: 2+1+1 then
                1+1+1+1. Placed fourth it could not fit the single remaining
                column and wrapped, leaving one cell empty on the first row and
                three on the last (docs/DECISIONS.md D-071). */}
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-2 xl:grid-cols-4">
            <Panel
              title="Demand by Branch × Value Class"
              accent={VIOLET}
              className="lg:col-span-2 xl:col-span-2"
              note={`Each column is a branch, split by value class — the top ${summary.branch_by_group.limit} of ${summary.branch_by_group.total_branches} by value. Click a column to filter.`}
            >
              <ResponsiveContainer width="100%" height={236}>
                <BarChart data={summary.branch_by_group.data} margin={{ top: 8, right: 6, left: -6, bottom: 0 }} barCategoryGap="26%">
                  <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="var(--color-border)" />
                  <XAxis
                    dataKey="name"
                    tick={{ ...TICK, fontSize: 8 }}
                    tickLine={false}
                    interval={0}
                    angle={-40}
                    textAnchor="end"
                    height={68}
                  />
                  <YAxis tick={TICK} tickFormatter={(value: number) => inr(value)} width={54} />
                  <Tooltip formatter={(value: number) => inr(value)} contentStyle={TOOLTIP} />
                  <Legend wrapperStyle={{ fontSize: 9, cursor: 'pointer' }} />
                  {summary.branch_by_group.groups.map((group, index) => (
                    <Bar
                      key={group}
                      dataKey={group}
                      stackId="a"
                      fill={SERIES_COLORS[(index + 1) % SERIES_COLORS.length]}
                      radius={index === summary.branch_by_group.groups.length - 1 ? [5, 5, 0, 0] : undefined}
                      isAnimationActive={false}
                      className="cursor-pointer"
                      onClick={(entry: { name?: string }) => entry?.name && toggleBranch(entry.name)}
                    />
                  ))}
                </BarChart>
              </ResponsiveContainer>
            </Panel>
            <Panel
              title="Demand by Branch"
              accent={BLUE}
              note="Click a ring segment to filter to that branch."
              action={branch ? <ClearChip label="filtered" onClear={() => setBranch('')} /> : undefined}
            >
              <div className="relative">
                <ResponsiveContainer width="100%" height={196}>
                  <PieChart>
                    <Pie
                      data={summary.by_branch.slice(0, 10)}
                      dataKey="demand_value"
                      nameKey="name"
                      cx="50%"
                      cy="46%"
                      innerRadius={52}
                      outerRadius={78}
                      paddingAngle={2}
                      stroke="none"
                      isAnimationActive={false}
                      className="cursor-pointer"
                      onClick={(entry: { name?: string }) => entry?.name && toggleBranch(entry.name)}
                    >
                      {summary.by_branch.slice(0, 10).map((row, index) => (
                        <Cell
                          key={row.name}
                          fill={SERIES_COLORS[index % SERIES_COLORS.length]}
                          opacity={dimBranch(row.name)}
                        />
                      ))}
                    </Pie>
                    <Tooltip formatter={(value: number) => inr(value)} contentStyle={TOOLTIP} />
                    <Legend
                      wrapperStyle={{ fontSize: 10, cursor: 'pointer' }}
                      onClick={(entry: { value?: string }) => entry?.value && toggleBranch(entry.value)}
                    />
                  </PieChart>
                </ResponsiveContainer>
                <div className="pointer-events-none absolute inset-x-0 top-[26%] flex flex-col items-center">
                  <span className="text-base font-bold leading-none text-[var(--color-text)]">
                    {inr(branchTotal)}
                  </span>
                  <span className="text-[9px] uppercase tracking-wide text-[var(--color-text-muted)]">
                    top 10 of {summary.kpis.branch_count}
                  </span>
                </div>
              </div>
            </Panel>

            <Panel
              title="Demand by Value Class"
              accent={TEAL}
              note="SKU count shown under each column. Click to filter."
              action={valueClass ? <ClearChip label="filtered" onClear={() => setValueClass('')} /> : undefined}
            >
              <ResponsiveContainer width="100%" height={196}>
                <BarChart
                  data={summary.by_value_class}
                  margin={{ top: 18, right: 6, left: -12, bottom: 0 }}
                  barCategoryGap="28%"
                >
                  <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="var(--color-border)" />
                  <XAxis
                    dataKey="name"
                    tick={(props) => <ClassTick {...props} rows={summary.by_value_class} />}
                    height={56}
                    tickLine={false}
                    interval={0}
                  />
                  <YAxis tick={TICK} tickFormatter={(value: number) => num(value)} />
                  <Tooltip
                    formatter={(value: number) => `${num(value)} units`}
                    contentStyle={TOOLTIP}
                    cursor={{ fill: 'rgba(0,91,171,0.06)' }}
                  />
                  <Bar
                    dataKey="demand_units"
                    radius={[5, 5, 0, 0]}
                    isAnimationActive={false}
                    className="cursor-pointer"
                    onClick={(entry: { name?: string }) => entry?.name && toggleValueClass(entry.name)}
                  >
                    {summary.by_value_class.map((row, index) => (
                      <Cell
                        key={row.name}
                        fill={SERIES_COLORS[index % SERIES_COLORS.length]}
                        opacity={dimClass(row.name)}
                      />
                    ))}
                    <LabelList dataKey="demand_units" position="top" formatter={(v: number) => num(v)} style={LABEL} />
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            <SampleMixCaveat axis="value_class" />
              </Panel>

            <Panel title="Unfilled Demand by Value Class" accent={AMBER} note="Positive shortfall only. Click a column to filter.">
              <ResponsiveContainer width="100%" height={196}>
                <BarChart
                  data={summary.by_value_class}
                  margin={{ top: 18, right: 6, left: -12, bottom: 0 }}
                  barCategoryGap="28%"
                >
                  <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="var(--color-border)" />
                  <XAxis
                    dataKey="name"
                    tick={{ ...TICK, fontSize: 8 }}
                    tickLine={false}
                    interval={0}
                    angle={-30}
                    textAnchor="end"
                    height={52}
                  />
                  <YAxis tick={TICK} tickFormatter={(value: number) => num(value)} />
                  <Tooltip
                    formatter={(value: number) => `${num(value)} units short`}
                    contentStyle={TOOLTIP}
                    cursor={{ fill: 'rgba(161,92,7,0.06)' }}
                  />
                  <Bar
                    dataKey="shortfall_units"
                    radius={[5, 5, 0, 0]}
                    isAnimationActive={false}
                    className="cursor-pointer"
                    onClick={(entry: { name?: string }) => entry?.name && toggleValueClass(entry.name)}
                  >
                    {summary.by_value_class.map((row) => (
                      <Cell key={row.name} fill={AMBER} opacity={dimClass(row.name)} />
                    ))}
                    <LabelList dataKey="shortfall_units" position="top" formatter={(v: number) => num(v)} style={LABEL} />
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </Panel>

            

            <Panel
              title="Demand by Glass Type"
              accent={TEAL}
              note="Laminated windscreens, sidelites and backlites. This is the axis the twenty SKUs were chosen to span, and the split is very uneven — one type carries most of the volume."
            >
              <ResponsiveContainer width="100%" height={215}>
                <BarChart data={glassRows} margin={{ top: 16, right: 6, left: -14, bottom: 0 }} barCategoryGap="26%">
                  <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="var(--color-border)" />
                  <XAxis dataKey="name" tick={{ ...TICK, fontSize: 10 }} tickLine={false} interval={0} />
                  <YAxis tick={TICK} width={46} />
                  <Tooltip
                    contentStyle={TOOLTIP}
                    formatter={(v: number, _n, item) => {
                      const row = item?.payload as { sku_count?: number; shortfall_units?: number };
                      return [
                        `${num(v)} units · ${row?.sku_count ?? 0} SKUs · ${num(row?.shortfall_units)} short`,
                        'Ordered',
                      ];
                    }}
                  />
                  <Bar dataKey="demand_units" radius={[3, 3, 0, 0]} isAnimationActive={false}>
                    <LabelList
                      dataKey="demand_units"
                      position="top"
                      formatter={(v: number) => num(v)}
                      style={{ fill: 'var(--color-text-muted)', fontSize: 9 }}
                    />
                    {glassRows.map((row, i) => (
                      <Cell key={row.name} fill={[TEAL, BLUE, VIOLET, AMBER][i % 4]} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            <SampleMixCaveat axis="glass_type" />
              </Panel>

            <Panel
              title="Demand by Vehicle Category"
              accent={NAVY}
              note="Where the glass ends up. Car & MUV dominates by volume, but a commercial or high-end SKU can still matter disproportionately on value and on service."
            >
              <ResponsiveContainer width="100%" height={215}>
                <BarChart
                  data={vehicleRows}
                  layout="vertical"
                  margin={{ top: 4, right: 30, left: 4, bottom: 0 }}
                  barCategoryGap="24%"
                >
                  <CartesianGrid horizontal={false} strokeDasharray="3 3" stroke="var(--color-border)" />
                  <XAxis type="number" tick={TICK} />
                  <YAxis
                    type="category"
                    dataKey="name"
                    tick={{ ...TICK, fontSize: 9 }}
                    width={84}
                    tickLine={false}
                  />
                  <Tooltip
                    contentStyle={TOOLTIP}
                    formatter={(v: number, _n, item) => {
                      const row = item?.payload as { sku_count?: number };
                      return [`${num(v)} units · ${row?.sku_count ?? 0} SKUs`, 'Ordered'];
                    }}
                  />
                  <Bar dataKey="demand_units" radius={[0, 3, 3, 0]} isAnimationActive={false}>
                    {vehicleRows.map((row, i) => (
                      <Cell key={row.name} fill={[NAVY, BLUE, TEAL, SLATE][i % 4]} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            <SampleMixCaveat axis="vehicle_category" />
              </Panel>

            <Panel
              title="Demand by Vehicle Age"
              accent={AMBER}
              note="Which parc the demand comes from. Replacement glass skews to older vehicles, so a profile weighted to the oldest band is expected — a shift toward the newest band would be the surprise."
            >
              <ResponsiveContainer width="100%" height={215}>
                <BarChart
                  data={ageRows}
                  layout="vertical"
                  margin={{ top: 4, right: 30, left: 4, bottom: 0 }}
                  barCategoryGap="20%"
                >
                  <CartesianGrid horizontal={false} strokeDasharray="3 3" stroke="var(--color-border)" />
                  <XAxis type="number" tick={TICK} />
                  <YAxis
                    type="category"
                    dataKey="short"
                    tick={{ ...TICK, fontSize: 8 }}
                    width={96}
                    tickLine={false}
                  />
                  <Tooltip
                    contentStyle={TOOLTIP}
                    formatter={(v: number, _n, item) => {
                      const row = item?.payload as { sku_count?: number };
                      return [`${num(v)} units · ${row?.sku_count ?? 0} SKUs`, 'Ordered'];
                    }}
                    labelFormatter={(l) => ageRows.find((r) => r.short === l)?.name ?? String(l)}
                  />
                  <Bar dataKey="demand_units" radius={[0, 3, 3, 0]} isAnimationActive={false}>
                    {ageRows.map((row, i) => (
                      <Cell key={row.name} fill={[AMBER, NAVY, BLUE, TEAL, SLATE][i % 5]} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            <SampleMixCaveat axis="vehicle_age_category" />
              </Panel>

            <Panel
              title="Fill Rate by Glass Type"
              accent={GREEN}
              note="Despatched units as a share of ordered units. The dashed line is a fully filled type; a bar short of it is demand that was ordered and not met."
            >
              <ResponsiveContainer width="100%" height={215}>
                <BarChart
                  data={glassFill.rows}
                  layout="vertical"
                  margin={{ top: 4, right: 42, left: 4, bottom: 0 }}
                  barCategoryGap="26%"
                >
                  <CartesianGrid horizontal={false} strokeDasharray="3 3" stroke="var(--color-border)" />
                  <XAxis
                    type="number"
                    domain={[0, (max: number) => Math.max(105, Math.ceil(max / 10) * 10)]}
                    tick={TICK}
                    tickFormatter={(v: number) => `${v}%`}
                  />
                  <YAxis
                    type="category"
                    dataKey="name"
                    tick={{ ...TICK, fontSize: 9 }}
                    width={84}
                    tickLine={false}
                  />
                  <ReferenceLine x={100} stroke={SLATE} strokeDasharray="4 4" />
                  <Tooltip
                    contentStyle={TOOLTIP}
                    formatter={(v: number, _n, item) => {
                      const row = item?.payload as {
                        demand_units?: number;
                        despatched_units?: number;
                      };
                      return [
                        `${v}% · ${num(row?.despatched_units)} of ${num(row?.demand_units)} units`,
                        'Fill rate',
                      ];
                    }}
                  />
                  <Bar dataKey="fill_pct" radius={[0, 3, 3, 0]} isAnimationActive={false}>
                    <LabelList
                      dataKey="fill_pct"
                      position="right"
                      formatter={(v: number) => `${v}%`}
                      style={{ fill: 'var(--color-text-muted)', fontSize: 9 }}
                    />
                    {glassFill.rows.map((row) => (
                      <Cell
                        key={row.name}
                        fill={row.fill_pct >= 100 ? GREEN : row.fill_pct >= 95 ? TEAL : AMBER}
                      />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
              {glassFill.unrecorded > 0 && (
                <p className="mt-1 text-[10px] leading-relaxed text-[var(--color-text-muted)]">
                  {glassFill.unrecorded} glass {glassFill.unrecorded === 1 ? 'type is' : 'types are'}{' '}
                  absent: no despatch was recorded against{' '}
                  {glassFill.unrecorded === 1 ? 'it' : 'them'}, which is missing data rather than a
                  zero, so plotting 0% would be wrong.
                </p>
              )}
            </Panel>

            <Panel
              title="Value per Unit by Vehicle Category"
              accent={VIOLET}
              note="Demand value ÷ ordered units — what a unit is actually worth in each segment. Realised from orders, not MRP, which is historical and never used as a forward driver."
            >
              <ResponsiveContainer width="100%" height={215}>
                <BarChart
                  data={vehicleValue}
                  margin={{ top: 16, right: 6, left: -6, bottom: 0 }}
                  barCategoryGap="26%"
                >
                  <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="var(--color-border)" />
                  <XAxis dataKey="short" tick={{ ...TICK, fontSize: 9 }} tickLine={false} interval={0} />
                  <YAxis tick={TICK} width={54} tickFormatter={(v: number) => inr(v)} />
                  <Tooltip
                    contentStyle={TOOLTIP}
                    labelFormatter={(l) => vehicleValue.find((r) => r.short === l)?.name ?? String(l)}
                    formatter={(v: number, _n, item) => {
                      const row = item?.payload as { demand_units?: number; demand_value?: number };
                      return [
                        `${inr(v)} per unit · ${inr(row?.demand_value)} over ${num(row?.demand_units)} units`,
                        'Realised value',
                      ];
                    }}
                  />
                  <Bar dataKey="per_unit" radius={[3, 3, 0, 0]} isAnimationActive={false}>
                    <LabelList
                      dataKey="per_unit"
                      position="top"
                      formatter={(v: number) => inr(v)}
                      style={{ fill: 'var(--color-text-muted)', fontSize: 9 }}
                    />
                    {vehicleValue.map((row, i) => (
                      <Cell key={row.name} fill={[VIOLET, NAVY, BLUE, TEAL][i % 4]} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </Panel>

            <Panel
              title="Volume vs Value by SKU"
              accent={BLUE}
              note="One mark per SKU, sized by how many branch × SKU series it runs in. High and left is a low-volume, high-value product; low and right is the opposite. The bar charts rank on one axis at a time and cannot show this."
            >
              <ResponsiveContainer width="100%" height={215}>
                <ScatterChart margin={{ top: 10, right: 12, left: -4, bottom: 4 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
                  <XAxis
                    type="number"
                    dataKey="demand_units"
                    name="Ordered units"
                    tick={TICK}
                    tickFormatter={(v: number) => num(v)}
                  />
                  <YAxis
                    type="number"
                    dataKey="demand_value"
                    name="Demand value"
                    tick={TICK}
                    width={54}
                    tickFormatter={(v: number) => inr(v)}
                  />
                  <ZAxis type="number" dataKey="series_count" range={[45, 190]} name="Series" />
                  <Tooltip
                    cursor={{ strokeDasharray: '3 3', stroke: 'var(--color-border)' }}
                    content={({ active, payload }) => {
                      if (!active || !payload?.length) return null;
                      const row = payload[0]?.payload as {
                        name?: string;
                        demand_units?: number;
                        demand_value?: number;
                        per_unit?: number;
                        series_count?: number;
                      };
                      return (
                        <div style={TOOLTIP}>
                          <div className="text-[11px] font-semibold">{row?.name}</div>
                          <div className="text-[10.5px]">{num(row?.demand_units)} units ordered</div>
                          <div className="text-[10.5px]">{inr(row?.demand_value)} demand value</div>
                          <div className="text-[10.5px]">{inr(row?.per_unit)} per unit</div>
                          <div className="text-[10.5px] opacity-70">
                            {row?.series_count} branch × SKU series
                          </div>
                        </div>
                      );
                    }}
                  />
                  <Scatter data={skuScatter} isAnimationActive={false}>
                    {skuScatter.map((row, i) => (
                      <Cell
                        key={row.name}
                        fill={SERIES_COLORS[i % SERIES_COLORS.length]}
                        fillOpacity={0.72}
                      />
                    ))}
                  </Scatter>
                </ScatterChart>
              </ResponsiveContainer>
            </Panel>

            <Panel
              title="Unfilled Share by Vehicle Age"
              accent={RED}
              note="Gross positive shortfall as a share of ordered units. Over-despatched lines are excluded from the numerator, so this is not the net figure — the two are reported separately throughout."
            >
              <ResponsiveContainer width="100%" height={215}>
                <BarChart
                  data={ageRisk}
                  layout="vertical"
                  margin={{ top: 4, right: 40, left: 4, bottom: 0 }}
                  barCategoryGap="20%"
                >
                  <CartesianGrid horizontal={false} strokeDasharray="3 3" stroke="var(--color-border)" />
                  <XAxis type="number" tick={TICK} tickFormatter={(v: number) => `${v}%`} />
                  <YAxis
                    type="category"
                    dataKey="short"
                    tick={{ ...TICK, fontSize: 8 }}
                    width={96}
                    tickLine={false}
                  />
                  <Tooltip
                    contentStyle={TOOLTIP}
                    labelFormatter={(l) => ageRisk.find((r) => r.short === l)?.name ?? String(l)}
                    formatter={(v: number, _n, item) => {
                      const row = item?.payload as {
                        shortfall_units?: number;
                        demand_units?: number;
                      };
                      return [
                        `${v}% · ${num(row?.shortfall_units)} of ${num(row?.demand_units)} units`,
                        'Unfilled',
                      ];
                    }}
                  />
                  <Bar dataKey="unfilled_share_pct" radius={[0, 3, 3, 0]} isAnimationActive={false}>
                    <LabelList
                      dataKey="unfilled_share_pct"
                      position="right"
                      formatter={(v: number) => `${v}%`}
                      style={{ fill: 'var(--color-text-muted)', fontSize: 9 }}
                    />
                    {ageRisk.map((row) => (
                      <Cell
                        key={row.name}
                        fill={
                          row.unfilled_share_pct >= 5
                            ? RED
                            : row.unfilled_share_pct >= 1
                              ? AMBER
                              : TEAL
                        }
                      />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </Panel>
          </div>

          {/* Trend row */}
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
            <Panel title="Ordered Demand Trend" accent={BLUE} className="lg:col-span-2">
              <ResponsiveContainer width="100%" height={200}>
                <AreaChart data={trend} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                  <defs>
                    <linearGradient id="demandFill" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor={BLUE} stopOpacity={0.32} />
                      <stop offset="100%" stopColor={BLUE} stopOpacity={0.02} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="var(--color-border)" />
                  <XAxis dataKey="label" tick={TICK} minTickGap={18} tickLine={false} />
                  <YAxis tick={TICK} tickFormatter={(value: number) => num(value)} />
                  <Tooltip formatter={(value: number) => `${num(value)} units`} contentStyle={TOOLTIP} />
                  <Area
                    type="monotone"
                    dataKey="demand_units"
                    name="Ordered units"
                    stroke={BLUE}
                    fill="url(#demandFill)"
                    strokeWidth={2}
                    dot={false}
                    isAnimationActive={false}
                  />
                </AreaChart>
              </ResponsiveContainer>
            </Panel>

            <Panel title="Ordered vs Despatched" accent={TEAL} note="Where the two separate, demand was not filled. A gap in the despatch line is a month with no recorded despatch.">
              <ResponsiveContainer width="100%" height={200}>
                <LineChart data={trend} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                  <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="var(--color-border)" />
                  <XAxis dataKey="label" tick={TICK} minTickGap={22} tickLine={false} />
                  <YAxis tick={TICK} tickFormatter={(value: number) => num(value)} />
                  <Tooltip formatter={(value: number) => `${num(value)} units`} contentStyle={TOOLTIP} />
                  <Legend wrapperStyle={{ fontSize: 10 }} />
                  <Line
                    type="monotone"
                    dataKey="demand_units"
                    name="Ordered"
                    stroke={SLATE}
                    strokeWidth={1.5}
                    strokeDasharray="4 3"
                    dot={false}
                  />
                  <Line
                    type="monotone"
                    dataKey="despatched_units"
                    name="Despatched"
                    stroke={TEAL}
                    strokeWidth={2}
                    dot={false}
                    connectNulls={false}
                  />
                </LineChart>
              </ResponsiveContainer>
            </Panel>
          </div>

          <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
            <Panel title="Unfilled Demand Trend" accent={AMBER}>
              <ResponsiveContainer width="100%" height={180}>
                <AreaChart data={trend} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                  <defs>
                    <linearGradient id="shortfallFill" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor={AMBER} stopOpacity={0.3} />
                      <stop offset="100%" stopColor={AMBER} stopOpacity={0.02} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="var(--color-border)" />
                  <XAxis dataKey="label" tick={TICK} minTickGap={22} tickLine={false} />
                  <YAxis tick={TICK} tickFormatter={(value: number) => num(value)} />
                  <Tooltip formatter={(value: number) => `${num(value)} units`} contentStyle={TOOLTIP} />
                  <Area
                    type="monotone"
                    dataKey="shortfall_units"
                    name="Units short"
                    stroke={AMBER}
                    fill="url(#shortfallFill)"
                    strokeWidth={2}
                    dot={false}
                    isAnimationActive={false}
                  />
                </AreaChart>
              </ResponsiveContainer>
            </Panel>

            <Panel title="Fill Rate" accent={TEAL} note="Dashed line is a fully filled month. Months with no recorded despatch are absent, not zero.">
              <ResponsiveContainer width="100%" height={180}>
                <LineChart data={trend} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                  <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="var(--color-border)" />
                  <XAxis dataKey="label" tick={TICK} minTickGap={22} tickLine={false} />
                  <YAxis tick={TICK} unit="%" />
                  <Tooltip formatter={(value: number) => `${value}%`} contentStyle={TOOLTIP} />
                  <Legend wrapperStyle={{ fontSize: 10 }} />
                  <ReferenceLine y={100} stroke={SLATE} strokeDasharray="4 4" />
                  <Line type="monotone" dataKey="fill_rate_pct" name="Fill rate" stroke={TEAL} strokeWidth={2} dot={false} connectNulls={false} />
                  <Line type="monotone" dataKey="censored_share_pct" name="Short-despatched rows" stroke={AMBER} strokeWidth={1.6} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </Panel>

            <Panel title="Demand Signal Mix" accent={GREEN} note="Ordered demand is the target; a sales-proxy row is a labelled substitute, never the same measurement.">
              <ResponsiveContainer width="100%" height={180}>
                <LineChart data={trend} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                  <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="var(--color-border)" />
                  <XAxis dataKey="label" tick={TICK} minTickGap={22} tickLine={false} />
                  <YAxis tick={TICK} unit="%" />
                  <Tooltip formatter={(value: number) => `${value}%`} contentStyle={TOOLTIP} />
                  <Legend wrapperStyle={{ fontSize: 10 }} />
                  <Line type="monotone" dataKey="order_share_pct" name="Order" stroke={GREEN} strokeWidth={2} dot={false} />
                  <Line type="monotone" dataKey="proxy_share_pct" name="Sales proxy" stroke={SLATE} strokeWidth={1.6} dot={false} />
                  <Line type="monotone" dataKey="censored_share_pct" name="Censored" stroke={RED} strokeWidth={1.6} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </Panel>
          </div>

          <div className="grid grid-cols-1 gap-3 lg:grid-cols-2 xl:grid-cols-4">
            <Panel
              title="Demand by Branch over Time"
              accent={BLUE}
              className="xl:col-span-2"
              note={`One line per branch — the top ${summary.branch_over_time.limit} of ${summary.branch_over_time.total_branches} by value. Click a legend entry to filter.`}
            >
              <ResponsiveContainer width="100%" height={186}>
                <LineChart data={branchOverTime} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                  <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="var(--color-border)" />
                  <XAxis dataKey="label" tick={TICK} minTickGap={22} tickLine={false} />
                  <YAxis tick={TICK} tickFormatter={(value: number) => inr(value)} />
                  <Tooltip formatter={(value: number) => inr(value)} contentStyle={TOOLTIP} />
                  <Legend
                    wrapperStyle={{ fontSize: 10, cursor: 'pointer' }}
                    onClick={(entry: { value?: string }) => entry?.value && toggleBranch(entry.value)}
                  />
                  {summary.branch_over_time.names.map((name, index) => (
                    <Line
                      key={name}
                      type="monotone"
                      dataKey={name}
                      stroke={SERIES_COLORS[index % SERIES_COLORS.length]}
                      strokeWidth={branch === name ? 2.6 : 1.7}
                      strokeOpacity={branch && branch !== name ? 0.3 : 1}
                      dot={false}
                    />
                  ))}
                </LineChart>
              </ResponsiveContainer>
            </Panel>

            <Panel title="Ordered vs Despatched by Value Class" accent={VIOLET} note="Grey = ordered, solid = despatched.">
              <ResponsiveContainer width="100%" height={186}>
                <BarChart data={orderedVsDespatched} margin={{ top: 16, right: 6, left: -12, bottom: 0 }} barCategoryGap="26%">
                  <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="var(--color-border)" />
                  <XAxis dataKey="name" tick={{ ...TICK, fontSize: 9 }} tickLine={false} />
                  <YAxis tick={TICK} tickFormatter={(value: number) => num(value)} />
                  <Tooltip formatter={(value: number) => `${num(value)} units`} contentStyle={TOOLTIP} cursor={{ fill: 'rgba(91,75,183,0.06)' }} />
                  <Legend wrapperStyle={{ fontSize: 9 }} />
                  <Bar dataKey="ordered" name="Ordered" fill="#cbd5e1" radius={[4, 4, 0, 0]} isAnimationActive={false} />
                  <Bar dataKey="despatched" name="Despatched" fill={VIOLET} radius={[4, 4, 0, 0]} isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            </Panel>

            <Panel title="Realised Price per Unit" accent={NAVY} note="Demand value ÷ units. Dashed line is the window average. MRP is historical and is never used as a forecast driver.">
              <ResponsiveContainer width="100%" height={186}>
                <LineChart data={trend} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                  <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="var(--color-border)" />
                  <XAxis dataKey="label" tick={TICK} minTickGap={22} tickLine={false} />
                  <YAxis tick={TICK} tickFormatter={(value: number) => `₹${Math.round(value)}`} />
                  <Tooltip formatter={(value: number) => `₹${Number(value).toFixed(2)}`} contentStyle={TOOLTIP} />
                  {averagePrice != null && (
                    <ReferenceLine
                      y={averagePrice}
                      stroke={SLATE}
                      strokeDasharray="5 4"
                      label={{ value: `avg ₹${averagePrice.toFixed(0)}`, position: 'insideTopRight', fill: SLATE, fontSize: 9 }}
                    />
                  )}
                  <Line type="monotone" dataKey="price_per_unit" name="₹ per unit" stroke={NAVY} strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </Panel>
          </div>

          <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
            <Panel title="Seasonality" accent={GREEN} note="Mean ordered demand per calendar month. The observation count matters: a mean of one month is not a seasonal estimate.">
              <ResponsiveContainer width="100%" height={180}>
                <BarChart data={summary.seasonality} margin={{ top: 16, right: 6, left: -12, bottom: 0 }} barCategoryGap="22%">
                  <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="var(--color-border)" />
                  {/* Single-initial ticks, upright. Twelve months in a
                      third-width panel leaves ~13px per tick, and a rotated
                      three-letter label needs ~17px to stay clear of its
                      neighbour - so rotation cannot solve this one and the
                      label has to get shorter. The sequence runs Jan to Dec, and
                      the tooltip carries the full month name. */}
                  <XAxis
                    dataKey="name"
                    tick={{ ...TICK, fontSize: 9 }}
                    tickLine={false}
                    interval={0}
                    tickFormatter={(value: string) => String(value).slice(0, 1)}
                  />
                  <YAxis tick={TICK} tickFormatter={(value: number) => num(value)} />
                  <Tooltip
                    formatter={(value: number, _name, item) =>
                      [`${num(value)} units`, `${(item?.payload as { observations?: number })?.observations ?? 0} observation(s)`] as [string, string]
                    }
                    contentStyle={TOOLTIP}
                  />
                  <Bar dataKey="mean_demand_units" radius={[4, 4, 0, 0]} isAnimationActive={false}>
                    {summary.seasonality.map((row) => (
                      <Cell key={row.month} fill={GREEN} opacity={row.observations >= 2 ? 1 : 0.45} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
              <p className="mt-1 text-[10px] text-[var(--color-text-muted)]">
                Faded columns rest on a single observation.
              </p>
            </Panel>

            <Panel title="Demand Concentration" accent={TEAL} note="How much of a branch's volume sits in its five largest SKUs.">
              <MiniTable
                rows={summary.concentration.map((row) => ({
                  label: `${row.branch} · ${row.sku_count} SKUs`,
                  value: `${row.top5_share_pct}% in top 5`,
                }))}
              />
            </Panel>

            <Panel title="Coverage" accent={VIOLET} note="Months with observed demand against months in the window. A filled month is an explicit zero, not an observation.">
              <MiniTable
                rows={summary.coverage.map((row) => ({
                  label: row.branch,
                  value: `${row.observed_months} of ${row.window_months} months (${pct(row.coverage_pct, 0)})`,
                }))}
              />
            </Panel>
          </div>

          <BranchScorecardSection
            data={scorecardQuery.data}
            loading={scorecardQuery.isLoading}
            error={scorecardQuery.error as Error | null}
          />

          <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
            <Panel
              title="Top SKUs by Ordered Demand"
              accent={BLUE}
              className="lg:col-span-2"
              note="Filled against unfilled, stacked, so the bar length is total ordered demand and the amber part is what was not supplied. The widest amber band is the product costing the most service, which is not always the biggest seller."
            >
              <ResponsiveContainer width="100%" height={280}>
                <BarChart
                  data={skuRows}
                  layout="vertical"
                  margin={{ top: 4, right: 20, left: 4, bottom: 0 }}
                  barCategoryGap="22%"
                >
                  <CartesianGrid horizontal={false} strokeDasharray="3 3" stroke="var(--color-border)" />
                  <XAxis type="number" tick={TICK} />
                  <YAxis
                    type="category"
                    dataKey="short"
                    tick={{ ...TICK, fontSize: 8 }}
                    width={112}
                    tickLine={false}
                  />
                  <Tooltip
                    contentStyle={TOOLTIP}
                    formatter={(v: number, name: string) => [`${num(v)} units`, name]}
                    labelFormatter={(label) =>
                      skuRows.find((r) => r.short === label)?.name ?? String(label)
                    }
                  />
                  <Legend wrapperStyle={{ fontSize: 9 }} />
                  <Bar dataKey="filled_units" name="Filled" stackId="s" fill={BLUE} isAnimationActive={false} />
                  <Bar
                    dataKey="shortfall_units"
                    name="Unfilled"
                    stackId="s"
                    fill={AMBER}
                    radius={[0, 3, 3, 0]}
                    isAnimationActive={false}
                  />
                </BarChart>
              </ResponsiveContainer>
            </Panel>

            <Panel
              title="Service Risk by SKU"
              accent={RED}
              note="Unfilled demand as a percentage of what was ordered, worst first. A high share on a small SKU is a different problem from a high share on a large one, so the tooltip carries the volume."
            >
              <ResponsiveContainer width="100%" height={280}>
                <BarChart
                  data={[...skuRows].sort((a, b) => b.unfilled_share_pct - a.unfilled_share_pct).slice(0, 8)}
                  layout="vertical"
                  margin={{ top: 4, right: 26, left: 4, bottom: 0 }}
                >
                  <CartesianGrid horizontal={false} strokeDasharray="3 3" stroke="var(--color-border)" />
                  <XAxis type="number" tick={TICK} unit="%" />
                  <YAxis
                    type="category"
                    dataKey="short"
                    tick={{ ...TICK, fontSize: 8 }}
                    width={104}
                    tickLine={false}
                  />
                  <Tooltip
                    contentStyle={TOOLTIP}
                    formatter={(v: number, _n, item) => {
                      const row = item?.payload as { demand_units?: number; shortfall_units?: number };
                      return [
                        `${v}% — ${num(row?.shortfall_units)} of ${num(row?.demand_units)} units short`,
                        'Unfilled share',
                      ];
                    }}
                    labelFormatter={(label) =>
                      skuRows.find((r) => r.short === label)?.name ?? String(label)
                    }
                  />
                  <Bar dataKey="unfilled_share_pct" radius={[0, 3, 3, 0]} isAnimationActive={false}>
                    {[...skuRows]
                      .sort((a, b) => b.unfilled_share_pct - a.unfilled_share_pct)
                      .slice(0, 8)
                      .map((r) => (
                        <Cell key={r.name} fill={r.unfilled_share_pct >= 10 ? RED : AMBER} />
                      ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </Panel>
          </div>

          <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
            <Panel
              title="Concentration by Value Class"
              accent={NAVY}
              className="lg:col-span-2"
              note="The ABC view: bars are ordered units, the line is the running share of total demand. It answers how much of demand sits in how few products."
            >
              <ResponsiveContainer width="100%" height={220}>
                <ComposedChart data={pareto} margin={{ top: 8, right: 8, left: -12, bottom: 0 }}>
                  <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="var(--color-border)" />
                  <XAxis dataKey="name" tick={{ ...TICK, fontSize: 9 }} tickLine={false} interval={0} />
                  <YAxis yAxisId="left" tick={TICK} width={48} />
                  <YAxis
                    yAxisId="right"
                    orientation="right"
                    tick={TICK}
                    width={44}
                    unit="%"
                    domain={[0, 100]}
                    ticks={[0, 50, 100]}
                  />
                  <Tooltip contentStyle={TOOLTIP} />
                  <Legend wrapperStyle={{ fontSize: 9 }} />
                  <Bar
                    yAxisId="left"
                    dataKey="demand_units"
                    name="Ordered units"
                    fill={NAVY}
                    radius={[3, 3, 0, 0]}
                    isAnimationActive={false}
                  />
                  <Line
                    yAxisId="right"
                    type="monotone"
                    dataKey="cumulative_pct"
                    name="Cumulative %"
                    stroke={AMBER}
                    strokeWidth={2}
                    isAnimationActive={false}
                  />
                </ComposedChart>
              </ResponsiveContainer>
            </Panel>

            <Panel
              title="Exception Mix"
              accent={RED}
              note={
                exceptions && !exceptions.empty
                  ? `${num(exceptions.kpis.total_lines)} flagged branch × SKU lines. Severity is fixed per type, not scored.`
                  : 'No exception condition in this selection.'
              }
            >
              {exceptions && !exceptions.empty ? (
                <ResponsiveContainer width="100%" height={220}>
                  <PieChart>
                    <Pie
                      data={exceptions.by_severity}
                      dataKey="lines"
                      nameKey="name"
                      innerRadius={45}
                      outerRadius={80}
                      paddingAngle={2}
                      isAnimationActive={false}
                    >
                      {exceptions.by_severity.map((row) => (
                        <Cell
                          key={row.severity}
                          fill={
                            row.severity === 'critical'
                              ? RED
                              : row.severity === 'high'
                                ? AMBER
                                : SLATE
                          }
                        />
                      ))}
                    </Pie>
                    <Tooltip contentStyle={TOOLTIP} formatter={(v: number) => `${num(v)} lines`} />
                    <Legend wrapperStyle={{ fontSize: 9 }} />
                  </PieChart>
                </ResponsiveContainer>
              ) : (
                <p className="py-6 text-center text-[11px] text-[var(--color-text-muted)]">
                  {exceptionsQuery.isLoading ? 'Reading exceptions…' : 'Nothing flagged.'}
                </p>
              )}
            </Panel>
          </div>

        </>
      )}
    </div>
  );
}

/** Axis tick that prints the value class with its SKU count beneath it —
 *  the reference does the same with a department and its cost centre.
 *
 *  Rotated rather than centred. Two of the six real value classes are `New
 *  Model` and `UNKNOWN`, and six centred labels of that length collide into
 *  each other in a quarter-width panel — the SKU-count line makes it worse,
 *  because it is wider than the name above it. Rotating the whole group keeps
 *  the name and its count together and stops them touching their neighbours.
 */
function ClassTick(props: {
  x?: number;
  y?: number;
  payload?: { value?: string; index?: number };
  rows?: Array<{ sku_count: number }>;
}) {
  const { x = 0, y = 0, payload, rows } = props;
  const count = payload?.index != null ? rows?.[payload.index]?.sku_count : undefined;
  return (
    <g transform={`translate(${x},${y}) rotate(-30)`}>
      <text x={0} y={0} dy={8} textAnchor="end" fontSize={9} fill="var(--color-text-muted)">
        {payload?.value}
      </text>
      {count != null && (
        <text x={0} y={0} dy={18} textAnchor="end" fontSize={8} fill="var(--color-text-muted)" opacity={0.6}>
          {count} SKUs
        </text>
      )}
    </g>
  );
}

const METRIC_ORDER = ['fill_rate', 'short_despatch_share', 'demand_stability', 'coverage'];

function BranchScorecardSection({
  data,
  loading,
  error,
}: {
  data: ReturnType<typeof Object> extends never ? never : import('@/api/analytics').BranchScorecard | undefined;
  loading: boolean;
  error: Error | null;
}) {
  if (loading) return <LoadingBlock label="Scoring branches" />;
  if (error) return <ErrorState error={error} />;
  if (!data || data.empty || !data.branches.length) return null;

  return (
    <div className="flex flex-col gap-3">
      <Panel title="Branch Operational Scorecard" accent={VIOLET} note={data.note}>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-[11px]">
            <thead>
              <tr className="text-[var(--color-text-muted)]">
                <th className="pb-1 pr-3">Measure</th>
                <th className="pb-1 pr-3">Scores 100</th>
                <th className="pb-1 pr-3">Scores 0</th>
                <th className="pb-1">Target</th>
              </tr>
            </thead>
            <tbody>
              {METRIC_ORDER.map((metric) => {
                const scale = data.scales[metric];
                if (!scale) return null;
                return (
                  <tr key={metric} className="border-t border-[var(--color-border)]">
                    <td className="py-1 pr-3 text-[var(--color-text)]">{data.labels[metric] ?? metric}</td>
                    <td className="py-1 pr-3 text-[var(--color-text-muted)]">{scale.good}%</td>
                    <td className="py-1 pr-3 text-[var(--color-text-muted)]">{scale.poor}%</td>
                    <td className="py-1 text-[var(--color-text-muted)]">
                      {scale.higher_is_better ? '≥' : '≤'}
                      {scale.target}%
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Panel>

      {/* Column count follows the number of branches. Fixed at four, a
          two-branch workspace left two empty cells at the end of the row. */}
      <div
        className={`grid grid-cols-1 gap-3 ${
          data.branches.length <= 2
            ? 'lg:grid-cols-2'
            : data.branches.length === 3
              ? 'lg:grid-cols-3'
              : 'lg:grid-cols-2 xl:grid-cols-4'
        }`}
      >
        {data.branches.map((entry) => (
          <ScorecardCard key={entry.branch} entry={entry} scales={data.scales} labels={data.labels} />
        ))}
      </div>
    </div>
  );
}

function ScorecardCard({
  entry,
  scales,
  labels,
}: {
  entry: ScorecardBranch;
  scales: import('@/api/analytics').BranchScorecard['scales'];
  labels: Record<string, string>;
}) {
  return (
    <Card>
      <div className="mb-2 flex items-start gap-2">
        <div className="flex h-11 w-11 shrink-0 flex-col items-center justify-center rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-2)]">
          <span className="text-sm font-bold leading-none text-[var(--color-text)]">{entry.score ?? '—'}</span>
          <span className="text-[8px] uppercase tracking-wide text-[var(--color-text-muted)]">score</span>
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5 text-[10px]">
            <span className="font-semibold text-[var(--color-text-muted)]">#{entry.rank}</span>
            <span className={entry.off_target.length ? 'text-[var(--color-danger)]' : 'text-[var(--color-text-muted)]'}>
              {entry.off_target.length
                ? `${entry.off_target.length}/${METRIC_ORDER.length} off target`
                : 'all on target'}
            </span>
          </div>
          <div className="truncate text-[11px] font-semibold text-[var(--color-text)]">{entry.branch}</div>
          <div className="mt-0.5 text-[9px] text-[var(--color-text-muted)]">
            {num(entry.demand_units)} units · {inr(entry.demand_value)} · {entry.sku_count} SKUs
          </div>
        </div>
      </div>
      <div className="flex flex-col gap-2">
        {METRIC_ORDER.map((metric) => {
          const scale = scales[metric];
          if (!scale) return null;
          return (
            <MetricBar
              key={metric}
              label={labels[metric] ?? metric}
              score={entry.score_components[metric] ?? null}
              value={entry.metric_values[metric] ?? null}
              scale={scale}
            />
          );
        })}
      </div>
      {entry.worst_metric && (
        <div className="mt-2 rounded bg-[var(--color-surface-2)] px-2 py-1.5 text-[10px]">
          <span className="font-medium text-[var(--color-text)]">Focus: </span>
          <span className="text-[var(--color-text-muted)]">{labels[entry.worst_metric] ?? entry.worst_metric}</span>
        </div>
      )}
    </Card>
  );
}

function MetricBar({
  label,
  score,
  value,
  scale,
}: {
  label: string;
  score: number | null;
  value: number | null;
  scale: { good: number; poor: number; target: number; higher_is_better: boolean };
}) {
  const targetPosition = Math.max(
    0,
    Math.min(100, ((scale.poor - scale.target) / (scale.poor - scale.good)) * 100),
  );
  const meetsTarget =
    value == null ? null : scale.higher_is_better ? value >= scale.target : value <= scale.target;
  return (
    <div>
      <div className="flex items-baseline justify-between">
        <span className="text-[10px] text-[var(--color-text-muted)]">{label}</span>
        <span className="text-[11px] font-semibold text-[var(--color-text)]">
          {value == null ? '—' : `${value}%`}
        </span>
      </div>
      <div className="relative mt-1 h-2 w-full overflow-hidden rounded-full bg-[var(--color-surface-2)]">
        <div
          className="h-full rounded-full"
          style={{ width: `${score ?? 0}%`, background: meetsTarget === false ? SLATE : 'var(--color-primary)' }}
        />
        <div
          className="absolute top-0 h-full border-l border-dashed border-[var(--color-text-muted)]"
          style={{ left: `${targetPosition}%` }}
        />
      </div>
      <div className="mt-0.5 text-[9px] text-[var(--color-text-muted)]">
        {score != null && <span className="text-[var(--color-text)]">{score}/100</span>}
        {' · target '}
        {scale.higher_is_better ? '≥' : '≤'}
        {scale.target}%
        {meetsTarget === false && <span className="font-medium text-[var(--color-danger)]"> · off target</span>}
      </div>
    </div>
  );
}
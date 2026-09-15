/**
 * Demand Analytics — the AIS port of the reference's Labor Analytics page.
 *
 * Panel-for-panel and interaction-for-interaction: the filter bar, four KPI
 * tiles with their own sparklines, a doughnut with clickable segments, bar
 * charts with value labels, a stacked cross-tab, the trend row, an efficiency
 * chart with a reference line, a multi-line per-branch trend whose legend
 * filters, two MiniTable panels, and the scorecard.
 *
 * What changed is the domain, not the shape. Branch replaces site, value class
 * replaces department, ordered demand replaces labour cost, and despatch
 * replaces hours worked — the mapping table is in
 * `docs/UI_VISUAL_PARITY.md` §2 and in `app/domain/ais/analytics.py`.
 *
 * The one deliberate structural difference: the reference offers a
 * daily/weekly/monthly grain selector. AIS demand history is monthly, so the
 * control offers monthly and a real quarterly roll-up and says why the others
 * are absent. Splitting monthly rows into days would be inventing data.
 */
import { useMemo, useState } from 'react';
import { MonthRange } from '@/components/ui/MonthRange';
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
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import {
  analyticsKeys,
  fetchAnalyticsFilters,
  fetchAnalyticsSummary,
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

export function DemandAnalyticsPage() {
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

  const anyFilter = branch || valueClass || startPeriod || endPeriod;
  const rangeInvalid = !!(startPeriod && endPeriod && startPeriod > endPeriod);

  return (
    <div className="flex flex-col gap-5">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[var(--color-primary)]">
            Demand Analytics
          </p>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight text-[var(--color-text)]">
            Where the demand actually is.
          </h1>
          <p className="mt-1 max-w-2xl text-sm text-[var(--color-text-muted)]">
            Ordered demand by branch, value class and month, against what was despatched. Click any
            column, slice or legend entry to filter the whole page.
          </p>
        </div>
        <Link
          to="/assistant"
          className="rounded-lg border border-[var(--color-primary)] px-3 py-1.5 text-xs font-medium text-[var(--color-primary)] hover:bg-[var(--color-primary)]/10"
        >
          Ask the assistant
        </Link>
      </header>

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
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-2 xl:grid-cols-4">
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
              title="Demand by Branch × Value Class"
              accent={VIOLET}
              className="xl:col-span-2"
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

          <Card>
            <h3 className="text-[11px] font-semibold uppercase tracking-[0.06em] text-[var(--color-text)]">
              How these measures are defined
            </h3>
            <ul className="mt-2 flex flex-col gap-1.5">
              {summary.notes.map((note) => (
                <li key={note} className="text-[11px] leading-relaxed text-[var(--color-text-muted)]">
                  {note}
                </li>
              ))}
            </ul>
          </Card>
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

      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2 xl:grid-cols-4">
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
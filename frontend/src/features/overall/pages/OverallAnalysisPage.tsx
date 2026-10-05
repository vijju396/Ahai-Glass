/**
 * Overall Analysis — every demand visual, for the whole workspace.
 *
 * This is the Demand Analytics page: the same sixteen panels, the same
 * cross-filtering, the same calendar range picker and branch scorecard. It
 * was rebuilt from that page rather than re-implemented, because those panels
 * were already verified and re-typing them would have risked regressions for
 * nothing.
 *
 * **Demand signal mix** is the one panel here that has to stay. It shows the
 * share of rows sourced from a real purchase order rather than the invoiced
 * proxy. Everything before Apr 2025 is proxy, so a trend crossing that line
 * compares two different measurements — the single most misleading thing on
 * the page if it is not shown.
 *
 * The page is **description only**. It carries no forecast accuracy, no
 * champion, no model figure of any kind: accuracy is answered on Training and
 * on Forecasting, and repeating it here invited the reading that a demand
 * summary was a model result. A Pareto panel and an exception-severity donut
 * were also dropped (D-101) — neither answered a question about demand that
 * another panel on this page did not already answer better.
 *
 * Everything is read from `/analytics/summary` and
 * `/analytics/branch-scorecard`, both already cut to the workspace. This page
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
  ComposedChart,
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
} from 'recharts';
import {
  analyticsKeys,
  fetchAnalyticsFilters,
  fetchAnalyticsSummary,
  type AnalyticsQuery,
} from '@/api/analytics';
import {
  AMBER,
  BLUE,
  Card,
  ClearChip,
  GREEN,
  LABEL,
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
import { Explain } from '@/components/ui/Explain';
import { grainOptionLabel, periodNoun, shortPeriod } from '../../../app/period';

const SELECT_CLASS =
  'rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-2.5 py-1.5 text-xs text-[var(--color-text)]';

/** `2026-07` → `Jul 26`; a quarterly bucket is already short enough. */

export function OverallAnalysisPage() {
  const [branch, setBranch] = useState('');
  const [valueClass, setValueClass] = useState('');
  const [startPeriod, setStartPeriod] = useState('');
  const [endPeriod, setEndPeriod] = useState('');
  const [grain, setGrain] = useState('monthly');

  /* This page reports the client's whole network - every branch, every SKU -
     while Training, Forecasting and Per Branch & SKU stay on the workspace.
     The banner states which, and the payload's `workspace_scope` carries
     `restricted: false`, so a network total can never be read as a workspace
     one (D-138). */
  const filtersQuery = useQuery({
    queryKey: analyticsKeys.networkFilters,
    queryFn: () => fetchAnalyticsFilters(true),
  });
  const filters = filtersQuery.data;

  /* With no FROM chosen, the page starts at the first month holding real
     orders. Before it the panel is sales proxy only - no order and no
     despatch - so including it made every total on the page disagree with
     the ordered-vs-despatched tiles (docs/DECISIONS.md D-122). Picking an
     earlier month in FROM still reaches that history. */
  const ordersStart = filters?.orders_start_month ?? '';
  // Never earlier than the orders window: before it there are no orders, and
  // including those weeks made every panel total more than the tiles.
  const effectiveStart = startPeriod && startPeriod > ordersStart ? startPeriod : ordersStart;

  const query: AnalyticsQuery = useMemo(
    () => ({
      branch: branch || undefined,
      value_class: valueClass || undefined,
      start_period: effectiveStart || undefined,
      end_period: endPeriod || undefined,
      grain,
    }),
    [branch, valueClass, effectiveStart, endPeriod, grain],
  );

  const summaryQuery = useQuery({
    queryKey: analyticsKeys.networkSummary(query),
    queryFn: () => fetchAnalyticsSummary(query, true),
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

  /** Every SKU ranked by ordered units, with the running share of the total.
   *  `core` marks the SKUs up to and including the one that crosses 80%. Uses
   *  `by_sku` whole — not the top-12 cut above — because a running share of a
   *  truncated list would never reach 100%. */
  const pareto = useMemo(() => {
    const ranked = [...(summary?.by_sku ?? [])]
      .filter((r) => (r.demand_units || 0) > 0)
      .sort((a, b) => (b.demand_units || 0) - (a.demand_units || 0));
    const total = ranked.reduce((sum, r) => sum + (r.demand_units || 0), 0);
    // Ordered value, so the tooltip can say what a SKU is worth as well as how
    // many of it were ordered. The two rankings are not the same: a cheap
    // high-volume SKU and an expensive low-volume one swap places.
    const valueTotal = ranked.reduce((sum, r) => sum + (r.demand_value || 0), 0);
    let running = 0;
    let eighty = 0;
    const rows = ranked.map((r, index) => {
      const before = running;
      running += r.demand_units || 0;
      const core = total > 0 && before / total < 0.8;
      if (core) eighty = index + 1;
      return {
        name: r.name,
        short: r.name.replace(/^FG\./, '').slice(0, 22),
        demand_units: r.demand_units,
        cumulative_pct: total > 0 ? Math.round((1000 * running) / total) / 10 : 0,
        // One decimal, not a whole number: at 136 SKUs most shares are under
        // 1%, and rounding them to "0%" printed a row of zeroes along the
        // baseline that said nothing and hid the labels that mattered.
        share_pct: total > 0 ? Math.round((1000 * (r.demand_units || 0)) / total) / 10 : 0,
        demand_value: r.demand_value || 0,
        value_pct: valueTotal > 0 ? Math.round((1000 * (r.demand_value || 0)) / valueTotal) / 10 : 0,
        core,
      };
    });
    // The top group's real share: it includes the SKU that crosses 80%, so it
    // is usually a little above 80.
    const coreShare = eighty > 0 ? Math.round(rows[eighty - 1]?.cumulative_pct ?? 0) : 0;
    return { rows, eighty, coreShare };
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

  const anyFilter = branch || valueClass || startPeriod || endPeriod;
  const rangeInvalid = !!(effectiveStart && endPeriod && effectiveStart > endPeriod);

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
          <Explain label="About this page" variant="note">
            Ordered demand by branch, value class and month, against what was despatched. Click
            any column, slice or legend entry to filter the whole page, or{' '}
            <Link to="/series" className="text-link">
              go per branch and SKU
            </Link>{' '}
            for one series at a time.
          </Explain>
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
            from={effectiveStart}
            to={endPeriod}
            onFromChange={setStartPeriod}
            onToChange={setEndPeriod}
            first={filters?.orders_start_period ?? filters?.period_range?.min}
            last={filters?.period_range?.max}
            months={filters?.orders_periods ?? filters?.periods.length}
            minMonth={ordersStart || undefined}
            resetLabel="Reset dates"
            periodNoun={periodNoun(filters?.panel_grain)}
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
                {grainOptionLabel(option)}
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
              {summary.window.start} → {summary.window.end} · {summary.window.periods}{' '}
              {periodNoun(filters?.panel_grain)}
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
          <SectionLinks />

          {/* KPI tiles — orders in, sales out, and the difference between
                them, all three on ONE set of rows so they reconcile exactly:
                tile 1 − tile 2 = tile 3. Total ordered value is larger than
                tile 1 and is deliberately not shown here; it covers rows that
                carry no despatch figure at all, and subtracting sales from it
                would report a gap in the data as an undelivered order
                (docs/DECISIONS.md D-121). */}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <StatTile
              label="Orders received"
              value={inr(summary.kpis.ordered_value_known)}
              sublabel={`${num(summary.kpis.ordered_units_known)} units ordered`}
              spark={trend}
              sparkKey="ordered_value_known"
              tint="blue"
              accent
            />
            <StatTile
              label="Sales despatched"
              value={inr(summary.kpis.despatch_value)}
              sublabel={`${num(summary.kpis.despatched_units)} units despatched`}
              spark={trend}
              sparkKey="despatch_value"
              tint="teal"
            />
            <StatTile
              label="Orders not despatched"
              value={inr(summary.kpis.gap_value)}
              sublabel={`${num(summary.kpis.gap_units)} units · ${pct(summary.kpis.fill_rate_value_pct)} of orders covered`}
              spark={trend}
              sparkKey="gap_value"
              tint="amber"
            />
          </div>
          {/* The page never reaches before the orders window, so the tiles and
                every panel below are the same rows and their totals agree. The
                one figure that legitimately differs is the unfilled count. */}
          <p className="-mt-1 text-[10px] text-[var(--color-text-muted)]">
            Every figure on this page covers {summary.window.start} → {summary.window.end}. Order data
            starts in {summary.window.start}; the weeks before it hold sales figures only, so they are
            not shown. Unfilled panels below count only lines that were short ({num(summary.kpis.shortfall_units)} units);
            lines that were over-despatched bring the net figure on the tile down to{' '}
            {num(summary.kpis.gap_units)}.
          </p>

          <section id="sec-demand" className="flex scroll-mt-4 flex-col gap-3">
            <SectionHeader title="Where the demand comes from" question="Which branches, products and vehicles drive orders?" />
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-2 xl:grid-cols-4">
            <Panel className="lg:col-span-2 xl:col-span-2"
              title="Demand by Branch × Value Class"
              accent={VIOLET}
              note="Each column is a branch, split by value class. Click a column to filter."
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
                    {summary.kpis.branch_count > 10
                      ? `top 10 of ${summary.kpis.branch_count}`
                      : `${summary.kpis.branch_count} branches`}
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

            <Panel
              title="Demand by Glass Type"
              accent={TEAL}
              note="Laminated windscreens, sidelites and backlites."
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
              note="Ordered units by vehicle category."
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
              note="Ordered units by vehicle age band."
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
              title="Value per Unit by Vehicle Category"
              accent={VIOLET}
              note="Ordered value ÷ ordered units, per segment."
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
              className="xl:col-span-2"
              title="Volume vs Value by SKU"
              accent={BLUE}
              note="One mark per SKU: ordered units against ordered value."
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

            {/* Last in the section and full width: 136 SKUs cannot be read in a
                half-width panel, and every chart above it is a summary this one
                breaks down. */}
            <Panel
              className="lg:col-span-2 xl:col-span-4"
              title="The SKUs That Carry the Demand"
              accent={NAVY}
              note={
                pareto.rows.length
                  ? `All ${pareto.rows.length} SKUs, tallest first. Navy bars are the ones that make up the first ${pareto.coreShare}% of ordered units. Labels show each SKU's share of units; shares under 1% are left off and read off the tooltip, which also gives ordered value and its share of the money.`
                  : 'SKUs ranked by ordered units.'
              }
            >
              {/* A floor width, then scroll. Below about 1,200px the 136 SKU
                  labels start to touch each other, and an unreadable axis is
                  worse than a scrollbar. */}
              <div className="overflow-x-auto">
                <div className="min-w-[1200px]">
              <ResponsiveContainer width="100%" height={560}>
                <ComposedChart data={pareto.rows} margin={{ top: 46, right: 8, left: 4, bottom: 0 }}>
                  <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="var(--color-border)" />
                  <XAxis
                    dataKey="short"
                    tick={{ ...TICK, fontSize: 9 }}
                    tickLine={false}
                    interval={0}
                    angle={-90}
                    textAnchor="end"
                    height={176}
                  />
                  <YAxis yAxisId="units" tick={TICK} tickFormatter={(value: number) => num(value)} width={56} />
                  {/* Written out rather than left to Recharts' "name : value"
                      line, which put the money in the label slot and read
                      backwards. Units and value each get their own line. */}
                  <Tooltip
                    cursor={{ fill: 'var(--color-surface-2)' }}
                    content={({ active, payload }) => {
                      const row = active ? payload?.[0]?.payload : null;
                      if (!row) return null;
                      return (
                        <div style={{ ...TOOLTIP, padding: '8px 10px', lineHeight: 1.55 }}>
                          <div style={{ fontWeight: 600, marginBottom: 4 }}>{row.name}</div>
                          <div>
                            {num(row.demand_units)} units · <strong>{row.share_pct}%</strong> of all ordered units
                          </div>
                          <div>
                            {inr(row.demand_value)} · <strong>{row.value_pct}%</strong> of all ordered value
                          </div>
                        </div>
                      );
                    }}
                  />
                  <Bar yAxisId="units" dataKey="demand_units" name="Ordered units" radius={[2, 2, 0, 0]} isAnimationActive={false}>
                    {pareto.rows.map((r) => (
                      <Cell key={r.name} fill={r.core ? NAVY : '#cbd5e1'} />
                    ))}
                    {/* Rotated like the axis. Bars sit about 8px apart, so a
                        horizontal "5.6%" overlapped its neighbours. */}
                    <LabelList
                      dataKey="share_pct"
                      position="top"
                      angle={-90}
                      offset={18}
                      formatter={(v: number) => (v >= 1 ? `${v}%` : '')}
                      style={{ ...LABEL, fontSize: 9 }}
                    />
                  </Bar>
                </ComposedChart>
              </ResponsiveContainer>
                </div>
              </div>
            </Panel>
          </div>
          </section>

          <section id="sec-time" className="flex scroll-mt-4 flex-col gap-3">
            <SectionHeader title="How demand moves over time" question="Is it growing, and when does it peak?" />
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-2 xl:grid-cols-4">
            <Panel className="xl:col-span-2" title="Ordered Demand Trend" accent={BLUE}>
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

            <Panel className="xl:col-span-2"
              title="Demand by Branch over Time"
              accent={BLUE}
              note="One line per branch. Click a legend entry to filter."
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

            <Panel className="xl:col-span-2" title="Seasonality" accent={GREEN} note="Mean ordered units per calendar month.">
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

            <Panel className="xl:col-span-2" title="Realised Price per Unit" accent={NAVY} note="Ordered value ÷ units. Dashed line is the average.">
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
          </section>

          <section id="sec-deliver" className="flex scroll-mt-4 flex-col gap-3">
            <SectionHeader title="How well we deliver" question="Where are we letting customers down?" />
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-2 xl:grid-cols-4">
            <Panel
              className="xl:col-span-2"
              title="Ordered vs Despatched"
              accent={TEAL}
              note="The gap between the lines is what was not despatched. Fill rate reads on the right."
            >
              {/* One chart for what used to be three - ordered vs despatched,
                  unfilled over time, and fill rate - because all three were the
                  same two series drawn three ways (docs/DECISIONS.md D-123). */}
              <ResponsiveContainer width="100%" height={240}>
                <ComposedChart data={trend} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
                  <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="var(--color-border)" />
                  <XAxis dataKey="label" tick={TICK} minTickGap={22} tickLine={false} />
                  <YAxis yAxisId="units" tick={TICK} tickFormatter={(value: number) => num(value)} />
                  <YAxis yAxisId="pct" orientation="right" tick={TICK} unit="%" domain={[0, 120]} />
                  <Tooltip
                    formatter={(value: number, name: string) =>
                      name === 'Fill rate' ? `${value}%` : `${num(value)} units`
                    }
                    contentStyle={TOOLTIP}
                  />
                  <Legend wrapperStyle={{ fontSize: 10 }} />
                  <ReferenceLine yAxisId="pct" y={100} stroke={SLATE} strokeDasharray="4 4" />
                  <Area
                    yAxisId="units"
                    type="monotone"
                    dataKey="demand_units"
                    name="Ordered"
                    stroke={BLUE}
                    fill={BLUE}
                    fillOpacity={0.08}
                    strokeWidth={2}
                    dot={false}
                    isAnimationActive={false}
                  />
                  <Line
                    yAxisId="units"
                    type="monotone"
                    dataKey="despatched_units"
                    name="Despatched"
                    stroke={TEAL}
                    strokeWidth={2}
                    dot={false}
                    connectNulls={false}
                  />
                  <Line
                    yAxisId="pct"
                    type="monotone"
                    dataKey="fill_rate_pct"
                    name="Fill rate"
                    stroke={AMBER}
                    strokeWidth={1.5}
                    strokeDasharray="4 3"
                    dot={false}
                    connectNulls={false}
                  />
                </ComposedChart>
              </ResponsiveContainer>
            </Panel>

            <Panel className="xl:col-span-2"
              title="Top SKUs by Ordered Demand"
              accent={BLUE}
              note="Bar length is units ordered; amber is the part not despatched."
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
              title="Fill Rate by Glass Type"
              accent={GREEN}
              note="Despatched ÷ ordered units. Dashed line is fully filled."
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
              title="Unfilled Share by Vehicle Age"
              accent={RED}
              note="Units short ÷ units ordered, by vehicle age band."
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
          </div>
          </section>

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

const SECTIONS = [
  { id: 'sec-demand', label: 'Where demand comes from' },
  { id: 'sec-time', label: 'Over time' },
  { id: 'sec-deliver', label: 'How well we deliver' },
];

/** Jump links to the page's three sections. Buttons that scroll, rather than
 *  `#hash` links, so the router never sees a navigation. */
function SectionLinks() {
  return (
    <nav aria-label="Page sections" className="flex flex-wrap gap-2">
      {SECTIONS.map((section) => (
        <button
          key={section.id}
          type="button"
          onClick={() => document.getElementById(section.id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })}
          className="rounded-full border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-1 text-[11px] font-medium text-[var(--color-text)] hover:border-[var(--color-primary)] hover:text-[var(--color-primary)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--color-primary)]"
        >
          {section.label}
        </button>
      ))}
    </nav>
  );
}

function SectionHeader({ title, question }: { title: string; question: string }) {
  return (
    <header className="mt-3 border-b border-[var(--color-border)] pb-2">
      <h2 className="text-base font-semibold tracking-tight text-[var(--color-text)]">{title}</h2>
      <p className="text-[11px] text-[var(--color-text-muted)]">{question}</p>
    </header>
  );
}

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
import { SampleMixCaveat } from '@/components/ui/SampleMixCaveat';
import { keepPreviousData, useQuery } from '@tanstack/react-query';
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

/* `num` abbreviates - 2063 becomes "2.1K". That is right on a chart axis and
   wrong on a count the reader is being asked to take literally: "2.1K of 2.1K
   SKUs" hides whether the two are the same number (D-143). */
const exact = (value: number) => value.toLocaleString('en-IN');

/** `2026-07` → `Jul 26`; a quarterly bucket is already short enough. */

export function OverallAnalysisPage() {
  const [branch, setBranch] = useState('');
  const [valueClass, setValueClass] = useState('');
  /* The three product axes the page charts in "Where the demand comes from".
     They were drawn but not selectable, so a reader could see that CAR & MUV
     carries the demand and had no way to ask what the trend, the fill rate and
     the top SKUs look like for CAR & MUV alone (D-141). */
  const [glassType, setGlassType] = useState('');
  const [vehicleCategory, setVehicleCategory] = useState('');
  const [vehicleAge, setVehicleAge] = useState('');
  /* No start/end state any more: the month-range picker is gone (D-143) and
     the window is the order book's own extent. */
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

  /* The page starts at the first month holding real orders. Before it the
     panel is sales proxy only - no order and no despatch - so including it
     made every total on the page disagree with the ordered-vs-despatched
     tiles (D-122). This used to be the floor under a FROM the reader could
     move; with the picker gone (D-143) it is simply the window. */
  const effectiveStart = filters?.orders_start_month ?? '';

  const query: AnalyticsQuery = useMemo(
    () => ({
      branch: branch || undefined,
      value_class: valueClass || undefined,
      glass_type: glassType || undefined,
      vehicle_category: vehicleCategory || undefined,
      vehicle_age_category: vehicleAge || undefined,
      start_period: effectiveStart || undefined,
      grain,
    }),
    [branch, valueClass, glassType, vehicleCategory, vehicleAge, effectiveStart, grain],
  );

  /* `keepPreviousData` is what makes a filter change feel like a filter change
     rather than a page load. Without it the key changes, `data` goes
     `undefined`, every panel below unmounts, the document collapses to the
     height of the filter bar and the browser drops the reader at the top —
     then the payload arrives and the page grows back under them. Holding the
     previous payload keeps the document the same height, so the scroll
     position survives and only the numbers change (D-142). */
  const summaryQuery = useQuery({
    queryKey: analyticsKeys.networkSummary(query),
    queryFn: () => fetchAnalyticsSummary(query, true),
    enabled: !!filters,
    placeholderData: keepPreviousData,
  });

  const summary = summaryQuery.data;

  /** Cross-filter: clicking a slice, column or legend entry sets the matching
   *  page filter, and clicking the already-selected item clears it. Same
   *  behaviour as the reference, which is what makes the dimming below read as
   *  a selection rather than a bug. */
  const toggleBranch = (name: string) => setBranch((current) => (current === name ? '' : name));
  const toggleValueClass = (name: string) => setValueClass((current) => (current === name ? '' : name));

  // `dimBranch` went with the branch donut (D-140): nothing on this page now
  // dims by branch, and the active filter shows as a clear-chip on the panel.
  const dimClass = (name: string) => (valueClass && name !== valueClass ? 0.28 : 1);

  const trend = useMemo(
    () => (summary?.trend ?? []).map((point) => ({ ...point, label: shortPeriod(point.period) })),
    [summary],
  );
  const branchOverTime = useMemo(
    () => (summary?.branch_over_time?.data ?? []).map((row) => ({ ...row, label: shortPeriod(String(row.period)) })),
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

  /** Volume against value, one mark per SKU, cut into the four groups a
   *  planner treats differently.
   *
   *  The bar charts rank on one axis at a time and so cannot show the thing
   *  that matters for planning: a low-volume SKU can sit high on value, and it
   *  is the position off the diagonal that identifies it. This panel replaced
   *  a 2,063-bar Pareto that answered the same question by making the reader
   *  count bars (D-139).
   *
   *  **The cuts are Pareto, not medians.** A SKU is core *volume* if it falls
   *  inside the set making up the first 80% of ordered units, and core *value*
   *  if it falls inside the set making the first 80% of ordered value. A
   *  median split on a catalogue this long-tailed lands near zero and would
   *  call half the tail "high". The two sets are deliberately computed
   *  separately: that they disagree is the finding, not a rounding artefact.
   */
  const skuMix = useMemo(() => {
    const rows = (summary?.by_sku ?? []).filter(
      (r) => (r.demand_units || 0) > 0 && (r.demand_value || 0) > 0,
    );
    const unitTotal = rows.reduce((sum, r) => sum + (r.demand_units || 0), 0);
    const valueTotal = rows.reduce((sum, r) => sum + (r.demand_value || 0), 0);

    /** The SKUs making the first 80% of `key`, and the value of the last one
     *  in — which is where the threshold line is drawn. */
    const coreOf = (key: 'demand_units' | 'demand_value') => {
      const ranked = [...rows].sort((a, b) => (b[key] || 0) - (a[key] || 0));
      const total = ranked.reduce((sum, r) => sum + (r[key] || 0), 0);
      const names = new Set<string>();
      let running = 0;
      let cut = 0;
      for (const row of ranked) {
        if (total > 0 && running / total >= 0.8) break;
        running += row[key] || 0;
        names.add(row.name);
        cut = row[key] || 0;
      }
      return { names, cut };
    };
    const volume = coreOf('demand_units');
    const value = coreOf('demand_value');

    const marks = rows.map((r) => {
      const bigVolume = volume.names.has(r.name);
      const bigValue = value.names.has(r.name);
      return {
        name: r.name,
        short: r.name.replace(/^FG\./, '').slice(0, 20),
        demand_units: r.demand_units,
        demand_value: r.demand_value,
        per_unit: Math.round((r.demand_value / r.demand_units) * 100) / 100,
        series_count: r.series_count,
        segment: bigVolume && bigValue ? 'both' : bigValue ? 'value' : bigVolume ? 'volume' : 'tail',
      };
    });

    const share = (n: number, total: number) =>
      total > 0 ? Math.round((1000 * n) / total) / 10 : 0;

    const segments = (
      [
        // Named by what the group does, not by which set it is in. "Value
        // without volume" described the arithmetic and read as a judgement on
        // the SKU; "Less volume, more revenue" says the thing itself.
        { key: 'both', label: 'Most revenue and most volume', colour: NAVY },
        { key: 'value', label: 'Less volume, more revenue', colour: VIOLET },
        { key: 'volume', label: 'More volume, less revenue', colour: TEAL },
        { key: 'tail', label: 'Low on both', colour: SLATE },
      ] as const
    ).map((segment) => {
      const members = marks.filter((m) => m.segment === segment.key);
      const units = members.reduce((sum, m) => sum + (m.demand_units || 0), 0);
      const money = members.reduce((sum, m) => sum + (m.demand_value || 0), 0);
      return {
        ...segment,
        count: members.length,
        sku_pct: share(members.length, marks.length),
        units,
        unit_pct: share(units, unitTotal),
        value: money,
        value_pct: share(money, valueTotal),
      };
    });

    /** Ticks on the decades. Recharts' own log ticks land on the data's
     *  quantiles — "2, 3, 5, 7, 12, 18, 27 …" — which is a crowded axis
     *  whose gridlines mean nothing in particular. Powers of ten are what a
     *  log axis is for. */
    const decades = (values: number[]) => {
      const usable = values.filter((v) => v > 0);
      if (!usable.length) return undefined;
      const ticks: number[] = [];
      for (
        let tick = 10 ** Math.floor(Math.log10(Math.min(...usable)));
        tick <= Math.max(...usable) * 10;
        tick *= 10
      ) {
        ticks.push(tick);
      }
      return ticks;
    };

    return {
      marks,
      segments,
      unitCut: volume.cut,
      valueCut: value.cut,
      total: marks.length,
      unitTicks: decades(marks.map((m) => m.demand_units || 0)),
      valueTicks: decades(marks.map((m) => m.demand_value || 0)),
    };
  }, [summary]);

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

  /** The product axes in the filter bar, declared once and rendered in a loop.
   *  Written out three times they drifted apart in the first draft — one
   *  missing its `aria-label`, another its chip. `options` is optional on the
   *  payload, so a backend that predates these lists renders an "All …" select
   *  with nothing in it rather than throwing. */
  const productFilters = [
    { key: 'glass', all: 'All glass types', aria: 'Glass type',
      value: glassType, set: setGlassType, options: filters?.glass_types },
    { key: 'vehicle', all: 'All vehicle categories', aria: 'Vehicle category',
      value: vehicleCategory, set: setVehicleCategory, options: filters?.vehicle_categories },
    { key: 'age', all: 'All vehicle ages', aria: 'Vehicle age',
      value: vehicleAge, set: setVehicleAge, options: filters?.vehicle_age_categories },
  ];
  const clearAll = () => {
    setBranch('');
    setValueClass('');
    setGlassType('');
    setVehicleCategory('');
    setVehicleAge('');
  };

  /** How much of the client's data the page is counting, under the current
   *  filters. Both sides of each ratio are taken on the order book:
   *  `ordered_sku_count` rather than `sku_count`, because the latter includes
   *  SKUs carried only by the pre-order sales proxy and printed "2,315 of
   *  2,063" against the order-book denominator (D-143). Falls back to the
   *  unqualified counts if an older payload has no ordered-only figures. */
  const counts = useMemo(() => {
    if (!summary || summary.empty) return null;
    const scope = summary.workspace_scope;
    return {
      branches: summary.kpis.ordered_branch_count ?? summary.kpis.branch_count,
      skus: summary.kpis.ordered_sku_count ?? summary.kpis.sku_count,
      totalBranches: scope?.total_branches,
      totalSkus: scope?.total_skus,
    };
  }, [summary]);

  const anyFilter = branch || valueClass || glassType || vehicleCategory || vehicleAge;

  /* How many years each Seasonality bar averages, said once under the chart
     instead of on every hover (D-145). Always two or three on this window. */
  const seasonSpan = useMemo(() => {
    const years = (summary?.seasonality ?? []).map((m) => m.observations).filter((n) => n > 0);
    if (!years.length) return 'Each column averages the years in the window';
    const low = Math.min(...years);
    const high = Math.max(...years);
    return low === high
      ? `Each column averages ${low} year${low === 1 ? '' : 's'}`
      : `Each column averages ${low}–${high} years`;
  }, [summary]);

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

      {/* The scope banner was removed from this page (D-142). It read
          "53 of 53 branches · 2063 of 2063 SKUs · the client's whole dataset",
          and the page's own lede already says it describes every branch and
          SKU in the source data. The component is unchanged and still renders
          on every page where the scope IS restricted and therefore worth
          stating. */}

      {/* Filter bar. Sticky, because the page is four screens tall and a
          reader looking at the delivery panels at the bottom should be able to
          change the branch without scrolling back up for it.
          `top-0` against the window, which is the scroll container on desktop;
          under 800 px the topbar itself turns sticky at 72 px, so the bar
          clears it there. The wrapper carries the page background and a
          symmetric `-my-2`/`py-2`, so content scrolling underneath disappears
          behind the bar instead of showing through the layout gap. */}
      <div className="sticky top-0 z-20 -my-2 bg-[var(--color-bg)] py-2 max-[800px]:top-[72px]">
      <Card className="!py-2.5">
        <div className="flex flex-wrap items-center gap-2 text-xs">
          {/* The month-range picker was removed (D-143). The window is now
              fixed at the order book's own extent — `effectiveStart` still
              pins the start to the first month holding real orders, because
              earlier months are sales-proxy rows with no order and no despatch
              and including them made every total on the page disagree with the
              tiles (D-122). The window is still printed on the right, so the
              reader is told what they are looking at even though they can no
              longer change it. */}
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
          {productFilters.map((filter) => (
            <select
              key={filter.key}
              value={filter.value}
              onChange={(event) => filter.set(event.target.value)}
              className={SELECT_CLASS}
              aria-label={filter.aria}
            >
              <option value="">{filter.all}</option>
              {(filter.options ?? []).map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          ))}
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
          {productFilters
            .filter((filter) => filter.value)
            .map((filter) => (
              <ClearChip key={filter.key} label={filter.value} onClear={() => filter.set('')} />
            ))}
          {anyFilter && (
            <button
              type="button"
              onClick={clearAll}
              className="text-[10px] font-medium text-[var(--color-text-muted)] underline"
            >
              Clear all
            </button>
          )}

          {/* The panels below are holding the PREVIOUS filter's payload while
              this runs. Saying so is the price of not unmounting them: stale
              numbers presented in silence would read as current ones. */}
          {summaryQuery.isFetching && !summaryQuery.isLoading && (
            <span className="ml-auto text-[11px] font-medium text-[var(--color-primary)]">
              Updating…
            </span>
          )}
          {summary && !summary.empty && (
            <span
              className={`text-[11px] text-[var(--color-text-muted)] ${
                summaryQuery.isFetching && !summaryQuery.isLoading ? '' : 'ml-auto'
              }`}
            >
              {summary.window.start} → {summary.window.end} · {summary.window.periods}{' '}
              {periodNoun(filters?.panel_grain)}
            </span>
          )}
        </div>
        {/* What the page is counting, and nothing else. The grain note that
            used to sit here explained how weekly rows roll into months — true,
            but four lines of method under a control strip the reader came to
            use (D-143). Both figures are taken on the order book, so the
            numerator and the denominator count the same universe: `sku_count`
            includes SKUs carried only by the pre-order sales proxy, and
            against a 2,063 denominator it printed "2,315 of 2,063". */}
        {counts && (
          <p className="mt-1.5 text-[10px] text-[var(--color-text-muted)]">
            Covering <strong className="font-semibold text-[var(--color-text)]">{exact(counts.branches)}</strong>
            {counts.totalBranches ? ` of ${exact(counts.totalBranches)}` : ''} branches and{' '}
            <strong className="font-semibold text-[var(--color-text)]">{exact(counts.skus)}</strong>
            {counts.totalSkus ? ` of ${exact(counts.totalSkus)}` : ''} SKUs.
          </p>
        )}
      </Card>
      </div>

      {/* `isLoading` is the FIRST load only. A refetch after a filter change is
          `isFetching`, and the panels below keep the previous payload
          (`keepPreviousData`) rather than unmounting — which is what used to
          throw the reader back to the top of the page (D-142). */}
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
            {/* Full width, and every branch. It absorbed a top-10 donut of the
                same measure that sat beside it: a ring and a stack both said
                "where the demand is by branch", and the ring could only ever
                show ten of the 53 (D-140). */}
            <Panel className="lg:col-span-2 xl:col-span-4"
              title="Demand by Branch × Value Class"
              accent={VIOLET}
              note={`All ${summary.branch_by_group.total_branches} branches by ordered value, split by value class. Scroll sideways for the smaller ones. Click a column to filter.`}
              action={branch ? <ClearChip label="filtered" onClear={() => setBranch('')} /> : undefined}
            >
              {/* The axis holds 53 rotated depot names. At a width that fits
                  them they are 20 px apart and unreadable, so the chart keeps
                  its own width and the panel scrolls instead — `minWidth` so a
                  narrow workspace still fills the panel rather than leaving a
                  short chart in a wide box. */}
              <div className="overflow-x-auto">
                <div
                  style={{
                    minWidth: '100%',
                    width: Math.max(640, summary.branch_by_group.data.length * 34),
                  }}
                >
                  <ResponsiveContainer width="100%" height={320}>
                    <BarChart data={summary.branch_by_group.data} margin={{ top: 8, right: 6, left: -6, bottom: 0 }} barCategoryGap="26%">
                      <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="var(--color-border)" />
                      <XAxis
                        dataKey="name"
                        tick={{ ...TICK, fontSize: 8 }}
                        tickLine={false}
                        interval={0}
                        angle={-40}
                        textAnchor="end"
                        height={78}
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
                </div>
              </div>
            </Panel>

            <Panel
              className="xl:col-span-2"
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
              className="xl:col-span-2"
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

            {/* Spans two so the section's five remaining quarter-panels tile
                into whole rows: 2+1+1 then 2+2. An odd one out left a gap the
                width of a panel at the bottom of the section. */}
            <Panel
              className="xl:col-span-2"
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

            {/* Full width and last in the section. It replaced a 2,063-bar
                Pareto that said the same thing by making the reader count bars
                — and at this scale the bars were a solid block (D-139). */}
            <Panel
              className="lg:col-span-2 xl:col-span-4"
              title="Volume vs Value by SKU"
              accent={BLUE}
              note={
                skuMix.total
                  ? `All ${num(skuMix.total)} ordered SKUs, one mark each: units across, money up, bubble size is how many branches order it. The lines are the Pareto cuts — the first 80% of units, and the first 80% of value — so the four corners are four different kinds of SKU. Both axes are logarithmic, because the largest SKU outsells the smallest by about five orders of magnitude and a linear axis stacks everything into the corner.`
                  : 'One mark per SKU: ordered units against ordered value.'
              }
            >
              {/* The answer in words first — one small line per group, since
                  hunting for a group in a cloud of 2,063 marks is work the page
                  can do for the reader. Each line is the same sentence: this
                  share of the revenue, from this share of the catalogue, moving
                  this share of the units. Four cards said the same thing and
                  took a quarter of the panel to do it. */}
              <ul className="mb-3 flex flex-col gap-1 text-[11px] text-[var(--color-text-muted)]">
                {skuMix.segments.map((segment) => (
                  <li key={segment.key} className="flex items-baseline gap-2">
                    <span
                      className="mt-[1px] h-2 w-2 shrink-0 rounded-full"
                      style={{ background: segment.colour }}
                    />
                    <span>
                      <span className="font-semibold text-[var(--color-text)]">
                        {segment.value_pct}% of the revenue
                      </span>{' '}
                      comes from{' '}
                      <span className="font-semibold text-[var(--color-text)]">
                        {segment.sku_pct}% of the SKUs
                      </span>{' '}
                      ({num(segment.count)}), and they move {segment.unit_pct}% of the units —{' '}
                      <span style={{ color: segment.colour }}>{segment.label}</span>
                    </span>
                  </li>
                ))}
              </ul>

              <ResponsiveContainer width="100%" height={460}>
                <ScatterChart margin={{ top: 12, right: 20, left: 8, bottom: 16 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
                  {/* Logarithmic, and `domain` is explicit: Recharts' 'auto' on
                      a log axis rounds to the data's own extremes and clips the
                      outermost marks in half. */}
                  <XAxis
                    type="number"
                    dataKey="demand_units"
                    name="Ordered units"
                    scale="log"
                    domain={['dataMin', 'dataMax']}
                    allowDataOverflow={false}
                    ticks={skuMix.unitTicks}
                    tick={TICK}
                    tickFormatter={(v: number) => num(v)}
                    label={{
                      value: 'Ordered units (log)',
                      position: 'insideBottom',
                      offset: -8,
                      style: { ...LABEL, fontSize: 10 },
                    }}
                  />
                  <YAxis
                    type="number"
                    dataKey="demand_value"
                    name="Demand value"
                    scale="log"
                    domain={['dataMin', 'dataMax']}
                    allowDataOverflow={false}
                    ticks={skuMix.valueTicks}
                    tick={TICK}
                    width={64}
                    tickFormatter={(v: number) => inr(v)}
                    label={{
                      value: 'Ordered value (log)',
                      angle: -90,
                      position: 'insideLeft',
                      style: { ...LABEL, fontSize: 10 },
                    }}
                  />
                  <ZAxis type="number" dataKey="series_count" range={[18, 260]} name="Series" />
                  {/* The two Pareto cuts. Drawn rather than described, because
                      which side of them a mark sits on is the whole reading. */}
                  <ReferenceLine
                    x={skuMix.unitCut}
                    stroke="var(--color-text-muted)"
                    strokeDasharray="4 4"
                    label={{
                      value: '80% of units →',
                      position: 'insideTopLeft',
                      style: { ...LABEL, fontSize: 9 },
                    }}
                  />
                  <ReferenceLine
                    y={skuMix.valueCut}
                    stroke="var(--color-text-muted)"
                    strokeDasharray="4 4"
                    label={{
                      value: '↑ 80% of value',
                      position: 'insideTopRight',
                      style: { ...LABEL, fontSize: 9 },
                    }}
                  />
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
                        segment?: string;
                      };
                      const segment = skuMix.segments.find((s) => s.key === row?.segment);
                      return (
                        <div style={TOOLTIP}>
                          <div className="text-[11px] font-semibold">{row?.name}</div>
                          {segment ? (
                            <div
                              className="text-[10px] font-semibold"
                              style={{ color: segment.colour }}
                            >
                              {segment.label}
                            </div>
                          ) : null}
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
                  <Legend
                    verticalAlign="top"
                    align="right"
                    iconSize={8}
                    wrapperStyle={{ fontSize: 10, paddingBottom: 6 }}
                  />
                  {/* One series per group rather than per-mark `Cell`s: the
                      colour then means the group, the legend names it, and
                      clicking a legend entry isolates it. */}
                  {skuMix.segments.map((segment) => (
                    <Scatter
                      key={segment.key}
                      name={segment.label}
                      data={skuMix.marks.filter((m) => m.segment === segment.key)}
                      fill={segment.colour}
                      fillOpacity={segment.key === 'tail' ? 0.34 : 0.72}
                      isAnimationActive={false}
                    />
                  ))}
                </ScatterChart>
              </ResponsiveContainer>
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

            <Panel
              className="xl:col-span-2"
              title="Seasonality"
              accent={GREEN}
              note="Mean ordered units per calendar month, averaged across the years in the window."
            >
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
                  {/* `observations` is a count of YEARS. It used to be a count
                      of periods, which on a weekly panel made every bar claim
                      ten of them over a two-year window (D-145). The number is
                      the same two or three on nearly every bar, so it is stated
                      once below rather than on every hover. */}
                  <Tooltip
                    formatter={(value: number) => [`${num(value)} units`, 'Average'] as [string, string]}
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
                {seasonSpan}. Faded columns rest on a single year.
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

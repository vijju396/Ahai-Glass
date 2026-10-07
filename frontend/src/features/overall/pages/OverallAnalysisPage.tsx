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
import { useEffect, useMemo, useRef, useState } from 'react';
import type { CSSProperties } from 'react';
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
  Tooltip,
  XAxis,
  YAxis,
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
  tickNum,
  pct,
} from '@/components/ui/Dashboard';
import { ErrorState, LoadingBlock } from '@/components/ui/States';
import { Explain } from '@/components/ui/Explain';
import { MonthRange } from '@/components/ui/MonthRange';
import { grainOptionLabel, periodNoun, shortPeriod } from '../../../app/period';

const SELECT_CLASS =
  'rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-2.5 py-1.5 text-xs text-[var(--color-text)]';

/* `num` abbreviates - 2063 becomes "2.1K". That is right on a chart axis and
   wrong on a count the reader is being asked to take literally: "2.1K of 2.1K
   SKUs" hides whether the two are the same number (D-145). */
const exact = (value: number) => value.toLocaleString('en-IN');

/* `inr` abbreviates anything over a thousand, which is right for a demand
   value and wrong for a unit price: ₹2,427 and ₹7,229 both read "₹2K" / "₹7K"
   and the step between them disappears. A per-unit price gets its digits
   (D-155, and the same helper Per Branch & SKU already carries). */
const rupees = (value: number | null | undefined): string =>
  value == null || !Number.isFinite(value)
    ? '\u2014'
    : `\u20B9${Math.round(value).toLocaleString('en-IN')}`;

/* A log axis needs an explicit domain, and it cannot hold a zero: `log(0)` is
   undefined, so recharts drops that bar. `logDomain` floors to the decade
   below the smallest positive value and ceils to the decade above the largest,
   which puts every real value inside the axis and lands the ticks on round
   powers of ten — recharts' own "auto" bounds on a log scale crop the smallest
   column. Returns null when the series cannot carry a log axis (fewer than two
   positive values, or everything inside one decade), and the caller then falls
   back to the linear axis rather than drawing a broken one (D-149). */
/* A line whose values all sit in a narrow band near the top of a zero-based
   axis is drawn as a near-straight line whatever it actually did. Realised
   price runs ₹3,184 to ₹3,510 against an axis to ₹3,600, so all of its
   movement — including a real 10% climb after February — is squeezed into nine
   per cent of the panel's height. A log axis cannot help: at 1.10x there are no
   orders of magnitude to compress. Fitting the axis to the data is the fix
   (D-150).

   Legitimate on a LINE and not on a bar. A line carries its value in its
   position, so moving the baseline moves the whole line and changes nothing it
   says. A bar carries its value as length FROM the baseline, so cutting the
   baseline off a bar chart overstates every difference on it. That is why this
   is used on one line chart and nowhere else, and why the panel note says the
   axis does not start at zero. */
function tightDomain(...values: Array<number | null | undefined>) {
  const points = values.filter(
    (v): v is number => typeof v === 'number' && Number.isFinite(v),
  );
  if (points.length < 2) return null;
  const low = Math.min(...points);
  const high = Math.max(...points);
  const span = high - low;
  if (span <= 0) return null;

  /* Round the step to 1, 2 or 5 times a power of ten. Left to itself recharts
     divided this domain into ₹3130, ₹3280, ₹3560 — three labels, unevenly
     spaced, none of them a number anyone would choose. */
  const raw = span / 4;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const normalised = raw / magnitude;
  const step = (normalised <= 1.5 ? 1 : normalised <= 3 ? 2 : normalised <= 7 ? 5 : 10) * magnitude;

  const lo = Math.floor((low - span * 0.15) / step) * step;
  const hi = Math.ceil((high + span * 0.15) / step) * step;
  const ticks: number[] = [];
  for (let tick = lo; tick <= hi + step / 2; tick += step) ticks.push(Math.round(tick));
  return { domain: [lo, hi] as [number, number], ticks };
}

const LOG_MIN_SPREAD = 30;

/** The plot's height. The top row is only 27.6% of it, so 500 is what keeps
 *  the two high-value blocks legible (D-156). */
const PLOT_H = 500;

/**
 * Where the two cuts fall on a log plot, as percentages (D-156, D-157).
 *
 * The quadrants are NOT halves and must not be drawn as halves. Drawing a
 * cross through the middle and labelling it "80%" would put the line in the
 * wrong place and say so in writing — and the uneven split is the Pareto point
 * itself, since the tail occupies most of the plot while carrying 13.3% of the
 * revenue against 82.6% of the catalogue.
 *
 * Bounds are rounded out to whole decades so the gridline labels are powers of
 * ten rather than the data's own ragged extremes.
 */
function plotGeometry(
  marks: Array<{ demand_units: number; demand_value: number }>,
  unitCut: number,
  valueCut: number,
) {
  const bounds = (values: number[]) => {
    const usable = values.filter((v) => v > 0);
    if (!usable.length) return null;
    const lo = 10 ** Math.floor(Math.log10(Math.min(...usable)));
    const hi = 10 ** Math.ceil(Math.log10(Math.max(...usable)));
    return hi > lo ? ([lo, hi] as [number, number]) : null;
  };
  const unitBounds = bounds(marks.map((m) => m.demand_units));
  const valueBounds = bounds(marks.map((m) => m.demand_value));

  /** A value's position along its axis, 0 at the low end and 100 at the high. */
  const at = (value: number, span: [number, number] | null) => {
    if (!span || !(value > 0)) return 50;
    const [lo, hi] = span;
    const pct = ((Math.log10(value) - Math.log10(lo)) / (Math.log10(hi) - Math.log10(lo))) * 100;
    // Clamped so a cut outside the drawn decades cannot push a block off the
    // plot; 6/94 keeps a sliver of the smaller side visible either way.
    return Math.min(94, Math.max(6, pct));
  };

  return {
    unitBounds,
    valueBounds,
    unitCutPct: at(unitCut, unitBounds),
    valueCutPct: at(valueCut, valueBounds),
    axisPos: at,
  };
}

function logDomain(values: Array<number | null | undefined>) {
  const positive = values.filter(
    (v): v is number => typeof v === 'number' && Number.isFinite(v) && v > 0,
  );
  if (positive.length < 2) return null;
  const smallest = Math.min(...positive);
  const largest = Math.max(...positive);

  /* Log only where log earns its place. Below about one and a half decades of
     spread it makes the chart WORSE, not better: Value per Unit by Vehicle
     Category runs 2,304 to 38,897 — a 17x spread where four of the five
     segments sit between 2,304 and 4,880 — and a log axis flattens those four
     into bars of visibly equal height, hiding a difference a linear axis shows
     plainly. So that panel keeps its linear axis even with the toggle on, and
     the panels that span 242x to 279,112x take the log one. */
  if (largest / smallest < LOG_MIN_SPREAD) return null;

  const lo = 10 ** Math.floor(Math.log10(smallest));
  const hi = 10 ** Math.ceil(Math.log10(largest));
  if (lo >= hi) return null;

  const decades: number[] = [];
  for (let tick = lo; tick <= hi * 1.000001; tick *= 10) decades.push(tick);
  /* Glass type spans eight decades (6 units against 1.67M). Eight labels on a
     215 px axis is a ladder, not a scale, so past six decades the labels thin
     to every other one — the gridlines stay implied by the domain. */
  const ticks = decades.length > 6 ? decades.filter((_, index) => index % 2 === 0) : decades;
  return { domain: [lo, hi] as [number, number], ticks };
}

/** `2026-07` → `Jul 26`; a quarterly bucket is already short enough. */

export function OverallAnalysisPage() {
  const [branch, setBranch] = useState('');
  const [valueClass, setValueClass] = useState('');
  /* The three product axes the page charts in "Where the demand comes from".
     They were drawn but not selectable, so a reader could see that CAR & MUV
     carries the demand and had no way to ask what the trend, the fill rate and
     the top SKUs look like for CAR & MUV alone (D-143). */
  const [glassType, setGlassType] = useState('');
  const [vehicleCategory, setVehicleCategory] = useState('');
  const [vehicleAge, setVehicleAge] = useState('');
  /* The date range is back, at the head of the bar this time (D-148). D-145
     removed it on the grounds that its FROM could not move below the order
     book's start; that is still true, and it is now the picker's floor rather
     than a reason not to have one - TO was always free, and a reader asking
     "what did the last quarter look like?" had no way to say so. */
  const [startPeriod, setStartPeriod] = useState('');
  const [endPeriod, setEndPeriod] = useState('');
  /* Ordered demand is violently skewed, so on a linear axis the page draws
     half its own categories as nothing. Measured on the unfiltered window:
     glass types span 279,112x (1.67M units against 6), SKUs 92,636x, value
     classes 727x and branches 242x — MANDI's 647 units beside BENGALURU's
     156,563 is under a pixel tall. A log axis gives every category a readable
     height (D-149).

     A toggle rather than a hard switch, because the two scales answer
     different questions: linear says "how much bigger", log says "what is
     there at all". The cost of log is real — bar LENGTH stops being
     proportional to the value — so each panel using it says so in its note
     instead of leaving the reader to infer it. */
  const [logScale, setLogScale] = useState(true);

  /* Which panel, if any, is open as a popup. One at a time, held by id, so
     expanding a second closes the first without a second click.

     The popup is an overlay over an UNTOUCHED page (D-152). The first build
     hid everything else instead — section links, KPI tiles, the other sixteen
     panels — and scrolled to the top, which lost the reader's place and made
     the whole page jump. Nothing hides or moves now: the chosen card lifts out
     into a fixed box and leaves a placeholder of its own height in the grid
     slot it came from, so closing puts it back exactly where it was with the
     scroll position never having changed.

     It opens BELOW the filter bar rather than over it, because the reason to
     blow a chart up here is to interrogate it — change the branch, narrow the
     dates, flip the scale — and watch it move. The card is never unmounted, so
     it goes on reading the same `summary` query every other panel reads. */
  const [expandedPanel, setExpandedPanel] = useState<string | null>(null);

  /* The SKU list behind one block of the Volume vs Value map (D-155). It opens
     the same way an expanded panel does — same geometry, same backdrop, same
     three ways out — so the two are driven by one value rather than two
     parallel sets of effects that could disagree. */
  const [skuDrawer, setSkuDrawer] = useState<string | null>(null);
  const overlayFor = expandedPanel ?? (skuDrawer ? `sku:${skuDrawer}` : null);
  const closeOverlay = () => {
    setExpandedPanel(null);
    setSkuDrawer(null);
  };

  /* Where the popup sits: the full content column, from just under the filter
     bar to just above the bottom of the window. Both the bar's height and its
     horizontal extent are MEASURED — it wraps from one row to three as the
     window narrows, and anchoring to its left edge and width is what keeps the
     popup over the content column instead of across the sidebar. */
  const filterBarRef = useRef<HTMLDivElement>(null);
  const [overlayBox, setOverlayBox] = useState<CSSProperties | null>(null);

  useEffect(() => {
    if (!overlayFor) {
      setOverlayBox(null);
      return undefined;
    }
    const measure = () => {
      const bar = filterBarRef.current?.getBoundingClientRect();
      const top = bar ? Math.max(8, bar.bottom + 10) : 96;
      setOverlayBox({
        position: 'fixed',
        top,
        left: bar ? Math.round(bar.left) : 16,
        width: bar ? Math.round(bar.width) : undefined,
        height: Math.max(260, Math.round(window.innerHeight - top - 14)),
      });
    };
    measure();
    window.addEventListener('resize', measure);
    const observer = new ResizeObserver(measure);
    if (filterBarRef.current) observer.observe(filterBarRef.current);
    return () => {
      window.removeEventListener('resize', measure);
      observer.disconnect();
    };
  }, [overlayFor]);

  /* Escape closes it, and the background is frozen while it is open — frozen
     in a way that cannot shift the page sideways. `overflow: hidden` alone
     removes the scrollbar and everything behind jumps by its width, which is
     exactly the moving-things problem this rebuild exists to fix, so the lost
     width is paid back as padding. Scroll POSITION is never touched, so
     closing returns the reader to the pixel they left. */
  useEffect(() => {
    if (!overlayFor) return undefined;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') closeOverlay();
    };
    window.addEventListener('keydown', onKey);

    const root = document.documentElement;
    const gutter = window.innerWidth - root.clientWidth;
    const previousOverflow = root.style.overflow;
    const previousPadding = document.body.style.paddingRight;
    root.style.overflow = 'hidden';
    if (gutter > 0) document.body.style.paddingRight = `${gutter}px`;

    return () => {
      window.removeEventListener('keydown', onKey);
      root.style.overflow = previousOverflow;
      document.body.style.paddingRight = previousPadding;
    };
  }, [overlayFor]);

  /** Everything a panel needs to take part. `className` is its ordinary grid
   *  class in every case — no panel is ever hidden or re-spanned, which is the
   *  difference between this and the version it replaced. */
  const panelProps = (id: string, baseClass = '') => ({
    expanded: expandedPanel === id,
    onToggleExpand: () => {
      setSkuDrawer(null);
      setExpandedPanel((current) => (current === id ? null : id));
    },
    className: baseClass,
    overlayStyle: expandedPanel === id && overlayBox ? overlayBox : undefined,
  });

  /** A chart's height. Takes the panel id because only the popped panel grows
   *  — the sixteen still sitting in the page behind it keep their own heights,
   *  which is what "not moving other things" means. The popup's own chrome
   *  (header, note, padding) is 104px of the box. */
  const chartH = (id: string, base: number) =>
    expandedPanel === id && overlayBox
      ? Math.max(base, Number(overlayBox.height ?? base) - 104)
      : base;
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
     tiles (D-122). So that month is the floor under FROM, not just the
     default: `effectiveStart` takes the reader's choice only when it is later.
     The picker's own `minMonth` stops them picking earlier in the first place;
     this is the belt to that braces, because a typed value can land anywhere. */
  const ordersStart = filters?.orders_start_month ?? '';
  const effectiveStart = startPeriod && startPeriod > ordersStart ? startPeriod : ordersStart;

  const query: AnalyticsQuery = useMemo(
    () => ({
      branch: branch || undefined,
      value_class: valueClass || undefined,
      glass_type: glassType || undefined,
      vehicle_category: vehicleCategory || undefined,
      vehicle_age_category: vehicleAge || undefined,
      start_period: effectiveStart || undefined,
      end_period: endPeriod || undefined,
      grain,
    }),
    [branch, valueClass, glassType, vehicleCategory, vehicleAge, effectiveStart, endPeriod, grain],
  );

  /* `keepPreviousData` is what makes a filter change feel like a filter change
     rather than a page load. Without it the key changes, `data` goes
     `undefined`, every panel below unmounts, the document collapses to the
     height of the filter bar and the browser drops the reader at the top —
     then the payload arrives and the page grows back under them. Holding the
     previous payload keeps the document the same height, so the scroll
     position survives and only the numbers change (D-144). */
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

  // `dimBranch` went with the branch donut (D-142): nothing on this page now
  // dims by branch, and the active filter shows as a clear-chip on the panel.
  const dimClass = (name: string) => (valueClass && name !== valueClass ? 0.28 : 1);

  /** Axis props for a quantity axis, spread onto the numeric `XAxis`/`YAxis`
   *  of the magnitude charts. Returns nothing at all when the toggle is off or
   *  the series cannot carry a log axis, so the chart keeps its linear default
   *  rather than rendering half-drawn.
   *
   *  Deliberately NOT applied to three kinds of chart: the stacked ones (Top
   *  SKUs stacks filled on unfilled, and stacked segments do not add up on a
   *  log axis), the percentage ones (fill rate and unfilled share are already
   *  on a 0–100 scale where small values are legible), and the time series
   *  (log bends the shape of a trend, which is the one thing those charts
   *  exist to show). Volume vs Value by SKU was already log on both axes. */
  const magnitudeAxis = (values: Array<number | null | undefined>) => {
    if (!logScale) return {};
    const bounds = logDomain(values);
    if (!bounds) return {};
    return {
      scale: 'log' as const,
      domain: bounds.domain,
      ticks: bounds.ticks,
      allowDataOverflow: true,
    };
  };

  /** Every branch by ordered units, largest first. This replaced a stacked
   *  Branch x Value Class chart (D-149): the stack answered two questions at
   *  once and neither well — 53 columns each split five ways left the smaller
   *  branches as a few unreadable slivers, and the value-class split already
   *  has its own panel directly below. Plotted in units, like every other
   *  "Demand by …" panel on the page; the stack plotted value, which is why it
   *  ranked SECUNDRABAD above BENGALURU on one measure and below on the other.
   *  The value is still on the tooltip. */
  const branchRows = useMemo(
    () => [...(summary?.by_branch ?? [])].sort((a, b) => (b.demand_units || 0) - (a.demand_units || 0)),
    [summary],
  );

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
  /* The average is folded in so the dashed reference line cannot fall outside
     the axis it is drawn on. */
  const priceDomain = useMemo(
    () => tightDomain(...trend.map((point) => point.price_per_unit), averagePrice),
    [trend, averagePrice],
  );

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
   *  count bars (D-141).
   *
   *  **The cuts are Pareto, not medians.** A SKU is core *volume* if it falls
   *  inside the set making up the first 80% of ordered units. A median split
   *  on a catalogue this long-tailed lands near zero and would call half the
   *  tail "high".
   *
   *  **The two cuts are not the same construction** (D-157). The units cut is
   *  the plain 80% Pareto. The value cut is placed so the corner the two lines
   *  box off holds 80% of revenue — see `cornerValueCut` below. The sets still
   *  disagree, and that they disagree is the finding: 29 SKUs earn their place
   *  on value alone and 120 on volume alone.
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
    /** The value cut, placed so the **corner** holds 80% of revenue (D-157).
     *
     *  Not the same construction as `coreOf`. Taking the first 80% of value on
     *  its own is a true statement about the top *row*, but the units cut then
     *  slices a sliver of that row away into the low-volume block, and the
     *  corner — the one number a reader takes off this panel — came out at
     *  77.9% instead of 80%. So the value threshold is lowered until the
     *  SKUs that are big on *both* counts reach 80% of all revenue. The row
     *  above the line then holds more than 80%, which is why that line is no
     *  longer labelled "80% of value".
     */
    const cornerValueCut = (bigVolume: Set<string>) => {
      const ranked = [...rows].sort((a, b) => (b.demand_value || 0) - (a.demand_value || 0));
      const names = new Set<string>();
      let corner = 0;
      let cut = 0;
      for (const row of ranked) {
        names.add(row.name);
        cut = row.demand_value || 0;
        if (bigVolume.has(row.name)) corner += row.demand_value || 0;
        if (valueTotal > 0 && corner / valueTotal >= 0.8) break;
      }
      return { names, cut };
    };

    const volume = coreOf('demand_units');

    /** 80% in the corner is not always reachable. The corner can only ever
     *  hold revenue belonging to a high-*volume* SKU, so the ceiling is what
     *  those SKUs carry between them — 93.7% across the whole catalogue, but
     *  only 75.0% under a Sidelite filter. Lowering the line past that point
     *  admits low-volume SKUs that add nothing to the corner and everything to
     *  the row, which emptied the two bottom blocks. When the target is out of
     *  reach the panel falls back to the plain 80%-of-value Pareto cut and
     *  says so in the note, rather than drawing a degenerate chart (D-157). */
    const cornerCeiling = rows
      .filter((r) => volume.names.has(r.name))
      .reduce((sum, r) => sum + (r.demand_value || 0), 0);
    const cornerTargeted = valueTotal > 0 && cornerCeiling >= 0.8 * valueTotal;
    const value = cornerTargeted ? cornerValueCut(volume.names) : coreOf('demand_value');

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
      cornerTargeted,
      cornerCeilingPct: share(cornerCeiling, valueTotal),
      total: marks.length,
      unitTicks: decades(marks.map((m) => m.demand_units || 0)),
      valueTicks: decades(marks.map((m) => m.demand_value || 0)),
      ...plotGeometry(marks, volume.cut, value.cut),
    };
  }, [summary]);

  /** The block whose SKU list is open, and its rows (D-155). Sorted on open
   *  rather than inside the table, so the ranking is computed once instead of
   *  on every render while 1.7K rows are scrolled. */
  const drawerSegment = skuMix.segments.find((segment) => segment.key === skuDrawer) ?? null;
  const drawerRows = useMemo(
    () =>
      skuDrawer
        ? [...skuMix.marks]
            .filter((mark) => mark.segment === skuDrawer)
            .sort((a, b) => (b.demand_value || 0) - (a.demand_value || 0))
        : [],
    [skuDrawer, skuMix.marks],
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
    setStartPeriod('');
    setEndPeriod('');
  };

  /** How much of the client's data the page is counting, under the current
   *  filters. Both sides of each ratio are taken on the order book:
   *  `ordered_sku_count` rather than `sku_count`, because the latter includes
   *  SKUs carried only by the pre-order sales proxy and printed "2,315 of
   *  2,063" against the order-book denominator (D-145). Falls back to the
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

  /* No "start after end" guard here, deliberately. `MonthRange` passes each
     field the other as its bound and clamps on every change, so an inverted
     range cannot be produced by the control — measured: typing 2024-06 into
     FROM snaps it back to 2025-04 and leaves the window untouched. A message
     that can never render is worse than none (D-148). */
  const anyFilter =
    branch || valueClass || glassType || vehicleCategory || vehicleAge || startPeriod || endPeriod;

  /* How many years each Seasonality bar averages, said once under the chart
     instead of on every hover (D-147). Always two or three on this window. */
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

      {/* The scope banner was removed from this page (D-144). It read
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
      <div ref={filterBarRef} className="sticky top-0 z-20 -my-2 bg-[var(--color-bg)] py-2 max-[800px]:top-[72px]">
      <Card className="!py-2.5">
        <div className="flex flex-wrap items-center gap-2 text-xs">
          {/* The date range leads the bar, because it is the question a reader
              asks first — "over what period?" — and everything after it narrows
              that window rather than the other way round (D-148). `minMonth`
              floors FROM at the first month holding real orders: earlier months
              are sales-proxy rows with no order and no despatch, and including
              them made every total on the page disagree with the tiles (D-122).
              TO is free to the end of the panel. */}
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
          {/* Not a filter — it changes nothing about what is counted, only how
              the magnitude charts are drawn. It sits here because it is a
              page-wide control and there is nowhere else a reader would look
              for one (D-149). */}
          <label
            className="flex cursor-pointer select-none items-center gap-1.5 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-2.5 py-1.5 text-xs text-[var(--color-text)]"
            title="Draw the magnitude charts on a logarithmic axis so the smallest categories are still visible. Bar lengths stop being proportional."
          >
            <input
              type="checkbox"
              checked={logScale}
              onChange={(event) => setLogScale(event.target.checked)}
              className="h-3 w-3 accent-[var(--color-primary)]"
            />
            Log scale
          </label>

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
            use (D-145). Both figures are taken on the order book, so the
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
          throw the reader back to the top of the page (D-144). */}
      {(filtersQuery.isLoading || summaryQuery.isLoading) && <LoadingBlock label="Aggregating the panel" />}
      {filtersQuery.isError && <ErrorState error={filtersQuery.error} />}
      {summaryQuery.isError && <ErrorState error={summaryQuery.error} />}

      {summary?.empty && (
        <Card>
          <p className="text-sm text-[var(--color-text)]">{summary.reason}</p>
        </Card>
      )}

      {/* The backdrop. It starts where the popup starts, so the filter bar
          above it is never covered and never stops responding — changing a
          filter with the popup open is the whole point. Clicking it closes,
          the way a reader expects of anything that dims the page. `z-30`
          against the card's `z-40`. */}
      {overlayFor && overlayBox && (
        <div
          className="fixed inset-0 z-30 bg-black/25"
          style={{ top: overlayBox.top }}
          onClick={closeOverlay}
          aria-hidden="true"
        />
      )}

      {/* The SKU list behind one block of the Volume vs Value map (D-155).
          Same box, same backdrop, same Esc as an expanded panel — a reader who
          has closed one has already learnt how to close the other. */}
      {skuDrawer && overlayBox && drawerSegment && (
        <Card
          className="z-40 flex flex-col overflow-hidden"
          style={overlayBox}
        >
          <div className="mb-2 flex items-start justify-between gap-2">
            <div className="flex items-center gap-2">
              <span
                className="h-3.5 w-[3px] shrink-0 rounded-full"
                style={{ background: drawerSegment.colour }}
              />
              <h3 className="text-[11px] font-semibold uppercase tracking-[0.06em] text-[var(--color-text)]">
                {drawerSegment.label}
              </h3>
            </div>
            <button
              type="button"
              onClick={closeOverlay}
              aria-label={`Close the ${drawerSegment.label} list`}
              title="Close (Esc)"
              className="-m-1 shrink-0 rounded p-1 text-[var(--color-text-muted)] hover:bg-[var(--color-surface-2)] hover:text-[var(--color-text)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--color-primary)]"
            >
              <svg
                viewBox="0 0 16 16"
                width="13"
                height="13"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.6"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                <path d="M1.5 6.5H6.5V1.5" />
                <path d="M14.5 9.5H9.5V14.5" />
                <path d="M6.5 6.5L1.5 1.5" />
                <path d="M9.5 9.5L14.5 14.5" />
              </svg>
            </button>
          </div>

          {/* The totals first, because the question a block asks is "how much
              is in here?" and counting 1,715 table rows is not an answer. */}
          <div className="mb-2 grid shrink-0 grid-cols-2 gap-2 sm:grid-cols-4">
            {[
              { k: 'SKUs', v: exact(drawerSegment.count), s: `${drawerSegment.sku_pct.toFixed(1)}% of the catalogue` },
              { k: 'Ordered value', v: inr(drawerSegment.value), s: `${drawerSegment.value_pct.toFixed(1)}% of the revenue` },
              { k: 'Ordered units', v: num(drawerSegment.units), s: `${drawerSegment.unit_pct.toFixed(1)}% of the units` },
              {
                k: 'Value per unit',
                v: drawerSegment.units ? rupees(drawerSegment.value / drawerSegment.units) : '—',
                s: 'across the block',
              },
            ].map((tile) => (
              <div
                key={tile.k}
                className="rounded-lg border border-[var(--color-border)] px-2.5 py-1.5"
                style={{ background: `${drawerSegment.colour}0f` }}
              >
                <div className="text-[9px] font-semibold uppercase tracking-[0.07em] text-[var(--color-text-muted)]">
                  {tile.k}
                </div>
                <div className="text-sm font-bold leading-tight text-[var(--color-text)]">{tile.v}</div>
                <div className="text-[9px] text-[var(--color-text-muted)]">{tile.s}</div>
              </div>
            ))}
          </div>

          <p className="mb-1.5 shrink-0 text-[10px] text-[var(--color-text-muted)]">
            Every SKU in this block, largest first by ordered value. Value is
            ordered quantity at mean MRP.
          </p>

          {/* The one scrolling region. Everything above it is pinned, so the
              column headings stay put while 1.7K rows go past. */}
          <div className="min-h-0 flex-1 overflow-auto rounded-lg border border-[var(--color-border)]">
            <table className="w-full border-collapse text-[11px]">
              <thead className="sticky top-0 z-10 bg-[var(--color-surface-2)]">
                <tr className="text-left text-[var(--color-text-muted)]">
                  <th className="px-2.5 py-1.5 font-semibold">#</th>
                  <th className="px-2.5 py-1.5 font-semibold">SKU</th>
                  <th className="px-2.5 py-1.5 text-right font-semibold">Ordered units</th>
                  <th className="px-2.5 py-1.5 text-right font-semibold">Ordered value</th>
                  <th className="px-2.5 py-1.5 text-right font-semibold">Per unit</th>
                  <th className="px-2.5 py-1.5 text-right font-semibold">Branches</th>
                </tr>
              </thead>
              <tbody>
                {drawerRows.map((row, index) => (
                  <tr
                    key={row.name}
                    className="border-t border-[var(--color-border)] text-[var(--color-text)]"
                  >
                    <td className="px-2.5 py-1 text-[var(--color-text-muted)] tabular-nums">
                      {index + 1}
                    </td>
                    <td className="px-2.5 py-1 font-medium">{row.name}</td>
                    <td className="px-2.5 py-1 text-right tabular-nums">{exact(row.demand_units)}</td>
                    <td className="px-2.5 py-1 text-right tabular-nums">{inr(row.demand_value)}</td>
                    <td className="px-2.5 py-1 text-right tabular-nums">{rupees(row.per_unit)}</td>
                    <td className="px-2.5 py-1 text-right tabular-nums">{exact(row.series_count)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {summary && !summary.empty && (
        <>
          {/* Nothing on this page hides or moves while a panel is expanded.
              The panel lifts out into a popup above it and leaves a
              same-sized placeholder in its grid slot (D-152). */}
          <SectionLinks />

          {/* KPI tiles — orders in, sales out, and the difference between
                them, all three on ONE set of rows so they reconcile exactly:
                tile 1 − tile 2 = tile 3. Total ordered value is larger than
                tile 1 and is deliberately not shown here; it covers rows that
                carry no despatch figure at all, and subtracting sales from it
                would report a gap in the data as an undelivered order
                (docs/DECISIONS.md D-121). */}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
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
            {/* The fourth tile is a rate, not a sum, so it sits outside the
                "tile 1 − tile 2 = tile 3" identity above — and it divides the
                gross shortfall, not the net gap on the tile beside it. Those
                are different numbers (504.3K against 468.4K) because 5,534
                lines were over-despatched, so the sublabel names the quantity
                being divided rather than leaving the reader to assume it is
                the 468.4K next door (D-153, D-158). */}
            <StatTile
              label="Unfilled rate"
              value={pct(summary.kpis.unfilled_rate_pct)}
              sublabel={`${num(summary.kpis.shortfall_units)} of ${num(summary.kpis.ordered_units_known)} units short`}
              spark={trend}
              sparkKey="unfilled_rate_pct"
              tint="amber"
            />
          </div>
          {/* The page never reaches before the orders window, so the tiles and
                every panel below are the same rows and their totals agree. The
                one figure that legitimately differs is the unfilled count. */}
          <p className="-mt-1 text-[10px] text-[var(--color-text-muted)]">
            Every figure on this page covers {summary.window.start} → {summary.window.end}. Order data
            starts in {summary.window.start}; the weeks before it hold sales figures only, so they are
            not shown. The unfilled rate counts only lines that were short ({num(summary.kpis.shortfall_units)} units),
            as do the unfilled panels below; lines that were over-despatched cancel part of that, which
            is why the tile beside it shows a smaller net gap of {num(summary.kpis.gap_units)} units.
            The two tiles divide different quantities, so the rate is not 100% minus the coverage
            figure next to it.
          </p>

          <section id="sec-demand" className="flex scroll-mt-4 flex-col gap-3">
            <SectionHeader title="Where the demand comes from" question="Which branches, products and vehicles drive orders?" />
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-2 xl:grid-cols-4">
            {/* Full width, and every branch. It absorbed a top-10 donut of the
                same measure that sat beside it: a ring and a stack both said
                "where the demand is by branch", and the ring could only ever
                show ten of the 53 (D-142). */}
            <Panel {...panelProps('branch', 'lg:col-span-2 xl:col-span-4')}
              title="Demand by Branch"
              accent={VIOLET}
              note={`All ${branchRows.length} branches by ordered units, largest first.${
                logScale ? ' Log scale: read the gridline a column reaches, not its height.' : ''
              } Scroll sideways for the smaller ones. Click a column to filter.`}
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
                    width: Math.max(640, branchRows.length * 34),
                  }}
                >
                  <ResponsiveContainer width="100%" height={chartH('branch', 320)}>
                    <BarChart data={branchRows} margin={{ top: 8, right: 6, left: -6, bottom: 0 }} barCategoryGap="26%">
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
                      <YAxis
                        tick={TICK}
                        tickFormatter={tickNum}
                        width={54}
                        {...magnitudeAxis(branchRows.map((row) => row.demand_units))}
                      />
                      <Tooltip
                        contentStyle={TOOLTIP}
                        formatter={(value: number, _name, item) => {
                          const row = item?.payload as { demand_value?: number; sku_count?: number };
                          return [
                            `${num(value)} units · ${inr(row?.demand_value)} · ${row?.sku_count ?? 0} SKUs`,
                            'Ordered',
                          ];
                        }}
                      />
                      <Bar
                        dataKey="demand_units"
                        radius={[5, 5, 0, 0]}
                        isAnimationActive={false}
                        className="cursor-pointer"
                        onClick={(entry: { name?: string }) => entry?.name && toggleBranch(entry.name)}
                      >
                        {branchRows.map((row) => (
                          <Cell
                            key={row.branch}
                            fill={VIOLET}
                            opacity={branch && row.name !== branch ? 0.28 : 1}
                          />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>
            </Panel>

            <Panel {...panelProps('value-class', 'xl:col-span-2')}
              title="Demand by Value Class"
              accent={TEAL}
              note="SKU count shown under each column. Click to filter."
              action={valueClass ? <ClearChip label="filtered" onClear={() => setValueClass('')} /> : undefined}
            >
              <ResponsiveContainer width="100%" height={chartH('value-class', 196)}>
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
                  <YAxis
                    tick={TICK}
                    tickFormatter={tickNum}
                    {...magnitudeAxis(summary.by_value_class.map((row) => row.demand_units))}
                  />
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

            <Panel {...panelProps('glass-type')}
              title="Demand by Glass Type"
              accent={TEAL}
              note="Laminated windscreens, sidelites and backlites."
            >
              <ResponsiveContainer width="100%" height={chartH('glass-type', 215)}>
                <BarChart data={glassRows} margin={{ top: 16, right: 6, left: -14, bottom: 0 }} barCategoryGap="26%">
                  <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="var(--color-border)" />
                  <XAxis dataKey="name" tick={{ ...TICK, fontSize: 10 }} tickLine={false} interval={0} />
                  <YAxis
                    tick={TICK}
                    width={46}
                    tickFormatter={tickNum}
                    {...magnitudeAxis(glassRows.map((row) => row.demand_units))}
                  />
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

            <Panel {...panelProps('vehicle-category')}
              title="Demand by Vehicle Category"
              accent={NAVY}
              note="Ordered units by vehicle category."
            >
              <ResponsiveContainer width="100%" height={chartH('vehicle-category', 215)}>
                <BarChart
                  data={vehicleRows}
                  layout="vertical"
                  margin={{ top: 4, right: 30, left: 4, bottom: 0 }}
                  barCategoryGap="24%"
                >
                  <CartesianGrid horizontal={false} strokeDasharray="3 3" stroke="var(--color-border)" />
                  <XAxis
                    type="number"
                    tick={TICK}
                    tickFormatter={tickNum}
                    {...magnitudeAxis(vehicleRows.map((row) => row.demand_units))}
                  />
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

            <Panel {...panelProps('vehicle-age', 'xl:col-span-2')}
              title="Demand by Vehicle Age"
              accent={AMBER}
              note="Ordered units by vehicle age band."
            >
              <ResponsiveContainer width="100%" height={chartH('vehicle-age', 215)}>
                <BarChart
                  data={ageRows}
                  layout="vertical"
                  margin={{ top: 4, right: 30, left: 4, bottom: 0 }}
                  barCategoryGap="20%"
                >
                  <CartesianGrid horizontal={false} strokeDasharray="3 3" stroke="var(--color-border)" />
                  <XAxis
                    type="number"
                    tick={TICK}
                    tickFormatter={tickNum}
                    {...magnitudeAxis(ageRows.map((row) => row.demand_units))}
                  />
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
            <Panel {...panelProps('value-per-unit', 'xl:col-span-2')}
              title="Value per Unit by Vehicle Category"
              accent={VIOLET}
              note="Ordered value ÷ ordered units, per segment."
            >
              <ResponsiveContainer width="100%" height={chartH('value-per-unit', 215)}>
                <BarChart
                  data={vehicleValue}
                  margin={{ top: 16, right: 6, left: -6, bottom: 0 }}
                  barCategoryGap="26%"
                >
                  <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="var(--color-border)" />
                  <XAxis dataKey="short" tick={{ ...TICK, fontSize: 9 }} tickLine={false} interval={0} />
                  <YAxis
                    tick={TICK}
                    width={54}
                    tickFormatter={(v: number) => inr(v)}
                    {...magnitudeAxis(vehicleValue.map((row) => row.per_unit))}
                  />
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

            {/* Four blocks, not 2,063 marks (D-155). The scatter before it
                drew one bubble per SKU, and at this count the middle of the
                cloud was a solid smear: the marks that carried the reading
                were the few at the edges, and the 1.7K in the tail were the
                ones doing the smearing. The reading was never which mark is
                where - it is how much sits in each quadrant, which is a number
                and now reads as one. The marks are not lost; each block opens
                the list behind it.

                No expand button: the panel is already full width, and there is
                nothing in a block to magnify. */}
            <Panel
              className="lg:col-span-2 xl:col-span-4"
              title="Volume vs Value by SKU"
              accent={BLUE}
              note={
                skuMix.total
                  ? `All ${num(skuMix.total)} ordered SKUs, split by two cuts. Across: how many units a SKU moves — the line is the 80% mark, so everything right of it makes up the first 80% of units ordered. Up: how much money it brings — ${
                      skuMix.cornerTargeted
                        ? 'that line is set so the top-right corner holds 80% of all revenue, which is the group to run the business on. The row above it therefore holds a little more than 80%.'
                        : `the fast-moving SKUs in this selection carry only ${skuMix.cornerCeilingPct}% of revenue between them, so no line can put 80% in the corner — this one is the plain 80%-of-value cut instead.`
                    } Click a block for the SKUs in it. Value is ordered quantity at mean MRP.`
                  : 'Ordered SKUs, split by the Pareto cuts on units and on value.'
              }
            >
              {skuMix.total ? (
                <>
                  {/* A real plot frame, with the blocks sitting in it (D-156).
                      The two dashed lines are the Pareto cuts at their MEASURED
                      positions — 56.3% across and 72.4% up, not a cross through
                      the middle — so each block's footprint is the quadrant it
                      actually owns. That the tail fills most of the plot while
                      carrying 14.2% of the revenue is the Pareto reading, and
                      drawing it as four equal boxes threw it away. */}
                  <div className="flex gap-1.5">
                    <div className="flex w-4 shrink-0 items-center justify-center">
                      <span className="whitespace-nowrap text-[9px] uppercase tracking-[0.08em] text-[var(--color-text-muted)] [writing-mode:vertical-rl] [transform:rotate(180deg)]">
                        Ordered value (log) →
                      </span>
                    </div>

                    {/* The y gutter: decade labels at their own log positions,
                        which is what makes the frame a chart rather than a
                        border round some boxes. */}
                    <div className="relative w-[58px] shrink-0" style={{ height: PLOT_H }}>
                      {(skuMix.valueTicks ?? []).map((tick) => (
                        <span
                          key={tick}
                          className="absolute right-1 translate-y-1/2 text-[9px] tabular-nums text-[var(--color-text-muted)]"
                          style={{ bottom: `${skuMix.axisPos(tick, skuMix.valueBounds)}%` }}
                        >
                          {inr(tick)}
                        </span>
                      ))}
                    </div>

                    <div className="min-w-0 flex-1">
                      <div
                        className="relative rounded-lg border border-[var(--color-border)]"
                        style={{ height: PLOT_H }}
                      >
                        {/* Decade gridlines, so a block's position can be read
                            against the scale rather than only against its
                            neighbours. */}
                        {(skuMix.valueTicks ?? []).map((tick) => (
                          <div
                            key={`vg-${tick}`}
                            className="pointer-events-none absolute inset-x-0 border-t border-dashed border-[var(--color-border)] opacity-60"
                            style={{ bottom: `${skuMix.axisPos(tick, skuMix.valueBounds)}%` }}
                          />
                        ))}
                        {(skuMix.unitTicks ?? []).map((tick) => (
                          <div
                            key={`ug-${tick}`}
                            className="pointer-events-none absolute inset-y-0 border-l border-dashed border-[var(--color-border)] opacity-60"
                            style={{ left: `${skuMix.axisPos(tick, skuMix.unitBounds)}%` }}
                          />
                        ))}

                        {/* The two cuts, labelled, because which side of them a
                            block sits on is the whole reading. Only the units
                            line is an 80% line; the value line is placed to
                            fill the corner to 80% and is labelled as the cut it
                            is, not as a share it does not carry (D-157). */}
                        <div
                          className="pointer-events-none absolute inset-y-0 z-10 border-l border-dashed"
                          style={{
                            left: `${skuMix.unitCutPct}%`,
                            borderColor: 'var(--color-text-muted)',
                          }}
                        >
                          <span className="absolute -top-px left-1 whitespace-nowrap rounded bg-[var(--color-surface)] px-1 text-[9px] text-[var(--color-text-muted)]">
                            80% of units →
                          </span>
                        </div>
                        <div
                          className="pointer-events-none absolute inset-x-0 z-10 border-t border-dashed"
                          style={{
                            bottom: `${skuMix.valueCutPct}%`,
                            borderColor: 'var(--color-text-muted)',
                          }}
                        >
                          <span className="absolute -top-1.5 right-1 whitespace-nowrap rounded bg-[var(--color-surface)] px-1 text-[9px] text-[var(--color-text-muted)]">
                            ↑ value cut
                          </span>
                        </div>

                        {/* One block per quadrant, placed by the cuts. */}
                        {(
                          [
                            { key: 'value', high: true, right: false },
                            { key: 'both', high: true, right: true },
                            { key: 'tail', high: false, right: false },
                            { key: 'volume', high: false, right: true },
                          ] as const
                        ).map(({ key, high, right }) => {
                          const segment = skuMix.segments.find((s) => s.key === key);
                          if (!segment) return null;
                          const open = skuDrawer === key;
                          const left = right ? skuMix.unitCutPct : 0;
                          const width = right ? 100 - skuMix.unitCutPct : skuMix.unitCutPct;
                          const top = high ? 0 : 100 - skuMix.valueCutPct;
                          const height = high ? 100 - skuMix.valueCutPct : skuMix.valueCutPct;
                          return (
                            <button
                              key={key}
                              type="button"
                              onClick={() => {
                                setExpandedPanel(null);
                                setSkuDrawer((current) => (current === key ? null : key));
                              }}
                              aria-label={`List the ${segment.count} SKUs in ${segment.label}`}
                              className="group absolute flex flex-col overflow-hidden rounded-lg border p-2.5 text-left transition-shadow hover:shadow-[var(--shadow-sm)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--color-primary)]"
                              style={{
                                containerType: 'size',
                                left: `calc(${left}% + 4px)`,
                                width: `calc(${width}% - 8px)`,
                                top: `calc(${top}% + 4px)`,
                                height: `calc(${height}% - 8px)`,
                                background: `${segment.colour}14`,
                                borderColor: open ? segment.colour : `${segment.colour}44`,
                                boxShadow: open ? `inset 0 0 0 1px ${segment.colour}` : undefined,
                              }}
                            >
                              <div className="flex shrink-0 items-start justify-between gap-2">
                                <span
                                  className="font-semibold uppercase leading-tight tracking-[0.05em]"
                                  style={{
                                    color: segment.colour,
                                    fontSize: 'clamp(9px, min(7cqh, 3.2cqw), 12px)',
                                  }}
                                >
                                  {segment.label}
                                </span>
                                <span
                                  className="shrink-0 whitespace-nowrap text-[var(--color-text-muted)] opacity-0 transition-opacity group-hover:opacity-100"
                                  style={{ fontSize: 'clamp(8px, min(6cqh, 2.6cqw), 10px)' }}
                                >
                                  click to list →
                                </span>
                              </div>

                              {/* The two figures, sized to the block they sit
                                  in. A bar of the same length said it a second
                                  time and cost the room the number needed; a
                                  big block now carries big type, which is the
                                  comparison the bar was drawing. `cqh`/`cqw`
                                  are read off this button, so the type tracks
                                  the quadrant as the cuts move. */}
                              <div className="flex min-h-0 flex-1 flex-col justify-center gap-[3cqh]">
                                <div className="flex items-baseline gap-[0.4em]">
                                  <span
                                    className="font-bold leading-none tabular-nums"
                                    style={{
                                      color: segment.colour,
                                      fontSize: 'clamp(17px, min(26cqh, 15cqw), 58px)',
                                    }}
                                  >
                                    {segment.value_pct.toFixed(1)}%
                                  </span>
                                  <span
                                    className="leading-tight text-[var(--color-text-muted)]"
                                    style={{ fontSize: 'clamp(9px, min(8cqh, 4cqw), 15px)' }}
                                  >
                                    of revenue
                                  </span>
                                </div>
                                <div className="flex items-baseline gap-[0.4em]">
                                  <span
                                    className="font-bold leading-none tabular-nums text-[var(--color-text)]"
                                    style={{ fontSize: 'clamp(13px, min(17cqh, 10cqw), 38px)' }}
                                  >
                                    {segment.sku_pct.toFixed(1)}%
                                  </span>
                                  <span
                                    className="leading-tight text-[var(--color-text-muted)]"
                                    style={{ fontSize: 'clamp(9px, min(8cqh, 4cqw), 15px)' }}
                                  >
                                    of SKUs
                                  </span>
                                </div>
                              </div>
                            </button>
                          );
                        })}
                      </div>

                      {/* The x gutter, under the plot it belongs to. */}
                      <div className="relative mt-0.5 h-3">
                        {(skuMix.unitTicks ?? []).map((tick) => (
                          <span
                            key={tick}
                            className="absolute -translate-x-1/2 text-[9px] tabular-nums text-[var(--color-text-muted)]"
                            style={{ left: `${skuMix.axisPos(tick, skuMix.unitBounds)}%` }}
                          >
                            {tickNum(tick)}
                          </span>
                        ))}
                      </div>
                      <div className="text-center text-[9px] uppercase tracking-[0.08em] text-[var(--color-text-muted)]">
                        Ordered units (log) →
                      </div>
                    </div>
                  </div>
                </>
              ) : (
                <p className="py-6 text-center text-[11px] text-[var(--color-text-muted)]">
                  No ordered SKU matches these filters.
                </p>
              )}
            </Panel>
          </div>
          </section>

          <section id="sec-time" className="flex scroll-mt-4 flex-col gap-3">
            <SectionHeader title="How demand moves over time" question="Is it growing, and when does it peak?" />
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-2 xl:grid-cols-4">
            <Panel {...panelProps('trend', 'xl:col-span-2')} title="Ordered Demand Trend" accent={BLUE}>
              <ResponsiveContainer width="100%" height={chartH('trend', 200)}>
                <AreaChart data={trend} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                  <defs>
                    <linearGradient id="demandFill" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor={BLUE} stopOpacity={0.32} />
                      <stop offset="100%" stopColor={BLUE} stopOpacity={0.02} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="var(--color-border)" />
                  <XAxis dataKey="label" tick={TICK} minTickGap={18} tickLine={false} />
                  <YAxis tick={TICK} tickFormatter={tickNum} />
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

            <Panel {...panelProps('branch-over-time', 'xl:col-span-2')}
              title="Demand by Branch over Time"
              accent={BLUE}
              note="One line per branch. Click a legend entry to filter."
            >
              <ResponsiveContainer width="100%" height={chartH('branch-over-time', 186)}>
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

            <Panel {...panelProps('seasonality', 'xl:col-span-2')}
              title="Seasonality"
              accent={GREEN}
              note="Mean ordered units per calendar month, averaged across the years in the window."
            >
              <ResponsiveContainer width="100%" height={chartH('seasonality', 180)}>
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
                  <YAxis tick={TICK} tickFormatter={tickNum} />
                  {/* `observations` is a count of YEARS. It used to be a count
                      of periods, which on a weekly panel made every bar claim
                      ten of them over a two-year window (D-147). The number is
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

            <Panel {...panelProps('price', 'xl:col-span-2')}
              title="Realised Price per Unit"
              accent={NAVY}
              /* Kept under 90 characters on purpose: past that `Panel` folds
                 the note behind a "How to read this" click, and the one thing
                 a reader must not have to click for is the warning that the
                 axis does not start at zero. */
              note={`Ordered value ÷ units. Dashed line is the average.${
                priceDomain ? ' Axis starts above zero.' : ''
              }`}
            >
              <ResponsiveContainer width="100%" height={chartH('price', 186)}>
                <LineChart data={trend} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                  <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="var(--color-border)" />
                  <XAxis dataKey="label" tick={TICK} minTickGap={22} tickLine={false} />
                  <YAxis
                    tick={TICK}
                    tickFormatter={(value: number) => `₹${Math.round(value)}`}
                    {...(priceDomain
                      ? { domain: priceDomain.domain, ticks: priceDomain.ticks, allowDataOverflow: true }
                      : {})}
                  />
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
            <Panel {...panelProps('ordered-despatched', 'xl:col-span-2')}
              title="Ordered vs Despatched"
              accent={TEAL}
              note="The gap between the lines is what was not despatched. Fill rate reads on the right."
            >
              {/* One chart for what used to be three - ordered vs despatched,
                  unfilled over time, and fill rate - because all three were the
                  same two series drawn three ways (docs/DECISIONS.md D-123). */}
              <ResponsiveContainer width="100%" height={chartH('ordered-despatched', 240)}>
                <ComposedChart data={trend} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
                  <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="var(--color-border)" />
                  <XAxis dataKey="label" tick={TICK} minTickGap={22} tickLine={false} />
                  <YAxis yAxisId="units" tick={TICK} tickFormatter={tickNum} />
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

            <Panel {...panelProps('top-skus', 'xl:col-span-2')}
              title="Top SKUs by Ordered Demand"
              accent={BLUE}
              note="Bar length is units ordered; amber is the part not despatched."
            >
              <ResponsiveContainer width="100%" height={chartH('top-skus', 280)}>
                <BarChart
                  data={skuRows}
                  layout="vertical"
                  margin={{ top: 4, right: 20, left: 4, bottom: 0 }}
                  barCategoryGap="22%"
                >
                  <CartesianGrid horizontal={false} strokeDasharray="3 3" stroke="var(--color-border)" />
                  <XAxis type="number" tick={TICK} tickFormatter={tickNum} />
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

            <Panel {...panelProps('unfilled-value-class')} title="Unfilled Demand by Value Class" accent={AMBER} note="Positive shortfall only. Click a column to filter.">
              <ResponsiveContainer width="100%" height={chartH('unfilled-value-class', 196)}>
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
                    /* 52 cut "Not in product master" off by 5.6px: rotated -30
                       degrees, a 21-character label at 8px needs ~45px of
                       vertical band plus the tick gap (D-154). */
                    height={64}
                  />
                  <YAxis
                    tick={TICK}
                    tickFormatter={tickNum}
                    {...magnitudeAxis(summary.by_value_class.map((row) => row.shortfall_units))}
                  />
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

            <Panel {...panelProps('fill-rate')}
              title="Fill Rate by Glass Type"
              accent={GREEN}
              note="Despatched ÷ ordered units. Dashed line is fully filled."
            >
              <ResponsiveContainer width="100%" height={chartH('fill-rate', 215)}>
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

            <Panel {...panelProps('unfilled-age')}
              title="Unfilled Share by Vehicle Age"
              accent={RED}
              note="Units short ÷ units ordered, by vehicle age band."
            >
              <ResponsiveContainer width="100%" height={chartH('unfilled-age', 215)}>
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

            <Panel {...panelProps('ordered-despatched-class')} title="Ordered vs Despatched by Value Class" accent={VIOLET} note="Grey = ordered, solid = despatched.">
              <ResponsiveContainer width="100%" height={chartH('ordered-despatched-class', 186)}>
                <BarChart data={orderedVsDespatched} margin={{ top: 16, right: 6, left: -12, bottom: 0 }} barCategoryGap="26%">
                  <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="var(--color-border)" />
                  <XAxis dataKey="name" tick={{ ...TICK, fontSize: 9 }} tickLine={false} />
                  {/* Grouped, not stacked, so a log axis is sound here: each
                      bar is read against the axis on its own. */}
                  <YAxis
                    tick={TICK}
                    tickFormatter={tickNum}
                    {...magnitudeAxis(
                      orderedVsDespatched.flatMap((row) => [row.ordered, row.despatched]),
                    )}
                  />
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

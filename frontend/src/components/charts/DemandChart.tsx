import { Chart, monthLabel, useChartColors } from './Chart';
import type { DiagnosticPoint, SeriesForecastResponse } from '@/types/phase7';

export type DemandView = 'overview' | 'actual' | 'validation' | 'forecast';

/**
 * Monthly demand: actuals, the out-of-sample backtest, and the forecast.
 *
 * On the **full timeline** all three appear at once, which is only readable
 * if they are told apart at a glance. Three devices do that, and each earns
 * its place:
 *
 * - A **shaded band and a labelled divider** at the forecast origin. Without
 *   it the eye has no boundary between what happened and what is predicted —
 *   the two were one continuous line of the same weight.
 * - **Distinct stroke treatments**: actuals solid with a light fill,
 *   backtest dashed over the history it was scored on, forecast dashed ahead
 *   of the origin, service levels dotted and thin.
 * - The backtest is drawn **only over the months it actually covers**, so it
 *   visibly stops where the evidence stops rather than being interpolated
 *   across the whole history.
 */
export function DemandChart({
  data,
  view = 'overview',
  points = [],
  quantiles = true,
  height = 350,
  range = 0,
}: {
  data: SeriesForecastResponse;
  view?: DemandView;
  points?: DiagnosticPoint[];
  quantiles?: boolean;
  height?: number;
  range?: number;
}) {
  const c = useChartColors();
  const history = range ? data.history.slice(-range) : data.history;
  const future = data.forecasts;
  const actualName = history.some((p) => p.target_source?.includes('sales_proxy'))
    ? 'Actual demand (includes sales proxy)'
    : 'Ordered demand (actual)';
  const periods =
    view === 'validation'
      ? points.map((p) => p.period ?? '')
      : view === 'forecast'
        ? future.map((p) => p.period)
        : view === 'actual'
          ? history.map((p) => p.period)
          : [...history.map((p) => p.period), ...future.map((p) => p.period)];
  const pad = view === 'forecast' ? [] : history.map(() => null);

  const line = (
    name: string,
    values: (number | null)[],
    color: string | undefined,
    dashed = false,
  ) => ({
    name,
    type: 'line',
    data: values,
    showSymbol: values.length < 15,
    symbolSize: 6,
    connectNulls: false,
    itemStyle: { color },
    lineStyle: { width: 2.5, type: dashed ? 'dashed' : 'solid' },
    emphasis: { focus: 'series' },
  });

  /** Backtest predictions aligned to the timeline's own month slots, so they
   *  sit under the actuals they were scored against and stop where they run
   *  out rather than being stretched across the history. */
  const backtestByPeriod = new Map<string, number | null>();
  for (const p of points) if (p.period) backtestByPeriod.set(p.period, p.predicted ?? null);
  const backtestOnTimeline = periods.map((period) => backtestByPeriod.get(period) ?? null);
  const hasBacktest = view === 'overview' && backtestByPeriod.size > 0;

  /** The boundary between observed and predicted, and a wash over the
   *  forecast span. Attached to the actuals series so it draws once. */
  const originIndex = history.length - 1;
  const forecastMarks =
    view === 'overview' && future.length > 0 && history.length > 0
      ? {
          markArea: {
            silent: true,
            itemStyle: { color: c.s2, opacity: 0.055 },
            data: [
              [
                { xAxis: periods[originIndex] ?? '' },
                { xAxis: periods[periods.length - 1] ?? '' },
              ],
            ],
          },
          markLine: {
            silent: true,
            symbol: 'none',
            lineStyle: { color: c['ink-3'], type: 'dashed', width: 1.5 },
            label: {
              formatter: 'forecast begins',
              color: c['ink-3'],
              fontSize: 10,
              position: 'insideEndTop',
            },
            data: [{ xAxis: periods[originIndex] ?? '' }],
          },
        }
      : {};

  const series =
    view === 'validation'
      ? [
          line('Actual', points.map((p) => p.actual), c.s1),
          line('Backtest forecast', points.map((p) => p.predicted), c.s2, true),
        ]
      : [
          ...(view !== 'forecast'
            ? [
                {
                  ...line(
                    actualName,
                    [
                      ...history.map((p) => p.actual),
                      ...(view === 'overview' ? future.map(() => null) : []),
                    ],
                    c.s1,
                  ),
                  areaStyle: { color: c.s1, opacity: 0.065 },
                  ...forecastMarks,
                },
              ]
            : []),
          ...(hasBacktest
            ? [
                {
                  ...line('Backtest (out-of-sample)', backtestOnTimeline, c.s4, true),
                  symbol: 'circle',
                  symbolSize: 5,
                  showSymbol: true,
                  lineStyle: { width: 1.8, type: [5, 4] },
                },
              ]
            : []),
          ...(view !== 'actual'
            ? [
                line('Forecast', [...pad, ...future.map((p) => p.point_forecast)], c.s2, true),
                ...(quantiles
                  ? (['q80', 'q90', 'q95'] as const).map((q, i) => ({
                      ...line(q, [...pad, ...future.map((p) => p[q])], [c.s3, c.s5, c.s6][i], true),
                      symbol: 'none',
                      lineStyle: { width: 1.3, type: 'dotted' },
                    }))
                  : []),
              ]
            : []),
        ];

  /** Which months each series legitimately covers.
   *
   *  The tooltip used the shared `valueFormatter`, which prints "Not
   *  available" for any null. On a multi-series timeline that is wrong and,
   *  in this application, actively misleading: "Not available" is
   *  load-bearing vocabulary for a value that *should* exist and could not be
   *  produced. A forecast has no value in Mar 2026 because the forecast
   *  starts in Aug — that is a structural absence, not a failure, and
   *  labelling it the same way collapses two of the seven states this project
   *  is required to keep apart (docs/DECISIONS.md D-069).
   *
   *  So: a series outside its own span is omitted from the tooltip, and a
   *  null *inside* its span still reads "Not available", because there it
   *  genuinely is. */
  const historyPeriods = new Set(history.map((p) => p.period));
  const futurePeriods = new Set(future.map((p) => p.period));
  const spanFor = (name: string): Set<string> => {
    if (name === actualName || name === 'Actual') return historyPeriods;
    if (name.startsWith('Backtest')) return new Set(backtestByPeriod.keys());
    return futurePeriods;
  };
  const unavailableReason = new Map(
    future.map((f) => [f.period, f.unavailable_reason ?? null]),
  );

  const tooltipFormatter = (params: unknown) => {
    const rows = (Array.isArray(params) ? params : [params]) as Array<{
      axisValue?: string;
      seriesName?: string;
      value?: unknown;
      marker?: string;
    }>;
    if (!rows.length) return '';
    const period = rows[0]?.axisValue ?? '';
    const lines = rows
      .filter((r) => {
        if (r.value != null) return true;
        // Keep an in-span null: that is a real gap worth naming.
        return spanFor(r.seriesName ?? '').has(period);
      })
      .map((r) => {
        const value =
          r.value == null
            ? 'Not available'
            : typeof r.value === 'number'
              ? Intl.NumberFormat('en-IN', { maximumFractionDigits: 2 }).format(r.value)
              : String(r.value);
        return `<div style="display:flex;gap:12px;justify-content:space-between">
          <span>${r.marker ?? ''}${r.seriesName ?? ''}</span>
          <strong>${value}</strong>
        </div>`;
      });
    if (!lines.length) return '';
    const reason = unavailableReason.get(period);
    const footer =
      reason && rows.some((r) => r.value == null && futurePeriods.has(period))
        ? `<div style="margin-top:4px;max-width:260px;white-space:normal;opacity:.75">${reason}</div>`
        : '';
    return `<div><div style="margin-bottom:4px"><strong>${monthLabel(period)}</strong></div>${lines.join('')}${footer}</div>`;
  };

  return (
    <Chart
      label={
        view === 'validation'
          ? 'Actual demand versus out-of-sample backtest forecast, ordered quantity by month'
          : 'Monthly demand: historical actuals, out-of-sample backtest and future point forecasts with optional service-level quantiles'
      }
      height={height}
      option={{
        tooltip: { formatter: tooltipFormatter },
        grid: { left: 68, right: 25, top: 55, bottom: 64 },
        legend: {
          top: 0,
          left: 0,
          type: 'scroll',
          icon: 'roundRect',
          itemWidth: 14,
          itemHeight: 4,
          textStyle: { color: c['ink-2'], fontSize: 11 },
        },
        xAxis: {
          type: 'category',
          data: periods,
          boundaryGap: false,
          axisLine: { lineStyle: { color: c.rule } },
          axisTick: { show: false },
          axisLabel: { color: c['ink-3'], formatter: monthLabel, hideOverlap: true },
        },
        yAxis: {
          type: 'value',
          name: 'Quantity · units',
          nameTextStyle: { color: c['ink-3'], align: 'left' },
          axisLabel: {
            color: c['ink-3'],
            formatter: (v: number) => Intl.NumberFormat('en', { notation: 'compact' }).format(v),
          },
          splitLine: { lineStyle: { color: c.rule, type: 'dashed' } },
        },
        dataZoom: [
          { type: 'inside' },
          {
            type: 'slider',
            height: 18,
            bottom: 5,
            borderColor: c.rule,
            fillerColor: c.s1 + '18',
            textStyle: { color: c['ink-3'] },
            labelFormatter: (_: number, v: string) => monthLabel(v),
          },
        ],
        series,
      }}
    />
  );
}

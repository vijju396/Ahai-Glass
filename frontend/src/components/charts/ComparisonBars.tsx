import { Chart, useChartColors } from './Chart';

/** Presentation-only comparison. All measured quantities come from the API. */
export function ComparisonBars({ labels, series, unit = 'Units', height = 270 }: { labels: string[]; series: { name: string; values: (number | null)[] }[]; unit?: string; height?: number }) {
  const c = useChartColors();
  return <Chart label={`${series.map(s => s.name).join(' versus ')} by ${labels.join(', ')}; ${unit}`} height={height} option={{
    grid: { left: 65, right: 20, top: 48, bottom: 52 },
    legend: { top: 0, left: 0, textStyle: { color: c['ink-2'], fontSize: 11 }, itemWidth: 12, itemHeight: 8 },
    xAxis: { type: 'category', data: labels, axisTick: { show: false }, axisLine: { lineStyle: { color: c.rule } }, axisLabel: { color: c['ink-3'], fontSize: 11, width: 100, overflow: 'break', interval: 0 } },
    yAxis: { type: 'value', name: unit, nameTextStyle: { color: c['ink-3'] }, axisLabel: { color: c['ink-3'], formatter: (v: number) => Intl.NumberFormat('en', { notation: 'compact' }).format(v) }, splitLine: { lineStyle: { color: c.rule, type: 'dashed' } } },
    series: series.map(s => ({ name: s.name, type: 'bar', data: s.values, barMaxWidth: 34, itemStyle: { borderRadius: [4, 4, 0, 0] } })),
  }} />;
}

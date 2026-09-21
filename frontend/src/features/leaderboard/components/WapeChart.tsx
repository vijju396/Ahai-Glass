/**
 * Models on the x-axis, WAPE percentage on the y-axis.
 *
 * A model that did not run has `wape === null` and appears as a **labelled
 * gap**, not as a missing bar: silently fewer bars would let a reader conclude
 * the model was never part of the comparison. The gap carries the reason in its
 * tooltip.
 *
 * Baselines are drawn in a distinct series, because one of them beating the
 * champion is a real and frequent outcome on this data and the chart must not
 * imply otherwise.
 */
import { Chart, useChartColors } from '@/components/charts/Chart';
import type { ComparisonPoint } from '@/types/phase7';
import { Explain } from '@/components/ui/Explain';

interface Props {
  points: ComparisonPoint[];
  /** Rendered under the chart, e.g. the scope these metrics belong to. */
  caption?: string;
}

export function WapeChart({ points, caption }: Props) {
  const c = useChartColors();
  const labels = points.map((point) => point.display_name);
  const registered = points.map((point) =>
    point.is_baseline || point.wape_pct === null ? null : point.wape_pct,
  );
  const baselines = points.map((point) =>
    point.is_baseline ? point.wape_pct : null,
  );
  const missing = points.filter((point) => point.wape_pct === null);

  const option = {
    grid: { left: 56, right: 16, top: 28, bottom: 96 },
    tooltip: {
      trigger: 'axis',
      renderMode: 'richText',
      formatter: (params: { dataIndex: number }[]) => {
        const point = points[params[0]?.dataIndex ?? 0];
        if (!point) return '';
        const lines = [point.display_name, `Status: ${point.status}`];
        if (point.wape_pct === null) {
          lines.push('WAPE: not defined');
          if (point.exclusion_reason) lines.push(point.exclusion_reason);
        } else {
          lines.push(`WAPE: ${point.wape_pct.toFixed(3)}%`);
        }
        if (point.is_baseline) lines.push('Non-registry baseline — never champion');
        if (point.is_champion) lines.push('Champion');
        return lines.join('\n');
      },
    },
    legend: { data: ['Registered models', 'Baselines'], top: 0, textStyle: { color: c['ink-2'] } },
    xAxis: {
      type: 'category',
      data: labels,
      axisLabel: { rotate: 38, fontSize: 10, interval: 0, color: c['ink-3'] },
    },
    yAxis: {
      type: 'value',
      name: 'WAPE %',
      nameLocation: 'middle',
      nameGap: 42,
      axisLabel: { formatter: '{value}%', color: c['ink-3'] },
      splitLine: { lineStyle: { color: c.rule, type: 'dashed' } },
    },
    series: [
      {
        name: 'Registered models',
        type: 'bar',
        data: registered,
        itemStyle: { color: c.s1, borderRadius: [4, 4, 0, 0] },
        emphasis: { focus: 'series' },
      },
      {
        name: 'Baselines',
        type: 'bar',
        data: baselines,
        itemStyle: { color: c.s4, borderRadius: [4, 4, 0, 0] },
        emphasis: { focus: 'series' },
      },
    ],
  };

  return (
    <div>
      <Chart option={option} height={360} label="All registered models and baselines compared by WAPE percentage; unavailable metrics remain labelled gaps" />
      {missing.length > 0 && (
        <Explain variant="note">
          No bar for {missing.map((point) => point.display_name).join(', ')} —
          WAPE is not defined for {missing.length === 1 ? 'it' : 'them'} in this
          scope. The models are on the axis with a gap rather than removed from
          the comparison.
        </Explain>
      )}
      {caption && <Explain variant="note">{caption}</Explain>}
    </div>
  );
}

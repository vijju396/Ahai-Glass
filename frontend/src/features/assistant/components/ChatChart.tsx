/**
 * Renders whichever chart the assistant's backend facts produced for the
 * question just asked. Ported from the reference's `ChatChart.tsx`, and it
 * reuses the same style tokens the dashboard pages use so a chat chart looks
 * like part of the app rather than a bolted-on extra.
 *
 * The chart *spec* is built in the backend from the same facts the answer is
 * written from, so a chart here can never disagree with the paragraph above
 * it, and the model is never asked to author a data array. `type` is one of
 * three allowlisted values; anything else never reaches this component.
 */
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { SERIES_COLORS, TICK, TOOLTIP } from '@/components/ui/Dashboard';
import type { AssistantChart } from '@/api/analytics';

const formatValue = (value: unknown): string => {
  if (typeof value !== 'number') return String(value ?? '');
  if (Number.isInteger(value)) return value.toLocaleString('en-IN');
  return value.toFixed(1);
};

export function ChatChart({ chart }: { chart: AssistantChart }) {
  return (
    <figure className="mt-2 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-2.5">
      <figcaption className="mb-1.5 text-[10px] font-semibold uppercase tracking-[0.06em] text-[var(--color-text-muted)]">
        {chart.title}
      </figcaption>
      <ResponsiveContainer width="100%" height={190}>
        {chart.type === 'line' ? (
          <LineChart data={chart.data} margin={{ top: 4, right: 8, left: -18, bottom: 0 }}>
            <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="var(--color-border)" />
            <XAxis dataKey={chart.x_key} tick={{ ...TICK, fontSize: 9 }} tickLine={false} minTickGap={24} />
            <YAxis tick={TICK} width={44} tickFormatter={formatValue} />
            <Tooltip formatter={(value: number) => formatValue(value)} contentStyle={TOOLTIP} />
            {chart.series.map((series, index) => (
              <Line
                key={series.key}
                type="monotone"
                dataKey={series.key}
                name={series.label}
                stroke={series.color ?? SERIES_COLORS[index % SERIES_COLORS.length]}
                strokeWidth={1.75}
                dot={false}
                isAnimationActive={false}
              />
            ))}
          </LineChart>
        ) : chart.type === 'bar' ? (
          // Below ~15 categories every label fits angled; above that they would
          // collide, so fall back to the auto-thinned axis the line chart uses.
          <BarChart
            data={chart.data}
            margin={{ top: 4, right: 8, left: -18, bottom: 0 }}
            barCategoryGap={chart.data.length <= 15 ? '28%' : '10%'}
          >
            <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="var(--color-border)" />
            {chart.data.length <= 15 ? (
              <XAxis
                dataKey={chart.x_key}
                tick={{ ...TICK, fontSize: 8 }}
                tickLine={false}
                interval={0}
                angle={-20}
                textAnchor="end"
                height={44}
              />
            ) : (
              <XAxis dataKey={chart.x_key} tick={{ ...TICK, fontSize: 9 }} tickLine={false} minTickGap={24} />
            )}
            <YAxis tick={TICK} width={44} tickFormatter={formatValue} />
            <Tooltip formatter={(value: number) => formatValue(value)} contentStyle={TOOLTIP} />
            {chart.series.map((series, index) => (
              <Bar
                key={series.key}
                dataKey={series.key}
                name={series.label}
                fill={series.color ?? SERIES_COLORS[index % SERIES_COLORS.length]}
                radius={[4, 4, 0, 0]}
                isAnimationActive={false}
              />
            ))}
          </BarChart>
        ) : (
          <PieChart>
            <Pie
              data={chart.data}
              dataKey={chart.series[0]?.key ?? 'value'}
              nameKey={chart.x_key}
              cx="50%"
              cy="50%"
              innerRadius={42}
              outerRadius={70}
              paddingAngle={2}
              stroke="none"
              isAnimationActive={false}
            >
              {chart.data.map((_row, index) => (
                <Cell key={index} fill={SERIES_COLORS[index % SERIES_COLORS.length]} />
              ))}
            </Pie>
            <Tooltip formatter={(value: number) => formatValue(value)} contentStyle={TOOLTIP} />
          </PieChart>
        )}
      </ResponsiveContainer>
    </figure>
  );
}

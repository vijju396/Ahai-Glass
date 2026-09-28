/**
 * The four charts on the Lead Time page.
 *
 * Each answers a question the table cannot (D-105):
 *
 * - **Trend** — is the observed duration moving? It is: measured over this
 *   workspace, the last third of the months runs 43.9% above the first third.
 *   Monthly points, not a rolling mean: a smoothed line blurs the month a
 *   change started, and the month is the useful part.
 * - **Distribution** — the mean says 3.9 days; the distribution says how often
 *   it is 8 or more. A planner is exposed to the tail, not the average.
 * - **Stated against observed** — grouped bars, never stacked. Stacking would
 *   assert that the two add up to something, and they do not: one is a
 *   supplied planning figure, the other a measured duration.
 * - **By SKU** — Location Master is branch-grained, so there is no stated
 *   per-SKU figure to compare against and none is drawn.
 *
 * The stated average is a reference line on the trend chart rather than a
 * series, because it is one number per branch for the whole window — drawing
 * it as a line over time would imply it was measured monthly.
 */
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type {
  LeadTimeBucket,
  LeadTimeMonth,
  LeadTimeObservedBranch,
  LeadTimeSku,
} from '@/api/analytics';
import { AMBER, BLUE, NAVY, RED, TEAL, TICK, TOOLTIP } from '@/components/ui/Dashboard';
import { Card } from '@/components/ui/Card';

const BRANCH_COLORS = [BLUE, TEAL, NAVY, AMBER];

export function LeadTimeTrendChart({
  months,
  branches,
}: {
  months: LeadTimeMonth[];
  branches: LeadTimeObservedBranch[];
}) {
  const names = branches.map((b) => b.branch);
  // One stated figure per branch for the whole window. Averaged only when the
  // workspace holds more than one, and labelled as the reference it is.
  const stated = branches
    .map((b) => b.stated_avg)
    .filter((v): v is number => v != null);
  const statedRef = stated.length
    ? stated.reduce((a, b) => a + b, 0) / stated.length
    : null;

  return (
    <Card
      title="Observed lead time by order month"
      subtitle="Mean days from Order Date to Despatch Date, per month"
    >
      <ResponsiveContainer width="100%" height={240}>
        <LineChart data={months} margin={{ top: 8, right: 12, left: -20, bottom: 0 }}>
          <CartesianGrid strokeDasharray="2 4" stroke="var(--color-border)" vertical={false} />
          <XAxis dataKey="period" tick={TICK} interval="preserveStartEnd" />
          <YAxis tick={TICK} unit="d" width={38} />
          <Tooltip
            formatter={(value: number, name: string) => [`${value} d`, name]}
            contentStyle={TOOLTIP}
          />
          <Legend wrapperStyle={{ fontSize: 10 }} />
          {statedRef != null && (
            <ReferenceLine
              y={statedRef}
              stroke={RED}
              strokeDasharray="4 4"
              label={{
                value: `Stated ${statedRef.toFixed(1)} d`,
                position: 'insideTopRight',
                fontSize: 9,
                fill: RED,
              }}
            />
          )}
          {names.map((name, i) => (
            <Line
              key={name}
              type="monotone"
              dataKey={name}
              name={name}
              stroke={BRANCH_COLORS[i % BRANCH_COLORS.length]}
              strokeWidth={2}
              dot={{ r: 2 }}
              isAnimationActive={false}
              connectNulls={false}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
      <p className="mt-1 text-[10px] leading-relaxed text-[var(--color-text-muted)]">
        The dashed line is the stated average from Location Master — one figure for the whole
        window, drawn as a reference rather than a series because it was not measured monthly.
        Points are monthly means, not smoothed: a rolling average would blur the month a
        change began.
      </p>
    </Card>
  );
}

export function LeadTimeDistributionChart({ buckets }: { buckets: LeadTimeBucket[] }) {
  return (
    <Card
      title="How long orders actually took"
      subtitle="Share of order lines by whole days from order to despatch"
    >
      <ResponsiveContainer width="100%" height={200}>
        <BarChart data={buckets} margin={{ top: 8, right: 12, left: -22, bottom: 0 }}>
          <CartesianGrid strokeDasharray="2 4" stroke="var(--color-border)" vertical={false} />
          <XAxis dataKey="label" tick={TICK} />
          <YAxis tick={TICK} unit="%" width={38} />
          <Tooltip
            formatter={(value: number, _n, item) => [
              `${value}% (${(item?.payload?.lines ?? 0).toLocaleString('en-IN')} lines)`,
              'Share',
            ]}
            contentStyle={TOOLTIP}
          />
          <Bar dataKey="share_pct" radius={[3, 3, 0, 0]} isAnimationActive={false}>
            {buckets.map((b) => (
              // The tail is coloured, not hidden. A planner is exposed to the
              // slow days, not to the average one.
              <Cell key={b.label} fill={b.days >= 7 ? AMBER : BLUE} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      <p className="mt-1 text-[10px] leading-relaxed text-[var(--color-text-muted)]">
        The final bar is a catch-all for everything at or beyond that many days, so the tail
        is visible as a tail rather than running off the axis. Amber marks a week or more.
      </p>
    </Card>
  );
}

export function LeadTimeStatedVsObservedChart({
  branches,
}: {
  branches: LeadTimeObservedBranch[];
}) {
  const data = branches.map((b) => ({
    branch: b.branch,
    stated: b.stated_avg,
    observed: b.observed_mean,
    p95: b.observed_p95,
  }));
  return (
    <Card
      title="Stated against observed, by branch"
      subtitle="The master's figure, the measured mean, and the measured p95"
    >
      <ResponsiveContainer width="100%" height={200}>
        <BarChart data={data} margin={{ top: 8, right: 12, left: -22, bottom: 0 }} barCategoryGap="25%">
          <CartesianGrid strokeDasharray="2 4" stroke="var(--color-border)" vertical={false} />
          <XAxis dataKey="branch" tick={TICK} />
          <YAxis tick={TICK} unit="d" width={38} />
          <Tooltip formatter={(value: number, name: string) => [`${value} d`, name]} contentStyle={TOOLTIP} />
          <Legend wrapperStyle={{ fontSize: 10 }} />
          {/* Grouped, never stacked. Stacking would assert the three add up to
              something; one is a supplied planning figure and two are measured
              durations of the same lines. */}
          <Bar dataKey="stated" name="Stated average" fill={NAVY} radius={[3, 3, 0, 0]} isAnimationActive={false} />
          <Bar dataKey="observed" name="Observed mean" fill={BLUE} radius={[3, 3, 0, 0]} isAnimationActive={false} />
          <Bar dataKey="p95" name="Observed p95" fill={AMBER} radius={[3, 3, 0, 0]} isAnimationActive={false} />
        </BarChart>
      </ResponsiveContainer>
    </Card>
  );
}

export function LeadTimeBySkuChart({ skus }: { skus: LeadTimeSku[] }) {
  const data = [...skus]
    .sort((a, b) => b.mean - a.mean)
    .map((s) => ({ ...s, short: s.sku.replace(/^FG\./, '') }));
  return (
    <Card
      title="Observed lead time by SKU"
      subtitle="Slowest first. Location Master is branch-grained, so there is no stated per-SKU figure to compare against"
    >
      <ResponsiveContainer width="100%" height={Math.max(220, data.length * 18)}>
        <BarChart
          data={data}
          layout="vertical"
          margin={{ top: 4, right: 16, left: 4, bottom: 0 }}
          barCategoryGap="22%"
        >
          <CartesianGrid strokeDasharray="2 4" stroke="var(--color-border)" horizontal={false} />
          <XAxis type="number" tick={TICK} unit="d" />
          <YAxis type="category" dataKey="short" tick={{ ...TICK, fontSize: 9 }} width={128} />
          <Tooltip
            formatter={(value: number, name: string, item) => [
              `${value} d`,
              name === 'mean' ? `Mean (${(item?.payload?.lines ?? 0).toLocaleString('en-IN')} lines)` : name,
            ]}
            contentStyle={TOOLTIP}
          />
          <Legend wrapperStyle={{ fontSize: 10 }} />
          <Bar dataKey="mean" name="Mean" fill={BLUE} radius={[0, 3, 3, 0]} isAnimationActive={false} />
          <Bar dataKey="p95" name="p95" fill={AMBER} radius={[0, 3, 3, 0]} isAnimationActive={false} />
        </BarChart>
      </ResponsiveContainer>
    </Card>
  );
}

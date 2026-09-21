/**
 * Lead-time panels for Supply Intelligence.
 *
 * The lead-time file is one of the five client sources, and until now its only
 * appearance in the UI was a single column in the replenishment table plus the
 * ingestion controls in Data Studio. Two of the three computed columns —
 * `std_lead_time_days` and `transit_lead_time_days` — reached no screen at all.
 *
 * The panel that matters most here is **Least reliable branches**. The
 * replenishment protection period is `review period + average lead time`, so a
 * branch whose lead time swings between 1 and 6 days gets exactly the same
 * cover as one that is reliably 3 days. Nothing in the application said so
 * before. This does not change any recommended quantity — it makes the
 * omission visible, which is a prerequisite for deciding whether to fix it.
 */
import { useQuery } from '@tanstack/react-query';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { fetchLeadTime, leadTimeKeys } from '@/api/analytics';
import {
  AMBER,
  BLUE,
  NAVY,
  Panel,
  RED,
  SLATE,
  StatTile,
  TEAL,
  TICK,
  TOOLTIP,
} from '@/components/ui/Dashboard';
import { Card } from '@/components/ui/Card';
import { ErrorState, LoadingBlock } from '@/components/ui/States';
import { Explain } from '@/components/ui/Explain';

/** Above this, spread relative to the mean is large enough that the average
 *  alone is a poor planning number. Not a threshold from the data — a stated
 *  reading aid, drawn as a reference line so the reader can disagree with it. */
const HIGH_VARIABILITY_CV = 40;

/** Branches shown on the main bar chart. Forty-nine rotated depot names leave
 *  ~9px per label where a 55-degree rotation needs ~13px to stay clear, so the
 *  chart has to show fewer — the same cap the other branch charts on this
 *  application use, and it is named in the panel note. The full set is still
 *  in the payload and in the recommendation table above. */
const BRANCHES_CHARTED = 12;

export function LeadTimePanels() {
  const query = useQuery({ queryKey: leadTimeKeys.all, queryFn: () => fetchLeadTime() });
  const data = query.data;

  if (query.isLoading) return <LoadingBlock label="Reading lead times" />;
  if (query.isError) return <ErrorState error={query.error} />;
  if (!data || data.empty) {
    return (
      <Card>
        <Explain variant="hint">{data?.reason ?? 'No lead-time data is available yet.'}</Explain>
      </Card>
    );
  }

  const { kpis } = data;
  const worst = data.least_reliable[0];

  return (
    <div className="flex flex-col gap-3">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatTile
          label="Median lead time"
          value={`${kpis.median_avg_days ?? '—'} d`}
          sublabel={`p95 ${kpis.p95_avg_days ?? '—'} d · max ${kpis.max_avg_days ?? '—'} d`}
          tint="blue"
          accent
        />
        <StatTile
          label="Branches measured"
          value={`${kpis.branches_with_a_usable_lead_time} of ${kpis.branches}`}
          sublabel={
            // "the rest report a zero-day lead time" is a lie when there is no
            // rest, which is exactly what a two-branch workspace produces.
            kpis.branches_with_a_usable_lead_time < kpis.branches
              ? `${kpis.branches - kpis.branches_with_a_usable_lead_time} report a zero-day lead time`
              : 'every branch in this workspace reports one'
          }
          tint="navy"
        />
        <StatTile
          label="Median spread"
          value={`± ${kpis.median_std_days ?? '—'} d`}
          sublabel="standard deviation per branch"
          tint="teal"
        />
        <StatTile
          label="Least reliable"
          value={worst ? `${worst.cv_pct}%` : '—'}
          sublabel={worst ? `${worst.branch} · ${worst.avg_days} d ± ${worst.std_days} d` : undefined}
          tint="amber"
        />
      </div>

      <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
        <Panel
          title="Lead Time by Branch"
          accent={BLUE}
          className="lg:col-span-2"
          note={`Average days to receipt, slowest first — the ${BRANCHES_CHARTED} slowest of ${data.by_branch.length} measured branches. The amber bar is the spread (± one standard deviation): a tall amber bar on a short blue one is a branch you cannot plan around.`}
        >
          <ResponsiveContainer width="100%" height={230}>
            <BarChart
              data={data.by_branch.slice(0, BRANCHES_CHARTED)}
              margin={{ top: 8, right: 8, left: -14, bottom: 0 }}
              barCategoryGap="18%"
            >
              <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="var(--color-border)" />
              <XAxis
                dataKey="branch"
                tick={{ ...TICK, fontSize: 7 }}
                tickLine={false}
                interval={0}
                angle={-45}
                textAnchor="end"
                height={72}
              />
              <YAxis tick={TICK} unit="d" width={34} />
              <Tooltip
                formatter={(value: number, name: string) => [`${value} d`, name]}
                contentStyle={TOOLTIP}
              />
              <Legend wrapperStyle={{ fontSize: 9 }} />
              {kpis.median_avg_days != null && (
                <ReferenceLine
                  y={kpis.median_avg_days}
                  stroke={SLATE}
                  strokeDasharray="4 4"
                  label={{
                    value: `median ${kpis.median_avg_days}d`,
                    position: 'insideTopRight',
                    fill: SLATE,
                    fontSize: 9,
                  }}
                />
              )}
              <Bar dataKey="avg_days" name="Average" fill={BLUE} radius={[3, 3, 0, 0]} isAnimationActive={false} />
              <Bar dataKey="std_days" name="Spread (± 1 sd)" fill={AMBER} radius={[3, 3, 0, 0]} isAnimationActive={false} />
            </BarChart>
          </ResponsiveContainer>
        </Panel>

        <Panel
          title="Least Reliable Branches"
          accent={RED}
          note={`Spread as a percentage of the mean, worst first. The dashed line marks ${HIGH_VARIABILITY_CV}% — above it, the average alone is a weak planning number.`}
        >
          <ResponsiveContainer width="100%" height={230}>
            <BarChart
              data={data.least_reliable}
              layout="vertical"
              margin={{ top: 4, right: 30, left: 4, bottom: 0 }}
            >
              <CartesianGrid horizontal={false} strokeDasharray="3 3" stroke="var(--color-border)" />
              <XAxis type="number" tick={TICK} unit="%" />
              <YAxis
                type="category"
                dataKey="branch"
                tick={{ ...TICK, fontSize: 8 }}
                width={104}
                tickLine={false}
              />
              <Tooltip
                formatter={(value: number, _name, item) => {
                  const row = item?.payload as { avg_days?: number; std_days?: number };
                  return [`${value}% — ${row?.avg_days} d ± ${row?.std_days} d`, 'Variability'];
                }}
                contentStyle={TOOLTIP}
              />
              <ReferenceLine x={HIGH_VARIABILITY_CV} stroke={SLATE} strokeDasharray="4 4" />
              <Bar dataKey="cv_pct" radius={[0, 3, 3, 0]} isAnimationActive={false}>
                {data.least_reliable.map((row) => (
                  <Cell key={row.branch} fill={row.cv_pct != null && row.cv_pct >= HIGH_VARIABILITY_CV ? RED : AMBER} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </Panel>
      </div>

      <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
        <Panel title="Lead-Time Distribution" accent={TEAL} note="How many branches sit at each whole-day average.">
          <ResponsiveContainer width="100%" height={170}>
            <BarChart data={data.distribution} margin={{ top: 14, right: 6, left: -18, bottom: 0 }} barCategoryGap="26%">
              <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="var(--color-border)" />
              <XAxis dataKey="bucket" tick={{ ...TICK, fontSize: 9 }} tickLine={false} interval={0} />
              <YAxis tick={TICK} width={28} allowDecimals={false} />
              <Tooltip formatter={(value: number) => [`${value} branches`, '']} contentStyle={TOOLTIP} />
              <Bar dataKey="branches" fill={TEAL} radius={[3, 3, 0, 0]} isAnimationActive={false} />
            </BarChart>
          </ResponsiveContainer>
        </Panel>

        <Panel
          title="Transit vs Handling"
          accent={NAVY}
          note="Total lead time split into the journey and everything else. A negative handling figure means the two source columns disagree — those branches are in the anomalies panel, not here."
        >
          <ResponsiveContainer width="100%" height={170}>
            <BarChart
              data={data.by_branch.filter((row) => (row.handling_days ?? -1) >= 0).slice(0, 12)}
              margin={{ top: 8, right: 6, left: -18, bottom: 0 }}
              barCategoryGap="20%"
            >
              <CartesianGrid vertical={false} strokeDasharray="3 3" stroke="var(--color-border)" />
              <XAxis
                dataKey="branch"
                tick={{ ...TICK, fontSize: 7 }}
                tickLine={false}
                interval={0}
                angle={-50}
                textAnchor="end"
                height={56}
              />
              <YAxis tick={TICK} unit="d" width={30} />
              <Tooltip formatter={(value: number, name: string) => [`${value} d`, name]} contentStyle={TOOLTIP} />
              <Legend wrapperStyle={{ fontSize: 9 }} />
              <Bar dataKey="transit_days" name="Transit" stackId="lt" fill={NAVY} isAnimationActive={false} />
              <Bar dataKey="handling_days" name="Handling" stackId="lt" fill={TEAL} radius={[3, 3, 0, 0]} isAnimationActive={false} />
            </BarChart>
          </ResponsiveContainer>
        </Panel>

        <Panel
          title="Lead-Time Anomalies"
          accent={AMBER}
          note={`${kpis.anomaly_count} finding(s). Surfaced, not corrected — these are properties of the source file.`}
        >
          {data.anomalies.length === 0 ? (
            <p className="py-3 text-[11px] text-[var(--color-text-muted)]">
              No branch reports an impossible lead time.
            </p>
          ) : (
            <div className="ref-scroll flex max-h-[170px] flex-col gap-1.5 overflow-y-auto">
              {data.anomalies.map((row, index) => (
                <div
                  key={`${row.branch}-${index}`}
                  className="border-b border-[var(--color-border)] pb-1.5 last:border-0"
                >
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="text-[11px] font-semibold text-[var(--color-text)]">{row.branch}</span>
                    <span className="shrink-0 text-[10px] text-[var(--color-text-muted)]">
                      {row.avg_days ?? '—'} d total · {row.transit_days ?? '—'} d transit
                    </span>
                  </div>
                  <p className="text-[10px] leading-relaxed text-[var(--color-text-muted)]">{row.reason}</p>
                </div>
              ))}
            </div>
          )}
        </Panel>
      </div>

      <Card>
        <h3 className="text-[11px] font-semibold uppercase tracking-[0.06em] text-[var(--color-text)]">
          How to read these lead times
        </h3>
        <ul className="mt-2 flex flex-col gap-1.5">
          {data.notes.map((note) => (
            <li key={note} className="text-[11px] leading-relaxed text-[var(--color-text-muted)]">
              {note.replaceAll('**', '')}
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}

/**
 * Forecast accuracy across every SKU and location, as a few metric types.
 *
 * One honest question — "how close are the forecasts?" — has more than one
 * honest answer, because there is more than one way to measure a miss. This
 * panel shows the same result expressed four ways rather than picking one and
 * hiding the rest:
 *
 * - **Accuracy** — 100 minus the average percentage miss (MAPE), floored at
 *   zero. The everyday "how right, on average" number.
 * - **MAPE** — that average percentage miss on its own.
 * - **WAPE** — the miss measured as a share of total volume, so a big-selling
 *   line counts for more than a slow one.
 * - **Volume-weighted accuracy** — 100 minus WAPE.
 *
 * Every figure is the **median across lines** of that line's own official,
 * leakage-safe metric — never a pooled sum, which a single blown-up forecast
 * would swamp. It reads from `GET /api/training/{id}/accuracy-windows`, the
 * same run the Training page uses, so the two never disagree.
 */
import { useQuery } from '@tanstack/react-query';
import { accuracyKeys, fetchAccuracyWindows, fetchCurrentRun, trainingKeys } from '@/api/training';
import { GREEN, Panel } from '@/components/ui/Dashboard';
import { periodNoun, periodNounOne } from '@/app/period';

function Metric({
  value,
  suffix = '%',
  label,
  hint,
  strong,
}: {
  value: number | null | undefined;
  suffix?: string;
  label: string;
  hint: string;
  strong?: boolean;
}) {
  return (
    <div className="min-w-[150px] flex-1 border-l border-[var(--color-border)] pl-3 first:border-l-0 first:pl-0">
      <div
        className="text-[28px] font-semibold leading-none tabular-nums"
        style={{ color: strong ? GREEN : 'var(--color-text)' }}
      >
        {value == null ? '—' : `${value.toFixed(1)}${suffix}`}
      </div>
      <div className="mt-1 text-[11px] font-semibold text-[var(--color-text)]">{label}</div>
      <div className="text-[10px] leading-tight text-[var(--color-text-muted)]">{hint}</div>
    </div>
  );
}

export function CombinedAccuracy() {
  const current = useQuery({
    queryKey: trainingKeys.current,
    queryFn: fetchCurrentRun,
    retry: false,
    staleTime: 60_000,
  });
  const runId = current.data?.id;
  const windows = useQuery({
    queryKey: accuracyKeys.windows(runId ?? '', null),
    queryFn: () => fetchAccuracyWindows(runId as string, null),
    enabled: !!runId,
    retry: false,
  });

  const d = windows.data;
  if (!runId || !d) return null;

  // The headline is the six-month total, because that is the window the plant
  // actually plans and buys on — a schedule is judged on the half-year it
  // covers, not on whether any one week landed. `combined_metrics_horizon` is
  // computed whether or not it clears the target, so this never silently falls
  // back to a per-period figure while the caption says six months.
  const horizon = d.combined_metrics_horizon;
  const perPeriod = d.combined_metrics;
  // Falls back to the per-period median only when there is no six-month block
  // to score at all — a run too short to contain one. The caption below
  // follows the same branch, so the words always match the number.
  const m = horizon ?? perPeriod;
  const unit = periodNoun(d.panel_grain);
  const unitOne = periodNounOne(d.panel_grain);
  const blockNote = horizon
    ? `${horizon.window_periods} ${unit} added together, ${horizon.blocks} such stretches across ${horizon.lines} branch × SKU lines`
    : `${m.lines} branch × SKU lines`;

  return (
    <Panel
      title="Forecast accuracy across every SKU and location"
      accent={GREEN}
      note={
        horizon
          ? `Measured on the six-month total — ${blockNote} — over ${unit} the models were tested against and never fitted on.`
          : `No six-month stretch was scored on this run, so this is the median across ${m.lines} lines of each line's own single-${unitOne} metric.`
      }
    >
      <div className="flex flex-wrap items-stretch gap-3">
        <Metric
          value={m.accuracy_pct}
          label="Accuracy"
          hint={horizon ? 'over six months, higher is better' : `per ${unitOne}, higher is better`}
          strong
        />
        <Metric
          value={m.mape_pct}
          label="Average miss"
          hint={horizon ? 'over six months, lower is better' : `per ${unitOne}, lower is better`}
        />
        <Metric
          value={m.weighted_accuracy_pct}
          label="Volume-weighted accuracy"
          hint="weights big-selling lines more"
        />
        <Metric value={m.wape_pct} label="Volume-weighted miss" hint="miss as a share of volume, lower is better" />
      </div>

      {/* The single-period figure is kept in view rather than replaced. Six
          months is the number a plan is held to, but it is a larger total with
          the misses cancelling inside it; a reader who takes 82.8% to mean
          "any given week lands within 17%" has misread it, and the only
          reliable guard against that is showing both. */}
      {horizon && perPeriod && perPeriod.accuracy_pct != null && (
        <p className="mt-3 border-t border-[var(--color-border)] pt-2 text-[11px] leading-relaxed text-[var(--color-text-muted)]">
          <strong>One {unitOne} on its own is {perPeriod.accuracy_pct.toFixed(1)}% accurate</strong>
          {perPeriod.weighted_accuracy_pct != null &&
            ` (${perPeriod.weighted_accuracy_pct.toFixed(1)}% volume-weighted)`}
          . It is the same forecasts either way — six months is higher because
          over- and under-forecasts inside the window cancel, not because the
          model is better. Plan a half-year against the figure above; do not
          read it as what a single {unitOne} will do.{' '}
          {horizon.series_at_target} of {horizon.series_scored} lines clear{' '}
          {d.target_accuracy_pct}% on their own over six months
          {horizon.meets_target === false &&
            `, though no window's middle line reaches ${d.target_accuracy_pct}%`}
          .{' '}
          {horizon.lines_worse_over_horizon > 0 && (
            <>
              Cancelling is not guaranteed:{' '}
              <strong>
                {horizon.lines_worse_over_horizon} of{' '}
                {horizon.lines_better_over_horizon + horizon.lines_worse_over_horizon} lines
                are <em>less</em> accurate over six months
              </strong>
              , because a model that misses the same way every {unitOne} compounds
              rather than cancels. Open a line to see which figure it is.
            </>
          )}
        </p>
      )}
    </Panel>
  );
}

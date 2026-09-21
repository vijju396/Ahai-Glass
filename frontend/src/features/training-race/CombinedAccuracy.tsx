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
  // The headline is the recommended-window ("86%") reading; fall back to the
  // all-lines median only if no window cleared the target.
  const m = d.combined_metrics_best ?? d.combined_metrics;
  const window = d.combined_metrics_best?.window_label ?? null;

  return (
    <Panel
      title="Forecast accuracy across every SKU and location"
      accent={GREEN}
      note={
        window
          ? `Measured over ${window.toLowerCase()}, across ${m.lines} branch × SKU lines, on months the models were tested against and never fitted on.`
          : `The median across ${m.lines} lines of each line's own metric, on months the models were tested against and never fitted on.`
      }
    >
      <div className="flex flex-wrap items-stretch gap-3">
        <Metric value={m.accuracy_pct} label="Accuracy" hint="100 − average miss, higher is better" strong />
        <Metric value={m.mape_pct} label="Average miss" hint="typical gap to actual, lower is better" />
        <Metric
          value={m.weighted_accuracy_pct}
          label="Volume-weighted accuracy"
          hint="weights big-selling lines more"
        />
        <Metric value={m.wape_pct} label="Volume-weighted miss" hint="miss as a share of volume, lower is better" />
      </div>
    </Panel>
  );
}

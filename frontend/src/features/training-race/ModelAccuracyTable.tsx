/**
 * Every model, on one table, scored on the number it is actually chosen by.
 *
 * The console beside this answers "which model won *this* line". The question
 * it could not answer was the one asked first in a demo: **how accurate is
 * each of the thirteen, over the window we plan in, and is that what decided
 * the winner?** The page carried per-line leaderboards and a combined headline
 * and nothing in between.
 *
 * Accuracy is the six-month figure - the forecasts added up across the
 * planning window and scored against the actual total - and MAPE is the same
 * number the other way round, 100 minus it. That is what the champion selector
 * ranks on (docs/DECISIONS.md D-120), so "lines won" is read off the same
 * column that produced it. Read from `/api/training/{run}/monitor`.
 *
 * **How many lines each model was scored on is on the row's tooltip, not in a
 * column.** Four models here ran on 5 of 40 lines and score far better on
 * those, so the top row of this table wins nothing at all. The count was a
 * column until the table was cut back to accuracy and MAPE on request; it is
 * still on every row that differs from the rest, because without it those four
 * rows read as the best models rather than as a different set of lines.
 */
import { useQuery } from '@tanstack/react-query';
import {
  fetchCurrentRun,
  fetchTrainingMonitor,
  monitorKeys,
  trainingKeys,
  type MonitorModel,
} from '@/api/training';
import { GREEN, Panel, SLATE } from '@/components/ui/Dashboard';
import { LoadingBlock } from '@/components/ui/States';

const pct = (v: number | null | undefined, digits = 1) =>
  v == null ? '—' : `${v.toFixed(digits)}%`;

/** Registry models first, then the baselines, each ordered by the metric the
 *  champion is chosen on. A model with no six-month figure sorts last rather
 *  than being dropped — it did run, and its row says so. */
function order(a: MonitorModel, b: MonitorModel): number {
  if (a.is_baseline !== b.is_baseline) return a.is_baseline ? 1 : -1;
  const av = a.horizon_mape ?? Number.POSITIVE_INFINITY;
  const bv = b.horizon_mape ?? Number.POSITIVE_INFINITY;
  return av - bv || a.display_name.localeCompare(b.display_name);
}

export function ModelAccuracyTable() {
  const current = useQuery({
    queryKey: trainingKeys.current,
    queryFn: fetchCurrentRun,
    retry: false,
  });
  const runId = current.data?.id;
  const monitor = useQuery({
    queryKey: monitorKeys.run(runId ?? ''),
    queryFn: () => fetchTrainingMonitor(runId as string),
    enabled: Boolean(runId),
    retry: false,
  });

  if (monitor.isPending && runId) {
    return (
      <Panel title="How accurate each model is" accent={SLATE}>
        <LoadingBlock rows={8} label="Reading the run" />
      </Panel>
    );
  }
  if (!monitor.data) return null;

  const models = monitor.data.models.slice().sort(order);
  const registry = models.filter((m) => !m.is_baseline);
  /* The widest set of lines any model was scored on. A row measured on fewer
     than this is measured on a different, easier or harder set — stated on the
     row rather than left for the reader to infer from a number. */
  const widest = Math.max(0, ...registry.map((m) => m.horizon_scored ?? 0));
  return (
    <Panel
      title="How accurate each model is, over the window we plan in"
      accent={GREEN}
      note="Accuracy over a six-month total — the figure each line's champion is picked on. Every registered model is listed, including the ones that won nothing."
    >
      <div className="table-scroll max-h-[420px]">
        <table className="data">
          <thead>
            <tr>
              <th>Model</th>
              <th className="num">Accuracy</th>
              <th className="num">MAPE</th>
              <th className="num">Lines won</th>
            </tr>
          </thead>
          <tbody>
            {models.map((m) => {
              const short = (m.horizon_scored ?? 0) > 0 && (m.horizon_scored ?? 0) < widest;
              return (
                <tr
                  key={m.model_id}
                  title={
                    short
                      ? `Measured on ${m.horizon_scored} of ${widest} lines — not comparable with a full row.`
                      : (m.reason ?? undefined)
                  }
                >
                  <td
                    style={{
                      fontWeight: m.champion_count > 0 ? 600 : 400,
                      color: m.is_baseline ? 'var(--color-text-muted)' : undefined,
                    }}
                  >
                    {m.display_name}
                    {m.is_baseline && (
                      <span className="ml-1 text-[9px] text-[var(--color-text-muted)]">
                        baseline — never champion
                      </span>
                    )}
                  </td>
                  <td className="num" style={{ fontWeight: 600 }}>
                    {pct(m.horizon_accuracy)}
                  </td>
                  <td className="num">{pct(m.horizon_mape)}</td>
                  <td className="num" style={{ color: m.champion_count > 0 ? GREEN : undefined }}>
                    {m.champion_count || '—'}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

    </Panel>
  );
}

/**
 * The training console: one button, thirteen models, one race.
 *
 * This is the seam between the app and the race. It resolves the field from the
 * API — never from a list in the frontend — picks a trainer, and hands both to
 * `BarRace`, which knows nothing about this application.
 *
 * **Swapping the trainer is one line**, which is the `TRAINER` constant below.
 * `ApiTrainer` submits a real run and streams it; `MockTrainer` needs no
 * backend at all and is what the race was developed against.
 */
import { useMemo, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { fetchCurrentRun, fetchTrainingMonitor, monitorKeys, trainingKeys } from '@/api/training';
import { analyticsKeys, fetchAnalyticsFilters } from '@/api/analytics';
import { resolveModels } from '@/config/models';
import { ErrorState, LoadingBlock } from '@/components/ui/States';
import { BarRace } from './BarRace';
import { Leaderboard } from './Leaderboard';
import { ApiTrainer } from './ApiTrainer';
import { MockTrainer } from './MockTrainer';
import { SSETrainer } from './SSETrainer';

/** Swap to `'mock'` to drive the race with no backend. */
const TRAINER: 'api' | 'mock' = 'api';

export function TrainingConsole() {
  const [error, setError] = useState<string | null>(null);
  const client = useQueryClient();

  const current = useQuery({
    queryKey: trainingKeys.current,
    queryFn: fetchCurrentRun,
    retry: false,
    refetchInterval: 20_000,
  });

  const runId = current.data?.id;
  const live = ['running', 'queued', 'pending'].includes(current.data?.status ?? '');

  // The field. Taken from the most recent run's model rows, which is the only
  // place the frontend learns model identity.
  const monitor = useQuery({
    queryKey: monitorKeys.run(runId ?? ''),
    queryFn: () => fetchTrainingMonitor(runId as string),
    enabled: !!runId,
    retry: false,
    // The *field* — which models exist — does not change while a run is in
    // flight, and re-reading it does. Every refetch produced a new object, a
    // new `models` array, and a `load()` that wiped the race back to zero
    // mid-run. The scores come from the event stream; this query is only ever
    // asked who is racing.
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    refetchOnMount: false,
  });

  const filters = useQuery({
    queryKey: analyticsKeys.filters,
    queryFn: fetchAnalyticsFilters,
    retry: false,
    staleTime: 5 * 60_000,
  });

  /** Keyed on identity, not on the response object.
   *
   *  `useMemo([monitor.data])` still handed back a fresh array on every
   *  refetch, because the object is new even when the field is identical — and
   *  a new array is a new `load()`. The key is the model ids themselves, so
   *  the array is stable for as long as the field really is. */
  const fieldKey = (monitor.data?.models ?? [])
    .map((m) => `${m.model_id}:${m.is_baseline ? 1 : 0}`)
    .join('|');

  /** The thirteen registered models race. The four non-registry baselines are
   *  still fitted and still reported — the leaderboard states the strongest of
   *  them and how many registered models it beats — but they are not lanes.
   *  They are not candidates, and a bar implies a candidate. */
  const models = useMemo(
    () => resolveModels(monitor.data?.models ?? []).filter((m) => !m.isBaseline),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [fieldKey],
  );

  const scope = filters.data?.workspace_scope;
  const body = useMemo(
    () => ({
      tiers: ['aggregate', 'local'],
      ...(scope?.branches ? { branches: scope.branches } : {}),
      ...(scope?.skus ? { skus: scope.skus } : {}),
    }),
    [scope],
  );

  const trainer = useMemo(
    () =>
      TRAINER === 'mock'
        ? new MockTrainer()
        : new ApiTrainer(
            body,
            // Re-read the current run the moment one is submitted, so the race
            // attaches to it in a second rather than waiting for the poll.
            () => client.invalidateQueries({ queryKey: trainingKeys.current }),
            (message) => setError(message),
          ),
    [body, client],
  );

  /** The run already in existence, streamed without being asked for.
   *
   *  Keyed on the run id and whether it is live, so the race re-attaches when
   *  a new run starts and not on every render. The mock has nothing to attach
   *  to — it is not a run. */
  const attach = useMemo(
    () =>
      TRAINER === 'mock' || !runId
        ? null
        : { trainer: new SSETrainer(runId), live, key: `${runId}:${live}` },
    [runId, live],
  );

  if (current.isLoading || (runId && monitor.isLoading)) {
    return <LoadingBlock label="Reading the model field…" />;
  }
  if (monitor.error) return <ErrorState error={monitor.error} />;

  if (!models.length) {
    return (
      <p className="text-[11px] leading-relaxed text-[var(--color-text-muted)]">
        No training run has been recorded yet, so the field is not known. The race lists the
        models a run reports; start one and they appear.
      </p>
    );
  }

  return (
    <>
      <BarRace
        models={models}
        trainer={trainer}
        attach={attach}
        onStart={() => setError(null)}
      />

      <div className="mt-4 border-t border-[var(--color-border)] pt-3">
        <h4 className="mb-1 text-[11px] font-semibold uppercase tracking-[0.06em] text-[var(--color-text)]">
          Model leaderboard
        </h4>
        <Leaderboard
          models={monitor.data?.models ?? []}
          championsSelected={(monitor.data?.models ?? []).some((m) => m.champion_count > 0)}
        />
      </div>
      {error && (
        <p className="mt-2 text-[10.5px] leading-relaxed" style={{ color: 'var(--color-danger)' }}>
          {error}
        </p>
      )}
    </>
  );
}

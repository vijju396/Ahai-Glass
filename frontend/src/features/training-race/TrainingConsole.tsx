/**
 * The training console: one button, thirteen models, one race.
 *
 * This is the seam between the app and the race. It resolves the field from the
 * API — never from a list in the frontend — picks a trainer, and hands both to
 * `BarRace`, which knows nothing about this application.
 *
 * It renders in one of two variants, decided by the page-level filter above it:
 *
 * - **`detail`** — a line is selected. The race replays that line's own board
 *   and the leaderboard beneath it is that line's ranking. This is the drill-in
 *   view: which model won *this* SKU, and by how much.
 * - **`summary`** — no line is selected (All locations / All SKUs). There is no
 *   per-line story to tell and the workspace-averaged board was removed as
 *   noise (docs/DECISIONS.md D-096), so this is just the train control: a
 *   button when idle, and the live race while a run is actually in flight.
 *   The combined numbers and the accuracy spread sit above it and carry the
 *   summary; the console here only starts a run and shows it happening.
 *
 * **Swapping the trainer is one line**, the `TRAINER` constant below.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { Play } from 'lucide-react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { fetchCurrentRun, fetchTrainingMonitor, monitorKeys, trainingKeys } from '@/api/training';
import { analyticsKeys, fetchAnalyticsFilters } from '@/api/analytics';
import { fetchLeaderboard, leaderboardKeys } from '@/api/leaderboard';
import { resolveModels } from '@/config/models';
import { ErrorState, LoadingBlock } from '@/components/ui/States';
import { BarRace } from './BarRace';
import { ScopeLeaderboard } from './ScopeLeaderboard';
import { ApiTrainer } from './ApiTrainer';
import { MockTrainer } from './MockTrainer';
import { SSETrainer } from './SSETrainer';
import { ScopeTrainer } from './ScopeTrainer';

/** Swap to `'mock'` to drive the race with no backend. */
const TRAINER: 'api' | 'mock' = 'api';

/**
 * @param scopeKey One branch x SKU line, chosen by the page-level filter.
 *   Present ⇒ `detail` variant; absent ⇒ `summary` variant.
 * @param untrained The filter resolved to a pair this run never trained.
 */
export function TrainingConsole({
  scopeKey = null,
  untrained = false,
}: {
  scopeKey?: string | null;
  untrained?: boolean;
} = {}) {
  const [error, setError] = useState<string | null>(null);
  const client = useQueryClient();
  const isDetail = !!scopeKey;

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

  const fieldKey = (monitor.data?.models ?? [])
    .map((m) => `${m.model_id}:${m.is_baseline ? 1 : 0}`)
    .join('|');

  const models = useMemo(
    () => resolveModels(monitor.data?.models ?? []).filter((m) => !m.isBaseline),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [fieldKey],
  );

  /* The selected line's own board, replayed as the race in detail mode. */
  const scopeQuery = useMemo(
    () => ({
      ...(runId ? { training_run_id: runId } : {}),
      scope_level: 'series',
      scope_key: scopeKey ?? '',
    }),
    [runId, scopeKey],
  );
  const scopeBoard = useQuery({
    queryKey: leaderboardKeys.board(scopeQuery),
    queryFn: () => fetchLeaderboard(scopeQuery),
    enabled: isDetail,
    retry: false,
  });

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
            () => client.invalidateQueries({ queryKey: trainingKeys.current }),
            (message) => setError(message),
          ),
    [body, client],
  );

  /** In detail mode the race replays the line's board. In summary mode it only
   *  ever shows a live run — there is no idle replay, so the console does not
   *  sit there restating a finished race nobody selected. */
  const attach = useMemo(() => {
    if (TRAINER === 'mock' || !runId) return null;
    if (isDetail && !live && scopeBoard.data) {
      return {
        trainer: new ScopeTrainer(scopeBoard.data.rows ?? [], true),
        live: false,
        key: `${runId}:scope:${scopeKey}`,
      };
    }
    if (live) return { trainer: new SSETrainer(runId), live: true, key: `${runId}:live` };
    return null;
  }, [runId, live, isDetail, scopeKey, scopeBoard.data]);

  /* Summary-mode train button. It kicks a run and lets the current-run poll
     flip `live`, at which point the live race mounts and the button gives way
     to it. The throwaway stream it opens is closed the moment that happens. */
  const startStop = useRef<null | (() => void)>(null);
  useEffect(() => {
    if (live) {
      startStop.current?.();
      startStop.current = null;
    }
  }, [live]);
  const handleTrain = () => {
    setError(null);
    startStop.current?.();
    startStop.current = trainer.start(models, () => {});
  };

  if (current.isLoading || (runId && monitor.isLoading)) {
    return <LoadingBlock label="Reading the model field…" />;
  }
  if (monitor.error) return <ErrorState error={monitor.error} />;

  if (!models.length) {
    return (
      <p className="text-[11px] leading-relaxed text-[var(--color-text-muted)]">
        No training run has been recorded yet, so the field is not known. Start one and the models
        appear here, racing.
      </p>
    );
  }

  // ---- summary variant: train control only ---------------------------------
  if (!isDetail) {
    return (
      <>
        {live ? (
          <BarRace models={models} trainer={trainer} attach={attach} onStart={() => setError(null)} />
        ) : (
          <div className="flex flex-wrap items-center gap-3">
            <button
              type="button"
              onClick={handleTrain}
              className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--color-primary)] px-3 py-1.5 text-[11px] font-semibold text-white shadow-[var(--shadow-sm)] transition hover:opacity-90"
            >
              <Play size={13} strokeWidth={2.5} />
              Train all models
            </button>
            <span className="text-[11px] text-[var(--color-text-muted)]">
              {untrained
                ? 'The line selected above was not trained by this run.'
                : 'Runs all 13 models across every line. Pick a location and SKU above to drill into one.'}
            </span>
          </div>
        )}
        {error && (
          <p className="mt-2 text-[10.5px] leading-relaxed" style={{ color: 'var(--color-danger)' }}>
            {error}
          </p>
        )}
      </>
    );
  }

  // ---- detail variant: this line's race + leaderboard -----------------------
  return (
    <>
      {!live && (
        <p className="mb-1.5 text-[10.5px] text-[var(--color-text-muted)]">
          Each bar is that model&apos;s measured accuracy on{' '}
          <span className="mono">{scopeKey!.replace('|', ' · ')}</span> alone — the same figures as
          the table below, replayed.
        </p>
      )}
      <BarRace
        models={models}
        trainer={trainer}
        attach={attach}
        onStart={() => setError(null)}
        animate={false}
      />

      <div className="mt-4 border-t border-[var(--color-border)] pt-3">
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <h4 className="text-[11px] font-semibold uppercase tracking-[0.06em] text-[var(--color-text)]">
            Model leaderboard
          </h4>
          <span className="text-[10px] text-[var(--color-text-muted)]">for this one line</span>
        </div>
        <ScopeLeaderboard trainingRunId={runId} scopeKey={scopeKey!} />
      </div>
      {error && (
        <p className="mt-2 text-[10.5px] leading-relaxed" style={{ color: 'var(--color-danger)' }}>
          {error}
        </p>
      )}
    </>
  );
}

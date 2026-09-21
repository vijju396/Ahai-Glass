/**
 * The training console, and the one filter that governs it.
 *
 * This component used to carry four more panels: run-level status tiles, the
 * accuracy-by-planning-window table, the fold design, and a per-model outcome
 * chart. All four were removed as engineering detail that does not belong in
 * front of a client (docs/DECISIONS.md D-096). **None of the information was
 * lost**, which is the condition that made the removal safe:
 *
 * - **Fold design** — the same origins, training windows and validation
 *   windows are in "Validation design" further down this page, read from the
 *   same run. The copy here was a duplicate.
 * - **Per-model outcomes** — every model still appears on the leaderboard
 *   inside the console with its status and, when it did not run, the exact
 *   requirement it missed. The run-level totals are on "Most recent run".
 * - **Accuracy by planning window** — now on the landing page as the combined
 *   figure across every SKU and location, which is where someone looks first.
 *   Filtered to one line, the leaderboard states that line's champion and its
 *   measured accuracy in a sentence.
 *
 * So what is left is the thing a demo is actually about: pick a line, watch
 * the models race on it, read which one won and by how much.
 */
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { BLUE, GREEN, Panel, SLATE } from '@/components/ui/Dashboard';
import { LoadingBlock } from '@/components/ui/States';
import { fetchCurrentRun, trainingKeys } from '@/api/training';
import { TrainingConsole } from '@/features/training-race/TrainingConsole';
import { CombinedAccuracy } from '@/features/training-race/CombinedAccuracy';
import {
  SeriesFilter,
  resolveSelection,
  useSeriesLines,
} from '@/features/training-race/SeriesFilter';

export function TrainingMonitor() {
  const current = useQuery({
    queryKey: trainingKeys.current,
    queryFn: fetchCurrentRun,
    retry: false,
    refetchInterval: 15_000,
  });

  const live = !!current.data && ['running', 'queued', 'pending'].includes(current.data.status);

  /* One line, chosen once. The race and the leaderboard beneath it both read
     this, so it sits above both rather than inside either. */
  const lines = useSeriesLines();
  const [picked, setPicked] = useState({ branch: '', sku: '' });
  const selection = resolveSelection(lines, picked.branch, picked.sku);

  if (current.isLoading) return <LoadingBlock label="Looking for a training run…" />;
  if (current.error) {
    return (
      <Panel title="Training console" accent={SLATE}>
        <p className="text-[11px] leading-relaxed text-[var(--color-text-muted)]">
          No training run has been recorded yet. Start one and the models appear here, racing.
        </p>
      </Panel>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <SeriesFilter
        lines={lines}
        branch={picked.branch}
        sku={picked.sku}
        onChange={setPicked}
      />

      {selection.scopeKey ? (
        /* One line: its models and its leaderboard. */
        <Panel
          title={live ? 'Models racing' : 'How the models did on this line'}
          accent={live ? GREEN : BLUE}
          note="Each bar is a model; length is its accuracy on this line. The leaderboard beneath lists the same figures."
        >
          <TrainingConsole scopeKey={selection.scopeKey} untrained={selection.untrained} />
        </Panel>
      ) : (
        /* All locations, all SKUs: the combined accuracy, then the train
           control. No averaged race or leaderboard — those answer a question
           nobody asks (docs/DECISIONS.md D-096). */
        <>
          <CombinedAccuracy />
          <Panel title="Train the models" accent={BLUE} note="Runs all 13 models across every branch and SKU. Drill into any one line with the filter above.">
            <TrainingConsole untrained={selection.untrained} />
          </Panel>
        </>
      )}
    </div>
  );
}

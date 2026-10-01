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
import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { BLUE, GREEN, Panel, SLATE } from '@/components/ui/Dashboard';
import { LoadingBlock } from '@/components/ui/States';
import { fetchCurrentRun, trainingKeys } from '@/api/training';
import { TrainingConsole } from '@/features/training-race/TrainingConsole';
import { CombinedAccuracy } from '@/features/training-race/CombinedAccuracy';
import { ModelAccuracyTable } from '@/features/training-race/ModelAccuracyTable';
import {
  SeriesFilter,
  resolveSelection,
  useSeriesLines,
} from '@/features/training-race/SeriesFilter';
import { firstPair } from '@/app/seriesPair';
import { LineSummaryTiles } from '@/features/line-summary/LineSummaryTiles';

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

  /* The page opens on a line rather than on the run-wide summary. "All
     locations / All SKUs" is gone from the filter, so there is no selection
     that means "no line" any more (D-133). */
  useEffect(() => {
    if (picked.branch || lines.length === 0) return;
    setPicked(firstPair(lines));
  }, [lines, picked.branch]);

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

      {/* The same four tiles Forecasting shows for the same line, as the same
          component rather than a copy — chosen model, its measured accuracy and
          MAPE, the next-month figure and how many horizons came back. A reader
          who picks a line here and then opens Forecasting sees the identical
          numbers, which is the point of showing them twice. */}
      {selection.scopeKey && <LineSummaryTiles scopeKey={selection.scopeKey} />}

      {selection.scopeKey && (
        /* One line: its models and its leaderboard. First on the page, because
           the line is what a planner acts on. */
        <Panel
          title={live ? 'Models racing' : 'How the models did on this line'}
          accent={live ? GREEN : BLUE}
          note="Each bar is a model; length is its accuracy over a six-month total on this line. The leaderboard beneath lists the same figures."
        >
          <TrainingConsole scopeKey={selection.scopeKey} untrained={selection.untrained} />
        </Panel>
      )}

      {/* Beneath the line, and no longer behind an "All locations" selection.
          Both figures here are **medians across the lines** — each line scored
          on its own and the middle one reported — never a model fitted to
          summed demand. That distinction is the whole reason the aggregate
          scopes came off the pickers: the national scope on this run reports
          169.87% MAPE, and the median line reports 10.45% over the same
          six-month total (D-133). */}
      <CombinedAccuracy />
      {/* Per model, not per line. The combined figure above says how accurate
          the champions are together; this says how each of the thirteen scored
          on the same window, which is what the champion was picked on. Without
          it the page could show a winner and never show the number that made
          it the winner. */}
      <ModelAccuracyTable />
      <Panel
        title="Train the models"
        accent={BLUE}
        note="Runs all 13 models across every branch and SKU. The filter above drills into any one line."
      >
        <TrainingConsole untrained={selection.untrained} />
      </Panel>
    </div>
  );
}

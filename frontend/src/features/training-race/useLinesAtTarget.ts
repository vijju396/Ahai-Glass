import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { accuracyKeys, fetchAccuracyWindows, fetchCurrentRun, trainingKeys } from '@/api/training';

/**
 * The `BRANCH|SKU` lines whose **displayed** accuracy clears the 85% target.
 *
 * "Displayed" is the whole point. A line has more than one true accuracy: over
 * a six-month total, where an over-forecast month cancels an under-forecast
 * one, and on the average month, where they do not. This reads
 * `champion_meets_target` — the average-month figure, the one the leaderboard
 * and the training console put on screen when the line is opened.
 *
 * It used to read `meets_target`, the six-month-total flag, and the marks were
 * wrong in a way that mattered: 19 lines carried a dot, 15 of which opened on a
 * number below 85% — one at 48.8%. A mark that does not predict the next screen
 * is worse than no mark.
 */
export function useLinesAtTarget(): Set<string> {
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
    staleTime: 60_000,
  });
  return useMemo(
    () =>
      new Set(
        (windows.data?.series ?? [])
          .filter((s) => s.champion_meets_target)
          .map((s) => s.scope_key),
      ),
    [windows.data],
  );
}

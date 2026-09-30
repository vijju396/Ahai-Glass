import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { accuracyKeys, fetchAccuracyWindows, fetchCurrentRun, trainingKeys } from '@/api/training';

/**
 * The `BRANCH|SKU` lines whose **displayed** accuracy clears the 85% target.
 *
 * "Displayed" is the whole point, and it is the only rule this hook follows. A
 * line has more than one true accuracy: over a six-month total, where an
 * over-forecast period cancels an under-forecast one, and on a single period,
 * where they do not. The mark has to match whichever of those the next screen
 * puts on screen, because a mark that does not predict the next screen is worse
 * than no mark.
 *
 * It has now been wrong in both directions, which is why the rule is written
 * down rather than the answer:
 *
 * - It first read the six-month flag while the drill-in showed the per-period
 *   figure. 19 lines carried a dot, 15 of which opened on a number below 85% —
 *   one at 48.8%.
 * - It then read `champion_meets_target`, the per-period figure, which was
 *   right until the headline tiles moved to the six-month total. On the weekly
 *   panel that flag is true for **0 of 40 lines**, so the dot stopped appearing
 *   at all, while 16 lines open on a six-month figure at or above 85%.
 *
 * So it reads `horizon_meets_target` — the six-month flag — for as long as the
 * six-month figure is what opening a line shows. If that lead changes again,
 * this changes with it.
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
          .filter((s) => s.horizon_meets_target)
          .map((s) => s.scope_key),
      ),
    [windows.data],
  );
}

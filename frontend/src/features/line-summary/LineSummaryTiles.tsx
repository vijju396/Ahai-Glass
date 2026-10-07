/**
 * The four tiles that describe one branch × SKU line, shared by both screens.
 *
 * Training and Forecasting answer different questions — which model won, and
 * what it predicts — but they answer them about the same line, from the same
 * run, and a reader moves between the two expecting the numbers to agree.
 * They used to live only on Forecasting; Training now shows them too, on
 * request, and **as the same component rather than a second copy**. A copy
 * would have drifted the first time one of the four was reworded, which has
 * already happened twice to the accuracy tile alone (D-134).
 *
 * It runs its own queries rather than taking the data as props. The query keys
 * are the ones Forecasting already uses, so on that page every one is a cache
 * hit and no extra request is made; on Training they are the first fetch. That
 * keeps the component usable anywhere a `scope_key` is in hand without a
 * caller having to assemble three payloads first.
 */
import { useQuery } from '@tanstack/react-query';
import { fetchSeriesForecast, forecastKeys } from '@/api/forecasts';
import { accuracyKeys, fetchAccuracyWindows, fetchCurrentRun, trainingKeys } from '@/api/training';
import { monthLabel } from '@/components/charts/Chart';
import { StatTile } from '@/components/ui/Dashboard';
import { formatInt } from '@/components/ui/format';

export function LineSummaryTiles({ scopeKey }: { scopeKey: string }) {
  const series = useQuery({
    queryKey: forecastKeys.series('series', scopeKey),
    queryFn: () => fetchSeriesForecast('series', scopeKey),
    enabled: Boolean(scopeKey),
    retry: false,
  });

  // This line's accuracy over the six-month total — the same window the
  // headline panel reports — so drilling into a line does not swap the
  // measurement out from under the reader. Read from the accuracy-windows
  // endpoint rather than recomputed: the frontend carries no forecasting
  // arithmetic.
  const currentRun = useQuery({
    queryKey: trainingKeys.current,
    queryFn: fetchCurrentRun,
    retry: false,
    staleTime: 60_000,
  });
  const accuracyRunId = currentRun.data?.id;
  const accuracy = useQuery({
    queryKey: accuracyKeys.windows(accuracyRunId ?? '', null),
    queryFn: () => fetchAccuracyWindows(accuracyRunId as string, null),
    enabled: !!accuracyRunId,
    retry: false,
    staleTime: 60_000,
  });

  const data = series.data;
  if (!data) return null;

  const lineAccuracy = (accuracy.data?.series ?? []).find((row) => row.scope_key === scopeKey);
  const metrics = data.validation_metrics;
  const forecasts = data.forecasts ?? [];
  // The roll-up is only worth reading when a period is not already a month.
  const rollup = data.panel_grain === 'weekly' ? (data.monthly_rollup ?? []) : [];
  const firstRollup = rollup[0];
  const nextMonth = firstRollup
    ? {
        value: firstRollup.point_forecast,
        label: `${monthLabel(firstRollup.month)}${
          firstRollup.complete ? '' : ' (part month)'
        } · ${firstRollup.periods} weeks`,
      }
    : forecasts[0]
      ? { value: forecasts[0].point_forecast, label: monthLabel(forecasts[0].period) }
      : null;

  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      {/* A planner buys by the month, so this tile stays a month even when the
          panel is weekly: at weekly grain it shows the first month of the
          roll-up rather than the first week, and says how many weeks that month
          was built from. Showing a single week under a "next month" label would
          understate demand roughly fourfold. */}
      <StatTile
        label="Next-month forecast"
        value={formatInt(nextMonth?.value)}
        sublabel={nextMonth ? `${nextMonth.label} · reconciled units` : 'unavailable'}
        tint="blue"
        accent
      />
      <StatTile
        label="Model chosen for this series"
        value={metrics?.display_name ?? '—'}
        sublabel="selected on this series alone"
        tint="navy"
      />
      {/* MAPE, not WAPE. MAPE is the metric the champion for this series was
          selected on (D-043), so the error quoted beside the model name is the
          error that chose it.

          Accuracy and MAPE are **two tiles, and each reads its own field**
          (D-160). Neither is derived from the other: accuracy is floored at
          zero, so on a line whose error exceeds 100% `100 - accuracy` prints
          exactly 100.0% and hides the real figure. Four lines of this run read
          0% accuracy against measured MAPEs of 102.8%, 140.8%, 357.5% and
          100.0%; the other 257 agree, which is exactly why the shortcut
          survives casual testing (D-134). Both tiles show "—" when their own
          field is absent rather than borrowing the other's. */}
      <StatTile
        label="Accuracy, six-month total"
        value={
          lineAccuracy?.horizon_accuracy_pct == null
            ? '—'
            : `${lineAccuracy.horizon_accuracy_pct.toFixed(1)}%`
        }
        tint="teal"
      />
      <StatTile
        label="MAPE, six-month total"
        value={
          lineAccuracy?.horizon_mape_pct == null
            ? '—'
            : `${lineAccuracy.horizon_mape_pct.toFixed(1)}%`
        }
        tint="amber"
      />
    </div>
  );
}

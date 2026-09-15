/**
 * Live training monitor — what every model is doing, while it does it.
 *
 * The rest of the Training page explains the *design*: what the validation
 * scheme is, which metrics are computed, how the champion is chosen. That is
 * static text derived from code. This component answers the other question,
 * the one you only have while a run is in flight: **is it working, and which
 * models are refusing?**
 *
 * Three things it deliberately does:
 *
 * **The fold design is drawn from what the run actually did**, not restated
 * from configuration. The train and validation windows come from a stored
 * fold, so if a run used a different split than the settings imply, this shows
 * the split that was used. The bars are positioned on a real month axis, which
 * is the only way to see the property that matters: every validation window
 * begins strictly after its own training window ends.
 *
 * **Status is never collapsed into a score.** `Ineligible` is not `Failed` and
 * neither is a bad WAPE. A model with 52 completed runs and a poor median
 * error is not doing worse than one with 32 completed runs and a good one —
 * they are different facts and both are shown.
 *
 * **The four baselines are separated, always.** They run so the champion can
 * be checked against them, and one of them beating the champion is a finding
 * worth seeing — but they are not candidates, so they sit below a divider and
 * are labelled. Nothing here can present naive as a fourteenth model.
 *
 * Live updates come from the run's SSE stream when one is in flight; the
 * per-model table is polled alongside it, because the stream carries run-level
 * counters only.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import {
  AMBER,
  BLUE,
  GREEN,
  NAVY,
  Panel,
  RED,
  SLATE,
  TEAL,
  TICK,
  TOOLTIP,
  VIOLET,
  num,
} from '@/components/ui/Dashboard';
import { ErrorState, LoadingBlock } from '@/components/ui/States';
import {
  fetchCurrentRun,
  fetchTrainingMonitor,
  monitorKeys,
  trainingKeys,
  type MonitorFold,
  type MonitorModel,
  type TrainingMonitor as Monitor,
} from '@/api/training';
import { TrainingConsole } from '@/features/training-race/TrainingConsole';

/** Statuses, in the order the project defines them. Each is a different fact. */
const STATUS_KEYS = [
  { key: 'completed', label: 'Completed', color: GREEN },
  { key: 'ineligible', label: 'Ineligible', color: AMBER },
  { key: 'failed', label: 'Failed', color: RED },
  { key: 'timed_out', label: 'Timed out', color: VIOLET },
  { key: 'not_evaluated', label: 'Not evaluated (budget)', color: SLATE },
] as const;

export function TrainingMonitor() {
  const current = useQuery({
    queryKey: trainingKeys.current,
    queryFn: fetchCurrentRun,
    retry: false,
    refetchInterval: 15_000,
  });

  const runId = current.data?.id;
  const live = !!current.data && ['running', 'queued', 'pending'].includes(current.data.status);
  const stream = useLiveProgress(live ? runId : undefined);

  const monitor = useQuery({
    queryKey: monitorKeys.run(runId ?? ''),
    queryFn: () => fetchTrainingMonitor(runId as string),
    enabled: !!runId,
    // While a run is in flight the per-model table is the thing changing, and
    // the SSE stream does not carry it. Idle runs never change, so polling
    // stops entirely rather than burning a request a second forever.
    refetchInterval: live ? 2_000 : false,
    // Kept polling while the tab is hidden, which is not the usual default.
    //
    // An EventSource is unaffected by visibility but a React Query interval is
    // paused, so with the default the progress bar kept advancing from the
    // stream while the model table below it sat frozen — two numbers on one
    // screen disagreeing about the same run. That is worse than a little extra
    // traffic, and it is bounded: only while a run is actually in flight
    // (docs/DECISIONS.md D-073).
    refetchIntervalInBackground: live,
  });

  if (current.isLoading) return <LoadingBlock label="Looking for a training run…" />;
  if (current.error) {
    return (
      <Panel title="Training Monitor" accent={SLATE}>
        <p className="text-[11px] leading-relaxed text-[var(--color-text-muted)]">
          No training run has been recorded yet. Start one and this panel will follow it live:
          model by model, with the validation design it used.
        </p>
      </Panel>
    );
  }
  if (monitor.isLoading) return <LoadingBlock label="Reading run progress…" />;
  if (monitor.error) return <ErrorState error={monitor.error} />;
  const data = monitor.data;
  if (!data) return null;

  return (
    <div className="flex flex-col gap-3">
      <RunHeader data={data} live={live} progress={stream.progress ?? data.progress_pct} />

      {/* The console owns the button and the race. It resolves its field from
          the API and drives it from an event stream, so it knows nothing about
          this page and the race can be developed against a mock with no
          backend at all (docs/DECISIONS.md D-078). */}
      <Panel
        title={live ? 'Models racing' : 'Training console'}
        accent={live ? GREEN : BLUE}
        note="One button trains every model at once. Each bar is a model; length tracks its live accuracy, and the order they settle into is the result."
      >
        <TrainingConsole />
      </Panel>

      <FoldDesign folds={data.folds} />
      <StatusChart data={data} />
    </div>
  );
}

/**
 * Subscribes to the run's SSE stream.
 *
 * The stream only emits when progress actually changed, so a quiet run
 * produces no frames rather than one a second — which means "no event yet" is
 * normal and must not be rendered as a stall.
 */
function useLiveProgress(runId: string | undefined) {
  const [progress, setProgress] = useState<number | null>(null);
  const [stage, setStage] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);
  const ref = useRef<EventSource | null>(null);

  useEffect(() => {
    if (!runId) {
      setProgress(null);
      setConnected(false);
      return;
    }
    const source = new EventSource(`/api/training/${runId}/events`);
    ref.current = source;
    source.addEventListener('progress', (event) => {
      try {
        const payload = JSON.parse((event as MessageEvent).data);
        setProgress(payload.progress_pct ?? null);
        setStage(payload.stage_detail ?? null);
        setConnected(true);
      } catch {
        // A malformed frame is not worth tearing the stream down for; the
        // polled snapshot is the source of truth for everything but the bar.
      }
    });
    source.onerror = () => setConnected(false);
    return () => {
      source.close();
      ref.current = null;
    };
  }, [runId]);

  return { progress, stage, connected };
}

function RunHeader({ data, live, progress }: { data: Monitor; live: boolean; progress: number }) {
  /** Run-level counters are written when the run finishes, so mid-run they are
   *  all zero while the per-model rows already carry hundreds of resolved
   *  fits. Left alone, the five tiles read 0 directly above a lattice showing
   *  real work — the same "two numbers on one screen disagreeing about one
   *  run" defect as the frozen model table (docs/DECISIONS.md D-073). The
   *  per-model sums are the same data, so they stand in until the run-level
   *  totals exist. */
  const c = useMemo(() => {
    const stored = data.counters;
    const anyStored =
      stored.completed + stored.ineligible + stored.failed + stored.timed_out +
      stored.not_evaluated > 0;
    if (anyStored) return stored;
    const sum = (key: keyof MonitorModel) =>
      data.models.reduce((total, m) => total + Number(m[key] ?? 0), 0);
    return {
      total: data.models.reduce((t, m) => t + m.total, 0) || stored.total,
      completed: sum('completed'),
      ineligible: sum('ineligible'),
      failed: sum('failed'),
      timed_out: sum('timed_out'),
      not_evaluated: sum('not_evaluated'),
    };
  }, [data]);
  const done = c.completed + c.ineligible + c.failed + c.timed_out + c.not_evaluated;
  return (
    <Panel
      title="Training Monitor"
      accent={live ? GREEN : NAVY}
      note={
        live
          ? 'A run is in flight. Progress streams from the server; the model table below refreshes alongside it.'
          : 'No run is in flight, so this is the most recent run in its final state — not a live view.'
      }
    >
      <div className="flex flex-wrap items-center gap-2">
        <span
          className="rounded-full px-2 py-0.5 text-[10px] font-semibold"
          style={{
            background: live ? `${GREEN}22` : `${SLATE}22`,
            color: live ? GREEN : 'var(--color-text-muted)',
          }}
        >
          {live ? '● LIVE' : 'Not running'}
        </span>
        <span className="text-[11px] text-[var(--color-text-muted)]">
          Run <code className="text-[10.5px]">{data.run_id.slice(0, 8)}</code> · {data.status}
          {data.duration_seconds != null && ` · ${data.duration_seconds.toFixed(0)}s`}
        </span>
        {data.stage_detail && (
          <span className="text-[11px] text-[var(--color-text)]">{data.stage_detail}</span>
        )}
      </div>

      <div className="mt-2 h-2 w-full overflow-hidden rounded-full bg-[var(--color-surface-2)]">
        <div
          className="h-full rounded-full transition-[width] duration-500"
          style={{ width: `${Math.min(100, Math.max(0, progress))}%`, background: live ? GREEN : BLUE }}
        />
      </div>
      <div className="mt-1 flex flex-wrap items-baseline justify-between gap-2">
        <span className="text-[10px] text-[var(--color-text-muted)]">
          {/* No denominator while a run is in flight. The planned total is not
              known until the run writes it at the end, and the only number
              available mid-run is the count of fits already recorded — which
              as a denominator renders "204 of 204", a run that looks finished
              at a quarter done. Better to state what is true. */}
          {live
            ? `${num(done)} model runs resolved`
            : `${num(done)} of ${num(c.total)} model runs`}
          {data.series_requested > 0 &&
            ` · ${data.series_evaluated} of ${data.series_requested} series`}
        </span>
        <span className="text-[11px] font-semibold tabular-nums">{progress.toFixed(1)}%</span>
      </div>

      <div className="mt-2 grid grid-cols-2 gap-1.5 sm:grid-cols-5">
        {STATUS_KEYS.map((s) => (
          <div
            key={s.key}
            className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-2)] px-2 py-1.5"
          >
            <div className="text-[16px] font-semibold tabular-nums" style={{ color: s.color }}>
              {num(c[s.key])}
            </div>
            <div className="text-[9px] leading-tight text-[var(--color-text-muted)]">{s.label}</div>
          </div>
        ))}
      </div>
    </Panel>
  );
}

/** The train/validate windows, on a real month axis. */
function FoldDesign({ folds }: { folds: MonitorFold[] }) {
  const bounds = useMemo(() => {
    const months = folds
      .flatMap((f) => [f.train_end, f.validate_from, f.validate_to])
      .filter((m): m is string => !!m)
      .sort();
    return { first: months[0], last: months[months.length - 1] };
  }, [folds]);

  if (!folds.length) {
    return (
      <Panel title="Training set and validation set" accent={TEAL}>
        <p className="text-[11px] text-[var(--color-text-muted)]">
          No scored fold is stored for this run yet, so its split cannot be shown. It appears as
          soon as the first model completes.
        </p>
      </Panel>
    );
  }

  const toIndex = (p: string | null | undefined) => {
    if (!p) return 0;
    const [y, m] = p.split('-').map(Number);
    if (!Number.isFinite(y) || !Number.isFinite(m)) return 0;
    return (y as number) * 12 + ((m as number) - 1);
  };
  const lo = toIndex(bounds.first) - 18;
  const hi = toIndex(bounds.last);
  const span = Math.max(hi - lo, 1);
  const pct = (p: string | null | undefined) => ((toIndex(p) - lo) / span) * 100;

  return (
    <Panel
      title="Training set and validation set"
      accent={TEAL}
      note="Read from a fold this run actually scored, not restated from configuration. Each validation window begins strictly after its own training window ends — that is what makes the measurement leakage-safe."
    >
      <div className="flex flex-col gap-2">
        {folds.map((f) => (
          <div key={String(f.index)}>
            <div className="mb-0.5 flex flex-wrap items-baseline gap-2 text-[10px]">
              <span className="font-semibold text-[var(--color-text)]">
                Origin {Number(f.index) + 1} · {f.name}
              </span>
              <span className="text-[var(--color-text-muted)]">
                train through {f.train_end} ({f.train_rows} months) → validate {f.validate_from} to{' '}
                {f.validate_to} ({f.validate_months} months, horizons{' '}
                {f.horizons[0]}–{f.horizons[f.horizons.length - 1]})
              </span>
            </div>
            <div className="relative h-5 w-full rounded bg-[var(--color-surface-2)]">
              <div
                className="absolute top-0 h-full rounded-l"
                style={{ left: 0, width: `${pct(f.train_end)}%`, background: `${BLUE}cc` }}
                title={`Training: through ${f.train_end}`}
              />
              <div
                className="absolute top-0 h-full rounded-r"
                style={{
                  left: `${pct(f.validate_from)}%`,
                  width: `${Math.max(pct(f.validate_to) - pct(f.validate_from), 2)}%`,
                  background: `${AMBER}dd`,
                }}
                title={`Validation: ${f.validate_from} to ${f.validate_to}`}
              />
            </div>
          </div>
        ))}
      </div>
      <div className="mt-1.5 flex flex-wrap items-center gap-3 text-[10px] text-[var(--color-text-muted)]">
        <Swatch color={BLUE} label="Training set — the model may see this" />
        <Swatch color={AMBER} label="Validation set — scored, never fitted on" />
      </div>
      <p className="mt-1 text-[10px] leading-relaxed text-[var(--color-text-muted)]">
        The training window <strong>grows</strong> between origins ({folds[0]?.train_rows} months,
        then {folds[folds.length - 1]?.train_rows}) while the validation window moves forward.
        That is an expanding-window rolling origin — never a random split, which would let a
        later month inform an earlier prediction.
      </p>
    </Panel>
  );
}

function Swatch({ color, label }: { color: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1">
      <span className="inline-block h-2 w-4 rounded-sm" style={{ background: color }} />
      {label}
    </span>
  );
}

function StatusChart({ data }: { data: Monitor }) {
  const rows = data.models.map((m) => ({
    name: shortName(m),
    baseline: m.is_baseline,
    ...Object.fromEntries(STATUS_KEYS.map((s) => [s.key, m[s.key]])),
  }));
  return (
    <Panel
      title="How every model is doing"
      accent={NAVY}
      note="Stacked by outcome. Ineligible is a validated data requirement that was not met — it is not a failure, and a model that did not run never disappears from this chart."
    >
      <ResponsiveContainer width="100%" height={Math.max(240, rows.length * 19)}>
        <BarChart data={rows} layout="vertical" margin={{ top: 4, right: 12, left: 4, bottom: 0 }}>
          <CartesianGrid horizontal={false} strokeDasharray="3 3" stroke="var(--color-border)" />
          <XAxis type="number" tick={TICK} />
          <YAxis
            type="category"
            dataKey="name"
            tick={{ ...TICK, fontSize: 8.5 }}
            width={124}
            tickLine={false}
            interval={0}
          />
          <Tooltip contentStyle={TOOLTIP} />
          {STATUS_KEYS.map((s) => (
            <Bar key={s.key} dataKey={s.key} stackId="s" fill={s.color} isAnimationActive={false} />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </Panel>
  );
}

/** Display names are long; the table keeps them in full. */
function shortName(m: MonitorModel): string {
  const name = m.display_name.replace(' with exogenous variables', ' +exog');
  return name.length > 26 ? `${name.slice(0, 25)}…` : name;
}

/**
 * The bar chart race. Bars grow, rows overtake, the final order is the result.
 *
 * Built on the DOM rather than a charting library, because the two things that
 * decide whether this looks good — a reorder that glides and a width that
 * never steps — are both easier to control directly than to coax out of a
 * chart's animation model.
 *
 * **Every frame is written outside React.** One `requestAnimationFrame` loop
 * reads the store, eases each `displayScore` toward its `targetScore`, and
 * writes `style.width` and `style.transform` straight to cached DOM nodes.
 * React re-renders only when the field or the phase changes. Sixty renders a
 * second of thirteen rows would drop frames on any machine.
 *
 * Four details that carry the effect, each learned the hard way:
 *
 * **`transform` is written only when a rank actually changes.** Rewriting it
 * every frame restarts the CSS transition on every frame, so rows judder in
 * place instead of gliding to their new position. The previous rank is cached
 * and compared.
 *
 * **Scores are eased, not assigned.** Events land every few hundred
 * milliseconds; the race draws at 60fps. Without `display += (target -
 * display) * smoothing` the bars jump once per event and the motion dies.
 *
 * **The axis rescales to `max * headroom` every frame.** On a fixed 0–100 axis
 * the last third of a run looks frozen, because everything has converged into
 * a narrow band near the top. Rescaling keeps the leader nearly filling the
 * track and keeps the field moving when the numbers barely are.
 *
 * **Track width is measured once per resize, into a ref.** Reading layout
 * inside the frame loop forces a reflow sixty times a second.
 */
import { useEffect, useRef, useState } from 'react';
import { Play, RotateCcw, Trophy } from 'lucide-react';
import {
  FAMILIES,
  METRIC,
  familyColor,
  race,
  rowHeightFor,
  type ModelDef,
} from '@/config/models';
import { planFrame, stepDisplay } from './frame';
import { useRaceStore } from './store';
import type { Trainer } from './types';

interface Refs {
  row: HTMLDivElement | null;
  bar: HTMLDivElement | null;
  value: HTMLSpanElement | null;
  rank: HTMLSpanElement | null;
}

export function BarRace({
  models,
  trainer,
  attach,
  onStart,
  startLabel = 'Train all models',
  animate = true,
}: {
  models: ModelDef[];
  /** Starts a new run when the button is pressed. */
  trainer: Trainer;
  /** A run already in existence — live or finished — to show without being
   *  asked. Re-attaches whenever `key` changes. */
  attach?: { trainer: Trainer; live: boolean; key: string } | null;
  /** Called when the button is pressed, before the trainer starts. */
  onStart?: () => void;
  startLabel?: string;
  /** When false, bars appear at their final value with no growing or
   *  reordering. Used for the per-line replay, which is a result to read, not
   *  a race to watch. */
  animate?: boolean;
}) {
  // Deliberately NOT subscribed to `racers` or `epoch`. Both change on every
  // event, and a subscription would re-render the whole field dozens of times
  // a second — which also silently undid the loop's work, because React
  // re-applies the JSX `style` on each render and reset every bar to its
  // minimum width. Rows render from the stable `models` prop; the loop reads
  // live values through `getState()` and writes them to the DOM.
  const phase = useRaceStore((s) => s.phase);
  const leaderId = useRaceStore((s) => s.leaderId);

  const load = useRaceStore((s) => s.load);
  const apply = useRaceStore((s) => s.apply);
  const setPhase = useRaceStore((s) => s.setPhase);
  const resetStore = useRaceStore((s) => s.reset);

  const reduced = usePrefersReducedMotion() || !animate;
  const rowH = rowHeightFor(models.length);

  const refs = useRef(new Map<string, Refs>());
  const lastRank = useRef(new Map<string, number>());
  const trackWidth = useRef(0);
  const stopper = useRef<(() => void) | null>(null);
  const finishedAt = useRef<number | null>(null);
  const epochRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    load(models);
  }, [models, load]);

  /** Track width, measured from the stage this component owns.
   *
   *  Previously a callback ref was drilled into the first row. That is one more
   *  thing to go wrong for no benefit — and it did: under StrictMode the ref
   *  ended up pointing at a detached node measuring zero, the loop's
   *  `!trackWidth` guard tripped on every frame, and nothing drew at all while
   *  the store filled with perfectly good scores. The stage is right here, the
   *  track is a marked descendant of it, and one observer covers every resize. */
  const stageRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const stage = stageRef.current;
    if (!stage) return;
    const measure = () => {
      const track = stage.querySelector('[data-track]');
      if (track) trackWidth.current = track.getBoundingClientRect().width;
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(stage);
    return () => ro.disconnect();
  }, [models.length]);

  /** The frame loop. Runs for the life of the component. */
  useEffect(() => {
    let raf = 0;

    const frame = () => {
      raf = requestAnimationFrame(frame);
      const state = useRaceStore.getState();
      const field = state.racers;
      if (!field.length || !trackWidth.current) return;

      // Ease toward target. Mutated in place: nothing subscribes to it.
      for (const r of field) {
        const target = r.targetScore ?? 0;
        r.displayScore =
          reduced || state.phase === 'done' ? target : stepDisplay(r.displayScore, target);
      }

      for (const plan of planFrame(field, trackWidth.current)) {
        const node = refs.current.get(plan.id);
        if (!node) continue;

        // Only on an actual change; otherwise the transition restarts every
        // frame and the row judders in place instead of gliding.
        if (lastRank.current.get(plan.id) !== plan.rank) {
          lastRank.current.set(plan.id, plan.rank);
          if (node.row) node.row.style.transform = `translateY(${plan.rank * rowH}px)`;
          if (node.rank) node.rank.textContent = String(plan.rank + 1);
        }
        if (node.bar) node.bar.style.width = `${plan.width}px`;
        if (node.value) node.value.textContent = plan.label;
        if (plan.isLeader) state.setLeader(plan.id);
      }

      if (epochRef.current) epochRef.current.textContent = String(state.epoch);

    };

    raf = requestAnimationFrame(frame);
    return () => cancelAnimationFrame(raf);
  }, [rowH, reduced]);

  /** Settle → crown, once the last event has landed. */
  /** Settle → crown. Polled rather than subscribed, so watching for the end of
   *  the run does not re-render the field on every event along the way. */
  useEffect(() => {
    if (phase !== 'running') return;
    const id = window.setInterval(() => {
      const field = useRaceStore.getState().racers;
      if (!field.length) return;
      if (!field.every((r) => r.status === 'finished' || r.status === 'failed')) return;
      window.clearInterval(id);
      finishedAt.current = Date.now();
      setPhase('settling');
      window.setTimeout(() => setPhase('done'), race.settleHoldMs + 400);
    }, 400);
    return () => window.clearInterval(id);
  }, [phase, setPhase]);

  /** `requestAnimationFrame` does not fire while the document is hidden, so a
   *  tab switched away from during a run comes back with every `displayScore`
   *  frozen at whatever it held minutes ago. Easing from there would crawl.
   *  Snapping to the live values on return is both faster and more truthful. */
  useEffect(() => {
    const onVisible = () => {
      if (document.hidden) return;
      for (const r of useRaceStore.getState().racers) r.displayScore = r.targetScore ?? 0;
    };
    document.addEventListener('visibilitychange', onVisible);
    return () => document.removeEventListener('visibilitychange', onVisible);
  }, []);

  useEffect(() => () => stopper.current?.(), []);

  const begin = () => {
    stopper.current?.();
    resetStore();
    lastRank.current.clear();
    onStart?.();
    setPhase('running');
    stopper.current = trainer.start(models, apply);
  };

  /** Show the run that exists, without waiting to be asked.
   *
   *  The race used to populate only when the button was pressed, which meant a
   *  finished run showed an empty stage, and navigating away and back wiped
   *  what was on screen. Both read as "the feature is broken" and neither was
   *  about the race itself — it simply had no data until someone started a new
   *  run. The stream replays the whole field on connect, so attaching to the
   *  current run covers all three cases: live races, finished runs show their
   *  final standings, and a remount re-hydrates.
   *
   *  A finished run goes straight to `done`, so the bars appear at their final
   *  lengths instead of animating up from zero for a race that ended hours
   *  ago. */
  useEffect(() => {
    if (!attach || !models.length) return;
    stopper.current?.();
    lastRank.current.clear();
    resetStore();
    setPhase(attach.live ? 'running' : 'done');
    stopper.current = attach.trainer.start(models, apply);
    return () => {
      stopper.current?.();
      stopper.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [attach?.key, models]);

  const reset = () => {
    stopper.current?.();
    stopper.current = null;
    lastRank.current.clear();
    resetStore();
  };

  // The only per-model fact React needs. Joined to a string so the subscription
  // fires when the set of failures changes and not on every score update.
  const failedKey = useRaceStore((s) =>
    s.racers.filter((r) => r.status === 'failed').map((r) => r.id).join(','),
  );
  const failedIds = failedKey ? failedKey.split(',') : [];

  const running = phase === 'running' || phase === 'settling';
  const leaderName = models.find((r) => r.id === leaderId)?.name ?? null;

  return (
    <div>
      <div className="mb-3 flex items-end justify-between gap-4">
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={begin}
            disabled={running}
            className="inline-flex items-center gap-1.5 rounded-lg px-3.5 py-1.5 text-[12px] font-semibold text-white transition-opacity disabled:opacity-60"
            style={{ background: 'var(--color-primary)' }}
          >
            <Play size={13} strokeWidth={2.5} />
            {running ? 'Training' : startLabel}
          </button>
          <button
            type="button"
            onClick={reset}
            disabled={phase === 'idle'}
            className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--color-border)] px-2.5 py-1.5 text-[12px] text-[var(--color-text-muted)] transition-opacity disabled:opacity-40"
          >
            <RotateCcw size={12} strokeWidth={2.5} />
            Reset
          </button>
        </div>

        <div className="text-right leading-none">
          <div className="text-[9px] uppercase tracking-[0.08em] text-[var(--color-text-muted)]">
            Epoch
          </div>
          <div
            ref={epochRef}
            className="text-[26px] font-semibold tabular-nums text-[var(--color-text)]"
          >
            0
          </div>
        </div>
      </div>

      {/* The one live region: the leader, announced only when it changes. */}
      <p className="sr-only" aria-live="polite">
        {leaderName ? `${leaderName} leads on ${METRIC.label}` : ''}
      </p>

      <div ref={stageRef} className="relative" style={{ height: models.length * rowH }}>
        {models.map((r) => (
          <Row
            key={r.id}
            id={r.id}
            name={r.name}
            family={r.family}
            rowH={rowH}
            reduced={reduced}
            crowned={phase === 'done' && r.id === leaderId}
            failed={failedIds.includes(r.id)}
            register={(node) => {
              if (node) refs.current.set(r.id, node);
              else refs.current.delete(r.id);
            }}
          />
        ))}
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1">
        {FAMILIES.map((f) => (
          <span
            key={f.id}
            className="inline-flex items-center gap-1.5 text-[10px] text-[var(--color-text-muted)]"
          >
            <span className="h-2 w-2 rounded-[2px]" style={{ background: f.color }} />
            {f.label}
          </span>
        ))}
        <span className="ml-auto text-[10px] text-[var(--color-text-muted)]">
          {METRIC.label} · longer is better
        </span>
      </div>
    </div>
  );
}

function Row({
  id,
  name,
  family,
  rowH,
  reduced,
  crowned,
  failed,
  register,
}: {
  id: string;
  name: string;
  family: string;
  rowH: number;
  reduced: boolean;
  crowned: boolean;
  failed: boolean;
  register: (node: Refs | null) => void;
}) {
  const row = useRef<HTMLDivElement | null>(null);
  const bar = useRef<HTMLDivElement | null>(null);
  const value = useRef<HTMLSpanElement | null>(null);
  const rank = useRef<HTMLSpanElement | null>(null);

  useEffect(() => {
    register({ row: row.current, bar: bar.current, value: value.current, rank: rank.current });
    return () => register(null);
  }, [register]);

  return (
    <div
      ref={row}
      data-model-id={id}
      className="absolute inset-x-0 top-0 grid items-center gap-2 rounded px-1"
      style={{
        height: rowH,
        gridTemplateColumns: '22px 140px minmax(0,1fr)',
        transition: reduced ? 'none' : `transform ${race.reorderMs}ms ${race.reorderEase}`,
        background: crowned ? 'color-mix(in srgb, var(--color-primary) 9%, transparent)' : undefined,
        opacity: failed ? 0.45 : 1,
      }}
    >
      <span
        ref={rank}
        className="text-right text-[10px] font-semibold tabular-nums text-[var(--color-text-muted)]"
      >
        –
      </span>

      <span
        className="truncate text-right text-[11px] text-[var(--color-text)]"
        title={name}
        style={{ textDecoration: failed ? 'line-through' : undefined }}
      >
        {crowned && (
          <Trophy size={10} className="mr-1 inline-block align-[-1px]" strokeWidth={2.5} />
        )}
        {name}
      </span>

      <div data-track className="relative flex h-full items-center">
        <div
          ref={bar}
          className="h-[15px]"
          // No `width` here on purpose: the frame loop owns it. Declaring it
          // in JSX meant every React render snapped the bar back to 2px.
          style={{
            background: failed ? 'var(--color-text-muted)' : familyColor(family),
            borderRadius: '0 3px 3px 0',
          }}
        />
        <span
          ref={value}
          className="ml-1.5 text-[10.5px] font-semibold tabular-nums text-[var(--color-text)]"
          style={{ transform: crowned ? 'scale(1.06)' : undefined, transition: 'transform 200ms' }}
        >
          —
        </span>
      </div>
    </div>
  );
}

function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return;
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)');
    setReduced(mq.matches);
    const onChange = (e: MediaQueryListEvent) => setReduced(e.matches);
    mq.addEventListener('change', onChange);
    return () => mq.removeEventListener('change', onChange);
  }, []);
  return reduced;
}

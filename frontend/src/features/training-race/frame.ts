/**
 * What one frame of the race should look like — as a pure function.
 *
 * The loop that calls this can only run when the document is visible, because
 * `requestAnimationFrame` does not fire in a hidden tab. That makes the drawing
 * itself awkward to verify anywhere but a real screen, so the arithmetic that
 * decides rank, width and label lives here instead: no DOM, no timers, fully
 * testable. `BarRace` is then a thin thing that takes this output and assigns
 * it to nodes.
 */
import { scaleLinear } from 'd3-scale';
import { METRIC, race } from '@/config/models';
import type { Racer } from './types';

export interface FramePlan {
  id: string;
  rank: number;
  width: number;
  label: string;
  isLeader: boolean;
}

/** Ease one step toward the target. Exported so the test can drive it. */
export function stepDisplay(display: number, target: number, smoothing = race.smoothing): number {
  return display + (target - display) * smoothing;
}

/** The raw metric value behind a race value — the inverse of `toRaceValue`.
 *
 *  A 'lower is better' race draws bars from the converted value so longer
 *  still means better, while the number at the tip has to show the real
 *  measurement. Without this inverse a loss race would print the converted
 *  number, which means nothing to anyone. */
export function rawOf(raceValue: number): number {
  return METRIC.direction === 'higher'
    ? raceValue
    : Math.max(0, (1 - raceValue) * METRIC.worstCase);
}

export function labelFor(racer: Racer): string {
  if (racer.targetScore == null) return '—';
  return `${METRIC.format(rawOf(racer.displayScore))}${METRIC.suffix}`;
}

/**
 * Rank, bar width and label for every racer.
 *
 * Ordering is always descending on the race value, so it is correct for both
 * metric directions without a branch here. A failed model keeps its last
 * length and sinks below everything still running — it did not stop existing.
 *
 * The axis is rescaled to `max * headroom` every frame. On a fixed axis the
 * last third of a run looks frozen, because the field has converged into a
 * narrow band; rescaling keeps the leader nearly filling the track so late
 * overtakes are still visible.
 */
export function planFrame(field: Racer[], trackWidth: number): FramePlan[] {
  if (!field.length || trackWidth <= 0) return [];

  const order = field.slice().sort((a, b) => {
    if (a.status === 'failed' && b.status !== 'failed') return 1;
    if (b.status === 'failed' && a.status !== 'failed') return -1;
    return (b.targetScore ?? -1) - (a.targetScore ?? -1);
  });

  const usable = Math.max(24, trackWidth - race.valueGutterPx);
  const max = Math.max(...field.map((r) => r.displayScore), 1);
  const x = scaleLinear().domain([0, max * race.headroom]).range([0, usable]);

  return order.map((r, rank) => ({
    id: r.id,
    rank,
    width: Math.max(race.minBarPx, x(r.displayScore)),
    label: labelFor(r),
    isLeader: rank === 0 && r.targetScore != null,
  }));
}

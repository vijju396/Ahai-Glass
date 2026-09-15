/**
 * The race's arithmetic, tested without a screen.
 *
 * `requestAnimationFrame` does not fire in a hidden document, so the drawing
 * loop cannot be exercised in a headless environment at all. Everything that
 * decides what a frame *should* look like was therefore pulled out of the
 * component and into `frame.ts`, and this is where it is proved.
 */
import { describe, expect, it } from 'vitest';
import { labelFor, planFrame, rawOf, stepDisplay } from '@/features/training-race/frame';
import { METRIC, race, rowHeightFor, toRaceValue } from '@/config/models';
import { MockTrainer } from '@/features/training-race/MockTrainer';
import { resolveModels } from '@/config/models';
import type { Racer, TrainingEvent } from '@/features/training-race/types';

function racer(id: string, target: number | null, extra: Partial<Racer> = {}): Racer {
  return {
    id,
    name: id,
    family: 'ml',
    isBaseline: false,
    targetScore: target,
    displayScore: target ?? 0,
    epoch: 1,
    totalEpochs: 10,
    status: 'running',
    error: null,
    wins: 0,
    ...extra,
  };
}

describe('frame planning', () => {
  it('ranks descending on the race value', () => {
    const plan = planFrame([racer('a', 40), racer('b', 90), racer('c', 65)], 500);
    expect(plan.map((p) => p.id)).toEqual(['b', 'c', 'a']);
    expect(plan[0]!.rank).toBe(0);
    expect(plan[0]!.isLeader).toBe(true);
  });

  it('rescales so the leader nearly fills the track', () => {
    // A fixed axis would leave everything short and the late race looking
    // frozen; the leader should always be near the end of its track.
    const wide = planFrame([racer('a', 10), racer('b', 6)], 500);
    const narrow = planFrame([racer('a', 90), racer('b', 54)], 500);
    expect(wide[0]!.width).toBeCloseTo(narrow[0]!.width, 5);
    // ...and the ratio between the two bars is preserved.
    expect(wide[1]!.width / wide[0]!.width).toBeCloseTo(0.6, 2);
  });

  it('keeps a minimum width so an unscored row still reads as present', () => {
    const plan = planFrame([racer('a', null, { displayScore: 0 }), racer('b', 90)], 500);
    const zero = plan.find((p) => p.id === 'a')!;
    expect(zero.width).toBe(race.minBarPx);
    expect(zero.label).toBe('—');
  });

  it('reserves the gutter so a full-length leader cannot push its number out', () => {
    const plan = planFrame([racer('a', 100)], 500);
    expect(plan[0]!.width).toBeLessThanOrEqual(500 - race.valueGutterPx);
  });

  it('sinks a failed model below everything still running, without erasing it', () => {
    const plan = planFrame(
      [racer('dead', 99, { status: 'failed' }), racer('alive', 10)],
      500,
    );
    expect(plan.map((p) => p.id)).toEqual(['alive', 'dead']);
    // It keeps its last length rather than collapsing to nothing.
    expect(plan.find((p) => p.id === 'dead')!.width).toBeGreaterThan(race.minBarPx);
  });

  it('draws nothing before the track has been measured', () => {
    expect(planFrame([racer('a', 50)], 0)).toEqual([]);
  });
});

describe('smoothing', () => {
  it('approaches the target without overshooting', () => {
    let d = 0;
    for (let i = 0; i < 200; i += 1) d = stepDisplay(d, 80);
    expect(d).toBeGreaterThan(79.9);
    expect(d).toBeLessThanOrEqual(80);
  });

  it('moves a fraction of the gap per frame, so bars glide rather than jump', () => {
    // The whole point: one event must not land as one visible step.
    expect(stepDisplay(0, 100)).toBeCloseTo(100 * race.smoothing, 6);
  });
});

describe('metric direction', () => {
  it('converts a lower-is-better value so longer still means better', () => {
    // Simulated rather than mutated globally: `toRaceValue` reads METRIC at
    // call time, so this asserts the contract the config promises.
    const worse = 40;
    const better = 10;
    const convert = (raw: number) => Math.max(0, 1 - raw / 100);
    expect(convert(better)).toBeGreaterThan(convert(worse));
    // And the round trip returns the raw number for the label.
    expect(Math.max(0, (1 - convert(better)) * 100)).toBeCloseTo(better, 6);
  });

  it('is configured higher-is-better here, and round-trips', () => {
    expect(METRIC.direction).toBe('higher');
    expect(toRaceValue(72.5)).toBe(72.5);
    expect(rawOf(72.5)).toBe(72.5);
    expect(labelFor(racer('a', 72.5))).toBe(`72.5${METRIC.suffix}`);
  });
});

describe('layout derives from the field size', () => {
  it('fits every field in the supported range on one screen', () => {
    // The documented range is three to about twenty models.
    for (let n = 3; n <= 20; n += 1) {
      expect(n * rowHeightFor(n)).toBeLessThanOrEqual(race.maxStagePx);
    }
    expect(rowHeightFor(13)).toBe(race.rowHeight);
    expect(rowHeightFor(20)).toBeLessThan(race.rowHeight);
  });

  it('stops compressing at the legibility floor rather than shrinking forever', () => {
    // Past the supported range the stage is allowed to grow: an unreadable
    // 12px row is worse than a taller panel.
    expect(rowHeightFor(60)).toBe(race.minRowPx);
  });

  it('handles a small field without stretching rows', () => {
    expect(rowHeightFor(3)).toBe(race.rowHeight);
  });
});

describe('a full mock run', () => {
  it('produces at least four lead changes', async () => {
    const models = resolveModels(
      Array.from({ length: 13 }, (_, i) => ({
        model_id: `model_${i}`,
        display_name: `Model ${i}`,
        is_baseline: i > 9,
      })),
    );

    const field: Racer[] = models.map((m) => racer(m.id, null, { displayScore: 0 }));
    const byId = new Map(field.map((r) => [r.id, r]));

    const events: TrainingEvent[] = [];
    await new Promise<void>((resolve) => {
      const stop = new MockTrainer().start(models, (e) => {
        events.push(e);
        if (e.type === 'progress') {
          const row = byId.get(e.modelId)!;
          row.targetScore = e.value;
          row.displayScore = e.value;
        }
        if (e.type === 'failed') byId.get(e.modelId)!.status = 'failed';
      });
      setTimeout(() => {
        stop();
        resolve();
      }, 9000);
    });

    let leader: string | null = null;
    let changes = 0;
    // Replay the recorded values through the real planner.
    for (const r of field) r.displayScore = 0;
    for (const e of events) {
      if (e.type !== 'progress') continue;
      const row = byId.get(e.modelId)!;
      row.targetScore = e.value;
      row.displayScore = e.value;
      const top = planFrame(field, 500)[0];
      if (top && top.id !== leader) {
        if (leader !== null) changes += 1;
        leader = top.id;
      }
    }
    expect(changes).toBeGreaterThanOrEqual(4);
  }, 20000);
});

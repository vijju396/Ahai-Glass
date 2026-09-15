/**
 * A trainer that emits the real event contract on a schedule, with no backend.
 *
 * It generates its curves from whatever `MODELS` it is handed — it carries no
 * model list of its own, so adding a model to the workspace adds a lane to the
 * mock automatically.
 *
 * The curves are shaped to produce a race worth watching, and the shape is the
 * honest one: **fast-converging models sprint early and slower, stronger models
 * pass them later.** That is real behaviour for this field — a moving average
 * is near its ceiling after three epochs while a seasonal model is still
 * finding its period — and it is what makes lead changes happen in the middle
 * rather than everything being decided in the first second.
 *
 * Each lane gets a ceiling, a rate and a small amount of noise, seeded from the
 * model id so a given field always races the same way. A deterministic mock is
 * worth more than a novel one: when the reorder looks wrong you can replay the
 * exact run that showed it.
 */
import type { ModelDef } from '@/config/models';
import type { Trainer, TrainingEvent } from './types';

const TOTAL_EPOCHS = 60;
const TICK_MS = 260;

/** Stable hash → the mock is reproducible for a given field. */
function seed(text: string): number {
  let h = 2166136261;
  for (let i = 0; i < text.length; i += 1) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return (h >>> 0) / 4294967295;
}

interface Lane {
  model: ModelDef;
  ceiling: number;
  /** Epochs to reach half the ceiling. Small = sprints early. */
  halfLife: number;
  jitter: number;
  /** Epoch this lane starts moving; a small stagger reads as dispatch. */
  offset: number;
  failAt: number | null;
}

function lanesFor(models: ModelDef[]): Lane[] {
  return models.map((model, i) => {
    const a = seed(model.id);
    const b = seed(`${model.id}:rate`);
    const c = seed(`${model.id}:fail`);

    // Baselines converge almost immediately and plateau low: they are the
    // early leaders that get overtaken, which is exactly their real behaviour.
    const isBase = model.isBaseline;
    const ceiling = isBase ? 55 + a * 12 : 48 + a * 30;
    // Baselines converge in a couple of epochs; registry models take much
    // longer, which is what puts the overtakes in the middle of the run.
    const halfLife = isBase ? 0.6 + b * 0.8 : 4 + b * 14;

    return {
      model,
      ceiling,
      halfLife,
      jitter: isBase ? 0.25 : 0.9,
      offset: Math.floor(i * 0.4),
      // One lane in a large field fails, so the failure path is exercised
      // rather than only described. Never a baseline — those cannot fail.
      failAt: !isBase && c > 0.965 ? Math.floor(TOTAL_EPOCHS * (0.3 + c * 0.3)) : null,
    };
  });
}

export class MockTrainer implements Trainer {
  start(models: ModelDef[], onEvent: (event: TrainingEvent) => void): () => void {
    const lanes = lanesFor(models);
    let epoch = 0;
    let stopped = false;
    const dead = new Set<string>();

    for (const lane of lanes) {
      onEvent({ type: 'started', modelId: lane.model.id, totalEpochs: TOTAL_EPOCHS });
    }

    const timer = window.setInterval(() => {
      if (stopped) return;
      epoch += 1;

      for (const lane of lanes) {
        if (dead.has(lane.model.id)) continue;
        if (epoch < lane.offset) continue;

        if (lane.failAt != null && epoch === lane.failAt) {
          dead.add(lane.model.id);
          onEvent({
            type: 'failed',
            modelId: lane.model.id,
            error: 'The fit raised during optimisation.',
          });
          continue;
        }

        const t = epoch - lane.offset;
        // Hyperbolic saturation: fast at first, asymptotic to the ceiling.
        //
        // Deliberately not the exponential form. `no-duplicate-registry.test.ts`
        // bans the natural-exponential call anywhere in frontend source,
        // because forecast values are the backend's to derive. A mock curve is
        // not a forecast — but weakening a guard to let a demo file through is
        // a bad trade, and `t / (t + k)` has the same fast-then-flattening
        // shape. (The ban is a plain substring scan, so naming the call even
        // inside a comment trips it.)
        const base = (lane.ceiling * t) / (t + lane.halfLife);
        const noise = (seed(`${lane.model.id}:${epoch}`) - 0.5) * lane.jitter;
        const value = Math.max(0, base + noise);

        onEvent({ type: 'progress', modelId: lane.model.id, epoch, value });
      }

      if (epoch >= TOTAL_EPOCHS) {
        stopped = true;
        window.clearInterval(timer);
        for (const lane of lanes) {
          if (dead.has(lane.model.id)) continue;
          const t = epoch - lane.offset;
          const final = (lane.ceiling * t) / (t + lane.halfLife);
          onEvent({
            type: 'finished',
            modelId: lane.model.id,
            metrics: { accuracy: final },
          });
        }
      }
    }, TICK_MS);

    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }
}

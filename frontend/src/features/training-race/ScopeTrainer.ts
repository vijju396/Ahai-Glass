/**
 * Replays one branch x SKU line's finished board as a race.
 *
 * The live trainer streams a run as it happens. Once a run is over there is
 * nothing left to stream, and the race would otherwise sit on the workspace
 * average no matter which line the filter names — the console showing one
 * thing while the table under it showed another.
 *
 * So this trainer emits the same four events from stored results. Every value
 * is the line's own measured accuracy; nothing is invented and nothing is
 * interpolated. The only thing this adds is the *order* the bars arrive in,
 * which is deliberately worst-first so the field converges on the winner
 * rather than starting at the answer.
 *
 * A model that did not run emits `failed` with its real reason, so an
 * ineligible model keeps its lane and its explanation instead of disappearing
 * into an empty bar (CLAUDE.md: a model that did not run never disappears).
 */
import type { ModelDef } from '@/config/models';
import type { LeaderboardRow } from '@/types/phase7';
import type { Trainer, TrainingEvent } from './types';

/** Frames per model. Enough motion to read as a race, short enough to settle. */
const STEPS = 12;
/** Milliseconds between frames. */
const TICK = 28;

export class ScopeTrainer implements Trainer {
  constructor(
    private readonly rows: LeaderboardRow[],
    /** Emit every model's final value at once, with no stepped frames — for a
     *  static, un-animated board. */
    private readonly instant = false,
  ) {}

  start(models: ModelDef[], onEvent: (event: TrainingEvent) => void): () => void {
    const byId = new Map(this.rows.map((row) => [row.model_id, row]));
    let timer: ReturnType<typeof setTimeout> | null = null;
    let stopped = false;

    /* Worst first. Emitting best-first would settle the crown on frame one
       and there would be no overtakes to watch. */
    const field = models
      .map((model) => ({ model, row: byId.get(model.id) ?? null }))
      .sort((a, b) => (b.row?.mape ?? 9e9) - (a.row?.mape ?? 9e9));

    for (const { model } of field) {
      onEvent({ type: 'started', modelId: model.id, totalEpochs: STEPS });
    }

    if (this.instant) {
      for (const { model, row } of field) {
        const target =
          row?.accuracy ?? (row?.mape == null ? null : Math.max(0, 100 - row.mape));
        if (row == null || target == null) {
          onEvent({
            type: 'failed',
            modelId: model.id,
            error:
              row?.exclusion_reason ??
              row?.failure_reason ??
              'This model produced no score on this line.',
          });
        } else {
          onEvent({ type: 'progress', modelId: model.id, epoch: STEPS, value: target });
          onEvent({
            type: 'finished',
            modelId: model.id,
            metrics: {
              accuracy: target,
              ...(row.mape == null ? {} : { mape: row.mape }),
              ...(row.wape == null ? {} : { wape: row.wape }),
            },
          });
        }
      }
      return () => {};
    }

    let index = 0;
    let step = 0;
    const pump = () => {
      if (stopped || index >= field.length) return;
      const entry = field[index];
      if (!entry) return;
      const { model, row } = entry;
      const target =
        row?.accuracy ?? (row?.mape == null ? null : Math.max(0, 100 - row.mape));

      if (row == null || target == null) {
        onEvent({
          type: 'failed',
          modelId: model.id,
          error:
            row?.exclusion_reason ??
            row?.failure_reason ??
            'This model produced no score on this line.',
        });
        index += 1;
        step = 0;
      } else {
        step += 1;
        // Ease in, so a bar arrives rather than snapping to its value.
        const eased = target * (1 - Math.pow(1 - step / STEPS, 3));
        onEvent({ type: 'progress', modelId: model.id, epoch: step, value: eased });
        if (step >= STEPS) {
          onEvent({
            type: 'finished',
            modelId: model.id,
            metrics: {
              accuracy: target,
              ...(row.mape == null ? {} : { mape: row.mape }),
              ...(row.wape == null ? {} : { wape: row.wape }),
            },
          });
          index += 1;
          step = 0;
        }
      }
      timer = setTimeout(pump, TICK);
    };
    timer = setTimeout(pump, TICK);

    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
    };
  }
}

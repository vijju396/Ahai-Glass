/**
 * Starts a real training run, then races it.
 *
 * The button has to do two things the mock does not: submit the run, and only
 * then discover the id it needs to stream. Both live behind the same
 * `Trainer.start()` signature, so the race component is unchanged — it presses
 * start and gets a stop function, exactly as it does with the mock.
 *
 * A run already in flight is adopted rather than refused. Someone arriving mid
 * run, or pressing the button while the server is busy, should see the race
 * that is actually happening instead of an error about a conflict.
 */
import { fetchCurrentRun, submitRun } from '@/api/training';
import type { ModelDef } from '@/config/models';
import type { Trainer, TrainingEvent } from './types';
import { SSETrainer } from './SSETrainer';

const LIVE = ['running', 'queued', 'pending'];

export class ApiTrainer implements Trainer {
  constructor(
    private readonly body: Record<string, unknown>,
    private readonly onRunId?: (runId: string) => void,
    private readonly onError?: (message: string) => void,
  ) {}

  start(models: ModelDef[], onEvent: (event: TrainingEvent) => void): () => void {
    let stop: (() => void) | null = null;
    let cancelled = false;

    const attach = (runId: string) => {
      if (cancelled) return;
      this.onRunId?.(runId);
      stop = new SSETrainer(runId).start(models, onEvent);
    };

    (async () => {
      try {
        const current = await fetchCurrentRun().catch(() => null);
        if (current && LIVE.includes(current.status)) {
          attach(current.id);
          return;
        }
        const run = await submitRun(this.body);
        attach(run.id);
      } catch (err) {
        this.onError?.(readError(err));
      }
    })();

    return () => {
      cancelled = true;
      stop?.();
    };
  }
}

function readError(err: unknown): string {
  const body = (err as { response?: { data?: { error?: Record<string, unknown> } } })?.response
    ?.data?.error;
  if (body) {
    const message = String(body.message ?? 'The run could not be started.');
    const details = body.details as Record<string, unknown> | undefined;
    const remediation = details?.remediation ?? body.remediation;
    return remediation ? `${message} ${String(remediation)}` : message;
  }
  return (err as Error)?.message ?? 'The run could not be started.';
}

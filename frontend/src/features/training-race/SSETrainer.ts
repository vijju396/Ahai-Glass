/**
 * The live trainer. Same contract as the mock, so swapping is one line.
 *
 * Reads `GET /api/training/{runId}/model-events`, which emits the identical
 * four-event shape. Nothing downstream — store, race, crown — can tell which
 * trainer it is talking to, which is the point: the race is developed and
 * demoed against the mock and shipped against the server unchanged.
 */
import type { ModelDef } from '@/config/models';
import type { Trainer, TrainingEvent } from './types';

export class SSETrainer implements Trainer {
  constructor(private readonly runId: string) {}

  start(_models: ModelDef[], onEvent: (event: TrainingEvent) => void): () => void {
    const source = new EventSource(`/api/training/${this.runId}/model-events`);

    source.addEventListener('training', (raw) => {
      try {
        onEvent(JSON.parse((raw as MessageEvent).data) as TrainingEvent);
      } catch {
        // One malformed frame is not worth tearing the stream down for; the
        // next tick carries the same state again.
      }
    });

    source.addEventListener('end', () => source.close());

    return () => source.close();
  }
}

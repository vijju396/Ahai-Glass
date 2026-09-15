/**
 * The event contract the race is driven by.
 *
 * Both trainers emit exactly this, so swapping the mock for the live stream is
 * one line at the call site and nothing downstream knows the difference.
 */
import type { ModelDef } from '@/config/models';

export type TrainingEvent =
  | { type: 'started'; modelId: string; totalEpochs: number }
  | { type: 'progress'; modelId: string; epoch: number; value: number }
  | { type: 'finished'; modelId: string; metrics: Record<string, number> }
  | { type: 'failed'; modelId: string; error: string };

export type RunPhase = 'idle' | 'running' | 'settling' | 'done';

export interface Racer {
  id: string;
  name: string;
  family: string;
  isBaseline: boolean;
  /** Last value from an event. The race eases toward this. */
  targetScore: number | null;
  /** What is actually drawn this frame. */
  displayScore: number;
  epoch: number;
  totalEpochs: number;
  status: 'waiting' | 'running' | 'finished' | 'failed';
  error: string | null;
  /** Champion wins, when the source knows them. Never used for ranking. */
  wins: number;
}

export interface Trainer {
  /** Begins emitting. Returns a stop function. */
  start(models: ModelDef[], onEvent: (event: TrainingEvent) => void): () => void;
}

/**
 * Training state, held outside React's render path.
 *
 * The race writes bar widths sixty times a second from a `requestAnimationFrame`
 * loop. If that state lived in React, every frame would be a render of the
 * whole field; instead the store holds the numbers, the loop reads them
 * directly and writes to DOM nodes, and React only re-renders when the *set* of
 * racers or the run phase changes.
 *
 * `displayScore` is deliberately mutated in place by the loop rather than set
 * through zustand — it changes every frame and nothing subscribes to it.
 */
import { create } from 'zustand';
import type { ModelDef } from '@/config/models';
import { toRaceValue } from '@/config/models';
import type { Racer, RunPhase, TrainingEvent } from './types';

interface RaceState {
  racers: Racer[];
  phase: RunPhase;
  epoch: number;
  /** Rising counter so the race component knows the field was replaced. */
  generation: number;
  leaderId: string | null;

  load(models: ModelDef[]): void;
  apply(event: TrainingEvent): void;
  setPhase(phase: RunPhase): void;
  setLeader(id: string | null): void;
  reset(): void;
}

function blank(model: ModelDef): Racer {
  return {
    id: model.id,
    name: model.name,
    family: model.family,
    isBaseline: model.isBaseline,
    targetScore: null,
    displayScore: 0,
    epoch: 0,
    totalEpochs: 0,
    status: 'waiting',
    error: null,
    wins: 0,
  };
}

export const useRaceStore = create<RaceState>((set, get) => ({
  racers: [],
  phase: 'idle',
  epoch: 0,
  generation: 0,
  leaderId: null,

  load(models) {
    set((s) => ({
      racers: models.map(blank),
      phase: 'idle',
      epoch: 0,
      leaderId: null,
      generation: s.generation + 1,
    }));
  },

  apply(event) {
    const racers = get().racers;
    const index = racers.findIndex((r) => r.id === event.modelId);
    if (index === -1) return;
    const next = racers.slice();
    const existing = next[index];
    if (!existing) return;
    const row: Racer = { ...existing };

    switch (event.type) {
      case 'started':
        row.status = 'running';
        row.totalEpochs = event.totalEpochs;
        break;
      case 'progress':
        row.status = 'running';
        row.epoch = event.epoch;
        // Converted once, here. Everything downstream sorts descending on
        // targetScore, whichever direction the metric runs in.
        row.targetScore = toRaceValue(event.value);
        break;
      case 'finished':
        row.status = 'finished';
        if (typeof event.metrics[METRIC_KEY] === 'number') {
          row.targetScore = toRaceValue(event.metrics[METRIC_KEY]);
        }
        if (typeof event.metrics.wins === 'number') row.wins = event.metrics.wins;
        break;
      case 'failed':
        // Frozen at its last value and greyed, never removed. A model that
        // fell over is a result, and a row vanishing mid-race would read as
        // "this never existed".
        row.status = 'failed';
        row.error = event.error;
        break;
    }

    next[index] = row;
    const epoch = event.type === 'progress' ? Math.max(get().epoch, event.epoch) : get().epoch;
    set({ racers: next, epoch });
  },

  setPhase(phase) {
    set({ phase });
  },
  setLeader(id) {
    if (get().leaderId !== id) set({ leaderId: id });
  },
  reset() {
    set((s) => ({
      racers: s.racers.map((r) => ({
        ...r,
        targetScore: null,
        displayScore: 0,
        epoch: 0,
        status: 'waiting',
        error: null,
      })),
      phase: 'idle',
      epoch: 0,
      leaderId: null,
      generation: s.generation + 1,
    }));
  },
}));

/** The metric field a `finished` event carries. Kept beside the reducer that
 *  reads it so the two cannot drift. */
const METRIC_KEY = 'accuracy';

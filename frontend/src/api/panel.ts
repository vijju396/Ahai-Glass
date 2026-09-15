import { getJson, postJson } from '@/api/client';
import type { PanelBuild } from '@/types/api';

export const panelKeys = {
  current: ['panel', 'current'] as const,
};

export function fetchCurrentPanel(): Promise<PanelBuild> {
  return getJson<PanelBuild>('/panel/builds/current');
}

export function startPanelBuild(body: {
  training_cut_period?: string;
  horizons?: number[];
}): Promise<PanelBuild> {
  return postJson<PanelBuild>('/panel/builds', body);
}

export function isPanelBuildRunning(status: string | undefined): boolean {
  return status === 'pending' || status === 'running';
}

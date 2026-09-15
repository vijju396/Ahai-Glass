import { getJson } from '@/api/client';
import type { ModelRegistryResponse } from '@/types/api';

export const modelKeys = {
  registry: ['models', 'registry'] as const,
};

export function fetchModelRegistry(): Promise<ModelRegistryResponse> {
  return getJson<ModelRegistryResponse>('/models');
}

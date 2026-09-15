import { getJson } from '@/api/client';
import type { HealthResponse } from '@/types/api';

export const healthKeys = { all: ['health'] as const };

export function fetchHealth(): Promise<HealthResponse> {
  return getJson<HealthResponse>('/health');
}

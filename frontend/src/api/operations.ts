import { getJson, postJson } from '@/api/client';
import type {
  MonitoringResponse,
  ScenarioRequest,
  ScenarioResponse,
  SettingsResponse,
} from '@/types/operations';

export const operationsKeys = {
  monitoring: ['monitoring'] as const,
  settings: ['settings'] as const,
  exports: ['exports'] as const,
};

export function fetchMonitoring(): Promise<MonitoringResponse> {
  return getJson<MonitoringResponse>('/monitoring');
}

export function fetchSettings(): Promise<SettingsResponse> {
  return getJson<SettingsResponse>('/settings');
}

export function fetchExportKinds(): Promise<{
  kinds: { kind: string; description: string }[];
  note: string;
}> {
  return getJson('/exports');
}

/**
 * Evaluates a what-if against a stored baseline. The baseline is read-only:
 * this never overwrites the forecast it compares against.
 */
export function evaluateScenario(body: ScenarioRequest): Promise<ScenarioResponse> {
  return postJson<ScenarioResponse>('/scenarios', body);
}

/** The URL an export downloads from. Built here so the base path lives in one place. */
export function exportUrl(kind: string, params: Record<string, unknown> = {}): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== '') {
      search.set(key, String(value));
    }
  }
  const base = import.meta.env.VITE_API_BASE ?? '/api';
  const query = search.toString();
  return `${base}/exports/${kind}${query ? `?${query}` : ''}`;
}

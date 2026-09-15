import { getJson, postJson } from '@/api/client';
import type {
  ForecastRow,
  ForecastRun,
  HierarchyResponse,
  Page,
  SeriesForecastResponse,
} from '@/types/phase7';

export const forecastKeys = {
  runs: ['forecasts', 'runs'] as const,
  current: ['forecasts', 'current'] as const,
  rows: (query: Record<string, unknown>) => ['forecasts', 'rows', query] as const,
  series: (level: string, key: string) => ['forecasts', 'series', level, key] as const,
  hierarchy: (period?: string) => ['forecasts', 'hierarchy', period ?? 'all'] as const,
};

export function submitForecastRun(body: {
  training_run_id?: string;
  reconciliation?: string;
  horizons?: number[];
}): Promise<ForecastRun> {
  return postJson<ForecastRun>('/forecasts/runs', body);
}

export function fetchForecastRuns(limit = 25): Promise<Page<ForecastRun>> {
  return getJson<Page<ForecastRun>>('/forecasts/runs', { limit });
}

export function fetchCurrentForecastRun(): Promise<ForecastRun> {
  return getJson<ForecastRun>('/forecasts/runs/current');
}

/**
 * Rows with no forecast are included by default: they carry a reason, and
 * excluding them would hide scopes the run could not serve.
 */
export function fetchForecastRows(
  query: {
    forecast_run_id?: string;
    scope_level?: string;
    scope_key?: string;
    period_from?: string;
    period_to?: string;
    model_id?: string;
    include_unavailable?: boolean;
    limit?: number;
  } = {},
): Promise<Page<ForecastRow>> {
  return getJson<Page<ForecastRow>>('/forecasts', { limit: 200, ...query });
}

export function fetchSeriesForecast(
  scope_level: string,
  scope_key: string,
  forecast_run_id?: string,
): Promise<SeriesForecastResponse> {
  return getJson<SeriesForecastResponse>('/forecasts/series', {
    scope_level,
    scope_key,
    forecast_run_id,
    history_months: 120,
  });
}

export function fetchHierarchy(
  period?: string,
  forecast_run_id?: string,
): Promise<HierarchyResponse> {
  return getJson<HierarchyResponse>('/forecasts/hierarchy', { period, forecast_run_id });
}

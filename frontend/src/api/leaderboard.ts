import { getJson, postJson } from '@/api/client';
import type {
  ChampionSelection,
  ComparisonPoint,
  DiagnosticsResponse,
  LeaderboardResponse,
  Page,
  ScopeRef,
  SelectChampionsResponse,
} from '@/types/phase7';

/** Index signature so the query can be passed straight to the HTTP client. */
export interface ScopeQuery extends Record<string, unknown> {
  training_run_id?: string;
  scope_level?: string;
  scope_key?: string;
}

export const leaderboardKeys = {
  board: (query: ScopeQuery) => ['leaderboard', 'board', query] as const,
  comparison: (query: ScopeQuery) => ['leaderboard', 'comparison', query] as const,
  scopes: (level?: string) => ['leaderboard', 'scopes', level ?? 'all'] as const,
  diagnostics: (modelId: string, query: ScopeQuery) =>
    ['leaderboard', 'diagnostics', modelId, query] as const,
  champions: (scopeKind?: string) => ['champions', scopeKind ?? 'all'] as const,
  history: (scopeKind: string, scopeKey: string) =>
    ['champions', 'history', scopeKind, scopeKey] as const,
};

export function fetchLeaderboard(query: ScopeQuery = {}): Promise<LeaderboardResponse> {
  return getJson<LeaderboardResponse>('/models/leaderboard', query);
}

/** Models on x, WAPE on y - including the models that did not run. */
export function fetchComparison(query: ScopeQuery = {}): Promise<ComparisonPoint[]> {
  return getJson<ComparisonPoint[]>('/models/leaderboard/comparison', query);
}

export function fetchScopes(
  scope_level?: string,
  limit = 500,
): Promise<Page<ScopeRef>> {
  return getJson<Page<ScopeRef>>('/models/leaderboard/scopes', { scope_level, limit });
}

export function fetchDiagnostics(
  modelId: string,
  query: ScopeQuery = {},
): Promise<DiagnosticsResponse> {
  return getJson<DiagnosticsResponse>(`/models/${modelId}/diagnostics`, query);
}

export function fetchChampions(
  scope_kind?: string,
  limit = 200,
): Promise<Page<ChampionSelection>> {
  return getJson<Page<ChampionSelection>>('/models/champions', { scope_kind, limit });
}

export function fetchChampionHistory(
  scope_kind: string,
  scope_key: string,
): Promise<{ scope_kind: string; scope_key: string; entries: ChampionSelection[]; total: number }> {
  return getJson('/models/champions/history', { scope_kind, scope_key });
}

export function selectChampions(body: {
  training_run_id?: string;
  scope_kinds?: string[];
  actor?: string;
}): Promise<SelectChampionsResponse> {
  return postJson<SelectChampionsResponse>('/models/champions/select', body);
}

/** A reason is required; the backend enforces a 10-character floor too. */
export function overrideChampion(body: {
  scope_kind?: string;
  scope_key?: string;
  model_id: string;
  reason: string;
  actor?: string;
}): Promise<ChampionSelection> {
  return postJson<ChampionSelection>('/models/champion/override', body);
}

export function rollbackChampion(body: {
  scope_kind?: string;
  scope_key?: string;
  reason?: string;
  actor?: string;
}): Promise<ChampionSelection> {
  return postJson<ChampionSelection>('/models/champion/rollback', body);
}

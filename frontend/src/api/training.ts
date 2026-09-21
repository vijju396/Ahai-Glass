import { getJson, postJson } from '@/api/client';
import type {
  Page,
  RunEstimate,
  TrainingRunDetail,
  TrainingRunRequest,
  TrainingRunSummary,
} from '@/types/phase7';

export const trainingKeys = {
  runs: (offset: number, limit: number) => ['training', 'runs', offset, limit] as const,
  current: ['training', 'current'] as const,
  detail: (runId: string) => ['training', 'detail', runId] as const,
  estimate: (body: TrainingRunRequest) => ['training', 'estimate', body] as const,
};

/** What the run will cost. Never starts anything. */
export function estimateRun(body: TrainingRunRequest): Promise<RunEstimate> {
  return postJson<RunEstimate>('/training/estimate', body);
}

/** Returns 202 with a run id; the work happens in the background. */
export function submitRun(body: TrainingRunRequest): Promise<TrainingRunSummary> {
  return postJson<TrainingRunSummary>('/training', body);
}

export function fetchRuns(offset = 0, limit = 25): Promise<Page<TrainingRunSummary>> {
  return getJson<Page<TrainingRunSummary>>('/training', { offset, limit });
}

export function fetchCurrentRun(): Promise<TrainingRunSummary> {
  return getJson<TrainingRunSummary>('/training/current');
}

/**
 * Run detail with per-model rows. There is deliberately no status filter: the
 * ineligible, failed and timed-out rows are the point of the table.
 */
export function fetchRunDetail(
  runId: string,
  params: { scope_level?: string; scope_key?: string; limit?: number } = {},
): Promise<TrainingRunDetail> {
  return getJson<TrainingRunDetail>(`/training/${runId}`, { limit: 500, ...params });
}

export function cancelRun(runId: string): Promise<TrainingRunSummary> {
  return postJson<TrainingRunSummary>(`/training/${runId}/cancel`);
}

/**
 * Live monitor: per-model progress plus the validation design the run used.
 *
 * Aggregated server-side. The per-model rows number in the hundreds and this
 * is polled while a run is in flight, so summarising in the browser would
 * mean re-sending every row on every tick.
 */
export interface MonitorFold {
  index: number | null;
  name: string | null;
  train_end: string | null;
  train_rows: number | null;
  validate_from: string | null;
  validate_to: string | null;
  validate_months: number;
  horizons: number[];
}

export interface MonitorModel extends MonitorMetrics {
  model_id: string;
  display_name: string;
  /** The four non-registry baselines. Never candidates, never champion. */
  is_baseline: boolean;
  total: number;
  completed: number;
  ineligible: number;
  failed: number;
  timed_out: number;
  not_evaluated: number;
  running: number;
  pending: number;
  median_wape: number | null;
  best_wape: number | null;
  median_mape: number | null;
  fit_seconds: number;
  champion_count: number;
  scored: number;
}

/**
 * The shape of a run: how many scopes, at which levels, and who won them.
 *
 * The page explained the *rules* of training but never its *size* - how many
 * fits a run performs, at which levels of the hierarchy, and how many distinct
 * models end up winning something. That is the first question anyone being
 * shown this asks, and it used to be answerable only from the database.
 */
export interface MonitorPipeline {
  scopes_total: number;
  scopes_by_level: Record<string, number>;
  registry_models: number;
  baseline_models: number;
  champions_selected: number;
  champions_beaten_by_baseline: number;
  /** model_id -> how many scopes it is champion of, highest first. */
  champion_spread: Record<string, number>;
}

export interface TrainingMonitor {
  run_id: string;
  status: string;
  stage_detail: string | null;
  progress_pct: number;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  duration_seconds: number | null;
  is_live: boolean;
  counters: {
    total: number;
    completed: number;
    ineligible: number;
    failed: number;
    timed_out: number;
    not_evaluated: number;
  };
  series_requested: number;
  series_evaluated: number;
  restriction: Record<string, unknown> | null;
  folds: MonitorFold[];
  models: MonitorModel[];
  registry_model_count: number;
  baseline_model_count: number;
  pipeline: MonitorPipeline;
}

export const monitorKeys = {
  run: (runId: string) => ['training', 'monitor', runId] as const,
};

export function fetchTrainingMonitor(runId: string): Promise<TrainingMonitor> {
  return getJson<TrainingMonitor>(`/training/${runId}/monitor`);
}

/** Metrics the leaderboard shows beyond the race's single number. */
export interface MonitorMetrics {
  accuracy: number | null;
  /**
   * Accuracy with each scope weighted by its demand volume.
   *
   * `accuracy` treats a SKU selling 99 units over 28 months exactly like one
   * selling 9,672, and MAPE explodes on the small denominator — so the
   * unweighted figure is set largely by lines whose errors cost nothing.
   * Measured on this workspace the difference is 22 points at series grain.
   */
  accuracy_weighted: number | null;
  /** The weighted MAPE `accuracy_weighted` is 100 minus. The two reconcile. */
  mape_weighted: number | null;
  /** Accuracy at branch x SKU - the hardest grain, and most of the rows. */
  accuracy_series: number | null;
  /** Accuracy at national, region, branch and segment totals. */
  accuracy_aggregate: number | null;
  median_mae: number | null;
  median_rmse: number | null;
  median_smape: number | null;
  median_mase: number | null;
  median_bias: number | null;
  validation_points: number;
  /** Why an Ineligible model did not run. Null when it did. */
  reason: string | null;
}

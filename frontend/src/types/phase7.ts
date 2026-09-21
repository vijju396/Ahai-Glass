/**
 * Response types for training, the leaderboard, champions, forecasts and
 * inventory.
 *
 * These mirror the backend Pydantic schemas. They describe **shapes**, never
 * model identity: there is no list of model IDs anywhere in this file, because
 * the frontend learns those only from `GET /api/models`
 * (`src/test/no-duplicate-registry.test.ts` scans for a second registry).
 *
 * Every metric is `number | null`. `null` means the metric was undefined for
 * that window - on AIS data that is the common case, not an error - and the UI
 * must render it as "not defined", never as 0.
 */

export interface Page<T> {
  items: T[];
  total: number;
  offset: number;
  limit: number;
}

/* ---------------------------------------------------------------- training */

export interface TierEstimate {
  tier: string;
  series: number;
  origins: number;
  models: string[];
  fits: number;
  seconds: number;
  seconds_upper: number;
  notes: string[];
}

export interface RunEstimate {
  tiers: TierEstimate[];
  workers: number;
  total_fits: number;
  estimated_seconds: number;
  estimated_seconds_upper: number;
  estimated_human: string;
  estimated_human_upper: string;
  provenance: string;
  hard_timeout_models: string[];
}

export interface TrainingRunSummary {
  id: string;
  panel_build_id: string;
  status: string;
  stage_detail: string | null;
  progress_pct: number;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  duration_seconds: number | null;
  failure_reason: string | null;
  cancelled_at: string | null;
  tiers: string;
  min_history_profile: string;
  xgboost_training_profile: string;
  max_local_series: number;
  local_series_selection: string | null;
  estimated_seconds: number | null;
  total_budget_seconds: number | null;
  per_model_timeout_seconds: number | null;
  lstm_timeout_seconds: number | null;
  series_requested: number;
  series_evaluated: number;
  model_runs_total: number;
  model_runs_completed: number;
  model_runs_ineligible: number;
  model_runs_failed: number;
  model_runs_timed_out: number;
  model_runs_not_evaluated: number;
  residuals_recorded: number;
  mlflow_run_id: string | null;
  estimate: RunEstimate | null;
  origins: Record<string, unknown> | null;
  summary: Record<string, unknown> | null;
  warnings: unknown[] | null;
}

export interface ModelRunRow {
  id: string;
  training_run_id: string;
  tier: string;
  scope_level: string;
  scope_key: string;
  segment: string | null;
  model_id: string;
  display_name: string;
  is_baseline: boolean;
  status: string;
  evaluation_mode: string | null;
  failure_reason: string | null;
  eligibility: Record<string, unknown> | null;
  seasonal_period: number | null;
  origins_completed: number;
  origins_total: number;
  validation_points: number;
  total_test_points: number;
  duplicate_test_points: number;
  mae: number | null;
  rmse: number | null;
  wape: number | null;
  mape: number | null;
  accuracy: number | null;
  smape: number | null;
  mase: number | null;
  bias: number | null;
  bias_abs: number | null;
  naive_mae: number | null;
  legacy_mape: number | null;
  legacy_wape: number | null;
  legacy_mae: number | null;
  legacy_valid: boolean;
  zero_actual_points: number;
  censored_points: number;
  negative_predictions: number;
  max_abs_prediction: number | null;
  fit_seconds: number | null;
  predict_seconds: number | null;
  artifact_path: string | null;
  mlflow_run_id: string | null;
  parameters: Record<string, unknown> | null;
  features: unknown[] | null;
  origins: unknown[] | null;
}

export interface ModelStatusCount {
  status: string;
  count: number;
}

export interface TrainingRunDetail {
  run: TrainingRunSummary;
  status_counts: ModelStatusCount[];
  /** Registry models with no row in this run. Non-empty means a defect. */
  models_missing: string[];
  model_runs: ModelRunRow[];
  model_runs_returned: number;
  model_runs_matching: number;
  offset: number;
  limit: number;
}

export interface TrainingRunRequest {
  panel_build_id?: string | null;
  tiers?: string[];
  min_history_profile?: string | null;
  xgboost_training_profile?: string | null;
  max_local_series?: number | null;
  local_series_selection?: string | null;
  total_budget_seconds?: number | null;
  per_model_timeout_seconds?: number | null;
  hard_timeout_models?: string[] | null;
}

/* ------------------------------------------------------------ leaderboard */

export interface LeaderboardRow {
  model_id: string;
  display_name: string;
  status: string;
  is_baseline: boolean;
  evaluation_mode: string | null;
  rank: number | null;
  legacy_rank: number | null;
  is_champion: boolean;
  is_challenger: boolean;
  ranked: boolean;
  exclusion: string | null;
  exclusion_reason: string | null;
  comparability_note: string | null;
  wape: number | null;
  mae: number | null;
  rmse: number | null;
  mape: number | null;
  accuracy: number | null;
  smape: number | null;
  mase: number | null;
  bias: number | null;
  bias_abs: number | null;
  legacy_mape: number | null;
  legacy_valid: boolean;
  validation_points: number;
  distinct_test_points: number;
  origins_completed: number;
  origins_total: number;
  failure_reason: string | null;
  model_run_id: string | null;
}

export interface SkillScore {
  improvement_pct: number | null;
  champion_better: boolean | null;
  reason: string | null;
}

export interface ChampionSelection {
  id: string;
  training_run_id: string;
  scope_kind: string;
  scope_key: string;
  evaluated_scope_level: string | null;
  champion_model_id: string;
  champion_display_name: string;
  challenger_model_id: string | null;
  legacy_champion_model_id: string | null;
  champion_wape: number | null;
  champion_mae: number | null;
  champion_bias: number | null;
  champion_validation_points: number;
  champion_evaluation_mode: string | null;
  best_baseline_model_id: string | null;
  best_baseline_wape: number | null;
  beaten_by_baseline: boolean;
  selection_source: string;
  reason: string | null;
  actor: string | null;
  is_active: boolean;
  superseded_at: string | null;
  supersedes_id: string | null;
  restored_from_id: string | null;
  ranked_count: number;
  excluded_count: number;
  notes: unknown[] | null;
  created_at: string;
}

export interface LeaderboardResponse {
  training_run_id: string;
  panel_build_id: string | null;
  scope_level: string;
  scope_key: string;
  rows: LeaderboardRow[];
  champion_model_id: string | null;
  challenger_model_id: string | null;
  legacy_champion_model_id: string | null;
  best_baseline_model_id: string | null;
  best_baseline_wape: number | null;
  beaten_by_baseline: boolean;
  skill_vs_best_baseline: SkillScore;
  ranked_count: number;
  excluded_count: number;
  models_missing: string[];
  baselines_present: string[];
  notes: string[];
  origins: Record<string, unknown> | null;
  active_selection: ChampionSelection | null;
  /** `as_selected` when these rows are the board the champion was chosen on. */
  ranking_source?: string;
  ranking_note?: string | null;
}

export interface ComparisonPoint {
  model_id: string;
  display_name: string;
  wape: number | null;
  wape_pct: number | null;
  status: string;
  is_baseline: boolean;
  is_champion: boolean;
  exclusion: string | null;
  exclusion_reason: string | null;
}

export interface ScopeRef {
  scope_level: string;
  scope_key: string;
}

export interface FoldRow {
  origin_name: string | null;
  fold_index: number | null;
  train_end_period: string | null;
  train_rows: number | null;
  status: string | null;
  seasonal_period: number | null;
  failure_reason: string | null;
  eligibility: Record<string, unknown> | null;
  fit_seconds: number | null;
  predict_seconds: number | null;
  validation_periods: string[];
  metrics: Record<string, unknown> | null;
  legacy_metrics: Record<string, unknown> | null;
  negative_predictions: number | null;
  point_count: number;
}

export interface DiagnosticPoint {
  origin_name: string | null;
  fold_index: number | null;
  period: string | null;
  horizon: number | null;
  actual: number;
  predicted: number;
  residual: number;
}

export interface HorizonPerformance {
  horizon: number | null;
  points: number;
  mae: number | null;
  wape: number | null;
  bias: number | null;
  zero_actual_points: number;
}

export interface DiagnosticsResponse {
  training_run_id: string;
  model_id: string;
  display_name: string;
  is_baseline: boolean;
  scope_level: string;
  scope_key: string;
  status: string;
  evaluation_mode: string | null;
  failure_reason: string | null;
  eligibility: Record<string, unknown> | null;
  metrics: Record<string, number | boolean | null>;
  parameters: Record<string, unknown> | null;
  features: unknown[] | null;
  fit_seconds: number | null;
  predict_seconds: number | null;
  folds: FoldRow[];
  points: DiagnosticPoint[];
  horizon_performance: HorizonPerformance[];
  diagnostics_available: boolean;
  unavailable_reason: string | null;
}

export interface SelectChampionsResponse {
  training_run_id: string;
  selected: ChampionSelection[];
  skipped: { scope_kind: string; scope_key: string; reason: string; excluded_count: number }[];
  selected_count: number;
  skipped_count: number;
}

/* -------------------------------------------------------------- forecasts */

export interface ForecastRun {
  id: string;
  training_run_id: string;
  panel_build_id: string;
  status: string;
  stage_detail: string | null;
  progress_pct: number;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  duration_seconds: number | null;
  failure_reason: string | null;
  origin_period: string;
  horizons: string;
  requested_reconciliation: string | null;
  reconciliation_method: string | null;
  reconciliation_fallback_from: string | null;
  reconciliation_fallback_reason: string | null;
  shrinkage_intensity: number | null;
  coherent: boolean;
  max_incoherence: number | null;
  negatives_clipped: number;
  quantile_crossings_corrected: number;
  series_forecast: number;
  rows_written: number;
  rows_unavailable: number;
  summary: Record<string, unknown> | null;
  warnings: unknown[] | null;
}

export interface ForecastRow {
  id: string;
  forecast_run_id: string;
  scope_level: string;
  scope_key: string;
  canonical_branch: string | null;
  canonical_sku: string | null;
  region: string | null;
  demand_segment: string | null;
  value_class: string | null;
  period: string;
  horizon: number;
  model_id: string | null;
  model_display_name: string | null;
  model_run_id: string | null;
  champion_selection_id: string | null;
  forecast_source: string | null;
  point_forecast: number | null;
  q80: number | null;
  q90: number | null;
  q95: number | null;
  base_forecast: number | null;
  reconciliation_adjustment: number | null;
  reconciliation_method: string | null;
  quantile_method: string | null;
  quantile_pooling_level: string | null;
  quantile_residual_count: number;
  target_source: string | null;
  is_censored: boolean | null;
  unavailable_reason: string | null;
  drivers: Record<string, unknown> | null;
}

export interface HistoryPoint {
  period: string;
  actual: number;
  is_censored: boolean;
  target_source: string | null;
}

export interface ValidationMetrics {
  model_id: string;
  display_name: string;
  wape: number | null;
  mae: number | null;
  rmse: number | null;
  mape: number | null;
  smape: number | null;
  mase: number | null;
  bias: number | null;
  validation_points: number;
  evaluation_mode: string | null;
}

export interface SeriesForecastResponse {
  forecast_run_id: string;
  training_run_id: string;
  scope_level: string;
  scope_key: string;
  origin_period: string;
  history: HistoryPoint[];
  history_unavailable_reason: string | null;
  forecasts: ForecastRow[];
  validation_metrics: ValidationMetrics | null;
  drivers: Record<string, unknown> | null;
  reconciliation_method: string | null;
  coherent: boolean;
  snapshot_caveat: string;
}

export interface LevelTotals {
  scope_level: string;
  nodes: number;
  point_total: number;
  base_total: number;
  adjustment_total: number;
  q95_total: number;
}

export interface HierarchyResponse {
  forecast_run_id: string;
  origin_period: string;
  period: string | null;
  levels: LevelTotals[];
  level_gaps: {
    from_level: string;
    to_level: string;
    difference: number;
    coherent: boolean;
  }[];
  reconciliation_method: string | null;
  reconciliation_fallback_from: string | null;
  reconciliation_fallback_reason: string | null;
  coherent: boolean;
  max_incoherence: number | null;
  quantile_crossings_corrected: number;
}

/* -------------------------------------------------------------- inventory */

export interface Recommendation {
  scope_key: string;
  canonical_branch: string | null;
  canonical_sku: string | null;
  service_level: number;
  forecast_period: string | null;
  forecast_model_id: string | null;
  demand_segment: string | null;
  stock_class: string | null;
  monthly_point_forecast: number | null;
  monthly_quantile_forecast: number | null;
  review_period_days: number;
  lead_time_days: number | null;
  lead_time_source: string | null;
  lead_time_p95_days: number | null;
  protection_period_days: number | null;
  protection_months: number | null;
  usable_stock_on_hand: number | null;
  closing_stock_on_hand: number | null;
  negative_stock_rows: number;
  confirmed_stock_on_order: number;
  backorders: number;
  order_up_to_level: number | null;
  raw_recommended_order: number | null;
  recommended_order: number | null;
  days_of_cover: number | null;
  moq: number | null;
  truck_quantity: number | null;
  case_pack: number | null;
  substitute_skus: string[];
  target_source: string | null;
  is_censored: boolean | null;
  unavailable_reason: string | null;
  warnings: string[];
  caveats: string[];
  is_current_snapshot_estimate: boolean;
}

export interface RecommendationsResponse {
  forecast_run_id: string;
  period: string;
  service_level: number;
  scope_level: string;
  items: Recommendation[];
  total: number;
  offset: number;
  limit: number;
  unavailable_reason: string | null;
  notes: string[];
}

export interface SupplyOverviewResponse {
  forecast_run_id: string;
  period: string | null;
  branch: string | null;
  stock_snapshot_date: string;
  totals: {
    positions: number;
    positions_with_stock: number;
    dead_or_slow_positions: number;
    dead_stock_units: number;
    dead_stock_value: number | null;
    zero_stock_live_demand_positions: number;
    unfilled_recent_demand_units: number;
    negative_stock_rows: number;
  };
  dead_stock: {
    canonical_branch: string | null;
    canonical_sku: string | null;
    usable_qty: number;
    closing_value: number | null;
    recent_demand: number;
    stock_class: string | null;
  }[];
  zero_stock_live_demand: {
    canonical_branch: string | null;
    canonical_sku: string | null;
    usable_qty: number;
    recent_demand: number;
  }[];
  lead_time_assumptions: Record<string, Record<string, number | null>>;
  review_period_days: number;
  caveats: string[];
}

export interface TransferableStockResponse {
  canonical_sku: string;
  excluded_branch: string | null;
  holders: {
    canonical_branch: string;
    usable_qty: number;
    closing_qty: number;
    stock_class: string | null;
  }[];
  total_holders: number;
  total_usable_units: number;
  caveat: string;
}

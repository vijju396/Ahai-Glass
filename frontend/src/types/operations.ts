/**
 * Monitoring, scenario and settings response types.
 *
 * Note the shape of every monitoring measure: an `available`/`computable` flag
 * plus a `reason`. The UI must render "not yet computable" differently from
 * "measured, and fine" — they are different answers, and a page that showed
 * zero for both would be asserting a check that never ran.
 */

export interface Freshness {
  demand_history_end: string | null;
  demand_history_age_months: number | null;
  stock_snapshot_date: string;
  stock_snapshot_age_months: number | null;
  panel_built_at: string | null;
  panel_rows: number;
  dataset_ingested_at: string | null;
  note: string;
}

export interface DriftWindow {
  months: number;
  mean_monthly_demand: number | null;
  rows: number;
}

export interface DriftRow {
  scope_level: string;
  scope_key: string;
  earlier_mean_monthly_demand: number | null;
  recent_mean_monthly_demand: number | null;
  shift_pct: number | null;
}

export interface Drift {
  available: boolean;
  reason: string | null;
  window_months: number;
  recent_periods: string[];
  national: {
    earlier: DriftWindow;
    recent: DriftWindow;
    shift_pct: number | null;
  } | null;
  target_sources_recent: string[];
  target_sources_earlier: string[];
  target_source_changed: boolean;
  rows: DriftRow[];
  note: string | null;
}

export interface ChampionAgeRow {
  scope_kind: string;
  scope_key: string;
  champion_model_id: string;
  selection_source: string;
  selected_at: string | null;
  age_days: number | null;
  training_run_id: string;
  from_newest_training_run: boolean;
  beaten_by_baseline: boolean;
}

export interface ChampionAge {
  active_champions: number;
  newest_training_run_id: string | null;
  champions_from_older_runs: number;
  champions_beaten_by_a_baseline: number;
  rows: ChampionAgeRow[];
  note: string;
}

export interface DeteriorationRow {
  scope_level: string;
  scope_key: string;
  period: string;
  model_id: string | null;
  actual: number;
  point_forecast: number;
  absolute_error: number;
  accrued_wape: number | null;
  backtest_wape: number | null;
  deterioration_pct: number | null;
}

export interface Deterioration {
  /** False means it has not been checked — not that nothing deteriorated. */
  computable: boolean;
  reason: string | null;
  origin_period: string | null;
  forecast_periods: string[];
  observed_forecast_periods: string[];
  rows: DeteriorationRow[];
  note: string | null;
}

export interface MonitoringResponse {
  generated_at: string;
  freshness: Freshness;
  drift: Drift;
  champions: ChampionAge;
  deterioration: Deterioration;
  note: string;
}

export interface ScenarioRequest {
  name?: string;
  baseline_forecast_run_id?: string | null;
  demand_multiplier?: number;
  service_level?: number;
  lead_time_days?: number | null;
  review_period_days?: number | null;
  scope_level?: string;
  scope_keys?: string[] | null;
  period?: string | null;
  limit?: number;
}

export interface ScenarioRow {
  scope_key: string;
  period: string;
  horizon: number;
  model_id: string | null;
  baseline_point: number | null;
  scenario_point: number | null;
  baseline_quantile: number | null;
  scenario_quantile: number | null;
  baseline_recommended_order: number | null;
  scenario_recommended_order: number | null;
  unavailable_reason: string | null;
}

export interface ScenarioResponse {
  name: string;
  generated_at: string;
  baseline_forecast_run_id: string;
  baseline_origin_period: string;
  scope_level: string;
  period: string | null;
  levers: {
    demand_multiplier: number;
    service_level: number;
    lead_time_days: number | null;
    baseline_lead_time_days: number;
    review_period_days: number;
    baseline_review_period_days: number;
  };
  totals: {
    baseline_demand: number;
    scenario_demand: number;
    demand_delta: number;
    demand_delta_pct: number | null;
    baseline_order_quantity: number;
    scenario_order_quantity: number;
    order_delta: number;
    order_delta_pct: number | null;
  };
  rows: ScenarioRow[];
  rows_returned: number;
  rows_without_baseline: number;
  caveats: string[];
}

export interface SettingsResponse {
  app_name: string;
  app_version: string;
  environment: string;
  official_model_count: number;
  registered_model_ids: string[];
  baseline_method_ids: string[];
  min_history_profile: string;
  xgboost_training_profile: string;
  forecast_horizon_months: number;
  service_levels: number[];
  random_seed: number;
  max_local_series: number;
  local_series_selection: string;
  per_model_timeout_seconds: number;
  lstm_timeout_seconds: number;
  max_training_workers: number;
  review_period_days: number;
  default_lead_time_days: number;
  stock_snapshot_date: string;
  mlflow_enabled: boolean;
  mlflow_tracking_uri: string;
  database_dialect: string;
  expected_controls: Record<string, number>;
  notes: string[];
}

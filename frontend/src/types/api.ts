/**
 * Types mirroring the FastAPI Pydantic schemas.
 *
 * There is deliberately NO model-id union type and no model-name constant
 * anywhere in the frontend: model identity arrives from `GET /api/models` at
 * runtime. A second registry here would drift from the backend, which is
 * exactly the failure both reference projects avoided.
 */

export type ModelRunStatus =
  | 'queued'
  | 'preparing_data'
  | 'validating_eligibility'
  | 'training'
  | 'cross_validating'
  | 'generating_forecast'
  | 'saving_artifacts'
  | 'completed'
  | 'failed'
  | 'ineligible'
  | 'timed_out'
  | 'not_evaluated_budget'
  | 'cancelled';

export type EvaluationMode = 'rolling_origin' | 'holdout_fallback' | 'holdout_fast';

export type TargetSource = 'order' | 'sales_proxy';

export interface HealthComponent {
  name: string;
  status: 'ok' | 'degraded' | 'error';
  detail: string | null;
}

export interface HealthResponse {
  status: 'ok' | 'degraded' | 'error';
  app_name: string;
  version: string;
  environment: string;
  components: HealthComponent[];
}

export interface ModelDescriptor {
  model_id: string;
  display_name: string;
  rank: number;
  dependency_module: string;
  requires_exogenous: boolean;
  supports_pooled_training: boolean;
  uses_fast_holdout: boolean;
  min_required_history: number;
  min_history_reason: string | null;
  family: string;
}

export interface BaselineDescriptor {
  method_id: string;
  display_name: string;
}

export interface ModelRegistryResponse {
  models: ModelDescriptor[];
  baselines: BaselineDescriptor[];
  official_model_count: number;
  min_history_profile: string;
  xgboost_training_profile: string;
  notes: string[];
}

export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    details?: Record<string, unknown>;
    remediation?: string;
    correlation_id?: string;
  };
}

export interface Page<T> {
  items: T[];
  total: number;
  offset: number;
  limit: number;
}

// ---------------------------------------------------------------- datasets

export type IngestionStatus =
  | 'pending'
  | 'reading'
  | 'cleaning'
  | 'validating'
  | 'completed'
  | 'completed_with_failures'
  | 'failed'
  | 'cancelled';

export type ControlOutcome = 'pass' | 'fail' | 'warn' | 'not_evaluated';

export interface DatasetVersionSummary {
  id: string;
  version_number: number;
  status: IngestionStatus;
  stage_detail: string | null;
  progress_pct: number;
  started_at: string | null;
  finished_at: string | null;
  duration_seconds: number | null;
  controls_total: number;
  controls_failed: number;
  defects_total: number;
  failure_reason: string | null;
}

export interface Dataset {
  id: string;
  name: string;
  description: string | null;
  source_label: string;
  created_at: string;
  latest_version: DatasetVersionSummary | null;
}

export interface DatasetCreateResponse {
  dataset: Dataset;
  version_id: string;
  message: string;
}

export interface ColumnProfile {
  column_name: string;
  ordinal: number;
  detected_type: string;
  non_null_count: number;
  null_count: number;
  distinct_count: number | null;
  is_constant: boolean;
  is_pii: boolean;
  min_value: string | null;
  max_value: string | null;
  mean_value: number | null;
  sample_values: string[] | null;
  note: string | null;
}

export interface SourceFileProfile {
  role: string;
  filename: string;
  sheet_name: string | null;
  size_bytes: number;
  content_hash_sha256: string;
  row_count: number;
  column_count: number;
  read_seconds: number | null;
  columns: string[] | null;
  column_profiles: ColumnProfile[];
}

export interface DatasetProfileResponse {
  version: DatasetVersionSummary;
  source_files: SourceFileProfile[];
  pii_columns_excluded: string[];
  total_rows_read: number;
}

export interface ValidationControl {
  control_code: string;
  description: string;
  expected: string | null;
  measured: string | null;
  outcome: ControlOutcome;
  difference: string | null;
  tolerance_pct: number | null;
  remediation: string | null;
}

export interface DefectRecord {
  defect_code: string;
  title: string;
  severity: 'blocking' | 'corrected' | 'recorded';
  extent: string | null;
  affected_rows: number | null;
  source_role: string | null;
  rule_applied: string | null;
  fix_description: string;
  evidence: Record<string, unknown> | null;
}

export interface ServiceMeasures {
  total_ordered: number;
  total_despatched: number;
  net_shortfall: number;
  gross_positive_shortfall: number;
  over_delivered_qty: number;
  net_fill_rate: number | null;
  gross_shortfall_pct: number | null;
  lines_total: number;
  lines_fully_unserved: number;
  lines_with_shortfall: number;
  lines_over_delivered: number;
}

export interface LeadTime {
  count: number;
  median_days: number | null;
  p95_days: number | null;
  max_days: number | null;
  unparseable_dates: number;
  negative_excluded: number;
}

export interface ValidationResponse {
  version: DatasetVersionSummary;
  passed: boolean;
  controls: ValidationControl[];
  defects: DefectRecord[];
  service_measures: ServiceMeasures | null;
  lead_time: LeadTime | null;
  summary: Record<string, unknown>;
  blocking_message: string | null;
}

export interface ReconciliationFinding {
  finding_type: string;
  key_value: string;
  related_values: string[] | null;
  occurrence_count: number;
  note: string | null;
}

export interface MappingResponse {
  version: DatasetVersionSummary;
  canonical_sku_count: number;
  oracle_no_count: number;
  oracle_collision_count: number;
  canonical_disagreement_count: number;
  rows_missing_oracle: number;
  sku_prefixes: Record<string, number>;
  branch_universes: Record<string, number>;
  sku_universes: Record<string, number>;
  findings: ReconciliationFinding[];
  findings_total: number;
  canonical_key_rule: string;
  why_not_oracle_no: string;
}

// ------------------------------------------------------------- role mapping

export type SemanticRole =
  | 'time_column'
  | 'target_column'
  | 'series_identifier'
  | 'historical_driver'
  | 'future_known_driver'
  | 'static_attribute'
  | 'inventory'
  | 'capacity'
  | 'supply'
  | 'excluded_pii'
  | 'ignored';

export type MappingState = 'draft' | 'confirmed' | 'superseded';

export interface RoleAssignment {
  source_role: string;
  column_name: string;
  ordinal: number;
  role: SemanticRole;
  is_suggested: boolean;
  confidence: number | null;
  rationale: string | null;
  aggregation: string | null;
  imputation: string | null;
  notes: string | null;
}

export interface RuleResult {
  rule_code: string;
  severity: 'blocking' | 'warning';
  message: string;
  columns: string[] | null;
  remediation: string | null;
}

export interface MappingDetail {
  id: string;
  dataset_version_id: string;
  version_number: number;
  state: MappingState;
  frequency: string;
  timezone: string;
  forecast_horizon: number;
  aggregation_method: string;
  duplicate_handling: string;
  missing_timestamp_policy: string;
  target_imputation_policy: string;
  driver_imputation_policy: string;
  confirmed_at: string | null;
  confirmed_by: string | null;
  superseded_at: string | null;
  notes: string | null;
  created_at: string;
  assignments: RoleAssignment[];
  rule_results: RuleResult[];
  role_counts: Record<string, number>;
  unreviewed_count: number;
  blocking_count: number;
  warning_count: number;
  can_confirm: boolean;
  future_known_columns: string[];
  not_future_known_reasons: Record<string, string>;
}

export interface PreprocessingRun {
  id: string;
  status: string;
  stage_detail: string | null;
  progress_pct: number;
  started_at: string | null;
  finished_at: string | null;
  duration_seconds: number | null;
  failure_reason: string | null;
  branch_dim_rows: number;
  product_dim_rows: number;
  order_fact_rows: number;
  sales_fact_rows: number;
  fact_rows: number;
  stock_position_rows: number;
  distinct_series: number;
  distinct_periods: number;
  artifacts: Record<string, string> | null;
  summary: Record<string, unknown> | null;
}

// -------------------------------------------------------------- panel build

export interface PanelBuild {
  id: string;
  preprocessing_run_id: string;
  status: string;
  stage_detail: string | null;
  progress_pct: number;
  started_at: string | null;
  finished_at: string | null;
  duration_seconds: number | null;
  failure_reason: string | null;
  training_cut_period: string | null;
  horizons: string;
  panel_rows: number;
  series_count: number;
  period_count: number;
  observed_rows: number;
  materialised_zero_rows: number;
  censored_rows: number;
  training_rows: number;
  scoring_rows: number;
  feature_count: number;
  artifacts: Record<string, string> | null;
  summary: Record<string, unknown> | null;
}

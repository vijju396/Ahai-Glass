import { getJson, postJson } from '@/api/client';

export interface FilterOption {
  value: string;
  label: string;
  rows: number;
  units: number;
}

export interface AnalyticsFilters {
  workspace_scope?: WorkspaceScope;
  branches: FilterOption[];
  product_groups: FilterOption[];
  value_classes: FilterOption[];
  regions: FilterOption[];
  period_range: { min: string; max: string } | null;
  periods: string[];
  available_grains: string[];
  grain_note: string;
  series_count: number;
  panel_build_id: string;
  training_cut_period: string | null;
}

export interface TrendPoint {
  period: string;
  demand_units: number;
  demand_value: number;
  despatched_units: number | null;
  shortfall_units: number;
  fill_rate_pct: number | null;
  order_share_pct: number | null;
  proxy_share_pct: number | null;
  censored_share_pct: number | null;
  price_per_unit: number | null;
  rows: number;
  despatch_rows_excluded: number;
}

export interface DimensionRow {
  name: string;
  sku?: string;
  branch?: string;
  product_group?: string;
  value_class?: string;
  demand_units: number;
  demand_value: number;
  despatched_units: number | null;
  shortfall_units: number;
  sku_count: number;
  series_count: number;
}

export interface AnalyticsSummary {
  workspace_scope?: WorkspaceScope;
  empty: boolean;
  reason?: string;
  scope: Record<string, string | null>;
  window: { start: string; end: string; periods: number };
  available_grains: string[];
  grain_note: string;
  kpis: {
    demand_value: number;
    demand_units: number;
    shortfall_units: number;
    fill_rate_pct: number | null;
    order_share_pct: number | null;
    censored_rows: number;
    series_count: number;
    branch_count: number;
    sku_count: number;
    rows: number;
    despatch_rows_excluded_from_fill_rate: number;
  };
  trend: TrendPoint[];
  by_branch: DimensionRow[];
  by_product_group: DimensionRow[];
  by_value_class: DimensionRow[];
  /** Per SKU. The axis this workspace is defined on. */
  by_sku: DimensionRow[];
  /** Lam / Sidelite / Backlite — the product axis the sample was chosen on. */
  by_glass_type: DimensionRow[];
  by_vehicle_category: DimensionRow[];
  /** Replacement glass skews to older vehicles; this is where that shows. */
  by_vehicle_age: DimensionRow[];
  branch_by_group: {
    groups: string[];
    data: Array<Record<string, string | number>>;
    limit: number;
    total_branches: number;
  };
  branch_over_time: {
    names: string[];
    data: Array<Record<string, string | number>>;
    limit: number;
    total_branches: number;
  };
  seasonality: Array<{ month: number; name: string; mean_demand_units: number; observations: number }>;
  concentration: Array<{ branch: string; sku_count: number; top5_share_pct: number; demand_units: number }>;
  coverage: Array<{
    branch: string;
    observed_months: number;
    window_months: number;
    coverage_pct: number | null;
    demand_units: number;
  }>;
  notes: string[];
  panel_build_id: string;
}

export interface ExceptionRow {
  type: string;
  label: string;
  severity: string;
  definition: string;
  measure: string;
  series_id: string;
  branch: string;
  sku: string;
  product_group: string;
  value_class: string;
  units: number;
  occurrences: number;
}

export interface ExceptionsPayload {
  workspace_scope?: WorkspaceScope;
  empty: boolean;
  reason?: string;
  scope: Record<string, string | null>;
  types: Record<string, { label: string; severity: string; definition: string; measure: string }>;
  recent_window_months: number;
  kpis: {
    total_lines: number;
    critical_lines: number;
    high_lines: number;
    medium_lines: number;
    short_despatch_lines: number;
    zero_stock_live_demand_lines: number;
    units_affected: number;
  };
  by_severity: Array<{ name: string; severity: string; lines: number }>;
  by_type: Array<{ type: string; name: string; severity: string; lines: number; units: number }>;
  by_branch: Array<{ name: string; branch: string; lines: number; units: number }>;
  by_product_group: Array<{ name: string; product_group: string; lines: number; units: number }>;
  top_lines: ExceptionRow[];
  rows: ExceptionRow[];
  total_rows: number;
  notes: string[];
}

export interface ScorecardBranch {
  branch: string;
  rank: number;
  score: number | null;
  metric_values: Record<string, number | null>;
  score_components: Record<string, number | null>;
  off_target: string[];
  worst_metric: string | null;
  demand_units: number;
  demand_value: number;
  sku_count: number;
}

export interface BranchScorecard {
  empty: boolean;
  scales: Record<
    string,
    { good: number; poor: number; target: number; higher_is_better: boolean; unit: string }
  >;
  labels: Record<string, string>;
  branches: ScorecardBranch[];
  total_branches?: number;
  note?: string;
}

export interface WorkspaceScope {
  restricted: boolean;
  branches: string[] | null;
  branch_count: number | null;
  total_branches: number | null;
  skus: string[] | null;
  sku_count: number | null;
  total_skus: number | null;
  source: string;
  detail: string;
  note: string | null;
}

export interface AnalyticsQuery {
  branch?: string;
  sku?: string;
  product_group?: string;
  value_class?: string;
  start_period?: string;
  end_period?: string;
  grain?: string;
}

export const analyticsKeys = {
  filters: ['analytics', 'filters'] as const,
  summary: (q: AnalyticsQuery) => ['analytics', 'summary', q] as const,
  exceptions: (q: AnalyticsQuery) => ['analytics', 'exceptions', q] as const,
  scorecard: (q: AnalyticsQuery) => ['analytics', 'scorecard', q] as const,
};

export function fetchAnalyticsFilters(): Promise<AnalyticsFilters> {
  return getJson<AnalyticsFilters>('/analytics/filters');
}

export function fetchAnalyticsSummary(query: AnalyticsQuery): Promise<AnalyticsSummary> {
  return getJson<AnalyticsSummary>('/analytics/summary', query as Record<string, unknown>);
}

export function fetchExceptions(query: AnalyticsQuery): Promise<ExceptionsPayload> {
  return getJson<ExceptionsPayload>('/analytics/exceptions', query as Record<string, unknown>);
}

export function fetchBranchScorecard(query: AnalyticsQuery): Promise<BranchScorecard> {
  return getJson<BranchScorecard>('/analytics/branch-scorecard', query as Record<string, unknown>);
}

export interface LeadTimeBranch {
  branch: string;
  region: string;
  avg_days: number | null;
  std_days: number | null;
  transit_days: number | null;
  cv_pct: number | null;
  handling_days: number | null;
  holds_stock: boolean;
}

export interface LeadTimePayload {
  empty: boolean;
  reason?: string;
  kpis: {
    branches: number;
    branches_with_a_usable_lead_time: number;
    median_avg_days: number | null;
    p95_avg_days: number | null;
    max_avg_days: number | null;
    median_std_days: number | null;
    branches_zero_variability: number;
    anomaly_count: number;
  };
  by_branch: LeadTimeBranch[];
  least_reliable: LeadTimeBranch[];
  distribution: Array<{ bucket: string; branches: number }>;
  anomalies: Array<LeadTimeBranch & { reason: string }>;
  zero_variability_branches: string[];
  notes: string[];
}

export const leadTimeKeys = { all: ['analytics', 'lead-time'] as const };

export function fetchLeadTime(worst = 8): Promise<LeadTimePayload> {
  return getJson<LeadTimePayload>('/analytics/lead-time', { worst });
}

// ----------------------------------------------------------------------
// Assistant
// ----------------------------------------------------------------------

export interface AssistantStatus {
  enabled: boolean;
  configured: boolean;
  model: string;
  steps: string[];
  notes: string[];
  suggested_questions: string[];
}

export interface AssistantChart {
  type: 'line' | 'bar' | 'pie';
  title: string;
  x_key: string;
  series: Array<{ key: string; label: string; color?: string | null }>;
  data: Array<Record<string, string | number>>;
}

export interface AssistantScope {
  branch: string | null;
  sku: string | null;
  period: string | null;
  resolved_from: string | null;
}

export interface AssistantAnswer {
  question: string;
  answer: string;
  tools_used: string[];
  routed_by: string;
  answered_by: string;
  facts: Record<string, unknown>;
  chart: AssistantChart | null;
  scope: AssistantScope;
  model: string | null;
  provider_error: string | null;
}

export interface AssistantTurn {
  role: 'user' | 'assistant';
  content: string;
}

export const assistantKeys = {
  status: ['assistant', 'status'] as const,
};

export function fetchAssistantStatus(): Promise<AssistantStatus> {
  return getJson<AssistantStatus>('/assistant/status');
}

export function askAssistant(body: {
  question: string;
  history: AssistantTurn[];
  current_scope: AssistantScope | null;
}): Promise<AssistantAnswer> {
  return postJson<AssistantAnswer>('/assistant/ask', body);
}

// ----------------------------------------------------------------------
// AI recommendations
// ----------------------------------------------------------------------

export interface Recommendation {
  title: string;
  /** critical | high | medium */
  severity: string;
  observation: string;
  explanation: string;
  next_step: string | null;
  /** The figures the item rests on. An item with none was dropped server-side. */
  evidence: string[];
  source: string | null;
  /** The page a reader can check the figures against. */
  verify_on: string | null;
}

export interface RecommendationsPayload {
  items: Recommendation[];
  /** openai | deterministic_no_key | deterministic_after_provider_error */
  answered_by: string;
  sources: string[];
  facts: Record<string, unknown>;
  caveats: string[];
  temperature: number;
  model: string | null;
  provider_error: string | null;
}

export const recommendationKeys = { all: ['assistant', 'recommendations'] as const };

export function fetchRecommendations(): Promise<RecommendationsPayload> {
  return getJson<RecommendationsPayload>('/assistant/recommendations');
}

// ----------------------------------------------------------------------
// Series options (branch x SKU), for the per-series filters
// ----------------------------------------------------------------------

export interface SeriesOption {
  series_id: string;
  canonical_branch?: string;
  canonical_sku?: string;
  branch?: string;
  sku?: string;
  demand_units?: number;
  observed_months?: number;
}

export const seriesKeys = {
  options: (branch?: string) => ['analytics', 'series', branch ?? 'all'] as const,
};

export function fetchSeriesOptions(branch?: string): Promise<{ items: SeriesOption[] }> {
  return getJson<{ items: SeriesOption[] }>('/analytics/series', { branch, limit: 1000 });
}

// ----------------------------------------------------------------------
// How training works
// ----------------------------------------------------------------------

export interface TrainingModelRow {
  model_id: string;
  display_name: string;
  family: string | null;
  requires_exogenous: boolean;
  supports_pooled_training: boolean;
  uses_fast_holdout: boolean;
  min_history: Record<string, number>;
  min_history_active: number;
  parameters: Record<string, unknown>;
  features: Record<string, unknown>;
  dependency: string | null;
}

export interface TrainingOrigin {
  name: string;
  fold_index: number;
  train_start: string;
  train_end: string;
  validation_start: string;
  validation_end: string;
  train_months: number;
}

export interface TrainingMetric {
  key: string;
  label: string;
  unit: string;
  lower_is_better: boolean;
  definition: string;
  caveat: string | null;
}

export interface TrainingExplain {
  workspace_scope?: WorkspaceScope;
  validation: {
    method: string;
    why: string;
    horizon_months: number;
    min_train_periods: number;
    panel_window: { start: string; end: string };
    mandated_train_ends: string[];
    origins: TrainingOrigin[];
    fold_fitted_preprocessing: string;
    exogenous_rule: string;
  };
  models: TrainingModelRow[];
  model_count: number;
  metrics: TrainingMetric[];
  selection: {
    primary_metric: string;
    primary_metric_choices: string[];
    default_primary_metric: string;
    tie_breaks: string[];
    why_bias_second: string;
    min_validation_points: number;
    min_test_point_share: number;
    baselines_never_champion: boolean;
    baselines: Array<{ model_id: string; rule: string }>;
  };
  tuning: {
    summary: string;
    search_inside_folds: Array<{ model_id: string; what: string }>;
    fixed_settings: Record<string, unknown>;
    not_tuned: string[];
  };
  status_vocabulary: Array<{ status: string; meaning: string }>;
  active_run: {
    id: string;
    status: string;
    created_at: string;
    duration_seconds: number | null;
    tiers: string[];
    min_history_profile: string;
    xgboost_training_profile: string;
    max_local_series: number;
    local_series_selection: string | null;
    per_model_timeout_seconds: number | null;
    lstm_timeout_seconds: number | null;
    restriction: Record<string, unknown> | null;
    model_run_statuses: Record<string, number>;
    series_evaluated: number;
  } | null;
  notes: string[];
}

export const trainingExplainKeys = { all: ['training', 'explain'] as const };

export function fetchTrainingExplain(): Promise<TrainingExplain> {
  return getJson<TrainingExplain>('/training/explain');
}

// ----------------------------------------------------------------------
// Demand drift
// ----------------------------------------------------------------------

export interface DriftPoint {
  period: string;
  shift_pct: number;
  recent_mean: number;
  baseline_mean: number;
  /** The window spans the Apr 2025 source change, so part of the shift is a
   *  change of measurement rather than of demand. */
  straddles_measurement_change: boolean;
}

export interface DriftProjection {
  projectable: boolean;
  reason?: string;
  already_crossed?: boolean;
  months_ahead?: number;
  expected_period?: string;
  basis?: string;
  points_used?: number;
  slope_pct_per_month?: number;
  r_squared?: number | null;
  current_shift_pct?: number;
  threshold_pct?: number;
  from_period?: string;
}

export interface DriftPayload {
  empty: boolean;
  reason?: string;
  scope: string;
  window_months?: number;
  threshold_pct?: number;
  measurement_change?: string;
  points?: DriftPoint[];
  latest?: {
    period: string;
    shift_pct: number;
    recent_mean: number;
    baseline_mean: number;
    is_material: boolean;
  };
  projection?: DriftProjection;
  caveats?: string[];
  explanation?: {
    text: string;
    /** openai | deterministic_no_key | deterministic_after_provider_error
     *  | deterministic_after_unusable_reply */
    answered_by: string;
    model: string | null;
    rejected_because?: string;
    provider_error?: string;
  };
  workspace_scope?: WorkspaceScope;
}

export const driftKeys = {
  scope: (branch?: string, sku?: string) => ['analytics', 'drift', branch ?? '', sku ?? ''] as const,
};

export function fetchDrift(branch?: string, sku?: string): Promise<DriftPayload> {
  return getJson<DriftPayload>('/analytics/drift', { branch, sku });
}

// Forecast impact: measured error reduction, and the benefit projected from it.
//
// The two halves are deliberately separate types. `measured` is reproducible
// from stored folds; `projections` depend on assumptions the viewer sets and
// are not observations. Keeping them apart in the type stops a component
// rendering a projected rupee figure with the authority of a measured one.

export interface ImpactHorizon {
  horizon: number;
  champion_wape: number | null;
  baseline_wape: number | null;
  reduction_pct: number | null;
  points: number;
  volume: number;
  reportable: boolean;
}

export interface ImpactProjection {
  horizon: number;
  months: number;
  unfilled_units_in_window: number;
  recoverable_units: number;
  recovered_revenue: number;
  recovered_margin: number;
  safety_stock_released: number;
  reduction_pct: number | null;
  measured: boolean;
}

export interface ImpactAssumptions {
  recovery_share: number;
  margin_pct: number;
  stock_efficiency_share: number;
}

export interface ImpactPayload {
  empty?: boolean;
  reason?: string;
  basis: string;
  training_run_id: string | null;
  baseline_model_id?: string;
  scope_kind?: string;
  measured: {
    horizons: ImpactHorizon[];
    series_count: number;
    beaten_by_baseline: number;
    history_months: number;
  };
  exposure: {
    ordered_units: number;
    unfilled_units: number;
    unfilled_rows: number;
    demand_value: number;
    fill_rate_pct: number | null;
    series_count: number;
    value_per_unit: number | null;
  } | null;
  projections: ImpactProjection[];
  assumptions: ImpactAssumptions;
  assumption_labels: Record<string, string>;
  caveats: string[];
  workspace_scope?: WorkspaceScope;
}

export const impactKeys = {
  all: (a: Partial<ImpactAssumptions>) =>
    ['analytics', 'impact', a.recovery_share, a.margin_pct, a.stock_efficiency_share] as const,
};

export function fetchImpact(a: Partial<ImpactAssumptions> = {}): Promise<ImpactPayload> {
  return getJson<ImpactPayload>('/analytics/impact', {
    recovery_share: a.recovery_share,
    margin_pct: a.margin_pct,
    stock_efficiency_share: a.stock_efficiency_share,
  });
}

// How far the sampled SKUs distort the composition charts.
//
// The workspace's twenty SKUs were stratified so every category appears at
// all, which makes their volume mix non-proportional to the branches they came
// from. These figures let a composition panel say so on itself.

export interface MixLevel {
  level: string;
  sample_pct: number;
  branch_pct: number;
  gap_points: number;
  ratio: number | null;
  material: boolean;
  direction: 'over' | 'under';
}

export interface MixAxis {
  column: string;
  label: string;
  comparable: boolean;
  reason: string | null;
  levels: MixLevel[];
  max_gap_points: number;
  material: boolean;
  /** Null when the sample matches its branches closely enough to stay quiet. */
  caveat: string | null;
}

export interface SampleMixPayload {
  restricted: boolean;
  reason?: string;
  axes: Record<string, MixAxis>;
  sample_skus?: number | null;
  reference_skus?: number | null;
  material_axis_count?: number;
  worst_axis?: string | null;
  basis?: string;
  why?: string;
  workspace_scope?: WorkspaceScope;
}

export const sampleMixKeys = {
  all: ['analytics', 'sample-mix'] as const,
};

export function fetchSampleMix(): Promise<SampleMixPayload> {
  return getJson<SampleMixPayload>('/analytics/sample-mix');
}

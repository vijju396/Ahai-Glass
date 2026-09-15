/**
 * API-shaped fixtures for the training, leaderboard, forecast and inventory
 * pages.
 *
 * These name model IDs deliberately: a test asserting that all thirteen render
 * is the point of the one-registry rule, and `no-duplicate-registry.test.ts`
 * exempts test files for exactly that reason.
 *
 * The metric values are the ones measured on the real AIS panel (national
 * scope, two rolling origins), so a test that expects a particular ordering is
 * asserting against something the system actually produced rather than against
 * invented numbers.
 */
import type {
  ChampionSelection,
  ComparisonPoint,
  DiagnosticsResponse,
  ForecastRun,
  LeaderboardResponse,
  LeaderboardRow,
  RecommendationsResponse,
  SeriesForecastResponse,
  SupplyOverviewResponse,
  TrainingRunDetail,
  TrainingRunSummary,
} from '@/types/phase7';

/** Measured on the real national aggregate. */
const MEASURED: [string, string, number | null, string, string][] = [
  ['var_exog', 'VAR with exogenous variables', 4.578, 'completed', 'rolling_origin'],
  ['sarimax_exog', 'SARIMAX with exogenous variables', 6.192, 'completed', 'rolling_origin'],
  ['var', 'VAR', 9.603, 'completed', 'rolling_origin'],
  ['xgboost_exog', 'XGBoost with exogenous variables', 10.603, 'completed', 'rolling_origin'],
  ['xgboost', 'XGBoost', 11.156, 'completed', 'rolling_origin'],
  ['sarimax', 'SARIMAX', 13.157, 'completed', 'rolling_origin'],
  ['lstm', 'LSTM', 14.661, 'completed', 'holdout_fast'],
  ['auto_arima', 'Auto ARIMA', null, 'ineligible', 'holdout_fast'],
  ['auto_arima_exog', 'Auto ARIMA with exogenous variables', null, 'ineligible', 'holdout_fast'],
  ['exp_additive', 'Exponential Smoothing Additive', null, 'ineligible', 'rolling_origin'],
  ['exp_additive_damped', 'Exponential Smoothing Additive Damped', null, 'ineligible', 'rolling_origin'],
  ['exp_multiplicative', 'Exponential Smoothing Multiplicative', null, 'ineligible', 'rolling_origin'],
  [
    'exp_multiplicative_damped',
    'Exponential Smoothing Multiplicative Damped',
    null,
    'ineligible',
    'rolling_origin',
  ],
];

const BASELINES: [string, number][] = [
  ['ma6', 9.939],
  ['ma3', 10.314],
  ['naive', 11.835],
  ['seasonal_naive', 11.835],
];

function row(
  modelId: string,
  displayName: string,
  wape: number | null,
  status: string,
  mode: string,
  rank: number | null,
): LeaderboardRow {
  return {
    model_id: modelId,
    display_name: displayName,
    status,
    is_baseline: false,
    evaluation_mode: mode,
    rank,
    legacy_rank: wape === null ? null : rank,
    is_champion: rank === 1,
    is_challenger: rank === 2,
    ranked: rank !== null,
    exclusion: rank === null ? 'not_completed' : null,
    exclusion_reason:
      rank === null
        ? 'The model did not complete, so it has no metric to rank.'
        : null,
    comparability_note: null,
    wape,
    mae: wape === null ? null : wape * 1650,
    rmse: wape === null ? null : wape * 1900,
    mape: wape === null ? null : wape + 2,
    accuracy: wape === null ? null : 100 - (wape + 2),
    smape: wape === null ? null : wape + 1,
    mase: wape === null ? null : wape / 10,
    bias: wape === null ? null : wape / 4,
    bias_abs: wape === null ? null : wape / 4,
    legacy_mape: wape === null ? null : wape + 2,
    legacy_valid: wape !== null,
    validation_points: wape === null ? 0 : mode === 'holdout_fast' ? 6 : 10,
    distinct_test_points: wape === null ? 0 : mode === 'holdout_fast' ? 6 : 10,
    origins_completed: wape === null ? 0 : mode === 'holdout_fast' ? 1 : 2,
    origins_total: mode === 'holdout_fast' ? 1 : 2,
    failure_reason:
      status === 'ineligible'
        ? `${displayName} needs at least 24 training observations; this window has 22.`
        : null,
    model_run_id: `mr-${modelId}`,
  };
}

export function leaderboardFixture(
  overrides: Partial<LeaderboardResponse> = {},
): LeaderboardResponse {
  let rank = 0;
  const rows: LeaderboardRow[] = MEASURED.map(([id, name, wape, status, mode]) => {
    if (wape === null) return row(id, name, wape, status, mode, null);
    rank += 1;
    return row(id, name, wape, status, mode, rank);
  });
  const baselineRows: LeaderboardRow[] = BASELINES.map(([id, wape]) => ({
    ...row(id, id, wape, 'completed', 'rolling_origin', null),
    is_baseline: true,
    is_champion: false,
    is_challenger: false,
    exclusion: 'is_baseline',
    exclusion_reason:
      'Naive, seasonal-naive, MA3 and MA6 are non-registry baselines. They are reported for comparison and can never be champion.',
  }));

  return {
    training_run_id: 'train-0001',
    panel_build_id: 'panel-0001',
    scope_level: 'national',
    scope_key: 'NATIONAL',
    rows: [...rows, ...baselineRows],
    champion_model_id: 'var_exog',
    challenger_model_id: 'sarimax_exog',
    legacy_champion_model_id: 'var_exog',
    best_baseline_model_id: 'ma6',
    best_baseline_wape: 9.939,
    beaten_by_baseline: false,
    skill_vs_best_baseline: {
      improvement_pct: 53.94,
      champion_better: true,
      reason: null,
    },
    ranked_count: 7,
    excluded_count: 10,
    models_missing: [],
    baselines_present: ['ma3', 'ma6', 'naive', 'seasonal_naive'],
    notes: [
      'This ranking mixes evaluation modes (holdout_fast, rolling_origin). Point counts differ by mode (docs/DECISIONS.md D-037) and are shown on every row.',
    ],
    origins: { primary_validation: { shares: { order: 100 } } },
    active_selection: championFixture(),
    ...overrides,
  };
}

export function comparisonFixture(): ComparisonPoint[] {
  return [
    ...MEASURED.map(([id, name, wape, status]) => ({
      model_id: id,
      display_name: name,
      wape,
      wape_pct: wape,
      status,
      is_baseline: false,
      is_champion: id === 'var_exog',
      exclusion: wape === null ? 'not_completed' : null,
      exclusion_reason:
        wape === null ? 'The model did not complete, so it has no metric to rank.' : null,
    })),
    ...BASELINES.map(([id, wape]) => ({
      model_id: id,
      display_name: id,
      wape,
      wape_pct: wape,
      status: 'completed',
      is_baseline: true,
      is_champion: false,
      exclusion: 'is_baseline',
      exclusion_reason: 'Non-registry baseline.',
    })),
  ];
}

export function championFixture(
  overrides: Partial<ChampionSelection> = {},
): ChampionSelection {
  return {
    id: 'champ-0001',
    training_run_id: 'train-0001',
    scope_kind: 'overall',
    scope_key: 'NATIONAL',
    evaluated_scope_level: 'national',
    champion_model_id: 'var_exog',
    champion_display_name: 'VAR with exogenous variables',
    challenger_model_id: 'sarimax_exog',
    legacy_champion_model_id: 'var_exog',
    champion_wape: 4.578,
    champion_mae: 7558,
    champion_bias: 1.1,
    champion_validation_points: 10,
    champion_evaluation_mode: 'rolling_origin',
    best_baseline_model_id: 'ma6',
    best_baseline_wape: 9.939,
    beaten_by_baseline: false,
    selection_source: 'automatic',
    reason: null,
    actor: null,
    is_active: true,
    superseded_at: null,
    supersedes_id: null,
    restored_from_id: null,
    ranked_count: 7,
    excluded_count: 10,
    notes: [],
    created_at: '2026-09-09T10:00:00Z',
    ...overrides,
  };
}

export function trainingRunFixture(
  overrides: Partial<TrainingRunSummary> = {},
): TrainingRunSummary {
  return {
    id: 'train-0001',
    panel_build_id: 'panel-0001',
    status: 'completed',
    stage_detail: 'Complete',
    progress_pct: 100,
    created_at: '2026-09-09T09:00:00Z',
    started_at: '2026-09-09T09:00:05Z',
    finished_at: '2026-09-09T09:04:41Z',
    duration_seconds: 275.8,
    failure_reason: null,
    cancelled_at: null,
    tiers: 'aggregate',
    min_history_profile: 'reference',
    xgboost_training_profile: 'fast',
    max_local_series: 0,
    local_series_selection: 'value',
    estimated_seconds: 424.5,
    total_budget_seconds: null,
    per_model_timeout_seconds: 120,
    lstm_timeout_seconds: 300,
    series_requested: 69,
    series_evaluated: 69,
    model_runs_total: 1173,
    model_runs_completed: 738,
    model_runs_ineligible: 435,
    model_runs_failed: 0,
    model_runs_timed_out: 0,
    model_runs_not_evaluated: 0,
    residuals_recorded: 5148,
    mlflow_run_id: null,
    estimate: {
      tiers: [
        {
          tier: 'aggregate',
          series: 69,
          origins: 2,
          models: MEASURED.map(([id]) => id),
          fits: 2139,
          seconds: 1698,
          seconds_upper: 5092.8,
          notes: [
            '4 baselines add 552 evaluations at negligible cost - they are arithmetic on the training window',
          ],
        },
      ],
      workers: 4,
      total_fits: 2139,
      estimated_seconds: 424.5,
      estimated_seconds_upper: 1273.2,
      estimated_human: '7.1 min',
      estimated_human_upper: '21.2 min',
      provenance:
        'per-model fit times measured in this project on a real 28-month AIS series (Phase 5) and on two-origin backtests (Phase 6).',
      hard_timeout_models: [],
    },
    origins: null,
    summary: null,
    warnings: null,
    ...overrides,
  };
}

export function trainingDetailFixture(
  overrides: Partial<TrainingRunDetail> = {},
): TrainingRunDetail {
  const modelRuns = MEASURED.map(([id, name, wape, status, mode]) => ({
    id: `mr-${id}`,
    training_run_id: 'train-0001',
    tier: 'aggregate',
    scope_level: 'national',
    scope_key: 'NATIONAL',
    segment: 'smooth',
    model_id: id,
    display_name: name,
    is_baseline: false,
    status,
    evaluation_mode: mode,
    failure_reason:
      status === 'ineligible'
        ? `${name} needs at least 24 training observations; this window has 22.`
        : null,
    eligibility: null,
    seasonal_period: null,
    origins_completed: wape === null ? 0 : mode === 'holdout_fast' ? 1 : 2,
    origins_total: mode === 'holdout_fast' ? 1 : 2,
    validation_points: wape === null ? 0 : mode === 'holdout_fast' ? 6 : 10,
    total_test_points: wape === null ? 0 : 12,
    duplicate_test_points: wape === null ? 0 : 2,
    mae: wape === null ? null : wape * 1650,
    rmse: null,
    wape,
    mape: null,
    accuracy: null,
    smape: null,
    mase: null,
    bias: null,
    bias_abs: null,
    naive_mae: null,
    legacy_mape: null,
    legacy_wape: null,
    legacy_mae: null,
    legacy_valid: false,
    zero_actual_points: 0,
    censored_points: 0,
    negative_predictions: 0,
    max_abs_prediction: null,
    fit_seconds: 1.2,
    predict_seconds: 0.02,
    artifact_path: null,
    mlflow_run_id: null,
    parameters: null,
    features: null,
    origins: null,
  }));

  return {
    run: trainingRunFixture(),
    status_counts: [
      { status: 'completed', count: 738 },
      { status: 'ineligible', count: 435 },
    ],
    models_missing: [],
    model_runs: modelRuns,
    model_runs_returned: modelRuns.length,
    model_runs_matching: modelRuns.length,
    offset: 0,
    limit: 500,
    ...overrides,
  };
}

export function diagnosticsFixture(
  overrides: Partial<DiagnosticsResponse> = {},
): DiagnosticsResponse {
  return {
    training_run_id: 'train-0001',
    model_id: 'var_exog',
    display_name: 'VAR with exogenous variables',
    is_baseline: false,
    scope_level: 'national',
    scope_key: 'NATIONAL',
    status: 'completed',
    evaluation_mode: 'rolling_origin',
    failure_reason: null,
    eligibility: null,
    metrics: { wape: 4.578, mae: 7558, validation_points: 10 },
    parameters: null,
    features: null,
    fit_seconds: 1.2,
    predict_seconds: 0.02,
    folds: [
      {
        origin_name: 'primary',
        fold_index: 0,
        train_end_period: '2025-09',
        train_rows: 18,
        status: 'completed',
        seasonal_period: null,
        failure_reason: null,
        eligibility: null,
        fit_seconds: 0.6,
        predict_seconds: 0.01,
        validation_periods: ['2025-10', '2025-11'],
        metrics: null,
        legacy_metrics: null,
        negative_predictions: 0,
        point_count: 2,
      },
    ],
    points: [
      {
        origin_name: 'primary',
        fold_index: 0,
        period: '2025-10',
        horizon: 1,
        actual: 143953,
        predicted: 154204,
        residual: 10251,
      },
      {
        origin_name: 'primary',
        fold_index: 0,
        period: '2025-11',
        horizon: 2,
        actual: 156772,
        predicted: 152644,
        residual: -4128,
      },
    ],
    horizon_performance: [
      { horizon: 1, points: 1, mae: 10251, wape: 7.121, bias: 10251, zero_actual_points: 0 },
      { horizon: 2, points: 1, mae: 4128, wape: 2.633, bias: -4128, zero_actual_points: 0 },
    ],
    diagnostics_available: true,
    unavailable_reason: null,
    ...overrides,
  };
}

export function forecastRunFixture(overrides: Partial<ForecastRun> = {}): ForecastRun {
  return {
    id: 'fc-0001',
    training_run_id: 'train-0001',
    panel_build_id: 'panel-0001',
    status: 'completed',
    stage_detail: 'Complete',
    progress_pct: 100,
    created_at: '2026-09-09T11:00:00Z',
    started_at: '2026-09-09T11:00:01Z',
    finished_at: '2026-09-09T11:02:00Z',
    duration_seconds: 119,
    failure_reason: null,
    origin_period: '2026-07',
    horizons: '1,2,3,4,5,6',
    requested_reconciliation: 'mint_variance',
    reconciliation_method: 'mint_variance',
    reconciliation_fallback_from: null,
    reconciliation_fallback_reason: null,
    shrinkage_intensity: null,
    coherent: true,
    max_incoherence: 0,
    negatives_clipped: 0,
    quantile_crossings_corrected: 0,
    series_forecast: 66,
    rows_written: 396,
    rows_unavailable: 18,
    summary: null,
    warnings: null,
    ...overrides,
  };
}

export function seriesForecastFixture(
  overrides: Partial<SeriesForecastResponse> = {},
): SeriesForecastResponse {
  // `noUncheckedIndexedAccess` widens an indexed read to `| undefined`, and the
  // fixture's arrays are the same fixed length by construction. Pairing them
  // makes that explicit rather than asserting it away.
  const points: [string, number][] = [
    ['2026-08', 187503],
    ['2026-09', 183372],
    ['2026-10', 179890],
    ['2026-11', 177965],
    ['2026-12', 179156],
    ['2027-01', 172190],
  ];
  return {
    forecast_run_id: 'fc-0001',
    training_run_id: 'train-0001',
    scope_level: 'national',
    scope_key: 'NATIONAL',
    origin_period: '2026-07',
    history: [
      { period: '2026-06', actual: 193349, is_censored: false, target_source: 'order' },
      { period: '2026-07', actual: 200686, is_censored: false, target_source: 'order' },
    ],
    history_unavailable_reason: null,
    forecasts: points.map(([period, point], index) => ({
      id: `fr-${index}`,
      forecast_run_id: 'fc-0001',
      scope_level: 'national',
      scope_key: 'NATIONAL',
      canonical_branch: null,
      canonical_sku: null,
      region: null,
      demand_segment: 'smooth',
      value_class: null,
      period,
      horizon: index + 1,
      model_id: 'var_exog',
      model_display_name: 'VAR with exogenous variables',
      model_run_id: 'mr-var_exog',
      champion_selection_id: 'champ-0001',
      forecast_source: 'champion',
      point_forecast: point,
      q80: point * 1.048,
      q90: point * 1.061,
      q95: point * 1.077,
      base_forecast: point + 250,
      reconciliation_adjustment: -250,
      reconciliation_method: 'mint_variance',
      quantile_method: 'empirical',
      quantile_pooling_level: 'scope_all_horizons',
      quantile_residual_count: 12,
      target_source: 'order',
      is_censored: false,
      unavailable_reason: null,
      drivers: null,
    })),
    validation_metrics: {
      model_id: 'var_exog',
      display_name: 'VAR with exogenous variables',
      wape: 4.578,
      mae: 7558,
      rmse: 9200,
      mape: 6.5,
      smape: 5.5,
      mase: 0.46,
      bias: 1.1,
      validation_points: 10,
      evaluation_mode: 'rolling_origin',
    },
    drivers: { history_months: 28, seasonal_period: null },
    reconciliation_method: 'mint_variance',
    coherent: true,
    snapshot_caveat:
      'Forecasts carry the target-source mix of the window they were fitted on; a `sales_proxy` row is a labelled substitute, not ordered demand.',
    ...overrides,
  };
}

export function supplyOverviewFixture(
  overrides: Partial<SupplyOverviewResponse> = {},
): SupplyOverviewResponse {
  return {
    forecast_run_id: 'fc-0001',
    period: '2026-07',
    branch: null,
    stock_snapshot_date: '2026-08-01',
    totals: {
      positions: 70_724,
      positions_with_stock: 49_199,
      dead_or_slow_positions: 23_788,
      dead_stock_units: 409_031,
      dead_stock_value: 88_689_982,
      zero_stock_live_demand_positions: 21_549,
      unfilled_recent_demand_units: 377_501,
      negative_stock_rows: 2,
    },
    dead_stock: [
      {
        canonical_branch: 'BAWAL',
        canonical_sku: 'AISUW16-400C',
        usable_qty: 28_098,
        closing_value: 1_773_404,
        recent_demand: 0,
        stock_class: 'Cat D',
      },
    ],
    zero_stock_live_demand: [
      {
        canonical_branch: 'BENGALURU',
        canonical_sku: 'FG.BA5.LFH.GCG2120000',
        usable_qty: 0,
        recent_demand: 2715,
      },
    ],
    lead_time_assumptions: {
      JAIPUR: { avg_lead_time_days: 3, transit_lead_time_days: 6, truck_moq: null },
    },
    review_period_days: 30,
    caveats: [
      'Stock is a single snapshot dated 2026-08-01; demand history ends 2026-07. These are current-snapshot measures.',
    ],
    ...overrides,
  };
}

export function recommendationsFixture(
  overrides: Partial<RecommendationsResponse> = {},
): RecommendationsResponse {
  return {
    forecast_run_id: 'fc-0001',
    period: '2026-08',
    service_level: 95,
    scope_level: 'series',
    items: [
      {
        scope_key: 'JAIPUR|FG.BA5.LFH.GCG2120000',
        canonical_branch: 'JAIPUR',
        canonical_sku: 'FG.BA5.LFH.GCG2120000',
        service_level: 95,
        forecast_period: '2026-08',
        forecast_model_id: 'lstm',
        demand_segment: 'smooth',
        stock_class: 'Cat A',
        monthly_point_forecast: 800,
        monthly_quantile_forecast: 1000,
        review_period_days: 30,
        lead_time_days: 3,
        lead_time_source: 'Location Master average lead time',
        lead_time_p95_days: 6,
        protection_period_days: 33,
        protection_months: 1.0842,
        usable_stock_on_hand: 400,
        closing_stock_on_hand: 400,
        negative_stock_rows: 0,
        confirmed_stock_on_order: 0,
        backorders: 0,
        order_up_to_level: 1084.19,
        raw_recommended_order: 684.19,
        recommended_order: 684.19,
        days_of_cover: 15.2,
        moq: null,
        truck_quantity: null,
        case_pack: null,
        substitute_skus: [],
        target_source: 'order',
        is_censored: false,
        unavailable_reason: null,
        warnings: [
          'Confirmed stock on order and backorders are treated as zero because the source set contains no open-order or backorder snapshot.',
        ],
        caveats: ['A current-snapshot estimate.'],
        is_current_snapshot_estimate: true,
      },
      {
        scope_key: 'MANDI|FG.MP8.LFH.GCG2120000',
        canonical_branch: 'MANDI',
        canonical_sku: 'FG.MP8.LFH.GCG2120000',
        service_level: 95,
        forecast_period: '2026-08',
        forecast_model_id: null,
        demand_segment: 'intermittent',
        stock_class: null,
        monthly_point_forecast: null,
        monthly_quantile_forecast: null,
        review_period_days: 30,
        lead_time_days: null,
        lead_time_source: null,
        lead_time_p95_days: null,
        protection_period_days: null,
        protection_months: null,
        usable_stock_on_hand: null,
        closing_stock_on_hand: null,
        negative_stock_rows: 0,
        confirmed_stock_on_order: 0,
        backorders: 0,
        order_up_to_level: null,
        raw_recommended_order: null,
        recommended_order: null,
        days_of_cover: null,
        moq: null,
        truck_quantity: null,
        case_pack: null,
        substitute_skus: [],
        target_source: null,
        is_censored: null,
        unavailable_reason:
          'No q95 forecast exists for MANDI|FG.MP8.LFH.GCG2120000, so there is no demand figure to size an order against. Nothing was substituted.',
        warnings: [],
        caveats: ['A current-snapshot estimate.'],
        is_current_snapshot_estimate: true,
      },
    ],
    total: 2,
    offset: 0,
    limit: 100,
    unavailable_reason: null,
    notes: ['Review period 30 days, from settings.'],
    ...overrides,
  };
}

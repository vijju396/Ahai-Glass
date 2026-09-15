/**
 * API-shaped fixtures. Values are the real measured figures from the actual
 * source files, so a test that asserts on them is asserting the real contract.
 */
import type {
  Dataset,
  DatasetProfileResponse,
  DatasetVersionSummary,
  MappingDetail,
  MappingResponse,
  Page,
  PanelBuild,
  PreprocessingRun,
  ValidationResponse,
} from '@/types/api';

export const COMPLETED_VERSION: DatasetVersionSummary = {
  id: 'v1',
  version_number: 1,
  status: 'completed',
  stage_detail: 'Complete',
  progress_pct: 100,
  started_at: '2026-09-08T13:44:19Z',
  finished_at: '2026-09-08T13:52:15Z',
  duration_seconds: 475.6,
  controls_total: 11,
  controls_failed: 0,
  defects_total: 14,
  failure_reason: null,
};

export const RUNNING_VERSION: DatasetVersionSummary = {
  ...COMPLETED_VERSION,
  status: 'reading',
  stage_detail: 'Sales: 600,000 rows read',
  progress_pct: 15.3,
  finished_at: null,
  duration_seconds: null,
  controls_total: 0,
  defects_total: 0,
};

export const FAILED_CONTROL_VERSION: DatasetVersionSummary = {
  ...COMPLETED_VERSION,
  status: 'completed_with_failures',
  controls_failed: 2,
  failure_reason: '2 structural control(s) did not hold: S6, S7',
};

export function datasetPage(
  version: DatasetVersionSummary = COMPLETED_VERSION,
): Page<Dataset> {
  return {
    items: [
      {
        id: 'ds1',
        name: 'AIS source set 2026-08-27',
        description: 'Five client files',
        source_label: 'source',
        created_at: '2026-09-08T13:44:19Z',
        latest_version: version,
      },
    ],
    total: 1,
    offset: 0,
    limit: 25,
  };
}

export const VALIDATION: ValidationResponse = {
  version: COMPLETED_VERSION,
  passed: true,
  controls: [
    { control_code: 'S1', description: 'Sales invoice-line rows', expected: '1,703,042', measured: '1,703,042', outcome: 'pass', difference: null, tolerance_pct: 0.5, remediation: null },
    { control_code: 'S2', description: 'Order lines', expected: '775,912', measured: '775,912', outcome: 'pass', difference: null, tolerance_pct: 0.5, remediation: null },
    { control_code: 'S3', description: 'Stock snapshot rows', expected: '144,921', measured: '144,921', outcome: 'pass', difference: null, tolerance_pct: 0.5, remediation: null },
    { control_code: 'S4', description: 'Product-master rows', expected: '2,417', measured: '2,417', outcome: 'pass', difference: null, tolerance_pct: 0.5, remediation: null },
    { control_code: 'S5', description: 'Location-master rows (footer excluded)', expected: '57', measured: '57', outcome: 'pass', difference: null, tolerance_pct: 0.5, remediation: null },
    { control_code: 'S6', description: 'Distinct canonical SKUs', expected: '2,260', measured: '2,260', outcome: 'pass', difference: null, tolerance_pct: 0, remediation: null },
    { control_code: 'S7', description: 'Branch x SKU series', expected: '63,210', measured: '63,210', outcome: 'pass', difference: null, tolerance_pct: 0, remediation: null },
    { control_code: 'S8', description: 'Normalized order depots', expected: '53', measured: '53', outcome: 'pass', difference: null, tolerance_pct: 0.5, remediation: null },
    { control_code: 'S9', description: 'Product-master coverage of order lines (line-weighted, via Oracle No)', expected: '>= 99.0%', measured: '99.909%', outcome: 'pass', difference: null, tolerance_pct: null, remediation: null },
    { control_code: 'S10', description: 'Median order-to-despatch lead time (cleaned dates)', expected: '3 days', measured: '3 days', outcome: 'pass', difference: null, tolerance_pct: null, remediation: null },
    { control_code: 'S11', description: '95th-percentile lead time (cleaned dates)', expected: '6 days', measured: '6 days', outcome: 'pass', difference: null, tolerance_pct: null, remediation: null },
  ],
  defects: [
    { defect_code: 'D1', title: 'Product Name and HSN Code transposed beneath their headers: FY 25-26 Sales', severity: 'corrected', extent: 'confidence 100.0% over 200 sampled rows', affected_rows: null, source_role: 'sales', rule_applied: 'C2', fix_description: 'Detected by value pattern, not position.', evidence: null },
    { defect_code: 'D11', title: 'Order lines despatched beyond the quantity ordered', severity: 'recorded', extent: '9,498 lines, 35,867 units', affected_rows: 9498, source_role: 'orders', rule_applied: null, fix_description: 'Net and gross shortfall are reported separately.', evidence: null },
    { defect_code: 'D17', title: 'Material Code and Oracle No are not interchangeable join keys', severity: 'recorded', extent: '3,139 distinct via Material Code vs 2,063 via Oracle No', affected_rows: 48888, source_role: 'orders', rule_applied: 'C9', fix_description: 'Oracle No is the master join key in the order file.', evidence: null },
  ],
  service_measures: {
    total_ordered: 2_602_392,
    total_despatched: 2_133_961,
    net_shortfall: 468_431,
    gross_positive_shortfall: 504_298,
    over_delivered_qty: 35_867,
    net_fill_rate: 0.8199998,
    gross_shortfall_pct: 19.3782,
    lines_total: 775_912,
    lines_fully_unserved: 161_099,
    lines_with_shortfall: 168_599,
    lines_over_delivered: 9_498,
  },
  lead_time: {
    count: 775_628,
    median_days: 3,
    p95_days: 6,
    max_days: 27,
    unparseable_dates: 3,
    negative_excluded: 281,
  },
  summary: {},
  blocking_message: null,
};

export const FAILED_VALIDATION: ValidationResponse = {
  ...VALIDATION,
  version: FAILED_CONTROL_VERSION,
  passed: false,
  controls: VALIDATION.controls.map((control) =>
    control.control_code === 'S6'
      ? {
          ...control,
          measured: '2,147',
          outcome: 'fail' as const,
          difference: '-113 (-5.000%)',
          remediation:
            'The canonical key rule (C8) has changed behaviour. Raw Oracle No yields 2,147, not 2,260.',
        }
      : control,
  ),
  blocking_message:
    '1 structural control(s) did not hold: S6. Downstream phases must not treat this version as clean.',
};

export const MAPPING: MappingResponse = {
  version: COMPLETED_VERSION,
  canonical_sku_count: 2_260,
  oracle_no_count: 2_147,
  oracle_collision_count: 109,
  canonical_disagreement_count: 0,
  rows_missing_oracle: 11,
  sku_prefixes: { FG: 1_702_878, PREGST: 153, NONOE05: 6, NONOE08: 3 },
  branch_universes: {
    location_master: 57,
    stock: 54,
    order_depots: 53,
    selling_branches: 51,
  },
  sku_universes: {
    sales: 2_260,
    orders_via_oracle_no: 2_063,
    orders_via_material_code: 3_139,
    stock: 6_169,
    product_master: 2_417,
  },
  findings: [
    {
      finding_type: 'oracle_collision',
      key_value: 'FG.MYB.RDL.G00300A000',
      related_values: ['FG.MYB.RDL.G00300A000', 'PREGST.MYB.RDL.G00300A000'],
      occurrence_count: 2,
      note: 'One Oracle No spans several canonical Product Codes.',
    },
  ],
  findings_total: 110,
  canonical_key_rule:
    "UPPER(TRIM(Product Code)) -> strip a trailing '.AFM' or '.AF' -> strip a trailing '.' -> TRIM again.",
  why_not_oracle_no:
    'Raw Oracle No has only 2,147 distinct values because 109 Oracle numbers each span several canonical Product Codes.',
};

export const PROFILE: DatasetProfileResponse = {
  version: COMPLETED_VERSION,
  total_rows_read: 2_671_147,
  pii_columns_excluded: ['Customer Name', 'GSTIN', 'PAN No'],
  source_files: [
    {
      role: 'sales',
      filename: 'Sales Data FY 24~26.xlsb',
      sheet_name: 'FY 25-26 Sales + FY 24-25 Sales',
      size_bytes: 82_429_868,
      content_hash_sha256: 'abc123def456789012345678901234567890',
      row_count: 1_703_042,
      column_count: 33,
      read_seconds: 260.4,
      columns: ['Branch', 'Customer Name'],
      column_profiles: [
        { column_name: 'Branch', ordinal: 0, detected_type: 'text', non_null_count: 1_703_042, null_count: 0, distinct_count: 51, is_constant: false, is_pii: false, min_value: null, max_value: null, mean_value: null, sample_values: ['AGRA'], note: null },
        { column_name: 'Customer Name', ordinal: 1, detected_type: 'text', non_null_count: 1_703_042, null_count: 0, distinct_count: null, is_constant: false, is_pii: true, min_value: null, max_value: null, mean_value: null, sample_values: [], note: 'PII - counted only; values never read into the profile or any payload.' },
      ],
    },
  ],
};

// ------------------------------------------------------------- role mapping

export const ROLE_MAPPING: MappingDetail = {
  id: 'map1',
  dataset_version_id: 'v1',
  version_number: 1,
  state: 'draft',
  frequency: 'monthly',
  timezone: 'Asia/Kolkata',
  forecast_horizon: 6,
  aggregation_method: 'sum',
  duplicate_handling: 'aggregate',
  missing_timestamp_policy: 'explicit_zero',
  target_imputation_policy: 'leave_missing',
  driver_imputation_policy: 'leave_missing',
  confirmed_at: null,
  confirmed_by: null,
  superseded_at: null,
  notes: 'Phase 3 mapping',
  created_at: '2026-09-08T14:00:00Z',
  assignments: [
    {
      source_role: 'orders', column_name: 'Order Date', ordinal: 2,
      role: 'time_column', is_suggested: true, confidence: 0.9,
      rationale: 'AIS default mapping template.', aggregation: null,
      imputation: null, notes: null,
    },
    {
      source_role: 'orders', column_name: 'Quantity', ordinal: 6,
      role: 'target_column', is_suggested: true, confidence: 0.9,
      rationale: 'AIS default mapping template.', aggregation: null,
      imputation: null, notes: null,
    },
    {
      source_role: 'orders', column_name: 'Despatch Qty', ordinal: 7,
      role: 'supply', is_suggested: true, confidence: 0.9,
      rationale: 'AIS default mapping template.', aggregation: null,
      imputation: null,
      notes: 'A future despatch has not happened yet. It is also supply-censored.',
    },
    {
      source_role: 'orders', column_name: 'MRP Rate', ordinal: 8,
      role: 'historical_driver', is_suggested: true, confidence: 0.9,
      rationale: 'AIS default mapping template.', aggregation: null,
      imputation: null,
      notes: 'A price can change; its future value is not knowable in advance.',
    },
    {
      source_role: 'orders', column_name: 'Invoice No', ordinal: 9,
      role: 'excluded_pii', is_suggested: true, confidence: 1.0,
      rationale: 'Declared PII; excluded from every modelling dataset.',
      aggregation: null, imputation: null, notes: null,
    },
    {
      source_role: 'sales', column_name: 'Quantity', ordinal: 25,
      role: 'target_column', is_suggested: true, confidence: 0.9,
      rationale: 'AIS default mapping template.', aggregation: null,
      imputation: null, notes: null,
    },
  ],
  rule_results: [],
  role_counts: {
    time_column: 1,
    target_column: 2,
    supply: 1,
    historical_driver: 1,
    excluded_pii: 1,
  },
  unreviewed_count: 3,
  blocking_count: 0,
  warning_count: 0,
  can_confirm: false,
  future_known_columns: ['calendar_month', 'horizon_step', 'Region', 'Zone'],
  not_future_known_reasons: {
    'MRP Rate': 'A price can change; its future value is not knowable in advance.',
    'Despatch Qty': 'A future despatch has not happened yet. It is also supply-censored.',
  },
};

export const CONFIRMED_ROLE_MAPPING: MappingDetail = {
  ...ROLE_MAPPING,
  state: 'confirmed',
  confirmed_at: '2026-09-08T14:30:00Z',
  confirmed_by: 'vijji.babu',
  unreviewed_count: 0,
  can_confirm: false,
  assignments: ROLE_MAPPING.assignments.map((a) => ({ ...a, is_suggested: false })),
};

export const REVIEWED_ROLE_MAPPING: MappingDetail = {
  ...ROLE_MAPPING,
  unreviewed_count: 0,
  can_confirm: true,
  assignments: ROLE_MAPPING.assignments.map((a) => ({ ...a, is_suggested: false })),
};

export const BLOCKED_ROLE_MAPPING: MappingDetail = {
  ...ROLE_MAPPING,
  blocking_count: 1,
  rule_results: [
    {
      rule_code: 'R5',
      severity: 'blocking',
      message:
        "'MRP Rate' is mapped as a future-known driver, but its value is not available for the forecast horizon.",
      columns: ['MRP Rate'],
      remediation:
        "Reassign it as 'historical_driver'. A driver known only up to now must never be used as if its future value were available - that is leakage, and it fails at forecast time.",
    },
  ],
};

export const PREPROCESSING_RUNNING: PreprocessingRun = {
  id: 'pp1',
  status: 'running',
  stage_detail: 'Aggregating the sales fact',
  progress_pct: 57,
  started_at: '2026-09-08T14:31:00Z',
  finished_at: null,
  duration_seconds: null,
  failure_reason: null,
  branch_dim_rows: 0,
  product_dim_rows: 0,
  order_fact_rows: 0,
  sales_fact_rows: 0,
  fact_rows: 0,
  stock_position_rows: 0,
  distinct_series: 0,
  distinct_periods: 0,
  artifacts: null,
  summary: null,
};

export const PREPROCESSING_DONE: PreprocessingRun = {
  ...PREPROCESSING_RUNNING,
  status: 'completed',
  stage_detail: 'Complete',
  progress_pct: 100,
  finished_at: '2026-09-08T14:39:00Z',
  duration_seconds: 481.2,
  branch_dim_rows: 58,
  product_dim_rows: 2450,
  order_fact_rows: 363_310,
  sales_fact_rows: 411_902,
  fact_rows: 775_212,
  stock_position_rows: 143_004,
  distinct_series: 65_100,
  distinct_periods: 28,
  artifacts: {
    branch_dim: 'runtime/storage/prepared/pp1/branch_dim.parquet',
    order_fact: 'runtime/storage/prepared/pp1/order_fact.parquet',
  },
  summary: {
    period_range: ['2024-04', '2026-07'],
    order_periods: ['2025-04', '2026-07'],
    sales_periods: ['2024-04', '2026-03'],
    order_fact: { cells: 363_310, censored_cells: 107_000 },
    sales_fact: { cells: 411_902, transposition_corrected: ['FY 25-26 Sales'] },
    stock_position: {
      rows: 143_004,
      cells_with_stock: 49_199,
      negative_source_rows: 2,
    },
    warnings: [],
  },
};

// -------------------------------------------------------------- panel build

export const PANEL_BUILD_RUNNING: PanelBuild = {
  id: 'pb1',
  preprocessing_run_id: 'pp1',
  status: 'running',
  stage_detail: 'Building leakage-safe origin features',
  progress_pct: 62,
  started_at: '2026-09-09T09:00:00Z',
  finished_at: null,
  duration_seconds: null,
  failure_reason: null,
  training_cut_period: '2025-09',
  horizons: '1,2,3,4,5,6',
  panel_rows: 0,
  series_count: 0,
  period_count: 0,
  observed_rows: 0,
  materialised_zero_rows: 0,
  censored_rows: 0,
  training_rows: 0,
  scoring_rows: 0,
  feature_count: 0,
  artifacts: null,
  summary: null,
};

/** The real measured figures from the panel built against the client data. */
export const PANEL_BUILD_DONE: PanelBuild = {
  ...PANEL_BUILD_RUNNING,
  status: 'completed',
  stage_detail: 'Complete',
  progress_pct: 100,
  finished_at: '2026-09-09T09:02:20Z',
  duration_seconds: 139.9,
  panel_rows: 1_503_753,
  series_count: 68_675,
  period_count: 28,
  observed_rows: 634_951,
  materialised_zero_rows: 868_802,
  censored_rows: 109_145,
  training_rows: 3_895_148,
  scoring_rows: 360_702,
  feature_count: 35,
  artifacts: {
    panel: 'runtime/storage/prepared/panel_pb1/panel.parquet',
    training_frame: 'runtime/storage/prepared/panel_pb1/training_frame.parquet',
  },
  summary: {
    period_range: ['2024-04', '2026-07'],
    target_source_rows: { order: 994_526, sales_proxy: 509_227 },
    series_universe: {
      panel_series: 68_675,
      sales_control_series: 63_210,
      stock_only_pairs_excluded: 78_694,
    },
    sparsity: {
      zero_cell_share: 0.5778,
      series_with_one_nonzero_month: 10_877,
      series_with_12_plus_nonzero_months: 21_804,
      median_adi: 3.0,
      median_cv_squared: 0.2012,
    },
    feature_manifest: { feature_count: 35, max_lookback_months: 11 },
  },
};

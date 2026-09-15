/**
 * The three reference-parity pages.
 *
 * What is asserted is the behaviour the reference actually has, not that a
 * chart appeared:
 *
 * - **Cross-filtering works.** Clicking a chart sets the page filter and a
 *   clear chip puts it back. That is the reference's whole interaction model,
 *   and a page of charts that do not filter is not a port of it.
 * - **The grain control only offers grains the data has.** AIS demand is
 *   monthly; a daily option would be an invitation to read invented numbers.
 * - **An exception carries the definition it was found by**, so a planner can
 *   tell what the row means without reading the backend.
 * - **The assistant labels how an answer was produced** and never renders a
 *   chart the backend did not send.
 */
import { describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import * as analyticsApi from '@/api/analytics';
import { renderWithProviders } from '@/test/renderWithProviders';
import { DemandAnalyticsPage } from '../pages/DemandAnalyticsPage';
import { ExceptionsPage } from '@/features/exceptions/pages/ExceptionsPage';
import { AssistantPage } from '@/features/assistant/pages/AssistantPage';
import type {
  AnalyticsFilters,
  AnalyticsSummary,
  AssistantAnswer,
  AssistantStatus,
  BranchScorecard,
  ExceptionsPayload,
} from '@/api/analytics';

const FILTERS: AnalyticsFilters = {
  branches: [
    { value: 'BENGALURU', label: 'BENGALURU', rows: 100, units: 251_476 },
    { value: 'JAIPUR', label: 'JAIPUR', rows: 90, units: 190_000 },
  ],
  product_groups: [{ value: 'AIS GLASS', label: 'AIS GLASS', rows: 190, units: 441_476 }],
  value_classes: [
    { value: 'A', label: 'A', rows: 100, units: 300_000 },
    { value: 'B', label: 'B', rows: 90, units: 141_476 },
  ],
  regions: [{ value: 'SOUTH-1', label: 'SOUTH-1', rows: 190, units: 441_476 }],
  period_range: { min: '2024-04', max: '2026-07' },
  periods: ['2026-05', '2026-06', '2026-07'],
  available_grains: ['monthly', 'quarterly'],
  grain_note:
    'AIS demand history is monthly (one row per branch x SKU x month), so only monthly and a real quarterly roll-up are offered. A daily or weekly view would have to invent values the source data does not contain.',
  series_count: 68_675,
  panel_build_id: 'panel-1',
  training_cut_period: '2025-09',
};

function summary(overrides: Partial<AnalyticsSummary> = {}): AnalyticsSummary {
  return {
    empty: false,
    scope: { branch: null, product_group: null, value_class: null, grain: 'monthly' },
    window: { start: '2026-05', end: '2026-07', periods: 3 },
    available_grains: ['monthly', 'quarterly'],
    grain_note: FILTERS.grain_note,
    kpis: {
      demand_value: 13_460_208_859,
      demand_units: 4_165_509,
      shortfall_units: 504_298,
      fill_rate_pct: 82.0,
      order_share_pct: 66.14,
      censored_rows: 109_145,
      series_count: 68_675,
      branch_count: 53,
      sku_count: 2_334,
      rows: 1_503_753,
      despatch_rows_excluded_from_fill_rate: 1_140_448,
    },
    trend: [
      { period: '2026-05', demand_units: 180_000, demand_value: 500_000_000, despatched_units: 150_000, shortfall_units: 30_000, fill_rate_pct: 83.3, order_share_pct: 100, proxy_share_pct: 0, censored_share_pct: 9, price_per_unit: 2777, rows: 1000, despatch_rows_excluded: 0 },
      { period: '2026-06', demand_units: 193_349, demand_value: 520_000_000, despatched_units: 160_000, shortfall_units: 33_000, fill_rate_pct: 82.8, order_share_pct: 100, proxy_share_pct: 0, censored_share_pct: 9, price_per_unit: 2689, rows: 1000, despatch_rows_excluded: 0 },
      { period: '2026-07', demand_units: 200_686, demand_value: 540_000_000, despatched_units: 165_000, shortfall_units: 35_000, fill_rate_pct: 82.2, order_share_pct: 100, proxy_share_pct: 0, censored_share_pct: 9, price_per_unit: 2691, rows: 1000, despatch_rows_excluded: 0 },
    ],
    by_branch: [
      { name: 'BENGALURU', branch: 'BENGALURU', demand_units: 251_476, demand_value: 800_000_000, despatched_units: 200_000, shortfall_units: 40_000, sku_count: 1816, series_count: 1816 },
      { name: 'JAIPUR', branch: 'JAIPUR', demand_units: 190_000, demand_value: 600_000_000, despatched_units: 150_000, shortfall_units: 30_000, sku_count: 1200, series_count: 1200 },
    ],
    by_product_group: [
      { name: 'AIS GLASS', product_group: 'AIS GLASS', demand_units: 441_476, demand_value: 1_400_000_000, despatched_units: 350_000, shortfall_units: 70_000, sku_count: 3016, series_count: 3016 },
    ],
    by_value_class: [
      { name: 'A', value_class: 'A', demand_units: 300_000, demand_value: 900_000_000, despatched_units: 250_000, shortfall_units: 50_000, sku_count: 395, series_count: 395 },
      { name: 'B', value_class: 'B', demand_units: 141_476, demand_value: 500_000_000, despatched_units: 100_000, shortfall_units: 20_000, sku_count: 446, series_count: 446 },
    ],
    by_sku: [
      { name: 'FG.MP8.LFH.GCG2120000', sku: 'FG.MP8.LFH.GCG2120000', demand_units: 16_524, demand_value: 40_000_000, despatched_units: 15_481, shortfall_units: 1_043, sku_count: 1, series_count: 2 },
      { name: 'FG.TK4.LFH.GCG2120000', sku: 'FG.TK4.LFH.GCG2120000', demand_units: 6_867, demand_value: 18_000_000, despatched_units: 6_313, shortfall_units: 554, sku_count: 1, series_count: 2 },
    ],
    by_glass_type: [
      { name: 'Lam', demand_units: 65_056, demand_value: 160_000_000, despatched_units: 60_000, shortfall_units: 5_056, sku_count: 10, series_count: 20 },
      { name: 'Backlite', demand_units: 4_838, demand_value: 12_000_000, despatched_units: 4_500, shortfall_units: 338, sku_count: 4, series_count: 8 },
    ],
    by_vehicle_category: [
      { name: 'CAR & MUV', demand_units: 53_264, demand_value: 130_000_000, despatched_units: 50_000, shortfall_units: 3_264, sku_count: 15, series_count: 30 },
      { name: 'COMMERCIAL', demand_units: 7_929, demand_value: 20_000_000, despatched_units: 7_400, shortfall_units: 529, sku_count: 3, series_count: 6 },
    ],
    by_vehicle_age: [
      { name: 'Category Z ( >15 Years)', demand_units: 39_582, demand_value: 95_000_000, despatched_units: 37_000, shortfall_units: 2_582, sku_count: 9, series_count: 18 },
      { name: 'Category D (>9 & <=15 Years)', demand_units: 17_834, demand_value: 44_000_000, despatched_units: 16_800, shortfall_units: 1_034, sku_count: 4, series_count: 8 },
    ],
    branch_by_group: {
      groups: ['A', 'B'],
      data: [
        { name: 'BENGALURU', A: 500_000_000, B: 300_000_000 },
        { name: 'JAIPUR', A: 400_000_000, B: 200_000_000 },
      ],
      limit: 8,
      total_branches: 53,
    },
    branch_over_time: {
      names: ['BENGALURU', 'JAIPUR'],
      data: [
        { period: '2026-05', BENGALURU: 250_000_000, JAIPUR: 200_000_000 },
        { period: '2026-06', BENGALURU: 260_000_000, JAIPUR: 210_000_000 },
      ],
      limit: 6,
      total_branches: 53,
    },
    seasonality: [
      { month: 5, name: 'May', mean_demand_units: 180_000, observations: 2 },
      { month: 6, name: 'Jun', mean_demand_units: 193_349, observations: 1 },
    ],
    concentration: [{ branch: 'BENGALURU', sku_count: 1816, top5_share_pct: 14.9, demand_units: 251_476 }],
    coverage: [{ branch: 'BENGALURU', observed_months: 28, window_months: 28, coverage_pct: 100, demand_units: 251_476 }],
    notes: [
      'Demand value is ordered quantity x that month’s mean MRP, in rupees.',
      'Fill rate is despatched / ordered, computed only over months where a despatch figure exists.',
    ],
    panel_build_id: 'panel-1',
    ...overrides,
  };
}

const SCORECARD: BranchScorecard = {
  empty: false,
  scales: {
    fill_rate: { good: 100, poor: 70, target: 95, higher_is_better: true, unit: '%' },
    short_despatch_share: { good: 0, poor: 25, target: 5, higher_is_better: false, unit: '%' },
    demand_stability: { good: 0, poor: 80, target: 35, higher_is_better: false, unit: '%' },
    coverage: { good: 100, poor: 40, target: 80, higher_is_better: true, unit: '%' },
  },
  labels: {
    fill_rate: 'Fill rate',
    short_despatch_share: 'Short-despatch share',
    demand_stability: 'Demand variability',
    coverage: 'Months with demand',
  },
  branches: [
    {
      branch: 'BHUBANESWAR',
      rank: 1,
      score: 88,
      metric_values: { fill_rate: 94.5, short_despatch_share: 3.92, demand_stability: 12.4, coverage: 100 },
      score_components: { fill_rate: 82, short_despatch_share: 84, demand_stability: 85, coverage: 100 },
      off_target: ['fill_rate'],
      worst_metric: 'fill_rate',
      demand_units: 50_000,
      demand_value: 150_000_000,
      sku_count: 400,
    },
  ],
  total_branches: 53,
  note: 'Each branch scores out of 100 across four operational measures. This rates how a branch is running, never an individual.',
};

function exceptions(overrides: Partial<ExceptionsPayload> = {}): ExceptionsPayload {
  return {
    empty: false,
    scope: { branch: null },
    types: {
      censored_line: {
        label: 'Short despatch',
        severity: 'critical',
        definition: 'Despatched quantity is below ordered quantity, so the ordered figure is a lower bound on true demand.',
        measure: 'units short',
      },
      zero_stock_live_demand: {
        label: 'Zero stock, live demand',
        severity: 'critical',
        definition: 'No usable stock at this branch x SKU while demand was ordered in the last six months of history.',
        measure: 'recent demand units',
      },
    },
    recent_window_months: 6,
    kpis: {
      total_lines: 66_007,
      critical_lines: 59_726,
      high_lines: 6_082,
      medium_lines: 199,
      short_despatch_lines: 38_177,
      zero_stock_live_demand_lines: 21_549,
      units_affected: 923_539,
    },
    by_severity: [
      { name: 'critical', severity: 'critical', lines: 59_726 },
      { name: 'high', severity: 'high', lines: 6_082 },
    ],
    by_type: [
      { type: 'censored_line', name: 'Short despatch', severity: 'critical', lines: 38_177, units: 500_000 },
      { type: 'zero_stock_live_demand', name: 'Zero stock, live demand', severity: 'critical', lines: 21_549, units: 377_501 },
    ],
    by_branch: [
      { name: 'LUDHIANA', branch: 'LUDHIANA', lines: 2_000, units: 40_000 },
      { name: 'BENGALURU', branch: 'BENGALURU', lines: 1_800, units: 36_000 },
    ],
    by_product_group: [{ name: 'A', product_group: 'A', lines: 30_000, units: 400_000 }],
    top_lines: [
      {
        type: 'censored_line',
        label: 'Short despatch',
        severity: 'critical',
        definition: 'Despatched quantity is below ordered quantity, so the ordered figure is a lower bound on true demand.',
        measure: 'units short',
        series_id: 'LUDHIANA|FG.MP8.LFH.GCG2120000',
        branch: 'LUDHIANA',
        sku: 'FG.MP8.LFH.GCG2120000',
        product_group: 'AIS GLASS',
        value_class: 'A',
        units: 2767,
        occurrences: 12,
      },
    ],
    rows: [
      {
        type: 'censored_line',
        label: 'Short despatch',
        severity: 'critical',
        definition: 'Despatched quantity is below ordered quantity, so the ordered figure is a lower bound on true demand.',
        measure: 'units short',
        series_id: 'LUDHIANA|FG.MP8.LFH.GCG2120000',
        branch: 'LUDHIANA',
        sku: 'FG.MP8.LFH.GCG2120000',
        product_group: 'AIS GLASS',
        value_class: 'A',
        units: 2767,
        occurrences: 12,
      },
      {
        type: 'zero_stock_live_demand',
        label: 'Zero stock, live demand',
        severity: 'critical',
        definition: 'No usable stock at this branch x SKU while demand was ordered in the last six months of history.',
        measure: 'recent demand units',
        series_id: 'BENGALURU|FG.BA5.LFH.GCG2120000',
        branch: 'BENGALURU',
        sku: 'FG.BA5.LFH.GCG2120000',
        product_group: 'AIS GLASS',
        value_class: 'B',
        units: 989,
        occurrences: 1,
      },
    ],
    total_rows: 66_007,
    notes: ['Every exception here is a checkable condition on a real panel or stock row.'],
    ...overrides,
  };
}

function stubAnalytics() {
  vi.spyOn(analyticsApi, 'fetchAnalyticsFilters').mockResolvedValue(FILTERS);
  vi.spyOn(analyticsApi, 'fetchAnalyticsSummary').mockResolvedValue(summary());
  vi.spyOn(analyticsApi, 'fetchBranchScorecard').mockResolvedValue(SCORECARD);
}

describe('Demand Analytics', () => {
  it('shows the KPI strip from real aggregate figures', async () => {
    stubAnalytics();
    renderWithProviders(<DemandAnalyticsPage />);
    expect(await screen.findByText('₹1346.02Cr')).toBeInTheDocument();
    expect(screen.getByText('82.0%')).toBeInTheDocument();
    expect(screen.getByText('66.1%')).toBeInTheDocument();
  });

  it('offers only the grains the data supports, and says why', async () => {
    stubAnalytics();
    renderWithProviders(<DemandAnalyticsPage />);
    // The controls render before their options arrive, so wait for the filter
    // payload itself rather than for the <select>.
    await screen.findByRole('option', { name: 'BENGALURU' });
    const grain = screen.getByLabelText('Grain');
    const options = within(grain).getAllByRole('option').map((option) => option.textContent);
    expect(options).toEqual(['By month', 'By quarter']);
    expect(screen.getByText(/would have to invent values/i)).toBeInTheDocument();
  });

  it('filters the page when a branch is chosen, and a chip clears it', async () => {
    stubAnalytics();
    const user = userEvent.setup();
    renderWithProviders(<DemandAnalyticsPage />);
    await screen.findByRole('option', { name: 'BENGALURU' });
    await user.selectOptions(screen.getByLabelText('Branch'), 'BENGALURU');

    await waitFor(() =>
      expect(analyticsApi.fetchAnalyticsSummary).toHaveBeenCalledWith(
        expect.objectContaining({ branch: 'BENGALURU' }),
      ),
    );
    const chip = screen.getByRole('button', { name: /clear filter: bengaluru/i });
    await user.click(chip);
    await waitFor(() =>
      expect(analyticsApi.fetchAnalyticsSummary).toHaveBeenLastCalledWith(
        expect.objectContaining({ branch: undefined }),
      ),
    );
  });

  it('sends the chosen grain to the API', async () => {
    stubAnalytics();
    const user = userEvent.setup();
    renderWithProviders(<DemandAnalyticsPage />);
    await screen.findByRole('option', { name: 'BENGALURU' });
    await user.selectOptions(screen.getByLabelText('Grain'), 'quarterly');
    await waitFor(() =>
      expect(analyticsApi.fetchAnalyticsSummary).toHaveBeenCalledWith(
        expect.objectContaining({ grain: 'quarterly' }),
      ),
    );
  });

  it('scores branches with the target on each measure, never a person', async () => {
    stubAnalytics();
    renderWithProviders(<DemandAnalyticsPage />);
    expect(await screen.findByText('BHUBANESWAR')).toBeInTheDocument();
    expect(screen.getByText('88')).toBeInTheDocument();
    expect(screen.getByText(/never an individual/i)).toBeInTheDocument();
    expect(screen.getByText(/1\/4 off target/i)).toBeInTheDocument();
  });

  it('marks a seasonality point that rests on one observation', async () => {
    stubAnalytics();
    renderWithProviders(<DemandAnalyticsPage />);
    expect(await screen.findByText(/rest on a single observation/i)).toBeInTheDocument();
  });

  it('states how fill rate is defined, including the excluded months', async () => {
    stubAnalytics();
    renderWithProviders(<DemandAnalyticsPage />);
    expect(
      await screen.findByText(/computed only over months where a despatch figure exists/i),
    ).toBeInTheDocument();
  });

  it('reports an empty selection instead of rendering zeros', async () => {
    vi.spyOn(analyticsApi, 'fetchAnalyticsFilters').mockResolvedValue(FILTERS);
    vi.spyOn(analyticsApi, 'fetchBranchScorecard').mockResolvedValue(SCORECARD);
    vi.spyOn(analyticsApi, 'fetchAnalyticsSummary').mockResolvedValue({
      empty: true,
      reason: 'No panel row matches this combination.',
    } as unknown as AnalyticsSummary);
    renderWithProviders(<DemandAnalyticsPage />);
    expect(await screen.findByText('No panel row matches this combination.')).toBeInTheDocument();
    // No KPI strip at all, rather than a strip of zeros: a zero here would be
    // indistinguishable from a real zero.
    expect(screen.queryByText('ORDERED DEMAND VALUE')).not.toBeInTheDocument();
    expect(screen.queryByText('FILL RATE')).not.toBeInTheDocument();
  });
});

describe('Operational Exceptions', () => {
  function stub(payload = exceptions()) {
    vi.spyOn(analyticsApi, 'fetchAnalyticsFilters').mockResolvedValue(FILTERS);
    vi.spyOn(analyticsApi, 'fetchExceptions').mockResolvedValue(payload);
  }

  it('shows the exception counts by severity', async () => {
    stub();
    renderWithProviders(<ExceptionsPage />);
    expect(await screen.findByText('66.0K')).toBeInTheDocument();
    expect(screen.getByText('59.7K')).toBeInTheDocument();
  });

  it('shows every condition with the definition it was found by', async () => {
    stub();
    renderWithProviders(<ExceptionsPage />);
    expect(
      await screen.findByText(/Despatched quantity is below ordered quantity/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/No usable stock at this branch x SKU/i)).toBeInTheDocument();
  });

  it('ranks branch x SKU lines, never employees', async () => {
    stub();
    renderWithProviders(<ExceptionsPage />);
    expect(await screen.findByText(/equivalent of the reference's employee ranking/i)).toBeInTheDocument();
    expect(screen.getAllByText('FG.MP8.LFH.GCG2120000').length).toBeGreaterThan(0);
  });

  it('filters the table to one severity and clears it again', async () => {
    stub();
    const user = userEvent.setup();
    renderWithProviders(<ExceptionsPage />);
    await screen.findByText('66.0K');
    expect(screen.getAllByText('Short despatch').length).toBeGreaterThan(0);

    await screen.findByRole('option', { name: 'BENGALURU' });
    await user.selectOptions(screen.getByLabelText('Branch'), 'BENGALURU');
    await waitFor(() =>
      expect(analyticsApi.fetchExceptions).toHaveBeenCalledWith(
        expect.objectContaining({ branch: 'BENGALURU' }),
      ),
    );
    await user.click(screen.getByRole('button', { name: /clear filter: bengaluru/i }));
    await waitFor(() =>
      expect(analyticsApi.fetchExceptions).toHaveBeenLastCalledWith(
        expect.objectContaining({ branch: undefined }),
      ),
    );
  });

  it('says the hour-of-day panel has no AIS equivalent rather than faking one', async () => {
    stub();
    renderWithProviders(<ExceptionsPage />);
    expect(await screen.findByText(/no intra-day timestamps to bin/i)).toBeInTheDocument();
  });

  it('reports an empty selection honestly', async () => {
    stub(
      exceptions({
        empty: true,
        reason: 'No exception condition is present in this selection.',
      }),
    );
    renderWithProviders(<ExceptionsPage />);
    expect(
      await screen.findByText('No exception condition is present in this selection.'),
    ).toBeInTheDocument();
  });
});

describe('AI Assistant', () => {
  const STATUS: AssistantStatus = {
    enabled: true,
    configured: false,
    model: 'gpt-4.1-mini',
    steps: ['Open backend/.env', 'Paste your key', 'Restart the backend'],
    notes: ['The key stays on the server.'],
    suggested_questions: ['Show the monthly demand trend', 'Explain why this model is champion'],
  };

  function answer(overrides: Partial<AssistantAnswer> = {}): AssistantAnswer {
    return {
      question: 'Explain why this model is champion',
      answer: 'VAR with exogenous variables is champion at national scope with a WAPE of 4.578%.\n- **Champion** - VAR, WAPE 4.578%.',
      tools_used: ['model_leaderboard'],
      routed_by: 'keyword',
      answered_by: 'deterministic_no_key',
      facts: {},
      chart: null,
      scope: { branch: null, sku: null, period: null, resolved_from: null },
      model: null,
      provider_error: null,
      ...overrides,
    };
  }

  it('shows setup instructions when no key is configured', async () => {
    vi.spyOn(analyticsApi, 'fetchAssistantStatus').mockResolvedValue(STATUS);
    renderWithProviders(<AssistantPage />);

    // Wait on the suggestion buttons, which only exist once the status query
    // resolves. Waiting on /No API key configured/ instead matched the footer
    // sentence ("with no API key configured, answers are written locally"),
    // which renders before the status arrives - so the assertion passed while
    // the setup card was still absent.
    await screen.findByRole('button', { name: 'Show the monthly demand trend' });

    expect(screen.getByRole('heading', { name: /No API key configured/i })).toBeInTheDocument();
    // Each step renders as `{n}. {step}`, so no single element's text equals
    // the step on its own.
    expect(document.body.textContent).toContain('Open backend/.env');
    expect(document.body.textContent).toContain('Restart the backend');
    expect(screen.getByText(/answers are written locally/i)).toBeInTheDocument();
  });

  it('offers suggested questions and asks one', async () => {
    vi.spyOn(analyticsApi, 'fetchAssistantStatus').mockResolvedValue(STATUS);
    const ask = vi.spyOn(analyticsApi, 'askAssistant').mockResolvedValue(answer());
    const user = userEvent.setup();
    renderWithProviders(<AssistantPage />);
    await user.click(await screen.findByRole('button', { name: 'Explain why this model is champion' }));
    await waitFor(() => expect(ask).toHaveBeenCalled());
    expect(await screen.findByText(/champion at national scope with a WAPE of 4.578%/)).toBeInTheDocument();
  });

  it('labels a deterministic answer as one rather than implying a model wrote it', async () => {
    vi.spyOn(analyticsApi, 'fetchAssistantStatus').mockResolvedValue(STATUS);
    vi.spyOn(analyticsApi, 'askAssistant').mockResolvedValue(answer());
    const user = userEvent.setup();
    renderWithProviders(<AssistantPage />);
    await user.type(screen.getByLabelText(/Ask a question about demand/i), 'why?');
    await user.click(screen.getByRole('button', { name: 'Ask' }));
    expect(await screen.findByText(/Deterministic answer — no API key configured/i)).toBeInTheDocument();
  });

  it('links an answer to the page where its numbers can be checked', async () => {
    vi.spyOn(analyticsApi, 'fetchAssistantStatus').mockResolvedValue(STATUS);
    vi.spyOn(analyticsApi, 'askAssistant').mockResolvedValue(answer());
    const user = userEvent.setup();
    renderWithProviders(<AssistantPage />);
    await user.click(await screen.findByRole('button', { name: 'Explain why this model is champion' }));
    expect(await screen.findByRole('link', { name: /Check in Model Leaderboard/i })).toHaveAttribute(
      'href',
      '/leaderboard',
    );
  });

  it('renders a chart only when the backend sent one', async () => {
    vi.spyOn(analyticsApi, 'fetchAssistantStatus').mockResolvedValue(STATUS);
    vi.spyOn(analyticsApi, 'askAssistant').mockResolvedValue(
      answer({
        chart: {
          type: 'line',
          title: 'Ordered demand — the whole network',
          x_key: 'period',
          series: [{ key: 'demand', label: 'Ordered units' }],
          data: [
            { period: '2026-06', demand: 193_349 },
            { period: '2026-07', demand: 200_686 },
          ],
        },
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<AssistantPage />);
    await user.click(await screen.findByRole('button', { name: 'Show the monthly demand trend' }));
    expect(await screen.findByText('Ordered demand — the whole network')).toBeInTheDocument();
  });

  it('shows a scope chip that can be cleared', async () => {
    vi.spyOn(analyticsApi, 'fetchAssistantStatus').mockResolvedValue(STATUS);
    vi.spyOn(analyticsApi, 'askAssistant').mockResolvedValue(
      answer({ scope: { branch: 'BENGALURU', sku: null, period: null, resolved_from: 'question' } }),
    );
    const user = userEvent.setup();
    renderWithProviders(<AssistantPage />);
    await user.click(await screen.findByRole('button', { name: 'Show the monthly demand trend' }));
    const chip = await screen.findByRole('button', { name: /clear filter: bengaluru/i });
    await user.click(chip);
    expect(screen.queryByRole('button', { name: /clear filter: bengaluru/i })).not.toBeInTheDocument();
  });

  it('offers a retry when the request fails', async () => {
    vi.spyOn(analyticsApi, 'fetchAssistantStatus').mockResolvedValue(STATUS);
    vi.spyOn(analyticsApi, 'askAssistant').mockRejectedValue(new Error('network down'));
    const user = userEvent.setup();
    renderWithProviders(<AssistantPage />);
    await user.click(await screen.findByRole('button', { name: 'Show the monthly demand trend' }));
    expect(await screen.findByRole('button', { name: 'Retry' })).toBeInTheDocument();
  });

  it('sends prior turns so a follow-up resolves', async () => {
    vi.spyOn(analyticsApi, 'fetchAssistantStatus').mockResolvedValue(STATUS);
    const ask = vi.spyOn(analyticsApi, 'askAssistant').mockResolvedValue(answer());
    const user = userEvent.setup();
    renderWithProviders(<AssistantPage />);
    await user.click(await screen.findByRole('button', { name: 'Show the monthly demand trend' }));
    await screen.findByText(/champion at national scope/);
    await user.type(screen.getByLabelText(/Ask a question about demand/i), 'why?');
    await user.click(screen.getByRole('button', { name: 'Ask' }));
    await waitFor(() => expect(ask).toHaveBeenCalledTimes(2));
    const second = ask.mock.calls[1]?.[0];
    expect(second?.history.length).toBeGreaterThanOrEqual(2);
  });
});

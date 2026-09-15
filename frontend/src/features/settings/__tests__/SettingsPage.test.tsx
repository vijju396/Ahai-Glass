/**
 * Settings page contracts.
 *
 * Two properties: the page publishes no connection string or filesystem path,
 * and it carries no second model registry — the model IDs it renders come from
 * the API.
 */
import { describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import * as operationsApi from '@/api/operations';
import { SettingsPage } from '../pages/SettingsPage';
import { renderWithProviders } from '@/test/renderWithProviders';
import type { SettingsResponse } from '@/types/operations';

const MODEL_IDS = [
  'sarimax',
  'sarimax_exog',
  'auto_arima',
  'auto_arima_exog',
  'xgboost',
  'xgboost_exog',
  'exp_additive',
  'exp_additive_damped',
  'exp_multiplicative',
  'exp_multiplicative_damped',
  'var',
  'var_exog',
  'lstm',
];

function fixture(overrides: Partial<SettingsResponse> = {}): SettingsResponse {
  return {
    app_name: 'AIS Glass Forecast & Inventory Intelligence',
    app_version: '0.1.0',
    environment: 'local',
    official_model_count: 13,
    registered_model_ids: MODEL_IDS,
    baseline_method_ids: ['naive', 'seasonal_naive', 'ma3', 'ma6'],
    min_history_profile: 'reference',
    xgboost_training_profile: 'thorough',
    forecast_horizon_months: 6,
    service_levels: [80, 90, 95],
    random_seed: 42,
    max_local_series: 500,
    local_series_selection: 'value',
    per_model_timeout_seconds: 120,
    lstm_timeout_seconds: 300,
    max_training_workers: 4,
    review_period_days: 30,
    default_lead_time_days: 3,
    stock_snapshot_date: '2026-08-01',
    mlflow_enabled: true,
    mlflow_tracking_uri: 'file:./runtime/mlflow',
    database_dialect: 'sqlite',
    expected_controls: {
      sales_rows: 1_703_042,
      order_rows: 775_912,
      sales_skus: 2_260,
      series: 63_210,
    },
    notes: ['Changing these values is a deployment action, not a UI action.'],
    ...overrides,
  };
}

function stub() {
  vi.spyOn(operationsApi, 'fetchSettings').mockResolvedValue(fixture());
  vi.spyOn(operationsApi, 'fetchExportKinds').mockResolvedValue({
    kinds: [
      { kind: 'leaderboard', description: 'Model Leaderboard' },
      { kind: 'forecasts', description: 'Forecast Explorer' },
      { kind: 'recommendations', description: 'Supply Intelligence' },
      { kind: 'model_runs', description: 'Training Center' },
    ],
    note: 'An empty metric cell means undefined, never zero.',
  });
}

describe('SettingsPage', () => {
  it('renders the thirteen registered model IDs from the API', async () => {
    stub();
    renderWithProviders(<SettingsPage />);
    const table = await screen.findByTestId('registered-models');
    expect(table.querySelectorAll('tbody tr')).toHaveLength(13);
  });

  it('names the non-registry baselines as never-champion', async () => {
    stub();
    renderWithProviders(<SettingsPage />);
    await screen.findByTestId('registered-models');
    expect(screen.getByText(/can never be champion/i)).toBeInTheDocument();
  });

  it('shows the inventory policy inputs', async () => {
    stub();
    renderWithProviders(<SettingsPage />);
    const table = await screen.findByTestId('inventory-settings');
    expect(table.textContent).toMatch(/30 d/);
    expect(table.textContent).toMatch(/2026-08-01/);
    expect(screen.getByText(/current-snapshot estimate/i)).toBeInTheDocument();
  });

  it('shows the structural control expectations', async () => {
    stub();
    renderWithProviders(<SettingsPage />);
    const table = await screen.findByTestId('expected-controls');
    expect(table.textContent).toMatch(/17,03,042|1,703,042/);
    expect(table.textContent).toMatch(/63,210/);
  });

  it('exposes the dialect but no connection string or path', async () => {
    stub();
    renderWithProviders(<SettingsPage />);
    await screen.findByTestId('registered-models');
    expect(screen.getByText(/database: sqlite/i)).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/C:\\/);
    expect(document.body.textContent).not.toMatch(/\.venv/);
  });

  it('offers every export kind with a download link', async () => {
    stub();
    renderWithProviders(<SettingsPage />);
    const table = await screen.findByTestId('export-kinds');
    const links = table.querySelectorAll('a[download]');
    expect(links).toHaveLength(4);
    expect(links[0]?.getAttribute('href')).toMatch(/\/exports\/leaderboard/);
  });

  it('states that there is no write path for these values', async () => {
    stub();
    renderWithProviders(<SettingsPage />);
    expect(
      await screen.findByText(/deployment action, not a UI action/i),
    ).toBeInTheDocument();
  });
});

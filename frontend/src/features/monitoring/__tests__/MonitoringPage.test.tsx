/**
 * Monitoring page contracts.
 *
 * The single most important assertion here: **"not computable" must not render
 * as a zero or a green tick**. On this dataset error deterioration cannot be
 * measured at all, and a page that showed 0% would be asserting the champion
 * is holding up when nothing has been checked.
 */
import { describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import * as operationsApi from '@/api/operations';
import { ApiError } from '@/api/client';
import { MonitoringPage } from '../pages/MonitoringPage';
import { renderWithProviders } from '@/test/renderWithProviders';
import type { MonitoringResponse } from '@/types/operations';

function fixture(overrides: Partial<MonitoringResponse> = {}): MonitoringResponse {
  return {
    generated_at: '2026-09-09T10:00:00Z',
    freshness: {
      demand_history_end: '2026-07',
      demand_history_age_months: 2,
      stock_snapshot_date: '2026-08-01',
      stock_snapshot_age_months: 1,
      panel_built_at: '2026-09-09T08:00:00Z',
      panel_rows: 1_503_753,
      dataset_ingested_at: '2026-09-08T10:00:00Z',
      note: 'Demand history and the stock snapshot are reported separately because they do not end at the same month.',
    },
    drift: {
      available: true,
      reason: null,
      window_months: 6,
      recent_periods: ['2026-02', '2026-03', '2026-04', '2026-05', '2026-06', '2026-07'],
      national: {
        earlier: { months: 22, mean_monthly_demand: 140_000, rows: 900_000 },
        recent: { months: 6, mean_monthly_demand: 172_000, rows: 400_000 },
        shift_pct: 22.99,
      },
      target_sources_recent: ['order'],
      target_sources_earlier: ['order', 'sales_proxy'],
      target_source_changed: true,
      rows: [
        {
          scope_level: 'branch',
          scope_key: 'HYDERABAD',
          earlier_mean_monthly_demand: 1200,
          recent_mean_monthly_demand: 2200,
          shift_pct: 83.3,
        },
      ],
      note: 'No threshold is applied.',
    },
    champions: {
      active_champions: 166,
      newest_training_run_id: 'train-0002',
      champions_from_older_runs: 0,
      champions_beaten_by_a_baseline: 47,
      rows: [
        {
          scope_kind: 'overall',
          scope_key: 'NATIONAL',
          champion_model_id: 'var_exog',
          selection_source: 'automatic',
          selected_at: '2026-09-09T09:00:00Z',
          age_days: 0.04,
          training_run_id: 'train-0002',
          from_newest_training_run: true,
          beaten_by_baseline: false,
        },
      ],
      note: '47 of 166 active champion(s) are beaten by a non-registry baseline in their own scope.',
    },
    deterioration: {
      computable: false,
      reason:
        'None of the 6 forecast period(s) has been observed yet - the forecast origin is the last month the panel holds (2026-07), so there is no actual to compare against.',
      origin_period: '2026-07',
      forecast_periods: ['2026-08'],
      observed_forecast_periods: [],
      rows: [],
      note: null,
    },
    note: 'Nothing here raises an alert.',
    ...overrides,
  };
}

describe('MonitoringPage', () => {
  it('reports demand history and stock snapshot ages separately', async () => {
    vi.spyOn(operationsApi, 'fetchMonitoring').mockResolvedValue(fixture());
    renderWithProviders(<MonitoringPage />);
    expect(await screen.findByText('2026-07')).toBeInTheDocument();
    expect(screen.getByText('2026-08-01')).toBeInTheDocument();
    expect(screen.getByText(/2 month\(s\) old/)).toBeInTheDocument();
    expect(screen.getByText(/1 month\(s\) old/)).toBeInTheDocument();
  });

  it('shows both drift windows and states that no threshold is applied', async () => {
    vi.spyOn(operationsApi, 'fetchMonitoring').mockResolvedValue(fixture());
    renderWithProviders(<MonitoringPage />);
    expect(await screen.findByText('1,40,000')).toBeInTheDocument();
    expect(screen.getByText('1,72,000')).toBeInTheDocument();
    expect(screen.getByText('23.0%')).toBeInTheDocument();
    expect(screen.getByText(/No threshold is applied/)).toBeInTheDocument();
  });

  it('warns that part of a shift is a change of measurement', async () => {
    vi.spyOn(operationsApi, 'fetchMonitoring').mockResolvedValue(fixture());
    renderWithProviders(<MonitoringPage />);
    expect(
      await screen.findByText(/change of measurement/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/sales_proxy/)).toBeInTheDocument();
  });

  it('shows drift as unavailable with its reason when it cannot be measured', async () => {
    vi.spyOn(operationsApi, 'fetchMonitoring').mockResolvedValue(
      fixture({
        drift: {
          ...fixture().drift,
          available: false,
          reason: 'The panel artifact could not be read (FileNotFoundError).',
          national: null,
          rows: [],
        },
      }),
    );
    renderWithProviders(<MonitoringPage />);
    expect(
      await screen.findByText(/Drift could not be measured/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/FileNotFoundError/)).toBeInTheDocument();
  });

  it('states how many champions a baseline beats', async () => {
    vi.spyOn(operationsApi, 'fetchMonitoring').mockResolvedValue(fixture());
    renderWithProviders(<MonitoringPage />);
    expect(await screen.findByText('47')).toBeInTheDocument();
    expect(
      screen.getByText(/beaten by a non-registry baseline in their own scope/i),
    ).toBeInTheDocument();
  });

  it('renders deterioration as not-yet-checked, never as zero', async () => {
    vi.spyOn(operationsApi, 'fetchMonitoring').mockResolvedValue(fixture());
    renderWithProviders(<MonitoringPage />);
    expect(
      await screen.findByText(/This has not been checked yet/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/no actual to compare against/i),
    ).toBeInTheDocument();
    expect(screen.queryByTestId('deterioration-table')).not.toBeInTheDocument();
  });

  it('renders the deterioration table once it becomes computable', async () => {
    vi.spyOn(operationsApi, 'fetchMonitoring').mockResolvedValue(
      fixture({
        deterioration: {
          computable: true,
          reason: null,
          origin_period: '2026-07',
          forecast_periods: ['2026-08'],
          observed_forecast_periods: ['2026-08'],
          rows: [
            {
              scope_level: 'branch',
              scope_key: 'JAIPUR',
              period: '2026-08',
              model_id: 'var_exog',
              actual: 1000,
              point_forecast: 1200,
              absolute_error: 200,
              accrued_wape: 20,
              backtest_wape: 4.578,
              deterioration_pct: 15.422,
            },
          ],
          note: 'A positive deterioration means the model is doing worse in production than in validation.',
        },
      }),
    );
    renderWithProviders(<MonitoringPage />);
    const table = await screen.findByTestId('deterioration-table');
    expect(table.textContent).toMatch(/JAIPUR/);
    expect(table.textContent).toMatch(/15\.42%/);
    expect(
      screen.getByText(/worse in production than in validation/i),
    ).toBeInTheDocument();
  });

  it('states that nothing raises an alert', async () => {
    vi.spyOn(operationsApi, 'fetchMonitoring').mockResolvedValue(fixture());
    renderWithProviders(<MonitoringPage />);
    expect(await screen.findByText(/raises an alert/i)).toBeInTheDocument();
  });

  it('renders an actionable error state', async () => {
    vi.spyOn(operationsApi, 'fetchMonitoring').mockRejectedValue(
      new ApiError('nope', 0, 'network_error'),
    );
    renderWithProviders(<MonitoringPage />);
    expect(await screen.findByRole('alert')).toBeInTheDocument();
  });
});

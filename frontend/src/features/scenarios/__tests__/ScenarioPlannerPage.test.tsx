/**
 * Scenario Planner contracts.
 *
 * The properties that matter: nothing is shown before a real evaluation, the
 * levers are displayed beside their baseline values, a scope with no baseline
 * forecast is not scaled from nothing, and the page states that the baseline is
 * read-only.
 */
import { describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import * as operationsApi from '@/api/operations';
import { ApiError } from '@/api/client';
import { ScenarioPlannerPage } from '../pages/ScenarioPlannerPage';
import { renderWithProviders } from '@/test/renderWithProviders';
import type { ScenarioResponse } from '@/types/operations';

function fixture(overrides: Partial<ScenarioResponse> = {}): ScenarioResponse {
  return {
    name: 'Peak season',
    generated_at: '2026-09-09T10:00:00Z',
    baseline_forecast_run_id: 'fc-00000001',
    baseline_origin_period: '2026-07',
    scope_level: 'branch',
    period: null,
    levers: {
      demand_multiplier: 1.2,
      service_level: 95,
      lead_time_days: 10,
      baseline_lead_time_days: 3,
      review_period_days: 30,
      baseline_review_period_days: 30,
    },
    totals: {
      baseline_demand: 299_643,
      scenario_demand: 359_571,
      demand_delta: 59_928,
      demand_delta_pct: 20,
      baseline_order_quantity: 379_135,
      scenario_order_quantity: 551_470,
      order_delta: 172_335,
      order_delta_pct: 45.5,
    },
    rows: [
      {
        scope_key: 'JAIPUR',
        period: '2026-08',
        horizon: 1,
        model_id: 'var_exog',
        baseline_point: 1000,
        scenario_point: 1200,
        baseline_quantile: 1100,
        scenario_quantile: 1320,
        baseline_recommended_order: 1192,
        scenario_recommended_order: 1735,
        unavailable_reason: null,
      },
      {
        scope_key: 'MANDI',
        period: '2026-08',
        horizon: 1,
        model_id: null,
        baseline_point: null,
        scenario_point: null,
        baseline_quantile: null,
        scenario_quantile: null,
        baseline_recommended_order: null,
        scenario_recommended_order: null,
        unavailable_reason:
          'The baseline has no forecast for this scope, so there is nothing to scale. A scenario cannot invent one.',
      },
    ],
    rows_returned: 2,
    rows_without_baseline: 1,
    caveats: [
      'The baseline forecast run is read-only: a scenario is computed on read from the stored rows and never written back over them.',
      'Stock on hand is held at zero on both sides of the comparison.',
    ],
    ...overrides,
  };
}

describe('ScenarioPlannerPage', () => {
  it('shows nothing until a scenario has actually been evaluated', () => {
    vi.spyOn(operationsApi, 'evaluateScenario').mockResolvedValue(fixture());
    renderWithProviders(<ScenarioPlannerPage />);
    expect(screen.getByText(/No scenario evaluated yet/i)).toBeInTheDocument();
    expect(screen.queryByTestId('scenario-table')).not.toBeInTheDocument();
  });

  it('says up front that the baseline is read-only', () => {
    vi.spyOn(operationsApi, 'evaluateScenario').mockResolvedValue(fixture());
    renderWithProviders(<ScenarioPlannerPage />);
    expect(screen.getByText(/read-only/i)).toBeInTheDocument();
  });

  it('sends the levers the user set', async () => {
    const spy = vi
      .spyOn(operationsApi, 'evaluateScenario')
      .mockResolvedValue(fixture());
    renderWithProviders(<ScenarioPlannerPage />);
    await userEvent.click(screen.getByRole('button', { name: /evaluate scenario/i }));
    expect(spy.mock.calls.at(0)?.[0]).toMatchObject({
      demand_multiplier: 1.2,
      service_level: 95,
      scope_level: 'branch',
    });
  });

  it('shows the demand and order deltas separately', async () => {
    vi.spyOn(operationsApi, 'evaluateScenario').mockResolvedValue(fixture());
    renderWithProviders(<ScenarioPlannerPage />);
    await userEvent.click(screen.getByRole('button', { name: /evaluate scenario/i }));
    expect(await screen.findByText('+20.0%')).toBeInTheDocument();
    expect(screen.getByText('+45.5%')).toBeInTheDocument();
  });

  it('shows each lever beside its baseline value', async () => {
    vi.spyOn(operationsApi, 'evaluateScenario').mockResolvedValue(fixture());
    renderWithProviders(<ScenarioPlannerPage />);
    await userEvent.click(screen.getByRole('button', { name: /evaluate scenario/i }));
    expect(await screen.findByText('×1.2')).toBeInTheDocument();
    expect(screen.getByText('10 d')).toBeInTheDocument();
  });

  it('keeps a scope with no baseline forecast, with its reason', async () => {
    vi.spyOn(operationsApi, 'evaluateScenario').mockResolvedValue(fixture());
    renderWithProviders(<ScenarioPlannerPage />);
    await userEvent.click(screen.getByRole('button', { name: /evaluate scenario/i }));
    const table = await screen.findByTestId('scenario-table');
    const row = Array.from(table.querySelectorAll('tbody tr')).find((node) =>
      node.textContent?.includes('MANDI'),
    );
    expect(row?.textContent).toMatch(/cannot invent one/i);
    expect(
      screen.getByText(/1 row\(s\) have no baseline forecast/i),
    ).toBeInTheDocument();
  });

  it('renders the caveats the API returned', async () => {
    vi.spyOn(operationsApi, 'evaluateScenario').mockResolvedValue(fixture());
    renderWithProviders(<ScenarioPlannerPage />);
    await userEvent.click(screen.getByRole('button', { name: /evaluate scenario/i }));
    expect(
      await screen.findByText(/never written back over them/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/zero on both sides/i)).toBeInTheDocument();
  });

  it('shows a 404 as an empty state with the API guidance', async () => {
    vi.spyOn(operationsApi, 'evaluateScenario').mockRejectedValue(
      new ApiError(
        'No completed forecast run exists to build a scenario against.',
        404,
        'not_found',
        'POST /api/forecasts/runs first.',
      ),
    );
    renderWithProviders(<ScenarioPlannerPage />);
    await userEvent.click(screen.getByRole('button', { name: /evaluate scenario/i }));
    expect(await screen.findByText(/No baseline to build on/i)).toBeInTheDocument();
    expect(screen.getByText(/POST \/api\/forecasts\/runs/)).toBeInTheDocument();
  });
});

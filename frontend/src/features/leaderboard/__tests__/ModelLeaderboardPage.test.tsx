/**
 * Leaderboard page contracts.
 *
 * The assertions here mirror the backend's own: all thirteen registered models
 * render whatever their status, both rankings appear side by side, a baseline
 * is visibly separate and never champion, an undefined metric renders as a dash
 * rather than a zero, and a missing model produces a visible defect banner.
 *
 * Model names appear in the fixture, not in the page. That is what
 * `no-duplicate-registry.test.ts` allows and enforces.
 */
import { describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import * as leaderboardApi from '@/api/leaderboard';
import { ApiError } from '@/api/client';
import { ModelLeaderboardPage } from '../pages/ModelLeaderboardPage';
import { renderWithProviders } from '@/test/renderWithProviders';
import {
  championFixture,
  comparisonFixture,
  leaderboardFixture,
} from '@/test/phase7Fixtures';

const REGISTERED = [
  'SARIMAX',
  'SARIMAX with exogenous variables',
  'Auto ARIMA',
  'Auto ARIMA with exogenous variables',
  'XGBoost',
  'XGBoost with exogenous variables',
  'Exponential Smoothing Additive',
  'Exponential Smoothing Additive Damped',
  'Exponential Smoothing Multiplicative',
  'Exponential Smoothing Multiplicative Damped',
  'VAR',
  'VAR with exogenous variables',
  'LSTM',
];

function stub(overrides: Parameters<typeof leaderboardFixture>[0] = {}) {
  vi.spyOn(leaderboardApi, 'fetchScopes').mockResolvedValue({
    items: [{ scope_level: 'national', scope_key: 'NATIONAL' }],
    total: 1,
    offset: 0,
    limit: 500,
  });
  vi.spyOn(leaderboardApi, 'fetchComparison').mockResolvedValue(comparisonFixture());
  vi.spyOn(leaderboardApi, 'fetchChampionHistory').mockResolvedValue({
    scope_kind: 'overall',
    scope_key: 'NATIONAL',
    entries: [championFixture()],
    total: 1,
  });
  return vi
    .spyOn(leaderboardApi, 'fetchLeaderboard')
    .mockResolvedValue(leaderboardFixture(overrides));
}

describe('ModelLeaderboardPage', () => {
  it('renders all 13 registered models, whatever their status', async () => {
    stub();
    renderWithProviders(<ModelLeaderboardPage />);
    const table = await screen.findByTestId('leaderboard-table');
    const rows = table.querySelectorAll('tbody tr');
    expect(rows).toHaveLength(13);
  });

  it('renders every registered display name', async () => {
    stub();
    renderWithProviders(<ModelLeaderboardPage />);
    await screen.findByTestId('leaderboard-table');
    for (const name of REGISTERED) {
      expect(screen.getAllByText(name).length).toBeGreaterThan(0);
    }
  });

  it('shows an ineligible model with its requirement rather than hiding it', async () => {
    stub();
    renderWithProviders(<ModelLeaderboardPage />);
    const table = await screen.findByTestId('leaderboard-table');
    const row = table.querySelector('tr[data-model="auto_arima"]');
    expect(row).not.toBeNull();
    expect(row?.textContent).toMatch(/Ineligible/i);
    expect(row?.textContent).toMatch(/24 training observations/);
  });

  it('renders a distinct status for ineligible and completed models', async () => {
    stub();
    renderWithProviders(<ModelLeaderboardPage />);
    const table = await screen.findByTestId('leaderboard-table');
    const statuses = Array.from(
      table.querySelectorAll('tbody tr [data-status]'),
    ).map((node) => node.getAttribute('data-status'));
    expect(statuses).toHaveLength(13);
    expect(new Set(statuses)).toEqual(new Set(['completed', 'ineligible']));
  });

  it('renders an undefined metric as a dash, never as zero', async () => {
    stub();
    renderWithProviders(<ModelLeaderboardPage />);
    const table = await screen.findByTestId('leaderboard-table');
    const row = table.querySelector('tr[data-model="exp_additive"]');
    const cells = Array.from(row?.querySelectorAll('td') ?? []).map((c) => c.textContent);
    // WAPE, MAPE, accuracy and MAE are all undefined for an ineligible model.
    expect(cells).toContain('—');
    expect(cells).not.toContain('0.000');
  });

  it('shows both rankings side by side', async () => {
    stub();
    renderWithProviders(<ModelLeaderboardPage />);
    const table = await screen.findByTestId('leaderboard-table');
    const headers = Array.from(table.querySelectorAll('thead th')).map(
      (node) => node.textContent,
    );
    expect(headers).toContain('Rank');
    expect(headers).toContain('Legacy');
    expect(headers).toContain('WAPE %');
    expect(headers).toContain('MAPE %');
  });

  it('marks the champion and the challenger', async () => {
    stub();
    renderWithProviders(<ModelLeaderboardPage />);
    const table = await screen.findByTestId('leaderboard-table');
    expect(
      table.querySelector('tr[data-model="var_exog"]')?.textContent,
    ).toMatch(/Champion/);
    expect(
      table.querySelector('tr[data-model="sarimax_exog"]')?.textContent,
    ).toMatch(/Challenger/);
  });

  it('lists baselines in a separate table, unranked', async () => {
    stub();
    renderWithProviders(<ModelLeaderboardPage />);
    const baselines = await screen.findByTestId('baseline-table');
    const rows = baselines.querySelectorAll('tbody tr');
    expect(rows).toHaveLength(4);
    expect(baselines.textContent).toMatch(/never champion|non-registry/i);
    // A baseline must not appear in the registered table.
    const table = screen.getByTestId('leaderboard-table');
    expect(table.querySelector('tr[data-model="ma6"]')).toBeNull();
  });

  it('says plainly when a baseline beats the champion', async () => {
    stub({
      beaten_by_baseline: true,
      best_baseline_wape: 1.2,
      skill_vs_best_baseline: {
        improvement_pct: -280,
        champion_better: false,
        reason: null,
      },
    });
    renderWithProviders(<ModelLeaderboardPage />);
    expect(
      await screen.findByText(/non-registry baseline beats the champion/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/not the best available forecast/i),
    ).toBeInTheDocument();
  });

  it('renders a defect banner when a registered model has no row', async () => {
    stub({ models_missing: ['lstm'] });
    renderWithProviders(<ModelLeaderboardPage />);
    const alerts = await screen.findAllByRole('alert');
    expect(
      alerts.some((node) => /Models missing from this leaderboard/i.test(node.textContent ?? '')),
    ).toBe(true);
  });

  it('labels accuracy as informational only', async () => {
    stub();
    renderWithProviders(<ModelLeaderboardPage />);
    await screen.findByTestId('leaderboard-table');
    expect(screen.getByText(/informational only/i)).toBeInTheDocument();
  });

  it('surfaces the mixed-evaluation-mode note from the API', async () => {
    stub();
    renderWithProviders(<ModelLeaderboardPage />);
    expect(
      await screen.findByText(/mixes evaluation modes/i),
    ).toBeInTheDocument();
  });

  it('renders a loading state before the data arrives', () => {
    stub();
    renderWithProviders(<ModelLeaderboardPage />);
    expect(screen.getByRole('status')).toBeInTheDocument();
  });

  it('renders an actionable error state and can retry', async () => {
    vi.spyOn(leaderboardApi, 'fetchScopes').mockResolvedValue({
      items: [],
      total: 0,
      offset: 0,
      limit: 500,
    });
    vi.spyOn(leaderboardApi, 'fetchComparison').mockRejectedValue(
      new ApiError('nope', 0, 'network_error'),
    );
    const spy = vi
      .spyOn(leaderboardApi, 'fetchLeaderboard')
      .mockRejectedValue(new ApiError('nope', 0, 'network_error'));
    renderWithProviders(<ModelLeaderboardPage />);
    expect(await screen.findByRole('alert')).toBeInTheDocument();
    expect(screen.getByText(/Cannot reach the API/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /try again/i }));
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2));
  });

  it('shows a 404 as an empty state with the API guidance, not an error', async () => {
    vi.spyOn(leaderboardApi, 'fetchScopes').mockResolvedValue({
      items: [],
      total: 0,
      offset: 0,
      limit: 500,
    });
    vi.spyOn(leaderboardApi, 'fetchComparison').mockRejectedValue(
      new ApiError('none', 404, 'not_found'),
    );
    vi.spyOn(leaderboardApi, 'fetchLeaderboard').mockRejectedValue(
      new ApiError(
        'No training run has produced any model results yet.',
        404,
        'not_found',
        'POST /api/training to run one.',
      ),
    );
    renderWithProviders(<ModelLeaderboardPage />);
    expect(
      await screen.findByText(/No leaderboard for this scope yet/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/POST \/api\/training/)).toBeInTheDocument();
  });
});

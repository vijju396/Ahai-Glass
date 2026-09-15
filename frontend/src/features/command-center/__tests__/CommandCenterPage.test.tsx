import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MODEL_REGISTRY_FIXTURE, renderWithProviders } from '@/test/renderWithProviders';
import { CommandCenterPage } from '@/features/command-center/pages/CommandCenterPage';
import * as healthApi from '@/api/health';
import * as modelsApi from '@/api/models';
import * as forecastApi from '@/api/forecasts';
import * as leaderboardApi from '@/api/leaderboard';
import * as trainingApi from '@/api/training';
import * as inventoryApi from '@/api/inventory';
import * as panelApi from '@/api/panel';
import { ApiError } from '@/api/client';

const HEALTH_FIXTURE = {
  status: 'ok' as const,
  app_name: 'AIS Glass Forecast & Inventory Intelligence',
  version: '0.1.0',
  environment: 'local',
  components: [
    { name: 'database', status: 'ok' as const, detail: null },
    { name: 'model_registry', status: 'ok' as const, detail: '13 of 13 models registered.' },
    { name: 'source_data', status: 'ok' as const, detail: 'All 5 source files present.' },
    { name: 'ml_dependencies', status: 'ok' as const, detail: null },
  ],
};

describe('CommandCenterPage', () => {
  beforeEach(() => {
    const pending = new Promise<never>(() => {});
    vi.spyOn(forecastApi, 'fetchSeriesForecast').mockReturnValue(pending);
    vi.spyOn(forecastApi, 'fetchForecastRows').mockReturnValue(pending);
    vi.spyOn(forecastApi, 'fetchCurrentForecastRun').mockReturnValue(pending);
    vi.spyOn(leaderboardApi, 'fetchLeaderboard').mockReturnValue(pending);
    vi.spyOn(trainingApi, 'fetchCurrentRun').mockReturnValue(pending);
    vi.spyOn(inventoryApi, 'fetchSupplyOverview').mockReturnValue(pending);
    vi.spyOn(panelApi, 'fetchCurrentPanel').mockReturnValue(pending);
  });
  it('renders health components from the API', async () => {
    vi.spyOn(healthApi, 'fetchHealth').mockResolvedValue(HEALTH_FIXTURE);
    vi.spyOn(modelsApi, 'fetchModelRegistry').mockResolvedValue(
      MODEL_REGISTRY_FIXTURE as never,
    );
    renderWithProviders(<CommandCenterPage />);
    expect(await screen.findByText('model_registry')).toBeInTheDocument();
    expect(screen.getByText('13 of 13 models registered.')).toBeInTheDocument();
  });

  it('reports the official model count from the API, not a constant', async () => {
    vi.spyOn(healthApi, 'fetchHealth').mockResolvedValue(HEALTH_FIXTURE);
    vi.spyOn(modelsApi, 'fetchModelRegistry').mockResolvedValue({
      ...MODEL_REGISTRY_FIXTURE,
      official_model_count: 13,
    } as never);
    renderWithProviders(<CommandCenterPage />);
    expect(await screen.findByText('Official models')).toBeInTheDocument();
    expect(await screen.findByText('13')).toBeInTheDocument();
  });

  it('states the forecast target is ordered quantity', () => {
    vi.spyOn(healthApi, 'fetchHealth').mockReturnValue(new Promise(() => {}) as never);
    vi.spyOn(modelsApi, 'fetchModelRegistry').mockReturnValue(new Promise(() => {}) as never);
    renderWithProviders(<CommandCenterPage />);
    expect(screen.getByText(/ordered quantity/i)).toBeInTheDocument();
    expect(screen.getByText(/never despatched/i)).toBeInTheDocument();
  });

  it('surfaces a health failure instead of rendering an optimistic page', async () => {
    vi.spyOn(healthApi, 'fetchHealth').mockRejectedValue(
      new ApiError('Could not reach the API.', 0, 'network_error'),
    );
    vi.spyOn(modelsApi, 'fetchModelRegistry').mockResolvedValue(
      MODEL_REGISTRY_FIXTURE as never,
    );
    renderWithProviders(<CommandCenterPage />);
    await userEvent.click(screen.getByText('Service health & technical provenance'));
    expect(await screen.findByRole('alert')).toBeInTheDocument();
  });
});

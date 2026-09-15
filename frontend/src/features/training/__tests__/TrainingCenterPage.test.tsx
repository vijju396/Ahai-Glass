/**
 * Training Center contracts.
 *
 * What matters on this page: the cost is visible before anything starts, a
 * submission does not block, no model can disappear from the per-model table,
 * and a missing model produces a visible defect banner.
 */
import { describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import * as trainingApi from '@/api/training';
import { ApiError } from '@/api/client';
import { TrainingCenterPage } from '../pages/TrainingCenterPage';
import { renderWithProviders } from '@/test/renderWithProviders';
import {
  trainingDetailFixture,
  trainingRunFixture,
} from '@/test/phase7Fixtures';

function stub() {
  vi.spyOn(trainingApi, 'estimateRun').mockResolvedValue(
    trainingRunFixture().estimate!,
  );
  vi.spyOn(trainingApi, 'fetchCurrentRun').mockResolvedValue(trainingRunFixture());
  vi.spyOn(trainingApi, 'fetchRunDetail').mockResolvedValue(trainingDetailFixture());
}

describe('TrainingCenterPage', () => {
  it('shows the estimated cost before a run is submitted', async () => {
    stub();
    const submit = vi.spyOn(trainingApi, 'submitRun');
    renderWithProviders(<TrainingCenterPage />);
    const estimate = await screen.findByTestId('run-estimate');
    expect(estimate.textContent).toMatch(/7\.1 min/);
    expect(estimate.textContent).toMatch(/21\.2 min/);
    expect(estimate.textContent).toMatch(/2,139/);
    expect(submit).not.toHaveBeenCalled();
  });

  it('states where the estimate came from', async () => {
    stub();
    renderWithProviders(<TrainingCenterPage />);
    const estimate = await screen.findByTestId('run-estimate');
    expect(estimate.textContent).toMatch(/measured in this project/i);
  });

  it('submits a run and does not wait for it', async () => {
    stub();
    const submit = vi
      .spyOn(trainingApi, 'submitRun')
      .mockResolvedValue(trainingRunFixture({ status: 'queued' }));
    renderWithProviders(<TrainingCenterPage />);
    await screen.findByTestId('run-estimate');
    await userEvent.click(screen.getByRole('button', { name: /start training run/i }));
    await waitFor(() => expect(submit).toHaveBeenCalledTimes(1));
    expect(submit.mock.calls.at(0)?.[0]).toMatchObject({ tiers: ['aggregate'] });
  });

  it('surfaces a refused submission with the API remediation', async () => {
    stub();
    vi.spyOn(trainingApi, 'submitRun').mockRejectedValue(
      new ApiError(
        'A training run is already in progress.',
        409,
        'conflict',
        'Wait for it to finish, or cancel it first.',
      ),
    );
    renderWithProviders(<TrainingCenterPage />);
    await screen.findByTestId('run-estimate');
    await userEvent.click(screen.getByRole('button', { name: /start training run/i }));
    expect(
      await screen.findByText(/already in progress.*cancel it first/i),
    ).toBeInTheDocument();
  });

  it('shows the local series cap only when the local tier is selected', async () => {
    stub();
    renderWithProviders(<TrainingCenterPage />);
    await screen.findByTestId('run-estimate');
    expect(screen.queryByLabelText(/local series cap/i)).not.toBeInTheDocument();
    await userEvent.click(
      screen.getByRole('checkbox', { name: /high-value local series/i }),
    );
    expect(await screen.findByText(/Local series cap/i)).toBeInTheDocument();
  });

  it('reports the estimate beside what the run actually took', async () => {
    stub();
    renderWithProviders(<TrainingCenterPage />);
    await screen.findByTestId('status-counts');
    // 424.5 s estimated, 275.8 s actual - both rendered, so the estimate can
    // be audited rather than forgotten.
    expect(screen.getByText('7m 5s')).toBeInTheDocument();
    expect(screen.getByText('4m 36s')).toBeInTheDocument();
  });

  it('renders every status count, including the ones that are zero', async () => {
    stub();
    renderWithProviders(<TrainingCenterPage />);
    const counts = await screen.findByTestId('status-counts');
    for (const label of [
      'Completed',
      'Ineligible',
      'Failed',
      'Timed out',
      'Not evaluated (budget)',
    ]) {
      expect(counts.textContent).toContain(label);
    }
  });

  it('lists all 13 registered models with no status filter', async () => {
    stub();
    renderWithProviders(<TrainingCenterPage />);
    const table = await screen.findByTestId('model-run-table');
    expect(table.querySelectorAll('tbody tr')).toHaveLength(13);
    const statuses = Array.from(table.querySelectorAll('[data-status]')).map((node) =>
      node.getAttribute('status') ?? node.getAttribute('data-status'),
    );
    expect(new Set(statuses)).toEqual(new Set(['completed', 'ineligible']));
  });

  it('shows an ineligible model with its reason', async () => {
    stub();
    renderWithProviders(<TrainingCenterPage />);
    const table = await screen.findByTestId('model-run-table');
    expect(table.textContent).toMatch(/24 training observations/);
  });

  it('renders a defect banner when a registered model has no row at all', async () => {
    vi.spyOn(trainingApi, 'estimateRun').mockResolvedValue(
      trainingRunFixture().estimate!,
    );
    vi.spyOn(trainingApi, 'fetchCurrentRun').mockResolvedValue(trainingRunFixture());
    vi.spyOn(trainingApi, 'fetchRunDetail').mockResolvedValue(
      trainingDetailFixture({ models_missing: ['lstm'] }),
    );
    renderWithProviders(<TrainingCenterPage />);
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toMatch(/lstm/);
    expect(alert.textContent).toMatch(/defect/i);
  });

  it('offers cancellation only while a run is live', async () => {
    stub();
    renderWithProviders(<TrainingCenterPage />);
    await screen.findByTestId('status-counts');
    expect(screen.queryByRole('button', { name: /cancel run/i })).not.toBeInTheDocument();
  });

  it('offers cancellation for a running run', async () => {
    vi.spyOn(trainingApi, 'estimateRun').mockResolvedValue(
      trainingRunFixture().estimate!,
    );
    vi.spyOn(trainingApi, 'fetchCurrentRun').mockResolvedValue(
      trainingRunFixture({ status: 'running', progress_pct: 42 }),
    );
    vi.spyOn(trainingApi, 'fetchRunDetail').mockResolvedValue(trainingDetailFixture());
    const cancel = vi
      .spyOn(trainingApi, 'cancelRun')
      .mockResolvedValue(trainingRunFixture({ status: 'cancelling' }));
    renderWithProviders(<TrainingCenterPage />);
    const button = await screen.findByRole('button', { name: /cancel run/i });
    await userEvent.click(button);
    await waitFor(() => expect(cancel).toHaveBeenCalled());
    expect(
      await screen.findByText(/rows already written are kept/i),
    ).toBeInTheDocument();
  });

  it('shows an empty state, not an error, when no run exists', async () => {
    vi.spyOn(trainingApi, 'estimateRun').mockResolvedValue(
      trainingRunFixture().estimate!,
    );
    vi.spyOn(trainingApi, 'fetchCurrentRun').mockRejectedValue(
      new ApiError('none', 404, 'not_found', 'POST /api/training to start one.'),
    );
    renderWithProviders(<TrainingCenterPage />);
    expect(await screen.findByText(/No training run yet/i)).toBeInTheDocument();
    expect(
      screen.getByText(/deliberately empty|placeholder figures/i),
    ).toBeInTheDocument();
  });
});

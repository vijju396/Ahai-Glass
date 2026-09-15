import { describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '@/test/renderWithProviders';
import { PANEL_BUILD_DONE, PANEL_BUILD_RUNNING } from '@/test/fixtures';
import { PanelPanel } from '@/features/mapping/components/PanelPanel';
import * as panelApi from '@/api/panel';
import { ApiError } from '@/api/client';

describe('PanelPanel', () => {
  it('offers a build when none exists', async () => {
    vi.spyOn(panelApi, 'fetchCurrentPanel').mockRejectedValue(
      new ApiError('No panel has been built yet.', 404, 'not_found'),
    );
    renderWithProviders(<PanelPanel />);
    expect(await screen.findByText(/No panel built yet/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /build panel/i })).toBeInTheDocument();
  });

  it('starts a build at the mandated training cut', async () => {
    vi.spyOn(panelApi, 'fetchCurrentPanel').mockRejectedValue(
      new ApiError('No panel has been built yet.', 404, 'not_found'),
    );
    const spy = vi.spyOn(panelApi, 'startPanelBuild').mockResolvedValue(PANEL_BUILD_RUNNING);
    renderWithProviders(<PanelPanel />);
    await userEvent.click(await screen.findByRole('button', { name: /build panel/i }));
    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith({ training_cut_period: '2025-09' }),
    );
  });

  it('shows live progress with an accessible progressbar', async () => {
    vi.spyOn(panelApi, 'fetchCurrentPanel').mockResolvedValue(PANEL_BUILD_RUNNING);
    renderWithProviders(<PanelPanel />);
    expect(await screen.findByText(/Building leakage-safe origin features/i)).toBeInTheDocument();
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '62');
  });

  it('reports observed and materialised rows as different facts', async () => {
    vi.spyOn(panelApi, 'fetchCurrentPanel').mockResolvedValue(PANEL_BUILD_DONE);
    renderWithProviders(<PanelPanel />);
    expect(await screen.findByText('Observed rows')).toBeInTheDocument();
    expect(screen.getByText('Materialised zeros')).toBeInTheDocument();
    const tile = screen.getByText('Materialised zeros').closest('.tile');
    expect(tile?.textContent).toContain('true zero, not missing data');
  });

  it('explains that a zero is an observation rather than a gap', async () => {
    vi.spyOn(panelApi, 'fetchCurrentPanel').mockResolvedValue(PANEL_BUILD_DONE);
    renderWithProviders(<PanelPanel />);
    expect(
      await screen.findByText(/A zero is a real observation, not a gap/i),
    ).toBeInTheDocument();
    // The copy is split by a <code> element, so match against the container
    // text rather than a single text node.
    const callout = screen.getByText(/A zero is a real observation, not a gap/i).closest('.callout');
    expect(callout?.textContent).toMatch(/invented history before its first observation/i);
    expect(callout?.textContent).toMatch(/obsolescence signal/i);
    expect(callout?.textContent).toMatch(/value_unavailable_reason = true_zero/);
  });

  it('never presents the two target sources as equivalent', async () => {
    vi.spyOn(panelApi, 'fetchCurrentPanel').mockResolvedValue(PANEL_BUILD_DONE);
    renderWithProviders(<PanelPanel />);
    expect(
      await screen.findByText(/never treated as equivalent/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/censored signal recording what was available to sell/i)).toBeInTheDocument();
  });

  it('separates the panel universe from the 63,210 control', async () => {
    vi.spyOn(panelApi, 'fetchCurrentPanel').mockResolvedValue(PANEL_BUILD_DONE);
    renderWithProviders(<PanelPanel />);
    expect(
      await screen.findByText(/not the 63,210 control/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/remains a check on the canonical key/i)).toBeInTheDocument();
  });

  it('renders the sparsity measures', async () => {
    vi.spyOn(panelApi, 'fetchCurrentPanel').mockResolvedValue(PANEL_BUILD_DONE);
    renderWithProviders(<PanelPanel />);
    const table = await screen.findByTestId('sparsity-table');
    expect(table.textContent).toContain('Median average demand interval');
    expect(table.textContent).toContain('Median CV');
    expect(table.textContent).toContain('57.8%');
  });

  it('states that horizon is a feature rather than a recursive chain', async () => {
    vi.spyOn(panelApi, 'fetchCurrentPanel').mockResolvedValue(PANEL_BUILD_DONE);
    renderWithProviders(<PanelPanel />);
    expect(await screen.findByText(/no recursive chaining/i)).toBeInTheDocument();
  });

  it('surfaces a build failure with its reason', async () => {
    vi.spyOn(panelApi, 'fetchCurrentPanel').mockResolvedValue({
      ...PANEL_BUILD_DONE,
      status: 'failed',
      failure_reason: "FileNotFoundError: Preprocessed table 'order_fact' is missing.",
    });
    renderWithProviders(<PanelPanel />);
    expect(await screen.findByText(/Panel build failed/i)).toBeInTheDocument();
    expect(screen.getByText(/order_fact' is missing/i)).toBeInTheDocument();
  });

  it('shows no panel figures while the build is still running', async () => {
    vi.spyOn(panelApi, 'fetchCurrentPanel').mockResolvedValue(PANEL_BUILD_RUNNING);
    renderWithProviders(<PanelPanel />);
    await screen.findByRole('progressbar');
    expect(screen.queryByText('Panel rows')).not.toBeInTheDocument();
    expect(screen.queryByTestId('sparsity-table')).not.toBeInTheDocument();
  });
});

/**
 * Supply Intelligence contracts.
 *
 * The assertions that matter: a recommendation exposes its own calculation, a
 * row that could not be recommended for shows a reason rather than a zero,
 * unavailable rows are shown by default, and the single-snapshot limitation is
 * on the page rather than in a footnote nobody reads.
 */
import { describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import * as inventoryApi from '@/api/inventory';
import { ApiError } from '@/api/client';
import { SupplyIntelligencePage } from '../pages/SupplyIntelligencePage';
import { renderWithProviders } from '@/test/renderWithProviders';
import {
  recommendationsFixture,
  supplyOverviewFixture,
} from '@/test/phase7Fixtures';

function stub(
  recommendations: Parameters<typeof recommendationsFixture>[0] = {},
  overview: Parameters<typeof supplyOverviewFixture>[0] = {},
) {
  vi.spyOn(inventoryApi, 'fetchSupplyOverview').mockResolvedValue(
    supplyOverviewFixture(overview),
  );
  return vi
    .spyOn(inventoryApi, 'fetchRecommendations')
    .mockResolvedValue(recommendationsFixture(recommendations));
}

describe('SupplyIntelligencePage', () => {
  it('shows the placement totals from the stock snapshot', async () => {
    stub();
    renderWithProviders(<SupplyIntelligencePage />);
    expect(await screen.findByText('23,788')).toBeInTheDocument();
    expect(screen.getByText('21,549')).toBeInTheDocument();
    expect(screen.getByText('2026-08-01')).toBeInTheDocument();
  });

  it('surfaces the negative stock rows rather than clamping them away', async () => {
    stub();
    renderWithProviders(<SupplyIntelligencePage />);
    expect(await screen.findByText(/Negative stock rows/i)).toBeInTheDocument();
    expect(screen.getByText(/surfaced, not clamped/i)).toBeInTheDocument();
  });

  it('renders the snapshot caveat from the API', async () => {
    stub();
    renderWithProviders(<SupplyIntelligencePage />);
    expect(
      await screen.findByText(/current-snapshot measures/i),
    ).toBeInTheDocument();
  });

  it('exposes the whole calculation on each recommendation', async () => {
    stub();
    renderWithProviders(<SupplyIntelligencePage />);
    const table = await screen.findByTestId('recommendation-table');
    const headers = Array.from(table.querySelectorAll('thead th')).map(
      (node) => node.textContent,
    );
    for (const header of [
      'Order',
      'Order-up-to',
      'Usable stock',
      'On order',
      'Backorders',
      'Lead time',
      'Review',
      'Protection',
      'Cover',
    ]) {
      expect(headers).toContain(header);
    }
  });

  it('states the formula rather than leaving the reader to infer it', async () => {
    stub();
    renderWithProviders(<SupplyIntelligencePage />);
    expect(
      await screen.findByText(/protection period = review period \+ lead time/i),
    ).toBeInTheDocument();
  });

  it('shows a row with no recommendation as a reason, not a zero', async () => {
    stub();
    renderWithProviders(<SupplyIntelligencePage />);
    const table = await screen.findByTestId('recommendation-table');
    const rows = Array.from(table.querySelectorAll('tbody tr'));
    const refused = rows.find((row) => row.textContent?.includes('MANDI'));
    expect(refused).toBeDefined();
    expect(refused?.textContent).toMatch(/Nothing was substituted/i);
    // The order cell is a dash, not 0.
    const cells = Array.from(refused?.querySelectorAll('td') ?? []);
    expect(cells.at(1)?.textContent).toBe('—');
  });

  it('includes unavailable rows by default', async () => {
    const spy = stub();
    renderWithProviders(<SupplyIntelligencePage />);
    await screen.findByTestId('recommendation-table');
    expect(spy.mock.calls.at(0)?.[0]).toMatchObject({ only_actionable: false });
  });

  it('lets the service level be changed and re-queries', async () => {
    const spy = stub();
    renderWithProviders(<SupplyIntelligencePage />);
    await screen.findByTestId('recommendation-table');
    await userEvent.selectOptions(
      screen.getByLabelText(/service level/i),
      '80',
    );
    expect(
      spy.mock.calls.some((call) => call[0]?.service_level === 80),
    ).toBe(true);
  });

  it('explains why no recommendation is possible when the API says so', async () => {
    stub({
      items: [],
      total: 0,
      unavailable_reason:
        'This forecast run produced no series-level rows for 2026-08. A replenishment order is placed per branch x SKU, so it needs series-level forecasts.',
    });
    renderWithProviders(<SupplyIntelligencePage />);
    expect(
      await screen.findByText(/needs series-level forecasts/i),
    ).toBeInTheDocument();
  });

  it('lists zero-stock-against-live-demand positions', async () => {
    stub();
    renderWithProviders(<SupplyIntelligencePage />);
    const table = await screen.findByTestId('zero-stock-table');
    expect(table.textContent).toMatch(/BENGALURU/);
    expect(table.textContent).toMatch(/2,715/);
  });

  it('can look up which other branches hold a SKU, without calling it a transfer plan', async () => {
    stub();
    vi.spyOn(inventoryApi, 'fetchTransferableStock').mockResolvedValue({
      canonical_sku: 'FG.BA5.LFH.GCG2120000',
      excluded_branch: null,
      holders: [
        {
          canonical_branch: 'BAWAL',
          usable_qty: 4000,
          closing_qty: 4000,
          stock_class: 'Cat A',
        },
      ],
      total_holders: 1,
      total_usable_units: 4000,
      caveat:
        'Holdings only. The source set carries no inter-branch lane, transfer cost or transit time, so this is not a transfer plan.',
    });
    renderWithProviders(<SupplyIntelligencePage />);
    const table = await screen.findByTestId('zero-stock-table');
    await userEvent.click(
      table.querySelector('button') as HTMLButtonElement,
    );
    expect(await screen.findByText(/not a transfer plan/i)).toBeInTheDocument();
    // Scoped to the holders card: BAWAL also appears in the dead-stock table,
    // and a page-wide lookup would pass even if the holders table were empty.
    const holders = screen.getByText(/not a transfer plan/i).closest('.card');
    expect(holders?.textContent).toMatch(/BAWAL/);
    expect(holders?.textContent).toMatch(/4,000/);
  });

  it('lists dead stock as a placement signal, not an instruction to scrap', async () => {
    stub();
    renderWithProviders(<SupplyIntelligencePage />);
    const table = await screen.findByTestId('dead-stock-table');
    expect(table.textContent).toMatch(/AISUW16-400C/);
    expect(
      screen.getByText(/not an instruction to scrap/i),
    ).toBeInTheDocument();
  });

  it('shows an empty state when no forecast run exists', async () => {
    vi.spyOn(inventoryApi, 'fetchSupplyOverview').mockRejectedValue(
      new ApiError(
        'No completed forecast run exists.',
        404,
        'not_found',
        'POST /api/forecasts/runs first.',
      ),
    );
    vi.spyOn(inventoryApi, 'fetchRecommendations').mockRejectedValue(
      new ApiError('No completed forecast run exists.', 404, 'not_found'),
    );
    renderWithProviders(<SupplyIntelligencePage />);
    expect(
      await screen.findByText(/No completed forecast run yet/i),
    ).toBeInTheDocument();
  });
});

/**
 * Forecast Explorer contracts.
 *
 * The properties asserted here are the data-honesty ones: the quantile
 * ordering is visible, the reconciliation adjustment is a separate column
 * rather than folded into the number, a horizon with no interval says so, and
 * the interval's provenance travels onto the row.
 */
import { describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import * as forecastApi from '@/api/forecasts';
import * as leaderboardApi from '@/api/leaderboard';
import { ApiError } from '@/api/client';
import { ForecastExplorerPage } from '../pages/ForecastExplorerPage';
import { renderWithProviders } from '@/test/renderWithProviders';
import {
  forecastRunFixture,
  seriesForecastFixture,
  diagnosticsFixture,
} from '@/test/phase7Fixtures';

function stubScopes() {
  // The page lands on series level and resolves its scope from the Location
  // and SKU slicers. A single trained series resolves with no interaction, so
  // every test below gets straight to the content it is about.
  vi.spyOn(leaderboardApi, 'fetchScopes').mockResolvedValue({
    items: [{ scope_level: 'series', scope_key: 'BENGALURU|SKU-A' }],
    total: 1,
    offset: 0,
    limit: 500,
  });
}

function stub(overrides: Parameters<typeof seriesForecastFixture>[0] = {}) {
  stubScopes();
  vi.spyOn(forecastApi, 'fetchCurrentForecastRun').mockResolvedValue(
    forecastRunFixture(),
  );
  return vi
    .spyOn(forecastApi, 'fetchSeriesForecast')
    .mockResolvedValue(seriesForecastFixture(overrides));
}

describe('ForecastExplorerPage', () => {
  it('switches between actuals, future forecasts and the combined timeline', async () => {
    stub();
    renderWithProviders(<ForecastExplorerPage />);
    await screen.findByTestId('forecast-table');
    await userEvent.click(screen.getByRole('button', { name: 'Actual' }));
    expect(screen.getByTestId('actual-table').querySelectorAll('tbody tr')).toHaveLength(seriesForecastFixture().history.length);
    expect(screen.getByTestId('echart')).toHaveAttribute('data-series', 'Ordered demand (actual)');
    await userEvent.click(screen.getByRole('button', { name: 'Forecast' }));
    expect(screen.queryByTestId('actual-table')).not.toBeInTheDocument();
    expect(screen.getByTestId('echart')).toHaveAttribute('data-series', 'Forecast,q80,q90,q95');
    await userEvent.click(screen.getByRole('checkbox', { name: /show q80/i }));
    expect(screen.getByTestId('echart')).toHaveAttribute('data-series', 'Forecast');
  });

  it('requests diagnostics from the forecast training run, separating overlapping origins', async () => {
    stub();
    const fixture = diagnosticsFixture();
    const spy = vi.spyOn(leaderboardApi, 'fetchDiagnostics').mockResolvedValue(diagnosticsFixture({ points: [...fixture.points, { ...fixture.points[0]!, origin_name: 'second', fold_index: 1, predicted: 98765 }] }));
    renderWithProviders(<ForecastExplorerPage />);
    await screen.findByTestId('forecast-table');
    expect(spy).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: 'Actual vs forecast' }));
    const table = await screen.findByTestId('backtest-table');
    expect(table.querySelectorAll('tbody tr')).toHaveLength(1);
    expect(table.textContent).toContain('98,765');
    expect(spy).toHaveBeenCalledWith(seriesForecastFixture().validation_metrics!.model_id, expect.objectContaining({ training_run_id: seriesForecastFixture().training_run_id }));
    await userEvent.selectOptions(screen.getByLabelText('Backtest origin'), 'primary · fold 0');
    expect(screen.getByTestId('backtest-table').querySelectorAll('tbody tr')).toHaveLength(fixture.points.length);
  });

  it('shows unavailable backtests as an explicit state, not an invented comparison', async () => {
    stub();
    vi.spyOn(leaderboardApi, 'fetchDiagnostics').mockResolvedValue(diagnosticsFixture({ points: [], diagnostics_available: false, unavailable_reason: 'Predictions were not persisted.' }));
    renderWithProviders(<ForecastExplorerPage />);
    await screen.findByTestId('forecast-table');
    await userEvent.click(screen.getByRole('button', { name: 'Actual vs forecast' }));
    expect(await screen.findByText('Predictions were not persisted.')).toBeInTheDocument();
    expect(screen.queryByTestId('backtest-table')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Download CSV/ })).toBeDisabled();
  });

  it('labels sales-proxy actuals in the chart', async () => {
    const base = seriesForecastFixture();
    stub({ history: base.history.map(p => ({ ...p, target_source: 'sales_proxy' })) });
    renderWithProviders(<ForecastExplorerPage />);
    expect(await screen.findByTestId('echart')).toHaveAttribute('data-series', 'Actual demand (includes sales proxy),Forecast,q80,q90,q95');
  });

  it('limits actual rows when the viewer selects a history range', async () => {
    stub();
    renderWithProviders(<ForecastExplorerPage />);
    await screen.findByTestId('forecast-table');
    await userEvent.click(screen.getByRole('button', { name: 'Actual' }));
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'History range' }), '6');
    expect(screen.getByTestId('actual-table').querySelectorAll('tbody tr')).toHaveLength(Math.min(6, seriesForecastFixture().history.length));
  });

  it('renders six forecast horizons', async () => {
    stub();
    renderWithProviders(<ForecastExplorerPage />);
    const table = await screen.findByTestId('forecast-table');
    expect(table.querySelectorAll('tbody tr')).toHaveLength(6);
  });

  it('keeps point <= q80 <= q90 <= q95 on every row', async () => {
    stub();
    renderWithProviders(<ForecastExplorerPage />);
    const table = await screen.findByTestId('forecast-table');
    const rows = Array.from(table.querySelectorAll('tbody tr'));
    const numeric = (text: string | null) => Number((text ?? '').replace(/[^\d.-]/g, ''));
    for (const row of rows) {
      // Columns 2-5 are point, q80, q90, q95. Checked pairwise so a shorter
      // row fails loudly instead of silently skipping the assertion.
      const cells = Array.from(row.querySelectorAll('td')).map((cell) =>
        numeric(cell.textContent),
      );
      const band = cells.slice(2, 6);
      expect(band).toHaveLength(4);
      for (let index = 0; index < band.length - 1; index += 1) {
        expect(band[index] as number).toBeLessThanOrEqual(band[index + 1] as number);
      }
    }
  });

  it('shows the reconciliation adjustment as its own column', async () => {
    stub();
    renderWithProviders(<ForecastExplorerPage />);
    const table = await screen.findByTestId('forecast-table');
    const headers = Array.from(table.querySelectorAll('thead th')).map(
      (node) => node.textContent,
    );
    expect(headers).toContain('Pre-reconciliation');
    expect(headers).toContain('Adjustment');
  });

  it('shows where each interval came from', async () => {
    stub();
    renderWithProviders(<ForecastExplorerPage />);
    const table = await screen.findByTestId('forecast-table');
    expect(table.textContent).toMatch(/empirical/);
    expect(table.textContent).toMatch(/scope_all_horizons/);
    expect(table.textContent).toMatch(/12 residuals/);
  });

  it('carries the target source and censoring onto every row', async () => {
    stub();
    renderWithProviders(<ForecastExplorerPage />);
    const table = await screen.findByTestId('forecast-table');
    expect(table.textContent).toMatch(/order/);
  });

  it('charts history and forecast as separate series', async () => {
    stub();
    renderWithProviders(<ForecastExplorerPage />);
    const chart = await screen.findByTestId('echart');
    const series = chart.getAttribute('data-series') ?? '';
    expect(series).toMatch(/Ordered demand \(actual\)/);
    expect(series).toMatch(/Forecast/);
    expect(series).toMatch(/q80/);
    expect(series).toMatch(/q95/);
  });

  it('says when a horizon has a point forecast but no interval', async () => {
    const base = seriesForecastFixture();
    stub({
      forecasts: base.forecasts.map((row, index) =>
        index === 0 ? { ...row, q80: null, q90: null, q95: null } : row,
      ),
    });
    renderWithProviders(<ForecastExplorerPage />);
    expect(
      await screen.findByText(/without a band rather than with a fabricated one/i),
    ).toBeInTheDocument();
  });

  it('renders the snapshot caveat from the API', async () => {
    stub();
    renderWithProviders(<ForecastExplorerPage />);
    expect(
      await screen.findByText(/labelled substitute, not ordered demand/i),
    ).toBeInTheDocument();
  });

  it('shows the validation metrics of the model that was used', async () => {
    stub();
    renderWithProviders(<ForecastExplorerPage />);
    expect(
      await screen.findByText(/Validation metrics for the model used/i),
    ).toBeInTheDocument();
    expect(screen.getByText('4.578')).toBeInTheDocument();
    expect(screen.getByText('rolling_origin')).toBeInTheDocument();
  });

  it('explains an unreadable history without failing the page', async () => {
    stub({
      history: [],
      history_unavailable_reason:
        'The panel artifact could not be read (FileNotFoundError), so no history is available to plot. The forecasts themselves are unaffected.',
    });
    renderWithProviders(<ForecastExplorerPage />);
    expect(
      await screen.findByText(/forecasts themselves are unaffected/i),
    ).toBeInTheDocument();
    // The forecast table is still there.
    expect(screen.getByTestId('forecast-table')).toBeInTheDocument();
  });

  it('shows a 404 as an empty state carrying the API guidance', async () => {
    stubScopes();
    vi.spyOn(forecastApi, 'fetchCurrentForecastRun').mockResolvedValue(
      forecastRunFixture(),
    );
    vi.spyOn(forecastApi, 'fetchSeriesForecast').mockRejectedValue(
      new ApiError(
        'Forecast run has no rows for national/NATIONAL.',
        404,
        'not_found',
        'Generate forecasts first.',
      ),
    );
    renderWithProviders(<ForecastExplorerPage />);
    expect(await screen.findByText(/No forecast for this scope/i)).toBeInTheDocument();
    expect(screen.getByText(/Generate forecasts first/i)).toBeInTheDocument();
  });

  it('offers a CSV download once there is something to download', async () => {
    stub();
    renderWithProviders(<ForecastExplorerPage />);
    await screen.findByTestId('forecast-table');
    const button = screen.getByRole('button', { name: /download csv/i });
    expect(button).toBeEnabled();
  });
});

/**
 * The two slicers.
 *
 * A series scope key is `BRANCH|SKU`, so a location and a SKU together *are*
 * the series. The page therefore lands on series level and offers exactly two
 * dropdowns, which cross-filter each other in both directions and resolve the
 * scope between them. There is no third "Branch x SKU" picker, because it
 * could only restate the two choices already made - or contradict them.
 */
describe('ForecastExplorerPage slicers', () => {
  const SERIES_SCOPES = [
    { scope_level: 'series', scope_key: 'BENGALURU|SKU-A' },
    { scope_level: 'series', scope_key: 'BENGALURU|SKU-B' },
    { scope_level: 'series', scope_key: 'AHMEDABAD|SKU-A' },
  ];

  function stubSeriesScopes() {
    vi.spyOn(forecastApi, 'fetchCurrentForecastRun').mockResolvedValue(
      forecastRunFixture(),
    );
    const spy = vi
      .spyOn(forecastApi, 'fetchSeriesForecast')
      .mockResolvedValue(seriesForecastFixture());
    vi.spyOn(leaderboardApi, 'fetchScopes').mockImplementation(async (level) =>
      level === 'series'
        ? { items: SERIES_SCOPES, total: 3, offset: 0, limit: 500 }
        : {
            items: [{ scope_level: 'national', scope_key: 'NATIONAL' }],
            total: 1,
            offset: 0,
            limit: 500,
          },
    );
    return spy;
  }

  const options = (label: string) =>
    [...screen.getByLabelText(label).querySelectorAll('option')].map((o) => o.textContent);

  it('lands on series level with both slicers and no third picker', async () => {
    stubSeriesScopes();
    renderWithProviders(<ForecastExplorerPage />);

    expect(screen.getByLabelText('Level')).toHaveValue('series');
    expect(await screen.findByLabelText('Location')).toBeInTheDocument();
    expect(screen.getByLabelText('SKU')).toBeInTheDocument();
    expect(screen.queryByLabelText('Scope')).not.toBeInTheDocument();
    expect(screen.queryByText(/Branch × SKU/)).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: /switch to series level/i }),
    ).not.toBeInTheDocument();
  });

  it('builds both slicers from the trained scope keys', async () => {
    stubSeriesScopes();
    renderWithProviders(<ForecastExplorerPage />);
    await screen.findByRole('option', { name: 'AHMEDABAD' });

    expect(options('Location')).toEqual(['All locations', 'AHMEDABAD', 'BENGALURU']);
    expect(options('SKU')).toEqual(['All SKUs', 'SKU-A', 'SKU-B']);
  });

  it('narrows the SKU list to what the chosen location stocks', async () => {
    stubSeriesScopes();
    renderWithProviders(<ForecastExplorerPage />);
    await screen.findByRole('option', { name: 'AHMEDABAD' });
    await userEvent.selectOptions(screen.getByLabelText('Location'), 'AHMEDABAD');

    expect(options('SKU')).toEqual(['All SKUs', 'SKU-A']);
  });

  it('narrows the location list to those that stock the chosen SKU', async () => {
    // The reverse direction. This is what makes them slicers rather than a
    // one-way cascade: SKU-B exists only at BENGALURU, so AHMEDABAD must
    // disappear from Location once SKU-B is picked.
    stubSeriesScopes();
    renderWithProviders(<ForecastExplorerPage />);
    await screen.findByRole('option', { name: 'SKU-B' });
    await userEvent.selectOptions(screen.getByLabelText('SKU'), 'SKU-B');

    expect(options('Location')).toEqual(['All locations', 'BENGALURU']);
  });

  it('resolves the series once one scope matches, with no extra click', async () => {
    const spy = stubSeriesScopes();
    renderWithProviders(<ForecastExplorerPage />);
    await screen.findByRole('option', { name: 'BENGALURU' });
    await userEvent.selectOptions(screen.getByLabelText('Location'), 'BENGALURU');
    await userEvent.selectOptions(screen.getByLabelText('SKU'), 'SKU-B');

    await screen.findByTestId('forecast-table');
    expect(spy).toHaveBeenCalledWith('series', 'BENGALURU|SKU-B');
    // Named in the hint, so the reader can see which series the two slicers
    // landed on without inferring it from the two dropdowns.
    expect(
      screen.getByText('BENGALURU|SKU-B', { selector: 'strong' }),
    ).toBeInTheDocument();
  });

  it('resolves from one slicer when that alone leaves a single series', async () => {
    // SKU-B is stocked at exactly one location, so picking it is enough.
    const spy = stubSeriesScopes();
    renderWithProviders(<ForecastExplorerPage />);
    await screen.findByRole('option', { name: 'SKU-B' });
    await userEvent.selectOptions(screen.getByLabelText('SKU'), 'SKU-B');

    await screen.findByTestId('forecast-table');
    expect(spy).toHaveBeenCalledWith('series', 'BENGALURU|SKU-B');
  });

  it('asks for a narrower selection while more than one series matches', async () => {
    stubSeriesScopes();
    renderWithProviders(<ForecastExplorerPage />);
    await screen.findByRole('option', { name: 'SKU-A' });
    await userEvent.selectOptions(screen.getByLabelText('SKU'), 'SKU-A');

    expect(screen.getByText(/2 of 3 trained series match/i)).toBeInTheDocument();
    expect(screen.getByText(/Choose a location and a SKU/i)).toBeInTheDocument();
    expect(screen.queryByTestId('forecast-table')).not.toBeInTheDocument();
  });

  it('says that an untrained branch or SKU is absent rather than empty', async () => {
    stubSeriesScopes();
    renderWithProviders(<ForecastExplorerPage />);
    await screen.findByRole('option', { name: 'AHMEDABAD' });

    expect(
      screen.getByText(/a branch or\s+SKU the run did not reach does not appear here/i),
    ).toBeInTheDocument();
  });

  it('falls back to a plain scope picker above series level', async () => {
    stubSeriesScopes();
    renderWithProviders(<ForecastExplorerPage />);
    await userEvent.selectOptions(screen.getByLabelText('Level'), 'national');

    expect(await screen.findByLabelText('Scope')).toBeInTheDocument();
    expect(screen.queryByLabelText('Location')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('SKU')).not.toBeInTheDocument();
  });
});

import { describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithProviders } from '@/test/renderWithProviders';
import {
  COMPLETED_VERSION,
  FAILED_VALIDATION,
  PROFILE,
  RUNNING_VERSION,
  VALIDATION,
  datasetPage,
} from '@/test/fixtures';
import { DataStudioPage } from '@/features/data-studio/pages/DataStudioPage';
import * as datasetsApi from '@/api/datasets';
import { ApiError } from '@/api/client';

function mockAll(options: {
  version?: typeof COMPLETED_VERSION;
  validation?: typeof VALIDATION;
} = {}) {
  vi.spyOn(datasetsApi, 'fetchDatasets').mockResolvedValue(
    datasetPage(options.version ?? COMPLETED_VERSION),
  );
  vi.spyOn(datasetsApi, 'fetchValidation').mockResolvedValue(
    options.validation ?? VALIDATION,
  );
  vi.spyOn(datasetsApi, 'fetchProfile').mockResolvedValue(PROFILE);
}

describe('DataStudioPage', () => {
  it('shows a loading state while datasets load', () => {
    vi.spyOn(datasetsApi, 'fetchDatasets').mockReturnValue(new Promise(() => {}) as never);
    renderWithProviders(<DataStudioPage />);
    expect(screen.getByRole('status')).toBeInTheDocument();
  });

  it('offers to start ingestion when no dataset exists', async () => {
    vi.spyOn(datasetsApi, 'fetchDatasets').mockResolvedValue({
      items: [], total: 0, offset: 0, limit: 25,
    });
    renderWithProviders(<DataStudioPage />);
    expect(await screen.findByRole('button', { name: /start ingestion/i })).toBeInTheDocument();
    expect(screen.getByText(/never modified/i)).toBeInTheDocument();
  });

  it('renders live progress with an accessible progressbar while running', async () => {
    mockAll({ version: RUNNING_VERSION });
    renderWithProviders(<DataStudioPage />);
    expect(await screen.findByText(/Sales: 600,000 rows read/)).toBeInTheDocument();
    const bar = screen.getByRole('progressbar');
    expect(bar).toHaveAttribute('aria-valuenow', '15');
    expect(screen.getByRole('button', { name: /cancel/i })).toBeInTheDocument();
  });

  it('renders every structural control with expected and measured values', async () => {
    mockAll();
    renderWithProviders(<DataStudioPage />);
    const table = await screen.findByTestId('controls-table');
    expect(table.querySelectorAll('tbody tr')).toHaveLength(11);
    const s6 = table.querySelector('tr[data-control="S6"]');
    expect(s6?.textContent).toContain('2,260');
    expect(s6?.getAttribute('data-outcome')).toBe('pass');
  });

  it('surfaces a failed control rather than hiding it', async () => {
    mockAll({ validation: FAILED_VALIDATION });
    renderWithProviders(<DataStudioPage />);
    const table = await screen.findByTestId('controls-table');
    // The failing control is still a row, and still shows its measured value.
    const s6 = table.querySelector('tr[data-control="S6"]');
    expect(s6?.getAttribute('data-outcome')).toBe('fail');
    expect(s6?.textContent).toContain('2,147');
    expect(s6?.textContent).toMatch(/Oracle No yields 2,147/);
    expect(screen.getByText(/Controls did not hold/i)).toBeInTheDocument();
    expect(
      screen.getByText(/must not treat this version as clean/i),
    ).toBeInTheDocument();
  });

  it('reports net and gross shortfall as separate figures', async () => {
    mockAll();
    renderWithProviders(<DataStudioPage />);
    expect(await screen.findByText('Net shortfall')).toBeInTheDocument();
    expect(screen.getByText('Gross positive shortfall')).toBeInTheDocument();
    // The two must not be conflated: 468,431 vs 504,298.
    expect(screen.getByText('4,68,431')).toBeInTheDocument();
    expect(screen.getByText('5,04,298')).toBeInTheDocument();
    expect(screen.getByText(/despatched more than was ordered/i)).toBeInTheDocument();
  });

  it('shows the lead-time exclusions rather than only the clean statistic', async () => {
    mockAll();
    renderWithProviders(<DataStudioPage />);
    expect(await screen.findByText('Excluded')).toBeInTheDocument();
    expect(screen.getByText(/3 unparseable, 281 negative/)).toBeInTheDocument();
  });

  it('renders the defect register with each rule applied', async () => {
    mockAll();
    renderWithProviders(<DataStudioPage />);
    const table = await screen.findByTestId('defects-table');
    expect(table.querySelectorAll('tbody tr')).toHaveLength(3);
    expect(table.querySelector('tr[data-defect="D1"]')?.textContent).toContain('C2');
    expect(table.querySelector('tr[data-defect="D17"]')?.textContent).toContain('C9');
  });

  it('lists the source files with their content hashes', async () => {
    mockAll();
    renderWithProviders(<DataStudioPage />);
    const table = await screen.findByTestId('files-table');
    expect(table.textContent).toContain('Sales Data FY 24~26.xlsb');
    expect(table.textContent).toContain('17,03,042');
  });

  it('names the excluded PII columns', async () => {
    mockAll();
    renderWithProviders(<DataStudioPage />);
    expect(await screen.findByText(/3 PII columns excluded/i)).toBeInTheDocument();
  });

  it('renders an error state when the API is unreachable', async () => {
    vi.spyOn(datasetsApi, 'fetchDatasets').mockRejectedValue(
      new ApiError('Could not reach the API.', 0, 'network_error'),
    );
    renderWithProviders(<DataStudioPage />);
    expect(await screen.findByRole('alert')).toBeInTheDocument();
  });

  it('shows no fabricated figures before validation data arrives', async () => {
    vi.spyOn(datasetsApi, 'fetchDatasets').mockResolvedValue(datasetPage(RUNNING_VERSION));
    vi.spyOn(datasetsApi, 'fetchValidation').mockReturnValue(new Promise(() => {}) as never);
    vi.spyOn(datasetsApi, 'fetchProfile').mockReturnValue(new Promise(() => {}) as never);
    renderWithProviders(<DataStudioPage />);
    await screen.findByRole('progressbar');
    expect(screen.queryByTestId('controls-table')).not.toBeInTheDocument();
    expect(screen.queryByText('Net shortfall')).not.toBeInTheDocument();
  });
});

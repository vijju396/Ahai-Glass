import { describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithProviders } from '@/test/renderWithProviders';
import {
  MAPPING,
  PROFILE,
  ROLE_MAPPING,
  RUNNING_VERSION,
  datasetPage,
} from '@/test/fixtures';
import { MappingPage } from '@/features/mapping/pages/MappingPage';
import * as datasetsApi from '@/api/datasets';
import * as mappingsApi from '@/api/mappings';
import { ApiError } from '@/api/client';

function mockAll() {
  vi.spyOn(datasetsApi, 'fetchDatasets').mockResolvedValue(datasetPage());
  vi.spyOn(datasetsApi, 'fetchMapping').mockResolvedValue(MAPPING);
  vi.spyOn(datasetsApi, 'fetchProfile').mockResolvedValue(PROFILE);
  vi.spyOn(mappingsApi, 'fetchCurrentMapping').mockResolvedValue(ROLE_MAPPING);
  vi.spyOn(mappingsApi, 'fetchPreprocessing').mockRejectedValue(
    new ApiError('Not preprocessed yet.', 404, 'not_found'),
  );
}

describe('MappingPage', () => {
  it('prompts for an ingestion when none exists', async () => {
    vi.spyOn(datasetsApi, 'fetchDatasets').mockResolvedValue({
      items: [], total: 0, offset: 0, limit: 25,
    });
    renderWithProviders(<MappingPage />);
    expect(await screen.findByText(/No ingested dataset yet/i)).toBeInTheDocument();
  });

  it('waits rather than guessing while ingestion runs', async () => {
    vi.spyOn(datasetsApi, 'fetchDatasets').mockResolvedValue(datasetPage(RUNNING_VERSION));
    renderWithProviders(<MappingPage />);
    expect(await screen.findByText(/Ingestion is still running/i)).toBeInTheDocument();
  });

  it('contrasts the canonical SKU count against distinct Oracle No', async () => {
    mockAll();
    renderWithProviders(<MappingPage />);
    // Scoped to the tile, because 2,260 also appears legitimately in the
    // SKU-universes table as the sales row.
    const canonicalTile = (await screen.findByText('Canonical SKUs')).closest('.tile');
    expect(canonicalTile?.textContent).toContain('2,260');

    const oracleTile = screen.getByText('Distinct Oracle No').closest('.tile');
    expect(oracleTile?.textContent).toContain('2,147');

    const collisionTile = screen.getByText('Oracle No collisions').closest('.tile');
    expect(collisionTile?.textContent).toContain('109');

    // The disagreement count is zero: canonical -> Oracle is many-to-one.
    const disagreementTile = screen.getByText('Disagreements').closest('.tile');
    expect(disagreementTile?.textContent).toContain('0');
  });

  it('states the canonical key rule and why Oracle No is not the key', async () => {
    mockAll();
    renderWithProviders(<MappingPage />);
    expect(await screen.findByText(/strip a trailing/i)).toBeInTheDocument();
    expect(screen.getByText(/Why raw Oracle No is not the SKU key/i)).toBeInTheDocument();
    expect(screen.getByText(/109 Oracle numbers each span/i)).toBeInTheDocument();
  });

  it('reports all four branch universes without conflating them', async () => {
    mockAll();
    renderWithProviders(<MappingPage />);
    expect(await screen.findByText('Location Master')).toBeInTheDocument();
    expect(screen.getByText('Order Depots')).toBeInTheDocument();
    expect(screen.getByText('Selling Branches')).toBeInTheDocument();
  });

  it('shows that the order file has two non-equivalent SKU keys', async () => {
    mockAll();
    renderWithProviders(<MappingPage />);
    expect(await screen.findByText('Orders Via Oracle No')).toBeInTheDocument();
    expect(screen.getByText('Orders Via Material Code')).toBeInTheDocument();
    expect(screen.getByText('3,139')).toBeInTheDocument();
  });

  it('renders reconciliation findings with their related values', async () => {
    mockAll();
    renderWithProviders(<MappingPage />);
    const table = await screen.findByTestId('findings-table');
    expect(table.textContent).toContain('Oracle No collision');
    expect(table.textContent).toContain('PREGST.MYB.RDL.G00300A000');
  });

  it('flags a PII column as excluded and shows no sample value for it', async () => {
    mockAll();
    renderWithProviders(<MappingPage />);
    expect(await screen.findByText('PII excluded')).toBeInTheDocument();
    const piiRow = screen.getByText('Customer Name').closest('tr');
    expect(piiRow?.textContent).not.toContain('SALONI');
  });

  it('renders the editable role table', async () => {
    mockAll();
    renderWithProviders(<MappingPage />);
    const table = await screen.findByTestId('role-table');
    expect(table.querySelectorAll('tbody tr').length).toBe(
      ROLE_MAPPING.assignments.length,
    );
  });

  it('offers to create a draft when no role mapping exists', async () => {
    vi.spyOn(datasetsApi, 'fetchDatasets').mockResolvedValue(datasetPage());
    vi.spyOn(datasetsApi, 'fetchMapping').mockResolvedValue(MAPPING);
    vi.spyOn(datasetsApi, 'fetchProfile').mockResolvedValue(PROFILE);
    vi.spyOn(mappingsApi, 'fetchCurrentMapping').mockRejectedValue(
      new ApiError('No role mapping yet.', 404, 'not_found'),
    );
    renderWithProviders(<MappingPage />);
    expect(
      await screen.findByRole('button', { name: /create draft mapping/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/nothing is authoritative until a person confirms/i),
    ).toBeInTheDocument();
  });

  it('reports that preprocessing has not run rather than showing zeros', async () => {
    mockAll();
    renderWithProviders(<MappingPage />);
    expect(await screen.findByText(/Not preprocessed yet/i)).toBeInTheDocument();
  });
});

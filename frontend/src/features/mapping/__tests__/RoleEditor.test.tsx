import { describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '@/test/renderWithProviders';
import {
  BLOCKED_ROLE_MAPPING,
  CONFIRMED_ROLE_MAPPING,
  REVIEWED_ROLE_MAPPING,
  ROLE_MAPPING,
} from '@/test/fixtures';
import { RoleEditor } from '@/features/mapping/components/RoleEditor';
import * as mappingsApi from '@/api/mappings';
import { ApiError } from '@/api/client';

describe('RoleEditor', () => {
  it('renders one row per column assignment', () => {
    renderWithProviders(<RoleEditor mapping={ROLE_MAPPING} datasetId="ds1" />);
    const table = screen.getByTestId('role-table');
    expect(table.querySelectorAll('tbody tr')).toHaveLength(
      ROLE_MAPPING.assignments.length,
    );
  });

  it('makes a draft role editable', () => {
    renderWithProviders(<RoleEditor mapping={ROLE_MAPPING} datasetId="ds1" />);
    expect(
      screen.getByRole('combobox', { name: /Role for Quantity in orders/i }),
    ).toBeEnabled();
  });

  it('disambiguates same-named columns from different sources', () => {
    /** Both the order and sales files carry a column called "Quantity", so the
     *  accessible name must include the source or a screen-reader user cannot
     *  tell the two selects apart. */
    renderWithProviders(<RoleEditor mapping={ROLE_MAPPING} datasetId="ds1" />);
    expect(
      screen.getByRole('combobox', { name: /Role for Quantity in orders/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('combobox', { name: /Role for Quantity in sales/i }),
    ).toBeInTheDocument();
  });

  it('never lets a PII column be reassigned, even in a draft', () => {
    /** The UI must not offer an action the API would reject. */
    renderWithProviders(<RoleEditor mapping={ROLE_MAPPING} datasetId="ds1" />);
    expect(
      screen.queryByRole('combobox', { name: /Role for Invoice No in orders/i }),
    ).not.toBeInTheDocument();
    const piiRow = document.querySelector('tr[data-column="orders.Invoice No"]');
    expect(piiRow?.textContent).toContain('Excluded (PII)');
  });

  it('sends the edited role to the API and clears the suggestion', async () => {
    const spy = vi
      .spyOn(mappingsApi, 'updateAssignments')
      .mockResolvedValue(REVIEWED_ROLE_MAPPING);
    renderWithProviders(<RoleEditor mapping={ROLE_MAPPING} datasetId="ds1" />);
    await userEvent.selectOptions(
      screen.getByRole('combobox', { name: /Role for Despatch Qty in orders/i }),
      'historical_driver',
    );
    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith('map1', [
        expect.objectContaining({
          source_role: 'orders',
          column_name: 'Despatch Qty',
          role: 'historical_driver',
        }),
      ]),
    );
  });

  it('marks unreviewed assignments distinctly from reviewed ones', () => {
    renderWithProviders(<RoleEditor mapping={ROLE_MAPPING} datasetId="ds1" />);
    const body = screen.getByTestId('role-table').querySelector('tbody');
    // Scoped to the body: "Reviewed" is also the column header.
    expect(body?.querySelectorAll('.pill-warn').length).toBeGreaterThan(0);
    expect(body?.textContent).toContain('Suggested');
    expect(body?.textContent).not.toContain('Reviewed');
  });

  it('marks every assignment reviewed once confirmed', () => {
    renderWithProviders(<RoleEditor mapping={CONFIRMED_ROLE_MAPPING} datasetId="ds1" />);
    const body = screen.getByTestId('role-table').querySelector('tbody');
    expect(body?.textContent).toContain('Reviewed');
    expect(body?.textContent).not.toContain('Suggested');
  });

  it('shows why a column is not future-known', () => {
    renderWithProviders(<RoleEditor mapping={ROLE_MAPPING} datasetId="ds1" />);
    const body = screen.getByTestId('role-table').querySelector('tbody');
    expect(body?.textContent).toMatch(/A price can change/i);
    expect(body?.textContent).toMatch(/supply-censored/i);
  });

  it('renders a blocking rule with its remediation', () => {
    renderWithProviders(<RoleEditor mapping={BLOCKED_ROLE_MAPPING} datasetId="ds1" />);
    const rule = document.querySelector('[data-rule="R5"]');
    expect(rule?.textContent).toContain('blocking');
    expect(rule?.textContent).toContain('MRP Rate');
    expect(rule?.textContent).toMatch(/leakage/i);
  });

  it('disables confirmation while a required role is unreviewed', () => {
    renderWithProviders(<RoleEditor mapping={ROLE_MAPPING} datasetId="ds1" />);
    expect(screen.getByRole('button', { name: /confirm mapping/i })).toBeDisabled();
    expect(screen.getByText(/3 required role\(s\) still need review/i)).toBeInTheDocument();
  });

  it('states why confirmation is blocked when a rule fails', () => {
    renderWithProviders(<RoleEditor mapping={BLOCKED_ROLE_MAPPING} datasetId="ds1" />);
    expect(screen.getByText(/1 blocking rule\(s\) must be resolved/i)).toBeInTheDocument();
  });

  it('still requires a name before confirming a reviewed mapping', async () => {
    renderWithProviders(<RoleEditor mapping={REVIEWED_ROLE_MAPPING} datasetId="ds1" />);
    const button = screen.getByRole('button', { name: /confirm mapping/i });
    expect(button).toBeDisabled();
    await userEvent.type(screen.getByLabelText(/confirmed by/i), 'planner');
    expect(button).toBeEnabled();
  });

  it('confirms with the reviewer name', async () => {
    const spy = vi
      .spyOn(mappingsApi, 'confirmMapping')
      .mockResolvedValue(CONFIRMED_ROLE_MAPPING);
    renderWithProviders(<RoleEditor mapping={REVIEWED_ROLE_MAPPING} datasetId="ds1" />);
    await userEvent.type(screen.getByLabelText(/confirmed by/i), 'planner');
    await userEvent.click(screen.getByRole('button', { name: /confirm mapping/i }));
    await waitFor(() => expect(spy).toHaveBeenCalledWith('map1', 'planner'));
  });

  it('surfaces the API reason when confirmation is refused', async () => {
    vi.spyOn(mappingsApi, 'confirmMapping').mockRejectedValue(
      new ApiError(
        'The target and time columns must be reviewed before confirmation.',
        422,
        'validation_failed',
        undefined,
        undefined,
        { unreviewed_columns: ['Quantity'] },
      ),
    );
    renderWithProviders(<RoleEditor mapping={REVIEWED_ROLE_MAPPING} datasetId="ds1" />);
    await userEvent.type(screen.getByLabelText(/confirmed by/i), 'planner');
    await userEvent.click(screen.getByRole('button', { name: /confirm mapping/i }));
    expect(await screen.findByText(/Unreviewed: Quantity/i)).toBeInTheDocument();
  });

  it('states how many columns a person actually reviewed', () => {
    /** On a confirmed mapping most columns still read "Suggested" - they kept
     *  their template default. Saying so is more honest than relabelling them,
     *  but it needs explaining or it looks like confirmation did not stick. */
    renderWithProviders(<RoleEditor mapping={CONFIRMED_ROLE_MAPPING} datasetId="ds1" />);
    expect(
      screen.getByText(/columns were reviewed by a person/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/requires the target\s+and time columns to be reviewed explicitly/i),
    ).toBeInTheDocument();
  });

  it('locks every role once the mapping is confirmed', () => {
    renderWithProviders(<RoleEditor mapping={CONFIRMED_ROLE_MAPPING} datasetId="ds1" />);
    expect(screen.queryByRole('combobox', { name: /Role for/i })).not.toBeInTheDocument();
    expect(screen.getByText(/immutable, because a training run/i)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /confirm mapping/i })).not.toBeInTheDocument();
  });

  it('offers preprocessing only once confirmed', () => {
    const { unmount } = renderWithProviders(
      <RoleEditor mapping={ROLE_MAPPING} datasetId="ds1" />,
    );
    expect(screen.queryByRole('button', { name: /run preprocessing/i })).not.toBeInTheDocument();
    unmount();
    renderWithProviders(<RoleEditor mapping={CONFIRMED_ROLE_MAPPING} datasetId="ds1" />);
    expect(screen.getByRole('button', { name: /run preprocessing/i })).toBeInTheDocument();
  });

  it('filters the table by source', async () => {
    renderWithProviders(<RoleEditor mapping={ROLE_MAPPING} datasetId="ds1" />);
    await userEvent.selectOptions(
      screen.getByRole('combobox', { name: /filter by source file/i }),
      'sales',
    );
    const table = screen.getByTestId('role-table');
    expect(table.querySelectorAll('tbody tr')).toHaveLength(1);
  });

  it('filters the table by role', async () => {
    renderWithProviders(<RoleEditor mapping={ROLE_MAPPING} datasetId="ds1" />);
    await userEvent.selectOptions(
      screen.getByRole('combobox', { name: /filter by role/i }),
      'target_column',
    );
    const table = screen.getByTestId('role-table');
    expect(table.querySelectorAll('tbody tr')).toHaveLength(2);
  });

  it('can filter down to unreviewed columns only', async () => {
    renderWithProviders(<RoleEditor mapping={CONFIRMED_ROLE_MAPPING} datasetId="ds1" />);
    await userEvent.click(screen.getByLabelText(/unreviewed only/i));
    expect(screen.getByText(/No columns match these filters/i)).toBeInTheDocument();
  });

  it('warns that several columns look like demand', () => {
    renderWithProviders(<RoleEditor mapping={ROLE_MAPPING} datasetId="ds1" />);
    expect(screen.getByText(/Only ordered quantity is the target/i)).toBeInTheDocument();
  });
});

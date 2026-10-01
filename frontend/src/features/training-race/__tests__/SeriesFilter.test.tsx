/**
 * The Training filter after the aggregate scopes came off it (D-133).
 *
 * The thing worth a test is an *absence*: "All locations" and "All SKUs" used
 * to be the first option in each list and resolved to a separately fitted model
 * over summed demand. Putting either one back is a one-line edit, and nothing
 * else on the page would complain — so the guarantee is asserted here.
 *
 * `MarkedSelect` is a button plus a portalled listbox rather than a native
 * `<select>`, so the options only exist once the control is opened. These tests
 * open it the way a reader does.
 */
import { describe, expect, it, vi } from 'vitest';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '@/test/renderWithProviders';
import { SeriesFilter } from '@/features/training-race/SeriesFilter';
import * as trainingApi from '@/api/training';

const LINES = [
  { key: 'BENGALURU|FG.AAA', branch: 'BENGALURU', sku: 'FG.AAA' },
  { key: 'BENGALURU|FG.BBB', branch: 'BENGALURU', sku: 'FG.BBB' },
  { key: 'DELHI-1|FG.BBB', branch: 'DELHI-1', sku: 'FG.BBB' },
  { key: 'DELHI-1|FG.CCC', branch: 'DELHI-1', sku: 'FG.CCC' },
];

function renderFilter(branch: string, sku: string) {
  // The dot hook reads two endpoints; neither is what this file is about, so
  // both are left pending and the marks simply never appear.
  vi.spyOn(trainingApi, 'fetchCurrentRun').mockReturnValue(new Promise(() => {}) as never);
  vi.spyOn(trainingApi, 'fetchAccuracyWindows').mockReturnValue(new Promise(() => {}) as never);
  const onChange = vi.fn();
  renderWithProviders(
    <SeriesFilter lines={LINES} branch={branch} sku={sku} onChange={onChange} />,
  );
  return onChange;
}

/** Open one of the two controls and read the rows it offers. */
async function open(name: RegExp) {
  await userEvent.click(screen.getByRole('button', { name }));
  const list = screen.getByRole('listbox', { name });
  return {
    labels: within(list).getAllByRole('option').map((o) => o.textContent?.trim()),
    choose: (label: string) =>
      userEvent.click(within(list).getByText(label)),
  };
}

describe('the Training line filter', () => {
  it('offers no "All locations" and no "All SKUs"', async () => {
    renderFilter('BENGALURU', 'FG.AAA');
    expect((await open(/location/i)).labels).toEqual(['BENGALURU', 'DELHI-1']);
    expect((await open(/sku/i)).labels).toEqual(['FG.AAA', 'FG.BBB']);
  });

  it('has no Clear control, because there is no empty state to clear to', () => {
    renderFilter('BENGALURU', 'FG.AAA');
    expect(screen.queryByRole('button', { name: /^clear$/i })).toBeNull();
  });

  it('lists every location regardless of the SKU in hand', async () => {
    // The lists used to narrow each other, which hid DELHI-1 while a SKU it
    // does not stock was selected. Picking a location now *moves* the SKU, so
    // hiding the location would remove the only way to get there.
    renderFilter('BENGALURU', 'FG.AAA');
    expect((await open(/location/i)).labels).toContain('DELHI-1');
  });

  it('lands on a SKU the chosen location stocks', async () => {
    const onChange = renderFilter('BENGALURU', 'FG.AAA');
    await (await open(/location/i)).choose('DELHI-1');
    // FG.AAA is not stocked at DELHI-1, so the SKU moves with the location
    // rather than leaving the page on a pair no run trained.
    expect(onChange).toHaveBeenCalledWith({ branch: 'DELHI-1', sku: 'FG.BBB' });
  });

  it('keeps the SKU when the chosen location does stock it', async () => {
    const onChange = renderFilter('BENGALURU', 'FG.BBB');
    await (await open(/location/i)).choose('DELHI-1');
    expect(onChange).toHaveBeenCalledWith({ branch: 'DELHI-1', sku: 'FG.BBB' });
  });

  it('says the figures below cover every line, not the selected one', () => {
    renderFilter('BENGALURU', 'FG.AAA');
    expect(screen.getByText(/cover all 4 lines/i)).toBeInTheDocument();
  });
});

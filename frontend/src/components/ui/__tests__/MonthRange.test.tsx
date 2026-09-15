/**
 * The history-window pickers.
 *
 * Two properties carry weight here. The control is a **month** calendar, not a
 * day one, because the panel holds one row per branch × SKU × month and a day
 * picker would invite a question the data cannot answer. And the calendar is
 * bounded by the panel's own first and last month, in both directions, so it
 * cannot produce a query that returns an empty page.
 */
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MonthRange, monthLabel } from '../MonthRange';

const FIRST = '2024-04';
const LAST = '2026-07';

function setup(overrides: Partial<Parameters<typeof MonthRange>[0]> = {}) {
  const onFromChange = vi.fn();
  const onToChange = vi.fn();
  render(
    <MonthRange
      from=""
      to=""
      onFromChange={onFromChange}
      onToChange={onToChange}
      first={FIRST}
      last={LAST}
      months={28}
      {...overrides}
    />,
  );
  return { onFromChange, onToChange };
}

describe('monthLabel', () => {
  it('renders a period as a readable month and full year', () => {
    expect(monthLabel('2026-07')).toBe('Jul 2026');
    expect(monthLabel('2024-04')).toBe('Apr 2024');
  });

  it('passes anything that is not a month through untouched', () => {
    expect(monthLabel('2026-Q3')).toBe('2026-Q3');
    expect(monthLabel(null)).toBe('');
    expect(monthLabel(undefined)).toBe('');
  });
});

describe('MonthRange', () => {
  it('uses a month calendar, not a day one', () => {
    // The panel has no day-level values. A date input would let a reader ask
    // for a day and be handed a month, which is exactly the sort of quiet
    // fabrication the data contract forbids.
    setup();

    expect(screen.getByLabelText('From')).toHaveAttribute('type', 'month');
    expect(screen.getByLabelText('To')).toHaveAttribute('type', 'month');
  });

  it('bounds the calendar by the first and last month in the data', () => {
    setup();

    expect(screen.getByLabelText('From')).toHaveAttribute('min', FIRST);
    expect(screen.getByLabelText('From')).toHaveAttribute('max', LAST);
    expect(screen.getByLabelText('To')).toHaveAttribute('min', FIRST);
    expect(screen.getByLabelText('To')).toHaveAttribute('max', LAST);
  });

  it('states the available range, so an empty result is never a mystery', () => {
    setup();

    expect(screen.getByText(/Apr 2024 – Jul 2026/)).toBeInTheDocument();
    expect(screen.getByText(/28 months/)).toBeInTheDocument();
  });

  it('stops the two ends crossing over', () => {
    // A backwards window returns nothing. Rather than let the page go empty
    // and say why afterwards, the pickers constrain each other.
    setup({ from: '2025-01', to: '2025-06' });

    expect(screen.getByLabelText('From')).toHaveAttribute('max', '2025-06');
    expect(screen.getByLabelText('To')).toHaveAttribute('min', '2025-01');
  });

  it('clamps a typed month that falls outside the data', async () => {
    // `min`/`max` bound the calendar widget, but typing is not bounded by
    // them, so an out-of-range value has to be corrected rather than sent.
    const { onFromChange } = setup();
    const from = screen.getByLabelText('From');

    await userEvent.type(from, '2019-01');

    expect(onFromChange).toHaveBeenCalled();
    for (const [value] of onFromChange.mock.calls) {
      expect(value >= FIRST || value === '').toBe(true);
    }
  });

  it('offers a way back to the whole history once a window is set', async () => {
    const { onFromChange, onToChange } = setup({ from: '2025-01', to: '2025-06' });

    await userEvent.click(screen.getByRole('button', { name: /full history/i }));

    expect(onFromChange).toHaveBeenCalledWith('');
    expect(onToChange).toHaveBeenCalledWith('');
  });

  it('hides that control while no window is set, since there is nothing to clear', () => {
    setup();

    expect(screen.queryByRole('button', { name: /full history/i })).not.toBeInTheDocument();
  });

  it('says what an empty picker will default to', () => {
    setup();

    expect(screen.getByText('Defaults to Apr 2024')).toBeInTheDocument();
    expect(screen.getByText('Defaults to Jul 2026')).toBeInTheDocument();
  });

  it('renders without a known range, before the filters have loaded', () => {
    setup({ first: null, last: null, months: undefined });

    expect(screen.getByLabelText('From')).not.toHaveAttribute('min');
    expect(screen.queryByText(/Data available/)).not.toBeInTheDocument();
    expect(screen.getByText('Defaults to the earliest month')).toBeInTheDocument();
  });
});

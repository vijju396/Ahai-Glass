/**
 * `tickNum` exists because `num` stops at thousands (D-154).
 *
 * A log axis reaches the millions routinely — its top decade is
 * `10 ** ceil(log10(max))`, so a 348K column puts a 1,000,000 tick on the
 * axis. `num` renders that as "1000.0K": seven characters in a 46px gutter,
 * which is why the y-axis labels on Demand by Glass Type and Demand by Value
 * Class were cut off at the left edge when a panel was expanded.
 */
import { describe, expect, it } from 'vitest';
import { inr, num, tickNum } from '../Dashboard';

describe('tickNum keeps an axis label inside its gutter', () => {
  it('abbreviates the millions that num leaves at four digits of K', () => {
    expect(num(1_000_000)).toBe('1000.0K');
    expect(tickNum(1_000_000)).toBe('1M');

    expect(num(10_000_000)).toBe('10000.0K');
    expect(tickNum(10_000_000)).toBe('10M');
  });

  it('drops the trailing .0 on an exact decade, which is every log tick', () => {
    // The whole reason the axis is wide: these are the labels it carries.
    expect([1, 100, 1_000, 10_000, 100_000, 1_000_000].map(tickNum)).toEqual([
      '1',
      '100',
      '1K',
      '10K',
      '100K',
      '1M',
    ]);
  });

  it('keeps one decimal where it carries information', () => {
    expect(tickNum(55_000)).toBe('55K');
    expect(tickNum(1_674_700)).toBe('1.7M');
    expect(tickNum(2_500)).toBe('2.5K');
  });

  it('never exceeds six characters across the range a unit axis carries', () => {
    // The measured failure was a 7-character label in a 46px gutter. The range
    // asserted here is the real one: these are the smallest and largest
    // quantities on the page (6 units of Temp W/s, 4,140,507 network units)
    // plus the decade above the largest, which is where a log axis puts its
    // top tick.
    for (const v of [0, 6, 99, 2_600, 347_700, 1_674_700, 4_140_507, 10_000_000]) {
      expect(tickNum(v).length).toBeLessThanOrEqual(6);
    }
  });

  it('is not applied to money, which has its own Indian-numbering formatter', () => {
    // `tickNum` has no billions step and does not need one: a rupee axis uses
    // `inr`, which goes to lakh and crore. Guarding the boundary rather than
    // asserting a step that would never fire - and if a money axis is ever
    // pointed at `tickNum`, this is the line that explains why not.
    expect(tickNum(13_460_208_858)).toBe('13460.2M');
    expect(inr(13_460_208_858)).toBe('₹1346.02Cr');
  });

  it('handles negatives and the empty reading the same way num does', () => {
    expect(tickNum(-2_600_000)).toBe('-2.6M');
    expect(tickNum(null)).toBe('—');
    expect(tickNum(undefined)).toBe('—');
    expect(tickNum(Number.NaN)).toBe('—');
  });

  it('leaves num alone, because the KPI tiles read it literally', () => {
    // "2602.4K units" on a tile carries four more significant digits than
    // "2.6M units" would, and a tile is read rather than scanned.
    expect(num(2_602_392)).toBe('2602.4K');
  });
});

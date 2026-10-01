/**
 * The rule that keeps Training and Forecasting pointed at a trained line.
 *
 * Both pages lost their "All locations" and "All SKUs" options, which used to
 * resolve to the national and per-branch *aggregate* scopes (D-133). That makes
 * the repair rule load-bearing rather than cosmetic: there is no empty state to
 * fall back into, so a pair that names no trained line is a dead page.
 */
import { describe, expect, it } from 'vitest';
import { firstPair, repair, type Line } from '@/app/seriesPair';

/** Deliberately not in sorted order, and deliberately ragged: DELHI-1 stocks a
 *  SKU BENGALURU does not, which is the case the repair exists for. */
const LINES: Line[] = [
  { key: 'DELHI-1|FG.BBB', branch: 'DELHI-1', sku: 'FG.BBB' },
  { key: 'BENGALURU|FG.BBB', branch: 'BENGALURU', sku: 'FG.BBB' },
  { key: 'BENGALURU|FG.AAA', branch: 'BENGALURU', sku: 'FG.AAA' },
  { key: 'DELHI-1|FG.CCC', branch: 'DELHI-1', sku: 'FG.CCC' },
];

describe('the line a page opens on', () => {
  it('is the first in branch then SKU order, not the first in the payload', () => {
    // The payload leads with DELHI-1. Opening on whatever the API happened to
    // return first would make the landing line depend on row order.
    expect(firstPair(LINES)).toEqual({ branch: 'BENGALURU', sku: 'FG.AAA' });
  });

  it('is empty when the run trained nothing, rather than inventing a pair', () => {
    expect(firstPair([])).toEqual({ branch: '', sku: '' });
  });
});

describe('repairing the other slicer', () => {
  it('leaves a pair alone when it already names a trained line', () => {
    const next = { branch: 'DELHI-1', sku: 'FG.BBB' };
    expect(repair(LINES, next, 'branch')).toEqual(next);
  });

  it('moves the SKU when the chosen location does not stock it', () => {
    // "pick a branch, land on a SKU": BENGALURU has no FG.CCC, so the page
    // lands on BENGALURU's first SKU instead of showing nothing.
    expect(repair(LINES, { branch: 'BENGALURU', sku: 'FG.CCC' }, 'branch')).toEqual({
      branch: 'BENGALURU',
      sku: 'FG.AAA',
    });
  });

  it('moves the location when the chosen SKU is not stocked there', () => {
    expect(repair(LINES, { branch: 'BENGALURU', sku: 'FG.CCC' }, 'sku')).toEqual({
      branch: 'DELHI-1',
      sku: 'FG.CCC',
    });
  });

  it('never overrides the slicer the reader just touched', () => {
    // Both directions of the same case. Repairing the field someone just set
    // would fight them, so the branch survives a branch change and the SKU
    // survives a SKU change even though the *pair* is the same both times.
    expect(repair(LINES, { branch: 'BENGALURU', sku: 'FG.CCC' }, 'branch').branch).toBe(
      'BENGALURU',
    );
    expect(repair(LINES, { branch: 'BENGALURU', sku: 'FG.CCC' }, 'sku').sku).toBe('FG.CCC');
  });

  it('picks the first repair alphabetically, so the landing line is reproducible', () => {
    const wide: Line[] = [
      { key: 'PUNE|FG.ZZZ', branch: 'PUNE', sku: 'FG.ZZZ' },
      { key: 'PUNE|FG.AAA', branch: 'PUNE', sku: 'FG.AAA' },
      { key: 'PUNE|FG.MMM', branch: 'PUNE', sku: 'FG.MMM' },
    ];
    expect(repair(wide, { branch: 'PUNE', sku: 'NOT.STOCKED' }, 'branch').sku).toBe('FG.AAA');
  });

  it('returns the unrepairable pair unchanged rather than guessing', () => {
    // Neither half exists. Silently jumping to an unrelated line would be
    // worse than the page saying it has nothing for this pair.
    const orphan = { branch: 'NOWHERE', sku: 'FG.NONE' };
    expect(repair(LINES, orphan, 'branch')).toEqual(orphan);
    expect(repair(LINES, orphan, 'sku')).toEqual(orphan);
    expect(repair([], orphan, 'branch')).toEqual(orphan);
  });
});

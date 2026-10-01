/**
 * Keeping a branch × SKU pair pointed at a line that was actually trained.
 *
 * Training and Forecasting both open on a real line now rather than on an
 * aggregate, so both need the same three answers: which line to start on, what
 * to do when a location is picked that does not stock the current SKU, and
 * what to do when a SKU is picked that the current location does not carry.
 * The rule is the same in both places and the logic is not page-specific, so it
 * lives here rather than being written twice and drifting (D-133).
 *
 * **There is deliberately no empty state.** The old pages offered "All
 * locations" and "All SKUs", which resolved to the national and branch
 * *aggregate* scopes — separately fitted models over summed demand, whose error
 * says nothing about any line underneath. Those are gone from the pickers, so
 * every selection here resolves to one branch × SKU or to nothing at all.
 */

export interface Line {
  key: string;
  branch: string;
  sku: string;
}

/** The pair to open on: the first line in branch order, then SKU order.
 *
 *  Deliberately the first and not the best. A page that silently opened on its
 *  strongest line would flatter the run — the green dot already marks the
 *  strong ones, and a reader can take it or leave it. Alphabetical is a rule
 *  anyone can check; "whichever scored highest" is a thumb on the scale.
 */
export function firstPair(lines: Line[]): { branch: string; sku: string } {
  if (lines.length === 0) return { branch: '', sku: '' };
  const sorted = [...lines].sort(
    (a, b) => a.branch.localeCompare(b.branch) || a.sku.localeCompare(b.sku),
  );
  const head = sorted[0]!;
  return { branch: head.branch, sku: head.sku };
}

/**
 * The pair that results from changing one slicer, with the other repaired.
 *
 * Picking a location that does not stock the current SKU moves the SKU to the
 * first one that location *does* stock, rather than leaving the page on a pair
 * no run ever trained. That is the "pick a branch, land on a SKU" behaviour:
 * the selection is never allowed to sit in a hole.
 *
 * The slicer the reader just touched is never overridden — only the other one
 * moves. Repairing the field someone just set would fight them.
 */
export function repair(
  lines: Line[],
  next: { branch: string; sku: string },
  changed: 'branch' | 'sku',
): { branch: string; sku: string } {
  if (lines.some((l) => l.branch === next.branch && l.sku === next.sku)) return next;

  if (changed === 'branch') {
    const skus = lines
      .filter((l) => l.branch === next.branch)
      .map((l) => l.sku)
      .sort();
    return skus.length > 0 ? { branch: next.branch, sku: skus[0]! } : next;
  }

  const branches = lines
    .filter((l) => l.sku === next.sku)
    .map((l) => l.branch)
    .sort();
  return branches.length > 0 ? { branch: branches[0]!, sku: next.sku } : next;
}

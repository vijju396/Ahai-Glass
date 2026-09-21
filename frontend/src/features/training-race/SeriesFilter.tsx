/**
 * One branch x SKU line, chosen once, for the whole Training page.
 *
 * This used to live inside the leaderboard header, which made it look like a
 * leaderboard control. It is not: the choice governs the accuracy panel and
 * the leaderboard together, so it belongs above both, where a filter that
 * changes the page below it is read as a filter rather than a table option.
 *
 * The lines offered come from the **run**, not from the panel. A scoped run
 * covers a subset of the network, and offering a line it never trained would
 * open a leaderboard with nothing on it. The two slicers narrow each other for
 * the same reason — the same rule the Per Branch & SKU page follows.
 *
 * A 4px green dot, visible only while the list is open, marks an option whose
 * lines **all** forecast at 85% or better on their own, measured on months no
 * model was fitted on. "All" rather than "any" is the honest rule: with no
 * location picked, a SKU carries one line per branch, and a dot that meant
 * "strong somewhere" would send a demo into a branch that is not. Options with
 * a mixed record simply carry no dot, so the mark never has to be walked back.
 * It is left unexplained on purpose — a nudge toward a line, not a claim the
 * page has to defend.
 */
import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { fetchScopes, leaderboardKeys } from '@/api/leaderboard';
import { useLinesAtTarget } from './useLinesAtTarget';
import { MarkedSelect } from '@/components/ui/MarkedSelect';

const SELECT =
  'rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-2 py-1 text-[11px] text-[var(--color-text)]';

export interface SeriesSelection {
  branch: string;
  sku: string;
  /** The `BRANCH|SKU` key, or null while either slicer is still empty or the
   *  pair was never trained. */
  scopeKey: string | null;
  /** Both slicers are set but the run never trained that pair. */
  untrained: boolean;
}

export function useSeriesLines() {
  const scopes = useQuery({
    queryKey: leaderboardKeys.scopes('series'),
    queryFn: () => fetchScopes('series', 2000),
    retry: false,
    staleTime: 60_000,
  });

  return useMemo(
    () =>
      (scopes.data?.items ?? []).flatMap((row) => {
        const cut = row.scope_key.indexOf('|');
        if (cut <= 0) return [];
        return [
          {
            key: row.scope_key,
            branch: row.scope_key.slice(0, cut),
            sku: row.scope_key.slice(cut + 1),
          },
        ];
      }),
    [scopes.data],
  );
}

/** Resolves a branch/SKU pair against the lines this run actually trained. */
export function resolveSelection(
  lines: { key: string; branch: string; sku: string }[],
  branch: string,
  sku: string,
): SeriesSelection {
  const scopeKey =
    branch && sku ? (lines.find((l) => l.branch === branch && l.sku === sku)?.key ?? null) : null;
  return { branch, sku, scopeKey, untrained: !!branch && !!sku && !scopeKey };
}

export function SeriesFilter({
  lines,
  branch,
  sku,
  onChange,
}: {
  lines: { key: string; branch: string; sku: string }[];
  branch: string;
  sku: string;
  onChange: (next: { branch: string; sku: string }) => void;
}) {
  const atTarget = useLinesAtTarget();

  /* An option is strong when every line it currently resolves to clears the
     target. `candidates` is that set of lines, narrowed by the other slicer —
     the same narrowing the option list itself uses, so the dot always describes
     exactly what picking the option would show. */
  const strong = useMemo(() => {
    const mark = (candidates: { key: string }[]) =>
      candidates.length > 0 && candidates.every((l) => atTarget.has(l.key));
    return {
      branch: (b: string) => mark(lines.filter((l) => l.branch === b && (!sku || l.sku === sku))),
      sku: (s: string) => mark(lines.filter((l) => l.sku === s && (!branch || l.branch === branch))),
    };
  }, [lines, atTarget, branch, sku]);

  const branchOptions = useMemo(
    () => [...new Set(lines.filter((l) => !sku || l.sku === sku).map((l) => l.branch))].sort(),
    [lines, sku],
  );
  const skuOptions = useMemo(
    () => [...new Set(lines.filter((l) => !branch || l.branch === branch).map((l) => l.sku))].sort(),
    [lines, branch],
  );
  const selected = branch && sku;

  return (
    <div className="flex flex-wrap items-center gap-2 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface-2)] px-3 py-2">
      <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--color-text-muted)]">
        Showing
      </span>
      <MarkedSelect
        label="Location"
        className={SELECT}
        value={branch}
        onChange={(next) => onChange({ branch: next, sku })}
        options={[
          { value: '', label: 'All locations' },
          ...branchOptions.map((b) => ({ value: b, label: b, marked: strong.branch(b) })),
        ]}
      />
      <MarkedSelect
        label="SKU"
        className={SELECT}
        value={sku}
        onChange={(next) => onChange({ branch, sku: next })}
        options={[
          { value: '', label: 'All SKUs' },
          ...skuOptions.map((s) => ({ value: s, label: s, marked: strong.sku(s) })),
        ]}
      />
      {(branch || sku) && (
        <button
          type="button"
          className="link-button text-[11px]"
          onClick={() => onChange({ branch: '', sku: '' })}
        >
          Clear
        </button>
      )}
      <span className="ml-auto text-[10px] text-[var(--color-text-muted)]">
        {selected
          ? 'Accuracy and the leaderboard below are for this line alone.'
          : `Every figure below covers all ${lines.length} branch × SKU lines this run trained.`}
      </span>
    </div>
  );
}

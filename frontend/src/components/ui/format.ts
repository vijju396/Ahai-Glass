/**
 * Display formatting only.
 *
 * Nothing here derives a value: no forecast, no quantile, no order quantity.
 * The backend computes; React formats. `src/test/no-duplicate-registry.test.ts`
 * asserts that separation.
 */

const INTEGER = new Intl.NumberFormat('en-IN');

export function formatInt(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—';
  return INTEGER.format(Math.round(value));
}

export function formatPct(
  value: number | null | undefined,
  digits = 2,
  scale: 'ratio' | 'percent' = 'percent',
): string {
  if (value === null || value === undefined) return '—';
  const asPercent = scale === 'ratio' ? value * 100 : value;
  return `${asPercent.toFixed(digits)}%`;
}

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined) return '—';
  if (bytes < 1024) return `${bytes} B`;
  const units = ['KB', 'MB', 'GB'];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(1)} ${units[unit]}`;
}

export function formatSeconds(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return '—';
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes}m ${Math.round(seconds % 60)}s`;
}

export function formatDays(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—';
  return `${value.toFixed(0)} d`;
}

/** Shortens a SHA-256 for display without implying the full value is absent. */
export function shortHash(hash: string | null | undefined): string {
  if (!hash) return '—';
  return `${hash.slice(0, 12)}…`;
}

export function titleiseRole(role: string): string {
  return role.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

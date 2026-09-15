/**
 * Single source of truth for the training race: families, metric, and timing.
 *
 * **Why `MODELS` is not a literal list here.** The brief asks for one entry per
 * model in this file. This application cannot have that: the thirteen models
 * are registered and asserted server-side at import time
 * (`assert_canonical_registry`), the frontend reads them from the API, and
 * `src/test/no-duplicate-registry.test.ts` fails the build if a model id or
 * display name literal appears anywhere in frontend source. A hardcoded list
 * here would be a second registry that can silently drift from the real one —
 * precisely the failure that guard exists to prevent.
 *
 * So the file keeps the property the brief actually wants: **everything
 * variable lives in one place.** Families, the metric, the race constants and
 * the rule that assigns a model to a family are all here and nowhere else.
 * `resolveModels()` turns whatever the API returns into `ModelDef[]`, so the
 * race works for three models or twenty without touching a component.
 */

export type Family = { id: string; label: string; color: string };

export type ModelDef = {
  id: string;
  name: string; // shown on the row
  family: string; // Family.id — drives bar colour
  /** Non-registry baselines. They race, and can never be champion. */
  isBaseline: boolean;
};

/**
 * Four families, by algorithm class. Colour encodes family so the eye can
 * follow a bar as it overtakes; it never encodes rank.
 *
 * Mid-saturation hues chosen to hold up in both themes — the app ships a dark
 * mode and a pale pastel would vanish on the light surface while a neon would
 * glare on the dark one.
 */
export const FAMILIES: Family[] = [
  { id: 'arima', label: 'ARIMA family', color: '#3D6FD4' },
  { id: 'smoothing', label: 'Exponential smoothing', color: '#0D8C86' },
  { id: 'ml', label: 'Machine learning', color: '#7A5AD6' },
  { id: 'baseline', label: 'Baselines', color: '#8A8F98' },
];

/**
 * Which family a model belongs to, decided from the server's own identifiers.
 *
 * Deliberately pattern-based rather than a lookup table: a table keyed by model
 * id would be the duplicate registry this file exists to avoid, and would go
 * stale the moment the backend renamed anything.
 */
export function familyOf(modelId: string, isBaseline: boolean): string {
  if (isBaseline) return 'baseline';
  const id = modelId.toLowerCase();
  if (id.includes('arima') || id.includes('sarim')) return 'arima';
  if (id.includes('exp_') || id.includes('smooth')) return 'smoothing';
  return 'ml';
}

/** What the bars race on. */
export const METRIC = {
  key: 'accuracy',
  label: 'Accuracy',
  direction: 'higher' as 'higher' | 'lower',
  format: (v: number) => v.toFixed(1),
  suffix: '%',
  /** Only used when direction is 'lower'. */
  worstCase: 100,
};

/**
 * Bars always grow toward the winner.
 *
 * With a 'lower is better' metric — loss, RMSE, MAPE — a bar drawn from the raw
 * value would make the worst model longest and the race would read backwards.
 * Converting once at the boundary keeps every downstream comparison a plain
 * descending sort, while the number at the bar tip still shows the raw value.
 */
export const toRaceValue = (raw: number): number =>
  METRIC.direction === 'higher' ? raw : Math.max(0, 1 - raw / METRIC.worstCase);

/** Timing and geometry. The stage derives its height from the field size. */
export const race = {
  rowHeight: 32,
  reorderMs: 750,
  reorderEase: 'cubic-bezier(.22,1,.36,1)',
  smoothing: 0.12,
  headroom: 1.04,
  settleHoldMs: 300,
  /** Bars hold this many pixels so a row reads as present, not empty. */
  minBarPx: 2,
  /** Space kept at the right of the track for the value that rides the bar
   *  tip, so a full-length leader cannot push its own number off the edge. */
  valueGutterPx: 62,
  /** Below this the field is too tall for one screen, so rows compress
   *  instead of introducing a scrollbar. */
  maxStagePx: 560,
  /** Compression floor: a row shorter than this cannot hold a readable name
   *  and value, so the stage is allowed to grow instead. */
  minRowPx: 22,
};

/** Row height that keeps every model on screen without scrolling.
 *
 *  Rows compress rather than the stage scrolling — a race you have to scroll
 *  is not a race. Compression stops at `minRowPx`, because below that the name
 *  and the value stop being legible and an unreadable row is worse than a
 *  taller stage. That floor binds only past about twenty-five models; across
 *  the three-to-twenty range this is built for, every field fits. */
export function rowHeightFor(count: number): number {
  if (count <= 0) return race.rowHeight;
  return Math.min(race.rowHeight, Math.max(race.minRowPx, Math.floor(race.maxStagePx / count)));
}

/** Turn API rows into the race's own shape. */
export function resolveModels(
  rows: Array<{ model_id: string; display_name: string; is_baseline: boolean }>,
): ModelDef[] {
  return rows.map((row) => ({
    id: row.model_id,
    name: row.display_name,
    family: familyOf(row.model_id, row.is_baseline),
    isBaseline: row.is_baseline,
  }));
}

export function familyColor(familyId: string): string {
  return FAMILIES.find((f) => f.id === familyId)?.color ?? FAMILIES[0]?.color ?? '#3D6FD4';
}

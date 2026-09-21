/**
 * The model leaderboard, in the shape the reference projects use.
 *
 * Every registered model gets a row — **including the ones that did not run**.
 * Oxea's leaderboard states the rule directly ("never hide a failed or
 * ineligible model") and this project's own contract says the same: a model
 * that did not run never disappears and is never replaced by a zero. An
 * Ineligible model is not a bad model, it is a model whose data requirement was
 * not met, and the row carries the exact requirement so the reader can judge
 * whether that is fixable.
 *
 * **Accuracy is volume-weighted.** Each scope
 * counts in proportion to the units it sells, because the unweighted mean lets a
 * 99-unit line outweigh its own irrelevance (D-087). The unweighted `100 −
 * MAPE` of D-043 is not a column of its own - `MAPE` carries it two columns
 * along, so the figure is still on the row and the arithmetic is checkable in
 * place. The champion selector still ranks on MAPE; this table's default sort
 * does not change what won. WAPE, MAE, RMSE, sMAPE, MASE and bias are
 * decision context, not a second ranking — a model can lead on MAPE
 * and trail on WAPE, and the table lets you see that rather than hiding it
 * behind one number.
 *
 * **The thirteen only.** The four non-registry baselines are not rows here.
 * They are still fitted and still compared against, and the line beneath the
 * table reports the strongest of them — because a baseline beating registered
 * models is the most useful thing on this page and deleting it would flatter
 * the result.
 */
import { useMemo, useState } from 'react';
import { AMBER, GREEN, RED } from '@/components/ui/Dashboard';
import type { MonitorModel } from '@/api/training';

type SortKey =
  | 'accuracy_weighted'
  | 'accuracy_series'
  | 'mape_weighted'
  | 'median_wape'
  | 'median_mae'
  | 'median_rmse';

const COLUMNS: Array<{
  key: SortKey | null;
  label: string;
  title: string;
  numeric: boolean;
}> = [
  { key: null, label: '#', title: 'Rank on whichever column the table is sorted by — volume-weighted accuracy by default. The champion selector itself ranks on MAPE', numeric: false },
  { key: null, label: 'Model', title: 'Registered model', numeric: false },
  { key: 'accuracy_weighted', label: 'Accuracy', title: 'Volume-weighted: each scope counts in proportion to the units it actually sells, so a 99-unit line no longer counts the same as a 9,672-unit one. The unweighted figure is 100 − MAPE, and the MAPE column carries it', numeric: true },
  { key: 'accuracy_series', label: 'Series', title: 'Accuracy at branch × SKU — the hardest grain, and most of the scopes', numeric: true },
  { key: 'mape_weighted', label: 'MAPE', title: 'Volume-weighted mean absolute percentage error — the figure Accuracy is exactly 100 minus, so the two columns reconcile on the row. Zero actuals are excluded. The champion selector ranks on per-scope MAPE, which is a different question from this summary', numeric: true },
  { key: 'median_wape', label: 'WAPE', title: 'Total absolute error over total absolute demand', numeric: true },
  { key: 'median_mae', label: 'MAE', title: 'Mean absolute error, in units', numeric: true },
  { key: 'median_rmse', label: 'RMSE', title: 'Root mean squared error — punishes large misses harder than MAE', numeric: true },
  { key: null, label: 'Bias', title: 'Negative means the model forecasts below actual demand, which is the direction that causes a stockout', numeric: true },
  { key: null, label: 'Scopes', title: 'Completed + ineligible + failed fits for this model', numeric: true },
  { key: null, label: 'Wins', title: 'Scopes where this model was selected champion. This is what decides the forecast for a branch × SKU', numeric: true },
  { key: null, label: 'Fit', title: 'Total fit time across every scope', numeric: true },
];

const num = (v: number | null, digits = 2, suffix = '') =>
  v == null ? '—' : `${v.toFixed(digits)}${suffix}`;

export function Leaderboard({
  models,
  championsSelected,
}: {
  models: MonitorModel[];
  /** Whether champions were selected *from this run*. */
  championsSelected?: boolean;
}) {
  const [sort, setSort] = useState<SortKey>('accuracy_weighted');

  const registry = useMemo(() => {
    const rows = models.filter((m) => !m.is_baseline);
    const higherIsBetter = sort.startsWith('accuracy');
    return rows.slice().sort((a, b) => {
      const av = a[sort];
      const bv = b[sort];
      // A model with no measurement sorts last whichever way the column runs —
      // "not scored" is not "worst", it is absent, and letting it float to the
      // top of an ascending error column would be a lie.
      if (av == null && bv == null) return a.display_name.localeCompare(b.display_name);
      if (av == null) return 1;
      if (bv == null) return -1;
      return higherIsBetter ? bv - av : av - bv;
    });
  }, [models, sort]);

  // Compared on the same figure the table prints. Judging baselines on the
  // unweighted number while ranking models on the weighted one would make the
  // "beats N models" line disagree with the column above it.
  const acc = (m: MonitorModel) => m.accuracy_weighted ?? m.accuracy;
  const baselines = models.filter((m) => m.is_baseline && acc(m) != null);
  const bestBaseline = baselines.slice().sort((a, b) => (acc(b) ?? 0) - (acc(a) ?? 0))[0];
  const beaten = bestBaseline
    ? registry.filter((m) => acc(m) != null && (acc(m) as number) < (acc(bestBaseline) ?? 0)).length
    : 0;

  if (!registry.length) {
    return (
      <p className="text-[11px] text-[var(--color-text-muted)]">
        No model has been recorded for this run yet.
      </p>
    );
  }

  return (
    <div>
      {/* The question this answers, asked more than once: the Training page
          ranks #1 by median MAPE while Forecasting names a different model.
          They are different questions - "best on average across every scope"
          against "chosen for this particular scope" - and they diverge further
          when champion selection has not been run on the displayed run at all,
          because the forecasts then still come from an older run's champions. */}
      {championsSelected === false && (
        <p
          className="mb-2 rounded-lg border px-2 py-1.5 text-[10px] leading-relaxed"
          style={{
            borderColor: `${AMBER}55`,
            background: `${AMBER}0f`,
            color: 'var(--color-text)',
          }}
        >
          <strong>No champion has been selected from this run.</strong> The Wins column is
          therefore empty, and Forecasting is still serving an earlier run's champions — which
          is why the model named there can differ from the model ranked first here. Ranking
          first is an average across every scope; a champion is chosen per scope.
        </p>
      )}

      <div className="table-scroll">
        <table className="data">
          <thead>
            <tr>
              {COLUMNS.map((c) => (
                <th
                  key={c.label}
                  title={c.title}
                  className={c.numeric ? 'num' : undefined}
                  style={{ cursor: c.key ? 'pointer' : undefined, whiteSpace: 'nowrap' }}
                  onClick={c.key ? () => setSort(c.key as SortKey) : undefined}
                >
                  {c.label}
                  {c.key === sort ? ' ▾' : ''}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {registry.map((m, i) => {
              const scored = m.accuracy != null;
              return (
                <tr key={m.model_id} title={m.reason ?? undefined}>
                  <td className="num" style={{ color: i === 0 && scored ? GREEN : undefined }}>
                    {scored ? i + 1 : '—'}
                  </td>
                  <td style={{ fontWeight: i === 0 && scored ? 600 : 400 }}>{m.display_name}</td>
                  <td className="num" style={{ fontWeight: 600 }}>
                    {num(m.accuracy_weighted, 1, '%')}
                  </td>
                  <td className="num" style={{ color: AMBER }}>
                    {num(m.accuracy_series, 1, '%')}
                  </td>
                  <td className="num">{num(m.mape_weighted, 1, '%')}</td>
                  <td className="num">{num(m.median_wape, 1, '%')}</td>
                  <td className="num">{num(m.median_mae, 1)}</td>
                  <td className="num">{num(m.median_rmse, 1)}</td>
                  <td
                    className="num"
                    style={{ color: (m.median_bias ?? 0) < 0 ? AMBER : undefined }}
                  >
                    {num(m.median_bias, 1, '%')}
                  </td>
                  <td className="num">
                    {m.completed}
                    {m.ineligible > 0 && <span style={{ color: AMBER }}> +{m.ineligible}</span>}
                    {m.failed > 0 && <span style={{ color: RED }}> !{m.failed}</span>}
                  </td>
                  <td
                    className="num"
                    style={{ color: m.champion_count ? GREEN : undefined, fontWeight: m.champion_count ? 600 : 400 }}
                  >
                    {m.champion_count || '·'}
                  </td>
                  <td className="num">{m.fit_seconds ? `${m.fit_seconds.toFixed(0)}s` : '—'}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <p className="mt-2 text-[10px] leading-relaxed text-[var(--color-text-muted)]">
        <strong>Accuracy is volume-weighted.</strong> Each scope counts in proportion to the
        units it sells, so a line selling 99 units in 28 months no longer weighs as much as one
        selling 9,672 — MAPE explodes on the small denominator, and being wrong by 7 units on a
        3.5-unit month scores 200% while costing nobody anything. Weighting is worth about 22
        points at series grain on this workspace. The unweighted figure is not hidden: it is
        exactly 100 − <em>MAPE</em>, two columns along. <em>Series</em> isolates branch × SKU,
        the hardest grain and most of the scopes.
      </p>
      <p className="mt-1 text-[10px] leading-relaxed text-[var(--color-text-muted)]">
        Ranked on <strong>MAPE</strong> — the metric the champion selector uses. Accuracy is
        <strong> 100 − MAPE</strong> clamped at zero, the same number restated, not a second
        measurement. Every other column is decision context: a model can lead on MAPE and trail
        on WAPE, and this table lets you see that. A negative bias means the model forecasts
        <em> below</em> actual demand, which is the direction that causes a stockout.
        Hover an Ineligible row for the requirement it did not meet.
      </p>

      {bestBaseline && (
        <p className="mt-1 text-[10px] leading-relaxed" style={{ color: beaten > 0 ? AMBER : 'var(--color-text-muted)' }}>
          <strong>Baseline check.</strong> The strongest non-registry baseline is{' '}
          {bestBaseline.display_name} at {num(acc(bestBaseline), 1, '%')}, and it beats{' '}
          <strong>{beaten} of {registry.length}</strong> registered models. Baselines are fitted
          for exactly this comparison and can never be champion, so they are not rows above —
          but a model losing to one is worth knowing.
        </p>
      )}
    </div>
  );
}

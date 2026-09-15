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
 * **Ranked on MAPE.** `champion_primary_metric` is `mape`, accuracy is
 * `100 − MAPE` clamped at zero (D-043), and both are shown side by side so the
 * relationship is never a matter of trust. WAPE, MAE, RMSE, sMAPE, MASE and
 * bias are decision context, not a second ranking — a model can lead on MAPE
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
  | 'accuracy'
  | 'accuracy_aggregate'
  | 'accuracy_series'
  | 'median_mape'
  | 'median_wape'
  | 'median_mae'
  | 'median_rmse';

const COLUMNS: Array<{
  key: SortKey | null;
  label: string;
  title: string;
  numeric: boolean;
}> = [
  { key: null, label: '#', title: 'Rank on MAPE, the metric the champion selector uses', numeric: false },
  { key: null, label: 'Model', title: 'Registered model', numeric: false },
  { key: 'accuracy', label: 'Accuracy', title: '100 − MAPE across every scope. A blend of two very different grains — see the two columns beside it', numeric: true },
  { key: 'accuracy_aggregate', label: 'Agg.', title: 'Accuracy at national, region, branch and segment totals — where the models are strong', numeric: true },
  { key: 'accuracy_series', label: 'Series', title: 'Accuracy at branch × SKU — the hardest grain, and most of the scopes', numeric: true },
  { key: 'median_mape', label: 'MAPE', title: 'Mean absolute percentage error. The ranking metric. Zero actuals are excluded', numeric: true },
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
  const [sort, setSort] = useState<SortKey>('median_mape');

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

  const baselines = models.filter((m) => m.is_baseline && m.accuracy != null);
  const bestBaseline = baselines.slice().sort((a, b) => (b.accuracy ?? 0) - (a.accuracy ?? 0))[0];
  const beaten = bestBaseline
    ? registry.filter((m) => m.accuracy != null && m.accuracy < (bestBaseline.accuracy ?? 0)).length
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
                    {num(m.accuracy, 1, '%')}
                  </td>
                  <td className="num" style={{ color: GREEN }}>
                    {num(m.accuracy_aggregate, 1, '%')}
                  </td>
                  <td className="num" style={{ color: AMBER }}>
                    {num(m.accuracy_series, 1, '%')}
                  </td>
                  <td className="num">{num(m.median_mape, 1, '%')}</td>
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
        <strong>Accuracy is a blend of two grains, and the split matters more than the
        blend.</strong> A national or branch total forecasts far better than a single
        branch × SKU month does — <em>Agg.</em> and <em>Series</em> separate them. Most scopes
        in a run are branch × SKU, so the blended figure sits close to the harder one and
        understates how the models do at the levels most planning actually happens on.
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
          {bestBaseline.display_name} at {num(bestBaseline.accuracy, 1, '%')}, and it beats{' '}
          <strong>{beaten} of {registry.length}</strong> registered models. Baselines are fitted
          for exactly this comparison and can never be champion, so they are not rows above —
          but a model losing to one is worth knowing.
        </p>
      )}
    </div>
  );
}

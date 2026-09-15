import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { fetchCurrentPanel, isPanelBuildRunning, panelKeys, startPanelBuild } from '@/api/panel';
import { Card } from '@/components/ui/Card';
import { EmptyState, ErrorState } from '@/components/ui/States';
import { useToast } from '@/components/ui/Toast';
import { ApiError } from '@/api/client';
import { formatInt, formatPct, formatSeconds } from '@/components/ui/format';

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' ? (value as Record<string, unknown>) : {};
}

/** The modelling panel and the direct multi-horizon frames built from it. */
export function PanelPanel() {
  const queryClient = useQueryClient();
  const toast = useToast();

  const { data, isError, error, refetch } = useQuery({
    queryKey: panelKeys.current,
    queryFn: fetchCurrentPanel,
    retry: false,
    refetchInterval: (query) => (isPanelBuildRunning(query.state.data?.status) ? 4000 : false),
  });

  const build = useMutation({
    // Sep 2025 is the mandated training cut: validate Oct 2025 - Mar 2026.
    mutationFn: () => startPanelBuild({ training_cut_period: '2025-09' }),
    onSuccess: () => {
      toast.notify('Panel build started. It takes about two minutes.', 'info');
      void queryClient.invalidateQueries({ queryKey: panelKeys.current });
    },
    onError: (mutationError) =>
      toast.notify(
        mutationError instanceof ApiError
          ? mutationError.message
          : 'Could not start the panel build.',
        'error',
      ),
  });

  const buildButton = (
    <button
      type="button"
      className="btn btn-primary"
      onClick={() => build.mutate()}
      disabled={build.isPending}
    >
      {build.isPending ? 'Starting…' : 'Build panel'}
    </button>
  );

  if (isError) {
    if (error instanceof ApiError && error.status === 404) {
      return (
        <Card title="Modelling panel" actions={buildButton}>
          <EmptyState title="No panel built yet">
            The panel is branch &times; SKU &times; month with explicit zeros for
            active series, a labelled target source per row, and leakage-safe
            direct multi-horizon features. It needs a completed preprocessing run.
          </EmptyState>
        </Card>
      );
    }
    return (
      <Card title="Modelling panel">
        <ErrorState error={error} onRetry={() => refetch()} />
      </Card>
    );
  }

  if (!data) return null;

  const running = isPanelBuildRunning(data.status);
  const summary = asRecord(data.summary);
  const sources = asRecord(summary.target_source_rows);
  const universe = asRecord(summary.series_universe);
  const sparsity = asRecord(summary.sparsity);
  const features = asRecord(summary.feature_manifest);
  const range = Array.isArray(summary.period_range) ? (summary.period_range as string[]) : [];

  return (
    <div className="stack">
      <Card
        title="Modelling panel"
        subtitle={`${data.status}${data.duration_seconds ? ` · ${formatSeconds(data.duration_seconds)}` : ''}${data.training_cut_period ? ` · cut ${data.training_cut_period}` : ''}`}
        actions={
          <span
            className={`pill ${
              data.status === 'completed'
                ? 'pill-ok'
                : data.status === 'failed'
                  ? 'pill-crit'
                  : 'pill-info'
            }`}
          >
            {data.status}
          </span>
        }
      >
        {running && (
          <div role="status" aria-live="polite">
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
              <span>{data.stage_detail ?? 'Working'}</span>
              <span className="mono">{data.progress_pct.toFixed(0)}%</span>
            </div>
            <div
              style={{ height: 6, background: 'var(--surface-3)', borderRadius: 3, overflow: 'hidden' }}
              role="progressbar"
              aria-valuenow={Math.round(data.progress_pct)}
              aria-valuemin={0}
              aria-valuemax={100}
            >
              <div
                style={{
                  width: `${data.progress_pct}%`,
                  height: '100%',
                  background: 'var(--accent)',
                  transition: 'width .4s ease',
                }}
              />
            </div>
          </div>
        )}

        {data.failure_reason && (
          <div className="callout crit">
            <div className="h">Panel build failed</div>
            <p className="mono" style={{ fontSize: 12 }}>
              {data.failure_reason}
            </p>
          </div>
        )}

        {data.status === 'completed' && (
          <>
            <div className="tiles">
              <div className="tile">
                <div className="k">Panel rows</div>
                <div className="v">{formatInt(data.panel_rows)}</div>
                <div className="s">branch × SKU × month</div>
              </div>
              <div className="tile">
                <div className="k">Series</div>
                <div className="v">{formatInt(data.series_count)}</div>
                <div className="s">{data.period_count} monthly periods</div>
              </div>
              <div className="tile">
                <div className="k">Observed rows</div>
                <div className="v">{formatInt(data.observed_rows)}</div>
                <div className="s">a real observation</div>
              </div>
              <div className="tile is-warn">
                <div className="k">Materialised zeros</div>
                <div className="v">{formatInt(data.materialised_zero_rows)}</div>
                <div className="s">true zero, not missing data</div>
              </div>
              <div className="tile is-crit">
                <div className="k">Censored rows</div>
                <div className="v">{formatInt(data.censored_rows)}</div>
                <div className="s">demand was at least this</div>
              </div>
              <div className="tile">
                <div className="k">Training rows</div>
                <div className="v">{formatInt(data.training_rows)}</div>
                <div className="s">
                  {data.feature_count} features · horizons {data.horizons}
                </div>
              </div>
            </div>

            <div className="callout" style={{ marginTop: 'var(--sp-4)' }}>
              <div className="h">A zero is a real observation, not a gap</div>
              <p>
                {formatInt(data.materialised_zero_rows)} rows were materialised as
                explicit zeros for months an active series recorded no demand, and
                each carries <code>value_unavailable_reason = true_zero</code>. No
                series gets invented history before its first observation, and
                trailing zeros are kept because they are the obsolescence signal.
              </p>
            </div>

            {(sources.order !== undefined || sources.sales_proxy !== undefined) && (
              <div className="callout warn" style={{ marginTop: 'var(--sp-3)' }}>
                <div className="h">Two target sources, never treated as equivalent</div>
                <p>
                  <strong>{formatInt(sources.order as number)}</strong> rows carry the
                  true order book; <strong>{formatInt(sources.sales_proxy as number)}</strong>{' '}
                  carry the labelled <code>sales_proxy</code> — invoiced sales, a
                  censored signal recording what was available to sell, not what was
                  wanted. Every row says which it is.
                  {range.length === 2 && (
                    <>
                      {' '}
                      Panel span <span className="mono">{range[0]} → {range[1]}</span>.
                    </>
                  )}
                </p>
              </div>
            )}

            {universe.panel_series !== undefined && (
              <div className="callout" style={{ marginTop: 'var(--sp-3)' }}>
                <div className="h">The panel universe is not the 63,210 control</div>
                <p>
                  The panel holds <strong>{formatInt(universe.panel_series as number)}</strong>{' '}
                  demand-bearing branch × SKU series. The{' '}
                  {formatInt(universe.sales_control_series as number)} control counts
                  the sales file alone and remains a check on the canonical key.{' '}
                  {formatInt(universe.stock_only_pairs_excluded as number)} stock-only
                  pairs are excluded — they have no demand history to forecast from,
                  and stay visible in the stock position.
                </p>
              </div>
            )}

            {sparsity.zero_cell_share !== undefined && (
              <div className="table-scroll" style={{ marginTop: 'var(--sp-4)' }}>
                <table className="data" data-testid="sparsity-table">
                  <thead>
                    <tr>
                      <th>Sparsity measure</th>
                      <th className="num">Value</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr>
                      <td>Zero cells</td>
                      <td className="num">
                        {formatPct(sparsity.zero_cell_share as number, 1, 'ratio')}
                      </td>
                    </tr>
                    <tr>
                      <td>Series with one non-zero month</td>
                      <td className="num">
                        {formatInt(sparsity.series_with_one_nonzero_month as number)}
                      </td>
                    </tr>
                    <tr>
                      <td>Series with 12+ non-zero months</td>
                      <td className="num">
                        {formatInt(sparsity.series_with_12_plus_nonzero_months as number)}
                      </td>
                    </tr>
                    <tr>
                      <td>Median average demand interval</td>
                      <td className="num">
                        {sparsity.median_adi === null || sparsity.median_adi === undefined
                          ? '—'
                          : (sparsity.median_adi as number).toFixed(1)}
                      </td>
                    </tr>
                    <tr>
                      <td>Median CV² of non-zero sizes</td>
                      <td className="num">
                        {sparsity.median_cv_squared === null ||
                        sparsity.median_cv_squared === undefined
                          ? '—'
                          : (sparsity.median_cv_squared as number).toFixed(3)}
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            )}

            {features.max_lookback_months !== undefined && (
              <p className="dim" style={{ marginTop: 'var(--sp-3)', fontSize: 12 }}>
                {formatInt(features.feature_count as number)} features, deepest
                lookback {String(features.max_lookback_months)} months. Horizon is a
                feature, so one fitted model answers all of{' '}
                {data.horizons.split(',').join(', ')} — no recursive chaining.
              </p>
            )}
          </>
        )}
      </Card>
    </div>
  );
}

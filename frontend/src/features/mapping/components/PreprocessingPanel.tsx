import { useQuery } from '@tanstack/react-query';
import { fetchPreprocessing, isPreprocessingRunning, mappingKeys } from '@/api/mappings';
import { Card } from '@/components/ui/Card';
import { EmptyState, ErrorState } from '@/components/ui/States';
import { ApiError } from '@/api/client';
import { formatInt, formatSeconds } from '@/components/ui/format';

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' ? (value as Record<string, unknown>) : {};
}

export function PreprocessingPanel({ mappingId }: { mappingId: string }) {
  const { data, isError, error, refetch } = useQuery({
    queryKey: mappingKeys.preprocessing(mappingId),
    queryFn: () => fetchPreprocessing(mappingId),
    retry: false,
    refetchInterval: (query) =>
      isPreprocessingRunning(query.state.data?.status) ? 4000 : false,
  });

  if (isError) {
    // A 404 means "not run yet", which is a state rather than a failure.
    if (error instanceof ApiError && error.status === 404) {
      return (
        <Card title="Preprocessing">
          <EmptyState title="Not preprocessed yet">
            Run preprocessing to build the branch and product dimensions and the
            monthly facts. It re-streams all five sources.
          </EmptyState>
        </Card>
      );
    }
    return (
      <Card title="Preprocessing">
        <ErrorState error={error} onRetry={() => refetch()} />
      </Card>
    );
  }

  if (!data) return null;

  const running = isPreprocessingRunning(data.status);
  const summary = asRecord(data.summary);
  const orderFact = asRecord(summary.order_fact);
  const salesFact = asRecord(summary.sales_fact);
  const stock = asRecord(summary.stock_position);
  const periodRange = Array.isArray(summary.period_range)
    ? (summary.period_range as string[])
    : [];
  const orderPeriods = Array.isArray(summary.order_periods)
    ? (summary.order_periods as string[])
    : [];
  const salesPeriods = Array.isArray(summary.sales_periods)
    ? (summary.sales_periods as string[])
    : [];
  const warnings = Array.isArray(summary.warnings) ? (summary.warnings as string[]) : [];

  return (
    <div className="stack">
      <Card
        title="Preprocessing"
        subtitle={`${data.status}${data.duration_seconds ? ` · ${formatSeconds(data.duration_seconds)}` : ''}`}
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
            <div className="h">Preprocessing failed</div>
            <p className="mono" style={{ fontSize: 12 }}>
              {data.failure_reason}
            </p>
          </div>
        )}

        {data.status === 'completed' && (
          <>
            <div className="tiles">
              <div className="tile">
                <div className="k">Branch dimension</div>
                <div className="v">{formatInt(data.branch_dim_rows)}</div>
              </div>
              <div className="tile">
                <div className="k">Product dimension</div>
                <div className="v">{formatInt(data.product_dim_rows)}</div>
              </div>
              <div className="tile">
                <div className="k">Order fact cells</div>
                <div className="v">{formatInt(data.order_fact_rows)}</div>
                <div className="s">branch × SKU × month</div>
              </div>
              <div className="tile">
                <div className="k">Sales fact cells</div>
                <div className="v">{formatInt(data.sales_fact_rows)}</div>
                <div className="s">the labelled proxy source</div>
              </div>
              <div className="tile">
                <div className="k">Stock positions</div>
                <div className="v">{formatInt(data.stock_position_rows)}</div>
              </div>
              <div className="tile">
                <div className="k">Distinct series</div>
                <div className="v">{formatInt(data.distinct_series)}</div>
                <div className="s">{data.distinct_periods} monthly periods</div>
              </div>
            </div>

            <div className="callout" style={{ marginTop: 'var(--sp-4)' }}>
              <div className="h">
                Two target sources, deliberately kept separate
              </div>
              <p>
                Order periods {orderPeriods.length > 0 && (
                  <span className="mono">
                    {orderPeriods[0]} → {orderPeriods[orderPeriods.length - 1]}
                  </span>
                )}{' '}
                carry the true target. Sales periods{' '}
                {salesPeriods.length > 0 && (
                  <span className="mono">
                    {salesPeriods[0]} → {salesPeriods[salesPeriods.length - 1]}
                  </span>
                )}{' '}
                carry the censored proxy. Merging them now would erase which
                source each period came from, so the panel assigns{' '}
                <code>target_source</code> in Phase 4.
                {periodRange.length === 2 && (
                  <>
                    {' '}
                    Combined span:{' '}
                    <span className="mono">
                      {periodRange[0]} → {periodRange[1]}
                    </span>{' '}
                    ({data.distinct_periods} periods).
                  </>
                )}
              </p>
            </div>

            {orderFact.censored_cells !== undefined && (
              <div className="callout warn" style={{ marginTop: 'var(--sp-3)' }}>
                <div className="h">Censoring</div>
                <p>
                  {formatInt(orderFact.censored_cells as number)} of{' '}
                  {formatInt(orderFact.cells as number)} order cells were not
                  fully served, so true demand there was <em>at least</em> what
                  was ordered and possibly more.
                </p>
              </div>
            )}

            {warnings.length > 0 && (
              <div className="callout warn" style={{ marginTop: 'var(--sp-3)' }}>
                <div className="h">Warnings</div>
                {warnings.map((warning) => (
                  <p key={warning}>{warning}</p>
                ))}
              </div>
            )}

            {stock.negative_source_rows !== undefined && (
              <p className="dim" style={{ marginTop: 'var(--sp-3)', fontSize: 12 }}>
                Stock: {formatInt(stock.cells_with_stock as number)} of{' '}
                {formatInt(stock.rows as number)} cells hold stock;{' '}
                {formatInt(stock.negative_source_rows as number)} negative source
                row(s) preserved as visible exceptions and excluded from usable
                stock.
              </p>
            )}

            {salesFact.transposition_corrected !== undefined && (
              <p className="dim" style={{ marginTop: 4, fontSize: 12 }}>
                Sales: transposition corrected in{' '}
                <span className="mono">
                  {(salesFact.transposition_corrected as string[]).join(', ') || 'no sheet'}
                </span>
                .
              </p>
            )}
          </>
        )}
      </Card>

      {data.status === 'completed' && data.artifacts && (
        <Card title="Artifacts" subtitle="Parquet, with a versioned manifest alongside">
          <div className="table-scroll">
            <table className="data" data-testid="artifacts-table">
              <thead>
                <tr>
                  <th>Table</th>
                  <th>Path</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(data.artifacts).map(([name, path]) => (
                  <tr key={name}>
                    <td className="mono">{name}</td>
                    <td className="mono dim" style={{ fontSize: 11 }}>
                      {path}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}

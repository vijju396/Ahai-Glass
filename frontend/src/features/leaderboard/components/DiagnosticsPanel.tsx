/**
 * Per-model diagnostics: folds, actual-versus-predicted, residuals, and
 * horizon-level performance.
 *
 * A model that did not run renders its **reason**, not an empty chart frame
 * that could be mistaken for a flat forecast. The backend distinguishes two
 * cases and so does this panel: a model that never produced predictions, and a
 * model that completed under a run that did not persist them.
 */
import { Chart, useChartColors } from '@/components/charts/Chart';
import { useQuery } from '@tanstack/react-query';
import { fetchDiagnostics, leaderboardKeys } from '@/api/leaderboard';
import { Card } from '@/components/ui/Card';
import { EmptyState, ErrorState, LoadingBlock } from '@/components/ui/States';
import { formatInt, formatSeconds } from '@/components/ui/format';
import { Explain } from '@/components/ui/Explain';

interface Props {
  modelId: string;
  scopeLevel: string;
  scopeKey: string;
  onClose: () => void;
}

export function DiagnosticsPanel({ modelId, scopeLevel, scopeKey, onClose }: Props) {
  const c = useChartColors();
  const query = { scope_level: scopeLevel, scope_key: scopeKey };
  const { data, isPending, isError, error, refetch } = useQuery({
    queryKey: leaderboardKeys.diagnostics(modelId, query),
    queryFn: () => fetchDiagnostics(modelId, query),
    retry: false,
  });

  const labels = (data?.points ?? []).map(
    (point) => `${point.period ?? ''} h${point.horizon ?? ''}`,
  );

  const actualVsPredicted = {
    grid: { left: 64, right: 16, top: 30, bottom: 64 },
    tooltip: { trigger: 'axis' },
    legend: { data: ['Actual', 'Predicted'], top: 0 },
    xAxis: { type: 'category', data: labels, axisLabel: { rotate: 32, fontSize: 10 } },
    yAxis: { type: 'value', name: 'Ordered qty', nameGap: 48, nameLocation: 'middle' },
    series: [
      {
        name: 'Actual',
        type: 'line',
        data: (data?.points ?? []).map((point) => point.actual),
        itemStyle: { color: c.s1 },
      },
      {
        name: 'Predicted',
        type: 'line',
        data: (data?.points ?? []).map((point) => point.predicted),
        itemStyle: { color: c.s2 },
      },
    ],
  };

  const residuals = {
    grid: { left: 64, right: 16, top: 20, bottom: 64 },
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: labels, axisLabel: { rotate: 32, fontSize: 10 } },
    yAxis: {
      type: 'value',
      name: 'Predicted − actual',
      nameGap: 48,
      nameLocation: 'middle',
    },
    series: [
      {
        type: 'bar',
        data: (data?.points ?? []).map((point) => point.residual),
        itemStyle: { color: c.s4 },
      },
    ],
  };

  return (
    <Card
      title={`Diagnostics — ${data?.display_name ?? modelId}`}
      subtitle={`${scopeLevel}/${scopeKey}`}
      actions={
        <button type="button" className="btn" onClick={onClose}>
          Close
        </button>
      }
    >
      {isPending && <LoadingBlock rows={6} label="Loading diagnostics" />}
      {isError && <ErrorState error={error} onRetry={() => refetch()} />}
      {data && !data.diagnostics_available && (
        <EmptyState title="No predictions to chart">
          {data.unavailable_reason}
        </EmptyState>
      )}
      {data && data.diagnostics_available && (
        <>
          <h3>Actual versus predicted</h3>
          <Chart option={actualVsPredicted} height={300} label="Out-of-sample actual and predicted quantities by validation point" />
          <Explain variant="note">
            Out-of-sample points from every completed origin. Nothing here is a
            fitted value on training data.
          </Explain>

          <h3 style={{ marginTop: 'var(--sp-5)' }}>Residuals</h3>
          <Chart option={residuals} height={240} label="Backtest residuals: positive values indicate over-forecasting" />
          <Explain variant="note">
            Positive means the model over-forecast. These are the same residuals
            the q80/q90/q95 calibration is built from.
          </Explain>

          <h3 style={{ marginTop: 'var(--sp-5)' }}>Horizon-level performance</h3>
          <div className="table-scroll">
            <table className="data" data-testid="horizon-table">
              <thead>
                <tr>
                  <th className="num">Horizon</th>
                  <th className="num">Points</th>
                  <th className="num">MAE</th>
                  <th className="num">WAPE %</th>
                  <th className="num">Bias</th>
                  <th className="num">Zero actuals</th>
                </tr>
              </thead>
              <tbody>
                {data.horizon_performance.map((row) => (
                  <tr key={String(row.horizon)}>
                    <td className="num">{row.horizon ?? '—'}</td>
                    <td className="num">{formatInt(row.points)}</td>
                    <td className="num">{formatInt(row.mae)}</td>
                    <td className="num">
                      {row.wape === null ? '—' : row.wape.toFixed(3)}
                    </td>
                    <td className="num">{formatInt(row.bias)}</td>
                    <td className="num">{formatInt(row.zero_actual_points)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <h3 style={{ marginTop: 'var(--sp-5)' }}>Folds</h3>
          <div className="table-scroll">
            <table className="data" data-testid="fold-table">
              <thead>
                <tr>
                  <th>Origin</th>
                  <th>Trained through</th>
                  <th className="num">Train rows</th>
                  <th>Status</th>
                  <th className="num">Seasonal period</th>
                  <th className="num">Points</th>
                  <th className="num">Fit</th>
                  <th>Reason</th>
                </tr>
              </thead>
              <tbody>
                {data.folds.map((fold) => (
                  <tr key={`${fold.origin_name}-${fold.fold_index}`}>
                    <td>{fold.origin_name ?? '—'}</td>
                    <td className="mono">{fold.train_end_period ?? '—'}</td>
                    <td className="num">{formatInt(fold.train_rows)}</td>
                    <td>{fold.status ?? '—'}</td>
                    <td className="num">{fold.seasonal_period ?? 'none'}</td>
                    <td className="num">{formatInt(fold.point_count)}</td>
                    <td className="num">{formatSeconds(fold.fit_seconds)}</td>
                    <td>{fold.failure_reason ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {data.features && data.features.length > 0 && (
            <Explain variant="hint">
              <strong>Features used:</strong> {data.features.join(', ')}
            </Explain>
          )}
        </>
      )}
    </Card>
  );
}

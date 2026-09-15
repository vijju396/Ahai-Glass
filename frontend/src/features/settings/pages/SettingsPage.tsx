/**
 * Connections & Settings.
 *
 * Read-only, deliberately. There is no write endpoint, so a planner cannot
 * silently change the random seed or the history profile behind a run that has
 * already been stored — that would make a persisted result unreproducible.
 *
 * The registered model IDs are rendered here from `GET /api/settings`, which
 * is the same backend registry `GET /api/models` serves. This page does not
 * carry its own list.
 */
import { useQuery } from '@tanstack/react-query';
import {
  exportUrl,
  fetchExportKinds,
  fetchSettings,
  operationsKeys,
} from '@/api/operations';
import { Card } from '@/components/ui/Card';
import { ErrorState, LoadingBlock } from '@/components/ui/States';
import { formatDays, formatInt, formatSeconds } from '@/components/ui/format';

export function SettingsPage() {
  const settings = useQuery({
    queryKey: operationsKeys.settings,
    queryFn: fetchSettings,
    retry: false,
  });
  const exports = useQuery({
    queryKey: operationsKeys.exports,
    queryFn: fetchExportKinds,
    retry: false,
  });

  const data = settings.data;

  return (
    <div className="stack">
      <div className="page-head">
        <div className="eyebrow">10 &middot; Connections &amp; settings</div>
        <h1>Connections &amp; Settings</h1>
        <p className="lede">
          The effective runtime configuration, read from the API. There is no
          write endpoint: changing the seed or a history profile is a deployment
          action, so a stored run stays reproducible.
        </p>
      </div>

      <Card title="AIS workspace identity" subtitle="Official AIS website identity, adapted for a readable analytics workspace">
        <div className="insight-banner"><img src="/ais-logo.png" alt="Asahi India Glass Ltd. official logo" style={{ width: 78, height: 65, objectFit: 'contain', background: '#fff', borderRadius: 6 }} /><p><strong>Demand & supply intelligence</strong><br />Corporate blue and deep navy connect this workspace to AIS. Chart colors distinguish actuals, forecasts and comparison measures. Use the theme button in the header to switch between light and dark.</p></div>
        <div className="palette-row"><span className="palette-swatch"><i style={{ background: '#005bab' }} />Corporate blue · #005BAB</span><span className="palette-swatch"><i style={{ background: '#0f2754' }} />Deep navy · #0F2754</span><span className="palette-swatch"><i style={{ background: '#fff' }} />White · #FFFFFF</span></div>
        <p className="hint">Logo and website colors sourced from <a href="https://www.aisglass.com" target="_blank" rel="noreferrer">aisglass.com</a>. Supporting chart and status colors are analytics-specific, not an official AIS brand manual.</p>
      </Card>

      {settings.isPending && (
        <Card>
          <LoadingBlock rows={6} label="Loading settings" />
        </Card>
      )}
      {settings.isError && (
        <Card>
          <ErrorState error={settings.error} onRetry={() => settings.refetch()} />
        </Card>
      )}

      {data && (
        <>
          <Card title="Runtime" subtitle={`${data.app_name} ${data.app_version}`}>
            <div className="tiles">
              <div className="tile">
                <div className="k">Environment</div>
                <div className="v" style={{ fontSize: 17 }}>
                  {data.environment}
                </div>
                <div className="s">database: {data.database_dialect}</div>
              </div>
              <div className="tile">
                <div className="k">Official models</div>
                <div className="v">{data.official_model_count}</div>
                <div className="s">
                  plus {data.baseline_method_ids.length} non-registry baselines
                </div>
              </div>
              <div className="tile">
                <div className="k">Random seed</div>
                <div className="v">{data.random_seed}</div>
                <div className="s">fixed, so a run is reproducible</div>
              </div>
              <div className="tile">
                <div className="k">MLflow</div>
                <div className="v" style={{ fontSize: 17 }}>
                  {data.mlflow_enabled ? 'enabled' : 'disabled'}
                </div>
                <div className="s">{data.mlflow_tracking_uri}</div>
              </div>
            </div>
          </Card>

          <div className="grid-2">
            <Card title="Modelling" subtitle="What governs eligibility and cost">
              <div className="table-scroll">
                <table className="data" data-testid="modelling-settings">
                  <tbody>
                    <tr>
                      <th style={{ textAlign: 'left' }}>History profile</th>
                      <td>{data.min_history_profile}</td>
                    </tr>
                    <tr>
                      <th style={{ textAlign: 'left' }}>XGBoost profile</th>
                      <td>{data.xgboost_training_profile}</td>
                    </tr>
                    <tr>
                      <th style={{ textAlign: 'left' }}>Forecast horizon</th>
                      <td>{data.forecast_horizon_months} months</td>
                    </tr>
                    <tr>
                      <th style={{ textAlign: 'left' }}>Service levels</th>
                      <td>
                        {data.service_levels.map((level) => `q${level}`).join(', ')}
                      </td>
                    </tr>
                    <tr>
                      <th style={{ textAlign: 'left' }}>Local series cap</th>
                      <td>
                        {formatInt(data.max_local_series)} by{' '}
                        {data.local_series_selection}
                      </td>
                    </tr>
                    <tr>
                      <th style={{ textAlign: 'left' }}>Per-model timeout</th>
                      <td>{formatSeconds(data.per_model_timeout_seconds)}</td>
                    </tr>
                    <tr>
                      <th style={{ textAlign: 'left' }}>LSTM timeout</th>
                      <td>{formatSeconds(data.lstm_timeout_seconds)}</td>
                    </tr>
                    <tr>
                      <th style={{ textAlign: 'left' }}>Training workers</th>
                      <td>{data.max_training_workers}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </Card>

            <Card title="Inventory policy" subtitle="What the recommendations are sized on">
              <div className="table-scroll">
                <table className="data" data-testid="inventory-settings">
                  <tbody>
                    <tr>
                      <th style={{ textAlign: 'left' }}>Review period</th>
                      <td>{formatDays(data.review_period_days)}</td>
                    </tr>
                    <tr>
                      <th style={{ textAlign: 'left' }}>Default lead time</th>
                      <td>
                        {formatDays(data.default_lead_time_days)} (used only where
                        a branch has none)
                      </td>
                    </tr>
                    <tr>
                      <th style={{ textAlign: 'left' }}>Stock snapshot</th>
                      <td>{data.stock_snapshot_date}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <p className="hint">
                Protection period = review period + branch lead time. The stock
                file is a single snapshot, which is why every recommendation is
                labelled a current-snapshot estimate.
              </p>
            </Card>
          </div>

          <Card
            title="Registered models"
            subtitle="From the backend registry — this page carries no second list"
          >
            <div className="table-scroll">
              <table className="data" data-testid="registered-models">
                <thead>
                  <tr>
                    <th className="num">#</th>
                    <th>Model ID</th>
                  </tr>
                </thead>
                <tbody>
                  {data.registered_model_ids.map((modelId, index) => (
                    <tr key={modelId}>
                      <td className="num">{index + 1}</td>
                      <td className="mono">{modelId}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="hint">
              Non-registry baselines: {data.baseline_method_ids.join(', ')}. They
              are reported for comparison and can never be champion.
            </p>
          </Card>

          <Card
            title="Structural controls"
            subtitle="The row counts every ingestion is checked against"
          >
            <div className="table-scroll">
              <table className="data" data-testid="expected-controls">
                <thead>
                  <tr>
                    <th>Control</th>
                    <th className="num">Expected</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(data.expected_controls).map(([key, value]) => (
                    <tr key={key}>
                      <td>{key.replace(/_/g, ' ')}</td>
                      <td className="num">{formatInt(value)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

          <Card title="Exports" subtitle="CSV of exactly what a page displays">
            {exports.isPending && <LoadingBlock rows={3} label="Loading export kinds" />}
            {exports.isError && (
              <ErrorState error={exports.error} onRetry={() => exports.refetch()} />
            )}
            {exports.data && (
              <>
                <div className="table-scroll">
                  <table className="data" data-testid="export-kinds">
                    <thead>
                      <tr>
                        <th>Kind</th>
                        <th>Mirrors</th>
                        <th />
                      </tr>
                    </thead>
                    <tbody>
                      {exports.data.kinds.map((item) => (
                        <tr key={item.kind}>
                          <td className="mono">{item.kind}</td>
                          <td>{item.description}</td>
                          <td>
                            <a
                              className="btn"
                              href={exportUrl(item.kind)}
                              download
                            >
                              Download CSV
                            </a>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p className="hint">{exports.data.note}</p>
              </>
            )}
          </Card>

          {data.notes.map((note) => (
            <div className="callout" key={note}>
              <p>{note}</p>
            </div>
          ))}
        </>
      )}
    </div>
  );
}
